"""Tests for GitHub GraphQL parsing and slot state classification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from wave_radar.clients.github_client import GitHubWaveClient
from wave_radar.models import SlotState


def test_parse_graphql_detects_hot_maintainers_and_slot_states() -> None:
    now = datetime(2026, 11, 20, 16, 20, tzinfo=timezone.utc)
    t_recent = (now - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t_old = (now - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t_stale = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t_fresh = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    graphql_data = {
        "recentAssigned": {
            "nodes": [
                {
                    "number": 241,
                    "updatedAt": t_recent,
                    "repository": {"nameWithOwner": "trustpay-escrow/trustpay-escrow"},
                    "assignees": {"nodes": [{"login": "alice"}]},
                },
                {
                    "number": 240,
                    "updatedAt": t_recent,
                    "repository": {"nameWithOwner": "trustpay-escrow/trustpay-escrow"},
                    "assignees": {"nodes": [{"login": "bob"}]},
                },
                {
                    "number": 99,
                    "updatedAt": t_old,
                    "repository": {"nameWithOwner": "old/repo"},
                    "assignees": {"nodes": [{"login": "charlie"}]},
                },
            ]
        },
        "user": {
            "openPRs": {
                "nodes": [
                    {
                        "number": 2231,
                        "url": "https://github.com/dotandev/hintents/pull/2231",
                        "body": "Closes #2224",
                        "repository": {"nameWithOwner": "dotandev/hintents"},
                    }
                ]
            },
            "issueComments": {
                "nodes": [
                    # Non-wave comment should be ignored
                    {
                        "createdAt": t_fresh,
                        "body": "Looks good!",
                        "issue": {
                            "number": 1559,
                            "title": "Unrelated PR",
                            "url": "https://github.com/other/repo/issues/1559",
                            "state": "OPEN",
                            "labels": {"nodes": [{"name": "enhancement"}]},
                            "repository": {"nameWithOwner": "other/repo"},
                            "assignees": {"nodes": []},
                            "comments": {
                                "totalCount": 1,
                                "nodes": [{"author": {"login": "me"}}],
                            },
                        },
                    },
                    # Stale solo application (> 18h)
                    {
                        "createdAt": t_stale,
                        "body": "Stellar Wave Program",
                        "issue": {
                            "number": 708,
                            "title": "Old receipt email",
                            "url": "https://github.com/accensa/accensa-app/issues/708",
                            "state": "OPEN",
                            "labels": {"nodes": [{"name": "drips-wave"}]},
                            "repository": {"nameWithOwner": "accensa/accensa-app"},
                            "assignees": {"nodes": []},
                            "comments": {
                                "totalCount": 1,
                                "nodes": [{"author": {"login": "me"}}],
                            },
                        },
                    },
                    # PR open for assigned issue
                    {
                        "createdAt": t_stale,
                        "body": "wave:application-id:123",
                        "issue": {
                            "number": 2224,
                            "title": "Fix chi v4",
                            "url": "https://github.com/dotandev/hintents/issues/2224",
                            "state": "OPEN",
                            "labels": {"nodes": [{"name": "drips-wave"}]},
                            "repository": {"nameWithOwner": "dotandev/hintents"},
                            "assignees": {"nodes": [{"login": "me"}]},
                            "comments": {
                                "totalCount": 2,
                                "nodes": [{"author": {"login": "me"}}],
                            },
                        },
                    },
                    # Fresh solo application
                    {
                        "createdAt": t_fresh,
                        "body": "wave:application-id:456",
                        "issue": {
                            "number": 260,
                            "title": "Countdown",
                            "url": "https://github.com/trustpay-escrow/trustpay-escrow/issues/260",
                            "state": "OPEN",
                            "labels": {"nodes": [{"name": "Stellar Wave"}]},
                            "repository": {
                                "nameWithOwner": "trustpay-escrow/trustpay-escrow"
                            },
                            "assignees": {"nodes": []},
                            "comments": {
                                "totalCount": 1,
                                "nodes": [{"author": {"login": "me"}}],
                            },
                        },
                    },
                    # Lost to competitor
                    {
                        "createdAt": t_fresh,
                        "body": "wave:application-id:789",
                        "issue": {
                            "number": 2079,
                            "title": "Cursor pagination",
                            "url": "https://github.com/Smartdevs17/SubTrackr/issues/2079",
                            "state": "OPEN",
                            "labels": {"nodes": [{"name": "drips-wave"}]},
                            "repository": {"nameWithOwner": "Smartdevs17/SubTrackr"},
                            "assignees": {"nodes": [{"login": "spencer-vs"}]},
                            "comments": {
                                "totalCount": 3,
                                "nodes": [
                                    {"author": {"login": "me"}},
                                    {"author": {"login": "spencer-vs"}},
                                    {"author": {"login": "drips-wave"}},
                                ],
                            },
                        },
                    },
                ]
            },
        },
    }

    client = GitHubWaveClient(
        http_client=httpx.AsyncClient(),
        username="me",
        token="tok",
        online_window_minutes=15,
        stale_hours=18,
    )
    parsed = client.parse_graphql_data(graphql_data, now=now)

    assert len(parsed.online_signals) == 1
    assert parsed.online_signals[0].repo == "trustpay-escrow/trustpay-escrow"
    assert parsed.online_signals[0].assigned_recently == 2

    by_num = {a.issue_number: a.state for a in parsed.applications}
    assert 1559 not in by_num
    assert by_num[708] == SlotState.STALE
    assert by_num[2224] == SlotState.PR_OPEN
    assert by_num[260] == SlotState.APPLIED_SOLO
    assert by_num[2079] == SlotState.LOST
