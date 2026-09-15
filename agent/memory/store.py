"""五层记忆内存版：Conversation/Task/User/Org/Episodic。Redis/pgvector是下一步替换存储。"""


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
    def __init__(self):
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
