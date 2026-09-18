"""SCM integration v2: Phase 1 (Foundation) + Phase 2 + Phase 3 tests."""


def test_write_tools_all_registered():
    """Phase 1 #1: scm.order.cancel + scm.stock.adjust 也要在 registry 里。"""
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    names = set(reg.list_tools())
    assert "scm.purchase.create" in names
    assert "scm.order.cancel" in names
    assert "scm.stock.adjust" in names


def test_write_tools_all_classified_need_approval():
    """Phase 1 #1 联动：所有写口经 PolicyEngine 走 need_approval。"""
    from security.policy import PolicyEngine
    p = PolicyEngine()
    for tool in ("scm.purchase.create", "scm.order.cancel", "scm.stock.adjust"):
        d = p.check({"tenant_id": "t1", "role": "admin"}, tool, {"tenant_id": "t1"})
        assert d["decision"] == "need_approval", f"{tool}: {d}"


def test_unknown_scm_tool_denied():
    """Phase 1 #1 联动：未知 scm.* 必须 deny（防御 typo）。"""
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "admin"}, "scm.order.destroy", {"tenant_id": "t1"})
    assert d["decision"] == "deny"


def test_5xx_retry(monkeypatch):
    """Phase 1 #3: 5xx 必须重试 1 次（修复: _send 返回 (code, body) 不抛）。"""
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        return (503, {"error": "down"}) if calls["n"] == 1 else (200, {"ok": True})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5)
    code, body = c.get("/api/x")
    assert code == 200
    assert body == {"ok": True}
    assert calls["n"] == 2


def test_connect_error_retry(monkeypatch):
    """Phase 1 #3: ConnectError 必须重试 1 次。"""
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        import httpx
        if calls["n"] == 1:
            raise httpx.ConnectError("conn refused")
        return (200, {"ok": True})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5)
    code, body = c.get("/api/x")
    assert code == 200
    assert calls["n"] == 2


def test_no_retry_on_4xx(monkeypatch):
    """Phase 1 #3: 4xx 不重试。"""
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        return (404, {"error": "not found"})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5)
    code, body = c.get("/api/x")
    assert code == 404
    assert calls["n"] == 1


def test_5xx_give_up_after_retry(monkeypatch):
    """Phase 1 #3: 重试仍 5xx → 返回 code=0 + error body，不抛。"""
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        return (503, {"error": "down"})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5,
                  backoff_seconds=0)
    code, body = c.get("/api/x")
    assert code == 0
    assert "error" in body
    assert "5xx" in body["error"]
    assert calls["n"] == 2


def test_tenant_map_warning_on_bad_json(monkeypatch, recwarn):
    """Phase 1 #8: 坏 JSON → warning + 默认 map。"""
    monkeypatch.setenv("SCM_TENANT_MAP", "{not valid json")
    from integrations.scm import auth
    m = auth.load_tenant_map()
    assert m == {"t1": "tenant_001"}
    assert any("SCM_TENANT_MAP" in str(w.message) for w in recwarn.list)


def test_tenant_map_warning_on_empty(monkeypatch, recwarn):
    """Phase 1 #8: 空 dict → warning + 默认。"""
    monkeypatch.setenv("SCM_TENANT_MAP", "{}")
    from integrations.scm import auth
    m = auth.load_tenant_map()
    assert m == {"t1": "tenant_001"}
    assert any("SCM_TENANT_MAP" in str(w.message) for w in recwarn.list)


def test_to_scm_tenant_unknown_warns(monkeypatch, recwarn):
    """Phase 1 #8: agent tenant 不在 map 中 → warning + 透传。"""
    monkeypatch.setenv("SCM_TENANT_MAP", '{"t2":"tenant_002"}')
    from integrations.scm import auth
    scm_t = auth.to_scm_tenant("t9")
    assert scm_t == "t9"
    assert any("no scm tenant mapping" in str(w.message).lower() for w in recwarn.list)


def test_scm_supplier_get_registered():
    """Phase 2 #6: scm.supplier.get 必须在 registry 里。"""
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    assert "scm.supplier.get" in reg.list_tools()


