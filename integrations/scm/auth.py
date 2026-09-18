"""SCM auth: login换token + tenant映射。LLM永远摸不到token。"""
import json
import os
import time
import warnings

_DEFAULT_TENANT_MAP = {"t1": "tenant_001"}


def load_tenant_map() -> dict:
    raw = os.environ.get("SCM_TENANT_MAP", "")
    if not raw:
        return dict(_DEFAULT_TENANT_MAP)
    try:
        m = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        warnings.warn("SCM_TENANT_MAP invalid JSON, falling back to defaults", stacklevel=2)
        return dict(_DEFAULT_TENANT_MAP)
    if not isinstance(m, dict) or not m:
        warnings.warn("SCM_TENANT_MAP must be non-empty JSON object, falling back to defaults",
                      stacklevel=2)
        return dict(_DEFAULT_TENANT_MAP)
    return m


def to_scm_tenant(agent_tenant: str) -> str:
    m = load_tenant_map()
    if agent_tenant not in m:
        warnings.warn(f"no scm tenant mapping for {agent_tenant!r}, passing through",
                      stacklevel=2)
        return agent_tenant
    return m[agent_tenant]


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
