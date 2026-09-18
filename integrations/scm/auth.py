"""SCM auth: login换token + tenant映射。LLM永远摸不到token。"""
import json
import os
import time


def load_tenant_map() -> dict:
    raw = os.environ.get("SCM_TENANT_MAP", '{"t1":"tenant_001"}')
    try:
        return json.loads(raw)
    except Exception:
        return {"t1": "tenant_001"}


def to_scm_tenant(agent_tenant: str) -> str:
    return load_tenant_map().get(agent_tenant, agent_tenant)


class TokenCache:
    def __init__(self):
        self.token = ""
        self.expires_at = 0.0

    def get(self) -> str:
        if self.token and time.time() < self.expires_at - 60:
            return self.token
        return ""

    def set(self, token: str, ttl: int = 3600):
        self.token = token
        self.expires_at = time.time() + ttl
