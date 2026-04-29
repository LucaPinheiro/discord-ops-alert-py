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
        # topic -> (messages, kwargs)
        self._pending: dict[str, tuple[list[str], dict[str, Any]]] = {}
        # topic -> Timer
        self._timers: dict[str, threading.Timer] = {}

    def __call__(self, *, topic: str, message: str, **kwargs: Any) -> None:
        """Fire-and-forget: add message to batch, starts window if first for topic."""
        with self._lock:
            if topic not in self._pending:
                self._pending[topic] = ([], kwargs)
                timer = threading.Timer(
                    self._window_ms / 1000.0,
                    self._fire,
                    kwargs={"topic": topic},
                )
                self._timers[topic] = timer
                timer.daemon = True
                timer.start()
            self._pending[topic][0].append(message)

    async def async_(self, *, topic: str, message: str, **kwargs: Any) -> "NotifyResult":
        """Async variant: adds message to batch then flushes all pending topics.

        Note: flush() drains ALL topics, not just the one just added.
        """
        self(topic=topic, message=message, **kwargs)
        return await self.flush()

    async def flush(self) -> "NotifyResult":
        """Drain all pending topics immediately. Returns last NotifyResult."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            snapshot = dict(self._pending)
            self._pending.clear()
            self._timers.clear()

        last_result: "NotifyResult | None" = None
        for topic, (messages, kwargs) in snapshot.items():
            if messages:
                batched = _build_batched_message(messages)
                last_result = await self._notifier.async_(topic=topic, message=batched, **kwargs)

        if last_result is None:
            from discord_ops_alert.types import NotifyResult

            return NotifyResult(ok=True, attempts=0)

        return last_result

    def _fire(self, *, topic: str) -> None:
        """Called by Timer when window closes — sends the batch."""
        with self._lock:
            entry = self._pending.pop(topic, None)
            self._timers.pop(topic, None)
        if entry:
            messages, kwargs = entry
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
