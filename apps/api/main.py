"""Stage 1b Gateway - /chat routes into Agent Runtime."""
from fastapi import FastAPI
from pydantic import BaseModel

from agent.runtime import loop as _runtime_loop
from agent.runtime.state import AgentState
from agent.runtime.llm_planner import build_deepseek_planner, get_default_client
from infrastructure.pg.connector import get_connector
from infrastructure.pg.schema import ensure_schema
from observability.tracing import Tracer
from integrations.scm.client import scm_trace_id

app = FastAPI(title="Enterprise Agent Gateway", version="0.4.0")


class ChatRequest(BaseModel):
    message: str
    user_id: str = "u1"
    tenant_id: str = "t1"
    task_id: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "stage": 1}


@app.on_event("startup")
def _startup():
    try:
        ensure_schema(get_connector())
    except Exception as e:
        import warnings
        warnings.warn(f"memory schema init failed: {e}")


@app.post("/chat")
def chat(req: ChatRequest):
    # Stage 1b: Gateway → Runtime. 有Key走DeepSeek，无Key走echo降级。
    from agent.tools.executor import guarded_executor
    from security.policy import PolicyEngine
    from security.approval import ApprovalStore

    client, model = get_default_client()
    planner = build_deepseek_planner(client=client, model=model)
    st = AgentState(task=req.message)
    if req.task_id:
        st.task_id = req.task_id
    st.context["tenant_id"] = req.tenant_id

    # v2 Phase 3: HITL user 上下文（guarded_executor 需要 user 做 Policy 检查）
    user = {"tenant_id": req.tenant_id, "role": "admin", "user_id": req.user_id}
    st.context["user"] = user

    # v2 Phase 3: 开 trace + 把 trace_id 注入 contextvar 让 scm 客户端能埋点
    tracer = Tracer()
    tid = tracer.start_trace(req.message)
    st.context["trace_id"] = tid
    cv_token = scm_trace_id.set(tid)
    final = None
    try:
        final = _runtime_loop.run(
            st, planner=planner,
            executor=lambda plan, state: guarded_executor(
                plan, state, user=user,
                policy=PolicyEngine(),
                approvals=ApprovalStore(),
            ),
        )
    finally:
        status = final.status if final is not None else "unknown"
        tracer.end_trace(tid, status=status)
        scm_trace_id.reset(cv_token)

    at = final.context.get("agent_task") if final else None
    payload = {
        "reply": final.answer if final else "",
        "status": final.status if final else "failed",
        "user_id": req.user_id,
        "task_id": at.task_id if at else None,
        "trace_id": tid,
    }
    if at and final and final.status != "failed":
        payload["token_usage"] = dict(at.token_usage)
        payload["cost"] = at.cost

    # v2 Phase 3: HITL 闭环 — paused + need_approval 时把 aid 暴露给 caller
    if final and final.status == "paused" and final.context.get("pause_reason") == "need_approval":
        payload["approval_id"] = final.context.get("approval_id")
        payload["approval_tool"] = final.context.get("approval_tool")
        payload["approval_args"] = final.context.get("approval_args")

    return payload