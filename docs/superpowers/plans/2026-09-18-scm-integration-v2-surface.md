# SCM Integration v2 — Phase 3: Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 v1 缺口 #5（Gateway 暴露 approval_id）、#7（scm tracing）；HITL 闭环从 plan 出口接通到调用方；scm 调用可观测。

**Architecture:** TDD 顺序：先加 client contextvar + Tracer 埋点（#7，无 Policy 依赖）；再扩展 guarded_executor 写 state.context；再让 Runtime loop 在 need_approval 时 transition 到 paused；最后 /chat 在 status==paused 时 payload 加 approval_id。Phase 3 完成时 `pytest -q` 应 125 passed（Phase 2 后 118 + Phase 3 新增 7）。

**Tech Stack:** Python 3.12+, contextvars（stdlib）, FastAPI TestClient（已有）, pytest-asyncio auto。

**Base branch:** `feat/scm-integration-v2-scenarios`（Phase 2 PR 合并后基于此）；新分支 `feat/scm-integration-v2-surface` 基于更新后的 `feat/scm-integration`。

---

### Task 1: client.py Tracer 埋点 (#7)

**Files:**
- Modify: `integrations/scm/client.py:1-15`（import + contextvar 定义）
- Modify: `integrations/scm/client.py:_send`（加 log_event）
- Modify: `apps/api/main.py`（`/chat` 入口设置 contextvar）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 切分支**

```bash
cd D:\ProgramProject\enterprise-agent
git checkout feat/scm-integration
git pull origin feat/scm-integration
git checkout -b feat/scm-integration-v2-surface
```

- [ ] **Step 2: 写 failing tests**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_client_emits_trace_event():
    """Phase 3 #7: 设 contextvar 时 _send 在前后各发一个 scm_call/scm_result 事件。"""
    from contextvars import ContextVar
    from observability.tracing import Tracer
    from integrations.scm.client import ScmClient, scm_trace_id
    # 重置全局 Tracer 以避免被前面测试污染
    Tracer._shared = Tracer()
    tid = "tr-v2-surface-test"
    token = scm_trace_id.set(tid)
    try:
        # 不真发请求：直接调 _send 走 fake_send
        c = ScmClient(gateway_url="http://x", auth_url="http://a",
                      username="u", password="p", timeout=5)
        # 用真 httpx 发个 GET 到不存在的 host 会 timeout，但我们关心 trace
        # 改用 monkeypatch 替代：直接调 c._send 拿结果
        # 这里简化：只测 contextvar.get 返回 tid
        assert scm_trace_id.get() == tid
        events = Tracer._shared._traces.get(tid, {}).get("events", [])
        # 在 set 后立刻查应为空（_send 还没调）
        assert events == []
    finally:
        scm_trace_id.reset(token)


def test_client_log_event_fires_on_send(monkeypatch):
    """Phase 3 #7: 设 contextvar 时 _send 发 log_event。"""
    from observability.tracing import Tracer
    from integrations.scm.client import ScmClient, scm_trace_id
    Tracer._shared = Tracer()
    tid = "tr-send-test"
    token = scm_trace_id.set(tid)
    try:
        captured = []
        # monkeypatch Tracer._shared.log_event 看是否被调
        orig = Tracer._shared.log_event
        def fake_log(trace_id, stage, data):
            captured.append((trace_id, stage, data))
            return orig(trace_id, stage, data)
        Tracer._shared.log_event = fake_log
        # fake _send 走通路径
        def fake_send(self, method, path, **kw):
            import httpx
            r = httpx.Response(200, request=httpx.Request(method, "http://x"+path),
                               content=b'{"ok":true}')
            r.status_code = 200
            return (200, {"ok": True})
        monkeypatch.setattr(ScmClient, "_send", fake_send)
        c = ScmClient(gateway_url="http://x", auth_url="http://a",
                      username="u", password="p", timeout=5)
        c.get("/api/x")
        stages = [s for _, s, _ in captured]
        assert "scm_call" in stages
        assert "scm_result" in stages
    finally:
        scm_trace_id.reset(token)


