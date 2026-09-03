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


async def build_live_payload(db: Session) -> dict:
    state = get_or_create_live_state(db)
    current_segment = db.get(Segment, state.current_segment_id) if state.current_segment_id else None

    buses_db = db.query(Bus).order_by(Bus.id).all()
    levels: dict[str, float] = {}
    if runtime.audio_backend is not None:
        try:
            levels = await runtime.audio_backend.get_levels()
        except Exception:
            levels = {}

    bus_payload = [
        {
            "id": b.id,
            "device_id": b.device_id,
            "display_name": b.display_name,
            "direction": b.direction,
            "is_muted": b.is_muted,
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
        "notfall_mode": state.notfall_mode,
        "notfall_message": state.notfall_message,
        "notfall_acked": state.notfall_acked,
        "buses": bus_payload,
    }


async def broadcast_live_state(db: Session) -> None:
    payload = await build_live_payload(db)
    await manager.broadcast(payload)
