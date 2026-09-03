import hashlib
import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload

from ..auth import require_admin
from ..config import settings
from ..db import get_db
from ..models import Segment, Show

router = APIRouter(prefix="/api/days", tags=["export-import"], dependencies=[Depends(require_admin)])


def _segment_to_dict(segment: Segment) -> dict:
    return {
        "type": segment.type,
        "title": segment.title,
        "time": segment.time,
        "planned_duration": segment.planned_duration,
        "fixed": segment.fixed,
        "notes": segment.notes,
        "media_file": segment.media_file,
        "auto_route": segment.auto_route,
        "children": [_segment_to_dict(c) for c in segment.children],
    }


def _collect_media_files(segments_data: list[dict]) -> set[str]:
    files: set[str] = set()
    for seg in segments_data:
        if seg.get("media_file"):
            files.add(seg["media_file"])
        files |= _collect_media_files(seg.get("children", []))
    return files


@router.get("/{day_id}/export")
def export_day(day_id: int, db: Session = Depends(get_db)):
    show = (
        db.query(Show)
        .options(selectinload(Show.segments).selectinload(Segment.children))
        .filter(Show.id == day_id)
        .first()
    )
    if show is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag nicht gefunden")

    segments_data = [_segment_to_dict(s) for s in show.segments]
    tag_json = {"label": show.label, "segments": segments_data}
    media_files = _collect_media_files(segments_data)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("tag.json", json.dumps(tag_json, indent=2, ensure_ascii=False))
        for filename in media_files:
            src = settings.media_path / filename
            if src.exists():
                zf.write(src, arcname=f"media/{filename}")
    buf.seek(0)

    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in show.label)
    headers = {"Content-Disposition": f'attachment; filename="buschfunk-{safe_label}.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


def _create_segments(db: Session, show_id: int, items: list[dict], parent_id: int | None, name_map: dict[str, str]) -> None:
    for position, item in enumerate(items):
        media_file = item.get("media_file")
        segment = Segment(
            show_id=show_id,
            parent_id=parent_id,
            position=position,
            type=item.get("type", "song"),
            title=item.get("title", "Segment"),
            time=item.get("time"),
            planned_duration=item.get("planned_duration", 0),
            fixed=bool(item.get("fixed", False)),
            notes=item.get("notes"),
            media_file=name_map.get(media_file, media_file) if media_file else None,
            auto_route=item.get("auto_route", []),
        )
        db.add(segment)
        db.flush()
        children = item.get("children") or []
        if children and parent_id is None:
            _create_segments(db, show_id, children, segment.id, name_map)


@router.post("/{day_id}/import")
async def import_day(day_id: int, file: UploadFile, db: Session = Depends(get_db)):
    show = db.get(Show, day_id)
    if show is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag nicht gefunden")

    content = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Keine gültige .zip-Datei")

    try:
        tag_json = json.loads(zf.read("tag.json"))
    except (KeyError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tag.json fehlt oder ist ungültig")

    settings.media_path.mkdir(parents=True, exist_ok=True)
    name_map: dict[str, str] = {}
    for entry in zf.namelist():
        if not entry.startswith("media/") or entry.endswith("/"):
            continue
        original_name = entry.split("/", 1)[1]
        data = zf.read(entry)
        digest = hashlib.sha256(data).hexdigest()[:16]
        suffix = Path(original_name).suffix
        content_name = f"{digest}{suffix}"
        dest = settings.media_path / content_name
        if not dest.exists():
            dest.write_bytes(data)
        name_map[original_name] = content_name

    # bestehenden Ablauf des Tages ersetzen
    for segment in list(show.segments):
        db.delete(segment)
    db.flush()

    show.label = tag_json.get("label", show.label)
    _create_segments(db, show.id, tag_json.get("segments", []), None, name_map)
    db.commit()
    return {"ok": True}
