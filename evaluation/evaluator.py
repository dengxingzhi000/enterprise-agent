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


def context_quality_gate(baseline: dict, managed: dict, max_ratio: float = 0.7) -> dict:
    b_use, m_use = baseline.get("usage", 0) or 1, managed.get("usage", 0)
    ratio = m_use / b_use
    ok = managed.get("decision") == baseline.get("decision") and ratio <= max_ratio
    return {"pass": ok, "usage_ratio": ratio,
            "decision_match": managed.get("decision") == baseline.get("decision")}
