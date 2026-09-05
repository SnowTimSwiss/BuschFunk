"""Prozessweite Laufzeit-Singletons (analog zu ws.manager): das aktive
AudioBackend, die beiden Wiedergabe-Kanaele und welche Geraete zuletzt
gesehen wurden. Wird beim Start in main.py gesetzt."""

from .audio.backend import AudioBackend
from .audio.player import JinglePlayer, MusicPlayer
from .reporter import ReporterManager

audio_backend: AudioBackend | None = None
player: MusicPlayer | None = None
jingles: JinglePlayer | None = None
reporter: ReporterManager | None = None
last_seen_device_ids: set[str] = set()
audio_ready: bool = False
