from sqlalchemy.orm import Session

from . import runtime
from .models import Bus, LiveState
from .ws import manager


def get_or_create_live_state(db: Session) -> LiveState:
    state = db.get(LiveState, 1)
    if state is None:
        state = LiveState(id=1)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


async def apply_bus_state(bus: Bus) -> None:
    """Mute und Lautstaerke auf das Geraet legen.

    Der Sendungszustand wird bewusst nicht auf einzelne Geraete angewendet.
    Off-Air schaltet stattdessen den gemeinsamen Master-Ausgang; so bleiben
    die persoenlichen Mute-Schalter und Lautstaerken aller Geraete unveraendert.
    """
    backend = runtime.audio_backend
    if backend is None:
        return
    await backend.set_mute(bus.device_id, bus.is_muted)
    await backend.set_volume(bus.device_id, bus.volume)
    if bus.direction == "in":
        # idempotent - legt/entfernt die Kanalkorrektur nur bei tatsaechlicher
        # Aenderung an; so landet ein gespeicherter Modus auch nach einem
        # Neustart oder erneuten Einstecken wieder richtig.
        await backend.set_input_mode(bus.device_id, bus.channel_mode)


async def apply_all_buses(db: Session) -> None:
    for bus in db.query(Bus).all():
        if bus.device_id in runtime.last_seen_device_ids:
            await apply_bus_state(bus)


async def apply_on_air_transition(db: Session, on_air: bool) -> None:
    """Die komplette gemischte Ausgabe am Master stoppen oder freigeben.

    Quellen, Einzel-Mutes, Musik und Jingles laufen unveraendert weiter. Beim
    Umschalten kommt deshalb genau der aktuelle Mix wieder aus dem Master.
    """
    if runtime.audio_backend is not None:
        await runtime.audio_backend.set_master_mute(not on_air)


async def _levels() -> tuple[dict[str, float], float]:
    if runtime.audio_backend is None:
        return {}, 0.0
    try:
        return await runtime.audio_backend.get_levels(), await runtime.audio_backend.get_master_level()
    except Exception:
        return {}, 0.0


def _player_state() -> dict:
    if runtime.player is None:
        return {"playing": False, "paused": False, "title": None, "position": 0.0,
                "duration": 0.0, "queue_length": 0, "queue_index": 0, "queue_ahead": [],
                "repeat": True, "volume": 1.0, "track_id": None, "level": 0.0}
    return runtime.player.state()


def _jingle_state() -> dict:
    if runtime.jingles is None:
        return {"playing": False, "title": None, "level": 0.0}
    return runtime.jingles.state()


async def build_live_payload(db: Session) -> dict:
    state = get_or_create_live_state(db)
    buses_db = db.query(Bus).order_by(Bus.direction, Bus.id).all()
    levels, master_level = await _levels()

    return {
        "type": "live_state",
        "on_air": state.on_air,
        "buses": [
            {
                "id": b.id,
                "device_id": b.device_id,
                "display_name": b.display_name,
                "direction": b.direction,
                "is_muted": b.is_muted,
                "volume": b.volume,
                "channel_mode": b.channel_mode,
                "level": levels.get(b.device_id, 0.0),
                "connected": b.device_id in runtime.last_seen_device_ids,
            }
            for b in buses_db
        ],
        "master_level": master_level,
        "player": _player_state(),
        "jingle": _jingle_state(),
        "audio_ready": runtime.audio_ready,
    }


async def build_meters_payload(db: Session) -> dict:
    """Kleines, haeufig gesendetes Paket nur mit Pegeln und Abspielposition -
    damit Meter und Fortschrittsbalken fluessig laufen, ohne jedes Mal den
    ganzen Zustand zu verschicken."""
    levels, master_level = await _levels()
    id_by_device = {b.device_id: b.id for b in db.query(Bus.id, Bus.device_id).all()}
    player = _player_state()
    jingle = _jingle_state()
    return {
        "type": "meters",
        "levels": {str(id_by_device[dev]): lvl for dev, lvl in levels.items() if dev in id_by_device},
        "master_level": master_level,
        "position": player["position"],
        "playing": player["playing"],
        "player_level": player["level"],
        "jingle_level": jingle["level"],
    }


async def broadcast_live_state(db: Session) -> None:
    await manager.broadcast(await build_live_payload(db))
