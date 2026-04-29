"""Webhook transport — sends to a Discord webhook URL directly."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from discord_ops_alert.errors import DiscordOpsError, ErrorCode
from discord_ops_alert.http import post_async, post_sync
from discord_ops_alert.retry import OnRetry, with_retry_async, with_retry_sync
from discord_ops_alert.types import NotifyInput, NotifyResult, RetryConfig

_SENTINEL = object()


class WebhookTransport:
    """Sends notifications via Discord incoming webhook URLs.

    Args:
        webhooks: Mapping of topic name -> webhook URL.
        timeout_ms: Per-request timeout in milliseconds.
        retry: Retry configuration. Defaults to RetryConfig().
        on_retry: Optional callback invoked before each retry.
        default_username: Default username override for all messages (webhook only).
        default_avatar_url: Default avatar URL for all messages (webhook only).
    """

    def __init__(
        self,
        webhooks: dict[str, str],
        timeout_ms: int = 5000,
        retry: RetryConfig | None = _SENTINEL,  # type: ignore[assignment]
        on_retry: OnRetry = None,
        default_username: str | None = None,
        default_avatar_url: str | None = None,
    ) -> None:
        self._webhooks = webhooks
        self._timeout_ms = timeout_ms
        self._retry: RetryConfig = RetryConfig() if retry is _SENTINEL else (retry or RetryConfig())
        self._on_retry = on_retry
        self._default_username = default_username
        self._default_avatar_url = default_avatar_url

    def _resolve_url(self, topic: str) -> str:
        url = self._webhooks.get(topic)
        if not url:
            raise DiscordOpsError(
                ErrorCode.UNKNOWN_TOPIC,
                f'No webhook URL configured for topic "{topic}"',
            )
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params["wait"] = ["true"]
        new_query = urlencode({k: v[0] for k, v in params.items()})
        return urlunparse(parsed._replace(query=new_query))

    def _build_body(self, input: NotifyInput) -> dict:
        body: dict = {"content": input.message}
        username = input.username or self._default_username
        avatar_url = input.avatar_url or self._default_avatar_url
        if username:
            body["username"] = username
        if avatar_url:
            body["avatar_url"] = avatar_url
        return body

    async def send_async(self, input: NotifyInput) -> NotifyResult:
        """Send a notification asynchronously via webhook."""
        url = self._resolve_url(input.topic)
        body = self._build_body(input)

        attempts = 0

        async def _call() -> tuple[int, dict]:
            nonlocal attempts
            attempts += 1
            return await post_async(url, {}, body, self._timeout_ms)

        status, data = await with_retry_async(_call, self._retry, self._on_retry)

        if 200 <= status < 300:
            message_id = str(data["id"]) if isinstance(data.get("id"), (str, int)) else None
            return NotifyResult(ok=True, attempts=attempts, message_id=message_id)

        return NotifyResult(ok=False, attempts=attempts, error=f"Discord returned HTTP {status}")

    def send_sync(self, input: NotifyInput) -> NotifyResult:
        """Synchronous version of send_async."""
        url = self._resolve_url(input.topic)
        body = self._build_body(input)

        attempts = 0

        def _call() -> tuple[int, dict]:
            nonlocal attempts
            attempts += 1
            return post_sync(url, {}, body, self._timeout_ms)

        status, data = with_retry_sync(_call, self._retry, self._on_retry)

        if 200 <= status < 300:
            message_id = str(data["id"]) if isinstance(data.get("id"), (str, int)) else None
            return NotifyResult(ok=True, attempts=attempts, message_id=message_id)

        return NotifyResult(ok=False, attempts=attempts, error=f"Discord returned HTTP {status}")
