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
from .audio.player import JinglePlayer, MusicPlayer, kill_orphans
from .audio.stream import stream_manager
from .auth import ensure_setup_code
from .config import REPO_ROOT, settings
from .db import SessionLocal, init_db
from .live_state import (
    apply_bus_state,
    build_live_payload,
    build_meters_payload,
    get_or_create_live_state,
)
from .models import Bus
from .routers import auth as auth_router
from .routers import buses as buses_router
from .routers import library as library_router
from .routers import live as live_router
from .routers import player as player_router
from .routers import playlists as playlists_router
from .routers import stream_proxy as stream_proxy_router
from .routers import system as system_router
from .ws import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("buschfunk.main")

FRONTEND_DIR = REPO_ROOT / "frontend"

DISCOVERY_INTERVAL = 3.0   # Sekunden - Hotplug-Erkennung
METER_INTERVAL = 0.2       # Sekunden - Pegel-Updates an die Regie
STATE_EVERY_N_METERS = 5   # -> voller Live-Zustand einmal pro Sekunde


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
                        # Ein frisch eingestecktes Geraet soll sofort wieder so
                        # klingen wie vorher - Name, Mute und Pegel sind gespeichert.
                        if found.device_id not in known_connected:
                            await apply_bus_state(bus)
                    db.commit()
                finally:
                    db.close()
                known_connected = device_ids
        except Exception:
            logger.exception("Geraete-Erkennung fehlgeschlagen")
        await asyncio.sleep(DISCOVERY_INTERVAL)


async def _broadcast_loop() -> None:
    tick = 0
    while True:
        try:
            db = SessionLocal()
            try:
                if tick % STATE_EVERY_N_METERS == 0:
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

    kill_orphans()
    runtime.audio_backend = await create_audio_backend()
    await runtime.audio_backend.start()
    runtime.player = MusicPlayer()
    runtime.player.configure(runtime.audio_backend)
    runtime.jingles = JinglePlayer()
    runtime.jingles.configure(runtime.audio_backend)
    await stream_manager.start(runtime.audio_backend)
    db = SessionLocal()
    try:
        # Off-Air ist ein zentraler Master-Zustand, kein Einzel-Mute der Busse.
        await runtime.audio_backend.set_master_mute(not get_or_create_live_state(db).on_air)
    finally:
        db.close()

    tasks = [
        asyncio.create_task(_discover_buses_loop()),
        asyncio.create_task(_broadcast_loop()),
    ]

    yield

    for task in tasks:
        task.cancel()
    await runtime.player.stop()
    await runtime.jingles.stop()
    await stream_manager.stop()
    if runtime.audio_backend is not None:
        await runtime.audio_backend.stop()


app = FastAPI(title="BuschFunk", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")

app.include_router(auth_router.router)
app.include_router(library_router.router)
app.include_router(playlists_router.router)
app.include_router(player_router.router)
app.include_router(live_router.router)
app.include_router(live_router.public_router)
app.include_router(buses_router.router)
app.include_router(system_router.router)
app.include_router(system_router.public_router)
app.include_router(stream_proxy_router.router)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await manager.connect(websocket)
    db = SessionLocal()
    try:
        # Sofort den vollen Zustand schicken, statt den Client bis zum
        # naechsten Broadcast-Tick auf eine leere UI schauen zu lassen.
        await websocket.send_json(await build_live_payload(db))
    except Exception:
        pass
    finally:
        db.close()
    try:
        while True:
            # Einziges, was ein Client schickt: ob er die Pegel-Pakete will
            # (die Regie ja, die Hoerer-Seite nicht).
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
