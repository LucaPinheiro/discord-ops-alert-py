#!/usr/bin/env python3
"""Smoke test for discord-ops-alert Python package.

Mirrors the structure of discord-ops-smoke-test/test.ts from the npm package.

Run:
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... uv run python smoke_test.py
"""
from __future__ import annotations

import asyncio
import datetime
import os
import sys
import time

from discord_ops_alert import DiscordOpsError, ErrorCode, create_notifier
from discord_ops_alert.types import RetryEvent

webhook = os.environ.get("DISCORD_WEBHOOK_URL")
if not webhook:
    print("Set DISCORD_WEBHOOK_URL first")
    sys.exit(1)

passed = 0
failed = 0


def check(label: str, ok: bool, detail: object = None) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}", detail or "")


print("Smoke test — discord-ops-alert Python package\n")

print("1) Rejects legacy discordapp.com webhooks")
try:
    create_notifier(mode="webhook", webhooks={"t": "https://discordapp.com/api/webhooks/123/abc"})
    check("rejects discordapp.com", False, "expected DiscordOpsError")
except DiscordOpsError as e:
    check("rejects discordapp.com", e.code == ErrorCode.CONFIG_ERROR, e)

print("2) Rejects short bot tokens")
try:
    create_notifier(mode="bot", token="short-token", channels={"t": "12345678901234567"})
    check("rejects short bot token", False, "expected DiscordOpsError")
except DiscordOpsError as e:
    check("rejects short bot token", e.code == ErrorCode.CONFIG_ERROR, e)

print("3) Production webhook send actually reaches Discord")
retry_events: list[RetryEvent] = []
notify = create_notifier(
    mode="webhook",
    webhooks={"smoke": webhook},
    on_retry=lambda e: retry_events.append(e),
)
result = asyncio.run(
    notify.async_(
        topic="smoke",
        message=f"discord-ops-alert Python smoke test @ {datetime.datetime.utcnow().isoformat()}",
    )
)
check("send returned ok=True", result.ok is True, result)
check("attempts >= 1", result.attempts >= 1, result)
print(f"   retry events: {len(retry_events)} (0 expected)")

print("4) Message > 2000 chars -> validation_error result")
long_result = asyncio.run(notify.async_(topic="smoke", message="x" * 2001))
check("long message -> ok=False", long_result.ok is False, long_result)
check("error contains validation_error", "validation_error" in (long_result.error or ""), long_result)

print("5) on_error fires on fire-and-forget with unknown topic")
error_calls = 0
last_error_code = ""


def _on_err(err: DiscordOpsError, _inp: object) -> None:
    global error_calls, last_error_code
    error_calls += 1
    last_error_code = str(err.code)


fo_notify = create_notifier(mode="webhook", webhooks={"smoke": webhook}, on_error=_on_err)
fo_notify(topic="does-not-exist", message="x")  # type: ignore[arg-type]
time.sleep(0.5)
check("on_error fired", error_calls == 1, {"error_calls": error_calls})
check("on_error received unknown_topic code", last_error_code == "unknown_topic", {"last_error_code": last_error_code})

print("6) Second real send via async_()")
result2 = asyncio.run(
    notify.async_(topic="smoke", message="Second Python smoke test — validation, hooks & defaultUsername all wired")
)
check("second send ok", result2.ok is True, result2)

print("7) defaultUsername set at init (visual check in Discord)")
notify_with_username = create_notifier(
    mode="webhook", webhooks={"smoke": webhook}, default_username="PythonAlertBot"
)
result3 = asyncio.run(
    notify_with_username.async_(topic="smoke", message="This message should appear from 'PythonAlertBot' username")
)
check("send with defaultUsername ok", result3.ok is True, result3)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
