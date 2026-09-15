"""Stage3 RED: 企业知识库 = chunk元数据 + 租户/权限过滤 + 相关性排序。"""
from knowledge.document import Document
from knowledge.ingestion import ingest
from knowledge.store import KnowledgeStore


def _doc(text, tenant="t1", permission="employee", doc_id="d1", dept="finance"):
    return Document(
        text=text, tenant_id=tenant, department=dept,
        document_id=doc_id, version="v1", permission=permission,
    )


def test_ingestion_splits_with_metadata():
    doc = _doc("差旅报销制度。" * 50)
    chunks = ingest(doc, max_chars=100, overlap=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.tenant_id == "t1"
        assert c.permission == "employee"
        assert c.document_id == "d1"
        assert len(c.text) <= 100 + 20


def test_retrieval_filters_by_tenant_and_permission():
    store = KnowledgeStore()
    store.add_many(ingest(_doc("报销超过5000需财务审批", tenant="t1", permission="finance")))
    store.add_many(ingest(_doc("报销超过5000需财务审批", tenant="t2", permission="finance")))
    store.add_many(ingest(_doc("普通员工午餐补贴20元", tenant="t1", permission="employee")))

    # t1财务能查到t1财务文档，查不到t2的
    hits = store.search("报销5000审批", tenant_id="t1", allowed_permissions=["finance"])
    assert len(hits) == 1
    assert "5000" in hits[0].text

    # t1普通员工查不到财务文档
    hits2 = store.search("报销5000审批", tenant_id="t1", allowed_permissions=["employee"])
    assert all("5000" not in h.text or h.permission == "employee" for h in hits2)


def test_retrieval_ranks_relevant_first():
    store = KnowledgeStore()
    store.add_many(ingest(_doc("午餐补贴20元", doc_id="d-lunch")))
    store.add_many(ingest(_doc("差旅报销超过5000元需财务审批", doc_id="d-expense")))
    hits = store.search("报销超过5000审批", tenant_id="t1", allowed_permissions=["employee", "finance"])
    assert "5000" in hits[0].text


def test_knowledge_search_tool_exists():
    from agent.tools.builtin import build_default_registry
    reg = build_default_registry()
    assert "knowledge.search" in reg.list_tools()
    out = reg.call("knowledge.search", {"query": "报销5000", "tenant_id": "t1"})
    assert "5000" in str(out)
