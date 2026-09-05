from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DiscoveredBus:
    device_id: str
    display_name: str
    direction: str = "in"  # in (Eingang) | out (Ausgang, z.B. Monitor-Lautsprecher)
    connected: bool = True


@dataclass
class PlayerStatus:
    playing: bool = False
    title: str | None = None
    segment_id: int | None = None


class AudioBackend(ABC):
    """Abstraktion über die tatsächliche Audio-Infrastruktur (PipeWire) bzw.
    ein No-Op-Backend für Entwicklung ohne echte Hardware.

    Ein Bus ist entweder ein Eingang (direction="in": eine Audioquelle, die
    dauerhaft in den einen gemeinsamen Loopback-Mix einspeist) oder ein
    Ausgang (direction="out": ein Gerät, das den fertigen Mix abbekommt,
    z.B. Monitor-Lautsprecher). Mute/Unmute und Lautstärke passieren immer am
    jeweiligen Gerät selbst, nie am ffmpeg-Stream.

    Es werden ausschliesslich Geräte gemeldet, die tatsächlich am System
    hängen - keine Platzhalter, keine Default-Einträge.
    """

    @abstractmethod
    async def start(self) -> None:
        """Loopback/Mix-Sink anlegen, interne Prozesse starten."""

    @abstractmethod
    async def stop(self) -> None:
        """Alles wieder sauber beenden (z.B. beim Shutdown)."""

    @abstractmethod
    async def discover_buses(self) -> list[DiscoveredBus]:
        """Aktuell wirklich angeschlossene Quellen/Ausgänge."""

    @abstractmethod
    async def set_mute(self, device_id: str, muted: bool) -> None:
        ...

    @abstractmethod
    async def set_volume(self, device_id: str, volume: float) -> None:
        """0.0 (aus) .. 1.0 (Normalpegel) .. 1.5 (aufgedreht)."""

    @abstractmethod
    async def get_levels(self) -> dict[str, float]:
        """device_id -> Pegel 0.0 (still) .. 1.0 (voll ausgesteuert)."""

    @abstractmethod
    async def get_master_level(self) -> float:
        """Pegel des fertigen Mixes, also exakt das, was rausgeht."""

    @abstractmethod
    async def play_file(self, path: str, title: str | None = None, segment_id: int | None = None) -> None:
        """Interner Player-Bus: eine Datei (Jingle/Intro/Outro) in den Mix spielen."""

    @abstractmethod
    async def stop_player(self) -> None:
        ...

    @abstractmethod
    def player_status(self) -> PlayerStatus:
        ...

    @abstractmethod
    def mix_monitor_source(self) -> str:
        """ffmpeg-Input-Spezifikation für den finalen Mix (für stream.py)."""
