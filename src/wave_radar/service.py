"""Core Wave Radar orchestration, transition detection, and drift-free polling."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Callable

import httpx

from wave_radar.clients.drips_client import DripsWaveClient
from wave_radar.clients.github_client import GitHubWaveClient
from wave_radar.clients.telegram import TelegramNotifier
from wave_radar.config import RadarConfig
from wave_radar.models import (
    OnlineMaintainerSignal,
    RadarEvent,
    RadarSnapshot,
    RadarStateMemory,
    SlotState,
)

logger = logging.getLogger(__name__)


def configure_logging(log_file: str, level: str = "INFO") -> None:
    """Configure root logging to stdout and a size-rotated `radar.log`."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for h in list(root.handlers):
        root.removeHandler(h)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    file_h = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    root.addHandler(file_h)


def format_hot_maintainer_telegram(signal: OnlineMaintainerSignal) -> str:
    """Format an urgent Telegram HTML card for an online maintainer with open candidates."""
    lines = [
        f"🔥 <b>МЕЙНТЕЙНЕР ОНЛАЙН:</b> <code>{html.escape(signal.repo)}</code>",
        f"Назначил <b>{signal.assigned_recently}</b> задач(и) за окно "
        f"(последняя #{signal.latest_issue_number} → {html.escape(signal.latest_assignee)}).",
        "",
    ]
    for cand in signal.candidates[:3]:
        lines.append(
            f"• <b>#{cand.issue_number}</b> ({cand.points} pts, {cand.pending_apps} apps): "
            f'<a href="{html.escape(cand.drips_url, quote=True)}">Открыть в Drips</a>'
        )
        lines.append(f"<pre>{html.escape(cand.pitch)}</pre>")
    return "\n".join(lines)