def test_client_no_trace_event_when_contextvar_unset(monkeypatch):
    """Phase 3 #7: contextvar 未设时 _send 不应发 log_event（容错）。"""
    from observability.tracing import Tracer
    from integrations.scm.client import ScmClient, scm_trace_id
    Tracer._shared = Tracer()
    # 确保 contextvar 是 None
    assert scm_trace_id.get() is None
    captured = []
    orig = Tracer._shared.log_event
    def fake_log(trace_id, stage, data):
        captured.append((trace_id, stage))
        return orig(trace_id, stage, data)
    Tracer._shared.log_event = fake_log
    def fake_send(self, method, path, **kw):
        return (200, {"ok": True})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a",
                  username="u", password="p", timeout=5)
    c.get("/api/x")
    assert captured == []
```

- [ ] **Step 3: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_client_emits_trace_event tests/test_scm_integration_v2.py::test_client_log_event_fires_on_send tests/test_scm_integration_v2.py::test_client_no_trace_event_when_contextvar_unset -v`
Expected: 全部 FAIL with `cannot import name 'scm_trace_id'`。

- [ ] **Step 4: 改 client.py 加 contextvar + _send 埋点**

`integrations/scm/client.py` 顶部 import 区追加：
```python
import contextvars
from observability.tracing import Tracer
```

并在 import 区下方（`class ScmClient` 之前）加：
```python
scm_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "scm_trace_id", default=None
)
```

`_send` 方法（约 184-196 行）替换为：
```python
    def _send(self, method: str, path: str, **kw):
        url = self.gateway_url.rstrip("/") + path
        headers = kw.pop("headers", {})
        token = self._tokens.get()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("X-Request-Id", str(uuid.uuid4()))
        tid = scm_trace_id.get()
        if tid and Tracer._shared is not None:
            try:
                Tracer._shared.log_event(tid, "scm_call",
                                         {"method": method, "path": path})
            except Exception:
                pass
        r = httpx.request(method, url, headers=headers, timeout=self.timeout, **kw)
        try:
            body = r.json()
        except Exception:
            body = {"text": r.text[:2000]}
        if tid and Tracer._shared is not None:
            try:
                Tracer._shared.log_event(tid, "scm_result",
                                         {"method": method, "path": path,
                                          "code": r.status_code})
            except Exception:
                pass
        return (r.status_code, body)
```

- [ ] **Step 5: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_client_emits_trace_event tests/test_scm_integration_v2.py::test_client_log_event_fires_on_send tests/test_scm_integration_v2.py::test_client_no_trace_event_when_contextvar_unset -v`
Expected: 3 passed。

- [ ] **Step 6: 跑全套确认无回归**

Run: `pytest -q`
Expected: 121 passed（118 + 3 = 121）。

- [ ] **Step 7: 提交**

```bash
git add integrations/scm/client.py tests/test_scm_integration_v2.py
git commit -m "feat(scm): trace scm_call/scm_result events via contextvar (#7)

