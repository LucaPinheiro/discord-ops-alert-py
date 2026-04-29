# Embeds and Batching Implementation Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Discord embed support and message batching/debounce to `discord-ops-alert` Python package.

**Architecture:** Two independent features added to the existing package. Embeds extend the `NotifyInput` and webhook transport. Batching is a standalone wrapper (`BatchNotifier`) around the existing `Notifier` — zero changes to core send path.

**Tech Stack:** Python 3.11+, existing `httpx`/`pydantic` deps, `threading.Lock` + `threading.Timer` for batching.

---

## Feature 1: Embeds

### API

```python
from discord_ops_alert import Embed, EmbedField

notify(
    topic="errors",
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
```

`message` and `embed` are mutually exclusive. Passing both raises `DiscordOpsError(VALIDATION_ERROR)`.

### Types

```python
@dataclass
class EmbedField:
    name: str        # max 256 chars
    value: str       # max 1024 chars
    inline: bool = False

@dataclass
class Embed:
    title: str | None = None          # max 256 chars
    description: str | None = None    # max 4096 chars
    color: int | None = None          # 0x000000–0xFFFFFF
    fields: list[EmbedField] = field(default_factory=list)  # max 25
    footer: str | None = None         # max 2048 chars
    thumbnail_url: str | None = None
```

At least one of `title` or `description` must be set.

### Wire format (webhook body)

```json
{
  "embeds": [{
    "title": "...",
    "description": "...",
    "color": 16728132,
    "fields": [{"name": "...", "value": "...", "inline": true}],
    "footer": {"text": "..."},
    "thumbnail": {"url": "..."}
  }]
}
```

### Changes

| File | Change |
|---|---|
| `src/discord_ops_alert/types.py` | Add `EmbedField`, `Embed` dataclasses |
| `src/discord_ops_alert/types.py` | Add `embed: Embed \| None = None` to `NotifyInput` |
| `src/discord_ops_alert/validation.py` | Add `validate_embed()`, extend `validate_notify_input()` |
| `src/discord_ops_alert/transports/webhook.py` | Extend `_build_body()` to emit `embeds` array |
| `src/discord_ops_alert/notifier.py` | Pass `embed` parameter through `__call__` and `async_()` |
| `src/discord_ops_alert/__init__.py` | Export `Embed`, `EmbedField` |
| `tests/test_notifier.py` | Add tests 25–30 |

Bot transport ignores `embed` (Discord Bot API supports embeds too, but out of scope for v1 — bot transport sends `content` only).

---

## Feature 2: Batching

### API

```python
from discord_ops_alert import create_batch_notifier

batch = create_batch_notifier(notify, window_ms=3000)

batch(topic="errors", message="Timeout em /checkout")
batch(topic="errors", message="Timeout em /auth")
# → after 3s window closes, sends ONE message:
# "3 events:\n• Timeout em /checkout\n• Timeout em /auth"

await batch.flush()  # drain all topics immediately
```

### Behavior

- Accumulates messages per topic in a time window (default `window_ms=3000`).
- Window starts on **first message** for that topic. Subsequent messages extend no window — they just join the same batch.
- On window close: if 1 message accumulated → send as-is (identical to `notify`). If N > 1 → send as `"N events:\n• msg1\n• msg2..."` truncated to 2000 chars with `"... and N more"`.
- `flush()` drains all pending topics immediately (cancels timers, sends now).
- Thread-safe via `threading.Lock`.
- `BatchNotifier.__call__` and `BatchNotifier.async_()` have identical signatures to `Notifier`.

### New file

`src/discord_ops_alert/batch.py`:

```python
class BatchNotifier:
    def __init__(self, notifier: Notifier, window_ms: int = 3000) -> None: ...
    def __call__(self, *, topic, message, ...) -> None: ...
    async def async_(self, *, topic, message, ...) -> NotifyResult: ...
    async def flush(self) -> None: ...

def create_batch_notifier(notifier: Notifier, window_ms: int = 3000) -> BatchNotifier: ...
```

### Changes

| File | Change |
|---|---|
| `src/discord_ops_alert/batch.py` | New file — `BatchNotifier`, `create_batch_notifier` |
| `src/discord_ops_alert/__init__.py` | Export `BatchNotifier`, `create_batch_notifier` |
| `tests/test_batch.py` | New file — tests for batching behavior |

---

## Validation rules (embeds)

| Field | Rule |
|---|---|
| `title` | max 256 chars |
| `description` | max 4096 chars |
| `color` | 0 ≤ color ≤ 0xFFFFFF |
| `fields` | max 25 items |
| `EmbedField.name` | non-empty, max 256 chars |
| `EmbedField.value` | non-empty, max 1024 chars |
| `footer` | max 2048 chars |
| both `title` and `description` absent | raises `VALIDATION_ERROR` |
| both `message` and `embed` set | raises `VALIDATION_ERROR` |
| both `message` and `embed` absent | raises `VALIDATION_ERROR` |

---

## Smoke test additions

`smoke_test.py` gets two new test cases:

8. Send embed with title + color + fields → `ok=True`, visual check in Discord
9. Batch 3 messages on same topic → after `flush()`, single batched message arrives

---

## Out of scope

- Embeds in bot transport (bot API supports it, but adds complexity — defer to next release)
- `author`, `image`, `timestamp` embed fields (YAGNI)
- Per-call `window_ms` override on `BatchNotifier`
- `BatchNotifier` with `async_()` returning individual results per batched message
