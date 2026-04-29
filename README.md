# discord-ops-alert (Python)

Plug-and-play Discord alerts for your Python backend — fire-and-forget, retry, webhook/bot mode, embeds, and message batching.

[![PyPI](https://img.shields.io/pypi/v/discord-ops-alert)](https://pypi.org/project/discord-ops-alert/)
[![Python](https://img.shields.io/pypi/pyversions/discord-ops-alert)](https://pypi.org/project/discord-ops-alert/)
[![CI](https://github.com/LucaPinheiro/discord-ops-alert-py/actions/workflows/ci.yml/badge.svg)](https://github.com/LucaPinheiro/discord-ops-alert-py/actions/workflows/ci.yml)

---

## Install

```bash
pip install discord-ops-alert
# or
uv add discord-ops-alert
```

---

## Quick start

```python
from discord_ops_alert import create_notifier

notify = create_notifier(
    mode="webhook",           # "webhook" or "bot"
    url="https://discord.com/api/webhooks/...",  # webhook mode
    # token="Bot YOUR_TOKEN",  # bot mode
    # channels={"errors": "1234567890"},          # bot mode
    enabled_in=["production"],
)

# Fire-and-forget (non-blocking)
notify(topic="errors", message="Something went wrong")

# Async variant (awaitable, returns NotifyResult)
result = await notify.async_(topic="errors", message="Something went wrong")
print(result.ok, result.attempts, result.message_id)
```

---

## Discord Embeds

Send rich embed messages with title, description, color, fields, footer, and thumbnail.

> **Note:** Embeds are supported in **webhook mode only**. Bot mode sends plain text content.

```python
from discord_ops_alert import create_notifier, Embed, EmbedField

notify = create_notifier(mode="webhook", url="https://discord.com/api/webhooks/...")

notify(
    topic="errors",
    embed=Embed(
        title="DB timeout",
        description="Timeout on /checkout after 5s",
        color=0xFF4444,
        fields=[
            EmbedField("Endpoint", "/checkout", inline=True),
            EmbedField("Duration", "5002ms", inline=True),
        ],
        footer="prod · us-east-1",
        thumbnail_url="https://example.com/icon.png",
    ),
)
```

`message` and `embed` are mutually exclusive — passing both raises `DiscordOpsError`.

### Embed fields

| Field | Type | Max length | Required |
|---|---|---|---|
| `title` | `str \| None` | 256 chars | at least one of title/description |
| `description` | `str \| None` | 4096 chars | at least one of title/description |
| `color` | `int \| None` | `0x000000`–`0xFFFFFF` | no |
| `fields` | `list[EmbedField]` | max 25 items | no |
| `footer` | `str \| None` | 2048 chars | no |
| `thumbnail_url` | `str \| None` | — | no |

### EmbedField fields

| Field | Type | Required |
|---|---|---|
| `name` | `str` | yes (max 256 chars) |
| `value` | `str` | yes (max 1024 chars) |
| `inline` | `bool` | no (default `False`) |

---

## Message Batching

Accumulate messages per topic in a time window and send them as a single batched message.

```python
from discord_ops_alert import create_notifier, create_batch_notifier

notify = create_notifier(mode="webhook", url="https://discord.com/api/webhooks/...")
batch = create_batch_notifier(notify, window_ms=3000)

# These three calls accumulate within the 3-second window
batch(topic="errors", message="Timeout on /checkout")
batch(topic="errors", message="Timeout on /auth")
batch(topic="errors", message="Timeout on /profile")

# After 3s the window closes and ONE message is sent:
# "3 events:
# • Timeout on /checkout
# • Timeout on /auth
# • Timeout on /profile"
```

### Flush immediately

```python
# Drain all pending topics immediately (e.g., before shutdown)
await batch.flush()
```

### Async variant

```python
result = await batch.async_(topic="errors", message="Something failed")
# Note: async_() calls flush() internally, draining ALL pending topics
```

### Batching behavior

- Window starts on the **first message** for a topic. Later messages extend no window — they join the same batch.
- On window close: if **1 message** accumulated → sent as-is. If **N > 1** → sent as `"N events:\n• msg1\n• msg2..."` truncated to 2000 chars with `"... and N more"`.
- Different topics are batched independently.
- Thread-safe via `threading.Lock`.

---

## Configuration

### `create_notifier` options

| Option | Type | Required | Description |
|---|---|---|---|
| `mode` | `"webhook" \| "bot"` | yes | Transport mode |
| `url` | `str` | webhook only | Discord webhook URL |
| `token` | `str` | bot only | Discord bot token (`"Bot TOKEN"`) |
| `channels` | `dict[str, str]` | bot only | `{topic: channel_id}` |
| `enabled_in` | `list[str]` | no | Only send in these environments. Default: always enabled |
| `on_error` | `callable` | no | Error callback `(err: DiscordOpsError, input: NotifyInput) -> None` |
| `retry` | `RetryConfig` | no | Retry configuration |

### `create_batch_notifier` options

| Option | Type | Default | Description |
|---|---|---|---|
| `notifier` | `Notifier` | — | The underlying notifier to wrap |
| `window_ms` | `int` | `3000` | Batch window in milliseconds |

---

## Error handling

```python
from discord_ops_alert import DiscordOpsError

notify = create_notifier(
    ...,
    on_error=lambda err, inp: print(f"Discord alert failed: {err}"),
)
```

Or catch synchronously:

```python
try:
    result = await notify.async_(topic="errors", message="...")
    if not result.ok:
        print(f"Failed after {result.attempts} attempts")
except DiscordOpsError as e:
    print(f"Config error: {e}")
```

---

## Smoke test

Copy `.env.example` to `.env`, fill in your credentials, then run:

```bash
uv run python tests/smoke_test.py
```

---

## License

MIT
