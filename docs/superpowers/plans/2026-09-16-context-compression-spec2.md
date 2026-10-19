# Context Compression spec#2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 长任务超预算时把老段折成 extractive 摘要塞回窗口，原言保留 state；顺手闭环 Tracer.log_event。

**Architecture:** 新增 `agent/context/extract.py` 启发式摘要；`Provider.compress(segs, keep_recent)` 自治理；`assembler` 在 usage > trigger_ratio*available 时按层触发；`loop.py` 存 report 后用 `state.context.get("trace_id")` 调 `Tracer.log_event`（无则静默）。

**Tech Stack:** Python 3.12+, 无新硬依赖（extractive 零依赖，tiktoken 仍注释可选），pytest-asyncio auto。

---
### Task 1: extract 启发式摘要

**Files:**
- Create: `agent/context/extract.py`
- Test: `tests/test_context_compress.py`

- [ ] **Step 1: Write the failing test**

```python
def test_extract_returns_head_keywords_tail():
    from agent.context.extract import extract
    text = ("订单服务报错500。网关超时导致上游积压。ERROR traceId=abc123. "
            "中间穿插多次重试均失败。最终根因确认：Redis连接池耗尽。")
    out = extract(text, max_chars=200)
    assert "订单服务报错500" in out
    assert "Redis连接池耗尽" in out or "根因" in out
    assert len(out) <= 200


def test_extract_empty_or_stopwords_only():
    from agent.context.extract import extract
    assert extract("", max_chars=200) == "[empty-content]"
    assert extract("the a an of to", max_chars=200) == "[empty-content]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context_compress.py -v`
Expected: FAIL with "No module named 'agent.context.extract'"

- [ ] **Step 3: Write minimal implementation**

```python
"""agent/context/extract.py: 启发式 extractive 摘要（首句+关键词+尾句），零依赖。"""
import re

_SENT_SPLIT = re.compile(r"[.!?。！？\n]+")
_STOPWORDS = set("""a an the of to in on for with and or but is are was were be been being it its this that
                these those at by from as into about over under up down out off so than then too very
                我 你 他 她 它 我们 你们 他们 这 那 的 了 是 在 有 和 与 或 但 也 都 就 还 而 及 以
                对 上 下 出 入 到 被 让 把 给 用""".split())

def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    return parts or [text.strip()]

def _keywords(text: str, top: int = 5) -> list[str]:
    seen: list[str] = []
    for tok in text.split():
        t = tok.strip(".,;:!?()[]{}<>\"'`·、，。；：！？()【】《》 ")
        if len(t) < 3 or t.lower() in _STOPWORDS or not any(ch.isalnum() for ch in t):
            continue
        if t not in seen:
            seen.append(t)
        if len(seen) >= top:
            break
    return seen

def extract(text: str, max_chars: int = 200) -> str:
    if not text or not text.strip():
        return "[empty-content]"
    sents = _split_sentences(text)
    head = sents[0][:80]
    tail = sents[-1][:80] if len(sents) > 1 else ""
    kws = _keywords(text)
    parts = [head]
    if kws:
        parts.append("关键词:" + ",".join(kws))
    if tail and tail != head:
        parts.append(tail)
    out = "…".join(parts)
    if len(out) > max_chars:
        out = out[: max_chars - 3] + "..."
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_context_compress.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/context/extract.py tests/test_context_compress.py
git commit -m "feat: context extractive summary zero-dep"
```

### Task 2: Provider.compress 自治理

**Files:**
- Modify: `agent/context/providers.py`
- Modify: `agent/context/__init__.py`
- Test: `tests/test_context_compress.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_provider_compress_keeps_recent_and_summarizes_old():
    from agent.context.providers import ObservationProvider
    state = {"observations": [{"tool": f"t{i}", "result": f"r{i}"} for i in range(20)]}
    p = ObservationProvider(recent=10)  # 收集10条；keep_recent=5 压缩老5条
    collected = p.collect(state)
    kept, summary = p.compress(collected, keep_recent=5)
    assert len(kept) == 5
    assert summary is not None
    assert summary["name"] == "observation:summary"
    assert summary["text"].startswith("[")
    assert len(state["observations"]) == 20  # 原言保留
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context_compress.py::test_provider_compress_keeps_recent_and_summarizes_old -v`
Expected: FAIL with "'ObservationProvider' object has no attribute 'compress'"

- [ ] **Step 3: Write minimal implementation**

```python
# providers.py: add BaseProvider.compress + override for conv/obs; rest inherit no-op.
class BaseProvider:
    name = "base"
    priority = 0
    def collect(self, state: dict) -> list[dict]:
        raise NotImplementedError
    def compress(self, segs: list[dict], keep_recent: int) -> tuple[list[dict], dict | None]:
        if keep_recent <= 0 or keep_recent >= len(segs):
            return segs, None
        kept = segs[-keep_recent:]
        old_text = "\n".join(s.get("text", "") for s in segs[:-keep_recent])
        from .extract import extract
        return kept, {"name": f"{self.name}:summary", "priority": self.priority,
                      "text": extract(old_text)}