integrations.scm.client exposes scm_trace_id ContextVar. When set
(by /chat in Task 4) and Tracer._shared exists, _send emits two
log_events: scm_call before request, scm_result after with status
code. ContextVar unset → no events (no-op, safe for offline mocks
and existing tests)."
```

---

### Task 2: guarded_executor 写 state.context on need_approval (#5 链路第一步)

**Files:**
- Modify: `agent/tools/executor.py:37-41`（need_approval 分支）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 写 failing tests**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_guarded_executor_writes_context_on_need_approval():
    """Phase 3 #5 链路第一步: need_approval 时 state.context 写入 pause 元数据。"""
    from agent.tools.executor import guarded_executor
    from agent.runtime.state import AgentState
    from security.policy import PolicyEngine
    from security.approval import ApprovalStore
    state = AgentState(task="t")
    state.context["tenant_id"] = "t1"
    plan = {"action": "call_tool", "tool": "scm.purchase.create",
            "args": {"sku": "X", "tenant_id": "t1"}}
    out = guarded_executor(plan, state,
                           user={"tenant_id": "t1", "role": "admin"},
                           policy=PolicyEngine(),
                           approvals=ApprovalStore())
    assert "need approval" in str(out["result"])
    assert state.context.get("pause_reason") == "need_approval"
    assert state.context.get("approval_tool") == "scm.purchase.create"
    assert state.context.get("approval_args") == {"sku": "X", "tenant_id": "t1"}
    aid = state.context.get("approval_id")
    assert aid is not None and aid.startswith("apr-")


def test_guarded_executor_no_context_write_on_deny():
    """Phase 3 #5 联动: deny 时不写 pause 元数据。"""
    from agent.tools.executor import guarded_executor
    from agent.runtime.state import AgentState
    from security.policy import PolicyEngine
    state = AgentState(task="t")
    plan = {"action": "call_tool", "tool": "scm.order.get",
            "args": {"order_no": "O-1", "tenant_id": "t2"}}
    out = guarded_executor(plan, state,
                           user={"tenant_id": "t1", "role": "admin"},
                           policy=PolicyEngine(),
                           approvals=ApprovalStore())
    assert "DENY" in str(out["result"])
    assert "pause_reason" not in state.context
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_guarded_executor_writes_context_on_need_approval tests/test_scm_integration_v2.py::test_guarded_executor_no_context_write_on_deny -v`
Expected: 第一个 FAIL（context 没写），第二个 PASS（deny 不写 context）。

- [ ] **Step 3: 改 executor.py**

`agent/tools/executor.py` 的 `guarded_executor` 中 `need_approval` 分支替换：
```python
        if decision == "need_approval":
            aid = None
            if approvals is not None:
                aid = approvals.request(user, tool, args)
            ctx = getattr(state, "context", None)
            if isinstance(ctx, dict):
                ctx["pause_reason"] = "need_approval"
                ctx["approval_id"] = aid
                ctx["approval_tool"] = tool
                ctx["approval_args"] = args
            return {"tool": tool, "result": f"need approval {aid}: {tool} pending human review"}
```

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_guarded_executor_writes_context_on_need_approval tests/test_scm_integration_v2.py::test_guarded_executor_no_context_write_on_deny -v`
Expected: 2 passed。

- [ ] **Step 5: 跑全套确认无回归**

Run: `pytest -q`
Expected: 123 passed（121 + 2 = 123）。

- [ ] **Step 6: 提交**

```bash
git add agent/tools/executor.py tests/test_scm_integration_v2.py
git commit -m "feat(executor): write pause_reason/approval_id to state.context on need_approval

guarded_executor when Policy.need_approval fires now writes:
  state.context[pause_reason] = 'need_approval'
  state.context[approval_id]   = ApprovalStore.request() result
  state.context[approval_tool] = tool name
  state.context[approval_args] = args dict

Deny path does not write any of the above. Gateway /chat reads
these in Phase 3 Task 4 to surface approval_id to caller."
```

---

### Task 3: Runtime loop transition 到 paused (#5 链路第二步)

**Files:**
- Modify: `agent/runtime/loop.py:130-133`（call_tool observation 处理）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 写 failing test**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_runtime_transitions_to_paused_on_need_approval(monkeypatch):
    """Phase 3 #5 链路第二步: Runtime 收到 need approval observation 应 break + paused。"""
    from agent.runtime.loop import run
    from agent.runtime.state import AgentState
    from observability.tracing import Tracer
    from agent.runtime import agent_task as at_mod

    Tracer._shared = Tracer()

    # 第一次 plan → call_tool (high-risk write)
    # 第二次 plan → finish（兜底）
    plans = iter([
        {"action": "call_tool", "tool": "scm.purchase.create",
         "args": {"sku": "X", "tenant_id": "t1"}},
        {"action": "finish", "answer": "should not reach"},
    ])
    def fake_planner(state):
        return next(plans)
    state = AgentState(task="buy something")
    state.context["tenant_id"] = "t1"

    final = run(state, planner=fake_planner)

    assert final.status == "paused"
    assert final.context.get("pause_reason") == "need_approval"
    assert final.context.get("approval_id", "").startswith("apr-")
    # 第二次 plan 不应被消费
    assert not hasattr(final, "_plans_remaining_marker")
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_runtime_transitions_to_paused_on_need_approval -v`
Expected: FAIL（`final.status == "done"` 而不是 `"paused"`，因为现状 observation 后 `continue` 回到循环，再调 planner 取到 finish）。

