"""SCM HTTP封装：5s超时 / 401刷token重试1次 / 结果截断调用方做。"""
import os
import uuid

import httpx

from .auth import TokenCache


class ScmClient:
    def __init__(self, gateway_url="", auth_url="", username="", password="", timeout=5):
        self.gateway_url = gateway_url or os.environ.get("SCM_GATEWAY_URL", "")
        self.auth_url = auth_url or os.environ.get("SCM_AUTH_URL", "")
        self.username = username or os.environ.get("SCM_USERNAME", "")
        self.password = password or os.environ.get("SCM_PASSWORD", "")
        self.timeout = int(os.environ.get("SCM_TIMEOUT_SECONDS", str(timeout)))
        self._tokens = TokenCache()

    def _send(self, method: str, path: str, **kw):
        url = self.gateway_url.rstrip("/") + path
        headers = kw.pop("headers", {})
        token = self._tokens.get()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("X-Request-Id", str(uuid.uuid4()))
        r = httpx.request(method, url, headers=headers, timeout=self.timeout, **kw)
        try:
            body = r.json()
        except Exception:
            body = {"text": r.text[:2000]}
        return (r.status_code, body)

    def _login(self):
        try:
            r = httpx.post(
                self.auth_url.rstrip("/") + "/login",
                json={"username": self.username, "password": self.password},
                timeout=self.timeout,
            )
            data = r.json()
            token = data.get("token", "")
            if token:
                self._tokens.set(token, int(data.get("expires_in", 3600)))
        except Exception:
            pass

    def get(self, path: str, params: dict | None = None):
        code, body = self._send("GET", path, params=params or {})
        if code == 401:
            self._login()
            code, body = self._send("GET", path, params=params or {})
        return (code, body)

    @classmethod
    def from_env(cls):
        return cls()
