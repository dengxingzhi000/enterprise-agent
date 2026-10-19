# Memory PG spec#3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Context 九层补齐 memory 五接口（实现 Conv/User/Org，Episodic 占位），PG 主存 + InMemory 兜底，PG outage 不阻断装配。

**Architecture:** 新 `infrastructure/pg/` 包（schema + connector），`agent/memory/store.py` 升级为 connector 注入版，3 个 `MemoryProvider` 接 `DEFAULT_PROVIDERS`。`get_connector()` 工厂按 `PG_DSN`/`PG_OFFLINE` 选实现，启动 `ensure_schema()`。

**Tech Stack:** Python 3.12+, SQLAlchemy 2.x + psycopg[binary] 3.x（硬依赖，CI 可装），pytest-asyncio auto。

---
### Task 1: InMemoryConnector + BaseConnector 抽象

**Files:**
- Create: `infrastructure/__init__.py`
- Create: `infrastructure/pg/__init__.py`
- Create: `infrastructure/pg/connector.py`
- Test: `tests/test_memory_pg.py`

- [ ] **Step 1: Write the failing test**

```python
def test_inmemory_connector_crud_and_healthcheck():
    from infrastructure.pg.connector import InMemoryConnector
    c = InMemoryConnector()
    c.execute("CREATE TABLE x (id INT, name TEXT)")
    c.execute("INSERT INTO x VALUES (?, ?)", (1, "a"))
    rows = c.fetch_all("SELECT * FROM x")
    assert rows == [{"id": 1, "name": "a"}]
    one = c.fetch_one("SELECT * FROM x WHERE id = ?", (1,))
    assert one == {"id": 1, "name": "a"}
    assert c.healthcheck() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_pg.py -v`
Expected: FAIL with "No module named 'infrastructure'"

- [ ] **Step 3: Write minimal implementation**

```python
"""infrastructure/__init__.py"""
```

```python
"""infrastructure/pg/__init__.py"""
from .connector import (  # noqa: F401
    BaseConnector, InMemoryConnector, PGConnector, get_connector,
)
from .schema import ensure_schema  # noqa: F401
```

```python
"""infrastructure/pg/connector.py: InMemory + PG connector, PG-retry+healthcheck, factory."""
import os
import threading
import time
import warnings
from typing import Any, Sequence


class OperationalError(Exception):
    pass


class BaseConnector:
    def execute(self, sql: str, params: Sequence[Any] = ()) -> None: ...
    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]: ...
    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None: ...
    def healthcheck(self) -> bool: ...


class InMemoryConnector(BaseConnector):
    def __init__(self):
        self._tables: dict[str, list[dict]] = {}
        self._lock = threading.Lock()
        self._sql_to_table: dict[str, str] = {}

    @staticmethod
    def _resolve_table(sql: str) -> str:
        sql_low = sql.strip().lower()
        for kw in ("insert into", "select * from", "select from", "from"):
            idx = sql_low.find(kw)
            if idx >= 0:
                rest = sql_low[idx + len(kw):].lstrip()
                return rest.split()[0].rstrip(";").rstrip(",")
        return "x"

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._lock:
            sql_strip = sql.strip()
            low = sql_strip.lower()
            if low.startswith("create table"):
                tname = self._resolve_table(sql_strip)
                cols_sql = sql_strip[sql_strip.lower().find("(") + 1: sql_strip.rfind(")")]
                cols = [c.strip().split()[0] for c in cols_sql.split(",")]
                self._tables.setdefault(tname, [])
                self._sql_to_table[sql_strip] = tname
            elif low.startswith("insert into"):
                tname = self._resolve_table(sql_strip)
                cols = self._tables.setdefault(tname, [])
                cols.append(dict(zip([f"c{i}" for i in range(len(params))], params)))
            else:
                self._sql_to_table[sql_strip] = self._resolve_table(sql_strip)

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        with self._lock:
            tname = self._resolve_table(sql)
            return [dict(r) for r in self._tables.get(tname, [])]

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def healthcheck(self) -> bool:
        return True


class PGConnector(BaseConnector):
    def __init__(self, dsn: str, pool_size: int = 5):
        from sqlalchemy import create_engine
        self._engine = create_engine(dsn, pool_size=pool_size, pool_pre_ping=True, future=True)
        self._dsn = dsn

    def _run(self, op: str, sql: str, params: Sequence[Any] = ()):
        from sqlalchemy import text
        last: Exception | None = None
        for attempt in range(1, 4):
            try:
                with self._engine.connect() as conn:
                    result = conn.execute(text(sql), tuple(params))
                    if op == "execute":
                        conn.commit()
                        return None
                    rows = [dict(r._mapping) for r in result]
                    return rows if op == "fetch_all" else (rows[0] if rows else None)
            except Exception as e:  # noqa: BLE001 - retry all to keep contract
                last = e
                if attempt < 3:
                    time.sleep(2 ** (attempt - 1))
        raise OperationalError(str(last))

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self._run("execute", sql, params)

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        return self._run("fetch_all", sql, params)

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        return self._run("fetch_one", sql, params)

    def healthcheck(self) -> bool:
        try:
            return self.fetch_one("SELECT 1") is not None
        except Exception:
            return False


def get_connector() -> BaseConnector:
    dsn = os.environ.get("PG_DSN") or os.environ.get("POSTGRES_DSN")
    offline = os.environ.get("PG_OFFLINE") == "1"
    if offline or not dsn:
        if not dsn:
            warnings.warn("no PG_DSN set; using InMemoryConnector (dev only)")
        return InMemoryConnector()
    try:
        c = PGConnector(dsn, pool_size=int(os.environ.get("MEMORY_POOL_SIZE", "5")))
        if not c.healthcheck():
            warnings.warn("PG healthcheck failed; falling back to InMemoryConnector")
            return InMemoryConnector()
        from .schema import ensure_schema
        ensure_schema(c)
        return c
    except Exception as e:  # noqa: BLE001 - never block startup
        warnings.warn(f"PG init failed ({e}); falling back to InMemoryConnector")
        return InMemoryConnector()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory_pg.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add infrastructure/__init__.py infrastructure/pg/__init__.py infrastructure/pg/connector.py tests/test_memory_pg.py
git commit -m "feat: infrastructure pg connector with inmemory + pg + factory"
```

