"""内存检索：先按 tenant/permission 硬过滤，再按字面重合度排序（rerank占位）。"""
from .ingestion import Chunk


def _score(query: str, text: str) -> float:
    if not query or not text:
        return 0.0
    s = 0.0
    if query in text:
        s += 10.0
    # 2-gram 命中加分，中文无分词时的最小可用排序
    for i in range(len(query) - 1):
        if query[i:i + 2] in text:
            s += 1.0
    # 数字关键词加权（5000这类规则阈值必须排前面）
    for tok in ("5000", "5xx", "审批", "报销"):
        if tok in query and tok in text:
            s += 3.0
    return s


class KnowledgeStore:
    def __init__(self):
        self._chunks: list[Chunk] = []

    def add_many(self, chunks: list[Chunk]):
        self._chunks.extend(chunks)

    def search(self, query: str, tenant_id: str = "t1",
               allowed_permissions: list[str] | None = None, top_k: int = 3) -> list[Chunk]:
        allowed = set(allowed_permissions or ["employee"])
        candidates = [c for c in self._chunks
                      if c.tenant_id == tenant_id and c.permission in allowed]
        ranked = sorted(candidates, key=lambda c: _score(query, c.text), reverse=True)
        # 只返回有正分的，零分说明完全不相关
        hits = [c for c in ranked if _score(query, c.text) > 0]
        return hits[:top_k]
