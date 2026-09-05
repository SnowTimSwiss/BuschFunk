import logging

from ..config import settings
from .backend import AudioBackend, DiscoveredBus
from .dummy import DemoAudioBackend, DummyAudioBackend
from .pipewire import PipeWireAudioBackend, pipewire_available

logger = logging.getLogger("buschfunk.audio")

__all__ = ["AudioBackend", "DiscoveredBus", "create_audio_backend"]


async def create_audio_backend() -> AudioBackend:
    mode = settings.audio_backend
    if mode == "demo":
        logger.info("Audio-Backend: demo (simulierte Geräte, nur für Entwicklung)")
        return DemoAudioBackend()
    if mode == "dummy":
        logger.info("Audio-Backend: dummy (per Konfiguration erzwungen, keine Geräte)")
        return DummyAudioBackend()
    if mode == "pipewire":
        logger.info("Audio-Backend: pipewire (per Konfiguration erzwungen)")
        return PipeWireAudioBackend()

    if await pipewire_available():
        logger.info("Audio-Backend: pipewire (automatisch erkannt)")
        return PipeWireAudioBackend()

    logger.warning("Kein PipeWire-Server erreichbar - es werden keine Audiogeräte angezeigt.")
    return DummyAudioBackend()
