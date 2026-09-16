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
