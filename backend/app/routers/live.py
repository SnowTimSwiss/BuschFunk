from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from ..live_state import apply_on_air_transition, broadcast_live_state, build_live_payload, get_or_create_live_state
from ..schemas import OnAirRequest

router = APIRouter(prefix="/api/live", tags=["live"], dependencies=[Depends(require_admin)])
public_router = APIRouter(prefix="/api/live", tags=["live-public"])


@public_router.get("/status")
async def status(db: Session = Depends(get_db)):
    return await build_live_payload(db)


@router.post("/on-air")
async def set_on_air(body: OnAirRequest, db: Session = Depends(get_db)):
    """Auf Sendung gehen heisst: Mikrofone gehen auf UND die Musik faded
    wieder ein. Off air schliesst die Mikrofone und faded die Musik aus (ein
    laufender Jingle wird abgebrochen) - der Icecast-Stream selbst bleibt die
    ganze Zeit stehen, es kommt nur still an."""
    state = get_or_create_live_state(db)
    state.on_air = body.on_air
    db.commit()
    await apply_on_air_transition(db, body.on_air)
    await broadcast_live_state(db)
    return await build_live_payload(db)
