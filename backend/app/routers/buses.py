from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import runtime
from ..auth import require_admin
from ..db import get_db
from ..live_state import apply_bus_state, broadcast_live_state
from ..models import Bus
from ..schemas import BusRename, BusUpdate

router = APIRouter(prefix="/api/buses", tags=["buses"], dependencies=[Depends(require_admin)])

# Eingaenge duerfen deutlich staerker aufgedreht werden als Ausgaenge - manche
# Mischpultkanaele liefern selbst bei 150% noch zu leise. Monitor-Lautsprecher
# bleiben aus Ruecksicht auf die Ohren/Boxen bei 150% gedeckelt.
MAX_VOLUME_IN = 3.0
MAX_VOLUME_OUT = 1.5
CHANNEL_MODES = {"stereo", "mono", "left", "right"}


def _bus_dict(b: Bus, levels: dict[str, float]) -> dict:
    return {
        "id": b.id,
        "device_id": b.device_id,
        "display_name": b.display_name,
        "direction": b.direction,
        "is_muted": b.is_muted,
        "volume": b.volume,
        "channel_mode": b.channel_mode,
        "level": levels.get(b.device_id, 0.0),
        "connected": b.device_id in runtime.last_seen_device_ids,
    }


@router.get("")
async def list_buses(db: Session = Depends(get_db)):
    levels = {}
    if runtime.audio_backend is not None:
        levels = await runtime.audio_backend.get_levels()
    buses = db.query(Bus).order_by(Bus.direction, Bus.id).all()
    return [_bus_dict(b, levels) for b in buses]


@router.patch("/{bus_id}")
async def update_bus(bus_id: int, body: BusUpdate, db: Session = Depends(get_db)):
    bus = db.get(Bus, bus_id)
    if bus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gerät nicht gefunden")
    if body.is_muted is not None:
        bus.is_muted = body.is_muted
    if body.volume is not None:
        ceiling = MAX_VOLUME_IN if bus.direction == "in" else MAX_VOLUME_OUT
        bus.volume = max(0.0, min(ceiling, body.volume))
    if body.channel_mode is not None and body.channel_mode in CHANNEL_MODES:
        bus.channel_mode = body.channel_mode
    db.commit()
    await apply_bus_state(bus)
    await broadcast_live_state(db)
    return {"ok": True}


@router.patch("/{bus_id}/rename")
async def rename_bus(bus_id: int, body: BusRename, db: Session = Depends(get_db)):
    bus = db.get(Bus, bus_id)
    if bus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gerät nicht gefunden")
    bus.display_name = body.display_name.strip() or bus.display_name
    db.commit()
    await broadcast_live_state(db)
    return {"ok": True}


@router.delete("/{bus_id}")
async def forget_bus(bus_id: int, db: Session = Depends(get_db)):
    """Ein Gerät vergessen (Name/Zustand verwerfen). Nur sinnvoll für Geräte,
    die gerade nicht angeschlossen sind - angeschlossene tauchen bei der
    nächsten Erkennung sofort wieder auf."""
    bus = db.get(Bus, bus_id)
    if bus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gerät nicht gefunden")
    db.delete(bus)
    db.commit()
    await broadcast_live_state(db)
    return {"ok": True}
