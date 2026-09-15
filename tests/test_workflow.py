"""Stage6 RED: 确定性Workflow，异常才走人审，Agent只做模糊判断。"""
from workflow.graph import run_expense_workflow


def test_small_amount_auto_approve():
    out = run_expense_workflow(
        expense={"id": "E001", "amount": 1200, "user_id": "u1"},
        policy_threshold=5000,
    )
    assert out["decision"] == "auto_approve"
    assert out["state"]["amount_ok"] is True
    assert "fetch" in out["trace"][0]


def test_large_amount_routes_to_human():
    out = run_expense_workflow(
        expense={"id": "E002", "amount": 6230, "user_id": "u1"},
        policy_threshold=5000,
    )
    assert out["decision"] == "human_review"
    assert out["state"]["need_human"] is True


def test_missing_invoice_routes_to_human():
    out = run_expense_workflow(
        expense={"id": "E003", "amount": 800, "user_id": "u1", "has_invoice": False},
        policy_threshold=5000,
    )
    assert out["decision"] == "human_review"
