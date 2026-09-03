"""Der eine Dauer-ffmpeg-Prozess: Mix-Monitor -> Icecast.

Bewusst als rohe PID (nicht als asyncio.subprocess.Process) verwaltet: nach
einem Self-Update (app/update.py, os.execv) bleibt dieser Kindprozess am
Leben und weiterhin an unsere PID gebunden (execv ersetzt nur das
Python-Programm-Image, nicht die Prozess-/Elternbeziehungen im Kernel) - wir
lesen die PID-Datei nach dem Neustart einfach wieder ein und "adoptieren"
den bereits laufenden Stream, statt ihn neu zu verbinden. Genau das sorgt
dafür, dass ein Software-Update den laufenden Stream nicht unterbricht.
"""

import asyncio
import logging
import os
import signal
import subprocess
from pathlib import Path

from ..audio.backend import AudioBackend
from ..config import settings

logger = logging.getLogger("buschfunk.audio.stream")

RUNTIME_DIR = Path(__file__).resolve().parent.parent.parent / ".runtime"
PIDFILE = RUNTIME_DIR / "ffmpeg_stream.pid"

RESPAWN_MIN_INTERVAL = 5.0  # Sekunden - Schutz vor Crash-Loop


def _build_ffmpeg_cmd(source: str) -> list[str]:
    icecast_url = (
        f"icecast://source:{settings.icecast_source_password}"
        f"@{settings.icecast_host}:{settings.icecast_port}{settings.icecast_mount}"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "pipewire",
        "-i",
        source,
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        "-content_type",
        "audio/mpeg",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
        "-f",
        "mp3",
        icecast_url,
    ]


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class StreamManager:
    def __init__(self) -> None:
        self._pid: int | None = None
        self._monitor_task: asyncio.Task | None = None
        self._stopping = False
        self._source = ""

    async def start(self, audio_backend: AudioBackend) -> None:
        self._source = audio_backend.mix_monitor_source()
        if self._source.startswith("dummy://"):
            logger.info("Dummy-Audio-Backend aktiv - kein echter ffmpeg-Stream in diesem Modus.")
            return

        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        if PIDFILE.exists():
            try:
                pid = int(PIDFILE.read_text().strip())
            except ValueError:
                pid = None
            if pid and _pid_is_alive(pid):
                logger.info("Bestehenden Stream-Prozess (PID %s) nach Neustart übernommen.", pid)
                self._pid = pid
                self._monitor_task = asyncio.create_task(self._monitor_loop())
                return

        self._spawn()
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    def _spawn(self) -> None:
        cmd = _build_ffmpeg_cmd(self._source)
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
        self._pid = proc.pid
        PIDFILE.write_text(str(proc.pid))
        logger.info("Stream-ffmpeg gestartet (PID %s): %s", proc.pid, " ".join(cmd))

    async def _monitor_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(2.0)
            if self._pid is None or not _pid_is_alive(self._pid):
                if self._stopping:
                    return
                logger.warning("Stream-ffmpeg (PID %s) nicht mehr am Leben, starte neu.", self._pid)
                try:
                    os.waitpid(self._pid, os.WNOHANG)
                except (ChildProcessError, OSError, TypeError):
                    pass
                await asyncio.sleep(RESPAWN_MIN_INTERVAL)
                if not self._stopping:
                    self._spawn()

    async def stop(self) -> None:
        self._stopping = True
        if self._monitor_task:
            self._monitor_task.cancel()
        if self._pid and _pid_is_alive(self._pid):
            try:
                os.kill(self._pid, signal.SIGTERM)
            except OSError:
                pass
        if PIDFILE.exists():
            PIDFILE.unlink()

    @property
    def is_running(self) -> bool:
        return self._pid is not None and _pid_is_alive(self._pid)


stream_manager = StreamManager()
