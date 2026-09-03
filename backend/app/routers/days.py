import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from ..auth import require_admin
from ..config import settings
from ..db import get_db
from ..live_state import broadcast_live_state, get_or_create_live_state
from ..models import Segment, Show
from ..schemas import (
    SegmentCreate,
    SegmentOut,
    SegmentReorder,
    SegmentUpdate,
    ShowCreate,
    ShowOut,
    ShowSummary,
    ShowUpdate,
)

router = APIRouter(prefix="/api", tags=["days"])


def _show_query(db: Session):
    return db.query(Show).options(
        selectinload(Show.segments).selectinload(Segment.children)
    )


@router.get("/days", response_model=list[ShowSummary])
def list_days(db: Session = Depends(get_db)):
    shows = db.query(Show).order_by(Show.position).all()
    return [
        ShowSummary(id=s.id, label=s.label, segment_count=len(s.segments))
        for s in shows
    ]


@router.post("/days", response_model=ShowOut, dependencies=[Depends(require_admin)])
def create_day(body: ShowCreate, db: Session = Depends(get_db)):
    max_pos = db.query(Show).count()
    show = Show(label=body.label, position=max_pos)
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


@router.get("/days/{day_id}", response_model=ShowOut)
def get_day(day_id: int, db: Session = Depends(get_db)):
    show = _show_query(db).filter(Show.id == day_id).first()
    if show is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag nicht gefunden")
    return show


@router.patch("/days/{day_id}", response_model=ShowOut, dependencies=[Depends(require_admin)])
def update_day(day_id: int, body: ShowUpdate, db: Session = Depends(get_db)):
    show = db.get(Show, day_id)
    if show is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag nicht gefunden")
    if body.label is not None:
        show.label = body.label
    db.commit()
    db.refresh(show)
    return show


@router.delete("/days/{day_id}", dependencies=[Depends(require_admin)])
async def delete_day(day_id: int, db: Session = Depends(get_db)):
    show = db.get(Show, day_id)
    if show is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag nicht gefunden")
    db.delete(show)
    state = get_or_create_live_state(db)
    if state.active_show_id == day_id:
        state.active_show_id = None
        state.current_segment_id = None
    db.commit()
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/days/{day_id}/segments", response_model=SegmentOut, dependencies=[Depends(require_admin)])
def create_segment(day_id: int, body: SegmentCreate, db: Session = Depends(get_db)):
    show = db.get(Show, day_id)
    if show is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag nicht gefunden")
    if body.parent_id is not None:
        parent = db.get(Segment, body.parent_id)
        if parent is None or parent.show_id != day_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ungültiges Eltern-Segment")
        if parent.parent_id is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nur eine Verschachtelungsebene erlaubt")
        max_pos = len(parent.children)
    else:
        max_pos = len(show.segments)

    segment = Segment(
        show_id=day_id,
        parent_id=body.parent_id,
        position=max_pos,
        type=body.type,
        title=body.title,
        time=body.time,
        planned_duration=body.planned_duration,
        fixed=body.fixed,
        notes=body.notes,
        media_file=body.media_file,
        auto_route=body.auto_route,
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


@router.patch("/segments/{segment_id}", response_model=SegmentOut, dependencies=[Depends(require_admin)])
async def update_segment(segment_id: int, body: SegmentUpdate, db: Session = Depends(get_db)):
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment nicht gefunden")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(segment, field, value)
    db.commit()
    db.refresh(segment)
    await broadcast_live_state(db)
    return segment


@router.delete("/segments/{segment_id}", dependencies=[Depends(require_admin)])
async def delete_segment(segment_id: int, db: Session = Depends(get_db)):
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment nicht gefunden")
    db.delete(segment)
    state = get_or_create_live_state(db)
    if state.current_segment_id == segment_id:
        state.current_segment_id = None
        state.elapsed_offset_seconds = 0
    db.commit()
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/days/{day_id}/segments/reorder", dependencies=[Depends(require_admin)])
def reorder_segments(day_id: int, body: SegmentReorder, db: Session = Depends(get_db)):
    for position, segment_id in enumerate(body.ordered_ids):
        segment = db.get(Segment, segment_id)
        if segment is None or segment.show_id != day_id:
            continue
        segment.position = position
        segment.parent_id = body.parent_id
    db.commit()
    return {"ok": True}


@router.post("/segments/{segment_id}/media", response_model=SegmentOut, dependencies=[Depends(require_admin)])
async def upload_segment_media(segment_id: int, file: UploadFile, db: Session = Depends(get_db)):
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment nicht gefunden")

    suffix = Path(file.filename or "").suffix
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    dest = settings.media_path / safe_name
    settings.media_path.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    segment.media_file = safe_name
    db.commit()
    db.refresh(segment)
    return segment

