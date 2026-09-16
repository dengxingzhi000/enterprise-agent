"""infrastructure/pg/schema.py: 五张 memory 表幂等 DDL。"""
import warnings


SCHEMA_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS memory_user (
        id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL, department TEXT,
        permission TEXT NOT NULL DEFAULT 'public', version INT NOT NULL DEFAULT 1,
        body JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    """CREATE INDEX IF NOT EXISTS idx_memory_user_tenant ON memory_user(tenant_id)""",
    """CREATE INDEX IF NOT EXISTS idx_memory_user_perm ON memory_user(permission)""",
    """CREATE TABLE IF NOT EXISTS memory_org (
        id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL, department TEXT,
        permission TEXT NOT NULL DEFAULT 'public', version INT NOT NULL DEFAULT 1,
        body JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    """CREATE INDEX IF NOT EXISTS idx_memory_org_tenant ON memory_org(tenant_id)""",
    """CREATE TABLE IF NOT EXISTS memory_conv (
        id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL, department TEXT,
        permission TEXT NOT NULL DEFAULT 'public', version INT NOT NULL DEFAULT 1,
        body JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    """CREATE INDEX IF NOT EXISTS idx_memory_conv_tenant ON memory_conv(tenant_id)""",
    """CREATE TABLE IF NOT EXISTS memory_task (
        id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL, department TEXT,
        permission TEXT NOT NULL DEFAULT 'public', version INT NOT NULL DEFAULT 1,
        body JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS memory_episodic (
        id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL, department TEXT,
        permission TEXT NOT NULL DEFAULT 'public', version INT NOT NULL DEFAULT 1,
        body JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
    )""",
]


def ensure_schema(conn) -> None:
    for ddl in SCHEMA_DDL:
        try:
            conn.execute(ddl)
        except Exception as e:  # noqa: BLE001 - schema 失败不挂
            warnings.warn(f"schema DDL failed: {e}")
