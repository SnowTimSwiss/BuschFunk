from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import runtime
from ..auth import require_admin
from ..db import get_db
from ..live_state import broadcast_live_state
from ..models import Bus
from ..schemas import BusMute, BusRename

router = APIRouter(prefix="/api/buses", tags=["buses"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_buses(db: Session = Depends(get_db)):
    levels = {}
    if runtime.audio_backend is not None:
        levels = await runtime.audio_backend.get_levels()
    buses = db.query(Bus).order_by(Bus.id).all()
    return [
        {
            "id": b.id,
            "device_id": b.device_id,
            "display_name": b.display_name,
            "is_muted": b.is_muted,
            "level": levels.get(b.device_id, 0.0),
            "connected": b.device_id in runtime.last_seen_device_ids,
        }
        for b in buses
    ]


@router.patch("/{bus_id}")
async def set_mute(bus_id: int, body: BusMute, db: Session = Depends(get_db)):
    bus = db.get(Bus, bus_id)
    if bus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bus nicht gefunden")
    bus.is_muted = body.is_muted
    db.commit()
    if runtime.audio_backend is not None:
        await runtime.audio_backend.set_mute(bus.device_id, body.is_muted)
    await broadcast_live_state(db)
    return {"ok": True}


@router.patch("/{bus_id}/rename")
def rename_bus(bus_id: int, body: BusRename, db: Session = Depends(get_db)):
    bus = db.get(Bus, bus_id)
    if bus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bus nicht gefunden")
    bus.display_name = body.display_name
    db.commit()
    return {"ok": True}
