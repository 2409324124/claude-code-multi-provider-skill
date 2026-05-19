# Claude Code Multi-Provider Skill

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

Final Claude Code environment shape:

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:8084
ANTHROPIC_MODEL=router/opus
ANTHROPIC_DEFAULT_OPUS_MODEL=router/opus
ANTHROPIC_DEFAULT_SONNET_MODEL=router/sonnet
ANTHROPIC_DEFAULT_HAIKU_MODEL=router/haiku
CLAUDE_CODE_SUBAGENT_MODEL=router/subagent
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

## Install

```bash
mkdir -p ~/.codex/skills
cp -R claude-code-multi-provider ~/.codex/skills/
chmod +x ~/.codex/skills/claude-code-multi-provider/scripts/diagnose.sh
```

## Diagnose

```bash
~/.codex/skills/claude-code-multi-provider/scripts/diagnose.sh
```

Optional non-mutating launcher health checks:

```bash
~/.codex/skills/claude-code-multi-provider/scripts/diagnose.sh --health
```

`--health` checks `claude-router`, `claude-gpt`, and `claude-gemini` when those
commands exist. It intentionally skips MiMo and DeepSeek direct `cc-switch`
checks because checking those usually requires `cc-switch use`, which changes
the active default provider.
