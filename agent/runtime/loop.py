"""Agent Loop: Task → Planner → Executor → Observation → Reflection → ... → Final"""
from collections.abc import Callable
from .state import AgentState
from .planner import default_planner, default_executor


def run(
    state: AgentState,
    planner: Callable = default_planner,
    executor: Callable = default_executor,
    max_iterations: int = 8,
) -> AgentState:
    state.status = "running"
    while state.iteration < max_iterations:
        plan = planner(state)
        state.plan = plan

        if plan.get("action") == "finish":
            state.answer = plan.get("answer", "")
            state.status = "done"
            break

        if plan.get("action") == "call_tool":
            obs = executor(plan, state)
            state.observations.append(obs)
            # Reflection最小版：记入messages，下一轮planner能看到进展
            state.messages.append({"role": "observation", "content": str(obs)})
            state.iteration += 1
            continue

        # 未知action → 失败，避免无限循环
        state.status = "failed"
        state.answer = f"unknown action: {plan.get('action')}"
        break
    else:
        state.status = "failed"
        state.answer = "max_iterations exceeded"

    return state