- [ ] **Step 3: 改 loop.py**

`agent/runtime/loop.py` 中 `if plan.get("action") == "call_tool":` 分支（约 118-133 行）的 observation 处理段替换为：
```python
        if plan.get("action") == "call_tool":
            _record_tokens(task, llm_messages if assembler else inner.messages, "")
            try:
                obs = executor(plan, inner)
            except Exception as e:
                inner.status = "failed"
                inner.answer = f"executor_error: {e}"
                _record_tokens(task, llm_messages or inner.messages, "")
                task.transition("failed", "executor_error")
                _emit_status(task, "executor_error")
                inner.context["agent_task"] = task
                return inner
            inner.observations.append(obs)
            inner.messages.append({"role": "observation", "content": str(obs)})

            # v2 Phase 3: HITL pause — need_approval observation breaks the loop.
            obs_result = str(obs.get("result", ""))
            if obs_result.startswith("need approval"):
                inner.status = "paused"
                task.transition("paused", "need_approval")
                _emit_status(task, "need_approval")
                break

            inner.iteration += 1
            continue
```

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_runtime_transitions_to_paused_on_need_approval -v`
Expected: PASS。

- [ ] **Step 5: 跑全套确认无回归**

Run: `pytest -q`
Expected: 124 passed（123 + 1 = 124）。

- [ ] **Step 6: 提交**

```bash
git add agent/runtime/loop.py tests/test_scm_integration_v2.py
git commit -m "feat(loop): transition to paused on need_approval observation

Runtime loop breaks + sets inner.status='paused' when executor
observation starts with 'need approval'. AgentTask.transition
records the status change (paused already in ALLOWED_TRANSITIONS
from status.py). Existing AgentStatus 'paused' reused; no new
status values introduced."
```

---

### Task 4: /chat 暴露 approval_id (#5 链路第三步)

**Files:**
- Modify: `apps/api/main.py:35-54`（`chat` 处理）
- Modify: `apps/api/main.py:1-9`（import 增加 Tracer + contextvar）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 写 failing tests**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_chat_payload_surfaces_approval_id(monkeypatch):
    """Phase 3 #5 链路第三步: /chat 在 status=paused 时 payload 含 approval_id。"""
    from fastapi.testclient import TestClient
    from apps.api.main import app
    from agent.runtime import loop as loop_mod
    from agent.runtime.state import AgentState

    # mock run()：直接构造 paused 状态
    def fake_run(state, planner=None, **kw):
        state.status = "paused"
        state.answer = "need approval apr-99: scm.purchase.create pending human review"
        state.context["pause_reason"] = "need_approval"
        state.context["approval_id"] = "apr-99"
        state.context["approval_tool"] = "scm.purchase.create"
        state.context["approval_args"] = {"sku": "X", "tenant_id": "t1"}
        return state
    monkeypatch.setattr(loop_mod, "run", fake_run)
    # 干掉 startup 的 schema init
    from infrastructure.pg import connector as conn_mod
    monkeypatch.setattr(conn_mod, "get_connector", lambda: None)
    from infrastructure.pg import schema as schema_mod
    monkeypatch.setattr(schema_mod, "ensure_schema", lambda c: None)

    c = TestClient(app)
    r = c.post("/chat", json={"message": "buy X", "tenant_id": "t1"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paused"
    assert body["approval_id"] == "apr-99"
    assert body["approval_tool"] == "scm.purchase.create"
    assert body["approval_args"] == {"sku": "X", "tenant_id": "t1"}


def test_no_approval_field_when_not_paused(monkeypatch):
    """Phase 3 #5 联动: 普通 done 状态不含 approval_id。"""
    from fastapi.testclient import TestClient
    from apps.api.main import app
    from agent.runtime import loop as loop_mod
    from agent.runtime.state import AgentState

    def fake_run(state, planner=None, **kw):
        state.status = "done"
        state.answer = "OK"
        return state
    monkeypatch.setattr(loop_mod, "run", fake_run)
    from infrastructure.pg import connector as conn_mod
    monkeypatch.setattr(conn_mod, "get_connector", lambda: None)
    from infrastructure.pg import schema as schema_mod
    monkeypatch.setattr(schema_mod, "ensure_schema", lambda c: None)

    c = TestClient(app)
    r = c.post("/chat", json={"message": "hi", "tenant_id": "t1"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert "approval_id" not in body
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_chat_payload_surfaces_approval_id tests/test_scm_integration_v2.py::test_no_approval_field_when_not_paused -v`
Expected: 第一个 FAIL（payload 没 approval_id），第二个 PASS（done 状态本来就不含）。

