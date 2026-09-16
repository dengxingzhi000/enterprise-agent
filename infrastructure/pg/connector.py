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

    def ensure_schema(self) -> None: ...


class InMemoryConnector(BaseConnector):
    def __init__(self):
        self._tables: dict[str, list[dict]] = {}
        self._cols: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _resolve_table(sql: str) -> str:
        sql_low = sql.strip().lower()
        for kw in ("insert into", "select * from", "select from", "from"):
            idx = sql_low.find(kw)
            if idx >= 0:
                rest = sql_low[idx + len(kw):].lstrip()
                return rest.split()[0].rstrip(";").rstrip(",")
        return "x"

    @staticmethod
    def _parse_create_cols(sql_strip: str) -> list[str]:
        open_paren = sql_strip.find("(")
        close_paren = sql_strip.rfind(")")
        if open_paren < 0 or close_paren < 0 or close_paren <= open_paren:
            return []
        cols_sql = sql_strip[open_paren + 1: close_paren]
        cols: list[str] = []
        for part in cols_sql.split(","):
            tok = part.strip().split()
            if tok:
                cols.append(tok[0])
        return cols

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._lock:
            sql_strip = sql.strip()
            low = sql_strip.lower()
            if low.startswith("create table"):
                tname = self._resolve_table(sql_strip)
                cols = self._parse_create_cols(sql_strip)
                self._tables.setdefault(tname, [])
                self._cols[tname] = cols
            elif low.startswith("insert into"):
                tname = self._resolve_table(sql_strip)
                cols = self._cols.get(tname) or [
                    f"c{i}" for i in range(len(params))
                ]
                row = dict(zip(cols, params))
                self._tables.setdefault(tname, []).append(row)

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        with self._lock:
            tname = self._resolve_table(sql)
            return [dict(r) for r in self._tables.get(tname, [])]

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def healthcheck(self) -> bool:
        return True

    def ensure_schema(self) -> None:
        return None


class PGConnector(BaseConnector):
    def __init__(self, dsn: str, pool_size: int = 5):
        from sqlalchemy import create_engine
        self._engine = create_engine(
            dsn, pool_size=pool_size, pool_pre_ping=True, future=True
        )
        self._dsn = dsn

    def _run(self, op: str, sql: str, params: Sequence[Any] = ()):
        from sqlalchemy import text
        last: Exception | None = None
        for attempt in range(1, 5):
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
                if attempt < 4:
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

    def ensure_schema(self) -> None:
        from .schema import ensure_schema as _ensure
        _ensure(self)


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
