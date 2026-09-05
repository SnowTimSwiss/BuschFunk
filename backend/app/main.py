import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import runtime
from .audio import create_audio_backend
from .audio.stream import stream_manager
from .auth import ensure_setup_code
from .config import REPO_ROOT, settings
from .db import SessionLocal, init_db
from .live_state import (
    build_live_payload,
    build_meters_payload,
    compute_elapsed_seconds,
    get_or_create_live_state,
)
from .models import Bus, Segment
from .routers import auth as auth_router
from .routers import buses as buses_router
from .routers import days as days_router
from .routers import export_import as export_import_router
from .routers import live as live_router
from .routers import schedule as schedule_router
from .routers import stream_proxy as stream_proxy_router
from .routers import system as system_router
from .ws import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("buschfunk.main")

FRONTEND_DIR = REPO_ROOT / "frontend"

DISCOVERY_INTERVAL = 3.0   # Sekunden - Hotplug-Erkennung
METER_INTERVAL = 0.2       # Sekunden - Pegel-Updates an die UIs
STATE_EVERY_N_METERS = 5   # -> voller Live-Zustand einmal pro Sekunde


async def _apply_stored_state(bus: Bus) -> None:
    """Mute/Lautstärke aus der DB auf ein (wieder) angeschlossenes Gerät legen -
    damit ein neu eingestecktes Mischpult exakt so klingt wie vorher."""
    if runtime.audio_backend is None:
        return
    await runtime.audio_backend.set_mute(bus.device_id, bus.is_muted)
    await runtime.audio_backend.set_volume(bus.device_id, bus.volume)


async def _discover_buses_loop() -> None:
    known_connected: set[str] = set()
    while True:
        try:
            if runtime.audio_backend is not None:
                discovered = await runtime.audio_backend.discover_buses()
                device_ids = {b.device_id for b in discovered}
                runtime.last_seen_device_ids = device_ids
                runtime.audio_ready = True

                db = SessionLocal()
                try:
                    existing = {b.device_id: b for b in db.query(Bus).all()}
                    for found in discovered:
                        bus = existing.get(found.device_id)
                        if bus is None:
                            bus = Bus(
                                device_id=found.device_id,
                                display_name=found.display_name,
                                direction=found.direction,
                                is_muted=True,
                            )
                            db.add(bus)
                            db.flush()
                        else:
                            bus.direction = found.direction
                        if found.device_id not in known_connected:
                            await _apply_stored_state(bus)
                    db.commit()
                finally:
                    db.close()
                known_connected = device_ids
        except Exception:
            logger.exception("Geräte-Erkennung fehlgeschlagen")
        await asyncio.sleep(DISCOVERY_INTERVAL)


async def _check_end_media(db) -> None:
    """Segmente, deren Datei "am geplanten Ende" laufen soll, genau einmal
    anwerfen, sobald der Countdown durch ist."""
    state = get_or_create_live_state(db)
    if not state.is_on_air or state.current_segment_id is None:
        return
    if state.current_segment_id in runtime.fired_end_media:
        return
    segment = db.get(Segment, state.current_segment_id)
    if segment is None or segment.media_trigger != "end" or not segment.media_file:
        return
    if compute_elapsed_seconds(state) < segment.planned_duration:
        return
    runtime.fired_end_media.add(segment.id)
    from .routers.live import play_segment_media

    await play_segment_media(db, segment)


async def _broadcast_loop() -> None:
    tick = 0
    while True:
        try:
            db = SessionLocal()
            try:
                if tick % STATE_EVERY_N_METERS == 0:
                    await _check_end_media(db)
                    await manager.broadcast(await build_live_payload(db))
                elif await manager.has_meter_subscribers():
                    await manager.broadcast(await build_meters_payload(db), meters_only=True)
            finally:
                db.close()
        except Exception:
            logger.exception("Live-State-Broadcast fehlgeschlagen")
        tick += 1
        await asyncio.sleep(METER_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        ensure_setup_code(db)
    finally:
        db.close()

    runtime.audio_backend = await create_audio_backend()
    await runtime.audio_backend.start()
    await stream_manager.start(runtime.audio_backend)

    tasks = [
        asyncio.create_task(_discover_buses_loop()),
        asyncio.create_task(_broadcast_loop()),
    ]

    yield

    for t in tasks:
        t.cancel()
    await stream_manager.stop()
    if runtime.audio_backend is not None:
        await runtime.audio_backend.stop()


app = FastAPI(title="BuschFunk", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")

app.include_router(auth_router.router)
app.include_router(days_router.router)
app.include_router(live_router.router)
app.include_router(live_router.public_router)
app.include_router(buses_router.router)
app.include_router(schedule_router.router)
app.include_router(schedule_router.public_router)
app.include_router(export_import_router.router)
app.include_router(system_router.router)
app.include_router(system_router.public_router)
app.include_router(stream_proxy_router.router)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await manager.connect(websocket)
    db = SessionLocal()
    try:
        # Sofort den vollen Zustand schicken, statt den Client bis zum
        # nächsten Broadcast-Tick auf eine leere UI schauen zu lassen.
        await websocket.send_json(await build_live_payload(db))
    except Exception:
        pass
    finally:
        db.close()
    try:
        while True:
            # Einziges, was ein Client schickt: ob er die Pegel-Pakete will
            # (die Regie-UI ja, die Hörer-Seite nicht).
            raw = await websocket.receive_text()
            try:
                await manager.set_wants_meters(websocket, bool(json.loads(raw).get("meters")))
            except (ValueError, AttributeError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)


settings.media_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_path), name="media")

if FRONTEND_DIR.exists():
    app.mount("/admin", StaticFiles(directory=FRONTEND_DIR / "admin", html=True), name="admin")
    app.mount("/listen", StaticFiles(directory=FRONTEND_DIR / "listener", html=True), name="listen")


@app.get("/")
def root():
    return RedirectResponse("/listen/")
