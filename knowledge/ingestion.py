"""切分：按字符滑窗，保留overlap不断句。元数据原样继承。"""
from .document import Document, Chunk


def ingest(doc: Document, max_chars: int = 500, overlap: int = 50) -> list[Chunk]:
    text = doc.text or ""
    chunks: list[Chunk] = []
    step = max(1, max_chars - overlap)
    idx = 0
    for start in range(0, max(1, len(text)), step):
        piece = text[start:start + max_chars]
        if not piece:
            break
        chunks.append(Chunk(
            text=piece, tenant_id=doc.tenant_id, department=doc.department,
            document_id=doc.document_id, version=doc.version,
            permission=doc.permission, created_at=doc.created_at, chunk_id=idx,
        ))
        idx += 1
        if start + max_chars >= len(text):
            break
    return chunks or [Chunk(
        text="", tenant_id=doc.tenant_id, department=doc.department,
        document_id=doc.document_id, version=doc.version,
        permission=doc.permission, created_at=doc.created_at, chunk_id=0,
    )]
