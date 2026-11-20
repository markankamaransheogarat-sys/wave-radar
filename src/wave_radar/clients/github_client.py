"""Asynchronous GitHub GraphQL client for live Wave maintainer detection and slot tracking."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from wave_radar.models import OnlineMaintainerSignal, SlotState, TrackedApplication

logger = logging.getLogger(__name__)

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
_WAVE_MARKER_RE = re.compile(
    r"(?:wave:application-id|Stellar Wave Program)", re.IGNORECASE
)
_CLOSES_ISSUE_RE = re.compile(r"(?:closes|fixes|resolves)\s+#(\d+)", re.IGNORECASE)


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _is_wave_issue_or_comment(comment_body: str, labels: list[str]) -> bool:
    if _WAVE_MARKER_RE.search(comment_body or ""):
        return True
    lowered = {lbl.lower() for lbl in labels}
    return "drips-wave" in lowered or "stellar wave" in lowered


@dataclass(frozen=True, slots=True)
class GitHubRadarData:
    """Raw parsed data returned from a single GraphQL sweep."""

    online_signals: list[OnlineMaintainerSignal]
    applications: list[TrackedApplication]


class GitHubWaveClient:
    """Queries GitHub GraphQL in a single batch for hot maintainers and user slots."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        username: str,
        token: str,
        online_window_minutes: int = 15,
        stale_hours: int = 18,
        graphql_url: str = GITHUB_GRAPHQL_URL,
    ) -> None:
        self._client = http_client
        self._username = username
        self._token = token
        self._window = timedelta(minutes=online_window_minutes)
        self._stale_hours = float(stale_hours)
        self._graphql_url = graphql_url

    def _build_query(self, cutoff_iso: str) -> str:
        search_q = (
            f"is:issue label:drips-wave -no:assignee "
            f"-repo:soroworks/soroforge -repo:soroworks/soroprobe "
            f"updated:>={cutoff_iso} sort:updated-desc"
        )
        return """
        query($searchQ: String!, $login: String!) {
          recentAssigned: search(query: $searchQ, type: ISSUE, first: 80) {
            nodes {
              ... on Issue {
                number
                updatedAt
                repository { nameWithOwner }
                assignees(first: 2) { nodes { login } }
              }
            }
          }
          user(login: $login) {
            openPRs: pullRequests(states: OPEN, last: 15) {
              nodes {
                number
                url
                body
                repository { nameWithOwner }
              }
            }
            issueComments(last: 35) {
              nodes {
                createdAt
                body
                issue {
                  number
                  title
                  url
                  state
                  labels(first: 8) { nodes { name } }
                  repository { nameWithOwner }
                  assignees(first: 3) { nodes { login } }
                  comments(last: 10) {
                    totalCount
                    nodes { author { login } }
                  }
                }
              }
            }
          }
        }
        """

    async def fetch_radar_data(self, now: datetime | None = None) -> GitHubRadarData:
        """Execute GraphQL query and normalize hot maintainers + tracked user applications."""
        ref_now = now or datetime.now(timezone.utc)
        cutoff = ref_now - self._window
        cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        search_q = (
            f"is:issue label:drips-wave -no:assignee "
            f"-repo:soroworks/soroforge -repo:soroworks/soroprobe "
            f"updated:>={cutoff_iso} sort:updated-desc"
        )

        resp = await self._client.post(
            self._graphql_url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "wave-radar/0.1",
            },
            json={
                "query": self._build_query(cutoff_iso),
                "variables": {"searchQ": search_q, "login": self._username},
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"GitHub GraphQL errors: {payload['errors']}")

        data = payload["data"]
        return self.parse_graphql_data(data, now=ref_now)

    def parse_graphql_data(
        self, data: dict[str, Any], now: datetime
    ) -> GitHubRadarData:
        """Transform raw GitHub GraphQL response into typed domain signals."""
        cutoff = now - self._window
        grouped: dict[str, dict[str, Any]] = {}

        for node in (data.get("recentAssigned") or {}).get("nodes", []):
            if not node:
                continue
            assignees = [
                a["login"] for a in (node.get("assignees") or {}).get("nodes", []) if a
            ]
            if not assignees:
                continue
            updated_at = _parse_iso(node["updatedAt"])
            if updated_at < cutoff:
                continue
            repo = node["repository"]["nameWithOwner"]
            entry = grouped.get(repo)
            if entry is None:
                grouped[repo] = {
                    "count": 1,
                    "latest_at": updated_at,
                    "latest_num": int(node["number"]),
                    "latest_assignee": assignees[0],
                }
            else:
                entry["count"] += 1
                if updated_at > entry["latest_at"]:
                    entry["latest_at"] = updated_at
                    entry["latest_num"] = int(node["number"])
                    entry["latest_assignee"] = assignees[0]

        online_signals = [
            OnlineMaintainerSignal(
                repo=repo,
                assigned_recently=info["count"],
                latest_assigned_at=info["latest_at"],
                latest_issue_number=info["latest_num"],
                latest_assignee=info["latest_assignee"],
            )
            for repo, info in sorted(
                grouped.items(),
                key=lambda kv: (kv[1]["count"], kv[1]["latest_at"]),
                reverse=True,
            )
        ]

        user_block = data.get("user") or {}
        open_prs_by_issue: dict[str, str] = {}
        for pr in (user_block.get("openPRs") or {}).get("nodes", []):
            if not pr:
                continue
            repo = pr["repository"]["nameWithOwner"]
            for issue_num in _CLOSES_ISSUE_RE.findall(pr.get("body") or ""):
                open_prs_by_issue[f"{repo}#{issue_num}"] = pr["url"]

        seen_issues: set[str] = set()
        applications: list[TrackedApplication] = []
        comment_nodes = list((user_block.get("issueComments") or {}).get("nodes", []))
        for cmt in reversed(comment_nodes):
            if not cmt or not cmt.get("issue"):
                continue
            iss = cmt["issue"]
            repo = iss["repository"]["nameWithOwner"]
            num = int(iss["number"])
            key = f"{repo}#{num}"
            if key in seen_issues:
                continue

            labels = [
                lbl["name"] for lbl in (iss.get("labels") or {}).get("nodes", []) if lbl
            ]
            if not _is_wave_issue_or_comment(cmt.get("body", ""), labels):
                continue
            seen_issues.add(key)

            applied_at = _parse_iso(cmt["createdAt"])
            age_hours = max(0.0, (now - applied_at).total_seconds() / 3600.0)
            assignees = [
                a["login"] for a in (iss.get("assignees") or {}).get("nodes", []) if a
            ]
            pr_url = open_prs_by_issue.get(key)

            cmt_nodes = (iss.get("comments") or {}).get("nodes", [])
            non_bot_authors = {
                c["author"]["login"]
                for c in cmt_nodes
                if c and c.get("author") and c["author"].get("login") != "drips-wave"
            }
            applicants_count = max(1, len(non_bot_authors))

            if pr_url is not None and self._username in assignees:
                state = SlotState.PR_OPEN
            elif self._username in assignees:
                state = SlotState.ASSIGNED
            elif assignees or iss.get("state") == "CLOSED":
                state = SlotState.LOST
            elif age_hours >= self._stale_hours:
                state = SlotState.STALE
            elif applicants_count <= 1:
                state = SlotState.APPLIED_SOLO
            else:
                state = SlotState.APPLIED_COMPETED

            applications.append(
                TrackedApplication(
                    repo=repo,
                    issue_number=num,
                    title=iss["title"],
                    url=iss["url"],
                    applied_at=applied_at,
                    state=state,
                    applicants_count=applicants_count,
                    assignee=assignees[0] if assignees else None,
                    age_hours=round(age_hours, 1),
                    pr_url=pr_url,
                )
            )

        return GitHubRadarData(online_signals=online_signals, applications=applications)
