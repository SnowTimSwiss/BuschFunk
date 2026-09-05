from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from ..auth import require_admin
from ..db import get_db
from ..models import Playlist, PlaylistItem, Track
from ..schemas import (
    PlaylistAddTracks,
    PlaylistCreate,
    PlaylistOut,
    PlaylistReorder,
    PlaylistUpdate,
)

router = APIRouter(prefix="/api/playlists", tags=["playlists"], dependencies=[Depends(require_admin)])


def _load(db: Session, playlist_id: int) -> Playlist:
    playlist = (
        db.query(Playlist)
        .options(selectinload(Playlist.items).selectinload(PlaylistItem.track))
        .filter(Playlist.id == playlist_id)
        .first()
    )
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist nicht gefunden")
    return playlist


@router.get("", response_model=list[PlaylistOut])
def list_playlists(db: Session = Depends(get_db)):
    return (
        db.query(Playlist)
        .options(selectinload(Playlist.items).selectinload(PlaylistItem.track))
        .order_by(Playlist.position, Playlist.id)
        .all()
    )


@router.post("", response_model=PlaylistOut)
def create_playlist(body: PlaylistCreate, db: Session = Depends(get_db)):
    playlist = Playlist(name=body.name.strip() or "Neue Playlist", position=db.query(Playlist).count())
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return playlist


@router.patch("/{playlist_id}", response_model=PlaylistOut)
def update_playlist(playlist_id: int, body: PlaylistUpdate, db: Session = Depends(get_db)):
    playlist = _load(db, playlist_id)
    if body.name is not None and body.name.strip():
        playlist.name = body.name.strip()
    db.commit()
    db.refresh(playlist)
    return playlist


@router.delete("/{playlist_id}")
def delete_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = _load(db, playlist_id)
    db.delete(playlist)
    db.commit()
    return {"ok": True}


@router.post("/{playlist_id}/tracks", response_model=PlaylistOut)
def add_tracks(playlist_id: int, body: PlaylistAddTracks, db: Session = Depends(get_db)):
    playlist = _load(db, playlist_id)
    position = len(playlist.items)
    for track_id in body.track_ids:
        if db.get(Track, track_id) is None:
            continue
        db.add(PlaylistItem(playlist_id=playlist.id, track_id=track_id, position=position))
        position += 1
    db.commit()
    return _load(db, playlist_id)


@router.delete("/{playlist_id}/items/{item_id}", response_model=PlaylistOut)
def remove_item(playlist_id: int, item_id: int, db: Session = Depends(get_db)):
    item = db.get(PlaylistItem, item_id)
    if item is None or item.playlist_id != playlist_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eintrag nicht gefunden")
    db.delete(item)
    db.commit()
    return _load(db, playlist_id)


@router.post("/{playlist_id}/reorder", response_model=PlaylistOut)
def reorder(playlist_id: int, body: PlaylistReorder, db: Session = Depends(get_db)):
    for position, item_id in enumerate(body.ordered_item_ids):
        item = db.get(PlaylistItem, item_id)
        if item is not None and item.playlist_id == playlist_id:
            item.position = position
    db.commit()
    return _load(db, playlist_id)
