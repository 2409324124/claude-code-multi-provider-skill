# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "httpx",
#     "python-dotenv",
# ]
# ///
"""Universal Model Router for Claude Code.
Routes different model tiers to different backends:
  Opus    → GPT-5.5  (raine/claude-code-proxy)
  Sonnet  → DeepSeek (api.deepseek.com)
  Haiku   → MiMo     (xiaomimimo)
  SubAgent/other → Gemini (local proxy)

Features (LiteLLM-inspired):
  - Configurable retryable status codes per backend
  - Error classification: backend_error (cooldown+fallback) vs request_error (fallback only)
  - Retry-After header support for intelligent cooldown
  - Per-backend success/failure stats
"""

import json
import os
import sys
import time
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

load_dotenv()

app = FastAPI()


def clean_key(value: str | None) -> str | None:
    """Ignore empty or template placeholder API keys."""
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("your-") or stripped.endswith("-here"):
        return None
    return stripped


# ─── Backend configs ──────────────────────────────────────────────────────────
BACKENDS = {
    "gpt": {
        "base_url": os.getenv("GPT_BASE_URL", "http://127.0.0.1:18765"),
        "model": os.getenv("GPT_MODEL", "gpt-5.5"),
        "api_key": clean_key(os.getenv("GPT_API_KEY")),
    },
    "mimo": {
        "base_url": os.getenv("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/anthropic"),
        "model": os.getenv("MIMO_MODEL", "mimo-v2.5-pro"),
        "api_key": clean_key(os.getenv("MIMO_API_KEY")),
    },
    "deepseek": {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        "api_key": clean_key(os.getenv("DEEPSEEK_API_KEY")),
    },
    "gemini": {
        "base_url": os.getenv("GEMINI_BASE_URL", "http://127.0.0.1:8083"),
        "model": os.getenv("GEMINI_MODEL", "claude-3-5-haiku-latest"),
        "api_key": clean_key(os.getenv("GEMINI_API_KEY")),
    },
}

# ─── Routing table: (keyword, backend_name) ──────────────────────────────────
ROUTES = [
    (os.getenv("ROUTE_OPUS_KEYWORD", "opus"), os.getenv("ROUTE_OPUS_BACKEND", "gpt")),
    (os.getenv("ROUTE_SONNET_KEYWORD", "sonnet"), os.getenv("ROUTE_SONNET_BACKEND", "deepseek")),
    (os.getenv("ROUTE_HAIKU_KEYWORD", "haiku"), os.getenv("ROUTE_HAIKU_BACKEND", "mimo")),
    (os.getenv("ROUTE_SUBAGENT_KEYWORD", "subagent"), os.getenv("ROUTE_SUBAGENT_BACKEND", "gemini")),
]
DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "gemini")

TIMEOUT = httpx.Timeout(float(os.getenv("ROUTER_TIMEOUT", "600")), connect=10.0)

# ─── Fallback chains ─────────────────────────────────────────────────────────
FALLBACKS = {
    "gpt": [b.strip() for b in os.getenv("GPT_FALLBACKS", "mimo,deepseek,gemini").split(",") if b.strip()],
    "deepseek": [b.strip() for b in os.getenv("DEEPSEEK_FALLBACKS", "mimo,gpt,gemini").split(",") if b.strip()],
    "mimo": [b.strip() for b in os.getenv("MIMO_FALLBACKS", "gemini,deepseek").split(",") if b.strip()],
    "gemini": [b.strip() for b in os.getenv("GEMINI_FALLBACKS", "deepseek,mimo").split(",") if b.strip()],
}

# ─── Retryable status codes ──────────────────────────────────────────────────
# Global defaults: these statuses always trigger fallback + cooldown
RETRYABLE_STATUSES = {429, 502, 503, 504}

# Per-backend extra retryable statuses (e.g. GPT returns 400 for "no quota")
# Configure via: GPT_EXTRA_RETRYABLE=400,402
def _parse_extra_retryable(env_key: str) -> set[int]:
    raw = os.getenv(env_key, "")
    return {int(s.strip()) for s in raw.split(",") if s.strip().isdigit()}

