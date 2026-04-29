"""Bot transport — sends via Discord Bot token to a specific channel."""

from __future__ import annotations
from discord_ops_alert.errors import DiscordOpsError, ErrorCode
from discord_ops_alert.http import post_async, post_sync
from discord_ops_alert.retry import OnRetry, with_retry_async, with_retry_sync
from discord_ops_alert.types import NotifyInput, NotifyResult, RetryConfig

DISCORD_API_BASE = "https://discord.com/api/v10"
_SENTINEL = object()


class BotTransport:
    """username and avatar_url in NotifyInput are ignored — Bot API does not support them."""

    def __init__(self, token: str, channels: dict[str, str], timeout_ms: int = 5000, retry: RetryConfig | None = _SENTINEL, on_retry: OnRetry = None) -> None:  # type: ignore[assignment]
        self._token = token
        self._channels = channels
        self._timeout_ms = timeout_ms
        self._retry: RetryConfig = RetryConfig() if retry is _SENTINEL else (retry or RetryConfig())
        self._on_retry = on_retry

    def _resolve_channel_id(self, input: NotifyInput) -> str:
        if input.channel_id:
            return input.channel_id
        channel_id = self._channels.get(input.topic)
        if not channel_id:
            raise DiscordOpsError(ErrorCode.UNKNOWN_TOPIC, f'No channel ID configured for topic "{input.topic}"')
        return channel_id

    async def send_async(self, input: NotifyInput) -> NotifyResult:
        channel_id = self._resolve_channel_id(input)
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {self._token}"}
        body = {"content": input.message}
        attempts = 0

        async def _call() -> tuple[int, dict]:
            nonlocal attempts
            attempts += 1
            return await post_async(url, headers, body, self._timeout_ms)

        status, data = await with_retry_async(_call, self._retry, self._on_retry)
        if 200 <= status < 300:
            return NotifyResult(ok=True, attempts=attempts, message_id=str(data["id"]) if isinstance(data.get("id"), (str, int)) else None)
        return NotifyResult(ok=False, attempts=attempts, error=f"Discord returned HTTP {status}")

    def send_sync(self, input: NotifyInput) -> NotifyResult:
        channel_id = self._resolve_channel_id(input)
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {self._token}"}
        body = {"content": input.message}
        attempts = 0

        def _call() -> tuple[int, dict]:
            nonlocal attempts
            attempts += 1
            return post_sync(url, headers, body, self._timeout_ms)

        status, data = with_retry_sync(_call, self._retry, self._on_retry)
        if 200 <= status < 300:
            return NotifyResult(ok=True, attempts=attempts, message_id=str(data["id"]) if isinstance(data.get("id"), (str, int)) else None)
        return NotifyResult(ok=False, attempts=attempts, error=f"Discord returned HTTP {status}")
