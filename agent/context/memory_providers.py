"""agent/context/memory_providers.py: 九层补齐 User/Org/Conv 三实现，Episodic 占位。"""
from agent.memory.store import MemoryStore
from infrastructure.pg.connector import OperationalError


class MemoryOutage(Exception):
    pass


def _default_store() -> MemoryStore:
    from infrastructure.pg.connector import get_connector
    return MemoryStore(get_connector())


def _get_base():
    from .providers import BaseProvider
    return BaseProvider


class BaseMemoryProvider(_get_base()):
    layer = "memory"
    permission = "tenant"

    def __init__(self, store: MemoryStore | None = None, permission: str = "tenant",
                 keep_recent: int = 10):
        self._store = store if store is not None else _default_store()
        self.permission = permission
        self.keep_recent = keep_recent

    def collect(self, state: dict) -> list[dict]:
        tenant_id = state.get("tenant_id") or "default"
        try:
            rows = self._fetch(tenant_id)
        except OperationalError as e:
            raise MemoryOutage(f"{self.name}: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise MemoryOutage(f"{self.name}: {e}") from e
        body_rows = [r["body"] for r in rows if isinstance(r, dict) and r.get("body")]
        return self._format(body_rows)

    def _fetch(self, tenant_id: str) -> list[dict]:
        """Query connector directly so OperationalError surfaces.

        MemoryStore.query swallows OperationalError for graceful degradation;
        context providers must propagate it as MemoryOutage.
        """
        import json
        connector = self._store._c
        if connector is None:
            return []
        sql = (
            f"SELECT body, tenant_id, permission FROM memory_{self.layer} "
            f"WHERE tenant_id = ? AND permission = ? ORDER BY updated_at DESC LIMIT ?"
        )
        rows = connector.fetch_all(sql, (tenant_id, self.permission, self.keep_recent))
        result: list[dict] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if r.get("tenant_id") != tenant_id or r.get("permission") != self.permission:
                continue
            body = r.get("body")
            if body is None:
                continue
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except (TypeError, ValueError):
                    continue
            if not isinstance(body, dict):
                continue
            result.append(dict(r, body=body))
            if len(result) >= self.keep_recent:
                break
        return result

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
