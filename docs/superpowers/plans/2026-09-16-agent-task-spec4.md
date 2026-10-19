# AgentTask Wiring spec#4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 AgentState 套一层 AgentTask 包装——task_id/status/checkpoint_id/token_usage/cost 全在外层；老 AgentState + 老测试不动。

**Architecture:** 新 `agent/runtime/agent_task.py`（AgentTask dataclass + 状态机 + history + from_state 包装）+ `agent/runtime/counter.py`（Tiktoken/Heuristic Counter + Pricing）+ `agent/runtime/status.py`（ALLOWED_TRANSITIONS）；loop.run 自动 wrap，每轮 Counter + record_tokens + transition + Tracer 事件。

**Tech Stack:** Python 3.12+, uuid (stdlib), dataclasses, tiktoken (注释可选)，pytest-asyncio auto。

---
### Task 1: AgentTask + 状态机

**Files:**
- Create: `agent/runtime/status.py`
- Create: `agent/runtime/agent_task.py`
- Test: `tests/test_agent_task.py`

- [ ] **Step 1: Write the failing test**

```python
def test_agent_task_from_state_auto_uuid_and_pending():
    from agent.runtime.state import AgentState
    from agent.runtime.agent_task import AgentTask
    s = AgentState(task="x")
    t = AgentTask.from_state(s, tenant_id="t1")
    assert t.task_id and len(t.task_id) >= 32  # uuid4
    assert t.tenant_id == "t1"
    assert t.status == "pending"
    assert t.history == []
    assert t.state is s
    assert t.token_usage == {"input": 0, "output": 0, "total": 0}
    assert t.cost == 0.0


def test_agent_task_transition_legal_and_illegal():
    from agent.runtime.agent_task import AgentTask, InvalidTransition
    from agent.runtime.state import AgentState
    t = AgentTask.from_state(AgentState(task="x"))
    t.transition("running")
    t.transition("paused")
    t.transition("running")
    t.transition("done")
    assert [h["to"] for h in t.history] == ["running", "paused", "running", "done"]
    assert t.status == "done"
    import pytest
    with pytest.raises(InvalidTransition):
        t.transition("running")  # 终态不可再转
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_task.py -v`
Expected: FAIL with "No module named 'agent.runtime.agent_task'"

- [ ] **Step 3: Write minimal implementation**

```python
"""agent/runtime/status.py: 状态机允许转换表。"""
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending":   {"running", "cancelled"},
    "running":   {"paused", "done", "failed", "cancelled"},
    "paused":    {"running", "cancelled"},
    "done":      set(),
    "failed":    set(),
    "cancelled": set(),
}
```

```python
"""agent/runtime/agent_task.py: AgentTask 包装层 + 状态机 + history。"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .state import AgentState
from .status import ALLOWED_TRANSITIONS


class AgentTaskError(Exception):
    pass


class InvalidTransition(AgentTaskError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentTask:
    task_id: str
    tenant_id: str
    state: AgentState
    status: str = "pending"
    checkpoint_id: str | None = None
    token_usage: dict = field(default_factory=lambda: {"input": 0, "output": 0, "total": 0})
    cost: float = 0.0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    history: list[dict] = field(default_factory=list)

    @classmethod
    def from_state(cls, state: AgentState, tenant_id: str = "default") -> "AgentTask":
        tid = getattr(state, "task_id", None) or str(uuid.uuid4())
        return cls(task_id=tid, tenant_id=tenant_id, state=state)

    def transition(self, to: str, reason: str = "") -> None:
        allowed = ALLOWED_TRANSITIONS.get(self.status, set())
        if to not in allowed:
            raise InvalidTransition(f"{self.status} -> {to} not allowed")
        prev = self.status
        self.status = to
        self.updated_at = _now()
        self.history.append({"from": prev, "to": to, "reason": reason, "ts": self.updated_at})

    def attach_checkpoint(self, thread_id: str) -> None:
        if not thread_id:
            raise AgentTaskError("thread_id required")
        self.checkpoint_id = thread_id
        self.updated_at = _now()

    def record_tokens(self, input_n: int, output_n: int) -> None:
        if input_n < 0 or output_n < 0:
            raise ValueError("token counts must be >= 0")
        self.token_usage["input"] += input_n
        self.token_usage["output"] += output_n
        self.token_usage["total"] += input_n + output_n
        self.updated_at = _now()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "checkpoint_id": self.checkpoint_id,
            "token_usage": dict(self.token_usage),
            "cost": self.cost,
            "answer": self.state.answer,
            "history": list(self.history),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_task.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/runtime/status.py agent/runtime/agent_task.py tests/test_agent_task.py
git commit -m "feat: agent task wrapper with state machine and history"
```

