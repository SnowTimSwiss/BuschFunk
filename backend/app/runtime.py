"""Prozessweite Laufzeit-Singletons (analog zu ws.manager): welches
AudioBackend gerade aktiv ist, welche Geräte zuletzt gesehen wurden und
welche Segment-Mediendateien schon automatisch abgespielt wurden.
Wird beim Start in main.py gesetzt."""

from .audio.backend import AudioBackend

audio_backend: AudioBackend | None = None
last_seen_device_ids: set[str] = set()
audio_ready: bool = False

# Segment-IDs, deren "am Ende automatisch"-Datei in diesem Durchlauf schon
# gestartet wurde - verhindert, dass der Ticker sie jede Sekunde neu anwirft.
fired_end_media: set[int] = set()
