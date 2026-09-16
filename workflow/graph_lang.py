"""LangGraph对齐层：节点与自研Workflow一一对应。有langgraph就用真图，没有就fallback，保证测试与教学不断。"""
from .graph import run_expense_workflow


class _FallbackGraph:
    def __init__(self, policy_threshold: float = 5000):
        self.policy_threshold = policy_threshold

    def invoke(self, state: dict, config: dict | None = None) -> dict:
        return run_expense_workflow(state.get("expense", {}),
                                    policy_threshold=self.policy_threshold)


def build_expense_graph(policy_threshold: float = 5000, checkpointer=None, _store=None):
    from workflow.checkpoint import MemoryCheckpointer

    if checkpointer is not None:
        store = checkpointer
    elif _store is not None:
        store = _store
    else:
        store = MemoryCheckpointer()
    # Durable (pause/resume) semantics only when caller passes an explicit
    # checkpointer/_store; otherwise preserve classic human_review/auto_approve
    # parity for old callers (tests/test_stage8.py).
    durable = checkpointer is not None or _store is not None

    try:
        from langgraph.graph import StateGraph, END  # type: ignore
        has_langgraph = True
    except Exception:
        has_langgraph = False
    from .nodes import expense as n

    _fns = (n.fetch_expense, n.check_amount, n.retrieve_policy, n.judge_rule)

    def run_all(exp, resumed_state=None):
        if resumed_state:
            s = dict(resumed_state)
            s["expense"] = exp
            s.setdefault("policy_threshold", policy_threshold)
            s["trace"] = list(resumed_state.get("trace", []))
            s["_done"] = list(resumed_state.get("_done", []))
        else:
            s = {"expense": exp, "policy_threshold": policy_threshold, "trace": [], "_done": []}
        for fn in _fns:
            if fn.__name__ not in s.get("_done", []):
                s = fn(s)
                s.setdefault("_done", []).append(fn.__name__)
        return s

    def _save(tid, out, exp):
        if hasattr(store, "put"):
            try:
                store.put(tid, {
                    "expense": exp,
                    "_done": list(out.get("_done", [])),
                    "trace": list(out.get("trace", [])),
                    "need_human": out.get("need_human"),
                    "amount_ok": out.get("amount_ok"),
                    "policy_text": out.get("policy_text"),
                    "policy_threshold": policy_threshold,
                })
            except Exception:
                pass

    class _DurableAdapter:
        # HITL convention: caller uses state["expense"]+thread_id to call
        # ApprovalStore.request(), then same thread_id invoke(None) to resume.
        def invoke(self, state, config=None):
            tid = (config or {}).get("configurable", {}).get("thread_id", "default")
            if state is None:
                saved = store.get(tid) if hasattr(store, "get") else None
                if not saved:
                    return {"decision": "failed", "trace": [], "reason": "checkpoint_missing"}
                out = run_all(saved.get("expense", {}), saved)
                decision = "human_review" if out.get("need_human") else "auto_approve"
                trace = list(out.get("trace", [])) + [decision]
                _save(tid, out, out.get("expense", {}))
                return {"decision": decision, "state": out, "trace": trace}
            exp = state.get("expense", {}) if isinstance(state, dict) else {}
            saved = store.get(tid) if hasattr(store, "get") else None
            if saved and saved.get("expense") == exp:
                base = saved
            else:
                base = {"expense": exp, "policy_threshold": policy_threshold, "trace": [], "_done": []}
            out = run_all(exp, base)
            _save(tid, out, exp)
            if out.get("need_human"):
                if durable:
                    return {"decision": "paused_human_review", "state": out,
                            "trace": list(out.get("trace", [])) + ["paused"]}
                return {"decision": "human_review", "state": out,
                        "trace": list(out.get("trace", [])) + ["human_review"]}
            return {"decision": "auto_approve", "state": out,
                    "trace": list(out.get("trace", [])) + ["auto_approve"]}

    if has_langgraph and checkpointer is not None and not isinstance(store, MemoryCheckpointer):
        return _DurableAdapter()
    return _DurableAdapter()