```

Keep ConversationProvider/ObservationProvider class signatures intact; their existing `recent` arg stays (controls `collect` window). New `compress(..., keep_recent=...)` is independent.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_context_compress.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/context/providers.py tests/test_context_compress.py
git commit -m "feat: provider self-managed compress with recent window"
```

### Task 3: assembler 触发压缩 + report.compressed

**Files:**
- Modify: `agent/context/assembler.py`
- Modify: `agent/context/__init__.py` (no-op)
- Modify: `.env.example`
- Test: `tests/test_context_compress.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_assembler_compresses_when_over_trigger_ratio():
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    big = "ERROR trace " * 50
    state = {"task": "查500", "system": "你是助手。",
             "messages": [{"role": "user", "content": f"msg-{i}"} for i in range(20)],
             "observations": [{"tool": "logs.tail", "result": big} for _ in range(20)]}
    asm = ContextAssembler(budget=TokenBudget(total=800, reserved_for_output=100),
                           trigger_ratio=0.5)  # 触发阈值 0.5
    msgs, report = asm.assemble(state)
    assert report["usage"] <= 800
    providers = {c["provider"] for c in report.get("compressed", [])}
    assert "observation" in providers or "conversation" in providers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context_compress.py::test_assembler_compresses_when_over_trigger_ratio -v`
Expected: FAIL with "unexpected keyword argument 'trigger_ratio'" or report missing "compressed"

- [ ] **Step 3: Write minimal implementation**

```python
# assembler.py: add trigger_ratio param; when usage > trigger_ratio*available, call provider.compress
class ContextAssembler:
    def __init__(self, budget=None, providers=None, counter=None,
                 trigger_ratio: float = 0.8,
                 conversation_keep_recent: int = 3,
                 observation_keep_recent: int = 5):
        self.budget = budget or TokenBudget()
        self.providers = providers if providers is not None else DEFAULT_PROVIDERS
        self.counter = counter or get_counter()
        self.counter_used = type(self.counter).__name__.replace("Counter", "").lower()
        self.trigger_ratio = trigger_ratio
        self.conv_keep = conversation_keep_recent
        self.obs_keep = observation_keep_recent

    def assemble(self, state: dict) -> tuple[list[dict], dict]:
        segs: list[dict] = []
        skipped: list[str] = []
        for p in self.providers:
            try:
                for s in p.collect(state) or []:
                    s = dict(s)
                    s["tokens"] = self.counter.count(s.get("text", ""))
                    s["idx"] = len(segs)
                    segs.append(s)
            except Exception:
                skipped.append(p.name)
        usage = sum(s["tokens"] for s in segs)
        compressed: list[dict] = []
        if usage > self.trigger_ratio * self.budget.available and self.budget.available > 0:
            by_layer: dict[str, list[dict]] = {}
            for s in segs:
                by_layer.setdefault(s["name"].split("[")[0].split(":")[0], []).append(s)
            layer_keep = {"conversation": self.conv_keep, "observation": self.obs_keep}
            new_segs: list[dict] = []
            for s in segs:
                layer = s["name"].split("[")[0].split(":")[0]
                if layer not in layer_keep or len(by_layer[layer]) <= layer_keep[layer]:
                    new_segs.append(s)
                    continue
                target_provider = next((p for p in self.providers if p.name == layer), None)
                if target_provider is None:
                    new_segs.append(s)
                    continue
                try:
                    kept, summary = target_provider.compress(by_layer[layer], layer_keep[layer])
                    if summary is None:
                        new_segs.append(s)
                        continue
                    summary = dict(summary)
                    summary["tokens"] = self.counter.count(summary.get("text", ""))
                    summary["idx"] = len(new_segs)
                    new_segs.append(summary)
                    for k in kept:
                        k = dict(k); k["idx"] = len(new_segs); new_segs.append(k)
                    compressed.append({"provider": layer,
                                       "before": len(by_layer[layer]),
                                       "after": 1 + len(kept),
                                       "kept": len(kept)})
                except Exception:
                    skipped.append(target_provider.name)
            segs = new_segs
        fits, usage2, dropped = self.budget.check(segs)
        dropped = [d for d in dropped if d.get("name") not in ("system", "task")]
        dropped_idx = {d["idx"] for d in dropped if "idx" in d}
        kept = [s for s in segs if s.get("idx") not in dropped_idx and not s.get("skipped")]
        total = sum(s["tokens"] for s in kept)
        if total > self.budget.available and kept:
            ordered = sorted(kept, key=lambda s: s.get("priority", 0))
            victim = ordered[0]
            over = total - self.budget.available
            cut = max(0, len(victim["text"]) - over * 4)
            victim["text"] = victim["text"][:cut]
            victim["tokens"] = self.counter.count(victim["text"])
            victim["truncated"] = True
        msgs: list[dict] = []
        if kept:
            sys_idx = next((i for i, s in enumerate(kept) if s.get("name") == "system"), 0)
            msgs.append({"role": "system", "content": kept[sys_idx]["text"]})
            for i, s in enumerate(kept):
                if i == sys_idx:
                    continue
                msgs.append({"role": "user", "content": s["text"]})
        report = {"usage": sum(s["tokens"] for s in kept), "dropped": [d["name"] for d in dropped],
                  "counter_used": "tiktoken" if self.counter_used.startswith("tiktoken") else "heuristic",
                  "fits": fits, "skipped": skipped, "compressed": compressed}
        return msgs, report
```

