from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from ..models import ScheduleEntry
from ..schemas import ScheduleEntryCreate, ScheduleEntryOut, ScheduleEntryUpdate

router = APIRouter(prefix="/api/schedule", tags=["schedule"])
public_router = APIRouter(prefix="/api/schedule", tags=["schedule-public"])


@public_router.get("", response_model=list[ScheduleEntryOut])
def list_public_schedule(db: Session = Depends(get_db)):
    entries = (
        db.query(ScheduleEntry)
        .filter(ScheduleEntry.public.is_(True))
        .order_by(ScheduleEntry.position)
        .all()
    )
    return entries


@router.get("/all", response_model=list[ScheduleEntryOut], dependencies=[Depends(require_admin)])
def list_all_schedule(db: Session = Depends(get_db)):
    return db.query(ScheduleEntry).order_by(ScheduleEntry.position).all()


@router.post("", response_model=ScheduleEntryOut, dependencies=[Depends(require_admin)])
def create_entry(body: ScheduleEntryCreate, db: Session = Depends(get_db)):
    max_pos = db.query(ScheduleEntry).count()
    entry = ScheduleEntry(**body.model_dump(), position=max_pos)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=ScheduleEntryOut, dependencies=[Depends(require_admin)])
def update_entry(entry_id: int, body: ScheduleEntryUpdate, db: Session = Depends(get_db)):
    entry = db.get(ScheduleEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sendezeit nicht gefunden")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", dependencies=[Depends(require_admin)])
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(ScheduleEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sendezeit nicht gefunden")
    db.delete(entry)
    db.commit()
    return {"ok": True}
