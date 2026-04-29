"""Tests for BatchNotifier and _build_batched_message."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from discord_ops_alert.batch import BatchNotifier, _build_batched_message, create_batch_notifier
from discord_ops_alert.types import NotifyResult


@pytest.fixture
def mock_notifier():
    n = MagicMock()
    n.async_ = AsyncMock(return_value=NotifyResult(ok=True, attempts=1, message_id="123"))
    return n


@pytest.mark.asyncio
async def test_batch_single_message_sent_as_is(mock_notifier):
    batch = create_batch_notifier(mock_notifier)
    batch(topic="alerts", message="Hello")
    await batch.flush()
    mock_notifier.async_.assert_called_once()
    call_kwargs = mock_notifier.async_.call_args.kwargs
    assert call_kwargs["message"] == "Hello"


@pytest.mark.asyncio
async def test_batch_multiple_messages_formatted(mock_notifier):
    batch = create_batch_notifier(mock_notifier)
    batch(topic="alerts", message="Error A")
    batch(topic="alerts", message="Error B")
    batch(topic="alerts", message="Error C")
    await batch.flush()
    mock_notifier.async_.assert_called_once()
    msg = mock_notifier.async_.call_args.kwargs["message"]
    assert msg.startswith("3 events:\n")
    assert "• Error A" in msg
    assert "• Error B" in msg
    assert "• Error C" in msg


@pytest.mark.asyncio
async def test_batch_different_topics_independent(mock_notifier):
    batch = create_batch_notifier(mock_notifier)
    batch(topic="errors", message="E1")
    batch(topic="info", message="I1")
    await batch.flush()
    assert mock_notifier.async_.call_count == 2
    topics = {c.kwargs["topic"] for c in mock_notifier.async_.call_args_list}
    assert topics == {"errors", "info"}


@pytest.mark.asyncio
async def test_batch_flush_empty(mock_notifier):
    batch = create_batch_notifier(mock_notifier)
    result = await batch.flush()
    assert result.ok is True
    mock_notifier.async_.assert_not_called()


def test_build_batched_message_truncation():
    # 200 messages of 20 chars each → would exceed 2000 chars → truncated
    messages = [f"{'x' * 20} msg {i}" for i in range(200)]
    result = _build_batched_message(messages)
    assert len(result) <= 2000
    assert "... and" in result


def test_build_batched_message_single():
    result = _build_batched_message(["just one"])
    assert result == "just one"
