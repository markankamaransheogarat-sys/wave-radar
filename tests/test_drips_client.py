"""Tests for Drips Wave API filtering and repoId caching."""

from __future__ import annotations

import httpx
import pytest

from wave_radar.clients.drips_client import DripsWaveClient


@pytest.mark.asyncio
async def test_drips_client_resolves_repo_caches_and_filters() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        params = dict(request.url.params)
        if "repoId" not in params:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "iss-x",
                            "repo": {
                                "id": "repo-uuid-1",
                                "gitHubRepoFullName": "org/app",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "uuid-200-0app",
                        "gitHubIssueNumber": 12,
                        "title": "Add checksum",
                        "body": "Work in `src/checksum.ts`.",
                        "points": 200,
                        "pendingApplicationsCount": 0,
                        "assignedApplicant": None,
                        "gitHubCreatedAt": "2026-11-20T16:00:00Z",
                    },
                    {
                        "id": "uuid-100",
                        "gitHubIssueNumber": 13,
                        "title": "Too cheap",
                        "body": "",
                        "points": 100,
                        "pendingApplicationsCount": 0,
                        "assignedApplicant": None,
                        "gitHubCreatedAt": "2026-11-20T16:01:00Z",
                    },
                    {
                        "id": "uuid-competed",
                        "gitHubIssueNumber": 14,
                        "title": "Has competition",
                        "body": "",
                        "points": 200,
                        "pendingApplicationsCount": 1,
                        "assignedApplicant": None,
                        "gitHubCreatedAt": "2026-11-20T16:02:00Z",
                    },
                    {
                        "id": "uuid-excluded",
                        "gitHubIssueNumber": 15,
                        "title": "Already applied",
                        "body": "",
                        "points": 200,
                        "pendingApplicationsCount": 0,
                        "assignedApplicant": None,
                        "gitHubCreatedAt": "2026-11-20T16:03:00Z",
                    },
                ]
            },
        )

    cache: dict[str, str] = {}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DripsWaveClient(
            http_client, wave_program_id="prog-1", repo_id_cache=cache
        )
        cands = await client.fetch_repo_candidates(
            "org/app",
            min_points=200,
            max_pending_apps=0,
            exclude_keys={"org/app#15"},
        )
        assert len(cands) == 1
        assert cands[0].issue_number == 12
        assert cands[0].drips_url.endswith("/uuid-200-0app")
        assert "`src/checksum.ts`" in cands[0].pitch
        assert cache["org/app"] == "repo-uuid-1"

        # Second call reuses repoId cache without extra search query
        prev_calls = len(calls)
        await client.fetch_repo_candidates(
            "org/app", min_points=200, max_pending_apps=0
        )
        assert len(calls) == prev_calls + 1
