"""Stage5 RED: Tool前必须过Policy，高风险必须HITL。"""
from security.policy import PolicyEngine
from security.approval import ApprovalStore


def _user(role, dept="ops"):
    return {"user_id": "u1", "tenant_id": "t1", "role": role, "department": dept}


def test_employee_can_only_query_self():
    p = PolicyEngine()
    assert p.check(_user("employee"), "db.query", {"scope": "self"})["decision"] == "allow"
    assert p.check(_user("employee"), "db.query", {"scope": "all"})["decision"] == "deny"


def test_manager_can_query_dept_not_all():
    p = PolicyEngine()
    assert p.check(_user("manager"), "db.query", {"scope": "dept"})["decision"] == "allow"
    assert p.check(_user("manager"), "db.query", {"scope": "all"})["decision"] == "deny"


def test_finance_can_query_all():
    p = PolicyEngine()
    assert p.check(_user("finance"), "db.query", {"scope": "all"})["decision"] == "allow"


def test_high_risk_needs_approval():
    p = PolicyEngine()
    r = p.check(_user("finance"), "payment.execute", {"amount": 6000})
    assert r["decision"] == "need_approval"


def test_approval_flow():
    store = ApprovalStore()
    aid = store.request(_user("employee"), "payment.execute", {"amount": 6000})
    assert store.get(aid)["status"] == "pending"
    store.approve(aid, approver="manager-1")
    assert store.get(aid)["status"] == "approved"


def test_guarded_executor_denies_without_crash():
    from agent.tools.builtin import build_default_registry
    from agent.tools.executor import guarded_executor
    reg = build_default_registry()
    out = guarded_executor(
        {"tool": "db.query", "args": {"scope": "all"}},
        state=None, registry=reg,
        user=_user("employee"), policy=PolicyEngine(),
        approvals=ApprovalStore(),
    )
    assert "deny" in str(out["result"]).lower() or "拒绝" in str(out["result"])
