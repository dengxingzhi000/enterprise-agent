from agent.tools.registry import Registry


def test_register_scm_tools():
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    names = reg.list_tools()
    assert "scm.order.get" in names
    assert "scm.inventory.query" in names
    assert "scm.sales.report" in names


def test_401_refresh_retry(monkeypatch):
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return (401, {"error": "expired"})
        return (200, {"order_no": "20260915001", "status": "PAID"})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5)
    code, body = c.get("/api/orders/20260915001")
    assert code == 200
    assert body["status"] == "PAID"
    assert calls["n"] == 2


def test_cross_tenant_denied():
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "admin"}, "scm.order.get", {"tenant_id": "t2"})
    assert d["decision"] == "deny"


def test_offline_fallback():
    import os
    os.environ.pop("SCM_GATEWAY_URL", None)
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    out = reg.call("scm.order.get", {"order_no": "20260915001", "tenant_id": "t1"})
    assert "20260915001" in str(out)


def test_scm_read_allowed():
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "employee"}, "scm.order.get", {"tenant_id": "t1"})
    assert d["decision"] == "allow"


def test_analyze_sales_prefers_scm():
    import os
    os.environ.pop("SCM_GATEWAY_URL", None)
    from workflow.scenarios import analyze_sales
    out = analyze_sales("近7天为什么下降")
    assert "report" in out
    assert "trace" in out and len(out["trace"]) >= 1


def test_scm_write_needs_approval():
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "admin"}, "scm.purchase.create", {"tenant_id": "t1"})
    assert d["decision"] == "need_approval"
