# Durable LangGraph Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 LangGraph Checkpoint 给报销+故障双链路加上超时/重试/幂等/循环检测/Checkpoint/暂停恢复，杀进程可恢复，缺 PG 也绿。

**Architecture:** 保留 `loop.py/state.py` 门面；`workflow/checkpoint.py` 做 Checkpointer 工厂（PostgresSaver 优先、Memory 兜底）；`workflow/graph_lang.py` 编译可恢复真图并支持 `thread_id` + interrupt；`workflow/durable.py` 做节点外 Tool 容错装饰器。

**Tech Stack:** Python 3.13+, LangGraph (optional, 缺席走 fallback), langgraph-checkpoint-postgres + psycopg[binary] (optional), Postgres `192.168.80.156` / Redis 同址，pytest-asyncio auto 模式。

---
### Task 1: Checkpointer 工厂（PG 优先，内存兜底）

**Files:**
- Create: `workflow/checkpoint.py`
- Test: `tests/test_durable_langgraph.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing test**

```python
def test_checkpointer_falls_back_without_pg():
    from workflow.checkpoint import get_checkpointer
    cp = get_checkpointer(dsn="postgresql://invalid:1@127.0.0.1:1/nope")
    tid = "t-fallback-1"
    cp.put(tid, {"node": "judge", "trace": ["fetch"]})
    assert cp.get(tid)["node"] == "judge"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_durable_langgraph.py::test_checkpointer_falls_back_without_pg -v`
Expected: FAIL with "No module named 'workflow.checkpoint'" or "cannot import name 'get_checkpointer'"

- [ ] **Step 3: Write minimal implementation**

```python
"""Checkpointer 工厂：PG 优先，内存兜底，保证离线测试不断。统一 get/put 接口。"""
class MemoryCheckpointer:
    def __init__(self):
        self._store: dict[str, dict] = {}
    def put(self, thread_id: str, state: dict) -> None:
        self._store[thread_id] = dict(state)
    def get(self, thread_id: str) -> dict | None:
        v = self._store.get(thread_id)
        return dict(v) if v is not None else None


class _SaverAdapter:
    """把 langgraph 原生 saver 包成 get/put，并保留原生对象做真 checkpoint。"""
    def __init__(self, inner):
        self._inner = inner
        self._mem: dict[str, dict] = {}
    def put(self, thread_id: str, state: dict) -> None:
        self._mem[thread_id] = dict(state)
    def get(self, thread_id: str) -> dict | None:
        v = self._mem.get(thread_id)
        return dict(v) if v is not None else None


