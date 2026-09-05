import asyncio
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .. import runtime
from ..audio.probe import probe_duration
from ..auth import require_admin
from ..config import settings
from ..db import get_db
from ..models import Track
from ..schemas import TrackOut, TrackUpdate

router = APIRouter(prefix="/api/tracks", tags=["library"], dependencies=[Depends(require_admin)])

ALLOWED_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus", ".aiff", ".wma"}


def _pretty_title(original_name: str) -> str:
    """Aus "03_Sommer_Hit.mp3" wird "03 Sommer Hit" - besser als der rohe
    Dateiname, und immer noch von Hand ueberschreibbar."""
    stem = Path(original_name).stem.replace("_", " ").strip()
    return " ".join(stem.split()) or original_name


@router.get("", response_model=list[TrackOut])
def list_tracks(kind: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Track)
    if kind:
        query = query.filter(Track.kind == kind)
    return query.order_by(Track.title).all()


@router.post("", response_model=list[TrackOut])
async def upload_tracks(files: list[UploadFile], kind: str = "music", db: Session = Depends(get_db)):
    if kind not in ("music", "jingle"):
        kind = "music"
    settings.media_path.mkdir(parents=True, exist_ok=True)
    created: list[Track] = []

    for upload in files:
        original_name = upload.filename or "Audio"
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{original_name}: dieses Dateiformat wird nicht unterstuetzt.",
            )
        filename = f"{uuid.uuid4().hex}{suffix}"
        dest = settings.media_path / filename
        with dest.open("wb") as target:
            shutil.copyfileobj(upload.file, target)

        track = Track(
            filename=filename,
            original_name=original_name,
            title=_pretty_title(original_name),
            kind=kind,
            duration=await asyncio.to_thread(probe_duration, dest),
        )
        db.add(track)
        created.append(track)

    db.commit()
    for track in created:
        db.refresh(track)
    return created


@router.patch("/{track_id}", response_model=TrackOut)
def update_track(track_id: int, body: TrackUpdate, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Titel nicht gefunden")
    if body.title is not None and body.title.strip():
        track.title = body.title.strip()
    if body.kind in ("music", "jingle"):
        track.kind = body.kind
    db.commit()
    db.refresh(track)
    return track


@router.delete("/{track_id}")
async def delete_track(track_id: int, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Titel nicht gefunden")
    filename = track.filename
    db.delete(track)
    db.commit()

    if runtime.player is not None:
        await runtime.player.drop_track(track_id)
    path = settings.media_path / filename
    if path.exists():
        path.unlink()
    return {"ok": True}
