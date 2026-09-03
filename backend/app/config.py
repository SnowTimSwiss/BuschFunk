from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    session_secret: str = "dev-insecure-secret-change-me"
    database_path: str = "./buschfunk.db"
    media_dir: str = "../media"

    icecast_host: str = "127.0.0.1"
    icecast_port: int = 8001  # NICHT 8000 - das belegt bereits BuschFunk selbst
    icecast_source_password: str = "change-me"
    icecast_mount: str = "/stream"

    cloudflare_tunnel_token: str = ""

    audio_backend: str = "auto"  # auto | pipewire | dummy

    @property
    def database_file(self) -> Path:
        p = Path(self.database_path)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def media_path(self) -> Path:
        p = Path(self.media_dir)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


settings = Settings()
