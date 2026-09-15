"""LangGraph对齐层：节点与自研Workflow一一对应。有langgraph就用真图，没有就fallback，保证测试与教学不断。"""
from .graph import run_expense_workflow


class _FallbackGraph:
    def __init__(self, policy_threshold: float = 5000):
        self.policy_threshold = policy_threshold

    def invoke(self, state: dict) -> dict:
        return run_expense_workflow(state.get("expense", {}),
                                    policy_threshold=self.policy_threshold)


def build_expense_graph(policy_threshold: float = 5000):
    try:
        from langgraph.graph import StateGraph, END  # type: ignore
    except Exception:
        return _FallbackGraph(policy_threshold)

    from .nodes import expense as n

    def fetch(s: dict) -> dict:
        return n.fetch_expense(dict(s))

    def check(s: dict) -> dict:
        s = dict(s)
        s.setdefault("policy_threshold", policy_threshold)
        return n.check_amount(s)

    def policy(s: dict) -> dict:
        return n.retrieve_policy(dict(s))

    def judge(s: dict) -> dict:
        return n.judge_rule(dict(s))

    def route(s: dict) -> str:
        return "human" if s.get("need_human") else "auto"

    builder = StateGraph(dict)
    for name, fn in [("fetch", fetch), ("check", check), ("policy", policy), ("judge", judge)]:
        builder.add_node(name, fn)
    builder.set_entry_point("fetch")
    builder.add_edge("fetch", "check")
    builder.add_edge("check", "policy")
    builder.add_edge("policy", "judge")
    builder.add_conditional_edges("judge", route, {"human": END, "auto": END})
    graph = builder.compile()

    class _Adapter:
        def invoke(self, state: dict) -> dict:
            s = dict(state)
            s.setdefault("policy_threshold", policy_threshold)
            s.setdefault("trace", [])
            out = graph.invoke(s)
            decision = "human_review" if out.get("need_human") else "auto_approve"
            trace = out.get("trace", []) + [decision]
            return {"decision": decision, "state": out, "trace": trace}

    return _Adapter()
