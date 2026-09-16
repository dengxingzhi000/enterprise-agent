"""Agent Loop: Task → Planner → Executor → Observation → Reflection → ... → Final"""
import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING
from .state import AgentState
from .planner import default_planner, default_executor

if TYPE_CHECKING:
    from agent.context.assembler import ContextAssembler


def run(
    state: AgentState,
    planner: Callable = default_planner,
    executor: Callable = default_executor,
    max_iterations: int = 8,
    assembler: "ContextAssembler | None" = None,
) -> AgentState:
    state.status = "running"
    while state.iteration < max_iterations:
        planner_state = state
        if assembler is not None:
            try:
                llm_messages, report = assembler.assemble(
                    {"task": state.task, "messages": state.messages,
                     "observations": state.observations, "tool_calls": state.tool_calls,
                     "rag": state.context.get("rag", []), "system": state.context.get("system", "")})
                state.context["context_report"] = report
                # planner view is read-only by contract; collections copied defensively
                planner_state = dataclasses.replace(
                    state, messages=[{"role": m.get("role", "user"), "content": m.get("content", "")}
                                     for m in llm_messages],
                    observations=list(state.observations),
                    tool_calls=list(state.tool_calls),
                    context=dict(state.context))
            except Exception:  # noqa: BLE001 - 组装失败退化现状
                planner_state = state
        plan = planner(planner_state)
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