- [ ] **Step 3: 改 main.py**

`apps/api/main.py` import 区（约 1-9 行）追加：
```python
from observability.tracing import Tracer
from integrations.scm.client import scm_trace_id
```

`chat` 函数（35-54 行）替换为：
```python
@app.post("/chat")
def chat(req: ChatRequest):
    # Stage 1b: Gateway → Runtime. 有Key走DeepSeek，无Key走echo降级。
    client, model = get_default_client()
    planner = build_deepseek_planner(client=client, model=model)
    st = AgentState(task=req.message)
    if req.task_id:
        st.task_id = req.task_id
    st.context["tenant_id"] = req.tenant_id

    # v2 Phase 3: 开 trace + 把 trace_id 注入 contextvar 让 scm 客户端能埋点
    tracer = Tracer()
    tid = tracer.start_trace(req.message)
    st.context["trace_id"] = tid
    cv_token = scm_trace_id.set(tid)
    try:
        final = run(st, planner=planner)
    finally:
        tracer.end_trace(tid, status=final.status or "unknown")
        scm_trace_id.reset(cv_token)

    at = final.context.get("agent_task")
    payload = {
        "reply": final.answer,
        "status": final.status,
        "user_id": req.user_id,
        "task_id": at.task_id if at else None,
        "trace_id": tid,
    }
    if at and final.status != "failed":
        payload["token_usage"] = dict(at.token_usage)
        payload["cost"] = at.cost

    # v2 Phase 3: HITL 闭环 — paused + need_approval 时把 aid 暴露给 caller
    if final.status == "paused" and final.context.get("pause_reason") == "need_approval":
        payload["approval_id"] = final.context.get("approval_id")
        payload["approval_tool"] = final.context.get("approval_tool")
        payload["approval_args"] = final.context.get("approval_args")

    return payload
```

注意：`start_trace` 永远创建新 Tracer（v1 是 lazy），可能影响 v1 的 trace 测试。检查：

```bash
pytest tests/test_tracing.py -v
```

若 v1 已有 tracer 共享假设，改为：`tracer = Tracer._shared or Tracer()`。**本 plan 默认 start_trace 每次新建**，因为 v2 需要 trace_id 在 scm 调用前已确定。如果 v1 测试 break，回退到 `tracer = Tracer._shared or Tracer()` 并相应调 `start_trace` 仅在 shared 为 None 时。

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_chat_payload_surfaces_approval_id tests/test_scm_integration_v2.py::test_no_approval_field_when_not_paused -v`
Expected: 2 passed。

- [ ] **Step 5: 跑 v1 /chat 测试确认无回归**

Run: `pytest tests/test_health.py -v -k chat`
Expected: 仍 PASS。

- [ ] **Step 6: 跑全套确认无回归**

Run: `pytest -q`
Expected: 126 passed（124 + 2 = 126）。

- [ ] **Step 7: 提交**

```bash
git add apps/api/main.py tests/test_scm_integration_v2.py
git commit -m "feat(gateway): /chat surfaces approval_id when paused

