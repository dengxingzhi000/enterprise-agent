"""LangGraph对齐层：节点与自研Workflow一一对应。

两条诚实路径（无伪装分支）：
- 真图路径：langgraph 可导入 **且** checkpointer 是原生 saver
  （``get_tuple``/``put`` 形状，见 workflow/checkpoint.py）时，构建
  REAL StateGraph(fetch→check→policy→judge)，``compile(checkpointer=原生saver)``，
  ``need_human`` 时 ``interrupt()`` 暂停并双写 ApprovalStore，``invoke(None)``
  同 thread_id 恢复。
- 仿真路径：langgraph 缺席或只有内存 checkpointer 时，用 _DurableAdapter
  仿真 pause/resume 语义，保证 pytest 离线全绿。
"""
from .graph import run_expense_workflow


def _native_saver_of(store):
    """返回原生 saver（具 get_tuple/put），否则 None。"""
    if store is None:
        return None
    inner = getattr(store, "_inner", None)
    if inner is not None and hasattr(inner, "get_tuple") and hasattr(inner, "put"):
        return inner
    if hasattr(store, "get_tuple") and hasattr(store, "put") and not hasattr(store, "_store"):
        # 原生 saver 本体（MemorySaver/PostgresSaver），排除本地 MemoryCheckpointer。
        return store
    return None


def _langgraph_imports():
    try:
        from langgraph.graph import StateGraph, END  # type: ignore
        try:
            from langgraph.graph import interrupt  # type: ignore
        except Exception:
            from langgraph.types import interrupt  # type: ignore
        return StateGraph, END, interrupt
    except Exception:
        return None


def _build_real_expense_graph(policy_threshold, native_saver, approvals,
                               _idem_store=None, _loops=None):
    """REAL StateGraph 路径：仅在 langgraph 已安装时调用。"""
    StateGraph, END, interrupt = _langgraph_imports()
    from .nodes import expense as n
    from .durable import run_with_retry, IdempotencyStore, LoopDetector

    idem = _idem_store if _idem_store is not None else IdempotencyStore()
    loops: dict[str, LoopDetector] = _loops if _loops is not None else {}

    def _loop_for(tid: str) -> LoopDetector:
        det = loops.get(tid)
        if det is None:
            det = LoopDetector(limit=8)
            loops[tid] = det
        return det

    def _tid_of(config, default="default"):
        try:
            return (config or {}).get("configurable", {}).get("thread_id", default)
        except Exception:
            return default

    def _guarded(node: str, fn, state: dict, tid: str) -> dict:
        # Loop guard → failed loop_detected; retry exhaustion → fallback + human chain.
        det = _loop_for(tid)
        if det.visit(node):
            out = dict(state)
            out.setdefault("trace", []).append("loop_detected")
            out["_loop_failed"] = True
            out["_failed_node"] = node
            return out
        try:
            out = run_with_retry(f"{tid}:{node}", lambda: fn(dict(state)),
                                 store=idem, retries=3, timeout=5.0, backoff=1.0)
            if isinstance(state, dict) and state.get("_fallback_human"):
                out["_fallback_human"] = True
                out["need_human"] = True
            return out
        except Exception as e:  # noqa: BLE001 - fallback→human
            out = dict(state)
            out.setdefault("trace", []).extend(["timeout", "retry", "fallback", "human"])
            out["_fallback_node"] = node
            out["_fallback_error"] = f"{type(e).__name__}: {e}"
            out["need_human"] = True
            out["_fallback_human"] = True
            try:
                approvals.request(user={"thread_id": tid}, tool="expense_approval",
                                  args={"expense": out.get("expense", {}), "thread_id": tid})
            except Exception:
                pass
            return out

    def fetch(state: dict, config=None) -> dict:
        return _guarded("fetch_expense", n.fetch_expense, dict(state), _tid_of(config))

    def check(state: dict, config=None) -> dict:
        return _guarded("check_amount", n.check_amount, dict(state), _tid_of(config))

    def policy(state: dict, config=None) -> dict:
        return _guarded("retrieve_policy", n.retrieve_policy, dict(state), _tid_of(config))

    def judge(state: dict, config=None) -> dict:
        tid = _tid_of(config)
        out = _guarded("judge_rule", n.judge_rule, dict(state), tid)
        if out.get("_loop_failed"):
            return out
        if out.get("need_human"):
            try:
                approvals.request(
                    user={"thread_id": tid},
                    tool="expense_approval",
                    args={"expense": out.get("expense", {}), "thread_id": tid},
                )
            except Exception:
                pass
            interrupt({"thread_id": tid, "need_human": True})
        return out

    graph = StateGraph(dict)
    graph.add_node("fetch", fetch)
    graph.add_node("check", check)
    graph.add_node("policy", policy)
    graph.add_node("judge", judge)
    graph.set_entry_point("fetch")
    graph.add_edge("fetch", "check")
    graph.add_edge("check", "policy")
    graph.add_edge("policy", "judge")
    graph.add_edge("judge", END)
    compiled = graph.compile(checkpointer=native_saver)

    def _ensure_pending(tid, expense):
        try:
            for item in approvals._items.values():
                args = item.get("args", {}) if isinstance(item, dict) else {}
                if item.get("status") == "pending" and args.get("thread_id") == tid:
                    return item["id"]
            return approvals.request(
                user={"thread_id": tid},
                tool="expense_approval",
                args={"expense": expense or {}, "thread_id": tid},
            )
        except Exception:
            return None

    class _RealAdapter:
        def __init__(self):
            self.approval_store = approvals
            self.approvals = approvals
            self.idempotency_store = idem
            self._idem_store = idem

        def invoke(self, state, config=None):
            tid = _tid_of(config)
            cfg = {"configurable": {"thread_id": tid}}
            if state is None:
                resumed = compiled.invoke(None, config=cfg)
                decision = "human_review" if (resumed or {}).get("need_human") else "auto_approve"
                trace = list((resumed or {}).get("trace", [])) + [decision]
                return {"decision": decision, "state": resumed, "trace": trace}
            exp = state.get("expense", {}) if isinstance(state, dict) else {}
            init = {"expense": exp, "policy_threshold": policy_threshold, "trace": []}
            resumed = compiled.invoke(init, config=cfg)
            if isinstance(resumed, dict) and resumed.get("__interrupt__"):
                _ensure_pending(tid, exp)
                inner = resumed.get("__interrupt__")
                base = dict(resumed)
                base.pop("__interrupt__", None)
                trace = list(base.get("trace", [])) + ["paused"]
                return {"decision": "paused_human_review", "state": base,
                        "trace": trace, "interrupt": inner}
            if (resumed or {}).get("need_human"):
                _ensure_pending(tid, exp)
                trace = list(resumed.get("trace", [])) + ["paused"]
                return {"decision": "paused_human_review", "state": resumed, "trace": trace}
            trace = list((resumed or {}).get("trace", [])) + ["auto_approve"]
            return {"decision": "auto_approve", "state": resumed, "trace": trace}

    return _RealAdapter()


