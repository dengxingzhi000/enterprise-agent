# Context Assembly + Budget Implementation Plan (v0.3.0 spec#1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 loop 进 LLM 的窗口加上计数+预算+优先级截断，长任务 token 有界且答案不变，质量门 measurable。

**Architecture:** 新建 `agent/context/` 包（counter/budget/providers/assembler 四文件一次到位）；`loop.run(..., assembler=None)` 可选注入，无注入退化现状；`evaluator.context_quality_gate` 做基线对比。九层注册表占位，spec#1 只填 6 个基础 provider。

**Tech Stack:** Python 3.12+, tiktoken（硬依赖，CI 可装；BPE 下不到时运行时降启发式），pytest-asyncio auto，Tracer 可观测 report。

---
### Task 1: 计数器 + 预算

**Files:**
- Create: `agent/context/__init__.py`
- Create: `agent/context/counter.py`
- Create: `agent/context/budget.py`
- Test: `tests/test_context.py`

- [ ] **Step 1: Write the failing test**

```python
def test_counter_prefers_tiktoken_falls_back_heuristic():
    from agent.context.counter import get_counter, HeuristicCounter
    c = get_counter()
    n = c.count("hello world")
    assert 1 <= n <= 6  # tiktoken(cl100k)=2, heuristic=11//4=2, 区间防版本漂移


def test_counter_fallback_when_tiktoken_missing(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    from agent.context import counter as counter_mod
    import importlib
    importlib.reload(counter_mod)
    try:
        c = counter_mod.get_counter()
        assert isinstance(c, counter_mod.HeuristicCounter)
        assert c.count("abcd") == 1
    finally:
        importlib.reload(counter_mod)


def test_budget_drop_order_low_priority_first():
    from agent.context.budget import TokenBudget
    b = TokenBudget(total=10, reserved_for_output=0)
    segs = [
        {"name": "system", "priority": 100, "tokens": 4, "text": "sys"},
        {"name": "conv_old", "priority": 10, "tokens": 4, "text": "old"},
        {"name": "obs_old", "priority": 20, "tokens": 4, "text": "obs"},
    ]
    fits, usage, dropped = b.check(segs)
    assert fits is False
    assert dropped[0]["name"] == "conv_old"
    assert usage == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context.py -v`
Expected: FAIL with "No module named 'agent.context'"

- [ ] **Step 3: Write minimal implementation**

```python
"""agent/context/__init__.py"""
from .counter import get_counter, HeuristicCounter, TiktokenCounter  # noqa: F401
from .budget import TokenBudget  # noqa: F401
```

```python
"""agent/context/counter.py: 精确优先，启发兜底，保证离线不断。"""
import warnings


class EncodingUnavailable(Exception):
    pass


class BaseCounter:
    def count(self, text: str) -> int:
        raise NotImplementedError


class HeuristicCounter(BaseCounter):
    def count(self, text: str) -> int:
        return max(1, len(text) // 4)


class TiktokenCounter(BaseCounter):
    def __init__(self, encoding_name: str = "cl100k_base"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding_name)
        except Exception as e:  # noqa: BLE001 - 缺包或BPE下不到都转统一异常
            raise EncodingUnavailable(str(e))
    def count(self, text: str) -> int:
        return max(1, len(self._enc.encode(text)))


def get_counter() -> BaseCounter:
    try:
        return TiktokenCounter()
    except EncodingUnavailable as e:
        warnings.warn(f"tiktoken unavailable, fallback heuristic: {e}")
        return HeuristicCounter()
```

```python
"""agent/context/budget.py"""
class TokenBudget:
    def __init__(self, total: int = 8000, reserved_for_output: int = 1000):
        self.total = total if total and total > 0 else 10 ** 9
        self.reserved = reserved_for_output or 0
    @property
    def available(self) -> int:
        return max(0, self.total - self.reserved)
    def check(self, segments: list[dict]) -> tuple[bool, int, list[dict]]:
        usage = sum(s.get("tokens", 0) for s in segments)
        if usage <= self.available:
            return True, usage, []
        dropped: list[dict] = []
        kept = sorted(segments, key=lambda s: s.get("priority", 0))
        while kept and sum(s.get("tokens", 0) for s in kept) > self.available:
            dropped.append(kept.pop(0))
        return False, usage, dropped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_context.py -v`
Expected: PASS (3 passed; tiktoken 未装时第一条走 heuristic 照样绿)

- [ ] **Step 5: Commit**

```bash
git add agent/context/__init__.py agent/context/counter.py agent/context/budget.py tests/test_context.py
git commit -m "feat: context counter with tiktoken-first heuristic fallback + budget"
```

### Task 2: Providers + Assembler

**Files:**
- Create: `agent/context/providers.py`
- Create: `agent/context/assembler.py`
- Test: `tests/test_context.py` (append, keep Task 1 green)

- [ ] **Step 1: Write the failing test**

