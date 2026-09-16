"""Stage 1b Gateway - /chat routes into Agent Runtime."""
from fastapi import FastAPI
from pydantic import BaseModel

from agent.runtime.loop import run
from agent.runtime.state import AgentState
from agent.runtime.llm_planner import build_deepseek_planner, get_default_client
from infrastructure.pg.connector import get_connector
from infrastructure.pg.schema import ensure_schema

app = FastAPI(title="Enterprise Agent Gateway", version="0.1.0")


class ChatRequest(BaseModel):
    message: str
    user_id: str = "u1"
    tenant_id: str = "t1"


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
    client, model = get_default_client()
    planner = build_deepseek_planner(client=client, model=model)
    st = AgentState(task=req.message)
    st.context["tenant_id"] = req.tenant_id
    final = run(st, planner=planner)
    return {"reply": final.answer, "status": final.status, "user_id": req.user_id}
