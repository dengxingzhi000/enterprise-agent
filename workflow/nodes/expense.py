"""报销节点：全确定性代码，不调LLM。模糊case才由Agent复核（下一步）。"""


def fetch_expense(state: dict) -> dict:
    state.setdefault("trace", []).append("fetch")
    return state


def check_amount(state: dict) -> dict:
    amount = state["expense"].get("amount", 0)
    state["amount_ok"] = amount <= state.get("policy_threshold", 5000)
    state.setdefault("trace", []).append("check_amount")
    return state


def retrieve_policy(state: dict) -> dict:
    th = state.get("policy_threshold", 5000)
    state["policy_text"] = f"单笔超过{th}元需财务审批，需附发票。"
    state.setdefault("trace", []).append("retrieve_policy")
    return state


def judge_rule(state: dict) -> dict:
    has_invoice = state["expense"].get("has_invoice", True)
    state["need_human"] = (not state.get("amount_ok", True)) or (not has_invoice)
    state.setdefault("trace", []).append("judge_rule")
    return state
