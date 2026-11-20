"""Domain models for Wave Radar snapshots, hot maintainers, and slot tracking."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SlotState(str, Enum):
    """Lifecycle status of an issue we applied to or were assigned."""

    APPLIED_SOLO = "applied_solo"
    APPLIED_COMPETED = "applied_competed"
    STALE = "stale"
    ASSIGNED = "assigned"
    PR_OPEN = "pr_open"
    LOST = "lost"


@dataclass(frozen=True, slots=True)
class WaveCandidate:
    """Open unassigned Drips Wave issue ready for 1-click browser application."""

    drips_id: str
    drips_url: str
    repo: str
    issue_number: int
    title: str
    points: int
    pending_apps: int
    github_url: str
    pitch: str
    created_at: str


@dataclass(frozen=True, slots=True)
class OnlineMaintainerSignal:
    """Repository whose maintainer assigned one or more issues in the live window."""

    repo: str
    assigned_recently: int
    latest_assigned_at: datetime
    latest_issue_number: int
    latest_assignee: str
    candidates: tuple[WaveCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class TrackedApplication:
    """Current state of one of the user's Wave applications or assigned issues."""

    repo: str
    issue_number: int
    title: str
    url: str
    applied_at: datetime
    state: SlotState
    applicants_count: int
    assignee: str | None = None
    age_hours: float = 0.0
    pr_url: str | None = None


@dataclass(frozen=True, slots=True)
class RadarEvent:
    """Human-readable change event surfaced in alerts and the UI activity feed."""

    timestamp: datetime
    kind: str
    message: str


@dataclass(frozen=True, slots=True)
class RadarSnapshot:
    """Complete point-in-time radar state exposed to Web UI, CLI, and notifiers."""

    generated_at: datetime
    username: str
    online_window_minutes: int
    hot_maintainers: tuple[OnlineMaintainerSignal, ...] = ()
    applications: tuple[TrackedApplication, ...] = ()
    events: tuple[RadarEvent, ...] = ()
    active_slots_count: int = 0
    solo_slots_count: int = 0
    stale_slots_count: int = 0
    assigned_count: int = 0
    scan_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot cleanly to JSON-compatible dictionary."""
        raw = asdict(self)
        raw["generated_at"] = self.generated_at.isoformat()
        for m in raw["hot_maintainers"]:
            m["latest_assigned_at"] = m["latest_assigned_at"].isoformat()
        for app in raw["applications"]:
            app["applied_at"] = app["applied_at"].isoformat()
            app["state"] = app["state"].value
        for ev in raw["events"]:
            ev["timestamp"] = ev["timestamp"].isoformat()
        return raw


@dataclass(slots=True)
class RadarStateMemory:
    """In-memory deduplication state across polling ticks."""

    alerted_hot_keys: dict[str, datetime] = field(default_factory=dict)
    known_assigned: set[str] = field(default_factory=set)
    known_lost: set[str] = field(default_factory=set)
    repo_id_cache: dict[str, str] = field(default_factory=dict)
    activity_log: list[RadarEvent] = field(default_factory=list)
