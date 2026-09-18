from agent.tools.registry import Registry
from integrations.scm.tools import register_scm_tools


def test_register_scm_tools():
    reg = Registry()
    register_scm_tools(reg)
    names = reg.list_tools()
    assert "scm.order.get" in names
    assert "scm.inventory.query" in names
    assert "scm.sales.report" in names
