"""tests/test_memory_pg.py: Task 1 + Task 2 - InMemoryConnector + ensure_schema."""


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