### Task 2: Counter + Pricing

**Files:**
- Create: `agent/runtime/counter.py`
- Test: `tests/test_agent_task.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_counter_count_messages_returns_input_and_output():
    from agent.runtime.counter import get_counter, HeuristicCounter
    c = get_counter()
    out = c.count_messages([{"role": "system", "content": "你是助手"},
                            {"role": "user", "content": "你好"}])
    assert out["input"] >= 1
    assert out["output"] == 0  # 现有 messages 只算 input


def test_counter_falls_back_heuristic_when_tiktoken_missing(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    from agent.runtime import counter as cmod
    import importlib
    importlib.reload(cmod)
    try:
        c = cmod.get_counter()
        assert isinstance(c, cmod.HeuristicCounter)
        out = c.count_messages([{"role": "user", "content": "abcd"}])
        assert out["input"] >= 1
    finally:
        importlib.reload(cmod)


def test_pricing_accumulates_cost():
    from agent.runtime.counter import get_pricing, Pricing
    p = get_pricing("deepseek-chat")
    assert isinstance(p, Pricing)
    cost = (100 / 1000) * p.input_per_1k + (50 / 1000) * p.output_per_1k
    assert cost > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_task.py::test_counter_count_messages_returns_input_and_output -v`
Expected: FAIL with "No module named 'agent.runtime.counter'"

- [ ] **Step 3: Write minimal implementation**

```python
"""agent/runtime/counter.py: Token Counter + Pricing（Tiktoken 优先 / 启发兜底）。"""
import os
import warnings
from dataclasses import dataclass


class EncodingUnavailable(Exception):
    pass


@dataclass
class Pricing:
    model: str
    input_per_1k: float
    output_per_1k: float


class BaseCounter:
    def count_messages(self, messages: list[dict]) -> dict:
        raise NotImplementedError


class HeuristicCounter(BaseCounter):
    def count_messages(self, messages: list[dict]) -> dict:
        total = 0
        for m in messages:
            text = (m.get("content") or "") if isinstance(m, dict) else str(m)
            total += max(1, len(text) // 4)
        return {"input": total, "output": 0}


class TiktokenCounter(BaseCounter):
    def __init__(self, encoding_name: str = "cl100k_base"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding_name)
        except Exception as e:  # noqa: BLE001
            raise EncodingUnavailable(str(e))

    def count_messages(self, messages: list[dict]) -> dict:
        total = 0
        for m in messages:
            text = (m.get("content") or "") if isinstance(m, dict) else str(m)
            total += len(self._enc.encode(text))
        return {"input": total, "output": 0}


def get_counter() -> BaseCounter:
    try:
        return TiktokenCounter()
    except EncodingUnavailable as e:
        warnings.warn(f"tiktoken unavailable, fallback heuristic: {e}")
        return HeuristicCounter()


_DEFAULT_PRICING: dict[str, Pricing] = {
    "deepseek-chat": Pricing("deepseek-chat", 0.001, 0.002),
}


def get_pricing(model: str) -> Pricing:
    """返回 Pricing；未定价模型返回 0 + warn。"""
    if model in _DEFAULT_PRICING:
        return _DEFAULT_PRICING[model]
    inp = float(os.environ.get("MODEL_PRICING_INPUT", "0") or "0")
    out = float(os.environ.get("MODEL_PRICING_OUTPUT", "0") or "0")
    if inp > 0 or out > 0:
        return Pricing(model, inp, out)
    warnings.warn(f"no pricing for model={model}; cost will be 0")
    return Pricing(model, 0.0, 0.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_task.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/runtime/counter.py tests/test_agent_task.py
git commit -m "feat: token counter and pricing with heuristic fallback"
```

### Task 3: loop 接线（auto wrap + 状态机 + Counter + Tracer）

