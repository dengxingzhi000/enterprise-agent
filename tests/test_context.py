def test_counter_prefers_tiktoken_falls_back_heuristic():
    from agent.context.counter import get_counter, HeuristicCounter
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
