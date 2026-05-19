# Claude Code Multi-Provider Router

Make Claude Code route Opus/Sonnet/Haiku/SubAgent requests to GPT, DeepSeek, MiMo, and Gemini through an Anthropic-compatible local proxy. Includes a Codex skill, read-only diagnostics, cooldown-aware fallback, and secret-masked auditing.

A Codex skill for configuring, auditing, and troubleshooting a Claude Code
multi-provider setup with a local tier router:

- **Opus / primary** -> GPT-5.5 through `raine/claude-code-proxy`
- **Sonnet** -> DeepSeek official Claude Code Anthropic API
- **Haiku** -> MiMo Token Plan
- **SubAgent / unmatched models** -> Gemini via Vertex ADC proxy

The bundled diagnostic script is read-only by default. It masks secrets and does
not switch providers.

## Current Target Shape

```text
Claude Code
  -> local router              http://127.0.0.1:8084
     -> GPT-5.5 / Opus         http://127.0.0.1:18765  raine/claude-code-proxy
     -> DeepSeek / Sonnet      https://api.deepseek.com/anthropic
     -> MiMo / Haiku           https://token-plan-sgp.xiaomimimo.com/anthropic
     -> Gemini / SubAgent      http://127.0.0.1:8083
```

## Router Features

The router (`router.py`) implements intelligent multi-provider routing inspired by [LiteLLM](https://github.com/BerriAI/litellm):

| Feature | Description |
|---------|-------------|
| **Keyword routing** | Model name → backend: `opus`→GPT, `sonnet`→DeepSeek, `haiku`→MiMo, `subagent`→Gemini |
| **Fallback chains** | If primary backend fails, automatically tries next backend in chain |
| **Error classification** | `retryable` (cooldown+fallback) vs `fallback` (fallback only, no cooldown) |
| **Configurable retryable statuses** | Per-backend extra retryable status codes (e.g. GPT returns 400 for "no quota") |
| **Cooldown** | Failed backends are cooled down for N seconds (configurable, respects `Retry-After` header) |
| **Stats tracking** | Per-backend success/failure counts visible in health endpoint |
| **Streaming passthrough** | Streaming responses pass through directly (see streaming limitations below) |

### Streaming Limitations

Streaming mode (`stream: true`) supports fallback **before** the response body is streamed. The router checks the HTTP status code immediately after connecting to the backend:

- If the backend returns a non-200 status (429, 5xx, etc.) → router reads the error body, closes the connection, and triggers fallback to the next backend
- If the backend returns 200 → router commits to streaming and passes chunks through to Claude Code

Once streaming starts (200 status), the router cannot intercept or retry mid-stream. If the SSE stream contains errors **during** generation, they are passed through to Claude Code directly. This is a fundamental limitation of SSE streaming.

### Fallback Flow

```
Request → Primary Backend
  ├─ Success → Return response
  ├─ Retryable error (429, 5xx, quota exhaustion) → Cooldown + Try next fallback
  ├─ Fallback error (4xx client error) → Try next fallback (no cooldown)
  └─ All backends exhausted → Return 502
```

### Fallback Order (Default)

| Primary | Fallback 1 | Fallback 2 | Fallback 3 |
|---------|-----------|-----------|-----------|
| GPT | MiMo | DeepSeek | Gemini |
| DeepSeek | Gemini | MiMo | GPT |
| MiMo | Gemini | DeepSeek | — |
| Gemini | DeepSeek | MiMo | — |

## Install

```bash
mkdir -p ~/.codex/skills
cp -R claude-code-multi-provider ~/.codex/skills/
chmod +x ~/.codex/skills/claude-code-multi-provider/scripts/diagnose.sh
```

## Router Setup

The router source is in `claude-code-multi-provider/router/router.py`. Configuration template: `claude-code-multi-provider/router/.env.example`.

```bash
# Copy the router
cp claude-code-multi-provider/router/router.py ~/tools/claude-code-router/router.py
cp claude-code-multi-provider/router/pyproject.toml ~/tools/claude-code-router/pyproject.toml

# Create .env from template (edit with your actual values)
cp claude-code-multi-provider/router/.env.example ~/tools/claude-code-router/.env
vim ~/tools/claude-code-router/.env

# Install dependencies
cd ~/tools/claude-code-router
pip install fastapi uvicorn httpx python-dotenv
# or: uv pip install fastapi uvicorn httpx python-dotenv

# Start router
setsid python router.py </dev/null >router.log 2>&1 &

# Verify
curl http://127.0.0.1:8084/
```

## Claude Code Settings

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8084",
    "ANTHROPIC_MODEL": "router/opus",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "router/opus",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "router/sonnet",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "router/haiku",
    "CLAUDE_CODE_SUBAGENT_MODEL": "router/subagent"
  }
}
```

## Diagnose

```bash
~/.codex/skills/claude-code-multi-provider/scripts/diagnose.sh
```

Optional non-mutating launcher health checks:

```bash
~/.codex/skills/claude-code-multi-provider/scripts/diagnose.sh --health
```

## GPT Backend Notes

`clawgate` was tried first, but its ChatGPT mode warned that `gpt-5.5` was not
in the supported Codex model allowlist and Opus requests timed out. The working
GPT backend is now:

```bash
raine-claude-code-proxy serve
# default local port used by this setup: 18765
```

Validated raine/Codex models:

| Model | Result |
|---|---:|
| `gpt-5.5` | pass |
| `gpt-5.5-fast` | pass |
| `gpt-5.4` | pass |
| `gpt-5.4-fast` | pass |
| `gpt-5.3-codex` | pass |
| `gpt-5.3-codex-fast` | pass |
| `gpt-5.4-mini-fast` | pass |
| `gpt-5.3-codex-spark-fast` | fail for the tested ChatGPT account |
