"""Musik- und Jingle-Wiedergabe direkt in den Sende-Mix.

Zwei unabhaengige Kanaele, die beide in denselben PipeWire-Sink schreiben:

* **Musik** - eine Warteschlange, die von selbst weiterlaeuft. Genau das
  verhindert Sendepausen: solange etwas in der Liste steht (und "endlos
  wiederholen" an ist), geht der Ton nie aus.
* **Jingles** - ein Knopfdruck, spielt *ueber* die Musik. PipeWire summiert
  beide Streams im Mix-Sink, deshalb muss dafuer nichts gestoppt werden.

Pause laeuft weiterhin ueber SIGSTOP/SIGCONT auf dem ffmpeg-Prozess und gilt nur fuer den manuellen Player-Knopf.

Fade in/out bleibt eine reine Lautstaerke-Rampe auf dem PipeWire-Stream-Node (`wpctl set-volume`, in kleinen Schritten). Off-Air greift diese Player-Steuerung nicht an: Der gemeinsame Master-Ausgang wird zentral geschaltet.

Pegel fuer die Meter-Anzeige kommen ueber denselben ametadata-Trick wie beim
Mischpult (siehe pipewire.py), nur direkt im Wiedergabe-ffmpeg mitgemessen -
das ist der Pegel der Datei selbst (vor dem PipeWire-Fader), zeigt also auch
waehrend eines Fade-outs noch die volle Lautstaerke des Files an.
"""

import asyncio
import contextlib
import logging
import os
import random
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from .levels import LEVEL_FLOOR_DB, db_to_level

logger = logging.getLogger("buschfunk.audio.player")

RUNTIME_DIR = Path(__file__).resolve().parent.parent.parent / ".runtime"

MUSIC_STREAM_NAME = "BuschFunk-Musik"
JINGLE_STREAM_NAME = "BuschFunk-Jingle"

MIN_TRACK_SECONDS = 0.7   # kuerzer gelaufen = kaputte Datei, nicht als gespielt werten
MAX_FAILURES = 5          # danach lieber stoppen als durch die halbe Liste rasen
QUEUE_PREVIEW = 12        # so viele kommende Titel gehen ueber den WebSocket

LEVEL_INTERVAL = 0.1      # Sekunden zwischen zwei Pegelwerten (wie pipewire.py)
LEVEL_HOLD = 0.6          # ohne neuen Wert nach dieser Zeit auf 0 zurueckfallen

FADE_SECONDS = 1.2
FADE_STEPS = 24


@dataclass
class QueueEntry:
    track_id: int
    title: str
    path: str
    duration: float

    def as_dict(self, index: int) -> dict:
        return {"index": index, "track_id": self.track_id, "title": self.title, "duration": self.duration}


def _pidfile(name: str) -> Path:
    return RUNTIME_DIR / f"player_{name}.pid"


def kill_orphans() -> None:
    """Nach einem Self-Update (os.execv) laufen alte Wiedergabe-Prozesse weiter,
    ohne dass wir sie noch steuern koennten - die raeumen wir beim Start weg."""
    for name in ("music", "jingle"):
        path = _pidfile(name)
        if not path.exists():
            continue
        try:
            pid = int(path.read_text().strip())
        except (ValueError, OSError):
            pid = 0
        if pid:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
        with contextlib.suppress(OSError):
            path.unlink()


class _Channel:
    """Ein Wiedergabe-Kanal: hoechstens ein laufender ffmpeg-Prozess."""

    def __init__(self, name: str, stream_name: str) -> None:
        self.name = name
        self.stream_name = stream_name
        self.sink: str | None = None
        self._backend = None
        self._proc: asyncio.subprocess.Process | None = None
        self._level = 0.0
        self._level_at = 0.0
        self._output_volume = 1.0   # aktuell tatsaechlich ausgegebene Lautstaerke (fuer Fades)

    @property
    def level(self) -> float:
        if time.monotonic() - self._level_at > LEVEL_HOLD:
            return 0.0
        return self._level

    async def _spawn(self, path: str) -> asyncio.subprocess.Process | None:
        if self.sink is None:
            return None  # kein echtes Audio-Backend - der Aufrufer simuliert
        samples = int(48000 * LEVEL_INTERVAL)
        af = (
            f"asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
            "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"
        )
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", path, "-af", af,
            "-f", "pulse", "-device", self.sink, self.stream_name,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._proc = proc
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            _pidfile(self.name).write_text(str(proc.pid))
        return proc

    async def _drain(self, proc: asyncio.subprocess.Process) -> bytes:
        """Pegel-Metadaten von stdout laufend auswerten und stderr sammeln,
        bis der Prozess beendet ist - parallel, damit keine der beiden Pipes
        vollaeuft und ffmpeg blockiert."""
        stderr_chunks: list[bytes] = []

        async def read_stdout() -> None:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("lavfi.astats.Overall.RMS_level="):
                    continue
                try:
                    db = float(line.split("=", 1)[1])
                except ValueError:
                    db = LEVEL_FLOOR_DB
                self._level = db_to_level(db)
                self._level_at = time.monotonic()

        async def read_stderr() -> None:
            assert proc.stderr is not None
            async for raw in proc.stderr:
                stderr_chunks.append(raw)

        await asyncio.gather(read_stdout(), read_stderr())
        self._level = 0.0
        return b"".join(stderr_chunks)

    async def _ramp_volume(self, target: float, seconds: float = FADE_SECONDS) -> None:
        if self._backend is None:
            self._output_volume = target
            return
        start = self._output_volume
        if start == target:
            return
        for i in range(1, FADE_STEPS + 1):
            self._output_volume = start + (target - start) * i / FADE_STEPS
            await self._backend.set_stream_volume(self.stream_name, self._output_volume)
            await asyncio.sleep(seconds / FADE_STEPS)

    def _signal(self, sig: int) -> None:
        proc = self._proc
        if proc and proc.returncode is None:
            with contextlib.suppress(OSError):
                proc.send_signal(sig)

    async def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            with contextlib.suppress(OSError):
                proc.send_signal(signal.SIGCONT)  # ein pausierter Prozess stirbt sonst nicht
            with contextlib.suppress(OSError):
                proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            if proc.returncode is None:
                with contextlib.suppress(OSError):
                    proc.kill()
        with contextlib.suppress(OSError):
            _pidfile(self.name).unlink()


