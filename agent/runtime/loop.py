"""Agent Loop: Task → Planner → Executor → Observation → Reflection → ... → Final"""
import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING
from observability.tracing import Tracer
from .state import AgentState
from .planner import default_planner, default_executor
from .agent_task import AgentTask
from .counter import get_counter, get_pricing

if TYPE_CHECKING:
    from agent.context.assembler import ContextAssembler


def _wrap(state_or_task) -> AgentTask:
    if isinstance(state_or_task, AgentTask):
        return state_or_task
    return AgentTask.from_state(state_or_task)


def _emit_status(task: AgentTask, reason: str) -> None:
    trace_id = task.state.context.get("trace_id")
    if not trace_id:
        return
    tracer = Tracer._shared or Tracer()
    try:
        data = {"task_id": task.task_id,
                "from": task.history[-1]["from"] if task.history else None,
                "to": task.status, "reason": reason}
        tracer.log_event(trace_id, "task_status_changed", data)
    except Exception:
        pass


def _record_tokens(task: AgentTask, messages: list[dict], output_text: str = "") -> None:
    try:
        c = get_counter()
        counting = [{"role": "user", "content": task.state.task or ""}]
        for m in (messages or []):
            if not (isinstance(m, dict) and m.get("content") == task.state.task):
                counting.append(m)
        usage = c.count_messages(counting)
        if usage["input"]:
            task.record_tokens(usage["input"], 0)
            p = get_pricing("deepseek-chat")
            task.cost += (usage["input"] / 1000) * p.input_per_1k
        if output_text:
            out = c.count_messages([{"role": "assistant", "content": output_text}])
            if out["input"]:
                task.record_tokens(0, out["input"])
                p = get_pricing("deepseek-chat")
                task.cost += (out["input"] / 1000) * p.output_per_1k
    except Exception:
        pass


def run(
    state: AgentState,
    planner: Callable = default_planner,
    executor: Callable = default_executor,
    max_iterations: int = 8,
    assembler: "ContextAssembler | None" = None,
) -> AgentState:
    task = _wrap(state)
    inner = task.state if isinstance(state, AgentTask) else state
    task.transition("running", "loop_start")
    _emit_status(task, "loop_start")
    inner.status = "running"
    llm_messages = inner.messages
    while inner.iteration < max_iterations:
        planner_state = inner
        if assembler is not None:
            try:
                llm_messages, report = assembler.assemble(
                    {"task": inner.task, "messages": inner.messages,
                     "observations": inner.observations, "tool_calls": inner.tool_calls,
                     "rag": inner.context.get("rag", []),
                     "system": inner.context.get("system", ""),
                     "tenant_id": inner.context.get("tenant_id", "default")})
                inner.context["context_report"] = report
                trace_id = inner.context.get("trace_id")
                if trace_id:
                    try:
                        _T = Tracer._shared or Tracer()
                        _T.log_event(trace_id, "context_assemble", report)
                    except Exception:
                        pass
                planner_state = dataclasses.replace(
                    inner,
                    messages=[{"role": m.get("role", "user"), "content": m.get("content", "")}
                             for m in llm_messages],
                    observations=list(inner.observations),
                    tool_calls=list(inner.tool_calls),
                    context=dict(inner.context))
            except Exception:
                planner_state = inner
        try:
            plan = planner(planner_state)
        except Exception as e:
            inner.plan = None
            inner.status = "failed"
            inner.answer = f"planner_error: {e}"
            _record_tokens(task, llm_messages or inner.messages, "")
            task.transition("failed", "planner_error")
            _emit_status(task, "planner_error")
            inner.context["agent_task"] = task
            return inner
        inner.plan = plan

        if plan.get("action") == "finish":
            inner.answer = plan.get("answer", "")
            inner.status = "done"
            _record_tokens(task, llm_messages if assembler else inner.messages, inner.answer)
            task.transition("done", "finish_received")
            _emit_status(task, "finish_received")
            break

        if plan.get("action") == "call_tool":
            _record_tokens(task, llm_messages if assembler else inner.messages, "")
            try:
                obs = executor(plan, inner)
            except Exception as e:
                inner.status = "failed"
                inner.answer = f"executor_error: {e}"
                _record_tokens(task, llm_messages or inner.messages, "")
                task.transition("failed", "executor_error")
                _emit_status(task, "executor_error")
                inner.context["agent_task"] = task
                return inner
            inner.observations.append(obs)
            inner.messages.append({"role": "observation", "content": str(obs)})

            # v2 Phase 3: HITL pause — need_approval observation breaks the loop.
            obs_result = str(obs.get("result", ""))
            if obs_result.startswith("need approval"):
                inner.status = "paused"
                task.transition("paused", "need_approval")
                _emit_status(task, "need_approval")
                break

            inner.iteration += 1
            continue

        inner.status = "failed"
        inner.answer = f"unknown action: {plan.get('action')}"
        _record_tokens(task, llm_messages or inner.messages, "")
        task.transition("failed", "unknown_action")
        _emit_status(task, "unknown_action")
        break
    else:
        inner.status = "failed"
        inner.answer = "max_iterations exceeded"
        _record_tokens(task, llm_messages or inner.messages, "")
        task.transition("failed", "max_iterations")
        _emit_status(task, "max_iterations")

    inner.context["agent_task"] = task
    return inner
