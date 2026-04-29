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
    if retry_after_ms is not None and retry_after_ms >= 0:
        return min(retry_after_ms, config.max_delay_ms)
    exp = config.base_delay_ms * (2 ** (attempt - 1))
    capped = min(exp, config.max_delay_ms)
    return random.randint(0, max(0, capped))


def _last_error_to_discord_ops(exc: BaseException) -> DiscordOpsError:
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


async def with_retry_async(fn: Callable[[], Awaitable[T]], config: RetryConfig | None = None, on_retry: OnRetry = None) -> T:
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
                on_retry(RetryEvent(attempt=attempt, delay_ms=delay_ms, reason="status", status=exc.status_code, error=str(exc)))
            await asyncio.sleep(delay_ms / 1000)
        except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg)
            if on_retry is not None:
                on_retry(RetryEvent(attempt=attempt, delay_ms=delay_ms, reason="timeout", error=str(exc)))
            await asyncio.sleep(delay_ms / 1000)
        except OSError as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg)
            if on_retry is not None:
                on_retry(RetryEvent(attempt=attempt, delay_ms=delay_ms, reason="network", error=str(exc)))
            await asyncio.sleep(delay_ms / 1000)
    raise _last_error_to_discord_ops(last_exc) from last_exc  # type: ignore[arg-type]


def with_retry_sync(fn: Callable[[], T], config: RetryConfig | None = None, on_retry: OnRetry = None) -> T:
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
                on_retry(RetryEvent(attempt=attempt, delay_ms=delay_ms, reason="status", status=exc.status_code, error=str(exc)))
            time.sleep(delay_ms / 1000)
        except (TimeoutError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg)
            if on_retry is not None:
                on_retry(RetryEvent(attempt=attempt, delay_ms=delay_ms, reason="timeout", error=str(exc)))
            time.sleep(delay_ms / 1000)
        except OSError as exc:
            last_exc = exc
            if attempt >= cfg.max_attempts:
                break
            delay_ms = _compute_backoff(attempt, cfg)
            if on_retry is not None:
                on_retry(RetryEvent(attempt=attempt, delay_ms=delay_ms, reason="network", error=str(exc)))
            time.sleep(delay_ms / 1000)
    raise _last_error_to_discord_ops(last_exc) from last_exc  # type: ignore[arg-type]
