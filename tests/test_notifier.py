"""Unit tests for discord-ops-alert notifier.

Uses respx to mock httpx HTTP calls. asyncio_mode = "auto" (see pyproject.toml).
"""
from __future__ import annotations

import threading

import httpx
import pytest
import respx

from discord_ops_alert import DiscordOpsError, ErrorCode, create_notifier

# ---------------------------------------------------------------------------
# Test helpers / fixtures
# ---------------------------------------------------------------------------

# A valid Discord bot token that matches the regex:
# ^[A-Za-z0-9._-]{24,}\.[A-Za-z0-9._-]{6,}\.[A-Za-z0-9._-]{27,}$
VALID_TOKEN = "AABBCCDDEE1122334455AABB.AABBCC.AABBCCDDEE1122334455AABB1122334455"
VALID_CHANNEL_ID = "123456789012345678"  # 18 digits — valid snowflake

VALID_WEBHOOK_URL = "https://discord.com/api/webhooks/111111111111111111/aaaa-bbbb-cccc-dddd"

BOT_CHANNEL_URL = f"https://discord.com/api/v10/channels/{VALID_CHANNEL_ID}/messages"
WEBHOOK_URL_WITH_WAIT = f"{VALID_WEBHOOK_URL}?wait=true"

DISCORD_OK_RESPONSE = {"id": "999888777666555444", "content": "test"}


# ---------------------------------------------------------------------------
# 1. Init: invalid webhook URL raises DiscordOpsError(INVALID_CONFIG)
# ---------------------------------------------------------------------------

def test_invalid_webhook_url_raises():
    with pytest.raises(DiscordOpsError) as exc_info:
        create_notifier(
            mode="webhook",
            webhooks={"login": "https://not-discord.com/bad-url"},
        )
    assert exc_info.value.code == ErrorCode.CONFIG_ERROR


# ---------------------------------------------------------------------------
# 2. Init: valid webhook URL creates notifier without raising
# ---------------------------------------------------------------------------

def test_valid_webhook_url_ok():
    notify = create_notifier(
        mode="webhook",
        webhooks={"login": VALID_WEBHOOK_URL},
    )
    assert notify is not None


# ---------------------------------------------------------------------------
# 3. Init: short bot token raises DiscordOpsError(INVALID_CONFIG)
# ---------------------------------------------------------------------------

def test_invalid_bot_token_raises():
    with pytest.raises(DiscordOpsError) as exc_info:
        create_notifier(
            mode="bot",
            token="short-token",
            channels={"login": VALID_CHANNEL_ID},
        )
    assert exc_info.value.code == ErrorCode.CONFIG_ERROR


# ---------------------------------------------------------------------------
# 4. Init: invalid channel_id raises DiscordOpsError(INVALID_CONFIG)
# ---------------------------------------------------------------------------

def test_invalid_channel_id_raises():
    with pytest.raises(DiscordOpsError) as exc_info:
        create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": "not-a-snowflake"},
        )
    assert exc_info.value.code == ErrorCode.CONFIG_ERROR


# ---------------------------------------------------------------------------
# 5. Fire-and-forget returns None immediately
# ---------------------------------------------------------------------------

@respx.mock
def test_fire_and_forget_returns_none():
    respx.post(BOT_CHANNEL_URL).mock(
        return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE)
    )
    notify = create_notifier(
        mode="bot",
        token=VALID_TOKEN,
        channels={"login": VALID_CHANNEL_ID},
    )
    result = notify(topic="login", message="hello")
    assert result is None


# ---------------------------------------------------------------------------
# 6. Async variant returns NotifyResult(ok=True) on 200 response
# ---------------------------------------------------------------------------

async def test_async_returns_ok_true():
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(
            return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE)
        )
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
        )
        result = await notify.async_(topic="login", message="hello")
        assert result.ok is True
        assert result.skipped is False


# ---------------------------------------------------------------------------
# 7. Async variant returns message_id from Discord response
# ---------------------------------------------------------------------------

async def test_async_returns_message_id():
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(
            return_value=httpx.Response(200, json={"id": "999888777666555444", "content": "test"})
        )
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
        )
        result = await notify.async_(topic="login", message="hello")
        assert result.message_id == "999888777666555444"


# ---------------------------------------------------------------------------
# 8. Retry on 429: verify attempts > 1 in result (fast retry config)
# ---------------------------------------------------------------------------

async def test_retry_on_429_attempts_greater_than_one():
    from discord_ops_alert.types import RetryConfig

    async with respx.mock:
        # First call returns 429, second returns 200
        respx.post(BOT_CHANNEL_URL).mock(
            side_effect=[
                httpx.Response(429, json={"message": "rate limited", "retry_after": 0}),
                httpx.Response(200, json=DISCORD_OK_RESPONSE),
            ]
        )
        fast_retry = RetryConfig(max_attempts=3, base_delay_ms=0, max_delay_ms=0)
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
            retry=fast_retry,
        )
        result = await notify.async_(topic="login", message="hello")
        assert result.ok is True
        assert result.attempts > 1