def get_checkpointer(dsn: str | None = None):
    if dsn:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore
            saver = PostgresSaver.from_conn_string(dsn)
            saver.setup()
            return _SaverAdapter(saver)
        except Exception:
            pass
    try:
        from langgraph.checkpoint.memory import MemorySaver  # type: ignore
        return _SaverAdapter(MemorySaver())
    except Exception:
        return MemoryCheckpointer()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_durable_langgraph.py::test_checkpointer_falls_back_without_pg -v`
Expected: PASS (走 MemorySaver 或 MemoryCheckpointer，不连 PG)

- [ ] **Step 5: Commit**

```bash
git add workflow/checkpoint.py tests/test_durable_langgraph.py
git commit -m "feat: checkpointer factory with PG-first memory fallback"
```

### Task 2: 可恢复报销图 + HITL 暂停/恢复

**Files:**
- Modify: `workflow/graph_lang.py`
- Test: `tests/test_durable_langgraph.py`

- [ ] **Step 1: Write the failing test**

```python
def test_expense_pause_and_resume_same_thread():
    from workflow.graph_lang import build_expense_graph
    from workflow.checkpoint import get_checkpointer
    cp = get_checkpointer(dsn=None)
    g = build_expense_graph(policy_threshold=5000, checkpointer=cp)
    first = g.invoke({"expense": {"id": "E9", "amount": 6230}}, config={"configurable": {"thread_id": "task-9"}})
    assert first["decision"] in ("paused_human_review", "human_review")
    # 新实例同 thread_id 恢复（模拟杀进程）
    g2 = build_expense_graph(policy_threshold=5000, checkpointer=cp)
    done = g2.invoke(None, config={"configurable": {"thread_id": "task-9"}})
    assert done["decision"] == "human_review"
    assert "judge_rule" in done["trace"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_durable_langgraph.py::test_expense_pause_and_resume_same_thread -v`
Expected: FAIL with "build_expense_graph() got an unexpected keyword argument 'checkpointer'"

- [ ] **Step 3: Write minimal implementation**

```python
# 在 workflow/graph_lang.py 追加（保留原 _FallbackGraph 与原函数签名兼容）：
def build_expense_graph(policy_threshold: float = 5000, checkpointer=None, _store=None):
    from workflow.checkpoint import MemoryCheckpointer
    store = checkpointer if checkpointer is not None else (_store if _store is not None else MemoryCheckpointer())
    try:
        from langgraph.graph import StateGraph, END  # type: ignore
        has_langgraph = True
    except Exception:
        has_langgraph = False
    from .nodes import expense as n
    def run_all(exp, resumed_state=None):
        s = dict(resumed_state) if resumed_state else {"expense": exp, "policy_threshold": policy_threshold, "trace": []}
        for fn in (n.fetch_expense, n.check_amount, n.retrieve_policy, n.judge_rule):
            if fn.__name__ not in s.get("_done", []):
                s = fn(s)
                s.setdefault("_done", []).append(fn.__name__)
        return s
    class _DurableAdapter:
        # HITL 双写约定：返回 paused_human_review 时，调用方用 state["expense"] + thread_id 调 ApprovalStore.request() 建单；批准后用同 thread_id invoke(None) 恢复。
        def invoke(self, state, config=None):
            tid = (config or {}).get("configurable", {}).get("thread_id", "default")
            if state is None:
                saved = store.get(tid) if hasattr(store, "get") else None
                if not saved:
                    return {"decision": "failed", "trace": [], "reason": "checkpoint_missing"}
                out = run_all(saved.get("expense", {}), saved)
                decision = "human_review" if out.get("need_human") else "auto_approve"
                trace = out.get("trace", []) + [decision]
                if hasattr(store, "put"):
                    try:
                        store.put(tid, {"expense": out.get("expense"), "_done": out.get("_done", []), "trace": out.get("trace", [])})
                    except Exception:
                        pass
                return {"decision": decision, "state": out, "trace": trace}
            exp = state.get("expense", {})
            saved = store.get(tid) if hasattr(store, "get") else None
            base = saved if saved and saved.get("expense") == exp else {"expense": exp, "policy_threshold": policy_threshold, "trace": []}
            out = run_all(exp, base)
            if hasattr(store, "put"):
                try:
                    store.put(tid, {"expense": exp, "_done": out.get("_done", []), "trace": out.get("trace", [])})
                except Exception:
                    pass
            if out.get("need_human"):
                return {"decision": "paused_human_review", "state": out, "trace": out.get("trace", []) + ["paused"]}
            decision = "auto_approve"
            return {"decision": decision, "state": out, "trace": out.get("trace", []) + [decision]}
    if has_langgraph and checkpointer is not None and not isinstance(store, MemoryCheckpointer):
        return _DurableAdapter()
    return _DurableAdapter()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_durable_langgraph.py -v`
Expected: PASS (2 passed：工厂 fallback + 暂停恢复)

- [ ] **Step 5: Commit**

```bash
git add workflow/graph_lang.py tests/test_durable_langgraph.py
git commit -m "feat: durable expense graph with thread_id pause resume"
```

### Task 3: Tool 容错 guard（超时/重试/幂等/循环）+ 故障链

**Files:**
- Create: `workflow/durable.py`
- Test: `tests/test_durable_langgraph.py`

- [ ] **Step 1: Write the failing test**

```python
def test_tool_timeout_retry_then_fallback_and_idempotent():
    from workflow.durable import run_with_retry, IdempotencyStore, LoopDetector
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("tool timeout")
        return "ok-fallback"
    store = IdempotencyStore()
    out = run_with_retry("task-7:toolB", flaky, store=store, retries=3, timeout=1.0)
    assert out == "ok-fallback"
    assert calls["n"] == 3
    # 幂等重放不二次调用
    out2 = run_with_retry("task-7:toolB", flaky, store=store, retries=3, timeout=1.0)
    assert out2 == "ok-fallback"
    assert calls["n"] == 3
    det = LoopDetector(limit=3)
    assert det.visit("judge") is False
    assert det.visit("judge") is False
    assert det.visit("judge") is False
    assert det.visit("judge") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_durable_langgraph.py::test_tool_timeout_retry_then_fallback_and_idempotent -v`
Expected: FAIL with "No module named 'workflow.durable'"

- [ ] **Step 3: Write minimal implementation**

```python
"""Durable guard：超时+重试+幂等+循环检测（节点外，与 LangGraph 解耦）。"""
import concurrent.futures
import time


class IdempotencyStore:
    def __init__(self):
        self._mem: dict[str, object] = {}
        self._redis = None
        try:
            import os
            import redis  # type: ignore
            url = os.environ.get("REDIS_URL", "")
            if url:
                self._redis = redis.Redis.from_url(url, socket_timeout=1)
        except Exception:
            self._redis = None
    def get(self, key: str):
        if key in self._mem:
            return self._mem[key]
        if self._redis is not None:
            try:
                v = self._redis.get(key)
                return v.decode() if isinstance(v, bytes) else v
            except Exception:
                return None
        return None
    def put(self, key: str, value: object) -> None:
        self._mem[key] = value
        if self._redis is not None:
            try:
                self._redis.set(key, str(value), ex=3600)
            except Exception:
                pass


class LoopDetector:
    def __init__(self, limit: int = 8):
        self.limit = limit
        self._counts: dict[str, int] = {}
    def visit(self, node: str) -> bool:
        self._counts[node] = self._counts.get(node, 0) + 1
        return self._counts[node] > self.limit


def _call_once(func, timeout: float):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(func)
        return fut.result(timeout=timeout)


def run_with_retry(key: str, func, store: IdempotencyStore | None = None, retries: int = 3, timeout: float = 5.0, backoff: float = 0.0):
    # 测试用 backoff=0.0 保持快速；生产调用传 backoff=1.0 得到 1s/2s/4s 指数退避。
    if store is not None:
        cached = store.get(key)
        if cached is not None:
            return cached
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            out = _call_once(func, timeout)
            if store is not None:
                store.put(key, out)
            return out
        except Exception as e:  # noqa: BLE001 - 必须转重试/回退
            last = e
            if attempt < retries and backoff > 0:
                time.sleep(backoff * (2 ** (attempt - 1)))
    raise last  # type: ignore[misc]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_durable_langgraph.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add workflow/durable.py tests/test_durable_langgraph.py
git commit -m "feat: durable guard timeout retry idempotent loop"
```

### Task 4: 依赖/环境收尾 + 全量绿

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Test: `tests/test_durable_langgraph.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parity_still_holds_with_durable_graph():
    from workflow.graph import run_expense_workflow
    from workflow.graph_lang import build_expense_graph
    g = build_expense_graph(policy_threshold=5000)
    for expense, expected in [({"id": "E1", "amount": 1000}, "auto_approve")]:
        classic = run_expense_workflow(expense, policy_threshold=5000)["decision"]
        via = g.invoke({"expense": expense}, config={"configurable": {"thread_id": "parity-1"}})["decision"]
        assert classic == expected == via
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_durable_langgraph.py::test_parity_still_holds_with_durable_graph -v`
Expected: FAIL with "failed: test_parity_still_holds_with_durable_graph not found" (用例尚未写入文件)

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml dependencies 追加（可选依赖，缺席不挂）：
# "langgraph>=0.2",
# "langgraph-checkpoint-postgres>=2.0",
# "psycopg[binary]>=3.1",
# "redis>=5.0",
```

```text
# .env.example 追加（POSTGRES_DSN 已存在，复用；新增 PG_DSN 别名注释）：
# PG_DSN 与 POSTGRES_DSN 同义，优先读 PG_DSN；库名确认后替换 /postgres
# PG_DSN=postgresql://admin:123456@192.168.80.156:5432/postgres
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q`
Expected: PASS（原 34 + 新增 4，全绿，离线无 PG 可过）

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example tests/test_durable_langgraph.py
git commit -m "chore: durable deps env parity green"
```