class WaveRadarService:
    """Polls GitHub & Drips Wave to detect live maintainer activity and track 15/15 slots."""

    def __init__(
        self,
        config: RadarConfig,
        github_client: GitHubWaveClient,
        drips_client: DripsWaveClient,
        telegram: TelegramNotifier | None = None,
        dry_run: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._github = github_client
        self._drips = drips_client
        self._telegram = telegram
        self._dry_run = dry_run
        self._clock = clock or (lambda: asyncio.get_running_loop().time())
        self._memory = RadarStateMemory()
        self.latest_snapshot: RadarSnapshot | None = None
        self._scan_lock = asyncio.Lock()

    async def scan_once(self, now: datetime | None = None) -> RadarSnapshot:
        """Run one radar sweep, enrich hot maintainers via Drips, and emit transition alerts."""
        async with self._scan_lock:
            ref_now = now or datetime.now(timezone.utc)
            try:
                gh_data = await self._github.fetch_radar_data(now=ref_now)
            except Exception as exc:
                logger.warning("GitHub radar scan failed: %s", exc)
                prev = self.latest_snapshot
                snapshot = RadarSnapshot(
                    generated_at=ref_now,
                    username=self._config.github_username,
                    online_window_minutes=self._config.online_window_minutes,
                    hot_maintainers=prev.hot_maintainers if prev else (),
                    applications=prev.applications if prev else (),
                    events=tuple(self._memory.activity_log[-30:]),
                    active_slots_count=prev.active_slots_count if prev else 0,
                    solo_slots_count=prev.solo_slots_count if prev else 0,
                    stale_slots_count=prev.stale_slots_count if prev else 0,
                    assigned_count=prev.assigned_count if prev else 0,
                    scan_error=str(exc),
                )
                self.latest_snapshot = snapshot
                return snapshot

            applied_keys = {
                f"{app.repo}#{app.issue_number}" for app in gh_data.applications
            }
            hot_top = gh_data.online_signals[:6]

            candidate_lists = await asyncio.gather(
                *[
                    self._drips.fetch_repo_candidates(
                        repo_full_name=sig.repo,
                        min_points=self._config.min_points,
                        max_pending_apps=self._config.max_pending_apps,
                        limit=self._config.max_candidates_per_repo,
                        exclude_keys=applied_keys,
                    )
                    for sig in hot_top
                ],
                return_exceptions=True,
            )

            enriched_signals: list[OnlineMaintainerSignal] = []
            for sig, cands in zip(hot_top, candidate_lists, strict=True):
                if isinstance(cands, BaseException):
                    logger.warning(
                        "Drips enrichment failed for %s: %s", sig.repo, cands
                    )
                    enriched_signals.append(sig)
                else:
                    enriched_signals.append(
                        OnlineMaintainerSignal(
                            repo=sig.repo,
                            assigned_recently=sig.assigned_recently,
                            latest_assigned_at=sig.latest_assigned_at,
                            latest_issue_number=sig.latest_issue_number,
                            latest_assignee=sig.latest_assignee,
                            candidates=tuple(cands),
                        )
                    )

            await self._process_transitions(
                ref_now, enriched_signals, gh_data.applications
            )

            active_states = {
                SlotState.APPLIED_SOLO,
                SlotState.APPLIED_COMPETED,
                SlotState.STALE,
                SlotState.ASSIGNED,
            }
            active_apps = [a for a in gh_data.applications if a.state in active_states]
            solo_apps = [
                a for a in gh_data.applications if a.state == SlotState.APPLIED_SOLO
            ]
            stale_apps = [a for a in gh_data.applications if a.state == SlotState.STALE]
            assigned_apps = [
                a
                for a in gh_data.applications
                if a.state in (SlotState.ASSIGNED, SlotState.PR_OPEN)
            ]

            snapshot = RadarSnapshot(
                generated_at=ref_now,
                username=self._config.github_username,
                online_window_minutes=self._config.online_window_minutes,
                hot_maintainers=tuple(enriched_signals),
                applications=tuple(gh_data.applications),
                events=tuple(reversed(self._memory.activity_log[-30:])),
                active_slots_count=len(active_apps),
                solo_slots_count=len(solo_apps),
                stale_slots_count=len(stale_apps),
                assigned_count=len(assigned_apps),
                scan_error=None,
            )
            self.latest_snapshot = snapshot
            return snapshot

    async def _send_alert(self, html_text: str) -> None:
        if self._dry_run or self._telegram is None:
            return
        await self._telegram.send_html(html_text)

    def _record_event(self, now: datetime, kind: str, message: str) -> None:
        self._memory.activity_log.append(
            RadarEvent(timestamp=now, kind=kind, message=message)
        )
        if len(self._memory.activity_log) > 100:
            self._memory.activity_log = self._memory.activity_log[-100:]

    async def _process_transitions(
        self,
        now: datetime,
        signals: list[OnlineMaintainerSignal],
        applications: list,
    ) -> None:
        first_run = not (self._memory.known_assigned or self._memory.known_lost)
        for app in applications:
            key = f"{app.repo}#{app.issue_number}"
            if (
                app.state == SlotState.ASSIGNED
                and key not in self._memory.known_assigned
            ):
                self._memory.known_assigned.add(key)
                msg = f"🎉 НАЗНАЧЕНО НАМ: {key} — {app.title}"
                self._record_event(now, "assigned", msg)
                if not first_run:
                    await self._send_alert(
                        f"🎉 <b>НАЗНАЧЕНА ЗАДАЧА:</b> <code>{html.escape(key)}</code>\n"
                        f'<a href="{html.escape(app.url, quote=True)}">{html.escape(app.title)}</a>'
                    )
            elif app.state == SlotState.LOST and key not in self._memory.known_lost:
                self._memory.known_lost.add(key)
                if not first_run:
                    msg = (
                        f"🔓 Слот освободился: {key} (ушла {app.assignee or 'другому'})"
                    )
                    self._record_event(now, "lost", msg)
                    await self._send_alert(
                        f"🔓 <b>Слот освободился:</b> <code>{html.escape(key)}</code> "
                        f"→ {html.escape(app.assignee or 'закрыта')}"
                    )

        cooldown = timedelta(minutes=15)
        for sig in signals:
            if not sig.candidates:
                continue
            last_alerted = self._memory.alerted_hot_keys.get(sig.repo)
            if last_alerted is not None and (now - last_alerted) < cooldown:
                continue
            self._memory.alerted_hot_keys[sig.repo] = now
            msg = (
                f"🔥 {sig.repo} онлайн ({sig.assigned_recently}x за "
                f"{self._config.online_window_minutes}м) — найдено {len(sig.candidates)} шт. на {self._config.min_points} pts"
            )
            self._record_event(now, "hot", msg)
            await self._send_alert(format_hot_maintainer_telegram(sig))

    async def run_loop(self, stop_event: asyncio.Event | None = None) -> None:
        """Run drift-free periodic scanning until `stop_event` is set."""
        stopper = stop_event or asyncio.Event()
        deadline = self._clock()
        while not stopper.is_set():
            snap = await self.scan_once()
            logger.info(
                "Radar scan complete: hot_repos=%d, active_slots=%d, solo=%d, stale=%d, assigned=%d",
                len(snap.hot_maintainers),
                snap.active_slots_count,
                snap.solo_slots_count,
                snap.stale_slots_count,
                snap.assigned_count,
            )
            deadline += self._config.scan_interval_seconds
            now_mono = self._clock()
            if deadline < now_mono:
                deadline = now_mono + self._config.scan_interval_seconds
            delay = max(0.0, deadline - now_mono)
            try:
                await asyncio.wait_for(stopper.wait(), timeout=delay)
                break
            except TimeoutError:
                continue


def print_cli_summary(snapshot: RadarSnapshot) -> None:
    """Print a concise console summary for `--once` or headless terminal runs."""
    print(
        f"=== Wave Radar | {snapshot.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
        f"Slots: {snapshot.active_slots_count}/15 (solo={snapshot.solo_slots_count}, "
        f"stale={snapshot.stale_slots_count}, assigned={snapshot.assigned_count}) ==="
    )
    if snapshot.scan_error:
        print(f"ERROR: {snapshot.scan_error}")
    print("\n--- HOT MAINTAINERS ONLINE ---")
    if not snapshot.hot_maintainers:
        print("  (no assignments detected in current window)")
    for sig in snapshot.hot_maintainers:
        print(
            f"  * {sig.repo}: {sig.assigned_recently}x assigned "
            f"(latest #{sig.latest_issue_number} -> {sig.latest_assignee})"
        )
        for cand in sig.candidates:
            print(
                f"      #{cand.issue_number} [{cand.points} pts, {cand.pending_apps} apps]: {cand.drips_url}"
            )
            print(f"      PITCH: {cand.pitch.replace(chr(10), ' ')}")
