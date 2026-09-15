"""报销Workflow：START→fetch→check→policy→judge→分叉。"""
from .nodes import expense as n


def run_expense_workflow(expense: dict, policy_threshold: float = 5000) -> dict:
    state: dict = {"expense": expense, "policy_threshold": policy_threshold, "trace": []}
    for fn in (n.fetch_expense, n.check_amount, n.retrieve_policy, n.judge_rule):
        state = fn(state)
    if state.get("need_human"):
        state["trace"].append("human_review")
        return {"decision": "human_review", "state": state, "trace": state["trace"]}
    state["trace"].append("auto_approve")
    return {"decision": "auto_approve", "state": state, "trace": state["trace"]}
