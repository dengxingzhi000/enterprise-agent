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
