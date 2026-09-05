"""Echte PipeWire-Anbindung.

Routing-Idee: ein Null-Sink `buschfunk-mix` ist das gemeinsame Ziel. Jede
Hardware-Quelle (Mischpult, weitere USB-Interfaces) wird per `pw-link` in
dessen Input-Ports gemischt (mehrere Links auf denselben Input-Port werden
von PipeWire automatisch summiert). Umgekehrt wird jedes erkannte
Wiedergabegerät (Monitor-Lautsprecher, Kopfhörer) per `pw-link` an die
Monitor-Ports des Mix-Sinks gehängt, bekommt also denselben fertigen Mix wie
der Icecast-Stream. Mute/Unmute und Lautstärke laufen über `wpctl` auf dem
jeweiligen Gerät - der Link bleibt bestehen, es wird nie neu verbunden.

Pegel: pro Gerät (und für den Mix selbst) läuft **ein** dauerhafter
ffmpeg-Prozess, der alle 100 ms den RMS-Pegel auf stdout schreibt. Früher
wurde pro Sekunde und Gerät ein neuer ffmpeg gestartet - das war träge und
hat den Pi unnötig belastet.

Wichtig: dieser Code lässt sich in dieser Sandbox nicht gegen einen echten
PipeWire-Server verifizieren (kein laufender Daemon, kein wpctl vorhanden).
Vor dem Lager-Einsatz auf dem echten Pi prüfen (siehe docs/audio-setup.md).
"""

import asyncio
import contextlib
import json
import logging
import re
import time

from .backend import AudioBackend, DiscoveredBus
from .levels import LEVEL_FLOOR_DB, db_to_level

logger = logging.getLogger("buschfunk.audio.pipewire")

MIX_SINK_NAME = "buschfunk-mix"
MIX_MONITOR = f"{MIX_SINK_NAME}.monitor"

LEVEL_INTERVAL = 0.1      # Sekunden zwischen zwei Pegelwerten
LEVEL_HOLD = 0.6          # ohne neuen Wert nach dieser Zeit auf 0 zurückfallen

# wpctl kappt eine gewuenschte Lautstaerke standardmaessig bei 100%, egal
# welcher Zahlenwert uebergeben wird - das "-l" Limit muss mindestens so hoch
# sein wie der groesste Wert, den die App je schickt, sonst wirkt ein
# aufgedrehter Kanal-Fader schlicht nicht (genau das war der Bug hinter
# "auch 150% reicht nicht": es wurde nie mehr als 100% ausgegeben).
WPCTL_VOLUME_LIMIT = "5.0"


async def _run(*args: str, timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        return -1, "", f"{args[0]} nicht gefunden"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "timeout"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def pipewire_available() -> bool:
    code, _out, _err = await _run("pw-dump", "--no-colors", timeout=3.0)
    return code == 0


class _LevelMonitor:
    """Ein dauerhafter ffmpeg-Prozess, der den RMS-Pegel einer Pulse-Quelle
    fortlaufend auf stdout schreibt. Stirbt der Prozess (Gerät abgezogen),
    wird er mit Abstand neu gestartet."""

    def __init__(self, source: str) -> None:
        self.source = source
        self._level = 0.0
        self._updated_at = 0.0
        self._task: asyncio.Task | None = None
        self._proc: asyncio.subprocess.Process | None = None

    @property
    def level(self) -> float:
        if time.monotonic() - self._updated_at > LEVEL_HOLD:
            return 0.0
        return self._level

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._kill_proc()

    async def _kill_proc(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            if proc.returncode is None:
                proc.kill()

    def _cmd(self) -> list[str]:
        samples = int(48000 * LEVEL_INTERVAL)
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "pulse", "-i", self.source,
            "-af",
            f"asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
            "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-",
            "-f", "null", "-",
        ]

    async def _loop(self) -> None:
        while True:
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *self._cmd(),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    stdin=asyncio.subprocess.DEVNULL,
                )
                assert self._proc.stdout is not None
                async for raw in self._proc.stdout:
                    line = raw.decode(errors="replace").strip()
                    if not line.startswith("lavfi.astats.Overall.RMS_level="):
                        continue
                    value = line.split("=", 1)[1]
                    try:
                        db = float(value)
                    except ValueError:
                        db = LEVEL_FLOOR_DB  # "-inf" bei absoluter Stille
                    self._level = db_to_level(db)
                    self._updated_at = time.monotonic()
                await self._proc.wait()
            except asyncio.CancelledError:
                await self._kill_proc()
                raise
            except Exception:
                logger.debug("Pegelmessung für %s abgebrochen", self.source, exc_info=True)
            await asyncio.sleep(2.0)


