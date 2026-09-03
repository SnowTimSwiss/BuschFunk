import asyncio
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
from .live_state import broadcast_live_state
from .models import Bus
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


async def _discover_buses_loop() -> None:
    while True:
        try:
            if runtime.audio_backend is not None:
                discovered = await runtime.audio_backend.discover_buses()
                runtime.last_seen_device_ids = {b.device_id for b in discovered}
                db = SessionLocal()
                try:
                    existing = {b.device_id for b in db.query(Bus).all()}
                    for bus in discovered:
                        if bus.device_id not in existing:
                            db.add(Bus(device_id=bus.device_id, display_name=bus.display_name, is_muted=True))
                    db.commit()
                finally:
                    db.close()
        except Exception:
            logger.exception("Bus-Discovery fehlgeschlagen")
        await asyncio.sleep(3.0)


async def _broadcast_loop() -> None:
    while True:
        try:
            db = SessionLocal()
            try:
                await broadcast_live_state(db)
            finally:
                db.close()
        except Exception:
            logger.exception("Live-State-Broadcast fehlgeschlagen")
        await asyncio.sleep(1.0)


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
    try:
        while True:
            await websocket.receive_text()  # Client sendet nichts Relevantes, hält nur die Verbindung
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
