from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from .. import runtime
from ..audio.player import QueueEntry
from ..auth import require_admin
from ..config import settings
from ..db import get_db
from ..live_state import broadcast_live_state
from ..models import Playlist, PlaylistItem, Track
from ..schemas import (
    JingleRequest,
    PlayRequest,
    QueueJump,
    QueueRequest,
    RepeatRequest,
    VolumeRequest,
)

router = APIRouter(prefix="/api/player", tags=["player"], dependencies=[Depends(require_admin)])


def _player():
    if runtime.player is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Player ist noch nicht bereit")
    return runtime.player


def _entry(track: Track) -> QueueEntry | None:
    path = settings.media_path / track.filename
    if not path.exists():
        return None
    return QueueEntry(track_id=track.id, title=track.title, path=str(path), duration=track.duration)


def _entries_for_tracks(db: Session, track_ids: list[int]) -> list[QueueEntry]:
    entries = []
    for track_id in track_ids:
        track = db.get(Track, track_id)
        if track is not None:
            entry = _entry(track)
            if entry is not None:
                entries.append(entry)
    return entries


def _entries_for_playlist(db: Session, playlist_id: int) -> list[QueueEntry]:
    playlist = (
        db.query(Playlist)
        .options(selectinload(Playlist.items).selectinload(PlaylistItem.track))
        .filter(Playlist.id == playlist_id)
        .first()
    )
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist nicht gefunden")
    entries = [_entry(item.track) for item in playlist.items]
    return [e for e in entries if e is not None]


@router.post("/play")
async def play(body: PlayRequest, db: Session = Depends(get_db)):
    player = _player()
    if body.playlist_id is not None:
        entries = _entries_for_playlist(db, body.playlist_id)
        if not entries:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Diese Playlist ist leer")
        await player.play(entries, shuffle=body.shuffle)
    elif body.track_id is not None:
        entries = _entries_for_tracks(db, [body.track_id])
        if not entries:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei zu diesem Titel fehlt")
        await player.play_now(entries[0])
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kein Titel und keine Playlist angegeben")
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/queue")
async def queue(body: QueueRequest, db: Session = Depends(get_db)):
    player = _player()
    entries = (
        _entries_for_playlist(db, body.playlist_id)
        if body.playlist_id is not None
        else _entries_for_tracks(db, body.track_ids)
    )
    if not entries:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nichts zum Anhaengen gefunden")
    await player.enqueue(entries)
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/pause")
async def pause(db: Session = Depends(get_db)):
    await _player().toggle_pause()
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/next")
async def next_track(db: Session = Depends(get_db)):
    await _player().skip(1)
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/prev")
async def prev_track(db: Session = Depends(get_db)):
    await _player().skip(-1)
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/stop")
async def stop(db: Session = Depends(get_db)):
    await _player().clear()
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/jump")
async def jump(body: QueueJump, db: Session = Depends(get_db)):
    await _player().jump(body.index)
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/remove")
async def remove(body: QueueJump, db: Session = Depends(get_db)):
    await _player().remove(body.index)
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/volume")
async def volume(body: VolumeRequest, db: Session = Depends(get_db)):
    await _player().set_volume(body.volume)
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/repeat")
async def repeat(body: RepeatRequest, db: Session = Depends(get_db)):
    _player().set_repeat(body.repeat)
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/jingle")
async def play_jingle(body: JingleRequest, db: Session = Depends(get_db)):
    if runtime.jingles is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Player ist noch nicht bereit")
    track = db.get(Track, body.track_id)
    if track is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Titel nicht gefunden")
    path = settings.media_path / track.filename
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei zu diesem Titel fehlt")
    await runtime.jingles.play(str(path), track.title, track.duration)
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/jingle/stop")
async def stop_jingle(db: Session = Depends(get_db)):
    if runtime.jingles is not None:
        await runtime.jingles.stop()
    await broadcast_live_state(db)
    return {"ok": True}
