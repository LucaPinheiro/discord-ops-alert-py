"""Notifier factory — create_notifier() and the Notifier class."""

from __future__ import annotations
import os
import threading
from typing import Any
from discord_ops_alert.errors import DiscordOpsError, ErrorCode
from discord_ops_alert.logger import make_logger
from discord_ops_alert.transports.bot import BotTransport
from discord_ops_alert.transports.webhook import WebhookTransport
from discord_ops_alert.types import NotifyInput, NotifyResult
from discord_ops_alert.validation import OnError, validate_bot_options, validate_notify_input, validate_webhook_options


def _get_current_env() -> str:
    return os.environ.get("STAGE", "")


class Notifier:
    """Callable for fire-and-forget. Use .async_() for the awaitable variant."""

    def __init__(self, transport: WebhookTransport | BotTransport, enabled_in: list[str], on_error: OnError) -> None:
        self._transport = transport
        self._enabled_in = enabled_in
        self._on_error = on_error
        self._logger = make_logger()

    def _is_enabled(self) -> bool:
        if not self._enabled_in:
            return True
        return _get_current_env() in self._enabled_in

    def __call__(self, *, topic: str, message: str, channel_id: str | None = None, username: str | None = None, avatar_url: str | None = None) -> None:
        """Fire-and-forget: spawn daemon thread, return immediately, never raises."""
        if not self._is_enabled():
            return None
        input_ = NotifyInput(topic=topic, message=message, channel_id=channel_id, username=username, avatar_url=avatar_url)
        try:
            validate_notify_input(input_)
        except DiscordOpsError as exc:
            self._logger.error("discord_ops_alert: validation failed topic=%s error=%s", topic, str(exc))
            if self._on_error:
                try:
                    self._on_error(exc, input_)
                except Exception:
                    pass
            return None
        self._fire_and_forget(input_)
        return None

    def _fire_and_forget(self, input_: NotifyInput) -> None:
        def _run() -> None:
            try:
                result = self._transport.send_sync(input_)
                if result.ok:
                    self._logger.debug("notification sent topic=%s attempts=%d", input_.topic, result.attempts)
                else:
                    self._logger.error("discord_ops_alert: send failed topic=%s error=%s", input_.topic, result.error)
                    if self._on_error:
                        try:
                            self._on_error(DiscordOpsError(ErrorCode.DISCORD_ERROR, result.error or "unknown"), input_)
                        except Exception:
                            pass
            except DiscordOpsError as e:
                self._logger.error("discord_ops_alert: send failed topic=%s code=%s error=%s", input_.topic, e.code, str(e))
                if self._on_error:
                    try:
                        self._on_error(e, input_)
                    except Exception:
                        pass
            except Exception as e:
                self._logger.error("discord_ops_alert: unexpected error topic=%s error=%s", input_.topic, str(e))
                if self._on_error:
                    try:
                        self._on_error(DiscordOpsError(ErrorCode.DISCORD_ERROR, str(e), cause=e), input_)
                    except Exception:
                        pass
        threading.Thread(target=_run, daemon=True).start()

    async def async_(self, *, topic: str, message: str, channel_id: str | None = None, username: str | None = None, avatar_url: str | None = None) -> NotifyResult:
        """Awaitable variant. Always returns NotifyResult — never raises."""
        if not self._is_enabled():
            return NotifyResult(ok=True, attempts=0, skipped=True)
        input_ = NotifyInput(topic=topic, message=message, channel_id=channel_id, username=username, avatar_url=avatar_url)
        try:
            validate_notify_input(input_)
            result = await self._transport.send_async(input_)
            if result.ok:
                self._logger.info("discord_ops_alert: notification sent topic=%s attempts=%d", topic, result.attempts)
            else:
                exc = DiscordOpsError(ErrorCode.DISCORD_ERROR, result.error or "Discord returned a non-2xx response")
                if self._on_error:
                    try:
                        self._on_error(exc, input_)
                    except Exception:
                        pass
            return result
        except DiscordOpsError as exc:
            self._logger.error("discord_ops_alert: send failed topic=%s code=%s error=%s", topic, exc.code, str(exc))
            if self._on_error:
                try:
                    self._on_error(exc, input_)
                except Exception:
                    pass
            return NotifyResult(ok=False, attempts=0, error=f"{exc.code}: {exc.args[0]}")
        except Exception as exc:
            self._logger.error("discord_ops_alert: unexpected error topic=%s error=%s", topic, str(exc))
            ops = DiscordOpsError(ErrorCode.DISCORD_ERROR, str(exc), cause=exc)
            if self._on_error:
                try:
                    self._on_error(ops, input_)
                except Exception:
                    pass
            return NotifyResult(ok=False, attempts=0, error=f"discord_api_error: {exc}")


def create_notifier(*, mode: str, **kwargs: Any) -> Notifier:
    """Factory function. Raises DiscordOpsError(CONFIG_ERROR) on invalid options."""
    raw = {"mode": mode, **kwargs}
    if mode == "webhook":
        opts = validate_webhook_options(raw)
        transport: WebhookTransport | BotTransport = WebhookTransport(
            webhooks=opts.webhooks, timeout_ms=opts.timeout_ms, retry=opts.retry,
            on_retry=opts.on_retry, default_username=opts.default_username, default_avatar_url=opts.default_avatar_url,
        )
        return Notifier(transport=transport, enabled_in=opts.enabled_in, on_error=opts.on_error)
    if mode == "bot":
        opts_bot = validate_bot_options(raw)
        transport = BotTransport(
            token=opts_bot.token, channels=opts_bot.channels, timeout_ms=opts_bot.timeout_ms,
            retry=opts_bot.retry, on_retry=opts_bot.on_retry,
        )
        return Notifier(transport=transport, enabled_in=opts_bot.enabled_in, on_error=opts_bot.on_error)
    raise DiscordOpsError(ErrorCode.CONFIG_ERROR, f"Unknown mode '{mode}': must be 'webhook' or 'bot'")
