from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import runtime
from ..auth import require_admin
from ..db import get_db
from ..live_state import broadcast_live_state

router = APIRouter(prefix="/api/reporter", tags=["reporter"], dependencies=[Depends(require_admin)])


class ReporterMuteRequest(BaseModel):
    muted: bool


def _reporter():
    if runtime.reporter is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Reporter-Kanal ist noch nicht bereit")
    return runtime.reporter


@router.post("/pair")
async def pair(request: Request, db: Session = Depends(get_db)):
    pairing = await _reporter().create_pair()
    url = f"{str(request.base_url).rstrip('/')}/reporter/?pair={pairing['token']}"
    try:
        import segno
        qr_svg = segno.make(url).svg_data_uri(scale=5)
    except ImportError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "QR-Code-Modul fehlt") from exc
    await broadcast_live_state(db)
    return {"url": url, "qr_svg": qr_svg, "expires_at": pairing["expires_at"]}


@router.post("/disconnect")
async def disconnect(db: Session = Depends(get_db)):
    await _reporter().revoke()
    await broadcast_live_state(db)
    return {"ok": True}


@router.post("/mute")
async def mute(body: ReporterMuteRequest, db: Session = Depends(get_db)):
    await _reporter().set_muted(body.muted)
    await broadcast_live_state(db)
    return {"ok": True}


@router.get("/status")
async def reporter_status():
    return _reporter().state()
