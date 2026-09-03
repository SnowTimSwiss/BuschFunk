import random

from .backend import AudioBackend, DiscoveredBus

FAKE_BUSES = [
    DiscoveredBus(device_id="dummy:mixer", display_name="Mischpult / Mikrofone"),
    DiscoveredBus(device_id="dummy:laptop", display_name="Laptop / Spotify"),
]


class DummyAudioBackend(AudioBackend):
    """Simuliert Busse/Pegel ohne echte Audio-Hardware - für Entwicklung,
    Demos und automatisierte Tests. Wird automatisch verwendet, wenn kein
    PipeWire-Server erreichbar ist."""

    def __init__(self) -> None:
        self._muted: dict[str, bool] = {b.device_id: True for b in FAKE_BUSES}
        self._player_playing = False

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def discover_buses(self) -> list[DiscoveredBus]:
        return list(FAKE_BUSES)

    async def set_mute(self, device_id: str, muted: bool) -> None:
        self._muted[device_id] = muted

    async def get_levels(self) -> dict[str, float]:
        levels = {}
        for device_id, muted in self._muted.items():
            levels[device_id] = 0.0 if muted else round(random.uniform(0.15, 0.95), 3)
        levels["player"] = round(random.uniform(0.1, 0.8), 3) if self._player_playing else 0.0
        return levels

    async def mute_all(self) -> None:
        for device_id in self._muted:
            self._muted[device_id] = True
        self._player_playing = False

    async def play_file(self, path: str) -> None:
        self._player_playing = True

    async def stop_player(self) -> None:
        self._player_playing = False

    def mix_monitor_source(self) -> str:
        return "dummy://buschfunk-mix"
