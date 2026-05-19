---
name: claude-code-multi-provider
description: >-
  Configure, debug, and audit a Claude Code multi-provider setup with GPT,
  DeepSeek, MiMo, Gemini, local tier routing, fallback chains, cc-switch
  profiles, and read-only diagnostics.
---

# Claude Code Multi-Provider

Use this skill when the user asks about Claude Code provider setup, GPT/ChatGPT OAuth via `raine/claude-code-proxy` or clawgate, MiMo, DeepSeek, Gemini/Vertex, local tier routers, `cc-switch`, `claude-router`, `claude-gpt`, `claude-gemini`, or fallback launchers.

This skill is intentionally conservative: inspect first, avoid changing providers unless the user explicitly asks, and never print API keys or OAuth tokens.

## Known Entrypoints

Common entrypoints:

- `claude-router`: Claude Code through a local tier router, default local proxy `127.0.0.1:8084`.
- `raine-claude-code-proxy`: GPT/Codex OAuth backend, default local proxy `127.0.0.1:18765`.
- `claude-gpt`: legacy Claude Code through clawgate, default local proxy `127.0.0.1:8082`.
- `claude-gemini`: Claude Code through an Anthropic-compatible Gemini/Vertex proxy, default local proxy `127.0.0.1:8083`.
- `cc-switch use mimo && claude`: MiMo Token Plan via Anthropic-compatible endpoint.
- `cc-switch use deepseek && claude`: DeepSeek official Claude Code integration.

Final target routing:

1. Opus / primary -> GPT-5.5 through `raine-claude-code-proxy`.
2. Sonnet -> DeepSeek `deepseek-v4-pro`.
3. Haiku -> MiMo `mimo-v2.5-pro`.
4. SubAgent and unmatched model names -> Gemini/Vertex proxy.

Important: a fallback launcher such as `claude-auto` may run `cc-switch use mimo` or `cc-switch use deepseek`, so it can change the default provider. For diagnosis, prefer individual entrypoints.

## Router Architecture

The router (`router.py`) is a FastAPI proxy that sits between Claude Code and multiple LLM backends. It implements intelligent fallback inspired by LiteLLM.

### Request Flow

```
Claude Code → Router (:8084) → Backend
  ├─ Success → Return response
  ├─ Retryable error (429, 5xx, quota) → Cooldown + Try next fallback
  ├─ Fallback error (4xx) → Try next fallback (no cooldown)
  └─ All backends exhausted → 502
```

### Error Classification

The router classifies errors into two categories:

| Class | Behavior | Trigger |
|-------|----------|---------|
| `retryable` | Cooldown + fallback | 429, 502, 503, 504, per-backend extra codes, quota exhaustion in body |
| `fallback` | Fallback only, no cooldown | 4xx (except 429) |

### Per-Backend Configurable Retryable Statuses

Some backends return non-standard status codes for quota exhaustion. For example, GPT (`raine/claude-code-proxy`) returns 400 for "no quota". Configure via `.env`:

```bash
# GPT returns 400 for "no quota" — treat as retryable
GPT_EXTRA_RETRYABLE=400
```

### Cooldown

Failed backends are placed on cooldown for `COOLDOWN_SECONDS` (default 300s). If the backend returns a `Retry-After` header, that value is used instead.

### Fallback Chains

Configure per-backend fallback order in `.env`:

```bash
GPT_FALLBACKS=mimo,deepseek,gemini
DEEPSEEK_FALLBACKS=gemini,mimo,gpt
MIMO_FALLBACKS=gemini,deepseek
GEMINI_FALLBACKS=deepseek,mimo
```

### Health Endpoint

`GET /` returns backend status, stats, cooldown info, and configuration:

```json
{
  "status": "ok",
  "backends": {
    "gpt": {
      "base_url": "http://127.0.0.1:18765",
      "model": "gpt-5.5",
      "on_cooldown": true,
      "cooldown_remaining_s": 245,
      "stats": {"success": 0, "fail": 1, "cooldown": 0},
      "extra_retryable": [400]
    }
  },
  "fallbacks": {"gpt": ["mimo", "deepseek", "gemini"]},
  "global_retryable_statuses": [429, 502, 503, 504]
}
```

## Provider Shapes

