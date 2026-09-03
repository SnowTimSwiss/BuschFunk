"""Prozessweite Laufzeit-Singletons (analog zu ws.manager): welches
AudioBackend gerade aktiv ist. Wird beim Start in main.py gesetzt."""

from .audio.backend import AudioBackend

audio_backend: AudioBackend | None = None
last_seen_device_ids: set[str] = set()
