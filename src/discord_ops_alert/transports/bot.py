"""Bot transport — sends via Discord Bot token to a specific channel."""

from __future__ import annotations

from discord_ops_alert.errors import DiscordOpsError, ErrorCode
from discord_ops_alert.http import post_async, post_sync
from discord_ops_alert.retry import OnRetry, with_retry_async, with_retry_sync
from discord_ops_alert.types import NotifyInput, NotifyResult, RetryConfig

DISCORD_API_BASE = "https://discord.com/api/v10"

_SENTINEL = object()


class BotTransport:
    """Sends notifications via a Discord Bot token.

    Note:
        ``username`` and ``avatar_url`` fields in :class:`NotifyInput` are
        ignored for Bot transport — Discord's Bot API does not support
        per-message username or avatar overrides.

    Args:
        token: Discord Bot token (without the "Bot " prefix).
        channels: Mapping of topic name -> channel_id.
        timeout_ms: Per-request timeout in milliseconds.
        retry: Retry configuration. Defaults to RetryConfig().
        on_retry: Optional callback invoked before each retry.
    """

    def __init__(
        self,
        token: str,
        channels: dict[str, str],
        timeout_ms: int = 5000,
        retry: RetryConfig | None = _SENTINEL,  # type: ignore[assignment]
        on_retry: OnRetry = None,
    ) -> None:
        self._token = token
        self._channels = channels
        self._timeout_ms = timeout_ms
        self._retry: RetryConfig = RetryConfig() if retry is _SENTINEL else (retry or RetryConfig())
        self._on_retry = on_retry

    def _resolve_channel_id(self, input: NotifyInput) -> str:
        # Direct channel_id on the input takes precedence over topic mapping.
        if input.channel_id:
            return input.channel_id
        channel_id = self._channels.get(input.topic)
        if not channel_id:
            raise DiscordOpsError(
                ErrorCode.UNKNOWN_TOPIC,
                f'No channel ID configured for topic "{input.topic}"',
            )
        return channel_id

    def _build_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bot {self._token}"}

    async def send_async(self, input: NotifyInput) -> NotifyResult:
        """Send a notification asynchronously via Discord Bot API.

        Resolves channel_id from topic mapping or input.channel_id directly.
        Returns NotifyResult with ok=True and message_id on success.
        Raises DiscordOpsError(UNKNOWN_TOPIC) if topic is not configured
        and no channel_id is provided in input.
        """
        channel_id = self._resolve_channel_id(input)
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers = self._build_headers()
        body = {"content": input.message}

        attempts = 0

        async def _call() -> tuple[int, dict]:
            nonlocal attempts
            attempts += 1
            return await post_async(url, headers, body, self._timeout_ms)

        status, data = await with_retry_async(_call, self._retry, self._on_retry)

        if status >= 200 and status < 300:
            message_id = str(data["id"]) if isinstance(data.get("id"), (str, int)) else None
            return NotifyResult(ok=True, attempts=attempts, message_id=message_id)

        return NotifyResult(
            ok=False,
            attempts=attempts,
            error=f"Discord returned HTTP {status}",
        )

    def send_sync(self, input: NotifyInput) -> NotifyResult:
        """Synchronous version of send_async."""
        channel_id = self._resolve_channel_id(input)
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers = self._build_headers()
        body = {"content": input.message}

        attempts = 0

        def _call() -> tuple[int, dict]:
            nonlocal attempts
            attempts += 1
            return post_sync(url, headers, body, self._timeout_ms)

        status, data = with_retry_sync(_call, self._retry, self._on_retry)

        if status >= 200 and status < 300:
            message_id = str(data["id"]) if isinstance(data.get("id"), (str, int)) else None
            return NotifyResult(ok=True, attempts=attempts, message_id=message_id)

        return NotifyResult(
            ok=False,
            attempts=attempts,
            error=f"Discord returned HTTP {status}",
        )
