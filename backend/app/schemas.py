from pydantic import BaseModel, ConfigDict


# ---------- Mediathek ----------

class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    original_name: str
    title: str
    kind: str          # music | jingle
    duration: float


class TrackUpdate(BaseModel):
    title: str | None = None
    kind: str | None = None


# ---------- Playlists ----------

class PlaylistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    track: TrackOut


class PlaylistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    items: list[PlaylistItemOut]


class PlaylistCreate(BaseModel):
    name: str = "Neue Playlist"


class PlaylistUpdate(BaseModel):
    name: str | None = None


class PlaylistAddTracks(BaseModel):
    track_ids: list[int]


class PlaylistReorder(BaseModel):
    ordered_item_ids: list[int]


# ---------- Player ----------

class PlayRequest(BaseModel):
    track_id: int | None = None
    playlist_id: int | None = None
    shuffle: bool = False


class QueueRequest(BaseModel):
    track_ids: list[int] = []
    playlist_id: int | None = None


class QueueJump(BaseModel):
    index: int


class VolumeRequest(BaseModel):
    volume: float


class RepeatRequest(BaseModel):
    repeat: bool


class JingleRequest(BaseModel):
    track_id: int


# ---------- Mixer ----------

class BusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: str
    display_name: str
    direction: str
    is_muted: bool
    volume: float
    channel_mode: str = "stereo"
    level: float = 0.0
    connected: bool = False


class BusUpdate(BaseModel):
    is_muted: bool | None = None
    volume: float | None = None
    channel_mode: str | None = None


class BusRename(BaseModel):
    display_name: str


# ---------- Auth ----------

class SetupCodeVerify(BaseModel):
    code: str


class SetPassword(BaseModel):
    code: str
    password: str


class Login(BaseModel):
    password: str


# ---------- Sendung ----------

class OnAirRequest(BaseModel):
    on_air: bool


# ---------- System / update ----------

class VersionInfo(BaseModel):
    commit: str
    commit_short: str
    commit_date: str | None
    branch: str
    dirty: bool


class UpdateCheckResult(BaseModel):
    up_to_date: bool
    behind_by: int
    commits: list[str]
    error: str | None = None