EXTRA_RETRYABLE: dict[str, set[int]] = {
    name: _parse_extra_retryable(f"{name.upper()}_EXTRA_RETRYABLE")
    for name in BACKENDS
}

def is_retryable_status(name: str, status_code: int) -> bool:
    """Check if a status code should trigger fallback for this backend."""
    return status_code in RETRYABLE_STATUSES or status_code in EXTRA_RETRYABLE.get(name, set())

# ─── Cooldown ─────────────────────────────────────────────────────────────────
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "300"))
_cooldowns: dict[str, float] = {}


def is_on_cooldown(name: str) -> bool:
    until = _cooldowns.get(name)
    if until is None:
        return False
    if time.time() > until:
        _cooldowns.pop(name, None)
        return False
    return True


def mark_cooldown(name: str, retry_after: float | None = None):
    """Put a backend on cooldown. Use Retry-After header if available."""
    if retry_after and retry_after > 0:
        cd = min(retry_after, 3600)  # cap at 1 hour
    else:
        cd = COOLDOWN_SECONDS
    _cooldowns[name] = time.time() + cd
    print(f"[router] {name} on cooldown {cd:.0f}s")
    sys.stdout.flush()


# ─── Stats ────────────────────────────────────────────────────────────────────
_stats: dict[str, dict[str, int]] = {
    name: {"success": 0, "fail": 0, "cooldown": 0}
    for name in BACKENDS
}


def record_stat(name: str, kind: str):
    if name in _stats and kind in _stats[name]:
        _stats[name][kind] += 1


# ─── Error classification ─────────────────────────────────────────────────────
def classify_error(status_code: int, body: bytes, name: str) -> str:
    """Classify error for routing decisions.

    Returns:
        "retryable"   → cooldown + fallback (429, 5xx, quota exhaustion)
        "fallback"    → fallback only, no cooldown (4xx that might be backend-specific)
        "not_retryable" → return as-is (success, or truly non-retryable)
    """
    # Check for quota exhaustion in body (even on 200)
    if status_code == 200:
        try:
            data = json.loads(body)
            err = data.get("error", {})
            t = err.get("type", "")
            msg = str(err.get("message", "")).lower()
            if t in ("rate_limit_error", "overloaded_error", "insufficient_quota"):
                return "retryable"
            if any(kw in msg for kw in ("quota", "rate limit", "exceeded", "insufficient", "余额", "额度", "limit reached")):
                return "retryable"
        except (json.JSONDecodeError, TypeError):
            pass
        return "not_retryable"

    # Backend errors: cooldown + fallback
    if is_retryable_status(name, status_code):
        return "retryable"

    # Client errors (4xx except 429): fallback but no cooldown
    if 400 <= status_code < 500:
        return "fallback"

    # Other errors
    return "not_retryable"


def parse_retry_after(headers: httpx.Headers | dict) -> float | None:
    """Extract Retry-After header value in seconds."""
    ra = headers.get("retry-after") or headers.get("Retry-After")
    if ra is None:
        return None
    try:
        return float(ra)
    except (ValueError, TypeError):
        return None


# ─── Backend resolution ──────────────────────────────────────────────────────
def resolve_backend_name(model_name: str) -> str:
    """Route model name to backend name. First keyword match wins."""
    model_lower = model_name.lower()
    for keyword, backend_name in ROUTES:
        if keyword and keyword in model_lower:
            return backend_name
    return DEFAULT_BACKEND


def resolve_backend(model_name: str) -> dict:
    """Match model name to backend config."""
    model_lower = model_name.lower()
    for keyword, backend_name in ROUTES:
        if keyword and keyword in model_lower:
            return BACKENDS.get(backend_name, BACKENDS["gpt"])
    return BACKENDS.get(DEFAULT_BACKEND, BACKENDS["gpt"])


