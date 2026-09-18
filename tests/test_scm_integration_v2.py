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