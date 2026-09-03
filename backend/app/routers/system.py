import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ..auth import require_admin
from ..config import settings
from .. import update

logger = logging.getLogger("buschfunk.system")

router = APIRouter(prefix="/api/system", tags=["system"], dependencies=[Depends(require_admin)])
public_router = APIRouter(prefix="/api/system", tags=["system-public"])


@public_router.get("/stream-info")
def stream_info():
    return {"mount": settings.icecast_mount}


@router.get("/version")
async def version():
    info = await update.get_version_info()
    return info


@router.post("/update/check")
async def update_check():
    return await update.check_for_update()


async def _delayed_restart() -> None:
    await asyncio.sleep(0.5)
    update.restart_process()


@router.post("/update/apply")
async def update_apply(background_tasks: BackgroundTasks):
    try:
        await update.apply_update()
    except update.UpdateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    background_tasks.add_task(_delayed_restart)
    return {"ok": True, "restarting": True}