Router config:

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:8084
ANTHROPIC_MODEL=router/sonnet
ANTHROPIC_DEFAULT_OPUS_MODEL=router/opus
ANTHROPIC_DEFAULT_SONNET_MODEL=router/sonnet
ANTHROPIC_DEFAULT_HAIKU_MODEL=router/haiku
CLAUDE_CODE_SUBAGENT_MODEL=router/subagent
```

Route meanings:

- `router/opus` -> `gpt-5.5` through `raine-claude-code-proxy`.
- `router/sonnet` -> DeepSeek `deepseek-v4-pro`.
- `router/haiku` -> MiMo `mimo-v2.5-pro`.
- `router/subagent` and unmatched model names -> Gemini proxy.

raine GPT/Codex proxy:

```bash
GPT_PROXY_PORT=18765
GPT_MODEL=gpt-5.5
```

Validated raine models:

- works: `gpt-5.5`, `gpt-5.5-fast`, `gpt-5.4`, `gpt-5.4-fast`, `gpt-5.3-codex`, `gpt-5.3-codex-fast`, `gpt-5.4-mini-fast`
- failed for the tested ChatGPT account: `gpt-5.3-codex-spark-fast`

DeepSeek official Claude Code config:

```bash
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-pro
ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro
ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
CLAUDE_CODE_EFFORT_LEVEL=max
```

MiMo Token Plan config:

```bash
ANTHROPIC_BASE_URL=https://token-plan-sgp.xiaomimimo.com/anthropic
ANTHROPIC_MODEL=mimo-v2.5-pro
ANTHROPIC_DEFAULT_OPUS_MODEL=mimo-v2.5-pro
ANTHROPIC_DEFAULT_SONNET_MODEL=mimo-v2.5-pro
ANTHROPIC_DEFAULT_HAIKU_MODEL=mimo-v2.5-pro
CLAUDE_CODE_SUBAGENT_MODEL=mimo-v2.5-pro
```

Gemini/Vertex proxy config:

```bash
GEMINI_PROXY_DIR=~/tools/claude-code-proxy-gemini
GEMINI_PROXY_PORT=8083
PREFERRED_PROVIDER=google
USE_VERTEX_AUTH=true
VERTEX_PROJECT=<your-gcp-project-id>
VERTEX_LOCATION=<your-vertex-location>
BIG_MODEL=gemini-3.1-pro-preview
SMALL_MODEL=gemini-3.1-flash-lite
```

Legacy clawgate GPT config:

```bash
CLAWGATE_PORT=8082
CLAWGATE_BIG_MODEL=gpt-5.4
CLAWGATE_MID_MODEL=gpt-5.3-codex
CLAWGATE_SMALL_MODEL=gpt-5.2-codex
```

Use clawgate as a fallback only. In the local integration, clawgate ChatGPT mode did not reliably satisfy the GPT-5.5 target.

## Pitfalls

- Do not run `curl | bash` installers blindly. Inspect installer scripts, download binaries manually when possible, and verify checksums.
- `clawgate --version` may not exist. Use `clawgate help`, `clawgate status`, and `clawgate account list`.
- ChatGPT/Codex device auth and clawgate device auth can be separate flows. `codex login --device-auth` can succeed while `clawgate login --default` still waits for a different code.
- clawgate may not stay resident reliably with plain `nohup`. Use `setsid ... >log 2>&1 < /dev/null &`.
- clawgate ChatGPT mode warned that `gpt-5.5` was not in its known Codex model allowlist, and Opus requests through clawgate timed out under the 20 second acceptance window.
- `raine/claude-code-proxy` v0.0.13 successfully handled GPT-5.5 with Codex device auth in the tested setup.
- `cc-switch status` can show custom providers as `Active: unknown`. Check the URL and profile config.
- Do not use old DeepSeek `deepseek-chat` / `deepseek-reasoner` mappings for Claude Code if the official docs specify v4 Claude Code models.
- Do not copy terminal style artifacts like `[1m]` into model names. Treat them as ANSI formatting remnants unless the provider model list explicitly includes them.
- Gemini cannot be added to clawgate directly. Use a Gemini/Vertex Anthropic-compatible proxy or call Gemini CLI separately.
- A Gemini proxy must run from its repository directory. Starting `uvicorn server:app` elsewhere can fail with `Could not import module "server"`.
- Some Gemini proxies only map Claude model names containing `sonnet` or `haiku`; set Claude defaults accordingly to trigger Gemini model mapping.
- Some Gemini proxy whitelists lag behind Google model releases. Add model IDs such as `gemini-3.1-pro-preview` and `gemini-3.1-flash-lite` before setting them in `.env`.
- `gcloud auth application-default login` can fail in non-interactive shells at the verification code prompt. Existing `GOOGLE_APPLICATION_CREDENTIALS` service account JSON can be used where appropriate.
- Avoid fallback launchers during quiet audits if they mutate provider state.
- Claude Code settings can override shell-level `ANTHROPIC_MODEL=...` exports. For reliable route validation, update settings or use an entrypoint that fully controls the process environment.
- The router must strip incoming auth headers before forwarding. Do not pass `authorization`, `x-api-key`, `anthropic-api-key`, or `anthropic-auth-token` from Claude Code into arbitrary provider backends.
- Claude Code's native `--fallback-model` only works in `--print` mode and only handles overloaded (529) errors. It does NOT support cross-provider fallback (different API endpoints). The router is the correct solution for multi-provider fallback.

## Safe Workflow

For status-only tasks:

1. Run the bundled diagnostic script.
2. Read masked provider config.
3. Avoid running `cc-switch use ...` unless the user asked to switch providers.
4. Avoid `claude-auto` unless the user accepts provider mutation.

For non-mutating launcher health checks:

```bash
claude-router -p '只回复 OK'
claude-gpt -p '只回复 OK'
claude-gemini -p '只回复 OK'
```

For forced router route checks, prefer updating Claude Code settings or using a controlled wrapper. Shell-only overrides can be ignored when `~/.claude/settings.json` has an `env` block.

For MiMo or DeepSeek health checks, tell the user that `cc-switch use` will change the current default provider before running:

```bash
cc-switch use mimo && claude -p '只回复 OK'
cc-switch use deepseek && claude -p '只回复 OK'
```

## Diagnostic Script

Run:

```bash
~/.codex/skills/claude-code-multi-provider/scripts/diagnose.sh
```

Optional non-mutating health checks for independent launchers:

```bash
~/.codex/skills/claude-code-multi-provider/scripts/diagnose.sh --health
```

`--health` checks `claude-gpt` and `claude-gemini` only. It intentionally does not check MiMo or DeepSeek because that would require `cc-switch use`, which changes the default provider.
