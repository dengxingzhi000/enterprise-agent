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


def test_saver_adapter_delegates_to_native():
    from workflow.checkpoint import _SaverAdapter

    class FakeNative:
        def __init__(self):
            self.put_calls = []
            self.get_calls = []
            self._data = {}

        def put(self, config, checkpoint, metadata=None, new_versions=None):
            self.put_calls.append((config, checkpoint))
            tid = config["configurable"]["thread_id"]
            self._data[tid] = dict(checkpoint)

        def get_tuple(self, config):
            self.get_calls.append(config)
            tid = config["configurable"]["thread_id"]
            v = self._data.get(tid)
            return dict(v) if v is not None else None

    fake = FakeNative()
    adapter = _SaverAdapter(fake)
    adapter.put("t-native-1", {"node": "judge"})
    assert fake.put_calls, "native put must be called on delegation"
    assert fake.put_calls[0][0]["configurable"]["thread_id"] == "t-native-1"
    out = adapter.get("t-native-1")
    assert fake.get_calls, "native get_tuple must be called on delegation"
    assert out["node"] == "judge"


def test_pause_creates_approval_pending_entry_and_resume():
    from workflow.graph_lang import build_expense_graph
    from workflow.checkpoint import get_checkpointer
    from security.approval import ApprovalStore
    approvals = ApprovalStore()
    cp = get_checkpointer(dsn=None)
    g = build_expense_graph(policy_threshold=5000, checkpointer=cp, approval_store=approvals)
    first = g.invoke({"expense": {"id": "E9b", "amount": 6230}},
                     config={"configurable": {"thread_id": "task-apr-1"}})
    assert first["decision"] in ("paused_human_review", "human_review")
    pendings = [v for v in approvals._items.values() if v["status"] == "pending"]
    assert len(pendings) >= 1, "pause must dual-write ApprovalStore pending entry"
    done = g.invoke(None, config={"configurable": {"thread_id": "task-apr-1"}})
    assert done["decision"] == "human_review"
