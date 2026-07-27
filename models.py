import uuid
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class SyncMode(str, Enum):
    ONE_WAY_MIRROR = "one_way_mirror"  # Target becomes exact replica of source (deletes target extra files)
    ONE_WAY_BACKUP = "one_way_backup"  # Copies new/updated files to target (never deletes)
    TWO_WAY_SYNC = "two_way_sync"      # Syncs changes bidirectionally between source and targets


class ConflictPolicy(str, Enum):
    SOURCE_WINS = "source_wins"
    TARGET_WINS = "target_wins"
    KEEP_NEWEST = "keep_newest"
    SKIP = "skip"


class ScheduleType(str, Enum):
    MANUAL = "manual"
    INTERVAL = "interval"
    ON_DRIVE_CONNECT = "on_drive_connect"


class SyncAction(BaseModel):
    action_type: str  # "COPY_TO_TARGET", "COPY_TO_SOURCE", "DELETE_TARGET", "SKIP"
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    reason: str


class SyncJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    sources: List[str]
    targets: List[str]
    mode: SyncMode = SyncMode.ONE_WAY_BACKUP
    conflict_policy: ConflictPolicy = ConflictPolicy.KEEP_NEWEST
    schedule_type: ScheduleType = ScheduleType.MANUAL
    schedule_value: Optional[str] = None
    target_drive_volume_label: Optional[str] = None
    exclude_patterns: List[str] = [
        ".tmp",
        "$RECYCLE.BIN",
        ".DS_Store",
        "System Volume Information",
    ]
    is_active: bool = True