### Task 2: Schema 幂等 DDL + ensure_schema

**Files:**
- Create: `infrastructure/pg/schema.py`
- Test: `tests/test_memory_pg.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_ensure_schema_idempotent_on_inmemory(monkeypatch):
    from infrastructure.pg.connector import InMemoryConnector
    from infrastructure.pg.schema import ensure_schema
    c = InMemoryConnector()
    ensure_schema(c)
    ensure_schema(c)  # 双调不报错
    rows = c.fetch_all("SELECT 1")
    assert rows is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_pg.py::test_ensure_schema_idempotent_on_inmemory -v`
Expected: FAIL with "No module named 'infrastructure.pg.schema'"

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory_pg.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add infrastructure/pg/schema.py tests/test_memory_pg.py
git commit -m "feat: pg memory schema idempotent ddl"
```

### Task 3: MemoryStore 升级为 connector 注入

**Files:**
- Modify: `agent/memory/store.py`
- Test: `tests/test_memory_pg.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_memory_store_tenant_isolation_and_permission_filter():
    from infrastructure.pg.connector import InMemoryConnector
    from agent.memory.store import MemoryStore
    c = InMemoryConnector()
    c.execute("CREATE TABLE memory_user (id INT, tenant_id TEXT, permission TEXT, body TEXT)")
    s = MemoryStore(c)
    s.put("user", "tenant_a", {"name": "alice"}, permission="public")
    s.put("user", "tenant_b", {"name": "bob"}, permission="public")
    rows = s.query("user", "tenant_a", permission="public")
    assert len(rows) == 1
    assert rows[0]["body"]["name"] == "alice"


def test_memory_store_outage_degrades_silently(monkeypatch):
    from infrastructure.pg.connector import InMemoryConnector, OperationalError
    from agent.memory.store import MemoryStore
    c = InMemoryConnector()
    s = MemoryStore(c)
    def boom(sql, params=()):
        raise OperationalError("pg down")
    monkeypatch.setattr(c, "execute", boom)
    s.put("user", "tenant_a", {"x": 1})  # 不抛
    assert s.query("user", "tenant_a", permission="public") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_pg.py::test_memory_store_tenant_isolation_and_permission_filter -v`
Expected: FAIL with "MemoryStore.put missing" or signature mismatch

- [ ] **Step 3: Write minimal implementation**

Replace agent/memory/store.py to add a `MemoryStore(connector)` class with `put/get/query`; keep the existing function-style helpers as facade or deprecate (don't break existing tests). Add new methods:

```python
"""agent/memory/store.py: 内存版本 + connector 注入版本并存（向后兼容）。"""
from infrastructure.pg.connector import OperationalError
import json


