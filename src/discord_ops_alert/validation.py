"""Pydantic v2 models for validating create_notifier() options at init time."""

from __future__ import annotations
import re
from typing import Callable, Literal
from pydantic import BaseModel, Field, ValidationError, field_validator
from discord_ops_alert.errors import DiscordOpsError, ErrorCode
from discord_ops_alert.types import NotifyInput, RetryConfig, RetryEvent

_WEBHOOK_PREFIX = "https://discord.com/api/webhooks/"
_SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")
_BOT_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{24,}\.[A-Za-z0-9._-]{6,}\.[A-Za-z0-9._-]{27,}$")
_MAX_MESSAGE_LENGTH = 2000
_MAX_USERNAME_LENGTH = 80

OnError = Callable[["DiscordOpsError", "NotifyInput"], None] | None
OnRetry = Callable[["RetryEvent"], None] | None


class WebhookOptions(BaseModel):
    mode: Literal["webhook"]
    webhooks: dict[str, str]
    enabled_in: list[str] = Field(default_factory=list)
    timeout_ms: int = 5000
    retry: RetryConfig = Field(default_factory=RetryConfig)
    on_error: OnError = None
    on_retry: OnRetry = None
    default_username: str | None = None
    default_avatar_url: str | None = None
    model_config = {"arbitrary_types_allowed": True}

    @field_validator("webhooks")
    @classmethod
    def validate_webhooks(cls, v: dict[str, str]) -> dict[str, str]:
        for topic, url in v.items():
            if not url.startswith(_WEBHOOK_PREFIX):
                raise ValueError(f"Invalid webhook URL for topic '{topic}': must start with {_WEBHOOK_PREFIX}")
        return v

    @field_validator("default_username")
    @classmethod
    def validate_default_username(cls, v: str | None) -> str | None:
        if v is not None and len(v) > _MAX_USERNAME_LENGTH:
            raise ValueError(f"default_username must be at most {_MAX_USERNAME_LENGTH} characters")
        return v


class BotOptions(BaseModel):
    mode: Literal["bot"]
    token: str
    channels: dict[str, str]
    enabled_in: list[str] = Field(default_factory=list)
    timeout_ms: int = 5000
    retry: RetryConfig = Field(default_factory=RetryConfig)
    on_error: OnError = None
    on_retry: OnRetry = None
    model_config = {"arbitrary_types_allowed": True}

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        if not _BOT_TOKEN_RE.match(v):
            raise ValueError("Discord bot token must match the format: <24+ chars>.<6+ chars>.<27+ chars>")
        return v

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: dict[str, str]) -> dict[str, str]:
        for topic, channel_id in v.items():
            if not _SNOWFLAKE_RE.fullmatch(channel_id):
                raise ValueError(f"Invalid channel_id for topic '{topic}': must be 17-20 digits (Discord snowflake)")
        return v


def validate_webhook_options(raw: dict) -> WebhookOptions:
    try:
        return WebhookOptions(**raw)
    except ValidationError as e:
        raise DiscordOpsError(ErrorCode.CONFIG_ERROR, str(e)) from e


def validate_bot_options(raw: dict) -> BotOptions:
    try:
        return BotOptions(**raw)
    except ValidationError as e:
        raise DiscordOpsError(ErrorCode.CONFIG_ERROR, str(e)) from e


def validate_notify_input(input: NotifyInput) -> None:
    if not input.message:
        raise DiscordOpsError(ErrorCode.VALIDATION_ERROR, "message must be non-empty")
    if len(input.message) > _MAX_MESSAGE_LENGTH:
        raise DiscordOpsError(ErrorCode.VALIDATION_ERROR, f"message exceeds Discord's {_MAX_MESSAGE_LENGTH} character limit ({len(input.message)} chars)")
    if input.username is not None and len(input.username) > _MAX_USERNAME_LENGTH:
        raise DiscordOpsError(ErrorCode.VALIDATION_ERROR, f"username must be at most {_MAX_USERNAME_LENGTH} characters")
