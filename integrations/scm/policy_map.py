"""SCM读写分级：读=allow，写=need_approval，未知=deny。"""
SCM_READ_TOOLS = {"scm.order.get", "scm.inventory.query", "scm.sales.report"}
SCM_WRITE_TOOLS = {"scm.purchase.create", "scm.order.cancel", "scm.stock.adjust"}


def scm_policy_decision(tool: str) -> str:
    if tool in SCM_READ_TOOLS:
        return "allow"
    if tool in SCM_WRITE_TOOLS:
        return "need_approval"
    return "deny"