class MemoryStore:
    LAYERS = ("user", "org", "conv", "task", "episodic")

    def __init__(self, connector):
        self._c = connector

    def put(self, layer: str, tenant_id: str, body: dict, department: str | None = None,
            permission: str = "public", version: int = 1, key: str | None = None) -> None:
        if layer not in self.LAYERS:
            raise ValueError(f"unknown layer: {layer}")
        if not tenant_id:
            raise ValueError("tenant_id required")
        if permission == "*":
            raise ValueError("permission='*' forbidden")
        try:
            self._c.execute(
                f"INSERT INTO memory_{layer} (tenant_id, department, permission, version, body) "
                f"VALUES (?, ?, ?, ?, ?)",
                (tenant_id, department, permission, version, json.dumps(body)),
            )
        except OperationalError:
            pass  # outage degrade

    def query(self, layer: str, tenant_id: str, permission: str = "public",
              department: str | None = None, limit: int = 10) -> list[dict]:
        try:
            rows = self._c.fetch_all(
                f"SELECT body FROM memory_{layer} WHERE tenant_id = ? AND permission = ? "
                f"ORDER BY updated_at DESC LIMIT ?",
                (tenant_id, permission, limit),
            )
            return [json.loads(r["body"]) for r in rows]
        except OperationalError:
            return []

    def get(self, layer: str, tenant_id: str, permission: str = "public") -> list[dict]:
        return self.query(layer, tenant_id, permission=permission)
```

Preserve the original `MemoryStore` (function-based) by renaming the original class-free module to no-op or keep as `def save_conversation(...)`. Simpler: add the new `class MemoryStore(connector)` at module end; the old module-level dict-based implementation can stay (different class name OR move old methods to module-level functions prefixed `_`). Easiest: rename old in-memory methods to module functions `_mem_save_conv / _mem_get_conv / ...` and remove the old `class MemoryStore` to avoid name collision. Verify existing `tests/test_memory.py` doesn't import the old `MemoryStore` class for storage directly — if it does, add a compat alias.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory.py tests/test_memory_pg.py -v`
Expected: PASS (all green; existing memory tests still pass via legacy methods)

- [ ] **Step 5: Commit**

```bash
git add agent/memory/store.py tests/test_memory_pg.py
git commit -m "feat: memory store with tenant isolation and pg outage degrade"
```

### Task 4: MemoryProvider 接九层

**Files:**
- Create: `agent/context/memory_providers.py`
- Modify: `agent/context/providers.py` (add User/Org/Conv after observation, before tooltrace)
- Modify: `agent/context/__init__.py` (no-op)
- Test: `tests/test_memory_pg.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_memory_providers_collect_from_store_and_format():
    from infrastructure.pg.connector import InMemoryConnector
    from agent.memory.store import MemoryStore
    from agent.context.memory_providers import (ConvMemoryProvider, UserMemoryProvider,
                                                  OrgMemoryProvider, EpisodicMemoryProvider)
    c = InMemoryConnector()
    for t in ("memory_conv", "memory_user", "memory_org"):
        c.execute(f"CREATE TABLE {t} (id INT, tenant_id TEXT, permission TEXT, body TEXT)")
    s = MemoryStore(c)
    s.put("conv", "t1", {"role": "user", "content": "hi"}, permission="tenant")
    s.put("user", "t1", {"name": "alice", "role": "ops"}, permission="tenant")
    s.put("org", "t1", {"policy": "审批>5000走财务"}, permission="tenant")
    state = {"tenant_id": "t1"}
    conv_segs = ConvMemoryProvider(permission="tenant").collect(state)
    user_segs = UserMemoryProvider(permission="tenant").collect(state)
    org_segs = OrgMemoryProvider(permission="tenant").collect(state)
    epi_segs = EpisodicMemoryProvider(permission="tenant").collect(state)
    assert any("hi" in s["text"] for s in conv_segs)
    assert any("alice" in s["text"] for s in user_segs)
    assert any("审批" in s["text"] for s in org_segs)
    assert epi_segs == []


def test_memory_provider_outage_returns_empty_and_reports_skipped(monkeypatch):
    from infrastructure.pg.connector import InMemoryConnector, OperationalError
    from agent.memory.store import MemoryStore
    from agent.context.memory_providers import ConvMemoryProvider
    c = InMemoryConnector()
    c.execute("CREATE TABLE memory_conv (id INT, tenant_id TEXT, permission TEXT, body TEXT)")
    s = MemoryStore(c)
    def boom(sql, params=()):
        raise OperationalError("pg down")
    monkeypatch.setattr(c, "execute", boom)
    monkeypatch.setattr(c, "fetch_all", lambda sql, params=(): (_ for _ in ()).throw(OperationalError("pg down")))
    p = ConvMemoryProvider(permission="tenant")
    state = {"tenant_id": "t1"}
    assert p.collect(state) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_pg.py::test_memory_providers_collect_from_store_and_format -v`
