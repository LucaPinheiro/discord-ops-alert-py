"""Unit tests for discord-ops-alert. asyncio_mode = auto (see pyproject.toml)."""
from __future__ import annotations
import threading
import httpx
import pytest
import respx
from discord_ops_alert import DiscordOpsError, ErrorCode, create_notifier
from discord_ops_alert.types import NotifyResult

VALID_TOKEN = "AABBCCDDEE1122334455AABB.AABBCC.AABBCCDDEE1122334455AABB1122334455"
VALID_CHANNEL_ID = "123456789012345678"
VALID_WEBHOOK_URL = "https://discord.com/api/webhooks/111111111111111111/aaaa-bbbb-cccc-dddd"
BOT_CHANNEL_URL = f"https://discord.com/api/v10/channels/{VALID_CHANNEL_ID}/messages"
WEBHOOK_URL_WITH_WAIT = f"{VALID_WEBHOOK_URL}?wait=true"
DISCORD_OK_RESPONSE = {"id": "999888777666555444", "content": "test"}


def test_invalid_webhook_url_raises():
    with pytest.raises(DiscordOpsError) as exc_info:
        create_notifier(mode="webhook", webhooks={"login": "https://not-discord.com/bad-url"})
    assert exc_info.value.code == ErrorCode.CONFIG_ERROR


def test_valid_webhook_url_ok():
    assert create_notifier(mode="webhook", webhooks={"login": VALID_WEBHOOK_URL}) is not None


def test_invalid_bot_token_raises():
    with pytest.raises(DiscordOpsError) as exc_info:
        create_notifier(mode="bot", token="short-token", channels={"login": VALID_CHANNEL_ID})
    assert exc_info.value.code == ErrorCode.CONFIG_ERROR


def test_invalid_channel_id_raises():
    with pytest.raises(DiscordOpsError) as exc_info:
        create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": "not-a-snowflake"})
    assert exc_info.value.code == ErrorCode.CONFIG_ERROR


@respx.mock
def test_fire_and_forget_returns_none():
    respx.post(BOT_CHANNEL_URL).mock(return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE))
    notify = create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID})
    assert notify(topic="login", message="hello") is None


async def test_async_returns_ok_true():
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE))
        notify = create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID})
        result = await notify.async_(topic="login", message="hello")
        assert result.ok is True and result.skipped is False


async def test_async_returns_message_id():
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(return_value=httpx.Response(200, json={"id": "999888777666555444", "content": "test"}))
        notify = create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID})
        result = await notify.async_(topic="login", message="hello")
        assert result.message_id == "999888777666555444"


async def test_retry_on_429_attempts_greater_than_one():
    from discord_ops_alert.types import RetryConfig
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(side_effect=[
            httpx.Response(429, json={"message": "rate limited", "retry_after": 0}),
            httpx.Response(200, json=DISCORD_OK_RESPONSE),
        ])
        result = await create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}, retry=RetryConfig(max_attempts=3, base_delay_ms=0, max_delay_ms=0)).async_(topic="login", message="hello")
        assert result.ok is True and result.attempts > 1


async def test_enabled_in_skips_when_stage_not_matched(monkeypatch):
    monkeypatch.setenv("STAGE", "development")
    result = await create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}, enabled_in=["production"]).async_(topic="login", message="hello")
    assert result.ok is True and result.skipped is True


async def test_enabled_in_sends_when_stage_matches(monkeypatch):
    monkeypatch.setenv("STAGE", "production")
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE))
        result = await create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}, enabled_in=["production"]).async_(topic="login", message="hello")
        assert result.ok is True and result.skipped is False


def test_on_error_called_on_fire_and_forget_failure():
    from discord_ops_alert.types import RetryConfig
    error_seen = threading.Event()
    captured: list = []
    def on_error(err, inp):
        captured.append(err)
        error_seen.set()
    with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(side_effect=[httpx.Response(500, json={"message": "server error"})])
        notify = create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}, retry=RetryConfig(max_attempts=1, base_delay_ms=0, max_delay_ms=0), on_error=on_error)
        notify(topic="login", message="test")
        assert error_seen.wait(timeout=5.0)
    assert len(captured) == 1 and isinstance(captured[0], DiscordOpsError)


async def test_on_retry_called_on_retry():
    from discord_ops_alert.types import RetryConfig
    retry_events = []
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(side_effect=[
            httpx.Response(429, json={"message": "rate limited"}),
            httpx.Response(200, json=DISCORD_OK_RESPONSE),
        ])
        result = await create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}, retry=RetryConfig(max_attempts=3, base_delay_ms=0, max_delay_ms=0), on_retry=lambda e: retry_events.append(e)).async_(topic="login", message="hello")
        assert result.ok is True and len(retry_events) >= 1 and retry_events[0].attempt == 1