def _correction_stream_name(device_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", device_id)
    return f"BuschFunk-In-{safe}"


_PAN_FILTERS = {
    # pw-link kann Kanaele nur lauter/leiser oder stumm schalten, nicht neu
    # mischen - ein Mono-Kanal oder eine nur links belegte Quelle bleibt sonst
    # eben mono/links. Dafuer braucht es echtes Software-Downmixing per ffmpeg.
    "mono": "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1",
    "left": "pan=stereo|c0=c0|c1=c0",
    "right": "pan=stereo|c0=c1|c1=c1",
}


class _InputCorrection:
    """Ersetzt bei einer Quelle mit channel_mode != stereo das direkte
    pw-link-Routing durch einen dauerhaften ffmpeg-Prozess (gleiches Muster
    wie Musik/Jingle: `-f pulse` rein, Filter, `-f pulse` in den Mix-Sink
    raus). Der Pegel wird wie bei _LevelMonitor per ametadata mitgelesen."""

    def __init__(self, device_id: str, channel_mode: str) -> None:
        self.device_id = device_id
        self.channel_mode = channel_mode
        self.stream_name = _correction_stream_name(device_id)
        self._level = 0.0
        self._updated_at = 0.0
        self._task: asyncio.Task | None = None
        self._proc: asyncio.subprocess.Process | None = None

    @property
    def level(self) -> float:
        if time.monotonic() - self._updated_at > LEVEL_HOLD:
            return 0.0
        return self._level

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._kill_proc()

    async def _kill_proc(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            if proc.returncode is None:
                proc.kill()

    def _cmd(self) -> list[str]:
        samples = int(48000 * LEVEL_INTERVAL)
        pan = _PAN_FILTERS.get(self.channel_mode, "")
        filters = [pan, f"asetnsamples=n={samples}:p=0", "astats=metadata=1:reset=1",
                   "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"]
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "pulse", "-i", self.device_id,
            "-af", ",".join(f for f in filters if f),
            "-f", "pulse", "-device", MIX_SINK_NAME, self.stream_name,
        ]

    async def _loop(self) -> None:
        while True:
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *self._cmd(),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    stdin=asyncio.subprocess.DEVNULL,
                )
                assert self._proc.stdout is not None
                async for raw in self._proc.stdout:
                    line = raw.decode(errors="replace").strip()
                    if not line.startswith("lavfi.astats.Overall.RMS_level="):
                        continue
                    value = line.split("=", 1)[1]
                    try:
                        db = float(value)
                    except ValueError:
                        db = LEVEL_FLOOR_DB
                    self._level = db_to_level(db)
                    self._updated_at = time.monotonic()
                await self._proc.wait()
            except asyncio.CancelledError:
                await self._kill_proc()
                raise
            except Exception:
                logger.debug("Kanalkorrektur für %s abgebrochen", self.device_id, exc_info=True)
            await asyncio.sleep(2.0)


