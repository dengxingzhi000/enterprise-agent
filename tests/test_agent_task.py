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