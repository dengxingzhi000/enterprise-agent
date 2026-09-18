"""SCM HTTP封装：5s超时 / 401刷token重试1次 / 5xx/连接错重试1次 / 结果截断调用方做。"""
import contextvars
import os
import time as _time
import uuid

import httpx

from observability.tracing import Tracer

from .auth import TokenCache

scm_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "scm_trace_id", default=None
)


class ScmClient:
    def __init__(self, gateway_url="", auth_url="", username="", password="", timeout=5, backoff_seconds=None):
        self.gateway_url = gateway_url or os.environ.get("SCM_GATEWAY_URL", "")
        self.auth_url = auth_url or os.environ.get("SCM_AUTH_URL", "")
        self.username = username or os.environ.get("SCM_USERNAME", "")
        self.password = password or os.environ.get("SCM_PASSWORD", "")
        self.timeout = int(os.environ.get("SCM_TIMEOUT_SECONDS", str(timeout)))
        self.backoff_seconds = backoff_seconds if backoff_seconds is not None else float(
            os.environ.get("SCM_RETRY_BACKOFF_SECONDS", "0.3"))
        self._tokens = TokenCache()

    def _send(self, method: str, path: str, **kw):
        url = self.gateway_url.rstrip("/") + path
        headers = kw.pop("headers", {})
        token = self._tokens.get()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("X-Request-Id", str(uuid.uuid4()))
        tid = scm_trace_id.get()
        if tid and Tracer._shared is not None:
            try:
                Tracer._shared.log_event(tid, "scm_call",
                                         {"method": method, "path": path})
            except Exception:
                pass
        r = httpx.request(method, url, headers=headers, timeout=self.timeout, **kw)
        try:
            body = r.json()
        except Exception:
            body = {"text": r.text[:2000]}
        if tid and Tracer._shared is not None:
            try:
                Tracer._shared.log_event(tid, "scm_result",
                                         {"method": method, "path": path,
                                          "code": r.status_code})
            except Exception:
                pass
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
        params = params or {}
        try:
            code, body = self._send("GET", path, params=params)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if self.backoff_seconds > 0:
                _time.sleep(self.backoff_seconds)
            try:
                code, body = self._send("GET", path, params=params)
            except (httpx.ConnectError, httpx.TimeoutException) as e2:
                return (0, {"error": f"transport after retry: {e2}", "path": path})
            return (code, body)

        if 500 <= code < 600:
            if self.backoff_seconds > 0:
                _time.sleep(self.backoff_seconds)
            code, body = self._send("GET", path, params=params)
            if code == 0 or 500 <= code < 600:
                return (0, {"error": f"5xx after retry: {code}", "path": path})

        if code == 401:
            self._login()
            try:
                code, body = self._send("GET", path, params=params)
            except (httpx.ConnectError, httpx.TimeoutException) as e2:
                return (0, {"error": f"transport after 401-retry: {e2}", "path": path})
        return (code, body)

    @classmethod
    def from_env(cls):
        return cls()