# ─── Header building ─────────────────────────────────────────────────────────
def build_headers(backend: dict, incoming: dict = None, extra: dict = None) -> dict:
    """Build forwarded request headers with proper auth."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if incoming:
        for key, value in incoming.items():
            lk = key.lower()
            if lk in {
                "host", "content-length", "connection", "accept-encoding",
                "authorization", "x-api-key", "anthropic-api-key", "anthropic-auth-token",
            }:
                continue
            headers[key] = value
    if backend["api_key"]:
        headers["x-api-key"] = backend["api_key"]
        headers["Authorization"] = f"Bearer {backend['api_key']}"
    if extra:
        headers.update(extra)
    return headers


# ─── Proxy ────────────────────────────────────────────────────────────────────
async def proxy_request(method: str, path: str, query: str, headers_in: dict,
                        body: bytes, backend: dict, stream: bool):
    """Forward request to backend and return response."""
    url = f"{backend['base_url']}{path}"
    if query:
        url = f"{url}?{query}"
    headers = build_headers(backend, incoming=headers_in)

    if stream:
        client = httpx.AsyncClient(timeout=TIMEOUT, trust_env=False)
        req = client.build_request(method=method, url=url, headers=headers, content=body)
        try:
            backend_response = await client.send(req, stream=True)
        except httpx.TimeoutException as exc:
            await client.aclose()
            return Response(
                content=json.dumps({"type": "error", "error": {"type": "timeout_error", "message": str(exc)}}),
                status_code=504, media_type="application/json",
                headers={"x-route-backend": backend.get("model", ""), "x-route-status": "timeout"},
            )
        except httpx.RequestError as exc:
            await client.aclose()
            return Response(
                content=json.dumps({"type": "error", "error": {"type": "api_error", "message": str(exc)}}),
                status_code=502, media_type="application/json",
                headers={"x-route-backend": backend.get("model", ""), "x-route-status": "request_error"},
            )

        # Check status before committing to stream.
        # If backend returned error (4xx/5xx), read body and return as regular Response
        # so the caller can classify the error and potentially fallback.
        if backend_response.status_code >= 400:
            content = await backend_response.aread()
            await backend_response.aclose()
            await client.aclose()
            return Response(
                content=content,
                status_code=backend_response.status_code,
                media_type=backend_response.headers.get("content-type", "application/json").split(";")[0],
                headers={
                    "x-route-backend": backend.get("model", ""),
                    "x-route-status": str(backend_response.status_code),
                },
            )

        async def stream_response():
            try:
                async for chunk in backend_response.aiter_bytes():
                    yield chunk
            finally:
                await backend_response.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_response(),
            status_code=backend_response.status_code,
            media_type="text/event-stream",
            headers={
                "x-route-backend": backend.get("model", ""),
                "x-route-status": str(backend_response.status_code),
            },
        )

    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
        try:
            backend_response = await client.request(method=method, url=url, headers=headers, content=body)
        except httpx.TimeoutException as exc:
            return Response(
                content=json.dumps({"type": "error", "error": {"type": "timeout_error", "message": str(exc)}}),
                status_code=504, media_type="application/json",
                headers={"x-route-backend": backend.get("model", ""), "x-route-status": "timeout"},
            )
        except httpx.RequestError as exc:
            return Response(
                content=json.dumps({"type": "error", "error": {"type": "api_error", "message": str(exc)}}),
                status_code=502, media_type="application/json",
                headers={"x-route-backend": backend.get("model", ""), "x-route-status": "request_error"},
            )

        return Response(
            content=backend_response.content,
            status_code=backend_response.status_code,
            media_type=backend_response.headers.get("content-type", "application/json").split(";")[0],
            headers={
                "x-route-backend": backend.get("model", ""),
                "x-route-status": str(backend_response.status_code),
            },
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────
async def get_stream_flag(body_bytes: bytes) -> bool:
    try:
        return json.loads(body_bytes).get("stream", False)
    except (json.JSONDecodeError, TypeError):
        return False


async def rewrite_model(body_bytes: bytes, backend: dict) -> bytes:
    try:
        data = json.loads(body_bytes)
        original = data.get("model", "unknown")
        data["model"] = backend["model"]
        print(f"  {original} -> {backend['model']}  [{backend.get('base_url', '')}]")
        sys.stdout.flush()
        return json.dumps(data).encode("utf-8")
    except (json.JSONDecodeError, TypeError):
        return body_bytes


# ─── Main handler ─────────────────────────────────────────────────────────────
@app.api_route("/v1/messages", methods=["POST"])
@app.api_route("/v1/messages/count_tokens", methods=["POST"])
@app.api_route("/v1/messages", methods=["GET"])
async def handle_messages(request: Request):
    body = await request.body()

    primary_name = DEFAULT_BACKEND
    model_name = ""
    try:
        data = json.loads(body)
        model_name = data.get("model", "")
        primary_name = resolve_backend_name(model_name)
    except (json.JSONDecodeError, TypeError):
        pass

    stream = await get_stream_flag(body)

    candidate_names = [primary_name] + [n for n in FALLBACKS.get(primary_name, []) if n in BACKENDS]
    tried: list[str] = []

    for name in candidate_names:
        if is_on_cooldown(name):
            tried.append(f"{name}(cooldown)")
            continue

        backend = BACKENDS[name]
        rewritten = await rewrite_model(body, backend)
        print(f"[router] {request.method} {request.url.path} model={model_name} -> {name} ({backend['base_url']})")
        sys.stdout.flush()

        response = await proxy_request(
            method=request.method, path=request.url.path, query=request.url.query,
            headers_in=dict(request.headers), body=rewritten, backend=backend, stream=stream,
        )

        # Streaming: pass through (can't retry mid-stream)
        if isinstance(response, StreamingResponse):
            record_stat(name, "success")
            return response

        # Classify the response
        status = response.status_code
        error_class = classify_error(status, response.body, name)

        if error_class == "retryable":
            retry_after = parse_retry_after(response.headers)
            mark_cooldown(name, retry_after)
            record_stat(name, "fail")
            tried.append(f"{name}({status})")
            continue

        if error_class == "fallback":
            record_stat(name, "fail")
            tried.append(f"{name}({status})")
            continue

        # Success or non-retryable
        record_stat(name, "success")
        return response

    # All candidates exhausted
    return Response(
        content=json.dumps({
            "type": "error",
            "error": {
                "type": "all_backends_exhausted",
                "message": f"All backends failed: {', '.join(tried)}",
            },
        }),
        status_code=502,
        media_type="application/json",
    )


# ─── Health endpoint ──────────────────────────────────────────────────────────
@app.get("/")
async def health():
    now = time.time()
    return {
        "status": "ok",
        "backends": {
            name: {
                "base_url": cfg["base_url"],
                "model": cfg["model"],
                "on_cooldown": is_on_cooldown(name),
                "cooldown_remaining_s": max(0, _cooldowns.get(name, 0) - now),
                "stats": _stats.get(name, {}),
                "extra_retryable": sorted(EXTRA_RETRYABLE.get(name, set())),
            }
            for name, cfg in BACKENDS.items()
        },
        "fallbacks": FALLBACKS,
        "global_retryable_statuses": sorted(RETRYABLE_STATUSES),
    }


if __name__ == "__main__":
    host = os.getenv("ROUTER_HOST", "127.0.0.1")
    port = int(os.getenv("ROUTER_PORT", "8084"))
    print(f"Claude Code Router on http://{host}:{port}")
    for name, cfg in BACKENDS.items():
        extra = EXTRA_RETRYABLE.get(name, set())
        extra_str = f"  (extra retryable: {sorted(extra)})" if extra else ""
        print(f"  {name:10s} -> {cfg['base_url']}  ({cfg['model']}){extra_str}")
    sys.stdout.flush()
    uvicorn.run(app, host=host, port=port, log_level="warning")