```python
def test_assembler_bounds_long_task_and_reports():
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    state = {
        "task": "分析订单服务500错误",
        "system": "你是企业运维助手。",
        "messages": [{"role": "user", "content": f"msg-{i}"} for i in range(20)],
        "observations": [{"tool": "logs.tail", "result": "ERROR " * 50} for _ in range(20)],
        "rag": [{"text": "SOP: 500先查网关", "score": 0.9}],
    }
    asm = ContextAssembler(budget=TokenBudget(total=800, reserved_for_output=100))
    msgs, report = asm.assemble(state)
    assert report["usage"] <= 800
    assert report["dropped"], "超预算必须有丢弃记录"
    assert any(m["role"] == "system" for m in msgs)
    assert report["counter_used"] in ("tiktoken", "heuristic")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context.py::test_assembler_bounds_long_task_and_reports -v`
Expected: FAIL with "No module named 'agent.context.assembler'" or "cannot import name 'ContextAssembler'"

- [ ] **Step 3: Write minimal implementation**

```python
"""agent/context/providers.py: 6 基础 provider，memory深度版留 spec#2。丢弃顺序 conv→obs→rag-low→tooltrace（数字越小越先丢；system/task按名保留）"""
PRIORITY = {"system": 100, "task": 90, "rag": 60, "observation": 20, "conversation": 10, "tooltrace": 70}


class BaseProvider:
    name = "base"
    priority = 0
    def collect(self, state: dict) -> list[dict]:
        raise NotImplementedError


class SystemProvider(BaseProvider):
    name, priority = "system", PRIORITY["system"]
    def collect(self, state):
        t = state.get("system", "你是企业运维助手。")
        return [{"name": self.name, "priority": self.priority, "text": t}]


class TaskProvider(BaseProvider):
    name, priority = "task", PRIORITY["task"]
    def collect(self, state):
        return [{"name": self.name, "priority": self.priority, "text": state.get("task", "")}]


class ConversationProvider(BaseProvider):
    name, priority = "conversation", PRIORITY["conversation"]
    def __init__(self, recent: int = 5):
        self.recent = recent
    def collect(self, state):
        out = []
        for i, m in enumerate(state.get("messages", [])[-self.recent:]):
            out.append({"name": f"conversation[{i}]", "priority": self.priority,
                        "text": f"{m.get('role')}: {m.get('content')}"})
        return out


class ObservationProvider(BaseProvider):
    name, priority = "observation", PRIORITY["observation"]
    def __init__(self, recent: int = 10):
        self.recent = recent
    def collect(self, state):
        out = []
        for i, o in enumerate(state.get("observations", [])[-self.recent:]):
            out.append({"name": f"observation[{i}]", "priority": self.priority,
                        "text": f"{o.get('tool')}: {o.get('result')}"})
        return out


class RagProvider(BaseProvider):
    name, priority = "rag", PRIORITY["rag"]  # 上限60；实际按score分档 40+int(score*20) clamp 40..60，缺失按0.5→50，单条坏分仅跳过该条
    def collect(self, state):
        import math
        out = []
        for r in state.get("rag", []):
            if not isinstance(r, dict):
                continue
            try:
                score = float(r.get("score", 0.5))
                if not math.isfinite(score):
                    score = 0.5
            except (TypeError, ValueError, OverflowError):
                score = 0.5
            tier = max(40, min(60, 40 + int(score * 20)))
            out.append({"name": self.name, "priority": tier, "text": r.get("text", "")})
        return out


class ToolTraceProvider(BaseProvider):
    name, priority = "tooltrace", PRIORITY["tooltrace"]
    def collect(self, state):
        return [{"name": self.name, "priority": self.priority, "text": str(t)}
                for t in state.get("tool_calls", [])]


DEFAULT_PROVIDERS = [SystemProvider(), TaskProvider(), RagProvider(),
                     ObservationProvider(), ConversationProvider(), ToolTraceProvider()]
```

```python
"""agent/context/assembler.py"""
from .budget import TokenBudget
from .counter import get_counter
from .providers import DEFAULT_PROVIDERS


class ContextAssembler:
    def __init__(self, budget: TokenBudget | None = None, providers=None, counter=None):
        self.budget = budget or TokenBudget()
        self.providers = providers if providers is not None else DEFAULT_PROVIDERS
        self.counter = counter or get_counter()
        self.counter_used = type(self.counter).__name__.replace("Counter", "").lower()
    def assemble(self, state: dict) -> tuple[list[dict], dict]:
        segs: list[dict] = []
        for p in self.providers:
            try:
                for s in p.collect(state) or []:
                    s = dict(s)
                    s["tokens"] = self.counter.count(s.get("text", ""))
                    segs.append(s)
            except Exception:  # noqa: BLE001 - 单层故障跳过，不阻断
                segs.append({"name": f"{p.name}:skip", "priority": 0, "tokens": 0,
                             "text": "", "skipped": True})
        fits, usage, dropped = self.budget.check(segs)
        kept_names = {d["name"] for d in dropped}
        kept = [s for s in segs if s["name"] not in kept_names and not s.get("skipped")]
        # 仍超：截最低优先级保留段尾部
        total = sum(s["tokens"] for s in kept)
        if total > self.budget.available and kept:
            kept.sort(key=lambda s: s.get("priority", 0))
            over = total - self.budget.available
            victim = kept[0]
            cut = max(0, len(victim["text"]) - over * 4)
            victim["text"] = victim["text"][:cut]
            victim["tokens"] = self.counter.count(victim["text"])
            victim["truncated"] = True
        msgs = [{"role": "system", "content": kept[0]["text"]}] if kept else []
        for s in kept[1:]:
            msgs.append({"role": "user", "content": s["text"]})
        report = {"usage": sum(s["tokens"] for s in kept), "dropped": [d["name"] for d in dropped],
                  "counter_used": "tiktoken" if self.counter_used.startswith("tiktoken") else "heuristic",
                  "fits": fits}
        return msgs, report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_context.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/context/providers.py agent/context/assembler.py tests/test_context.py
git commit -m "feat: context providers and priority-drop assembler"
```

