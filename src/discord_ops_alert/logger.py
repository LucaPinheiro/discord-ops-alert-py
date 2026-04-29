"""Logger utilities for discord-ops-alert."""

from __future__ import annotations
import logging
from discord_ops_alert.types import Logger

_PREFIX = "discord_ops_alert"


def make_logger(name: str = _PREFIX, logger: Logger | None = None) -> Logger:
    if logger is not None:
        return logger
    return logging.getLogger(name)


class _SilentLogger:
    def debug(self, msg: str, *args: object, **kwargs: object) -> None: pass
    def info(self, msg: str, *args: object, **kwargs: object) -> None: pass
    def warning(self, msg: str, *args: object, **kwargs: object) -> None: pass
    def error(self, msg: str, *args: object, **kwargs: object) -> None: pass


def _make_default_logger() -> logging.Logger:
    logger = logging.getLogger(_PREFIX)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[discord-ops] %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


silent_logger: Logger = _SilentLogger()
default_logger: Logger = _make_default_logger()
