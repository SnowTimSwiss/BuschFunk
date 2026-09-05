from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import runtime
from .models import Bus, LiveState, Segment, Show
from .ws import manager


def flatten_playable(show: Show) -> list[Segment]:
    """Top-level Segmente ohne Kinder + die Kinder von Segmenten mit Kindern
    (eine Verschachtelungsebene) - genau diese Liste wird von Weiter/Zurück
    durchlaufen, nie der Eltern-Knoten selbst."""
    flat: list[Segment] = []
    for seg in show.segments:
        if seg.children:
            flat.extend(seg.children)
        else:
            flat.append(seg)
    return flat


def get_or_create_live_state(db: Session) -> LiveState:
    state = db.get(LiveState, 1)
    if state is None:
        state = LiveState(id=1)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def compute_elapsed_seconds(state: LiveState) -> int:
    elapsed = state.elapsed_offset_seconds
    if state.is_on_air and state.segment_started_at is not None:
        started = state.segment_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed += int((datetime.now(timezone.utc) - started).total_seconds())
    return elapsed


async def _levels() -> tuple[dict[str, float], float]:
    if runtime.audio_backend is None:
        return {}, 0.0
    try:
        return await runtime.audio_backend.get_levels(), await runtime.audio_backend.get_master_level()
    except Exception:
        return {}, 0.0


def _player_payload() -> dict:
    if runtime.audio_backend is None:
        return {"playing": False, "title": None, "segment_id": None}
    status = runtime.audio_backend.player_status()
    return {"playing": status.playing, "title": status.title, "segment_id": status.segment_id}


async def build_live_payload(db: Session) -> dict:
    state = get_or_create_live_state(db)
    current_segment = db.get(Segment, state.current_segment_id) if state.current_segment_id else None

    buses_db = db.query(Bus).order_by(Bus.direction, Bus.id).all()
    levels, master_level = await _levels()

    bus_payload = [
        {
            "id": b.id,
            "device_id": b.device_id,
            "display_name": b.display_name,
            "direction": b.direction,
            "is_muted": b.is_muted,
            "volume": b.volume,
            "level": levels.get(b.device_id, 0.0),
            "connected": b.device_id in runtime.last_seen_device_ids,
        }
        for b in buses_db
    ]

    return {
        "type": "live_state",
        "active_show_id": state.active_show_id,
        "current_segment_id": state.current_segment_id,
        "current_segment_title": current_segment.title if current_segment else None,
        "elapsed_seconds": compute_elapsed_seconds(state),
        "is_on_air": state.is_on_air,
        "buses": bus_payload,
        "master_level": master_level,
        "player": _player_payload(),
        "audio_ready": runtime.audio_ready,
    }


async def build_meters_payload(db: Session) -> dict:
    """Kleines, häufig gesendetes Paket nur mit den Pegeln - damit die Meter
    flüssig laufen, ohne jedes Mal den ganzen Live-Zustand zu verschicken."""
    levels, master_level = await _levels()
    id_by_device = {b.device_id: b.id for b in db.query(Bus.id, Bus.device_id).all()}
    return {
        "type": "meters",
        "levels": {str(id_by_device[dev]): lvl for dev, lvl in levels.items() if dev in id_by_device},
        "master_level": master_level,
        "player_playing": _player_payload()["playing"],
    }


async def broadcast_live_state(db: Session) -> None:
    payload = await build_live_payload(db)
    await manager.broadcast(payload)