async def test_bot_transport_sends_authorization_header():
    async with respx.mock:
        route = respx.post(BOT_CHANNEL_URL).mock(return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE))
        await create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}).async_(topic="login", message="hello")
        assert route.calls.last.request.headers["Authorization"] == f"Bot {VALID_TOKEN}"


async def test_webhook_transport_appends_wait_true():
    async with respx.mock:
        route = respx.post(WEBHOOK_URL_WITH_WAIT).mock(return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE))
        result = await create_notifier(mode="webhook", webhooks={"login": VALID_WEBHOOK_URL}).async_(topic="login", message="hello")
        assert route.called and result.ok is True


async def test_retry_after_header_is_extracted():
    from discord_ops_alert.errors import RetryableError
    from discord_ops_alert.http import post_async
    async with respx.mock:
        respx.post("https://discord.com/api/webhooks/test/send").mock(return_value=httpx.Response(429, json={"message": "rate limited"}, headers={"Retry-After": "2"}))
        with pytest.raises(RetryableError) as exc_info:
            await post_async("https://discord.com/api/webhooks/test/send", {}, {"content": "hi"})
        assert exc_info.value.retry_after_ms == 2000


async def test_retry_respects_retry_after_ms():
    from discord_ops_alert.types import RetryConfig
    retry_events = []
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(side_effect=[
            httpx.Response(429, json={"retry_after": 0.0}, headers={"Retry-After": "0"}),
            httpx.Response(200, json=DISCORD_OK_RESPONSE),
        ])
        result = await create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}, retry=RetryConfig(max_attempts=2, base_delay_ms=0, max_delay_ms=0), on_retry=lambda e: retry_events.append(e)).async_(topic="login", message="hello")
        assert result.ok is True and len(retry_events) == 1 and retry_events[0].delay_ms == 0


async def test_retry_exhausted_429_returns_rate_limited():
    from discord_ops_alert.types import RetryConfig
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(return_value=httpx.Response(429, json={"message": "rate limited"}))
        result = await create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}, retry=RetryConfig(max_attempts=2, base_delay_ms=0, max_delay_ms=0)).async_(topic="login", message="hello")
        assert result.ok is False and "rate_limited" in (result.error or "")


async def test_retry_exhausted_500_returns_discord_error():
    from discord_ops_alert.types import RetryConfig
    async with respx.mock:
        respx.post(BOT_CHANNEL_URL).mock(return_value=httpx.Response(500, json={"message": "server error"}))
        result = await create_notifier(mode="bot", token=VALID_TOKEN, channels={"login": VALID_CHANNEL_ID}, retry=RetryConfig(max_attempts=2, base_delay_ms=0, max_delay_ms=0)).async_(topic="login", message="hello")
        assert result.ok is False and "discord_api_error" in (result.error or "")


async def test_async_message_too_long_returns_validation_error():
    result = await create_notifier(mode="webhook", webhooks={"login": VALID_WEBHOOK_URL}).async_(topic="login", message="x" * 2001)
    assert result.ok is False and "validation_error" in (result.error or "")


async def test_async_empty_message_returns_validation_error():
    result = await create_notifier(mode="webhook", webhooks={"login": VALID_WEBHOOK_URL}).async_(topic="login", message="")
    assert result.ok is False and "validation_error" in (result.error or "")


async def test_async_username_too_long_returns_validation_error():
    result = await create_notifier(mode="webhook", webhooks={"login": VALID_WEBHOOK_URL}).async_(topic="login", message="hi", username="a" * 81)
    assert result.ok is False and "validation_error" in (result.error or "")


async def test_webhook_default_username_sent_in_body():
    import json as _json
    async with respx.mock:
        route = respx.post(WEBHOOK_URL_WITH_WAIT).mock(return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE))
        await create_notifier(mode="webhook", webhooks={"login": VALID_WEBHOOK_URL}, default_username="AlertBot").async_(topic="login", message="hello")
        assert _json.loads(route.calls.last.request.content).get("username") == "AlertBot"


async def test_webhook_per_call_username_overrides_default():
    import json as _json
    async with respx.mock:
        route = respx.post(WEBHOOK_URL_WITH_WAIT).mock(return_value=httpx.Response(200, json=DISCORD_OK_RESPONSE))
        await create_notifier(mode="webhook", webhooks={"login": VALID_WEBHOOK_URL}, default_username="AlertBot").async_(topic="login", message="hello", username="Override")
        assert _json.loads(route.calls.last.request.content).get("username") == "Override"


def test_default_logger_and_silent_logger_exported():
    from discord_ops_alert import default_logger, silent_logger
    from discord_ops_alert.types import Logger
    assert isinstance(default_logger, Logger) and isinstance(silent_logger, Logger)
    silent_logger.debug("test %s", "arg")
    silent_logger.info("test")
    silent_logger.warning("test")
    silent_logger.error("test")
