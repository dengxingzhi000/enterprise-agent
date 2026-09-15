"""Stage2 RED: Tool Registry + 运维四件套。"""
from agent.runtime.state import AgentState
from agent.runtime.loop import run
from agent.tools.registry import Tool, Registry
from agent.tools.builtin import build_default_registry
from agent.tools.executor import registry_executor


def test_registry_register_and_call():
    reg = Registry()
    reg.register(Tool(name="echo.hello", description="hi", func=lambda args: "hello"))
    assert "echo.hello" in reg.list_tools()
    assert reg.call("echo.hello", {}) == "hello"


def test_ops_four_tools_exist_and_return_data():
    reg = build_default_registry()
    for name in ["db.query", "metrics.get", "logs.search", "git.diff"]:
        assert name in reg.list_tools(), name
    assert "5xx" in str(reg.call("metrics.get", {"service": "order"}))
    assert "ERROR" in str(reg.call("logs.search", {"keyword": "5xx"}))


def test_loop_uses_registry_executor_end_to_end():
    reg = build_default_registry()

    def planner(state: AgentState):
        if state.iteration == 0:
            return {"action": "call_tool", "tool": "metrics.get", "args": {"service": "order"}}
        return {"action": "finish", "answer": f"根因分析: {state.observations[0]['result']}"}

    def executor(plan, state: AgentState):
        return registry_executor(plan, state, registry=reg)

    final = run(AgentState(task="订单5xx升高"), planner=planner, executor=executor)
    assert final.status == "done"
    assert "5xx" in final.answer
