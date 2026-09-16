"""Durable guard：超时+重试+幂等+循环检测（节点外，与 LangGraph 解耦）。"""
import concurrent.futures
import time


class IdempotencyStore:
    def __init__(self):
        self._mem: dict[str, object] = {}
        self._redis = None
        try:
            import os
            import redis  # type: ignore
            url = os.environ.get("REDIS_URL", "")
            if url:
                self._redis = redis.Redis.from_url(url, socket_timeout=1)
        except Exception:
            self._redis = None
    def get(self, key: str):
        if key in self._mem:
            return self._mem[key]
        if self._redis is not None:
            try:
                v = self._redis.get(key)
                return v.decode() if isinstance(v, bytes) else v
            except Exception:
                return None
        return None
    def put(self, key: str, value: object) -> None:
        self._mem[key] = value
        if self._redis is not None:
            try:
                self._redis.set(key, str(value), ex=3600)
            except Exception:
                pass


class LoopDetector:
    def __init__(self, limit: int = 8):
        self.limit = limit
        self._counts: dict[str, int] = {}
    def visit(self, node: str) -> bool:
        self._counts[node] = self._counts.get(node, 0) + 1
        return self._counts[node] > self.limit


def _call_once(func, timeout: float):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(func)
        return fut.result(timeout=timeout)


def run_with_retry(key: str, func, store: IdempotencyStore | None = None, retries: int = 3, timeout: float = 5.0, backoff: float = 0.0):
    # 测试用 backoff=0.0 保持快速；生产调用传 backoff=1.0 得到 1s/2s/4s 指数退避。
    if store is not None:
        cached = store.get(key)
        if cached is not None:
            return cached
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            out = _call_once(func, timeout)
            if store is not None:
                store.put(key, out)
            return out
        except Exception as e:  # noqa: BLE001 - 必须转重试/回退
            last = e
            if attempt < retries and backoff > 0:
                time.sleep(backoff * (2 ** (attempt - 1)))
    raise last  # type: ignore[misc]