```text
# .env.example 追加：
# CONTEXT_COMPRESS_RATIO=0.8
# CONVERSATION_KEEP_RECENT=3
# OBSERVATION_KEEP_RECENT=5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_context.py tests/test_context_compress.py -v`
Expected: PASS (15 + 4 = 19 passed; spec#1 tests still green)

- [ ] **Step 5: Commit**

```bash
git add agent/context/assembler.py .env.example tests/test_context_compress.py
git commit -m "feat: assembler trigger compress + compressed report"
```

### Task 4: loop 闭环 Tracer.log_event

**Files:**
- Modify: `agent/runtime/loop.py`
- Test: `tests/test_context_compress.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_loop_emits_tracer_event_when_trace_id_present(monkeypatch):
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    from observability.tracing import Tracer
    asm = ContextAssembler(budget=TokenBudget(total=400, reserved_for_output=0))
    calls: list[dict] = []
    class FakeTracer(Tracer):
        def log_event(self, trace_id, stage, data):
            calls.append({"trace_id": trace_id, "stage": stage, "data": data})
    t = FakeTracer()
    tid = t.start_trace("t")
    s = AgentState(task="x"); s.context["trace_id"] = tid; s.context["system"] = "你是助手。"
    s.context["rag"] = []
    def planner(state):
        return {"action": "finish", "answer": "ok"}
    run(s, planner=planner, assembler=asm, executor=lambda p, st: None)
    assert any(c["stage"] == "context_assemble" and c["trace_id"] == tid for c in calls)


def test_loop_silent_when_no_trace_id():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    asm = ContextAssembler(budget=TokenBudget(total=400, reserved_for_output=0))
    calls = {"n": 0}
    def planner(state):
        return {"action": "finish", "answer": "ok"}
    s = AgentState(task="x")
    # wrap build-in tracer via monkeypatch would be heavier; assert no exception raised when no trace_id
    import observability.tracing as tracing
    orig = tracing.Tracer.log_event
    def counting(self, trace_id, stage, data):
        calls["n"] += 1; return orig(self, trace_id, stage, data)
    tracing.Tracer.log_event = counting
    try:
        run(s, planner=planner, assembler=asm, executor=lambda p, st: None)
        assert calls["n"] == 0
    finally:
        tracing.Tracer.log_event = orig
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context_compress.py::test_loop_emits_tracer_event_when_trace_id_present tests/test_context_compress.py::test_loop_silent_when_no_trace_id -v`
Expected: FAIL with "No log_event call observed" / calls["n"] not 0

- [ ] **Step 3: Write minimal implementation**

```python
# loop.py: after state.context["context_report"]=report, emit via Tracer only if trace_id present
from observability.tracing import Tracer
_T = Tracer()  # shared default; tests can monkeypatch Tracer.log_event

# inside the assembler try-block, after `state.context["context_report"] = report`:
            trace_id = state.context.get("trace_id")
            if trace_id:
                try:
                    _T.log_event(trace_id, "context_assemble", report)
                except Exception:  # noqa: BLE001 - 可观测失败不阻断
                    pass
```

(Replace the existing assembler try-block lines 22-37 with the extended version; keep `except Exception` for assembly fallback as-is.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q`
Expected: PASS (58 + 6 = 64, all green)

- [ ] **Step 5: Commit**

```bash
git add agent/runtime/loop.py tests/test_context_compress.py
git commit -m "feat: loop emits Tracer log_event for context assemble"
```