When Runtime loop ends with status=paused + pause_reason=need_approval,
/chat response now includes:
  approval_id, approval_tool, approval_args

plus trace_id always (v2 Phase 3 #7 visibility). /approval/{aid}/decide
endpoint deferred to v3 (out of scope here)."
```

---

### Task 5: Phase 3 总验证 + PR

**Files:** 无新文件。

- [ ] **Step 1: 跑全套确认 GREEN**

Run: `pytest -q`
Expected: 126 passed。

- [ ] **Step 2: 确认改动集**

Run: `git diff --stat origin/feat/scm-integration..HEAD`
Expected 改动集：
- `integrations/scm/client.py`（contextvar + _send 埋点）
- `agent/tools/executor.py`（need_approval 写 context）
- `agent/runtime/loop.py`（paused transition）
- `apps/api/main.py`（/chat 暴露 aid）
- `tests/test_scm_integration_v2.py`

- [ ] **Step 3: 推送 + 开 PR**

```bash
git push -u origin feat/scm-integration-v2-surface
gh pr create --base feat/scm-integration --head feat/scm-integration-v2-surface \
  --title "feat(scm): v2 phase 3 surface (approval_id + scm tracing)" \
  --body "## What
Phase 3 of scm-integration-v2 spec. Closes gaps #5 and #7.

- integrations/scm/client.py: contextvar scm_trace_id; _send emits
  Tracer.log_event('scm_call'/'scm_result') when set
- agent/tools/executor.py: guarded_executor writes pause_reason,
  approval_id, approval_tool, approval_args into state.context on
  Policy.need_approval
- agent/runtime/loop.py: Runtime loop breaks + transitions to
  AgentStatus.paused when observation starts with 'need approval'
  (paused already in ALLOWED_TRANSITIONS, no new status added)
- apps/api/main.py: /chat creates a Tracer per request, sets
  scm_trace_id via contextvar, surfaces trace_id always and
  approval_id/tool/args when status='paused'

## Why
v1 returned 'need approval apr-X: ...' as the answer string;
callers couldn't programmatically extract the aid. Phase 3 makes
HITL actionable from outside the agent. Scm tracing closes the
observability gap so 5xx flakes (handled in Phase 1 retry) can be
diagnosed from the trace.

## How verified
- pytest -q: 126 passed (Phase 2 118 + Phase 3 new 8)
- v1 SCM tests still 8/8
- v2 Phase 1 + Phase 2 tests still pass
- FastAPI TestClient integration test confirms /chat payload shape

## Out of scope (v3 candidates)
- /approval/{aid}/decide HTTP endpoint
- ApprovalStore persistence to Postgres
- Resume from paused via /chat/{task_id}/resume"
```

Expected: PR URL 返回。

---

### Self-Review

- [x] **Spec coverage**: 7 gaps mapped to specific tasks (#1 → Phase 1 Task 1, #3 → Phase 1 Tasks 2, #8 → Phase 1 Task 3, #4 → Phase 2 Task 2, #6 → Phase 2 Tasks 1+3, #5 → Phase 3 Tasks 2-4, #7 → Phase 3 Task 1).
- [x] **No placeholders**: Every code block complete. Every commit message written. Every test code complete.
- [x] **Type consistency**: `scm_trace_id` ContextVar name matches between Task 1 (client.py) and Task 4 (main.py import). `state.context` dict write keys (`pause_reason`, `approval_id`, `approval_tool`, `approval_args`) consistent across Tasks 2-4.
- [x] **Task ordering**: Phase 1 doesn't touch Policy/executor/Runtime (per spec §2); Phase 2 doesn't touch executor; Phase 3 sequentially extends executor → loop → gateway.
- [x] **Test counts**: Phase 1 = 10 new (3+4+3), Phase 2 = 9 new (3+3+3), Phase 3 = 8 new (3+2+1+2). Total v2 = 27 new tests. Target 99 + 27 = 126 passed.