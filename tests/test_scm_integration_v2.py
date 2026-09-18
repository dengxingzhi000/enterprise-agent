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