"""Tests for WaveRadarService transition alerts and built-in Web Dashboard API."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer

from wave_radar.clients.github_client import GitHubRadarData
from wave_radar.config import RadarConfig
from wave_radar.models import (
    OnlineMaintainerSignal,
    SlotState,
    TrackedApplication,
    WaveCandidate,
)
from wave_radar.service import WaveRadarService
from wave_radar.web import create_web_app


class _StubGitHub:
    def __init__(self, responses: list[GitHubRadarData | Exception]) -> None:
        self._responses = responses
        self._idx = 0

    async def fetch_radar_data(self, now: datetime | None = None) -> GitHubRadarData:
        item = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        if isinstance(item, Exception):
            raise item
        return item


class _StubDrips:
    async def fetch_repo_candidates(
        self, repo_full_name: str, **_kwargs: object
    ) -> list[WaveCandidate]:
        return [
            WaveCandidate(
                drips_id="uuid-1",
                drips_url="https://www.drips.network/wave/stellar/issues/uuid-1",
                repo=repo_full_name,
                issue_number=260,
                title="Countdown widget",
                points=200,
                pending_apps=0,
                github_url=f"https://github.com/{repo_full_name}/issues/260",
                pitch="Hi! I'd like to take `#260`.",
                created_at="2026-11-20T16:00:00Z",
            )
        ]


class _SpyTelegram:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_html(self, text: str) -> bool:
        self.sent.append(text)
        return True


@pytest.mark.asyncio
async def test_service_detects_hot_maintainer_and_gracefully_handles_errors() -> None:
    now = datetime(2026, 11, 20, 16, 20, tzinfo=timezone.utc)
    cfg = RadarConfig(github_username="me", github_token="tok")
    gh = _StubGitHub(
        [
            GitHubRadarData(
                online_signals=[
                    OnlineMaintainerSignal(
                        repo="trustpay-escrow/trustpay-escrow",
                        assigned_recently=3,
                        latest_assigned_at=now,
                        latest_issue_number=241,
                        latest_assignee="alice",
                    )
                ],
                applications=[
                    TrackedApplication(
                        repo="trustpay-escrow/trustpay-escrow",
                        issue_number=255,
                        title="Bookmarks",
                        url="https://github.com/trustpay-escrow/trustpay-escrow/issues/255",
                        applied_at=now,
                        state=SlotState.APPLIED_SOLO,
                        applicants_count=1,
                    )
                ],
            ),
            RuntimeError("GitHub temporary 502"),
        ]
    )
    tg = _SpyTelegram()
    svc = WaveRadarService(cfg, gh, _StubDrips(), telegram=tg)  # type: ignore[arg-type]

    snap1 = await svc.scan_once(now=now)
    assert snap1.active_slots_count == 1
    assert snap1.solo_slots_count == 1
    assert len(snap1.hot_maintainers) == 1
    assert len(snap1.hot_maintainers[0].candidates) == 1
    assert len(tg.sent) == 1
    assert "МЕЙНТЕЙНЕР ОНЛАЙН" in tg.sent[0]

    # Error tick keeps previous hot_maintainers and records scan_error
    snap2 = await svc.scan_once(now=now)
    assert snap2.scan_error is not None
    assert len(snap2.hot_maintainers) == 1


@pytest.mark.asyncio
async def test_web_dashboard_routes() -> None:
    now = datetime(2026, 11, 20, 16, 20, tzinfo=timezone.utc)
    cfg = RadarConfig(github_username="me", github_token="tok")
    gh = _StubGitHub(
        [
            GitHubRadarData(
                online_signals=[
                    OnlineMaintainerSignal(
                        repo="trustpay-escrow/trustpay-escrow",
                        assigned_recently=1,
                        latest_assigned_at=now,
                        latest_issue_number=241,
                        latest_assignee="alice",
                    )
                ],
                applications=[],
            )
        ]
    )
    svc = WaveRadarService(cfg, gh, _StubDrips(), dry_run=True)  # type: ignore[arg-type]
    app = create_web_app(svc)

    async with TestClient(TestServer(app)) as client:
        resp_html = await client.get("/")
        assert resp_html.status == 200
        assert "Wave Radar" in await resp_html.text()

        resp_json = await client.get("/api/snapshot")
        assert resp_json.status == 200
        payload = await resp_json.json()
        assert payload["username"] == "me"
        assert payload["hot_maintainers"][0]["candidates"][0]["issue_number"] == 260

        resp_scan = await client.post("/api/scan")
        assert resp_scan.status == 200
