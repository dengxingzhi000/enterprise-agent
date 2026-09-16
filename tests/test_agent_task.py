"""AgentTask + 状态机 wrapper tests (spec#4 Task 1)."""
import pytest

from agent.runtime.state import AgentState
from agent.runtime.agent_task import AgentTask, InvalidTransition


def test_agent_task_from_state_auto_uuid_and_pending():
    s = AgentState(task="x")
    t = AgentTask.from_state(s, tenant_id="t1")
    assert t.task_id and len(t.task_id) >= 32
    assert t.tenant_id == "t1"
    assert t.status == "pending"
    assert t.history == []
    assert t.state is s
    assert t.token_usage == {"input": 0, "output": 0, "total": 0}
    assert t.cost == 0.0


def test_agent_task_transition_legal_and_illegal():
    t = AgentTask.from_state(AgentState(task="x"))
    t.transition("running")
    t.transition("paused")
    t.transition("running")
    t.transition("done")
    assert [h["to"] for h in t.history] == ["running", "paused", "running", "done"]
    assert t.status == "done"
    with pytest.raises(InvalidTransition):
        t.transition("running")


def test_agent_task_history_capped_at_50():
    t = AgentTask.from_state(AgentState(task="x"))
    t.transition("running")
    for _ in range(60):
        if t.status == "running":
            t.transition("paused")
        else:
            t.transition("running")
    assert len(t.history) == 50
    assert t.history[0]["from"] == "running"
    assert t.history[-1]["from"] == "paused"


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