class PipeWireAudioBackend(AudioBackend):
    def __init__(self) -> None:
        self._node_ids: dict[str, str] = {}      # device_id (node.name) -> numerische Node-ID
        self._directions: dict[str, str] = {}    # device_id -> in | out
        self._linked: set[str] = set()           # bereits verkabelte device_ids
        self._monitors: dict[str, _LevelMonitor] = {}
        self._corrections: dict[str, _InputCorrection] = {}  # device_id -> laufende Kanalkorrektur
        self._master = _LevelMonitor(MIX_MONITOR)

    # ---------- Lifecycle ----------

    async def start(self) -> None:
        await self._ensure_mix_sink()
        self._master.start()

    async def stop(self) -> None:
        await self._master.stop()
        for monitor in list(self._monitors.values()):
            await monitor.stop()
        self._monitors.clear()
        for correction in list(self._corrections.values()):
            await correction.stop()
        self._corrections.clear()

    async def _ensure_mix_sink(self) -> None:
        nodes = await self._dump_nodes()
        if any(self._node_name(n) == MIX_SINK_NAME for n in nodes):
            return
        await _run(
            "pw-cli", "create-node", "adapter",
            "{ factory.name=support.null-audio-sink "
            f"node.name={MIX_SINK_NAME} media.class=Audio/Sink "
            "audio.position=[FL,FR] object.linger=true }",
        )

    # ---------- Geräte-Erkennung ----------

    @staticmethod
    def _node_name(node: dict) -> str | None:
        return node.get("info", {}).get("props", {}).get("node.name")

    async def _dump_nodes(self) -> list[dict]:
        code, out, err = await _run("pw-dump", "--no-colors")
        if code != 0:
            logger.warning("pw-dump fehlgeschlagen: %s", err.strip())
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            logger.warning("pw-dump lieferte kein gültiges JSON")
            return []
        return [obj for obj in data if obj.get("type") == "PipeWire:Interface:Node"]

    async def discover_buses(self) -> list[DiscoveredBus]:
        nodes = await self._dump_nodes()
        buses: list[DiscoveredBus] = []
        seen: set[str] = set()

        for node in nodes:
            props = node.get("info", {}).get("props", {})
            media_class = props.get("media.class", "")
            name = props.get("node.name")
            if not name or name == MIX_SINK_NAME:
                continue
            if media_class == "Audio/Source":
                direction = "in"
            elif media_class == "Audio/Sink":
                direction = "out"
            else:
                continue
            display = props.get("node.description") or props.get("device.description") or name
            self._node_ids[name] = str(node.get("id"))
            self._directions[name] = direction
            seen.add(name)
            buses.append(DiscoveredBus(device_id=name, display_name=display, direction=direction))

        await self._sync_links(seen)
        self._sync_monitors(seen)

        # abgezogene Geräte: beim nächsten Einstecken wieder frisch verkabeln
        for gone in self._linked - seen:
            self._linked.discard(gone)
        return buses

    async def _sync_links(self, device_ids: set[str]) -> None:
        """Nur neu aufgetauchte Geräte verkabeln - die Port-Listen holen wir
        dafür genau einmal statt einmal pro Gerät."""
        new = [d for d in device_ids if d not in self._linked]
        if not new:
            return
        code, out_ports_raw, _ = await _run("pw-link", "-o")
        if code != 0:
            return
        code, in_ports_raw, _ = await _run("pw-link", "-i")
        if code != 0:
            return
        out_ports = [line.strip() for line in out_ports_raw.splitlines() if line.strip()]
        in_ports = [line.strip() for line in in_ports_raw.splitlines() if line.strip()]

        for device_id in new:
            if device_id in self._corrections:
                continue  # laeuft ueber die ffmpeg-Kanalkorrektur, nicht per pw-link
            if self._directions.get(device_id) == "in":
                src_prefix, dst_prefix = f"{device_id}:", f"{MIX_SINK_NAME}:"
            else:
                src_prefix, dst_prefix = f"{MIX_SINK_NAME}:monitor", f"{device_id}:"
            src = sorted(p for p in out_ports if p.startswith(src_prefix))
            dst = sorted(p for p in in_ports if p.startswith(dst_prefix))
            for s, d in zip(src, dst):
                await _run("pw-link", s, d)  # "schon verbunden" ignorieren wir bewusst
            self._linked.add(device_id)

    async def _unlink_input(self, device_id: str) -> None:
        """Bestehende pw-link-Verbindungen von diesem Eingang in den Mix-Sink
        kappen - sonst kaeme das unkorrigierte Rohsignal zusaetzlich zur
        Kanalkorrektur im Mix an."""
        self._linked.discard(device_id)
        code, out, _ = await _run("pw-link", "-l")
        if code != 0:
            return
        src_prefix = f"{device_id}:"
        dst_prefix = f"{MIX_SINK_NAME}:"
        current_out: str | None = None
        for raw_line in out.splitlines():
            if not raw_line.strip():
                continue
            if raw_line[0] not in (" ", "\t"):
                current_out = raw_line.strip()
                continue
            line = raw_line.strip()
            if not line.startswith("|->") and not line.startswith("|<-"):
                continue
            target = line[3:].strip()
            if current_out and current_out.startswith(src_prefix) and target.startswith(dst_prefix):
                await _run("pw-link", "-d", current_out, target)

    def _sync_monitors(self, device_ids: set[str]) -> None:
        for device_id in device_ids:
            if device_id in self._corrections:
                continue  # die Kanalkorrektur meldet ihren eigenen Pegel
            if device_id in self._monitors:
                continue
            # Ein Sink wird über seine ".monitor"-Quelle abgehört, eine Source direkt.
            source = device_id if self._directions.get(device_id) == "in" else f"{device_id}.monitor"
            monitor = _LevelMonitor(source)
            monitor.start()
            self._monitors[device_id] = monitor

        for gone in set(self._monitors) - device_ids:
            monitor = self._monitors.pop(gone)
            asyncio.create_task(monitor.stop())

    # ---------- Mute / Lautstärke / Pegel ----------

    async def set_mute(self, device_id: str, muted: bool) -> None:
        node_id = self._node_ids.get(device_id)
        if node_id is None:
            logger.warning("set_mute: Gerät %s gerade nicht angeschlossen", device_id)
            return
        await _run("wpctl", "set-mute", node_id, "1" if muted else "0")

    async def set_volume(self, device_id: str, volume: float) -> None:
        node_id = self._node_ids.get(device_id)
        if node_id is None:
            logger.warning("set_volume: Gerät %s gerade nicht angeschlossen", device_id)
            return
        await _run(
            "wpctl", "set-volume", "-l", WPCTL_VOLUME_LIMIT, node_id, f"{max(0.0, volume):.2f}"
        )

    async def set_input_mode(self, device_id: str, channel_mode: str) -> None:
        existing = self._corrections.get(device_id)
        if channel_mode == "stereo":
            if existing is not None:
                await existing.stop()
                del self._corrections[device_id]
                self._linked.discard(device_id)  # naechste Erkennung verlinkt wieder direkt
            return
        if existing is not None and existing.channel_mode == channel_mode:
            return
        if existing is not None:
            await existing.stop()
        await self._unlink_input(device_id)
        correction = _InputCorrection(device_id, channel_mode)
        correction.start()
        self._corrections[device_id] = correction

    async def get_levels(self) -> dict[str, float]:
        levels = {device_id: m.level for device_id, m in self._monitors.items()}
        for device_id, correction in self._corrections.items():
            levels[device_id] = correction.level
        return levels

    async def get_master_level(self) -> float:
        return self._master.level

    # ---------- Musik/Jingle-Wiedergabe ----------

    def playback_sink(self) -> str:
        return MIX_SINK_NAME

    async def set_stream_volume(self, stream_name: str, volume: float) -> bool:
        """Lautstaerke eines laufenden Wiedergabe-Streams. Der Stream taucht in
        PipeWire unter dem Namen auf, den ffmpeg dem pulse-Ausgang gibt."""
        for node in await self._dump_nodes():
            props = node.get("info", {}).get("props", {})
            if props.get("media.name") == stream_name or props.get("node.name") == stream_name:
                code, _out, _err = await _run(
                    "wpctl", "set-volume", "-l", WPCTL_VOLUME_LIMIT,
                    str(node.get("id")), f"{max(0.0, volume):.2f}"
                )
                return code == 0
        return False

    def mix_monitor_source(self) -> str:
        # ffmpeg liest über den "pulse"-Demuxer (PipeWire stellt dafür den
        # pipewire-pulse-Kompatibilitätsserver bereit); ein Sink wird darüber
        # nur über seine ".monitor"-Quelle abgegriffen, nicht über den
        # Sink-Namen selbst.
        return MIX_MONITOR
