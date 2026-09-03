from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from .. import runtime
from ..auth import require_admin
from ..db import get_db
from ..live_state import build_live_payload, broadcast_live_state, flatten_playable, get_or_create_live_state
from ..models import Bus, Segment, Show
from ..schemas import GoToSegment, NotesUpdate

router = APIRouter(prefix="/api/live", tags=["live"], dependencies=[Depends(require_admin)])
public_router = APIRouter(prefix="/api/live", tags=["live-public"])


def _load_show(db: Session, show_id: int) -> Show:
    show = (
        db.query(Show)
        .options(selectinload(Show.segments).selectinload(Segment.children))
        .filter(Show.id == show_id)
        .first()
    )
    if show is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag nicht gefunden")
    return show


def _reset_to_segment(state, segment_id: int | None) -> None:
    state.current_segment_id = segment_id
    state.elapsed_offset_seconds = 0
    state.segment_started_at = datetime.now(timezone.utc) if state.is_on_air else None


@public_router.get("/status")
async def get_status(db: Session = Depends(get_db)):
    return await build_live_payload(db)


@router.post("/select-show")
async def select_show(body: dict, db: Session = Depends(get_db)):
    show_id = body.get("show_id")
    show = _load_show(db, show_id)
    state = get_or_create_live_state(db)
    state.active_show_id = show.id
    flat = flatten_playable(show)
    _reset_to_segment(state, flat[0].id if flat else None)
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


@router.post("/goto")
async def goto_segment(body: GoToSegment, db: Session = Depends(get_db)):
    segment = db.get(Segment, body.segment_id)
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment nicht gefunden")
    state = get_or_create_live_state(db)
    _reset_to_segment(state, segment.id)
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


@router.post("/next")
async def next_segment(db: Session = Depends(get_db)):
    state = get_or_create_live_state(db)
    if state.active_show_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kein Tag ausgewählt")
    show = _load_show(db, state.active_show_id)
    flat = flatten_playable(show)
    ids = [s.id for s in flat]
    if state.current_segment_id in ids:
        idx = ids.index(state.current_segment_id)
        new_id = ids[idx + 1] if idx + 1 < len(ids) else ids[idx]
    else:
        new_id = ids[0] if ids else None
    _reset_to_segment(state, new_id)
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


@router.post("/prev")
async def prev_segment(db: Session = Depends(get_db)):
    state = get_or_create_live_state(db)
    if state.active_show_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kein Tag ausgewählt")
    show = _load_show(db, state.active_show_id)
    flat = flatten_playable(show)
    ids = [s.id for s in flat]
    if state.current_segment_id in ids:
        idx = ids.index(state.current_segment_id)
        new_id = ids[idx - 1] if idx > 0 else ids[idx]
    else:
        new_id = ids[0] if ids else None
    _reset_to_segment(state, new_id)
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


@router.post("/on-air")
async def set_on_air(body: dict, db: Session = Depends(get_db)):
    is_on_air = bool(body.get("is_on_air"))
    state = get_or_create_live_state(db)
    if is_on_air and not state.is_on_air:
        state.segment_started_at = datetime.now(timezone.utc)
    elif not is_on_air and state.is_on_air:
        from ..live_state import compute_elapsed_seconds

        state.elapsed_offset_seconds = compute_elapsed_seconds(state)
        state.segment_started_at = None
    state.is_on_air = is_on_air
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


@router.post("/notes")
async def update_notes(body: NotesUpdate, db: Session = Depends(get_db)):
    state = get_or_create_live_state(db)
    if state.current_segment_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kein aktives Segment")
    segment = db.get(Segment, state.current_segment_id)
    segment.notes = body.notes
    db.commit()
    await broadcast_live_state(db)
    return {"ok": True}


async def _set_notfall(db: Session, mode: str | None, message: str | None) -> dict:
    state = get_or_create_live_state(db)
    state.notfall_mode = mode
    state.notfall_message = message
    state.notfall_acked = mode is None
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


@router.post("/emergency/sos")
async def emergency_sos(db: Session = Depends(get_db)):
    """SOS: alle Hardware-Busse stumm, interner Player-Bus bleibt aktiv."""
    if runtime.audio_backend is not None:
        for bus in db.query(Bus).all():
            await runtime.audio_backend.set_mute(bus.device_id, True)
            bus.is_muted = True
    db.commit()
    return await _set_notfall(db, "sos", "NOTFALL: nur Playlist läuft – Mischpult & weitere Busse stumm")


@router.post("/emergency/mute-all")
async def emergency_mute_all(db: Session = Depends(get_db)):
    """Alles stumm: auch der interne Player-Bus wird beendet."""
    if runtime.audio_backend is not None:
        await runtime.audio_backend.mute_all()
    for bus in db.query(Bus).all():
        bus.is_muted = True
    db.commit()
    return await _set_notfall(db, "mute_all", "ALLES STUMM – kein Bus sendet gerade Audio")


@router.post("/emergency/unterbruch")
async def emergency_unterbruch(db: Session = Depends(get_db)):
    return await _set_notfall(
        db, "unterbruch", "TECHNISCHER UNTERBRUCH – Hörer:innen sehen einen Platzhalter-Hinweis"
    )


@router.post("/emergency/ack")
async def emergency_ack(db: Session = Depends(get_db)):
    state = get_or_create_live_state(db)
    state.notfall_acked = True
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)
