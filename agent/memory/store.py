"""五层记忆：内存版（dict 兜底）+ connector 注入版并存，向后兼容 tests/test_memory.py。

LAYERS = ("user", "org", "conv", "task", "episodic")，对应五张 memory_<layer> 表。
"""
import json
import warnings

from infrastructure.pg.connector import OperationalError


def _score(query: str, text: str) -> float:
    s = 0.0
    for i in range(len(query) - 1):
        if query[i:i + 2] in text:
            s += 1.0
    for tok in ("PO-001", "采购", "报销", "5xx", "5000"):
        if tok in query and tok in text:
            s += 5.0
    return s


class MemoryStore:
    LAYERS = ("user", "org", "conv", "task", "episodic")

    def __init__(self, connector=None):
        self._c = connector
        self._conversations: dict[tuple, list[dict]] = {}
        self._tasks: dict[str, dict] = {}
        self._episodic: dict[tuple, list[str]] = {}
        self._users: dict[str, dict] = {}
        self._orgs: dict[str, dict] = {}

    # --- Conversation (短期) ---
    def save_conversation(self, user_id: str, tenant_id: str, role: str, content: str):
        self._conversations.setdefault((user_id, tenant_id), []).append(
            {"role": role, "content": content})

    def get_conversation(self, user_id: str, tenant_id: str, limit: int = 10) -> list[dict]:
        return self._conversations.get((user_id, tenant_id), [])[-limit:]

    # --- Task ---
    def save_task(self, task_id: str, summary: str, status: str = "open", result: str = ""):
        self._tasks[task_id] = {"task_id": task_id, "summary": summary,
                                "status": status, "result": result}

    def get_task(self, task_id: str) -> dict:
        return self._tasks[task_id]

    # --- Episodic (情景) ---
    def save_episodic(self, user_id: str, tenant_id: str, event: str):
        self._episodic.setdefault((user_id, tenant_id), []).append(event)

    def recall_episodic(self, user_id: str, tenant_id: str, query: str, top_k: int = 3) -> list[str]:
        events = self._episodic.get((user_id, tenant_id), [])
        ranked = sorted(events, key=lambda e: _score(query, e), reverse=True)
        return [e for e in ranked if _score(query, e) > 0][:top_k]

    # --- User / Org (长期) ---
    def save_user_profile(self, user_id: str, profile: dict):
        self._users[user_id] = profile

    def get_user_profile(self, user_id: str) -> dict:
        return self._users.get(user_id, {})

    def save_org_memory(self, tenant_id: str, mem: dict):
        self._orgs[tenant_id] = mem

    def get_org_memory(self, tenant_id: str) -> dict:
        return self._orgs.get(tenant_id, {})

    # --- Connector 注入版（PG/InMemory 共用接口，tenant 隔离 + permission 过滤） ---
    def put(self, layer: str, tenant_id: str, body: dict, department: str | None = None,
            permission: str = "public", version: int = 1, key: str | None = None) -> None:
        if self._c is None:
            return
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
        except OperationalError as e:
            warnings.warn(f"memory put outage layer={layer}: {e}")

    def query(self, layer: str, tenant_id: str, permission: str = "public",
              department: str | None = None, limit: int = 10) -> list[dict]:
        if self._c is None:
            return []
        if layer not in self.LAYERS:
            raise ValueError(f"unknown layer: {layer}")
        where_parts = ["tenant_id = ?", "permission = ?"]
        params: list = [tenant_id, permission]
        if department is not None:
            where_parts.append("department = ?")
            params.append(department)
        params.append(limit)
        try:
            rows = self._c.fetch_all(
                f"SELECT body, tenant_id, permission, department FROM memory_{layer} "
                f"WHERE {' AND '.join(where_parts)} "
                f"ORDER BY updated_at DESC LIMIT ?",
                tuple(params),
            )
        except OperationalError:
            return []
        result: list[dict] = []
        for r in rows:
            if r.get("tenant_id") != tenant_id:
                continue
            if r.get("permission") != permission:
                continue
            if department is not None and r.get("department") != department:
                continue
            body = r.get("body")
            if body is None:
                continue
            try:
                parsed = json.loads(body)
            except (TypeError, ValueError):
                continue
            out = dict(r)
            out["body"] = parsed
            result.append(out)
            if len(result) >= limit:
                break
        return result

    def get(self, layer: str, tenant_id: str, permission: str = "public") -> list[dict]:
        return self.query(layer, tenant_id, permission=permission)
