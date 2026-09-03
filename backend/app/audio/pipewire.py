"""Echte PipeWire-Anbindung.

Routing-Idee: ein Null-Sink `buschfunk-mix` ist das gemeinsame Ziel. Jede
Hardware-Quelle (Mischpult, weitere USB-Interfaces) wird per `pw-link` in
dessen Input-Ports gemischt (mehrere Links auf denselben Input-Port werden
von PipeWire automatisch summiert). Umgekehrt wird jedes erkannte
Wiedergabegerät (Monitor-Lautsprecher, Kopfhörer) per `pw-link` an die
Monitor-Ports des Mix-Sinks gehängt, bekommt also denselben fertigen Mix wie
der Icecast-Stream. Mute/Unmute passiert immer über `wpctl set-mute` auf dem
jeweiligen Gerät - der Link bleibt bestehen, es wird nichts neu verbunden.
Der interne "Player"-Bus (Jingles/Intros/Outros) spielt Dateien
per kurzlebigem ffmpeg-Prozess über die generische "pipewire"-ALSA-PCM
(Ziel-Node per PIPEWIRE_NODE-Umgebungsvariable) direkt in den Mix.

Wichtig: dieser Code lässt sich in dieser Sandbox nicht gegen einen echten
PipeWire-Server verifizieren (kein laufender Daemon, kein wpctl vorhanden).
Vor dem Lager-Einsatz auf dem echten Pi mit angeschlossenem Mischpult prüfen
(siehe docs/audio-setup.md).
"""

import asyncio
import json
import logging
import os
import re

from .backend import AudioBackend, DiscoveredBus

logger = logging.getLogger("buschfunk.audio.pipewire")

MIX_SINK_NAME = "buschfunk-mix"


async def _run(*args: str, timeout: float = 5.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
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


class PipeWireAudioBackend(AudioBackend):
    def __init__(self) -> None:
        self._muted: dict[str, bool] = {}
        self._node_ids: dict[str, str] = {}  # device_id (node.name) -> numeric node id
        self._player_proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        await self._ensure_mix_sink()

    async def stop(self) -> None:
        await self.stop_player()

    async def _ensure_mix_sink(self) -> None:
        nodes = await self._dump_nodes()
        if any(n.get("info", {}).get("props", {}).get("node.name") == MIX_SINK_NAME for n in nodes):
            return
        await _run(
            "pw-cli",
            "create-node",
            "adapter",
            "{ factory.name=support.null-audio-sink "
            f"node.name={MIX_SINK_NAME} media.class=Audio/Sink "
            "audio.position=[FL,FR] object.linger=true }",
        )

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
        for node in nodes:
            props = node.get("info", {}).get("props", {})
            media_class = props.get("media.class", "")
            name = props.get("node.name")
            if not name:
                continue
            if media_class == "Audio/Source":
                # Hardware-Aufnahmequelle (Mischpult, USB-Interface) -> in den Mix
                self._node_ids[name] = str(node.get("id"))
                display = props.get("node.description") or props.get("device.description") or name
                buses.append(DiscoveredBus(device_id=name, display_name=display, direction="in"))
                await self._link_ports(f"{name}:", MIX_SINK_NAME)
            elif media_class == "Audio/Sink" and name != MIX_SINK_NAME:
                # Hardware-Wiedergabegerät (Monitor-Lautsprecher, Kopfhörer) -> bekommt den fertigen Mix
                self._node_ids[name] = str(node.get("id"))
                display = props.get("node.description") or props.get("device.description") or name
                buses.append(DiscoveredBus(device_id=name, display_name=display, direction="out"))
                await self._link_ports(f"{MIX_SINK_NAME}:monitor", name)
        return buses

    async def _link_ports(self, src_prefix: str, dst_node_name: str) -> None:
        """Verbindet alle Output-Ports, die mit `src_prefix` beginnen, mit den
        Input-Ports des Ziel-Node (z.B. `"quelle:"` oder `"mix:monitor"`)."""
        code, out, _err = await _run("pw-link", "-o")
        if code != 0:
            return
        src_ports = [line.strip() for line in out.splitlines() if line.startswith(src_prefix)]

        code, out, _err = await _run("pw-link", "-i")
        if code != 0:
            return
        dst_ports = [line.strip() for line in out.splitlines() if line.startswith(f"{dst_node_name}:")]

        for src, dst in zip(sorted(src_ports), sorted(dst_ports)):
            await _run("pw-link", src, dst)  # Fehler (z.B. "schon verbunden") ignorieren wir bewusst

    async def set_mute(self, device_id: str, muted: bool) -> None:
        self._muted[device_id] = muted
        node_id = self._node_ids.get(device_id)
        if node_id is None:
            logger.warning("set_mute: unbekannter Bus %s (noch nicht discovered?)", device_id)
            return
        await _run("wpctl", "set-mute", node_id, "1" if muted else "0")

    async def get_levels(self) -> dict[str, float]:
        async def sample(device_id: str) -> tuple[str, float]:
            if self._muted.get(device_id, True):
                return device_id, 0.0
            code, _out, err = await _run(
                "ffmpeg",
                "-f",
                "pipewire",
                "-i",
                device_id,
                "-t",
                "0.3",
                "-af",
                "astats=metadata=1:reset=1:length=0.3",
                "-f",
                "null",
                "-",
                timeout=2.0,
            )
            if code != 0:
                return device_id, 0.0
            match = re.search(r"Overall\).*?RMS level dB:\s*(-?\d+(\.\d+)?)", err, re.DOTALL)
            if not match:
                return device_id, 0.0
            db = float(match.group(1))
            level = max(0.0, min(1.0, (db + 60.0) / 60.0))
            return device_id, round(level, 3)

        results = await asyncio.gather(
            *(sample(device_id) for device_id in self._muted), return_exceptions=True
        )
        levels: dict[str, float] = {}
        for r in results:
            if isinstance(r, Exception):
                continue
            device_id, level = r
            levels[device_id] = level
        levels["player"] = 0.5 if self._player_proc and self._player_proc.returncode is None else 0.0
        return levels

    async def mute_all(self) -> None:
        for device_id in list(self._muted):
            await self.set_mute(device_id, True)
        await self.stop_player()

    async def play_file(self, path: str) -> None:
        await self.stop_player()
        # "pipewire" ist die generische ALSA-PCM des pipewire-alsa-Plugins;
        # PIPEWIRE_NODE lenkt sie auf unseren Mix-Sink, ganz ohne systemweite
        # asound.conf-Änderung.
        env = {**os.environ, "PIPEWIRE_NODE": MIX_SINK_NAME}
        self._player_proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-re", "-i", path, "-f", "alsa", "pipewire", "-loglevel", "error", env=env
        )

    async def stop_player(self) -> None:
        if self._player_proc and self._player_proc.returncode is None:
            self._player_proc.terminate()
            try:
                await asyncio.wait_for(self._player_proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._player_proc.kill()
        self._player_proc = None

    def mix_monitor_source(self) -> str:
        return MIX_SINK_NAME
