"""SCM Tool适配：REST翻译成Registry Tool。无配置回退Mock。"""
import os

from agent.tools.registry import Tool

from .auth import to_scm_tenant
from .client import ScmClient


def _use_mock() -> bool:
    return not os.environ.get("SCM_GATEWAY_URL")


def _mock_order(args: dict):
    return f"row1: order_no={args.get('order_no','20260915001')} status=PAID amount=6230 (mock)"


def _mock_inventory(args: dict):
    return f"sku={args.get('sku','SKU-001')} stock=128 warehouse=WH-01 (mock)"


def _mock_sales(args: dict):
    return f"sales range={args.get('range','7d')} gmv=123456 orders=321 (mock)"


def register_scm_tools(registry, client=None):
    if _use_mock() and client is None:
        registry.register(Tool("scm.order.get", "查SCM订单(只读)", _mock_order))
        registry.register(Tool("scm.inventory.query", "查SCM库存(只读)", _mock_inventory))
        registry.register(Tool("scm.sales.report", "查销售聚合(只读)", _mock_sales))
        # 写口占位：返回need-approval字符串。实际不会被调用，因为 guarded_executor
        # 在 PolicyEngine.need_approval 时已拦截；保留仅为防御 Policy 配置失误。
        registry.register(Tool("scm.purchase.create", "建采购单(占位, 走HITL)", lambda a: "need approval: scm.purchase.create pending human review"))
        registry.register(Tool("scm.order.cancel", "取消SCM订单(占位, 走HITL)", lambda a: "need approval: scm.order.cancel pending human review"))
        registry.register(Tool("scm.stock.adjust", "调整SCM库存(占位, 走HITL)", lambda a: "need approval: scm.stock.adjust pending human review"))
        return registry
    c = client or ScmClient.from_env()

    def _order_get(args: dict):
        args = args or {}
        try:
            code, body = c.get(f"/api/orders/{args.get('order_no','')}", params={"tenant": to_scm_tenant(args.get("tenant_id","t1"))})
            return str(body)[:2000] if code == 200 else f"tool error scm.order.get: {code} {str(body)[:500]}"
        except Exception as e:
            return f"tool error scm.order.get: {e}"

    def _inv_query(args: dict):
        args = args or {}
        try:
            code, body = c.get("/api/inventory", params={"sku": args.get("sku",""), "tenant": to_scm_tenant(args.get("tenant_id","t1"))})
            return str(body)[:2000] if code == 200 else f"tool error scm.inventory.query: {code} {str(body)[:500]}"
        except Exception as e:
            return f"tool error scm.inventory.query: {e}"

    def _sales(args: dict):
        args = args or {}
        try:
            code, body = c.get("/api/analytics/sales", params={"range": args.get("range","7d"), "tenant": to_scm_tenant(args.get("tenant_id","t1"))})
            return str(body)[:2000] if code == 200 else f"tool error scm.sales.report: {code} {str(body)[:500]}"
        except Exception as e:
            return f"tool error scm.sales.report: {e}"

    registry.register(Tool("scm.order.get", "查SCM订单(只读)", _order_get))
    registry.register(Tool("scm.inventory.query", "查SCM库存(只读)", _inv_query))
    registry.register(Tool("scm.sales.report", "查销售聚合(只读)", _sales_report_alias(_sales)))
    # 写口占位：返回need-approval字符串。实际不会被调用，因为 guarded_executor
    # 在 PolicyEngine.need_approval 时已拦截；保留仅为防御 Policy 配置失误。
    registry.register(Tool("scm.purchase.create", "建采购单(占位, 走HITL)", lambda a: "need approval: scm.purchase.create pending human review"))
    registry.register(Tool("scm.order.cancel", "取消SCM订单(占位, 走HITL)", lambda a: "need approval: scm.order.cancel pending human review"))
    registry.register(Tool("scm.stock.adjust", "调整SCM库存(占位, 走HITL)", lambda a: "need approval: scm.stock.adjust pending human review"))
    return registry


def _sales_report_alias(fn):
    return fn
