"""最小Eval：跑基准集，打出 TaskSuccess / PolicyViolation。"""
import time


def evaluate_expense_cases(cases: list[dict], policy_threshold: float = 5000) -> dict:
    from workflow.graph import run_expense_workflow
    passed = 0
    violations = 0
    t0 = time.perf_counter()
    for c in cases:
        out = run_expense_workflow(c["expense"], policy_threshold=policy_threshold)
        if out["decision"] == c["expected"]:
            passed += 1
        # 违规：在超标时自动通过
        amount = c["expense"].get("amount", 0)
        if out["decision"] == "auto_approve" and amount > policy_threshold:
            violations += 1
    total = len(cases) or 1
    return {
        "total": len(cases),
        "passed": passed,
        "task_success": passed / total,
        "policy_violation": violations / total,
        "avg_latency_ms": (time.perf_counter() - t0) * 1000 / total,
    }