# ---------------------------------------------------------------------------
# 9. enabled_in filtering: STAGE not in enabled_in → skipped=True
# ---------------------------------------------------------------------------

async def test_enabled_in_skips_when_stage_not_matched(monkeypatch):
    monkeypatch.setenv("STAGE", "development")
    notify = create_notifier(
        mode="bot",
        token=VALID_TOKEN,
        channels={"login": VALID_CHANNEL_ID},
        enabled_in=["production"],
    )
    result = await notify.async_(topic="login", message="hello")
    assert result.ok is True
    assert result.skipped is True


# ---------------------------------------------------------------------------
# 10. enabled_in filtering: STAGE in enabled_in → sends normally
# ---------------------------------------------------------------------------

async def test_enabled_in_sends_when_stage_matches(monkeypatch):
    monkeypatch.setenv("STAGE", "production")
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(
            return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE)
        )
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
            enabled_in=["production"],
        )
        result = await notify.async_(topic="login", message="hello")
        assert result.ok is True
        assert result.skipped is False


# ---------------------------------------------------------------------------
# 11. on_error called when fire-and-forget fails
# ---------------------------------------------------------------------------

def test_on_error_called_on_fire_and_forget_failure():
    from discord_ops_alert.types import RetryConfig

    error_seen = threading.Event()
    captured: list = []

    def on_error(err, inp):
        captured.append(err)
        error_seen.set()

    with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(
            side_effect=[httpx.Response(500, json={"message": "server error"})]
        )
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
            retry=RetryConfig(max_attempts=1, base_delay_ms=0, max_delay_ms=0),
            on_error=on_error,
        )
        notify(topic="login", message="test")
        assert error_seen.wait(timeout=5.0), "on_error was not called within timeout"

    assert len(captured) == 1
    assert isinstance(captured[0], DiscordOpsError)


# ---------------------------------------------------------------------------
# 12. on_retry called on each retry attempt
# ---------------------------------------------------------------------------

async def test_on_retry_called_on_retry():
    from discord_ops_alert.types import RetryConfig

    retry_events = []

    def on_retry(evt):
        retry_events.append(evt)

    async with respx.mock:
        # First call 429, second 200
        respx.post(BOT_CHANNEL_URL).mock(
            side_effect=[
                httpx.Response(429, json={"message": "rate limited"}),
                httpx.Response(200, json=DISCORD_OK_RESPONSE),
            ]
        )
        fast_retry = RetryConfig(max_attempts=3, base_delay_ms=0, max_delay_ms=0)
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
            retry=fast_retry,
            on_retry=on_retry,
        )
        result = await notify.async_(topic="login", message="hello")
        assert result.ok is True
        assert len(retry_events) >= 1
        assert retry_events[0].attempt == 1


# ---------------------------------------------------------------------------
# 13. Bot transport: sends Authorization: Bot header
# ---------------------------------------------------------------------------

async def test_bot_transport_sends_authorization_header():
    async with respx.mock:
        route = respx.post(BOT_CHANNEL_URL).mock(
            return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE)
        )
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
        )
        await notify.async_(topic="login", message="hello")

        assert route.called
        sent_request = route.calls.last.request
        assert sent_request.headers["Authorization"] == f"Bot {VALID_TOKEN}"


# ---------------------------------------------------------------------------
# 14. Webhook transport: appends ?wait=true to URL
# ---------------------------------------------------------------------------

async def test_webhook_transport_appends_wait_true():
    async with respx.mock:
        route = respx.post(WEBHOOK_URL_WITH_WAIT).mock(
            return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE)
        )
        notify = create_notifier(
            mode="webhook",
            webhooks={"login": VALID_WEBHOOK_URL},
        )
        result = await notify.async_(topic="login", message="hello")

        assert route.called, "Expected request to webhook URL with ?wait=true"
        assert result.ok is True


# ---------------------------------------------------------------------------
# 15. HTTP layer: extracts Retry-After header into RetryableError
# ---------------------------------------------------------------------------

async def test_retry_after_header_is_extracted():
    from discord_ops_alert.errors import RetryableError
    from discord_ops_alert.http import post_async

    async with respx.mock:
        respx.post("https://discord.com/api/webhooks/test/send").mock(
            return_value=httpx.Response(
                429,
                json={"message": "rate limited"},
                headers={"Retry-After": "2"},
            )
        )
        with pytest.raises(RetryableError) as exc_info:
            await post_async(
                "https://discord.com/api/webhooks/test/send",
                {},
                {"content": "hi"},
            )
        assert exc_info.value.retry_after_ms == 2000


# ---------------------------------------------------------------------------
# 16. Retry layer: respects retry_after_ms from RetryableError
# ---------------------------------------------------------------------------

