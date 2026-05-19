# 交接文档：Claude Code Multi-Provider Router

## 仓库
https://github.com/2409324124/claude-code-multi-provider-skill

## 当前状态
路由器已基本可用，但还有几个问题需要修复。

---

## 与 ec7bc57 阶段的区别

### 架构变化

**ec7bc57 阶段**：只有文档和诊断脚本，没有路由器代码。README 描述了一个"目标架构"，但路由器本身不在仓库里。

**当前版本**：新增了完整的路由器实现 `router/router.py`（~430行）。

### 路由机制对比

| 维度 | ec7bc57（旧） | 当前版本 |
|------|-------------|---------|
| **路由器代码** | 不在仓库里，只有文档描述 | `router/router.py`，FastAPI 实现 |
| **Fallback** | 无（单后端直连） | 多层 fallback chain，每后端可配置顺序 |
| **错误处理** | 无 | 分类：`retryable`（冷却+fallback）vs `fallback`（仅fallback） |
| **Cooldown** | 无 | 内存字典，支持 Retry-After 头 |
| **Stats** | 无 | 每后端 success/fail 计数 |
| **Streaming** | 未处理 | 先检查 status_code，>=400 走 fallback，2xx 才 passthrough |
| **Health 端点** | 无 | `GET /` 返回后端状态、统计、冷却、配置 |

### 代码结构

```
router/router.py
├── BACKENDS           # 4个后端配置（从 .env 读取）
├── ROUTES             # 关键词→后端映射表
├── FALLBACKS          # 每后端的 fallback 链
├── EXTRA_RETRYABLE    # 每后端额外可重试状态码（如 GPT 的 400）
├── _cooldowns         # 冷却状态（内存）
├── _stats             # 统计计数（内存）
├── classify_error()   # 错误分类核心函数
├── proxy_request()    # 代理请求（streaming/非streaming）
├── handle_messages()  # 主路由逻辑：遍历候选后端→fallback
└── health()           # GET / 端点
```

### 路由流程

```
请求进入 → resolve_backend_name(model) → 得到 primary_name
→ 构建 candidate_names = [primary] + FALLBACKS[primary]
→ 遍历候选:
   ├─ 跳过冷却中的
   ├─ rewrite_model(body, backend)  # 替换模型名
   ├─ proxy_request(...)            # 转发请求
   ├─ classify_error(status, body)  # 分类错误
   ├─ retryable → mark_cooldown + continue
   ├─ fallback → continue（不冷却）
   └─ success → return
→ 全部失败 → 502
```

---

## 必须修的

### 1. SKILL.md YAML 头部（GitHub 预览报错）

**问题**: GitHub 显示 `Error in user YAML: mapping values are not allowed in this context at line 2 column 93`

**文件**: `claude-code-multi-provider/SKILL.md` 第 1-8 行

**当前内容**:
```yaml
---
name: claude-code-multi-provider
description: "Configure, debug, and audit a Claude Code multi-provider setup with GPT, DeepSeek, MiMo, Gemini, local tier routing, fallback chains, cc-switch profiles, and read-only diagnostics."
---
```

**注意**: 刚改成了双引号字符串，但 GitHub 可能还没刷新。如果仍然报错，尝试用单引号或去掉引号用 `>-` 折叠标量。

**验证方法**: 打开 https://github.com/2409324124/claude-code-multi-provider-skill/blob/main/claude-code-multi-provider/SKILL.md 看预览是否正常。

---

### 2. Streaming fallback 逻辑漏洞

**问题**: `router.py` 中 `proxy_request` 的 streaming 分支，如果后端返回 429/500 等错误状态码，会直接包装成 `StreamingResponse` 返回，不会进入 `classify_error` 的 fallback 逻辑。

**文件**: `claude-code-multi-provider/router/router.py`，`proxy_request` 函数，约第 240-273 行

**当前代码**（有问题）:
```python
backend_response = await client.send(req, stream=True)
# ... 异常处理 ...

# 直接包装成 StreamingResponse，没有检查 status_code
async def stream_response():
    ...

return StreamingResponse(stream_response(), status_code=backend_response.status_code, ...)
```

**应该改成**:
```python
backend_response = await client.send(req, stream=True)
# ... 异常处理 ...

# 先检查状态码
if backend_response.status_code >= 400:
    # 读取错误响应体，关闭连接，返回普通 Response（让调用方能 fallback）
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

# 只有 2xx 才真正 passthrough streaming
async def stream_response():
    ...
return StreamingResponse(stream_response(), ...)
```

**同时更新 README 的 Streaming Limitations 章节**，改为：
> Streaming mode supports fallback **before** the response body is streamed. The router checks the HTTP status code immediately after connecting to the backend. If the backend returns 200, the router commits to streaming and passes chunks through directly.

---

## 建议修的（优先级中等）

### 3. .env.example API key 占位符

**文件**: `claude-code-multi-provider/router/.env.example`

**问题**: `MIMO_API_KEY=your-mimo-api-key-here` 和 `DEEPSEEK_API_KEY=your-deepseek-api-key-here` 是非注释状态，用户直接复制后 router 会把这个假值当真实 key 发出去。

**建议改成**:
```env
# MIMO_API_KEY=
# DEEPSEEK_API_KEY=
```

或者在 `router.py` 里加一个 key 清洗函数：
```python
def clean_key(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("your-") or value.endswith("-here"):
        return None
    return value
```

---

### 4. README 表格渲染

**问题**: GitHub 预览里表格可能显示不正常（行被压到一起）。

**文件**: `README.md`

**检查**: 打开 GitHub 预览，看 Router Features 表格和 Validated raine models 表格是否正常渲染。如果不行，确保表格前后有空行，且 `|` 对齐。

---

### 5. GitHub 语言检测

**问题**: 仓库主页显示 Shell 100%，但核心是 Python router。

**文件**: 根目录

**建议**: 添加 `.gitattributes`:
```
*.py linguist-language=Python
*.sh linguist-language=Shell
```

---

## 已完成的（不用再动）

- [x] 关键词路由（opus→GPT, sonnet→DeepSeek, haiku→MiMo, subagent→Gemini）
- [x] Fallback chains（可配置顺序）
- [x] 错误分类（retryable vs fallback）
- [x] 每后端可配置额外可重试状态码（`GPT_EXTRA_RETRYABLE=400`）
- [x] Cooldown 机制（支持 Retry-After 头）
- [x] 每后端统计（success/fail/cooldown）
- [x] 增强 health 端点
- [x] .env.example 和 pyproject.toml
- [x] .gitignore（排除 .env）
- [x] README 和 SKILL.md 基本文档

## 测试命令

```bash
# 启动路由器
setsid python router.py </dev/null >router.log 2>&1 &

# 健康检查
curl http://127.0.0.1:8084/

# 路由测试
curl -s -X POST http://127.0.0.1:8084/v1/messages -H "Content-Type: application/json" -d '{"model":"router/haiku","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
curl -s -X POST http://127.0.0.1:8084/v1/messages -H "Content-Type: application/json" -d '{"model":"router/sonnet","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
curl -s -X POST http://127.0.0.1:8084/v1/messages -H "Content-Type: application/json" -d '{"model":"router/opus","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'

# Claude Code 真实调用
claude -p "回复一个字：好"
claude -p "回复一个字：好" --model haiku
```