**Files:**
- Modify: `agent/runtime/loop.py`
- Test: `tests/test_agent_task.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_loop_wraps_agent_state_and_emits_status_changes():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    from observability.tracing import Tracer
    calls: list[dict] = []
    class Fake(Tracer):
        def log_event(self, trace_id, stage, data):
            calls.append({"trace_id": trace_id, "stage": stage, "data": data})
    t = Fake(); tid = t.start_trace("t")
    s = AgentState(task="x"); s.context["trace_id"] = tid
    run(s, planner=lambda st: {"action": "finish", "answer": "ok"},
        executor=lambda p, st: None)
    assert any(c["stage"] == "task_status_changed" and c["trace_id"] == tid for c in calls)


def test_loop_max_iterations_marks_failed():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    from agent.runtime.agent_task import AgentTask
    s = AgentState(task="x")
    calls = {"n": 0}
    def planner(state):
        calls["n"] += 1
        return {"action": "call_tool", "tool": "noop", "args": {}}
    def executor(plan, state):
        return {"tool": "noop", "result": "x"}
    s2 = run(s, planner=planner, executor=executor, max_iterations=4)
    task = s2.state if isinstance(s2, AgentTask) else s2
    # loop.run returns AgentState (legacy contract) → status carried via s.context["agent_task"].status
    # But after wrap, the returned value is the same wrapper; verify via history.
    # Direct check: s2.history if wrapped
    if isinstance(s2, AgentTask):
        assert s2.status == "failed"
        assert s2.history[-1]["reason"] == "max_iterations"
    else:
        # legacy contract returns AgentState; agent_task stored on s.context
        at = s2.context.get("agent_task")
        assert at and at.status == "failed" and at.history[-1]["reason"] == "max_iterations"


def test_loop_records_tokens_each_round():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    from agent.runtime.agent_task import AgentTask
    s = AgentState(task="x")
    s2 = run(s, planner=lambda st: {"action": "finish", "answer": "ok"},
             executor=lambda p, st: None)
    at = s2 if isinstance(s2, AgentTask) else s2.context.get("agent_task")
    assert at.token_usage["input"] >= 1
    assert at.token_usage["output"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_task.py::test_loop_wraps_agent_state_and_emits_status_changes -v`
Expected: FAIL — `log_event` not called for task_status_changed OR wrapper not created

- [ ] **Step 3: Write minimal implementation**

Modify `agent/runtime/loop.py`:

```python
# Top-of-file imports: add
from .agent_task import AgentTask
from .counter import get_counter, get_pricing

# New helper at module top:
def _wrap(task_or_state) -> AgentTask:
    if isinstance(task_or_state, AgentTask):
        return task_or_state
    return AgentTask.from_state(task_or_state)

def _emit_status(tracer_state_ref, task: AgentTask, reason: str):
    trace_id = task.state.context.get("trace_id")
    if not trace_id:
        return
    try:
        from observability.tracing import Tracer
        Tracer().log_event(trace_id, "task_status_changed",
                          {"task_id": task.task_id, "from": task.history[-1]["from"] if task.history else None,
                           "to": task.status, "reason": reason})
    except Exception:
        pass

def _record_round_tokens(task: AgentTask, planner_view_messages: list[dict], output_text: str):
    c = get_counter()
    usage = c.count_messages(planner_view_messages)
    task.record_tokens(usage["input"], 0)
    p = get_pricing("deepseek-chat")
    task.cost += (usage["input"] / 1000) * p.input_per_1k
    # output: best-effort count of answer text
    if output_text:
        out = c.count_messages([{"role": "assistant", "content": output_text}])
        task.record_tokens(0, out["input"])
        task.cost += (out["input"] / 1000) * p.output_per_1k
```

Modify the `run` function signature to accept `task_or_state` (rename `state` parameter to `task_or_state` for clarity, but keep backward compat by accepting `state` keyword too — easiest: keep param name `state` and call it `task_or_state` internally; existing tests use positional arg, so rename is fine if you update tests OR keep param `state`):

