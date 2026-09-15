"""Stage7 RED: Trace必须完整，Eval必须能量化。"""
from observability.tracing import Tracer
from evaluation.evaluator import evaluate_expense_cases


def test_tracer_records_full_chain_in_order():
    t = Tracer()
    tid = t.start_trace("订单5xx分析")
    t.log_event(tid, "planner", {"plan": "call metrics"})
    t.log_event(tid, "tool", {"tool": "metrics.get"})
    t.log_event(tid, "reflection", {"note": "5xx升高"})
    t.end_trace(tid, status="done")
    trace = t.get_trace(tid)
    assert [e["stage"] for e in trace["events"]] == ["planner", "tool", "reflection"]
    assert trace["status"] == "done"
    assert trace["latency_ms"] >= 0


def test_evaluator_scores_expense_workflow():
    cases = [
        {"expense": {"id": "E1", "amount": 1000}, "expected": "auto_approve"},
        {"expense": {"id": "E2", "amount": 6230}, "expected": "human_review"},
        {"expense": {"id": "E3", "amount": 800, "has_invoice": False}, "expected": "human_review"},
    ]
    report = evaluate_expense_cases(cases, policy_threshold=5000)
    assert report["task_success"] == 1.0
    assert report["total"] == 3
    assert report["policy_violation"] == 0.0
