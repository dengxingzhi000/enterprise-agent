"""tests/test_memory_pg.py: Task 1 + Task 2 + Task 3 + Task 4 - connector + schema + MemoryStore + MemoryProviders."""


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


def test_ensure_schema_idempotent_on_inmemory(monkeypatch):
    from infrastructure.pg.connector import InMemoryConnector
    from infrastructure.pg.schema import ensure_schema
    c = InMemoryConnector()
    ensure_schema(c)
    ensure_schema(c)
    rows = c.fetch_all("SELECT 1")
    assert rows is not None


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


def test_memory_store_put_warns_on_outage():
    import warnings
    from infrastructure.pg.connector import InMemoryConnector, OperationalError
    from agent.memory.store import MemoryStore
    c = InMemoryConnector()
    s = MemoryStore(c)
    def boom(sql, params=()):
        raise OperationalError("pg down")
    c.execute = boom  # 直接覆盖
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        s.put("user", "tenant_a", {"x": 1})
    assert any("memory put outage" in str(w.message) and "user" in str(w.message)
               for w in captured), f"no outage warning captured, got: {[str(w.message) for w in captured]}"


def test_memory_providers_collect_from_store_and_format(monkeypatch):
    import infrastructure.pg.connector as conn_mod
    from infrastructure.pg.connector import InMemoryConnector
    from agent.memory.store import MemoryStore
    from agent.context.memory_providers import (ConvMemoryProvider, UserMemoryProvider,
                                                  OrgMemoryProvider, EpisodicMemoryProvider)
    c = InMemoryConnector()
    monkeypatch.setattr(conn_mod, "get_connector", lambda: c)
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


def test_memory_provider_outage_raises_memory_outage(monkeypatch):
    from infrastructure.pg.connector import InMemoryConnector, OperationalError
    from agent.memory.store import MemoryStore
    from agent.context.memory_providers import ConvMemoryProvider, MemoryOutage
    c = InMemoryConnector()
    c.execute("CREATE TABLE memory_conv (id INT, tenant_id TEXT, permission TEXT, body TEXT)")
    s = MemoryStore(c)
    def boom(sql, params=()):
        raise OperationalError("pg down")
    monkeypatch.setattr(c, "execute", boom)
    monkeypatch.setattr(c, "fetch_all", lambda sql, params=(): (_ for _ in ()).throw(OperationalError("pg down")))
    p = ConvMemoryProvider(store=s, permission="tenant")
    state = {"tenant_id": "t1"}
    import pytest
    with pytest.raises(MemoryOutage):
        p.collect(state)
