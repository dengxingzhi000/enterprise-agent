"""tests/test_memory_pg.py: Task 1 + Task 2 + Task 3 - connector + schema + MemoryStore."""


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
