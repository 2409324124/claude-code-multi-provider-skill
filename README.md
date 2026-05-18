# Claude Code Multi-Provider Skill

A Codex skill for configuring, auditing, and troubleshooting a Claude Code
multi-provider setup:

- GPT / ChatGPT OAuth via `clawgate`
- MiMo Token Plan
- DeepSeek official Claude Code Anthropic API
- Gemini via Vertex ADC and an Anthropic-compatible proxy
- `cc-switch` profiles and fallback launchers

The bundled diagnostic script is read-only by default. It masks secrets and does
not switch providers.

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

`--health` checks `claude-gpt` and `claude-gemini` only. It intentionally skips
MiMo and DeepSeek because checking those usually requires `cc-switch use`, which
changes the active default provider.
