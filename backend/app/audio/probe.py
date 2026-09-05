"""Laenge einer Audiodatei bestimmen (ffprobe gehoert zum ffmpeg-Paket)."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("buschfunk.audio.probe")


def probe_duration(path: Path | str) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0.0
    try:
        return round(max(0.0, float(out.stdout.strip())), 2)
    except ValueError:
        return 0.0
