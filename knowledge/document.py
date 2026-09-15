"""企业文档元数据：每个Chunk都带租户/权限，检索时强制过滤。"""
from dataclasses import dataclass, field
from datetime import datetime, UTC


@dataclass
class Document:
    text: str
    tenant_id: str = "t1"
    department: str = "general"
    document_id: str = "d0"
    version: str = "v1"
    permission: str = "employee"  # employee | finance | manager | admin
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Chunk:
    text: str
    tenant_id: str
    department: str
    document_id: str
    version: str
    permission: str
    created_at: str
    chunk_id: int = 0
