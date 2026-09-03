from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DiscoveredBus:
    device_id: str
    display_name: str
    direction: str = "in"  # in (Eingang) | out (Ausgang, z.B. Monitor-Lautsprecher)
    connected: bool = True


class AudioBackend(ABC):
    """Abstraktion über die tatsächliche Audio-Infrastruktur (PipeWire) bzw.
    ein Dummy für Entwicklung/Demo ohne echte Hardware.

    Ein Bus ist entweder ein Eingang (direction="in": eine Audioquelle, die
    dauerhaft in den einen gemeinsamen Loopback-Mix einspeist) oder ein
    Ausgang (direction="out": ein Gerät, das den fertigen Mix abbekommt,
    z.B. Monitor-Lautsprecher). Mute/Unmute passiert immer am jeweiligen
    Gerät selbst, nie am ffmpeg-Stream.
    """

    @abstractmethod
    async def start(self) -> None:
        """Loopback/Mix-Sink anlegen, interne Prozesse starten."""

    @abstractmethod
    async def stop(self) -> None:
        """Alles wieder sauber beenden (z.B. beim Shutdown)."""

    @abstractmethod
    async def discover_buses(self) -> list[DiscoveredBus]:
        """Aktuell sichtbare Hardware-Quellen (ohne den internen Player-Bus)."""

    @abstractmethod
    async def set_mute(self, device_id: str, muted: bool) -> None:
        ...

    @abstractmethod
    async def get_levels(self) -> dict[str, float]:
        """device_id -> Pegel 0.0 (still) .. 1.0 (voll ausgesteuert)."""

    @abstractmethod
    async def mute_all(self) -> None:
        """Notfall: alle Busse (inkl. Player) stumm."""

    @abstractmethod
    async def play_file(self, path: str) -> None:
        """Interner Player-Bus: eine Datei (Jingle/Intro/Outro) in den Mix spielen."""

    @abstractmethod
    async def stop_player(self) -> None:
        ...

    @abstractmethod
    def mix_monitor_source(self) -> str:
        """ffmpeg-Input-Spezifikation für den finalen Mix (für stream.py)."""
