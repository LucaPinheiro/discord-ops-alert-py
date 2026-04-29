# discord-ops-alert (Python)

Alertas Discord plug-and-play para seu backend Python — fire-and-forget, retry, modos webhook/bot, embeds e batching de mensagens.

[![PyPI](https://img.shields.io/pypi/v/discord-ops-alert)](https://pypi.org/project/discord-ops-alert/)
[![Python](https://img.shields.io/pypi/pyversions/discord-ops-alert)](https://pypi.org/project/discord-ops-alert/)
[![CI](https://github.com/LucaPinheiro/discord-ops-alert-py/actions/workflows/ci.yml/badge.svg)](https://github.com/LucaPinheiro/discord-ops-alert-py/actions/workflows/ci.yml)

---

## Instalação

```bash
pip install discord-ops-alert
# ou
uv add discord-ops-alert
```

---

## Quick start

```python
from discord_ops_alert import create_notifier

notify = create_notifier(
    mode="webhook",           # "webhook" ou "bot"
    url="https://discord.com/api/webhooks/...",  # modo webhook
    # token="Bot SEU_TOKEN",   # modo bot
    # channels={"erros": "1234567890"},           # modo bot
    enabled_in=["production"],
)

# Fire-and-forget (não-bloqueante)
notify(topic="erros", message="Algo deu errado")

# Variante async (awaitable, retorna NotifyResult)
result = await notify.async_(topic="erros", message="Algo deu errado")
print(result.ok, result.attempts, result.message_id)
```

---

## Discord Embeds

Envie mensagens ricas com título, descrição, cor, campos, rodapé e thumbnail.

> **Nota:** Embeds são suportados apenas no **modo webhook**. O modo bot envia apenas texto simples.

```python
from discord_ops_alert import create_notifier, Embed, EmbedField

notify = create_notifier(mode="webhook", url="https://discord.com/api/webhooks/...")

notify(
    topic="erros",
    embed=Embed(
        title="Timeout no banco",
        description="Timeout em /checkout após 5s",
        color=0xFF4444,
        fields=[
            EmbedField("Endpoint", "/checkout", inline=True),
            EmbedField("Duração", "5002ms", inline=True),
        ],
        footer="prod · us-east-1",
        thumbnail_url="https://example.com/icon.png",
    ),
)
```

`message` e `embed` são mutuamente exclusivos — passar ambos lança `DiscordOpsError`.

### Campos do Embed

| Campo | Tipo | Tamanho máximo | Obrigatório |
|---|---|---|---|
| `title` | `str \| None` | 256 chars | pelo menos um de title/description |
| `description` | `str \| None` | 4096 chars | pelo menos um de title/description |
| `color` | `int \| None` | `0x000000`–`0xFFFFFF` | não |
| `fields` | `list[EmbedField]` | máx 25 itens | não |
| `footer` | `str \| None` | 2048 chars | não |
| `thumbnail_url` | `str \| None` | — | não |

### Campos do EmbedField

| Campo | Tipo | Obrigatório |
|---|---|---|
| `name` | `str` | sim (máx 256 chars) |
| `value` | `str` | sim (máx 1024 chars) |
| `inline` | `bool` | não (padrão `False`) |

---

## Batching de mensagens

Acumule mensagens por tópico em uma janela de tempo e envie como uma única mensagem consolidada.

```python
from discord_ops_alert import create_notifier, create_batch_notifier

notify = create_notifier(mode="webhook", url="https://discord.com/api/webhooks/...")
batch = create_batch_notifier(notify, window_ms=3000)

# Estas três chamadas se acumulam na janela de 3 segundos
batch(topic="erros", message="Timeout em /checkout")
batch(topic="erros", message="Timeout em /auth")
batch(topic="erros", message="Timeout em /profile")

# Após 3s a janela fecha e UMA mensagem é enviada:
# "3 events:
# • Timeout em /checkout
# • Timeout em /auth
# • Timeout em /profile"
```

### Flush imediato

```python
# Drena todos os tópicos pendentes imediatamente (ex.: antes de encerrar)
await batch.flush()
```

### Variante async

```python
result = await batch.async_(topic="erros", message="Algo falhou")
# Nota: async_() chama flush() internamente, drenando TODOS os tópicos pendentes
```

### Comportamento do batching

- A janela começa na **primeira mensagem** do tópico. Mensagens posteriores não estendem a janela — apenas entram no mesmo lote.
- No fechamento da janela: se **1 mensagem** acumulada → enviada sem alteração. Se **N > 1** → enviada como `"N events:\n• msg1\n• msg2..."` truncada em 2000 chars com `"... and N more"`.
- Tópicos diferentes são processados de forma independente.
- Thread-safe via `threading.Lock`.

---

## Configuração

### Opções do `create_notifier`

| Opção | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `mode` | `"webhook" \| "bot"` | sim | Modo de transporte |
| `url` | `str` | somente webhook | URL do webhook Discord |
| `token` | `str` | somente bot | Token do bot Discord (`"Bot TOKEN"`) |
| `channels` | `dict[str, str]` | somente bot | `{tópico: channel_id}` |
| `enabled_in` | `list[str]` | não | Só envia nestes ambientes. Padrão: sempre habilitado |
| `on_error` | `callable` | não | Callback de erro `(err: DiscordOpsError, input: NotifyInput) -> None` |
| `retry` | `RetryConfig` | não | Configuração de retry |

### Opções do `create_batch_notifier`

| Opção | Tipo | Padrão | Descrição |
|---|---|---|---|
| `notifier` | `Notifier` | — | O notifier subjacente a envolver |
| `window_ms` | `int` | `3000` | Janela de batching em milissegundos |

---

## Tratamento de erros

```python
from discord_ops_alert import DiscordOpsError

notify = create_notifier(
    ...,
    on_error=lambda err, inp: print(f"Alerta Discord falhou: {err}"),
)
```

Ou capture de forma síncrona:

```python
try:
    result = await notify.async_(topic="erros", message="...")
    if not result.ok:
        print(f"Falhou após {result.attempts} tentativas")
except DiscordOpsError as e:
    print(f"Erro de configuração: {e}")
```

---

## Smoke test

Copie `.env.example` para `.env`, preencha suas credenciais e execute:

```bash
uv run python tests/smoke_test.py
```

---

## Licença

MIT
