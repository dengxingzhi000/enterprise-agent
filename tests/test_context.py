def test_counter_returns_plausible_count():
    from agent.context.counter import get_counter
    c = get_counter()
    n = c.count("hello world")
    assert 1 <= n <= 6


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


def test_budget_fits_true_when_within_available():
    from agent.context.budget import TokenBudget
    b = TokenBudget(total=10, reserved_for_output=0)
    segs = [
        {"name": "system", "priority": 100, "tokens": 4, "text": "sys"},
    ]
    fits, usage, dropped = b.check(segs)
    assert fits is True
    assert usage == 4
    assert dropped == []


def test_budget_exact_fit_usage_equals_available():
    from agent.context.budget import TokenBudget
    b = TokenBudget(total=8, reserved_for_output=0)
    segs = [
        {"name": "system", "priority": 100, "tokens": 4, "text": "sys"},
        {"name": "task", "priority": 90, "tokens": 4, "text": "task"},
    ]
    fits, usage, dropped = b.check(segs)
    assert fits is True
    assert usage == 8
    assert dropped == []


def test_budget_empty_segments():
    from agent.context.budget import TokenBudget
    b = TokenBudget(total=10, reserved_for_output=0)
    fits, usage, dropped = b.check([])
    assert fits is True
    assert usage == 0
    assert dropped == []


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


def test_provider_priority_drop_order_conversation_before_tooltrace():
    from agent.context.providers import PRIORITY
    assert PRIORITY["conversation"] == 10
    assert PRIORITY["observation"] == 20
    assert PRIORITY["tooltrace"] == 70
    assert PRIORITY["task"] == 90
    assert PRIORITY["system"] == 100
    # rag tier range must sit between observation and tooltrace
    assert PRIORITY["observation"] < 40 <= 60 < PRIORITY["tooltrace"]
    # integration: tight budget drops conversation before tooltrace
    from agent.context.budget import TokenBudget
    from agent.context.providers import ConversationProvider, ToolTraceProvider
    cp = ConversationProvider()
    tp = ToolTraceProvider()
    c_segs = cp.collect({"messages": [{"role": "user", "content": "hi"}]})
    t_segs = tp.collect({"tool_calls": ["trace-data"]})
    for s in c_segs + t_segs:
        s["tokens"] = 4
    sys = {"name": "system", "priority": PRIORITY["system"], "tokens": 4, "text": "sys"}
    b = TokenBudget(total=8, reserved_for_output=0)
    fits, usage, dropped = b.check([sys] + c_segs + t_segs)
    assert fits is False
    assert dropped[0]["name"].startswith("conversation")


def test_rag_tiered_priority_low_score_dropped_first():
    from agent.context.providers import RagProvider
    from agent.context.budget import TokenBudget
    rp = RagProvider()
    segs = rp.collect({"rag": [{"text": "low", "score": 0.1}, {"text": "high", "score": 0.9}]})
    assert segs[0]["priority"] == 40 + int(0.1 * 20)
    assert segs[1]["priority"] == 40 + int(0.9 * 20)
    assert segs[0]["priority"] < segs[1]["priority"]
    # missing score defaults to 0.5 -> 50
    missing = rp.collect({"rag": [{"text": "no-score"}]})
    assert missing[0]["priority"] == 50
    # tight budget: low-score rag dropped first
    sys = {"name": "system", "priority": 100, "tokens": 4, "text": "sys"}
    for s in segs:
        s["tokens"] = 4
    b = TokenBudget(total=8, reserved_for_output=0)
    fits, usage, dropped = b.check([sys] + segs)
    assert fits is False
    assert dropped[0]["text"] == "low"


def test_truncation_keeps_system_role():
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    system_text = "SYSTEM_MARKER_" + "s" * 200
    task_text = "TASK_BODY_" + "t" * 500
    state = {"system": system_text, "task": task_text}
    asm = ContextAssembler(budget=TokenBudget(total=60, reserved_for_output=0))
    msgs, report = asm.assemble(state)
    assert msgs, "truncation path must still return msgs"
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == system_text


def test_assembler_skipped_providers_reported():
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    from agent.context.providers import SystemProvider, BaseProvider

    class BoomProvider(BaseProvider):
        name = "boom"
        priority = 5

        def collect(self, state):
            raise RuntimeError("boom")

    asm = ContextAssembler(
        budget=TokenBudget(total=800, reserved_for_output=100),
        providers=[SystemProvider(), BoomProvider()],
    )
    msgs, report = asm.assemble({"system": "sys-ok", "task": "t"})
    assert msgs, "assemble must still return msgs on provider exception"
    assert "skipped" in report
    assert "boom" in report["skipped"]
