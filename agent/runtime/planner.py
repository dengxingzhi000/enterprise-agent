"""Planner / Executor 默认实现。Stage1先给可注入的最小版本，真LLM在Stage1后半段接。"""
from typing import Callable
from .state import AgentState


def default_planner(state: AgentState) -> dict:
    # 占位：没有LLM时直接结束，避免死循环
    return {"action": "finish", "answer": f"echo: {state.task}"}


def default_executor(plan: dict, state: AgentState) -> dict:
    tool = plan.get("tool", "noop")
    state.tool_calls.append(plan)
    return {"tool": tool, "result": "noop-result"}