class MusicPlayer(_Channel):
    def __init__(self) -> None:
        super().__init__("music", MUSIC_STREAM_NAME)
        self.queue: list[QueueEntry] = []
        self.index = 0
        self.repeat = True
        self.volume = 1.0
        self.paused = False
        self._task: asyncio.Task | None = None
        self._playing = False
        self._started_at = 0.0
        self._paused_at = 0.0
        self._paused_total = 0.0
        self._skip: int | None = None   # None = einfach zum naechsten Titel
        self._stopping = False
        self._interrupt = asyncio.Event()   # bricht die simulierte Wiedergabe ab
        self._volume_task: asyncio.Task | None = None

    def configure(self, backend) -> None:
        self._backend = backend
        self.sink = backend.playback_sink()

    # ---------- Zustand ----------

    @property
    def current(self) -> QueueEntry | None:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    def position(self) -> float:
        if not self._playing:
            return 0.0
        now = self._paused_at if self.paused else time.monotonic()
        return max(0.0, now - self._started_at - self._paused_total)

    def state(self) -> dict:
        current = self.current if self._playing else None
        ahead = [
            entry.as_dict(i)
            for i, entry in enumerate(self.queue)
            if i > self.index
        ][:QUEUE_PREVIEW]
        return {
            "playing": self._playing,
            "paused": self.paused,
            "track_id": current.track_id if current else None,
            "title": current.title if current else None,
            "position": round(self.position(), 1),
            "duration": current.duration if current else 0.0,
            "queue_length": len(self.queue),
            "queue_index": self.index,
            "queue_ahead": ahead,
            "repeat": self.repeat,
            "volume": self.volume,
            "level": self.level,
        }

    # ---------- Steuerung ----------

    async def play(self, entries: list[QueueEntry], shuffle: bool = False) -> None:
        """Warteschlange ersetzen und von vorn starten."""
        entries = list(entries)
        if shuffle:
            random.shuffle(entries)
        await self._halt()
        self.queue = entries
        self.index = 0
        if entries:
            self._start_loop()

    async def play_now(self, entry: QueueEntry) -> None:
        """Einen Titel sofort spielen - der Rest der Warteschlange bleibt stehen
        und laeuft danach weiter."""
        if not self.queue or not self._playing:
            await self.play([entry, *self.queue[self.index + 1:]] if self.queue else [entry])
            return
        self.queue.insert(self.index + 1, entry)
        await self.skip(1)

    async def enqueue(self, entries: list[QueueEntry]) -> None:
        self.queue.extend(entries)
        if not self._playing and self.queue:
            self.index = min(self.index, len(self.queue) - 1)
            self._start_loop()

    async def skip(self, delta: int) -> None:
        if not self.queue:
            return
        if not self._playing:
            self.index = max(0, min(len(self.queue) - 1, self.index + delta))
            self._start_loop()
            return
        self._skip = delta
        await self._kill()

    async def jump(self, index: int) -> None:
        if not (0 <= index < len(self.queue)):
            return
        if not self._playing:
            self.index = index
            self._start_loop()
            return
        self._skip = index - self.index
        await self._kill()

    async def toggle_pause(self) -> None:
        if not self._playing:
            if self.queue:
                self._start_loop()
            return
        if self.paused:
            await self._resume_now()
        else:
            await self._pause_now()

    async def _pause_now(self) -> None:
        if not self._playing or self.paused:
            return
        await self._ramp_volume(0.0)
        self._paused_at = time.monotonic()
        self.paused = True
        self._signal(signal.SIGSTOP)

    async def _resume_now(self) -> None:
        if not self._playing or not self.paused:
            return
        self._paused_total += time.monotonic() - self._paused_at
        self.paused = False
        self._signal(signal.SIGCONT)
        self._volume_task = asyncio.create_task(self._ramp_volume(self.volume))

    async def stop(self) -> None:
        self._stopping = True
        await self._halt()

    async def clear(self) -> None:
        await self.stop()
        self.queue = []
        self.index = 0

    async def remove(self, index: int) -> None:
        if not (0 <= index < len(self.queue)):
            return
        self.queue.pop(index)
        if index < self.index:
            self.index -= 1
        elif index == self.index and self._playing:
            self._skip = 0  # an dieser Stelle steht jetzt der naechste Titel
            await self._kill()

    async def drop_track(self, track_id: int) -> None:
        """Einen geloeschten Titel ueberall aus der Warteschlange nehmen."""
        for index in range(len(self.queue) - 1, -1, -1):
            if self.queue[index].track_id == track_id:
                await self.remove(index)

    async def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.5, volume))
        if not self.paused:
            self._output_volume = self.volume
            if self._backend is not None:
                await self._backend.set_stream_volume(self.stream_name, self.volume)

    def set_repeat(self, repeat: bool) -> None:
        self.repeat = repeat

    # ---------- Ablauf ----------

    async def _kill(self) -> None:
        self._interrupt.set()
        await super()._kill()

    def _start_loop(self) -> None:
        self._stopping = False
        self._skip = None
        self._task = asyncio.create_task(self._run())

    async def _halt(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._kill()
        self._playing = False
        self.paused = False

    async def _run(self) -> None:
        failures = 0
        try:
            while not self._stopping and 0 <= self.index < len(self.queue):
                entry = self.queue[self.index]
                started = time.monotonic()
                ok = await self._play_entry(entry)
                ran = time.monotonic() - started

                if not ok and self._skip is None and ran < MIN_TRACK_SECONDS:
                    failures += 1
                    logger.warning("Titel liess sich nicht abspielen: %s", entry.path)
                    if failures >= MAX_FAILURES:
                        logger.error("Zu viele fehlerhafte Titel - Wiedergabe angehalten.")
                        break
                    await asyncio.sleep(0.3)
                else:
                    failures = 0

                if self._stopping:
                    break
                step, self._skip = (1 if self._skip is None else self._skip), None
                nxt = self.index + step
                if nxt >= len(self.queue):
                    if not self.repeat:
                        break
                    nxt = 0
                self.index = max(0, nxt)
        finally:
            self._playing = False
            self.paused = False

    async def _play_entry(self, entry: QueueEntry) -> bool:
        self._playing = True
        self.paused = False
        self._started_at = time.monotonic()
        self._paused_total = 0.0
        self._interrupt.clear()

        proc = await self._spawn(entry.path)
        if proc is None:
            await self._simulate(entry)
            return True

        self._volume_task = asyncio.create_task(self._apply_volume())
        err = await self._drain(proc)
        await proc.wait()
        if proc.returncode not in (0, None) and err:
            logger.warning("ffmpeg (%s): %s", entry.title, err.decode(errors="replace").strip()[:300])
        return proc.returncode == 0

    async def _simulate(self, entry: QueueEntry) -> None:
        """Ohne Audio-Hardware laeuft die Warteschlange trotzdem weiter - so
        laesst sich die Regie auch am Laptop bedienen und testen."""
        total = entry.duration if entry.duration > 0 else 5.0
        while self.position() < total and not self._interrupt.is_set():
            await asyncio.sleep(0.1)

    async def _apply_volume(self) -> None:
        """Der Stream taucht erst kurz nach dem Start in PipeWire auf - deshalb
        ein paar Anlaeufe, bis die Lautstaerke sitzt."""
        if self._backend is None:
            self._output_volume = self.volume
            return
        for _ in range(12):
            await asyncio.sleep(0.2)
            if await self._backend.set_stream_volume(self.stream_name, self.volume):
                self._output_volume = self.volume
                return


class JinglePlayer(_Channel):
    def __init__(self) -> None:
        super().__init__("jingle", JINGLE_STREAM_NAME)
        self._task: asyncio.Task | None = None
        self._title: str | None = None

    def configure(self, backend) -> None:
        self._backend = backend
        self.sink = backend.playback_sink()

    def state(self) -> dict:
        return {"playing": self._title is not None, "title": self._title, "level": self.level}

    async def play(self, path: str, title: str, duration: float) -> None:
        await self.stop()
        self._output_volume = 1.0
        self._title = title
        self._task = asyncio.create_task(self._run(path, duration))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._kill()
        self._title = None

    async def _run(self, path: str, duration: float) -> None:
        try:
            proc = await self._spawn(path)
            if proc is None:
                await asyncio.sleep(duration if duration > 0 else 2.0)
                return
            err = await self._drain(proc)
            await proc.wait()
            if proc.returncode not in (0, None) and err:
                logger.warning("Jingle-ffmpeg: %s", err.decode(errors="replace").strip()[:300])
        finally:
            self._title = None
