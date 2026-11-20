"""Asynchronous client for Drips Wave API (`wave-api.drips.network`)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from wave_radar.models import WaveCandidate
from wave_radar.pitch import generate_pitch

logger = logging.getLogger(__name__)

DRIPS_WAVE_API_BASE = "https://wave-api.drips.network/api"
DRIPS_WEB_ISSUE_BASE = "https://www.drips.network/wave/stellar/issues"


class DripsWaveClient:
    """Fetches open zero-competition high-point candidates for hot repositories."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        wave_program_id: str,
        repo_id_cache: dict[str, str] | None = None,
        api_base: str = DRIPS_WAVE_API_BASE,
    ) -> None:
        self._client = http_client
        self._wave_program_id = wave_program_id
        self._repo_id_cache = repo_id_cache if repo_id_cache is not None else {}
        self._api_base = api_base.rstrip("/")

    async def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.get(
            f"{self._api_base}{path}",
            params=params,
            headers={"Accept": "application/json", "User-Agent": "wave-radar/0.1"},
        )
        resp.raise_for_status()
        return resp.json()

    async def resolve_repo_id(self, repo_full_name: str) -> str | None:
        """Resolve GitHub `owner/name` to its Drips UUID `repoId` with caching."""
        cached = self._repo_id_cache.get(repo_full_name)
        if cached:
            return cached

        repo_short = repo_full_name.split("/")[-1]
        for query in (repo_full_name, repo_short):
            try:
                data = await self._get_json(
                    "/issues",
                    {
                        "waveProgramId": self._wave_program_id,
                        "search": query,
                        "limit": 25,
                    },
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "Drips repo search failed for %s: %s", repo_full_name, exc
                )
                continue

            for item in data.get("data", []):
                repo_obj = item.get("repo") or {}
                if repo_obj.get(
                    "gitHubRepoFullName"
                ) == repo_full_name and repo_obj.get("id"):
                    self._repo_id_cache[repo_full_name] = repo_obj["id"]
                    return repo_obj["id"]

        # Fallback: scan top pages of recently updated issues to populate cache
        for page in (1, 2):
            try:
                data = await self._get_json(
                    "/issues",
                    {
                        "waveProgramId": self._wave_program_id,
                        "state": "open",
                        "sortBy": "updatedAt",
                        "limit": 100,
                        "page": page,
                    },
                )
            except httpx.HTTPError:
                break
            for item in data.get("data", []):
                repo_obj = item.get("repo") or {}
                full = repo_obj.get("gitHubRepoFullName")
                rid = repo_obj.get("id")
                if full and rid:
                    self._repo_id_cache[full] = rid
            if repo_full_name in self._repo_id_cache:
                return self._repo_id_cache[repo_full_name]

        return None

    async def fetch_repo_candidates(
        self,
        repo_full_name: str,
        min_points: int = 200,
        max_pending_apps: int = 0,
        limit: int = 4,
        exclude_keys: set[str] | None = None,
    ) -> list[WaveCandidate]:
        """Return newest unassigned Drips issues matching point/competition filters."""
        repo_id = await self.resolve_repo_id(repo_full_name)
        if not repo_id:
            return []

        try:
            data = await self._get_json(
                "/issues",
                {
                    "waveProgramId": self._wave_program_id,
                    "repoId": repo_id,
                    "state": "open",
                    "limit": 100,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("Drips issue list failed for %s: %s", repo_full_name, exc)
            return []

        excluded = exclude_keys or set()
        matches: list[WaveCandidate] = []
        for item in data.get("data", []):
            if item.get("assignedApplicant") is not None:
                continue
            pts = int(item.get("points") or 0)
            apps = int(item.get("pendingApplicationsCount") or 0)
            if pts < min_points or apps > max_pending_apps:
                continue
            num = int(item.get("gitHubIssueNumber") or 0)
            key = f"{repo_full_name}#{num}"
            if key in excluded:
                continue
            drips_id = item["id"]
            title = str(item.get("title") or "")
            body = str(item.get("body") or "")
            matches.append(
                WaveCandidate(
                    drips_id=drips_id,
                    drips_url=f"{DRIPS_WEB_ISSUE_BASE}/{drips_id}",
                    repo=repo_full_name,
                    issue_number=num,
                    title=title,
                    points=pts,
                    pending_apps=apps,
                    github_url=f"https://github.com/{repo_full_name}/issues/{num}",
                    pitch=generate_pitch(num, title, body),
                    created_at=str(item.get("gitHubCreatedAt") or ""),
                )
            )

        matches.sort(key=lambda c: c.created_at, reverse=True)
        return matches[:limit]
