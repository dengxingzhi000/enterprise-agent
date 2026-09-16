def test_checkpointer_falls_back_without_pg():
    from workflow.checkpoint import get_checkpointer
    cp = get_checkpointer(dsn="postgresql://invalid:1@127.0.0.1:1/nope")
    tid = "t-fallback-1"
    cp.put(tid, {"node": "judge", "trace": ["fetch"]})
    assert cp.get(tid)["node"] == "judge"


def test_expense_pause_and_resume_same_thread():
    from workflow.graph_lang import build_expense_graph
    from workflow.checkpoint import get_checkpointer
    cp = get_checkpointer(dsn=None)
    g = build_expense_graph(policy_threshold=5000, checkpointer=cp)
    first = g.invoke({"expense": {"id": "E9", "amount": 6230}}, config={"configurable": {"thread_id": "task-9"}})
    assert first["decision"] in ("paused_human_review", "human_review")
    g2 = build_expense_graph(policy_threshold=5000, checkpointer=cp)
    done = g2.invoke(None, config={"configurable": {"thread_id": "task-9"}})
    assert done["decision"] == "human_review"
    assert "judge_rule" in done["trace"]


def test_tool_timeout_retry_then_fallback_and_idempotent():
    from workflow.durable import run_with_retry, IdempotencyStore, LoopDetector
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("tool timeout")
        return "ok-fallback"
    store = IdempotencyStore()
    out = run_with_retry("task-7:toolB", flaky, store=store, retries=3, timeout=1.0)
    assert out == "ok-fallback"
    assert calls["n"] == 3
    out2 = run_with_retry("task-7:toolB", flaky, store=store, retries=3, timeout=1.0)
    assert out2 == "ok-fallback"
    assert calls["n"] == 3
    det = LoopDetector(limit=3)
    assert det.visit("judge") is False
    assert det.visit("judge") is False
    assert det.visit("judge") is False
    assert det.visit("judge") is True


def test_parity_still_holds_with_durable_graph():
    from workflow.graph import run_expense_workflow
    from workflow.graph_lang import build_expense_graph
    g = build_expense_graph(policy_threshold=5000)
    for expense, expected in [({"id": "E1", "amount": 1000}, "auto_approve")]:
        classic = run_expense_workflow(expense, policy_threshold=5000)["decision"]
        via = g.invoke({"expense": expense}, config={"configurable": {"thread_id": "parity-1"}})["decision"]
        assert classic == expected == via
