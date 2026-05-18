#!/usr/bin/env bash
set -euo pipefail

HEALTH=0
if [[ "${1:-}" == "--health" ]]; then
  HEALTH=1
fi

section() {
  printf '\n== %s ==\n' "$1"
}

cmd_status() {
  local cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    printf '%-18s %s\n' "$cmd" "$(command -v "$cmd")"
  else
    printf '%-18s missing\n' "$cmd"
  fi
}

mask_json_file() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "missing: $file"
    return
  fi

  node - "$file" <<'NODE'
const fs = require('fs');
const path = process.argv[2];
const secretPattern = /(key|token|secret|refresh|access|credential|password)/i;

function mask(value, key = '') {
  if (value === null || value === undefined) return value;
  if (typeof value === 'string') {
    if (secretPattern.test(key)) return `*** len=${value.length}`;
    if (value.startsWith('sk-') || value.startsWith('tp-')) return `*** len=${value.length}`;
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => mask(item, key));
  if (typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = mask(v, k);
    return out;
  }
  return value;
}

try {
  const parsed = JSON.parse(fs.readFileSync(path, 'utf8'));
  console.log(JSON.stringify(mask(parsed), null, 2));
} catch (error) {
  console.log(`unreadable json: ${path}: ${error.message}`);
}
NODE
}

health_check() {
  local name="$1"
  shift
  local log
  log="$(mktemp)"
  if timeout 120 "$@" -p '只回复 OK' >"$log" 2>&1 && rg -q '^OK$|OK' "$log"; then
    printf '%-18s OK\n' "$name"
  else
    printf '%-18s FAIL\n' "$name"
    tail -n 20 "$log" || true
  fi
  rm -f "$log"
}

section "Commands"
for cmd in claude cc-switch clawgate claude-gpt claude-gemini claude-auto uv gcloud gemini ss rg node; do
  cmd_status "$cmd"
done

section "Listening Ports"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp 2>/dev/null | rg '127\.0\.0\.1:8082|127\.0\.0\.1:8083|clawgate|uvicorn' || true
else
  echo "ss missing"
fi

section "Current cc-switch Status"
if command -v cc-switch >/dev/null 2>&1; then
  cc-switch status || true
else
  echo "cc-switch missing"
fi

section "Claude Settings (masked)"
mask_json_file "$HOME/.claude/settings.json"

section "cc-switch Profiles (masked)"
mask_json_file "$HOME/.cc-switch/profiles.json"

section "Provider Files"
for file in \
  "$HOME/.clawgate/token.json" \
  "$HOME/tools/claude-code-proxy-gemini/.env" \
  "$GOOGLE_APPLICATION_CREDENTIALS" \
  "$HOME/.config/gcloud/application_default_credentials.json" \
  "$HOME/.gemini/oauth_creds.json"; do
  if [[ -n "${file:-}" && -f "$file" ]]; then
    printf 'present %s mode=%s\n' "$file" "$(stat -c '%a' "$file" 2>/dev/null || echo unknown)"
  elif [[ -n "${file:-}" ]]; then
    printf 'missing %s\n' "$file"
  fi
done

if [[ "$HEALTH" -eq 1 ]]; then
  section "Health Checks"
  if command -v claude-gpt >/dev/null 2>&1; then
    health_check "claude-gpt" claude-gpt
  else
    echo "claude-gpt missing"
  fi

  if command -v claude-gemini >/dev/null 2>&1; then
    health_check "claude-gemini" claude-gemini
  else
    echo "claude-gemini missing"
  fi

  echo "MiMo and DeepSeek health checks are skipped because they require cc-switch use and mutate the active provider."
else
  section "Health Checks"
  echo "Skipped. Re-run with --health to check claude-gpt and claude-gemini only."
fi
