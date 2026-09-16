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
    def planner(state):
        return {"action": "call_tool", "tool": "noop", "args": {}}
    def executor(plan, state):
        return {"tool": "noop", "result": "x"}
    s = run(AgentState(task="x"), planner=planner, executor=executor, max_iterations=4)
    at = s.context.get("agent_task")
    assert at and at.status == "failed"
    assert at.history[-1]["reason"] == "max_iterations"


def test_loop_records_tokens_each_round():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    s = run(AgentState(task="x"),
            planner=lambda st: {"action": "finish", "answer": "ok"},
            executor=lambda p, st: None)
    at = s.context.get("agent_task")
    assert at.token_usage["input"] >= 1
    assert at.token_usage["output"] >= 0
    assert at.cost >= 0


def test_loop_planner_exception_marks_failed():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    def planner(state):
        raise RuntimeError("boom")
    def executor(plan, state):
        return {"tool": "noop", "result": "x"}
    s = AgentState(task="x")
    result = run(s, planner=planner, executor=executor)
    at = result.context.get("agent_task")
    assert at is not None
    assert at.status == "failed"
    assert at.history[-1]["reason"] == "planner_error"
    assert "planner_error" in result.answer
    assert "boom" in result.answer


def test_loop_executor_exception_marks_failed():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    def planner(state):
        return {"action": "call_tool", "tool": "noop", "args": {}}
    def executor(plan, state):
        raise RuntimeError("executor_boom")
    s = AgentState(task="x")
    result = run(s, planner=planner, executor=executor)
    at = result.context.get("agent_task")
    assert at is not None
    assert at.status == "failed"
    assert at.history[-1]["reason"] == "executor_error"
    assert "executor_error" in result.answer
    assert "executor_boom" in result.answer


def test_loop_records_tokens_on_unknown_action_failure():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    def planner(state):
        return {"action": "weird_unknown_action"}
    def executor(plan, state):
        return None
    s = run(AgentState(task="record-unknown"), planner=planner, executor=executor)
    at = s.context.get("agent_task")
    assert at.status == "failed"
    assert at.history[-1]["reason"] == "unknown_action"
    assert at.token_usage["input"] >= 1