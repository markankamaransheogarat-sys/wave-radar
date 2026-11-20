"""CLI entrypoint for Wave Radar."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from typing import Sequence

import httpx
from aiohttp import web

from wave_radar.clients.drips_client import DripsWaveClient
from wave_radar.clients.github_client import GitHubWaveClient
from wave_radar.clients.telegram import TelegramNotifier
from wave_radar.config import RadarConfig
from wave_radar.service import WaveRadarService, configure_logging, print_cli_summary
from wave_radar.web import create_web_app


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags."""
    parser = argparse.ArgumentParser(
        prog="wave-radar",
        description="Real-time Drips Stellar Wave online-maintainer radar & pitch generator.",
    )
    parser.add_argument(
        "--env-file", default=None, help="Path to .env configuration file."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan, print summary, and exit.",
    )
    parser.add_argument(
        "--no-web", action="store_true", help="Disable built-in local Web UI server."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not send Telegram messages."
    )
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    config = RadarConfig.from_env(dotenv_path=args.env_file)
    config.validate()
    configure_logging(log_file=config.log_file, level=config.log_level)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    timeout = httpx.Timeout(config.http_timeout_seconds)
    proxy = config.proxy_url or None

    async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as http_client:
        gh_client = GitHubWaveClient(
            http_client=http_client,
            username=config.github_username,
            token=config.github_token,
            online_window_minutes=config.online_window_minutes,
            stale_hours=config.stale_hours,
        )
        drips_client = DripsWaveClient(
            http_client=http_client,
            wave_program_id=config.wave_program_id,
        )
        telegram = (
            TelegramNotifier(
                http_client, config.telegram_bot_token, config.telegram_chat_id
            )
            if (config.telegram_enabled and not args.dry_run)
            else None
        )
        service = WaveRadarService(
            config=config,
            github_client=gh_client,
            drips_client=drips_client,
            telegram=telegram,
            dry_run=args.dry_run,
        )

        if args.once:
            snap = await service.scan_once()
            print_cli_summary(snap)
            return 0

        runner: web.AppRunner | None = None
        if not args.no_web:
            app = create_web_app(service)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, config.web_host, config.web_port)
            await site.start()
            print(
                f"Wave Radar Web UI listening on http://{config.web_host}:{config.web_port}"
            )

        try:
            await service.run_loop(stop_event=stop_event)
        finally:
            if runner is not None:
                await runner.cleanup()

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