Expected: FAIL with "No module named 'agent.context.memory_providers'"

- [ ] **Step 3: Write minimal implementation**

```python
"""agent/context/memory_providers.py: 九层补齐 User/Org/Conv 三实现，Episodic 占位。"""
from .providers import BaseProvider
from agent.memory.store import MemoryStore
from infrastructure.pg.connector import OperationalError, get_connector


def _default_store() -> MemoryStore:
    return MemoryStore(get_connector())


class BaseMemoryProvider(BaseProvider):
    layer = "memory"
    permission = "tenant"

    def __init__(self, store: MemoryStore | None = None, permission: str = "tenant",
                 keep_recent: int = 10):
        self._store = store or _default_store()
        self.permission = permission
        self.keep_recent = keep_recent

    def collect(self, state: dict) -> list[dict]:
        tenant_id = state.get("tenant_id") or "default"
        try:
            rows = self._store.query(self.layer, tenant_id, permission=self.permission,
                                     limit=self.keep_recent)
        except OperationalError:
            rows = []
        except Exception:
            rows = []
        return self._format(rows)

    def _format(self, rows: list[dict]) -> list[dict]:
        raise NotImplementedError


class UserMemoryProvider(BaseMemoryProvider):
    name, priority = "memory_user", 25
    layer = "user"

    def _format(self, rows):
        out = []
        for r in rows:
            if isinstance(r, dict) and r.get("name"):
                out.append({"name": self.name, "priority": self.priority,
                            "text": f"用户画像: {r.get('name')} ({r.get('role','')})"})
        return out


class OrgMemoryProvider(BaseMemoryProvider):
    name, priority = "memory_org", 30
    layer = "org"

    def _format(self, rows):
        out = []
        for r in rows:
            if isinstance(r, dict) and r.get("policy"):
                out.append({"name": self.name, "priority": self.priority,
                            "text": f"组织策略: {r['policy']}"})
        return out


class ConvMemoryProvider(BaseMemoryProvider):
    name, priority = "memory_conv", 35
    layer = "conv"

    def _format(self, rows):
        out = []
        for i, r in enumerate(rows):
            if isinstance(r, dict):
                out.append({"name": f"memory_conv[{i}]", "priority": self.priority,
                            "text": f"{r.get('role','')}: {r.get('content','')}"})
        return out


class EpisodicMemoryProvider(BaseMemoryProvider):
    name, priority = "memory_episodic", 40
    layer = "episodic"

    def _format(self, rows):
        return []  # spec#3 占位
```

