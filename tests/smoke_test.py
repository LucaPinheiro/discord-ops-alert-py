#!/usr/bin/env python3
"""
Smoke test — sends a real message to Discord.

Requirements:
    Copy .env.example to .env and fill in real values:
        DISCORD_BOT_TOKEN=<real token>
        CHANNEL_MAP_JSON={"login": "<real_channel_id>"}
        STAGE=production  (or whatever is in enabled_in)

Run with:
    uv run python tests/smoke_test.py
"""
import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

from discord_ops_alert import DiscordOpsError, Embed, EmbedField, create_batch_notifier, create_notifier  # noqa: E402


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    channel_map = json.loads(os.environ.get("CHANNEL_MAP_JSON", "{}"))
    stage = os.environ.get("STAGE", "dev")

    if not token or not channel_map:
        print("WARNING: DISCORD_BOT_TOKEN and CHANNEL_MAP_JSON must be set in .env")
        print("   Copy .env.example to .env and fill in real values.")
        return

    try:
        notify = create_notifier(
            mode="bot",
            token=token,
            channels=channel_map,
            enabled_in=[stage],
            on_error=lambda err, inp: print(f"ERROR: {err}"),
        )
    except DiscordOpsError as e:
        print(f"⚠️  Invalid config: {e}")
        print("   Check DISCORD_BOT_TOKEN format and CHANNEL_MAP_JSON channel IDs (must be 17-20 digits)")
        return

    first_topic = list(channel_map.keys())[0]

    # Test 1: fire-and-forget
    print("Test 1: fire-and-forget...")
    notify(topic=first_topic, message="[discord-ops-alert-py] smoke test — fire-and-forget")
    time.sleep(2)
    print("  sent (check Discord)")

    # Test 2: async variant
    print("Test 2: async variant...")

    async def test_async():
        result = await notify.async_(
            topic=first_topic,
            message="[discord-ops-alert-py] smoke test — async",
        )
        print(f"  result: ok={result.ok} attempts={result.attempts} message_id={result.message_id}")
        return result

    result = asyncio.run(test_async())
    assert result.ok, f"async test failed: {result}"
    print("  passed")

    # Test 8: embed with title + color + fields (webhook only — bot ignores embed)
    print("Test 8: embed via webhook...")
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if not webhook_url:
        print("  SKIPPED: set WEBHOOK_URL in .env to run embed smoke test")
    else:
        try:
            webhook_notify = create_notifier(
                mode="webhook",
                url=webhook_url,
                enabled_in=[stage],
                on_error=lambda err, inp: print(f"ERROR: {err}"),
            )
        except DiscordOpsError as e:
            print(f"  SKIPPED: webhook config error: {e}")
            webhook_notify = None

        if webhook_notify:

            async def test_embed():
                result = await webhook_notify.async_(
                    topic="default",
                    embed=Embed(
                        title="DB timeout",
                        description="Timeout em /checkout após 5s",
                        color=0xFF4444,
                        fields=[
                            EmbedField("Endpoint", "/checkout", inline=True),
                            EmbedField("Duração", "5002ms", inline=True),
                        ],
                        footer="prod · us-east-1",
                    ),
                )
                print(f"  result: ok={result.ok} attempts={result.attempts}")
                return result

            result = asyncio.run(test_embed())
            assert result.ok, f"embed test failed: {result}"
            print("  passed (check Discord for embed visual)")

    # Test 9: batch 3 messages → single batched message after flush
    print("Test 9: batch 3 messages + flush...")

    async def test_batch():
        batch = create_batch_notifier(notify, window_ms=5000)
        batch(topic=first_topic, message="[discord-ops-alert-py] batch event 1")
        batch(topic=first_topic, message="[discord-ops-alert-py] batch event 2")
        batch(topic=first_topic, message="[discord-ops-alert-py] batch event 3")
        result = await batch.flush()
        print(f"  result: ok={result.ok} attempts={result.attempts}")
        return result

    result = asyncio.run(test_batch())
    assert result.ok, f"batch test failed: {result}"
    print("  passed (check Discord — should see ONE message with '3 events:')")

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