def test_scm_supplier_get_read_allowed():
    """Phase 2 #6 联动：PolicyEngine allow。"""
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "employee"},
                "scm.supplier.get", {"supplier_id": "SP-001", "tenant_id": "t1"})
    assert d["decision"] == "allow"


def test_scm_supplier_get_mock_payload():
    """Phase 2 #6: 离线 mock 返回 supplier 风险字段。"""
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    out = reg.call("scm.supplier.get", {"supplier_id": "SP-001", "tenant_id": "t1"})
    s = str(out)
    assert "SP-001" in s
    assert "credit_score" in s or "rating" in s


def test_run_it_ops_basic():
    """Phase 2 #4: run_it_ops 返回 report + trace，trace 含 metrics + logs。"""
    from workflow.scenarios import run_it_ops
    out = run_it_ops("近7天为什么下降")
    assert "report" in out
    assert "trace" in out
    assert "metrics.get" in out["trace"]
    assert "logs.search" in out["trace"]


def test_run_it_ops_extracts_order_no():
    """Phase 2 #4: question 含订单号（如'O-1234567'）时 trace 加 scm.order.get。"""
    from workflow.scenarios import run_it_ops
    out = run_it_ops("订单 O-20260915001 支付超时")
    assert "scm.order.get" in out["trace"]


def test_run_it_ops_no_order_no_keeps_template():
    """Phase 2 #4: 无订单号时 trace 不含 scm.order.get。"""
    from workflow.scenarios import run_it_ops
    out = run_it_ops("服务异常")
    assert "scm.order.get" not in out["trace"]


def test_run_it_ops_falls_back_to_knowledge_search(monkeypatch):
    """Phase 2 #4 + spec §3.4 step 4: tool 异常 → 静默回退 knowledge.search。"""
    from agent.tools.registry import Registry
    orig_call = Registry.call
    def fake_call(self, name, args):
        if name == "metrics.get":
            raise RuntimeError("metrics down")
        if name == "logs.search":
            raise RuntimeError("logs down")
        return orig_call(self, name, args)
    monkeypatch.setattr(Registry, "call", fake_call)
    from workflow.scenarios import run_it_ops
    out = run_it_ops("近7天为什么下降")
    # knowledge.search 应该被调一次（metrics 失败时）+一次（logs 失败时）
    assert out["trace"].count("knowledge.search") >= 2
    # report 仍是合法的报告（不应包含 sentinel error 字符串）
    assert "RuntimeError" not in out["report"]
    assert "metrics down" not in out["report"]


def test_review_contract_uses_supplier():
    """Phase 2 #6: risk 命中时 opinion 含 supplier 信息 + trace 含 scm.supplier.get。"""
    from workflow.scenarios import review_contract
    out = review_contract({"amount": 50000, "clauses": [], "supplier_id": "SP-001"})
    assert out["decision"] == "human_review"
    assert "supplier" in out["opinion"].lower() or "SP-001" in out["opinion"]
    assert "scm.supplier.get" in out["trace"]


def test_review_contract_no_supplier_id_skips_hook():
    """Phase 2 #6: 缺 supplier_id 时不调 scm，opinion 不含 supplier 字段。"""
    from workflow.scenarios import review_contract
    out = review_contract({"amount": 50000, "clauses": []})
    assert "scm.supplier.get" not in out["trace"]


def test_supplier_call_failure_does_not_break_review(monkeypatch):
    """Phase 2 #6: scm.supplier.get 失败时 review_contract 仍返回原 decision。"""
    from agent.tools.registry import Registry
    from workflow import scenarios
    orig_call = Registry.call
    def fake_call(self, name, args):
        if name == "scm.supplier.get":
            raise RuntimeError("scm down")
        return orig_call(self, name, args)
    monkeypatch.setattr(Registry, "call", fake_call)
    out = scenarios.review_contract({"amount": 50000, "clauses": [], "supplier_id": "SP-001"})
    assert out["decision"] == "human_review"
    assert "暂不可用" in out["opinion"] or "supplier" in out["opinion"].lower()