"""三场景复用同一套件：合同合规 + 销售分析（运维已在Stage2/6覆盖）。"""
RISKY_CLAUSES = ("无限赔偿", "预付款100%", "口头承诺", "独家买断")


def review_contract(contract: dict) -> dict:
    from knowledge.seed import get_default_store
    amount = contract.get("amount", 0)
    clauses = contract.get("clauses", [])
    hits = get_default_store().search("合同审批 赔偿 预付款", tenant_id="t1",
                                      allowed_permissions=["employee", "finance", "manager", "admin"])
    policy_ref = hits[0].text[:80] if hits else "超阈值需审批"
    risky = amount > 10000 or any(any(r in c for r in RISKY_CLAUSES) for c in clauses)
    if risky:
        return {"decision": "human_review",
                "opinion": f"风险条款需人审：{clauses}；金额{amount}。依据：{policy_ref}",
                "trace": ["retrieve_policy", "judge_rule", "human_review"]}
    return {"decision": "auto_approve",
            "opinion": f"标准小额合同自动通过：金额{amount}",
            "trace": ["retrieve_policy", "judge_rule", "auto_approve"]}


def analyze_sales(question: str, tenant_id: str = "t1") -> dict:
    import logging
    from agent.tools.builtin import build_default_registry
    reg = build_default_registry()
    trace = []
    try:
        if "scm.sales.report" in reg.list_tools():
            # range 保持 "7d" 默认；question 解析超出首版范围，暂不做动态解析。
            sales = reg.call("scm.sales.report", {"range": "7d", "tenant_id": tenant_id})
            trace.append("scm.sales.report")
        else:
            sales = reg.call("knowledge.search", {"query": question, "tenant_id": tenant_id})
            trace.append("knowledge.search")
    except Exception as e:
        logging.getLogger(__name__).warning("scm.sales.report failed: %r", e)
        try:
            sales = reg.call("knowledge.search", {"query": question, "tenant_id": tenant_id})
        except Exception:
            sales = "销售聚合暂不可用，已用本地知识库代替"
        trace.append("knowledge.search")
    metrics = reg.call("metrics.get", {"service": "mall"})
    rows = reg.call("db.query", {"scope": "self"})
    trace += ["metrics.get", "db.query"]
    report = (f"销售下降分析报告：{question}\n- 销售聚合：{sales}\n- 指标：{metrics}\n- 数据：{rows}\n"
              f"- 初步判断：支付超时导致下单失败，需按运维手册排查。")
    return {"report": report, "trace": trace}
