"""Stage1 RED: 期望的 Agent Runtime API。先看失败，再实现。"""
from agent.runtime.state import AgentState
from agent.runtime.loop import run


def test_state_defaults():
    s = AgentState(task="查差旅报销")
    assert s.task == "查差旅报销"
    assert s.messages == []
    assert s.iteration == 0
    assert s.status == "pending"


def test_loop_with_mock_tools_runs_to_done():
    """Mock Planner/Executor: 第1轮查数据，第2轮结束。"""
    calls = []

    def fake_planner(state: AgentState):
        if state.iteration == 0:
            return {"action": "call_tool", "tool": "db.query", "args": {"sql": "select 1"}}
        return {"action": "finish", "answer": "发现1条异常"}

    def fake_executor(plan, state: AgentState):
        calls.append(plan["tool"])
        return {"tool": plan["tool"], "result": "row1"}

    s = AgentState(task="查报销")
    final = run(s, planner=fake_planner, executor=fake_executor, max_iterations=8)

    assert final.status == "done"
    assert "异常" in final.answer
    assert calls == ["db.query"]
    assert len(final.observations) == 1
