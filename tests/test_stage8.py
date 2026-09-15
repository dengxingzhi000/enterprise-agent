"""Stage8 RED: 自研Workflow == LangGraph语义；三场景复用同一套件。"""
from workflow.graph import run_expense_workflow
from workflow.graph_lang import build_expense_graph
from workflow.scenarios import review_contract, analyze_sales


def test_langgraph_parity_with_handrolled():
    g = build_expense_graph(policy_threshold=5000)
    for expense, expected in [
        ({"id": "E1", "amount": 1000}, "auto_approve"),
        ({"id": "E2", "amount": 6230}, "human_review"),
    ]:
        classic = run_expense_workflow(expense, policy_threshold=5000)["decision"]
        via_graph = g.invoke({"expense": expense})["decision"]
        assert classic == expected == via_graph


def test_contract_scenario_flags_risky_clause():
    out = review_contract(
        contract={"id": "C1", "amount": 20000, "clauses": ["无限赔偿", "预付款100%"]},
    )
    assert out["decision"] == "human_review"
    assert "赔偿" in out["opinion"]


def test_contract_small_clean_auto_passes():
    out = review_contract(contract={"id": "C2", "amount": 3000, "clauses": ["标准条款"]})
    assert out["decision"] == "auto_approve"


def test_sales_analysis_combines_tools():
    out = analyze_sales(question="这个月销售额为什么下降")
    assert "报告" in out["report"] or "下降" in out["report"]
    assert "metrics.get" in out["trace"] or "db.query" in out["trace"]
