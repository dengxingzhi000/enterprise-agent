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
