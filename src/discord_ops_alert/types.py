"""Public types for discord-ops-alert."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Environment = Literal["development", "test", "homologation", "staging", "production"]


@runtime_checkable
class Logger(Protocol):
    """Structural type for a compatible logger (stdlib logging.Logger satisfies this)."""

    def debug(self, msg: str, *args: object, **kwargs: object) -> None: ...
    def info(self, msg: str, *args: object, **kwargs: object) -> None: ...
    def warning(self, msg: str, *args: object, **kwargs: object) -> None: ...
    def error(self, msg: str, *args: object, **kwargs: object) -> None: ...


@dataclass
class RetryConfig:
    """Retry configuration for exponential backoff."""

    max_attempts: int = 3
    """Max attempts including the first one."""
    base_delay_ms: int = 250
    """Base delay in ms for exponential backoff."""
    max_delay_ms: int = 5000
    """Max delay cap in ms."""

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_ms < 0:
            raise ValueError("base_delay_ms must be >= 0")


@dataclass
class RetryEvent:
    """Emitted before each retry attempt."""

    attempt: int
    delay_ms: int
    reason: Literal["network", "timeout", "status"] | None = None
    status: int | None = None
    error: str | None = None


@dataclass
class NotifyInput:
    """Input for a notify call."""

    topic: str
    message: str
    channel_id: str | None = None
    username: str | None = None
    avatar_url: str | None = None


@dataclass
class NotifyResult:
    """Result returned by notify."""

    ok: bool
    attempts: int
    message_id: str | None = None
    error: str | None = None
    skipped: bool = False
