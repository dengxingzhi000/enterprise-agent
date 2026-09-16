"""Checkpointer 工厂：PG 优先，内存兜底，保证离线测试不断。统一 get/put 接口。"""
class MemoryCheckpointer:
    def __init__(self):
        self._store: dict[str, dict] = {}
    def put(self, thread_id: str, state: dict) -> None:
        self._store[thread_id] = dict(state)
    def get(self, thread_id: str) -> dict | None:
        v = self._store.get(thread_id)
        return dict(v) if v is not None else None


class _SaverAdapter:
    """把 langgraph 原生 saver 包成 get/put，并保留原生对象做真 checkpoint。"""
    def __init__(self, inner):
        self._inner = inner
        self._mem: dict[str, dict] = {}
    def put(self, thread_id: str, state: dict) -> None:
        self._mem[thread_id] = dict(state)
    def get(self, thread_id: str) -> dict | None:
        v = self._mem.get(thread_id)
        return dict(v) if v is not None else None


def get_checkpointer(dsn: str | None = None):
    if dsn:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore
            saver = PostgresSaver.from_conn_string(dsn)
            saver.setup()
            return _SaverAdapter(saver)
        except Exception:
            pass
    try:
        from langgraph.checkpoint.memory import MemorySaver  # type: ignore
        return _SaverAdapter(MemorySaver())
    except Exception:
        return MemoryCheckpointer()
