"""discord-ops-alert — plug-and-play Discord alerts for your Python backend."""

from discord_ops_alert.batch import BatchNotifier, create_batch_notifier
from discord_ops_alert.errors import DiscordOpsError, ErrorCode
from discord_ops_alert.logger import default_logger, silent_logger
from discord_ops_alert.notifier import Notifier, create_notifier
from discord_ops_alert.types import (
    Embed,
    EmbedField,
    Environment,
    Logger,
    NotifyInput,
    NotifyResult,
    RetryConfig,
    RetryEvent,
)

__all__ = [
    "create_notifier",
    "Notifier",
    "NotifyResult",
    "NotifyInput",
    "RetryConfig",
    "RetryEvent",
    "Logger",
    "Environment",
    "DiscordOpsError",
    "ErrorCode",
    "default_logger",
    "silent_logger",
    "Embed",
    "EmbedField",
    "BatchNotifier",
    "create_batch_notifier",
]
