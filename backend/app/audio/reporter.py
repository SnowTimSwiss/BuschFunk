"""Audio-Eingang fuer einen per Browser gekoppelten Aussenreporter.

Das Handy liefert kleine WebM/Opus-Abschnitte per WebSocket. Ein langlebiger
ffmpeg-Prozess dekodiert sie und schreibt den Reporter als eigenen Stream in
den gemeinsamen PipeWire-Mix.
"""

import asyncio
import contextlib
import logging
import time

from .levels import LEVEL_FLOOR_DB, db_to_level

logger = logging.getLogger("buschfunk.audio.reporter")

REPORTER_STREAM_NAME = "BuschFunk-Aussenreporter"
LEVEL_INTERVAL = 0.1
LEVEL_HOLD = 0.6


class ReporterAudio:
    def __init__(self) -> None:
        self.sink: str | None = None
        self._backend = None
        self._proc: asyncio.subprocess.Process | None = None
        self._drain_task: asyncio.Task | None = None
        self._level = 0.0
        self._level_at = 0.0
        self._muted = True
        self._lock = asyncio.Lock()

    def configure(self, backend) -> None:
        self._backend = backend
        self.sink = backend.playback_sink()

    @property
    def level(self) -> float:
        if time.monotonic() - self._level_at > LEVEL_HOLD:
            return 0.0
        return self._level

    async def start(self) -> None:
        await self.stop()
        if self.sink is None:
            return  # Demo/ohne Audio-Hardware: Verbindung trotzdem testbar.
        samples = int(48000 * LEVEL_INTERVAL)
        audio_filter = (
            f"asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
            "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"
        )
        self._proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
            "-f", "webm", "-i", "pipe:0", "-af", audio_filter,
            "-f", "pulse", "-device", self.sink, REPORTER_STREAM_NAME,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._drain_task = asyncio.create_task(self._drain(self._proc))
        await self.set_muted(self._muted)

    async def feed(self, data: bytes) -> bool:
        """Einen Browser-Audioabschnitt an ffmpeg weitergeben."""
        proc = self._proc
        if proc is None:
            return self.sink is None
        if proc.returncode is not None or proc.stdin is None:
            return False
        try:
            async with self._lock:
                proc.stdin.write(data)
                await proc.stdin.drain()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    async def set_muted(self, muted: bool) -> None:
        self._muted = muted
        if self._backend is None:
            return
        volume = 0.0 if muted else 1.0
        for _ in range(12):
            if await self._backend.set_stream_volume(REPORTER_STREAM_NAME, volume):
                return
            await asyncio.sleep(0.15)

    async def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.stdin:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                proc.stdin.close()
        if proc and proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            if proc.returncode is None:
                proc.kill()
        task, self._drain_task = self._drain_task, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._level = 0.0

    async def _drain(self, proc: asyncio.subprocess.Process) -> None:
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
                logger.debug("Reporter-ffmpeg: %s", raw.decode(errors="replace").strip())

        await asyncio.gather(read_stdout(), read_stderr())
