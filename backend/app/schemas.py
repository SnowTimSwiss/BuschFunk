from pydantic import BaseModel, ConfigDict


# ---------- Segment ----------

class SegmentBase(BaseModel):
    type: str = "song"
    title: str = "Neues Segment"
    time: str | None = None
    planned_duration: int = 0
    fixed: bool = False
    notes: str | None = None
    media_file: str | None = None
    auto_route: list[int] = []


class SegmentCreate(SegmentBase):
    parent_id: int | None = None


class SegmentUpdate(BaseModel):
    type: str | None = None
    title: str | None = None
    time: str | None = None
    planned_duration: int | None = None
    fixed: bool | None = None
    notes: str | None = None
    media_file: str | None = None
    auto_route: list[int] | None = None


class SegmentOut(SegmentBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    show_id: int
    parent_id: int | None = None
    position: int
    children: list["SegmentOut"] = []


class SegmentReorder(BaseModel):
    ordered_ids: list[int]
    parent_id: int | None = None


# ---------- Show ----------

class ShowCreate(BaseModel):
    label: str = "Neuer Tag"


class ShowUpdate(BaseModel):
    label: str | None = None


class ShowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    position: int
    segments: list[SegmentOut] = []


class ShowSummary(BaseModel):
    id: int
    label: str
    segment_count: int


# ---------- Bus ----------

class BusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: str
    display_name: str
    direction: str = "in"
    is_muted: bool
    level: float = 0.0
    connected: bool = True


class BusRename(BaseModel):
    display_name: str


class BusMute(BaseModel):
    is_muted: bool


# ---------- ScheduleEntry ----------

class ScheduleEntryBase(BaseModel):
    day: str
    from_time: str
    to_time: str
    title: str
    public: bool = True


class ScheduleEntryCreate(ScheduleEntryBase):
    pass


class ScheduleEntryUpdate(BaseModel):
    day: str | None = None
    from_time: str | None = None
    to_time: str | None = None
    title: str | None = None
    public: bool | None = None


class ScheduleEntryOut(ScheduleEntryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    position: int


# ---------- Auth ----------

class SetupCodeVerify(BaseModel):
    code: str


class SetPassword(BaseModel):
    code: str
    password: str


class Login(BaseModel):
    password: str


# ---------- Live control ----------

class LiveStatus(BaseModel):
    active_show_id: int | None
    current_segment_id: int | None
    elapsed_seconds: int
    is_on_air: bool
    notfall_mode: str | None
    notfall_message: str | None
    notfall_acked: bool
    buses: list[BusOut]


class GoToSegment(BaseModel):
    segment_id: int


class NotesUpdate(BaseModel):
    notes: str


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