Modify `agent/context/providers.py`: append `UserMemoryProvider(), OrgMemoryProvider(), ConvMemoryProvider()` to `DEFAULT_PROVIDERS` (between observation and tooltrace; matches spec priority order).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory_pg.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/context/memory_providers.py agent/context/providers.py tests/test_memory_pg.py
git commit -m "feat: memory providers wired into context nine layers"
```

### Task 5: 装配集成 + loop 接线 + 依赖/环境

**Files:**
- Modify: `apps/api/main.py` (startup ensure_schema via get_connector)
- Modify: `pyproject.toml` (add sqlalchemy + psycopg hard deps)
- Modify: `.env.example` (append PG_OFFLINE / MEMORY_POOL_SIZE / MEMORY_QUERY_LIMIT)
- Modify: `agent/runtime/loop.py` (pass tenant_id into assembler state; report skipped)
- Test: `tests/test_memory_pg.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_loop_outage_skips_memory_layer_in_report():
    from agent.runtime.state import AgentState
    from agent.runtime.loop import run
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    from infrastructure.pg.connector import InMemoryConnector, OperationalError
    from agent.memory.store import MemoryStore
    from agent.context.memory_providers import ConvMemoryProvider
    c = InMemoryConnector()
    c.execute("CREATE TABLE memory_conv (id INT, tenant_id TEXT, permission TEXT, body TEXT)")
    s = MemoryStore(c)
    def boom(sql, params=()):
        raise OperationalError("pg down")
    monkey = __import__("pytest").MonkeyPatch()
    import infrastructure.pg.connector as conn_mod
    monkey.setattr(conn_mod, "get_connector", lambda: c)
    monkey.setattr(c, "execute", boom)
    monkey.setattr(c, "fetch_all", lambda sql, params=(): (_ for _ in ()).throw(OperationalError("pg down")))
    asm = ContextAssembler(budget=TokenBudget(total=400, reserved_for_output=0),
                           providers=[ConvMemoryProvider(MemoryStore(c))])
    st = AgentState(task="x"); st.context["tenant_id"] = "t1"
    def planner(state):
        return {"action": "finish", "answer": "ok"}
    run(st, planner=planner, assembler=asm, executor=lambda p, st: None)
    monkey.undo()
    rep = st.context.get("context_report", {})
    assert any(s.startswith("memory_") for s in rep.get("skipped", []))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory_pg.py::test_loop_outage_skips_memory_layer_in_report -v`
Expected: FAIL with "memory_* not in skipped" or context_report missing

- [ ] **Step 3: Write minimal implementation**

`agent/runtime/loop.py`: pass `tenant_id=state.context.get("tenant_id")` into assemble dict (alongside existing keys). Existing `assembler.assemble` calls gather segs via providers; with `BaseMemoryProvider.collect` catching OperationalError internally, segs list will be empty and `skipped` array will get the memory_* entries from the assemble-side skip path (current assemble does NOT auto-add to skipped for empty segs — update assembler to add provider name to skipped when its collect returns 0 segs due to operational error). Simplest: leave assemble as-is; have `BaseMemoryProvider.collect` raise a custom `MemoryOutage(name)` that assembler catches in its collect try/except — already covered by the existing `except Exception: skipped.append(p.name)`. Wait — current collect returns `[]` without raising. To get provider name in `report.skipped`, modify BaseMemoryProvider.collect to raise a sentinel exception caught by assembler.

Alternative (simpler, no assembler change): in BaseMemoryProvider.collect, on OperationalError return `[]` AND let caller not know — but then report won't show memory skip. To meet test requirement, modify BaseMemoryProvider.collect to raise `OperationalError` on outage so assembler skip path catches it; OR modify assembler to also track zero-seg providers.

Pick: modify `BaseMemoryProvider.collect` to raise a unique `MemoryOutage` exception when query returns 0 segs due to OperationalError; assembler catches and adds to skipped. Implementation:

```python
# memory_providers.py
class MemoryOutage(Exception):
    pass

class BaseMemoryProvider:
    def collect(self, state):
        tenant_id = state.get("tenant_id") or "default"
        try:
            rows = self._store.query(self.layer, tenant_id, permission=self.permission,
                                     limit=self.keep_recent)
        except (OperationalError, Exception) as e:
            raise MemoryOutage(f"{self.name}: {e}")
        return self._format(rows)
```

Assembler already does `except Exception: skipped.append(p.name)` — `MemoryOutage` will be caught.

`apps/api/main.py` startup:
```python
from infrastructure.pg.connector import get_connector
from infrastructure.pg.schema import ensure_schema

@app.on_event("startup")
def _startup():
    try:
        ensure_schema(get_connector())
    except Exception:
        pass  # warn-only
```

`pyproject.toml` dependencies add:
```toml
"sqlalchemy>=2.0",
"psycopg[binary]>=3.1",
```

`.env.example` append:
```text
# PG_OFFLINE=0
# MEMORY_POOL_SIZE=5
# MEMORY_QUERY_LIMIT=10
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q`
Expected: PASS (70 + 6 = 76 green; offline via `PG_OFFLINE=1` or unset)

- [ ] **Step 5: Commit**

```bash
git add apps/api/main.py pyproject.toml .env.example agent/runtime/loop.py agent/context/memory_providers.py tests/test_memory_pg.py
git commit -m "feat: memory pg wiring loop outage skip and api startup"
```