def build_expense_graph(policy_threshold: float = 5000, checkpointer=None, _store=None,
                         approval_store=None):
    from workflow.checkpoint import MemoryCheckpointer
    from security.approval import ApprovalStore

    if checkpointer is not None:
        store = checkpointer
    elif _store is not None:
        store = _store
    else:
        store = MemoryCheckpointer()
    # Durable (pause/resume) semantics only when caller passes an explicit
    # checkpointer/_store; otherwise preserve classic human_review/auto_approve
    # parity for old callers (tests/test_stage8.py).
    durable = checkpointer is not None or _store is not None
    approvals = approval_store if approval_store is not None else ApprovalStore()
    from .nodes import expense as n
    from .durable import run_with_retry, IdempotencyStore, LoopDetector

    _fns = (n.fetch_expense, n.check_amount, n.retrieve_policy, n.judge_rule)
    # Durable guard stores (offline dict fallback inside IdempotencyStore).
    _idem_store = IdempotencyStore()
    _loops: dict[str, LoopDetector] = {}

    def _loop_for(tid: str) -> LoopDetector:
        det = _loops.get(tid)
        if det is None:
            det = LoopDetector(limit=8)
            _loops[tid] = det
        return det

    # 真图路径：langgraph 可导入且 checkpointer 为原生 saver 时启用。
    if _langgraph_imports() is not None and _native_saver_of(store) is not None:
        return _build_real_expense_graph(policy_threshold, _native_saver_of(store), approvals,
                                         _idem_store=_idem_store, _loops=_loops)

    # 仿真路径（离线/无 langgraph）：诚实的 _DurableAdapter，不伪装成真图。
    def run_all(exp, resumed_state=None, tid: str = "default"):
        if resumed_state:
            s = dict(resumed_state)
            s["expense"] = exp
            s.setdefault("policy_threshold", policy_threshold)
            s["trace"] = list(resumed_state.get("trace", []))
            s["_done"] = list(resumed_state.get("_done", []))
        else:
            s = {"expense": exp, "policy_threshold": policy_threshold, "trace": [], "_done": []}
        det = _loop_for(tid)
        for fn in _fns:
            node = fn.__name__
            if node not in s.get("_done", []):
                # Loop guard first: visit-count check.
                if det.visit(node):
                    s.setdefault("trace", []).append("loop_detected")
                    s["_loop_failed"] = True
                    s["_failed_node"] = node
                    break
                # Durable guard: timeout/retry/idempotent wrapping.
                # Key format enforced: f"{thread_id}:{node}".
                key = f"{tid}:{node}"
                try:
                    s = run_with_retry(key, lambda fn=fn: fn(s), store=_idem_store,
                                       retries=3, timeout=5.0, backoff=1.0)
                    # Fallback is sticky: later deterministic nodes must not clear human routing.
                    if s.get("_fallback_human"):
                        s["need_human"] = True
                except Exception as e:  # noqa: BLE001 - retry exhaustion → fallback→human
                    s.setdefault("trace", []).extend(["timeout", "retry", "fallback", "human"])
                    s["_fallback_node"] = node
                    s["_fallback_error"] = f"{type(e).__name__}: {e}"
                    s["need_human"] = True
                    s["_fallback_human"] = True
                    _ensure_pending(tid, exp)
                    s.setdefault("_done", []).append(node)
                    continue
                s.setdefault("_done", []).append(node)
        return s

    def _save(tid, out, exp):
        if hasattr(store, "put"):
            try:
                store.put(tid, {
                    "expense": exp,
                    "_done": list(out.get("_done", [])),
                    "trace": list(out.get("trace", [])),
                    "need_human": out.get("need_human"),
                    "amount_ok": out.get("amount_ok"),
                    "policy_text": out.get("policy_text"),
                    "policy_threshold": policy_threshold,
                    "_fallback_human": out.get("_fallback_human", False),
                    "_fallback_node": out.get("_fallback_node"),
                    "_fallback_error": out.get("_fallback_error"),
                })
            except Exception:
                pass

    def _ensure_pending(tid, exp):
        try:
            for item in approvals._items.values():
                args = item.get("args", {}) if isinstance(item, dict) else {}
                if item.get("status") == "pending" and args.get("thread_id") == tid:
                    return item["id"]
            return approvals.request(
                user={"thread_id": tid},
                tool="expense_approval",
                args={"expense": exp, "thread_id": tid},
            )
        except Exception:
            return None

    def _reset_guard_for_new_expense(tid: str) -> None:
        # Same tid reused with a different expense (e.g. parity tests using
        # default tid): stale f"{tid}:{node}" idempotency entries must not leak
        # across expenses. Clear tid-prefixed keys + reset visit counts.
        try:
            mem = getattr(_idem_store, "_mem", None)
            if isinstance(mem, dict):
                for k in [k for k in mem.keys() if k.startswith(f"{tid}:")]:
                    mem.pop(k, None)
            r = getattr(_idem_store, "_redis", None)
            if r is not None:
                try:
                    for node in ("fetch_expense", "check_amount", "retrieve_policy", "judge_rule"):
                        r.delete(f"{tid}:{node}")
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from .durable import LoopDetector as _LD
            _loops[tid] = _LD(limit=8)
        except Exception:
            pass

    class _DurableAdapter:
        # HITL convention: pause 时双写 ApprovalStore（apr-* pending），
        # caller approve 后用 same thread_id invoke(None) 恢复。
        def __init__(self):
            self.approval_store = approvals
            self.approvals = approvals
            # Exposed for graph-level idempotency assertions (key f"{tid}:{node}").
            self.idempotency_store = _idem_store
            self._idem_store = _idem_store

        def invoke(self, state, config=None):
            tid = (config or {}).get("configurable", {}).get("thread_id", "default")
            if state is None:
                saved = store.get(tid) if hasattr(store, "get") else None
                if not saved:
                    return {"decision": "failed", "trace": [], "reason": "checkpoint_missing"}
                out = run_all(saved.get("expense", {}), saved, tid)
                if out.get("_loop_failed"):
                    trace = list(out.get("trace", [])) + ["failed"]
                    _save(tid, out, out.get("expense", {}))
                    return {"decision": "failed", "state": out, "trace": trace,
                            "reason": "loop_detected"}
                decision = "human_review" if out.get("need_human") else "auto_approve"
                trace = list(out.get("trace", [])) + [decision]
                _save(tid, out, out.get("expense", {}))
                return {"decision": decision, "state": out, "trace": trace}
            exp = state.get("expense", {}) if isinstance(state, dict) else {}
            saved = store.get(tid) if hasattr(store, "get") else None
            if saved and saved.get("expense") == exp:
                base = saved
            else:
                _reset_guard_for_new_expense(tid)
                base = {"expense": exp, "policy_threshold": policy_threshold, "trace": [], "_done": []}
            out = run_all(exp, base, tid)
            _save(tid, out, exp)
            if out.get("_loop_failed"):
                return {"decision": "failed", "state": out,
                        "trace": list(out.get("trace", [])) + ["failed"],
                        "reason": "loop_detected"}
            if out.get("need_human"):
                if durable:
                    _ensure_pending(tid, exp)
                    return {"decision": "paused_human_review", "state": out,
                            "trace": list(out.get("trace", [])) + ["paused"]}
                return {"decision": "human_review", "state": out,
                        "trace": list(out.get("trace", [])) + ["human_review"]}
            return {"decision": "auto_approve", "state": out,
                    "trace": list(out.get("trace", [])) + ["auto_approve"]}

    return _DurableAdapter()
