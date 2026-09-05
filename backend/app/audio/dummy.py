"""Backend ohne echte Audio-Hardware.

`DummyAudioBackend` meldet **keine** Geräte - wenn kein PipeWire läuft, hängt
auch nichts am System, und die UI soll genau das zeigen statt Platzhalter.
`DemoAudioBackend` (nur über `AUDIO_BACKEND=demo`) simuliert Geräte und Pegel
für Screenshots/Entwicklung am Laptop.
"""

import random

from .backend import AudioBackend, DiscoveredBus, PlayerStatus


class DummyAudioBackend(AudioBackend):
    def __init__(self) -> None:
        self._player = PlayerStatus()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def discover_buses(self) -> list[DiscoveredBus]:
        return []

    async def set_mute(self, device_id: str, muted: bool) -> None:
        pass

    async def set_volume(self, device_id: str, volume: float) -> None:
        pass

    async def get_levels(self) -> dict[str, float]:
        return {}

    async def get_master_level(self) -> float:
        return 0.0

    async def play_file(self, path: str, title: str | None = None, segment_id: int | None = None) -> None:
        self._player = PlayerStatus(playing=True, title=title, segment_id=segment_id)

    async def stop_player(self) -> None:
        self._player = PlayerStatus()

    def player_status(self) -> PlayerStatus:
        return self._player

    def mix_monitor_source(self) -> str:
        return "dummy://buschfunk-mix"


DEMO_BUSES = [
    DiscoveredBus(device_id="demo:mixer", display_name="Mischpult / Mikrofone", direction="in"),
    DiscoveredBus(device_id="demo:laptop", display_name="Laptop / Spotify", direction="in"),
    DiscoveredBus(device_id="demo:monitor", display_name="Monitor-Lautsprecher", direction="out"),
]


class DemoAudioBackend(DummyAudioBackend):
    def __init__(self) -> None:
        super().__init__()
        self._muted: dict[str, bool] = {b.device_id: True for b in DEMO_BUSES}
        self._volume: dict[str, float] = {b.device_id: 1.0 for b in DEMO_BUSES}

    async def discover_buses(self) -> list[DiscoveredBus]:
        return list(DEMO_BUSES)

    async def set_mute(self, device_id: str, muted: bool) -> None:
        self._muted[device_id] = muted

    async def set_volume(self, device_id: str, volume: float) -> None:
        self._volume[device_id] = volume

    async def get_levels(self) -> dict[str, float]:
        levels = {}
        for device_id, muted in self._muted.items():
            base = 0.0 if muted else random.uniform(0.15, 0.95)
            levels[device_id] = round(min(1.0, base * self._volume.get(device_id, 1.0)), 3)
        return levels

    async def get_master_level(self) -> float:
        ins = [
            lvl
            for dev, lvl in (await self.get_levels()).items()
            if any(b.device_id == dev and b.direction == "in" for b in DEMO_BUSES)
        ]
        player = random.uniform(0.2, 0.7) if self._player.playing else 0.0
        return round(min(1.0, max([*ins, player], default=0.0)), 3)
