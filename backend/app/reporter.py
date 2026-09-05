"""Kurzlebige QR-Kopplungen und Zustand des Aussenreporter-Kanals."""

import secrets
import time

from .audio.reporter import ReporterAudio

PAIR_TTL_SECONDS = 10 * 60


class ReporterManager:
    def __init__(self) -> None:
        self.audio = ReporterAudio()
        self._token: str | None = None
        self._expires_at = 0.0
        self._connected = False
        self._muted = True

    def configure(self, backend) -> None:
        self.audio.configure(backend)

    async def stop(self) -> None:
        await self.audio.stop()
        self._connected = False

    async def create_pair(self) -> dict:
        await self.stop()
        self._token = secrets.token_urlsafe(24)
        self._expires_at = time.time() + PAIR_TTL_SECONDS
        self._muted = True
        return {"token": self._token, "expires_at": self._expires_at}

    def accepts(self, token: str) -> bool:
        return bool(
            self._token
            and secrets.compare_digest(token, self._token)
            and (self._connected or time.time() < self._expires_at)
        )

    async def connect(self, token: str) -> bool:
        if not self.accepts(token):
            return False
        await self.audio.start()
        self._connected = True
        return True

    async def disconnect(self) -> None:
        await self.audio.stop()
        self._connected = False

    async def revoke(self) -> None:
        await self.disconnect()
        self._token = None
        self._expires_at = 0.0
        self._muted = True

    async def set_muted(self, muted: bool) -> None:
        self._muted = muted
        await self.audio.set_muted(muted)

    async def feed(self, data: bytes) -> bool:
        return await self.audio.feed(data)

    def state(self) -> dict:
        pending = self._token is not None and not self._connected and time.time() < self._expires_at
        return {
            "paired": self._token is not None,
            "pending": pending,
            "connected": self._connected,
            "muted": self._muted,
            "level": self.audio.level,
            "expires_at": self._expires_at if pending else None,
        }