```python
def run(state, planner=default_planner, executor=default_executor, max_iterations=8,
        assembler=None):
    task = _wrap(state)
    # legacy compat: callers expecting AgentState back get the inner state; new callers can use task.state
    # To keep existing tests untouched (they expect AgentState), return task but add `.state` shim:
    task.status = "running"
    task.history.append({"from": "pending", "to": "running", "reason": "loop_start", "ts": task.updated_at})
    task.updated_at = ... # use _now()
    _emit_status(None, task, "loop_start")
    inner = task.state
    inner.status = "running"
    # ... existing loop body uses `inner` as state; Counter + transition at finish
    while inner.iteration < max_iterations:
        planner_state = inner
        if assembler is not None:
            try:
                llm_messages, report = assembler.assemble(...)
                inner.context["context_report"] = report
                planner_state = dataclasses.replace(...)
            except Exception:
                planner_state = inner
        plan = planner(planner_state)
        inner.plan = plan
        if plan.get("action") == "finish":
            inner.answer = plan.get("answer", "")
            inner.status = "done"
            task.transition("done", "finish_received")
            _emit_status(None, task, "finish_received")
            _record_round_tokens(task, llm_messages if assembler else inner.messages, inner.answer)
            break
        if plan.get("action") == "call_tool":
            # record tokens pre-tool-call
            _record_round_tokens(task, llm_messages if assembler else inner.messages, "")
            obs = executor(plan, inner)
            inner.observations.append(obs)
            inner.messages.append({"role": "observation", "content": str(obs)})
            inner.iteration += 1
            continue
        inner.status = "failed"
        inner.answer = f"unknown action: {plan.get('action')}"
        task.transition("failed", "unknown_action")
        _emit_status(None, task, "unknown_action")
        break
    else:
        inner.status = "failed"
        inner.answer = "max_iterations exceeded"
        task.transition("failed", "max_iterations")
        _emit_status(None, task, "max_iterations")

    # Backward compat: existing tests expect return value to behave like AgentState.
    # Cleanest: stash task on inner.context and return inner (AgentState) so legacy tests pass.
    inner.context["agent_task"] = task
    return inner
```

IMPORTANT: tests/test_agent_task.py expects `s2` to BE AgentTask OR to carry it via `s.context["agent_task"]`. The compat shim above returns `inner` (AgentState) so existing tests stay green; new tests look up via `context["agent_task"]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q`
Expected: PASS (78 + 5 new = 83, all green)

- [ ] **Step 5: Commit**

```bash
git add agent/runtime/loop.py tests/test_agent_task.py
git commit -m "feat: loop wires agent task wrap counter status and tracer"
```

### Task 4: API + env 收尾

**Files:**
- Modify: `apps/api/main.py`
- Modify: `.env.example`
- Test: `tests/test_agent_task.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_api_returns_task_id_and_status():
    from fastapi.testclient import TestClient
    from apps.api.main import app
    c = TestClient(app)
    r = c.post("/chat", json={"message": "x"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("done", "failed")
    assert "task_id" in body
    assert body["task_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_task.py::test_api_returns_task_id_and_status -v`
Expected: FAIL — current /chat returns `{reply, status, user_id}` without `task_id`

- [ ] **Step 3: Write minimal implementation**

Modify `apps/api/main.py`: include task_id + token_usage + cost in /chat output. Accept optional `task_id` request field. Use the new loop return (which stashes AgentTask on state.context["agent_task"]).

```python
class ChatRequest(BaseModel):
    message: str
    user_id: str = "u1"
    tenant_id: str = "t1"
    task_id: str | None = None


@app.post("/chat")
def chat(req: ChatRequest):
    client, model = get_default_client()
    planner = build_deepseek_planner(client=client, model=model)
    s = AgentState(task=req.message)
    s.context["tenant_id"] = req.tenant_id
    if req.task_id:
        s.context["requested_task_id"] = req.task_id
    final = run(s, planner=planner)
    at = final.context.get("agent_task")
    payload = {"reply": final.answer, "status": final.status, "user_id": req.user_id}
    if at:
        payload["task_id"] = at.task_id
        payload["token_usage"] = at.token_usage
        payload["cost"] = at.cost
    return payload
```

Also bump `app.version = "0.4.0"` (string only, not enforced).

`.env.example` append:
```text
# MODEL_PRICING_INPUT=0.001
# MODEL_PRICING_OUTPUT=0.002
# AGENT_STATUS_HISTORY=50
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q`
Expected: PASS (83 + 1 = 84, all green)

- [ ] **Step 5: Commit**

```bash
git add apps/api/main.py .env.example tests/test_agent_task.py
git commit -m "feat: api chat exposes task id token usage cost + env"
```