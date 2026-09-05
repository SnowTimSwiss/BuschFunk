import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("buschfunk.ws")


class ConnectionManager:
    """Alle offenen WebSockets. Der volle Live-Zustand geht an alle; die
    Pegel-Pakete (5x/s) nur an Clients, die sich dafür angemeldet haben -
    Hörer-Handys brauchen sie nicht und sollen im Lager-WLAN nicht dafür
    zahlen."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._meter_subscribers: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
            self._meter_subscribers.discard(ws)

    async def set_wants_meters(self, ws: WebSocket, wants: bool) -> None:
        async with self._lock:
            if wants:
                self._meter_subscribers.add(ws)
            else:
                self._meter_subscribers.discard(ws)

    async def has_meter_subscribers(self) -> bool:
        async with self._lock:
            return bool(self._meter_subscribers)

    async def broadcast(self, payload: dict, meters_only: bool = False) -> None:
        message = json.dumps(payload, default=str)
        async with self._lock:
            targets = list(self._meter_subscribers if meters_only else self._connections)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
                    self._meter_subscribers.discard(ws)


manager = ConnectionManager()
