"""Reverse-Proxy für den Icecast-Stream unter derselben Origin wie die
restliche Software (ein Port lokal übers WLAN-AP, eine Subdomain extern
über den Cloudflare-Tunnel - kein separat exponierter Icecast-Port nötig)."""

import httpx
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse

from ..config import settings

router = APIRouter(tags=["stream-proxy"])


@router.get(settings.icecast_mount)
async def proxy_stream() -> Response:
    upstream_url = f"http://{settings.icecast_host}:{settings.icecast_port}{settings.icecast_mount}"
    # explizite, kurze Timeouts für alle Phasen (connect/write/pool) - nur
    # "read" grosszügig, weil ein Live-Stream lange zwischen Chunks pausieren
    # kann, aber trotzdem nicht unbegrenzt (verhindert einen hängenden Request,
    # falls Icecast mal gar nicht antwortet).
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)
    client = httpx.AsyncClient(timeout=timeout)
    try:
        upstream = await client.send(client.build_request("GET", upstream_url), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        return Response("Stream aktuell nicht erreichbar", status_code=503)

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        media_type=upstream.headers.get("content-type", "audio/mpeg"),
        status_code=upstream.status_code,
    )
