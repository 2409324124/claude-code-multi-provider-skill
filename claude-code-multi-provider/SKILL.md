---
name: claude-code-multi-provider
description: Use when configuring, debugging, or auditing a Claude Code multi-provider setup: GPT via clawgate/ChatGPT OAuth, MiMo Token Plan, DeepSeek official Claude Code Anthropic API, Gemini via Vertex ADC proxy, cc-switch profiles, and provider fallback launchers. Includes known pitfalls and a read-only diagnostic script.
---

# Claude Code Multi-Provider

Use this skill when the user asks about Claude Code provider setup, GPT/ChatGPT OAuth via clawgate, MiMo, DeepSeek, Gemini/Vertex, `cc-switch`, `claude-gpt`, `claude-gemini`, or `claude-auto`.

This skill is intentionally conservative: inspect first, avoid changing providers unless the user explicitly asks, and never print API keys or OAuth tokens.

## Known Entrypoints

Common entrypoints:

- `claude-gpt`: Claude Code through clawgate, ChatGPT/Codex OAuth backend, default local proxy `127.0.0.1:8082`.
- `claude-gemini`: Claude Code through an Anthropic-compatible Gemini/Vertex proxy, default local proxy `127.0.0.1:8083`.
- `cc-switch use mimo && claude`: MiMo Token Plan via Anthropic-compatible endpoint.
- `cc-switch use deepseek && claude`: DeepSeek official Claude Code integration.

Recommended fallback order:

1. GPT/clawgate as the primary model tier.
2. MiMo as the next preferred provider.
3. DeepSeek below MiMo.
4. Gemini/Vertex last.

Important: a fallback launcher such as `claude-auto` may run `cc-switch use mimo` or `cc-switch use deepseek`, so it can change the default provider. For diagnosis, prefer individual entrypoints.

## Provider Shapes

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

clawgate GPT config:

```bash
CLAWGATE_PORT=8082
CLAWGATE_BIG_MODEL=gpt-5.4
CLAWGATE_MID_MODEL=gpt-5.3-codex
CLAWGATE_SMALL_MODEL=gpt-5.2-codex
```

## Pitfalls

- Do not run `curl | bash` installers blindly. Inspect installer scripts, download binaries manually when possible, and verify checksums.
- `clawgate --version` may not exist. Use `clawgate help`, `clawgate status`, and `clawgate account list`.
- ChatGPT/Codex device auth and clawgate device auth can be separate flows. `codex login --device-auth` can succeed while `clawgate login --default` still waits for a different code.
- clawgate may not stay resident reliably with plain `nohup`. Use `setsid ... >log 2>&1 < /dev/null &`.
- `cc-switch status` can show custom providers as `Active: unknown`. Check the URL and profile config.
- Do not use old DeepSeek `deepseek-chat` / `deepseek-reasoner` mappings for Claude Code if the official docs specify v4 Claude Code models.
- Do not copy terminal style artifacts like `[1m]` into model names. Treat them as ANSI formatting remnants unless the provider model list explicitly includes them.
- Gemini cannot be added to clawgate directly. Use a Gemini/Vertex Anthropic-compatible proxy or call Gemini CLI separately.
- A Gemini proxy must run from its repository directory. Starting `uvicorn server:app` elsewhere can fail with `Could not import module "server"`.
- Some Gemini proxies only map Claude model names containing `sonnet` or `haiku`; set Claude defaults accordingly to trigger Gemini model mapping.
- Some Gemini proxy whitelists lag behind Google model releases. Add model IDs such as `gemini-3.1-pro-preview` and `gemini-3.1-flash-lite` before setting them in `.env`.
- `gcloud auth application-default login` can fail in non-interactive shells at the verification code prompt. Existing `GOOGLE_APPLICATION_CREDENTIALS` service account JSON can be used where appropriate.
- Avoid fallback launchers during quiet audits if they mutate provider state.

## Safe Workflow

For status-only tasks:

1. Run the bundled diagnostic script.
2. Read masked provider config.
3. Avoid running `cc-switch use ...` unless the user asked to switch providers.
4. Avoid `claude-auto` unless the user accepts provider mutation.

For non-mutating launcher health checks:

```bash
claude-gpt -p '只回复 OK'
claude-gemini -p '只回复 OK'
```

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
