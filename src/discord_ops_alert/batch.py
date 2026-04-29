"""Batching wrapper for Notifier — accumulates messages per topic in a time window."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from discord_ops_alert.notifier import Notifier
    from discord_ops_alert.types import NotifyResult


class BatchNotifier:
    """Wraps a Notifier and batches messages per topic within a time window.

    Window starts on first message for a topic. Subsequent messages in the same
    window join the batch. On window close:
    - 1 message → send as-is
    - N > 1 → send as "N events:\\n• msg1\\n• msg2..." truncated to 2000 chars
    """

    def __init__(self, notifier: "Notifier", window_ms: int = 3000) -> None:
        self._notifier = notifier
        self._window_ms = window_ms
        self._lock = threading.Lock()
        # topic -> list of messages
        self._pending: dict[str, list[str]] = {}
        # topic -> Timer
        self._timers: dict[str, threading.Timer] = {}

    def __call__(self, *, topic: str, message: str, **kwargs: Any) -> None:
        """Fire-and-forget: add message to batch, starts window if first for topic."""
        with self._lock:
            if topic not in self._pending:
                self._pending[topic] = []
                timer = threading.Timer(
                    self._window_ms / 1000.0,
                    self._fire,
                    kwargs={"topic": topic, **{k: v for k, v in kwargs.items()}},
                )
                self._timers[topic] = timer
                timer.daemon = True
                timer.start()
            self._pending[topic].append(message)

    async def async_(self, *, topic: str, message: str, **kwargs: Any) -> "NotifyResult":
        """Async variant: same as __call__ but returns a NotifyResult after flush."""
        self(topic=topic, message=message, **kwargs)
        return await self.flush()

    async def flush(self) -> "NotifyResult":
        """Drain all pending topics immediately. Returns last NotifyResult."""
        topics_to_fire: list[str] = []
        with self._lock:
            for _, timer in list(self._timers.items()):
                timer.cancel()
            topics_to_fire = list(self._pending.keys())
            self._timers.clear()

        last_result: "NotifyResult | None" = None
        for topic in topics_to_fire:
            with self._lock:
                messages = self._pending.pop(topic, [])
            if messages:
                batched = _build_batched_message(messages)
                last_result = await self._notifier.async_(topic=topic, message=batched)

        if last_result is None:
            # Nothing was pending — return a dummy ok result
            from discord_ops_alert.types import NotifyResult

            return NotifyResult(ok=True, attempts=0)

        return last_result

    def _fire(self, *, topic: str, **kwargs: Any) -> None:
        """Called by Timer when window closes — sends the batch."""
        with self._lock:
            messages = self._pending.pop(topic, [])
            self._timers.pop(topic, None)
        if messages:
            batched = _build_batched_message(messages)
            self._notifier(topic=topic, message=batched, **kwargs)


def _build_batched_message(messages: list[str]) -> str:
    """Build the batched message string. 1 message → as-is. N > 1 → formatted list."""
    if len(messages) == 1:
        return messages[0]

    header = f"{len(messages)} events:\n"
    bullets = [f"• {m}" for m in messages]
    body = "\n".join(bullets)
    full = header + body

    if len(full) <= 2000:
        return full

    # Truncate: keep as many bullets as fit, add "... and N more"
    result = header
    added = 0
    for bullet in bullets:
        candidate = result + bullet + "\n"
        if len(candidate) + 20 > 2000:  # leave room for "... and N more"
            break
        result = candidate
        added += 1
    remaining = len(messages) - added
    return result.rstrip("\n") + f"\n... and {remaining} more"


def create_batch_notifier(notifier: "Notifier", window_ms: int = 3000) -> BatchNotifier:
    """Factory: create a BatchNotifier wrapping the given notifier."""
    return BatchNotifier(notifier, window_ms=window_ms)
