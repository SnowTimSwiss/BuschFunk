import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from .. import runtime
from ..auth import require_admin
from ..config import settings
from ..db import get_db
from ..live_state import (
    build_live_payload,
    broadcast_live_state,
    compute_elapsed_seconds,
    flatten_playable,
    get_or_create_live_state,
)
from ..models import Segment, Show
from ..schemas import GoToSegment, NotesUpdate, PlayMedia

logger = logging.getLogger("buschfunk.live")

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


async def play_segment_media(db: Session, segment: Segment) -> bool:
    """Die am Segment hinterlegte Datei über den internen Player in den Mix
    spielen. Gibt False zurück, wenn nichts hinterlegt oder die Datei weg ist."""
    if runtime.audio_backend is None or not segment.media_file:
        return False
    path = settings.media_path / segment.media_file
    if not path.exists():
        logger.warning("Mediendatei fehlt: %s", path)
        return False
    await runtime.audio_backend.play_file(str(path), title=segment.title, segment_id=segment.id)
    return True


async def _reset_to_segment(db: Session, state, segment_id: int | None) -> None:
    state.current_segment_id = segment_id
    state.elapsed_offset_seconds = 0
    state.segment_started_at = datetime.now(timezone.utc) if state.is_on_air else None
    runtime.fired_end_media.discard(segment_id)  # neuer Durchlauf, "am Ende" darf wieder feuern

    segment = db.get(Segment, segment_id) if segment_id else None
    if segment and state.is_on_air and segment.media_trigger == "start":
        await play_segment_media(db, segment)


@public_router.get("/status")
async def get_status(db: Session = Depends(get_db)):
    return await build_live_payload(db)


@router.post("/select-show")
async def select_show(body: dict, db: Session = Depends(get_db)):
    show_id = body.get("show_id")
    show = _load_show(db, show_id)
    state = get_or_create_live_state(db)
    keep = state.active_show_id == show.id
    state.active_show_id = show.id
    if not keep:
        flat = flatten_playable(show)
        await _reset_to_segment(db, state, flat[0].id if flat else None)
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


@router.post("/goto")
async def goto_segment(body: GoToSegment, db: Session = Depends(get_db)):
    segment = db.get(Segment, body.segment_id)
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment nicht gefunden")
    state = get_or_create_live_state(db)
    state.active_show_id = segment.show_id
    await _reset_to_segment(db, state, segment.id)
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


async def _step(db: Session, delta: int) -> dict:
    state = get_or_create_live_state(db)
    if state.active_show_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kein Tag ausgewählt")
    show = _load_show(db, state.active_show_id)
    ids = [s.id for s in flatten_playable(show)]
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Der Tag hat noch keine Segmente")
    if state.current_segment_id in ids:
        idx = ids.index(state.current_segment_id)
        new_id = ids[max(0, min(len(ids) - 1, idx + delta))]
    else:
        new_id = ids[0]
    await _reset_to_segment(db, state, new_id)
    db.commit()
    await broadcast_live_state(db)
    return await build_live_payload(db)


@router.post("/next")
async def next_segment(db: Session = Depends(get_db)):
    return await _step(db, +1)


@router.post("/prev")
async def prev_segment(db: Session = Depends(get_db)):
    return await _step(db, -1)


@router.post("/restart-timer")
async def restart_timer(db: Session = Depends(get_db)):
    """Uhr des aktuellen Segments zurück auf null - ohne das Segment zu wechseln."""
    state = get_or_create_live_state(db)
    state.elapsed_offset_seconds = 0
    state.segment_started_at = datetime.now(timezone.utc) if state.is_on_air else None
    runtime.fired_end_media.discard(state.current_segment_id)
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


@router.post("/play-media")
async def play_media(body: PlayMedia, db: Session = Depends(get_db)):
    state = get_or_create_live_state(db)
    segment_id = body.segment_id or state.current_segment_id
    segment = db.get(Segment, segment_id) if segment_id else None
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment nicht gefunden")
    if not await play_segment_media(db, segment):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An diesem Segment hängt keine Audiodatei")
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/stop-media")
async def stop_media(db: Session = Depends(get_db)):
    if runtime.audio_backend is not None:
        await runtime.audio_backend.stop_player()
    await broadcast_live_state(db)
    return {"ok": True}
