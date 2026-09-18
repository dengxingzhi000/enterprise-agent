"""运维四件套 Mock: metrics/logs/git/db。返回确定性假数据，先跑通Loop。"""
from .registry import Registry, Tool


def _metrics_get(args: dict):
    service = args.get("service", "order")
    return f"{service} 5xx rate 12% (p99 latency 2.3s), window 15m"


def _logs_search(args: dict):
    keyword = args.get("keyword", "5xx")
    return f"ERROR order-api {keyword} Timeout upstream payment-service x42, trace_id=abc123"


def _git_diff(args: dict):
    return "recent commit 9f3a2b: payment-service timeout 2s->500ms, order-api retry x3"


def _db_query(args: dict):
    return "row1: order_no=20260915001 status=PAID amount=6230"


def _knowledge_search(args: dict):
    from knowledge.seed import get_default_store
    q = args.get("query", "")
    tenant = args.get("tenant_id", "t1")
    hits = get_default_store().search(q, tenant_id=tenant,
                                      allowed_permissions=["employee", "finance", "manager", "admin"])
    if not hits:
        return "no hits"
    return "\n".join(f"[{h.document_id}#{h.chunk_id} {h.permission}] {h.text[:200]}" for h in hits)


def build_default_registry() -> Registry:
    reg = Registry()
    reg.register(Tool("metrics.get", "查服务错误率/延迟", _metrics_get))
    reg.register(Tool("logs.search", "查错误日志", _logs_search))
    reg.register(Tool("git.diff", "查最近提交", _git_diff))
    reg.register(Tool("db.query", "查业务数据(mock)", _db_query))
    reg.register(Tool("knowledge.search", "查企业制度/手册(RAG)", _knowledge_search))
    try:
        from integrations.scm.tools import register_scm_tools
        register_scm_tools(reg)
    except Exception:
        pass
    return reg