async def test_retry_respects_retry_after_ms():
    from discord_ops_alert.types import RetryConfig

    retry_events = []

    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(
            side_effect=[
                httpx.Response(429, json={"retry_after": 0.0}, headers={"Retry-After": "0"}),
                httpx.Response(200, json=DISCORD_OK_RESPONSE),
            ]
        )
        fast_retry = RetryConfig(max_attempts=2, base_delay_ms=0, max_delay_ms=0)
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
            retry=fast_retry,
            on_retry=lambda e: retry_events.append(e),
        )
        result = await notify.async_(topic="login", message="hello")
        assert result.ok is True
        assert len(retry_events) == 1
        assert retry_events[0].delay_ms == 0


# ---------------------------------------------------------------------------
# 17. Retry exhausted on 429 → NotifyResult(ok=False) with rate_limited code
# ---------------------------------------------------------------------------

async def test_retry_exhausted_429_returns_rate_limited():
    from discord_ops_alert.types import RetryConfig

    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(
            return_value=httpx.Response(429, json={"message": "rate limited"})
        )
        fast_retry = RetryConfig(max_attempts=2, base_delay_ms=0, max_delay_ms=0)
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
            retry=fast_retry,
        )
        result = await notify.async_(topic="login", message="hello")
        assert result.ok is False
        assert "rate_limited" in (result.error or "")


# ---------------------------------------------------------------------------
# 18. Retry exhausted on 500 → NotifyResult(ok=False) with discord_api_error
# ---------------------------------------------------------------------------

async def test_retry_exhausted_500_returns_discord_error():
    from discord_ops_alert.types import RetryConfig

    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(
            return_value=httpx.Response(500, json={"message": "server error"})
        )
        fast_retry = RetryConfig(max_attempts=2, base_delay_ms=0, max_delay_ms=0)
        notify = create_notifier(
            mode="bot",
            token=VALID_TOKEN,
            channels={"login": VALID_CHANNEL_ID},
            retry=fast_retry,
        )
        result = await notify.async_(topic="login", message="hello")
        assert result.ok is False
        assert "discord_api_error" in (result.error or "")


# ---------------------------------------------------------------------------
# 19. Validation: message > 2000 chars → NotifyResult(ok=False, validation_error)
# ---------------------------------------------------------------------------

async def test_async_message_too_long_returns_validation_error():
    notify = create_notifier(
        mode="webhook",
        webhooks={"login": VALID_WEBHOOK_URL},
    )
    result = await notify.async_(topic="login", message="x" * 2001)
    assert result.ok is False
    assert "validation_error" in (result.error or "")


# ---------------------------------------------------------------------------
# 20. Validation: empty message → NotifyResult(ok=False, validation_error)
# ---------------------------------------------------------------------------

async def test_async_empty_message_returns_validation_error():
    notify = create_notifier(
        mode="webhook",
        webhooks={"login": VALID_WEBHOOK_URL},
    )
    result = await notify.async_(topic="login", message="")
    assert result.ok is False
    assert "validation_error" in (result.error or "")


# ---------------------------------------------------------------------------
# 21. Validation: username > 80 chars → NotifyResult(ok=False, validation_error)
# ---------------------------------------------------------------------------

async def test_async_username_too_long_returns_validation_error():
    notify = create_notifier(
        mode="webhook",
        webhooks={"login": VALID_WEBHOOK_URL},
    )
    result = await notify.async_(topic="login", message="hi", username="a" * 81)
    assert result.ok is False
    assert "validation_error" in (result.error or "")


# ---------------------------------------------------------------------------
# 22. defaultUsername is sent in webhook body when no per-call username given
# ---------------------------------------------------------------------------

async def test_webhook_default_username_sent_in_body():
    import json as _json

    async with respx.mock:
        route = respx.post(WEBHOOK_URL_WITH_WAIT).mock(
            return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE)
        )
        notify = create_notifier(
            mode="webhook",
            webhooks={"login": VALID_WEBHOOK_URL},
            default_username="AlertBot",
        )
        await notify.async_(topic="login", message="hello")
        sent_body = _json.loads(route.calls.last.request.content)
        assert sent_body.get("username") == "AlertBot"


# ---------------------------------------------------------------------------
# 23. Per-call username overrides defaultUsername
# ---------------------------------------------------------------------------

async def test_webhook_per_call_username_overrides_default():
    import json as _json

    async with respx.mock:
        route = respx.post(WEBHOOK_URL_WITH_WAIT).mock(
            return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE)
        )
        notify = create_notifier(
            mode="webhook",
            webhooks={"login": VALID_WEBHOOK_URL},
            default_username="AlertBot",
        )
        await notify.async_(topic="login", message="hello", username="Override")
        sent_body = _json.loads(route.calls.last.request.content)
        assert sent_body.get("username") == "Override"


# ---------------------------------------------------------------------------
# 24. default_logger and silent_logger are exported and satisfy Logger protocol
# ---------------------------------------------------------------------------

def test_default_logger_and_silent_logger_exported():
    from discord_ops_alert import default_logger, silent_logger
    from discord_ops_alert.types import Logger

    assert isinstance(default_logger, Logger)
    assert isinstance(silent_logger, Logger)
    silent_logger.debug("test %s", "arg")
    silent_logger.info("test")
    silent_logger.warning("test")
    silent_logger.error("test")
