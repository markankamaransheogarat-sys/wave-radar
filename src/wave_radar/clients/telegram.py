"""Optional async Telegram Bot API notifier for hot maintainers and slot changes."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends HTML notifications to Telegram without raising on transient failures."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        bot_token: str,
        chat_id: str,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self._client = http_client
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._base_url = base_url.rstrip("/")

    async def send_html(self, text: str) -> bool:
        """Dispatch a Telegram HTML message; returns True when accepted."""
        url = f"{self._base_url}/bot{self._bot_token}/sendMessage"
        try:
            resp = await self._client.post(
                url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
            return bool(resp.json().get("ok", False))
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Telegram HTTP %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Telegram send failed (%s): %s", type(exc).__name__, exc)
            return False
