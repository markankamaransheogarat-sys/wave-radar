"""Configuration loading and validation for Wave Radar."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from dotenv import load_dotenv

DEFAULT_WAVE_PROGRAM_ID = "fdc01c95-806f-4b6a-998b-a6ed37e0d81b"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def resolve_github_token(configured_token: str) -> str:
    """Return configured token or fall back to `gh auth token` if available."""
    if configured_token.strip():
        return configured_token.strip()
    try:
        out = subprocess.check_output(
            ["gh", "auth", "token"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
        return out
    except Exception:
        return ""


@dataclass(frozen=True, slots=True)
class RadarConfig:
    """Runtime settings loaded from `.env` and process environment."""

    github_username: str
    github_token: str = ""
    wave_program_id: str = DEFAULT_WAVE_PROGRAM_ID
    scan_interval_seconds: int = 45
    online_window_minutes: int = 15
    min_points: int = 200
    max_pending_apps: int = 0
    stale_hours: int = 18
    max_candidates_per_repo: int = 4
    http_timeout_seconds: float = 8.0
    web_host: str = "127.0.0.1"
    web_port: int = 8787
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    proxy_url: str = ""
    log_file: str = "radar.log"
    log_level: str = "INFO"

    @property
    def telegram_enabled(self) -> bool:
        """True when both bot token and chat ID are configured."""
        return bool(self.telegram_bot_token.strip() and self.telegram_chat_id.strip())

    def validate(self) -> None:
        """Ensure configuration invariants hold before starting loops."""
        if not self.github_username.strip():
            raise ValueError("GITHUB_USERNAME is required")
        if not self.github_token.strip():
            raise ValueError(
                "GITHUB_TOKEN is required (or authenticate via `gh auth login`)"
            )
        if self.scan_interval_seconds <= 0:
            raise ValueError("SCAN_INTERVAL_SECONDS must be positive")
        if self.online_window_minutes <= 0:
            raise ValueError("ONLINE_WINDOW_MINUTES must be positive")
        if self.min_points < 0:
            raise ValueError("MIN_POINTS must be non-negative")
        if self.max_pending_apps < 0:
            raise ValueError("MAX_PENDING_APPS must be non-negative")
        if self.http_timeout_seconds <= 0:
            raise ValueError("HTTP_TIMEOUT_SECONDS must be positive")

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> "RadarConfig":
        """Load configuration from `.env` and environment variables."""
        load_dotenv(dotenv_path=dotenv_path, override=False)
        token = resolve_github_token(os.getenv("GITHUB_TOKEN", ""))
        return cls(
            github_username=os.getenv(
                "GITHUB_USERNAME", "markankamaransheogarat-sys"
            ).strip(),
            github_token=token,
            wave_program_id=os.getenv(
                "WAVE_PROGRAM_ID", DEFAULT_WAVE_PROGRAM_ID
            ).strip()
            or DEFAULT_WAVE_PROGRAM_ID,
            scan_interval_seconds=_env_int("SCAN_INTERVAL_SECONDS", 45),
            online_window_minutes=_env_int("ONLINE_WINDOW_MINUTES", 15),
            min_points=_env_int("MIN_POINTS", 200),
            max_pending_apps=_env_int("MAX_PENDING_APPS", 0),
            stale_hours=_env_int("STALE_HOURS", 18),
            max_candidates_per_repo=_env_int("MAX_CANDIDATES_PER_REPO", 4),
            http_timeout_seconds=_env_float("HTTP_TIMEOUT_SECONDS", 8.0),
            web_host=os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
            web_port=_env_int("WEB_PORT", 8787),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
            proxy_url=os.getenv("PROXY_URL", "").strip(),
            log_file=os.getenv("LOG_FILE", "radar.log").strip() or "radar.log",
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
