"""Retry logic with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from discord_ops_alert.errors import DiscordOpsError, ErrorCode, RetryableError
from discord_ops_alert.types import RetryConfig, RetryEvent

T = TypeVar("T")

OnRetry = Callable[[RetryEvent], None] | None


def _compute_backoff(attempt: int, config: RetryConfig, retry_after_ms: int | None = None) -> int:
    """Exponential backoff with full jitter.

    *attempt* is 1-indexed (1 = first retry, i.e. after the 1st failure).
    Returns the delay in milliseconds to wait before the next attempt.
    """
    if retry_after_ms is not None and retry_after_ms >= 0:
        return min(retry_after_ms, config.max_delay_ms)
    exp = config.base_delay_ms * (2 ** (attempt - 1))
    capped = min(exp, config.max_delay_ms)
    return random.randint(0, max(0, capped))


def is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def _last_error_to_discord_ops(exc: BaseException) -> DiscordOpsError:
    """Convert the last caught exception into a typed DiscordOpsError."""
    if isinstance(exc, RetryableError):
        code = ErrorCode.RATE_LIMITED if exc.status_code == 429 else ErrorCode.DISCORD_ERROR
        return DiscordOpsError(code, str(exc), status=exc.status_code, cause=exc)
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        return DiscordOpsError(ErrorCode.TIMEOUT, str(exc), cause=exc)
    if isinstance(exc, OSError):
        return DiscordOpsError(ErrorCode.NETWORK_ERROR, str(exc), cause=exc)
    if isinstance(exc, DiscordOpsError):
        return exc
    return DiscordOpsError(ErrorCode.DISCORD_ERROR, str(exc), cause=exc)


async def with_retry_async(
    fn: Callable[[], Awaitable[T]],
    config: RetryConfig | None = None,
    on_retry: OnRetry = None,
) -> T:
    """Call *fn* up to *config.max_attempts* times with exponential backoff.

    *fn* is an async callable that either returns a value or raises
    :class:`RetryableError` to signal a transient failure.

    :raises DiscordOpsError: After all attempts are exhausted, re-raises the
        last error as a typed DiscordOpsError (RATE_LIMITED, TIMEOUT, etc.).
    """
    cfg = config or RetryConfig()
    last_exc: BaseException | None = None

    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return await fn()
        except RetryableError as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg, exc.retry_after_ms)
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        reason="status",
                        status=exc.status_code,
                        error=str(exc),
                    )
                )
            await asyncio.sleep(delay_ms / 1000)
        except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg)
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        reason="timeout",
                        error=str(exc),
                    )
                )
            await asyncio.sleep(delay_ms / 1000)
        except OSError as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg)
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        reason="network",
                        error=str(exc),
                    )
                )
            await asyncio.sleep(delay_ms / 1000)

    typed = _last_error_to_discord_ops(last_exc)  # type: ignore[arg-type]
    raise typed from last_exc


def with_retry_sync(
    fn: Callable[[], T],
    config: RetryConfig | None = None,
    on_retry: OnRetry = None,
) -> T:
    """Synchronous equivalent of :func:`with_retry_async`."""
    cfg = config or RetryConfig()
    last_exc: BaseException | None = None

    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return fn()
        except RetryableError as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg, exc.retry_after_ms)
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        reason="status",
                        status=exc.status_code,
                        error=str(exc),
                    )
                )
            time.sleep(delay_ms / 1000)
        except (TimeoutError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg)
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        reason="timeout",
                        error=str(exc),
                    )
                )
            time.sleep(delay_ms / 1000)
        except OSError as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg)
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        reason="network",
                        error=str(exc),
                    )
                )
            time.sleep(delay_ms / 1000)

    typed = _last_error_to_discord_ops(last_exc)  # type: ignore[arg-type]
    raise typed from last_exc
