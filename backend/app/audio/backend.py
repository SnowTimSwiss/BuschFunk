from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DiscoveredBus:
    device_id: str
    display_name: str
    direction: str = "in"  # in (Eingang) | out (Ausgang, z.B. Monitor-Lautsprecher)
    connected: bool = True


class AudioBackend(ABC):
    """Abstraktion ueber die tatsaechliche Audio-Infrastruktur (PipeWire) bzw.
    ein No-Op-Backend fuer Entwicklung ohne echte Hardware.

    Ein Bus ist entweder ein Eingang (direction="in": eine Audioquelle, die
    dauerhaft in den einen gemeinsamen Loopback-Mix einspeist) oder ein
    Ausgang (direction="out": ein Geraet, das den fertigen Mix abbekommt,
    z.B. Monitor-Lautsprecher). Mute/Unmute und Lautstaerke passieren immer am
    jeweiligen Geraet selbst, nie am ffmpeg-Stream.

    Musik und Jingles spielt der Player (audio/player.py) als eigene Streams in
    denselben Mix - PipeWire summiert das von selbst, ein Jingle kann also ueber
    der Musik laufen.

    Es werden ausschliesslich Geraete gemeldet, die tatsaechlich am System
    haengen - keine Platzhalter, keine Default-Eintraege.
    """

    @abstractmethod
    async def start(self) -> None:
        """Loopback/Mix-Sink anlegen, interne Prozesse starten."""

    @abstractmethod
    async def stop(self) -> None:
        """Alles wieder sauber beenden (z.B. beim Shutdown)."""

    @abstractmethod
    async def discover_buses(self) -> list[DiscoveredBus]:
        """Aktuell wirklich angeschlossene Quellen/Ausgaenge."""

    @abstractmethod
    async def set_mute(self, device_id: str, muted: bool) -> None:
        ...

    @abstractmethod
    async def set_master_mute(self, muted: bool) -> None:
        """Die komplette gemischte Ausgabe zentral stoppen oder freigeben.

        Einzelne Quellen und Ausgaengeraete bleiben dabei unveraendert.
        """
        ...

    @abstractmethod
    async def set_volume(self, device_id: str, volume: float) -> None:
        """0.0 (aus) .. 1.0 (Normalpegel) .. je nach Richtung weiter aufgedreht."""

    @abstractmethod
    async def set_input_mode(self, device_id: str, channel_mode: str) -> None:
        """Nur fuer Eingaenge: stereo | mono | left | right. Ein reiner
        Pegel-Regler kann Kanaele nicht neu mischen, deshalb ein eigener
        Signalweg fuer alles ausser "stereo"."""

    @abstractmethod
    async def get_levels(self) -> dict[str, float]:
        """device_id -> Pegel 0.0 (still) .. 1.0 (voll ausgesteuert)."""

    @abstractmethod
    async def get_master_level(self) -> float:
        """Pegel des fertigen Mixes, also exakt das, was rausgeht."""

    @abstractmethod
    def playback_sink(self) -> str | None:
        """Sink-Name, in den Musik/Jingles gespielt werden. None = kein echtes
        Audio vorhanden, der Player laeuft dann nur simuliert mit."""

    @abstractmethod
    async def set_stream_volume(self, stream_name: str, volume: float) -> bool:
        """Lautstaerke eines laufenden Wiedergabe-Streams (Musik) setzen.
        False, wenn der Stream (noch) nicht gefunden wurde."""

    @abstractmethod
    def mix_monitor_source(self) -> str:
        """ffmpeg-Input-Spezifikation fuer den finalen Mix (fuer stream.py)."""
