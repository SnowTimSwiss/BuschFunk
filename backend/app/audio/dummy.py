"""Backend ohne echte Audio-Hardware.

`DummyAudioBackend` meldet **keine** Geraete - wenn kein PipeWire laeuft, haengt
auch nichts am System, und die UI soll genau das zeigen statt Platzhalter.
`DemoAudioBackend` (nur ueber `AUDIO_BACKEND=demo`) simuliert Geraete und Pegel
fuer Screenshots/Entwicklung am Laptop.
"""

import random

from .backend import AudioBackend, DiscoveredBus


class DummyAudioBackend(AudioBackend):
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def discover_buses(self) -> list[DiscoveredBus]:
        return []

    async def set_mute(self, device_id: str, muted: bool) -> None:
        pass

    async def set_master_mute(self, muted: bool) -> None:
        pass

    async def set_volume(self, device_id: str, volume: float) -> None:
        pass

    async def set_input_mode(self, device_id: str, channel_mode: str) -> None:
        pass

    async def get_levels(self) -> dict[str, float]:
        return {}

    async def get_master_level(self) -> float:
        return 0.0

    def playback_sink(self) -> str | None:
        return None  # Player laeuft simuliert mit, es kommt aber kein Ton raus

    async def set_stream_volume(self, stream_name: str, volume: float) -> bool:
        return True

    def mix_monitor_source(self) -> str:
        return "dummy://buschfunk-mix"


DEMO_BUSES = [
    DiscoveredBus(device_id="demo:mixer", display_name="Mischpult / Mikrofone", direction="in"),
    DiscoveredBus(device_id="demo:laptop", display_name="Laptop", direction="in"),
    DiscoveredBus(device_id="demo:monitor", display_name="Monitor-Lautsprecher", direction="out"),
]


class DemoAudioBackend(DummyAudioBackend):
    def __init__(self) -> None:
        self._muted: dict[str, bool] = {b.device_id: True for b in DEMO_BUSES}
        self._volume: dict[str, float] = {b.device_id: 1.0 for b in DEMO_BUSES}
        self._master_muted = True

    async def discover_buses(self) -> list[DiscoveredBus]:
        return list(DEMO_BUSES)

    async def set_mute(self, device_id: str, muted: bool) -> None:
        self._muted[device_id] = muted

    async def set_master_mute(self, muted: bool) -> None:
        self._master_muted = muted

    async def set_volume(self, device_id: str, volume: float) -> None:
        self._volume[device_id] = volume

    async def get_levels(self) -> dict[str, float]:
        levels = {}
        for device_id, muted in self._muted.items():
            base = 0.0 if muted else random.uniform(0.15, 0.95)
            levels[device_id] = round(min(1.0, base * self._volume.get(device_id, 1.0)), 3)
        return levels

    async def get_master_level(self) -> float:
        if self._master_muted:
            return 0.0
        from .. import runtime

        ins = [
            level
            for device_id, level in (await self.get_levels()).items()
            if any(b.device_id == device_id and b.direction == "in" for b in DEMO_BUSES)
        ]
        music = 0.0
        if runtime.player is not None and runtime.player.state()["playing"]:
            music = random.uniform(0.25, 0.75) * runtime.player.volume
        return round(min(1.0, max([*ins, music], default=0.0)), 3)