### Task 3: loop 接线 + 质量门 + 依赖/环境

**Files:**
- Modify: `agent/runtime/loop.py`
- Modify: `evaluation/evaluator.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Test: `tests/test_context.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_loop_with_assembler_bounded_and_answer_preserved():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    calls = {"n": 0}
    def planner(state):
        calls["n"] += 1
        if calls["n"] <= 15:
            return {"action": "call_tool", "tool": "logs.tail", "args": {}}
        return {"action": "finish", "answer": "根因：网关超时"}
    def executor(plan, state):
        return {"tool": plan["tool"], "result": "ERROR trace " * 100}
    s1 = run(AgentState(task="查500"), planner=planner, executor=executor)
    calls["n"] = 0
    asm = ContextAssembler(budget=TokenBudget(total=1200, reserved_for_output=200))
    s2 = run(AgentState(task="查500"), planner=planner, executor=executor, assembler=asm)
    assert s1.answer == s2.answer == "根因：网关超时"
    _, report = asm.assemble({"task": s2.task, "messages": s2.messages,
                              "observations": s2.observations, "tool_calls": s2.tool_calls})
    assert report["usage"] <= 1200


def test_quality_gate_baseline_vs_managed():
    from evaluation.evaluator import context_quality_gate
    out = context_quality_gate(baseline={"decision": "human_review", "usage": 10000},
                               managed={"decision": "human_review", "usage": 6000})
    assert out["pass"] is True
    assert out["usage_ratio"] == 0.6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context.py::test_loop_with_assembler_bounded_and_answer_preserved -v`
Expected: FAIL with "run() got an unexpected keyword argument 'assembler'"

- [ ] **Step 3: Write minimal implementation**

```python
# agent/runtime/loop.py: 签名加 assembler=None；每轮用组装后窗口喂 planner（state 全量保留给 executor/checkpoint）
def run(state, planner=default_planner, executor=default_executor, max_iterations=8, assembler=None):
    import dataclasses
    state.status = "running"
    while state.iteration < max_iterations:
        planner_state = state
        if assembler is not None:
            try:
                llm_messages, report = assembler.assemble(
                    {"task": state.task, "messages": state.messages,
                     "observations": state.observations, "tool_calls": state.tool_calls,
                     "rag": state.context.get("rag", []), "system": state.context.get("system", "")})
                state.context["context_report"] = report
                planner_state = dataclasses.replace(
                    state, messages=[{"role": m.get("role", "user"), "content": m.get("content", "")}
                                     for m in llm_messages])
            except Exception:  # noqa: BLE001 - 组装失败退化现状
                planner_state = state
        plan = planner(planner_state)
        state.plan = plan
        if plan.get("action") == "finish":
            state.answer = plan.get("answer", "")
            state.status = "done"
            break
        if plan.get("action") == "call_tool":
            obs = executor(plan, state)
            state.observations.append(obs)
            state.messages.append({"role": "observation", "content": str(obs)})
            state.iteration += 1
            continue
        state.status = "failed"
        state.answer = f"unknown action: {plan.get('action')}"
        break
    else:
        state.status = "failed"
        state.answer = "max_iterations exceeded"
    return state
```

```python
# evaluation/evaluator.py 追加：
def context_quality_gate(baseline: dict, managed: dict, max_ratio: float = 0.7) -> dict:
    b_use, m_use = baseline.get("usage", 0) or 1, managed.get("usage", 0)
    ratio = m_use / b_use
    ok = managed.get("decision") == baseline.get("decision") and ratio <= max_ratio
    return {"pass": ok, "usage_ratio": ratio,
            "decision_match": managed.get("decision") == baseline.get("decision")}
```

```toml
# pyproject.toml dependencies 追加一行：
# "tiktoken>=0.7",
```

```text
# .env.example 追加：
# CONTEXT_BUDGET_TOKENS=8000
# CONTEXT_RESERVED_TOKENS=1000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q`
Expected: PASS（43 + 6，新旧全绿；tiktoken 未装时计数测试走 fallback 照样绿）

- [ ] **Step 5: Commit**

```bash
git add agent/runtime/loop.py evaluation/evaluator.py pyproject.toml .env.example tests/test_context.py
git commit -m "feat: loop context wiring with quality gate"
```
