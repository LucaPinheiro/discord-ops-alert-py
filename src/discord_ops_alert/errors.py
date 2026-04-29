"""Error types for discord-ops-alert."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    CONFIG_ERROR = "config_error"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN_TOPIC = "unknown_topic"
    NETWORK_ERROR = "network_error"
    RATE_LIMITED = "rate_limited"
    DISCORD_ERROR = "discord_api_error"
    TIMEOUT = "timeout"


class RetryableError(Exception):
    """Raised by the HTTP layer to signal a retryable failure.

    Wraps the HTTP status code and response body so the retry engine can
    make an informed decision without coupling to httpx.
    """

    def __init__(self, status_code: int, body: str = "", retry_after_ms: int | None = None) -> None:
        super().__init__(f"HTTP {status_code}: {body}")
        self.status_code = status_code
        self.body = body
        self.retry_after_ms = retry_after_ms


class DiscordOpsError(Exception):
    """Exception raised by the SDK.

    In fire-and-forget mode these never leak out — they are logged.
    When using async_() they are returned as NotifyResult(ok=False), never raised.
    """

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        details: dict | None = None,
        *,
        status: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.code = ErrorCode(code) if isinstance(code, str) else code
        self.status = status
        self.details = details
        self.__cause__ = cause

    def __str__(self) -> str:
        return f"[{self.code}] {super().__str__()}"

    def __repr__(self) -> str:
        return (
            f"DiscordOpsError(code={self.code!r}, message={super().__str__()!r}, "
            f"status={self.status!r})"
        )
