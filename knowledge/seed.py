"""默认种子知识：报销制度 + 运维手册，保证Tool开箱可用。"""
from .document import Document
from .ingestion import ingest
from .store import KnowledgeStore

_store: KnowledgeStore | None = None


def get_default_store() -> KnowledgeStore:
    global _store
    if _store is not None:
        return _store
    s = KnowledgeStore()
    s.add_many(ingest(Document(
        text="差旅报销制度：单笔超过5000元需财务审批，超过10000元需部门经理+财务双审批。合规要求附发票与行程单。",
        tenant_id="t1", department="finance", document_id="expense-policy",
        version="v1", permission="finance",
    )))
    s.add_many(ingest(Document(
        text="普通员工午餐补贴20元/天，随工资发放，无需审批。",
        tenant_id="t1", department="hr", document_id="lunch-policy",
        version="v1", permission="employee",
    )))
    s.add_many(ingest(Document(
        text="订单5xx排查手册：先看metrics.get确认错误率，再logs.search查ERROR堆栈，再git.diff看最近变更。",
        tenant_id="t1", department="ops", document_id="ops-runbook",
        version="v1", permission="employee",
    )))
    _store = s
    return s
