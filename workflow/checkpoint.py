"""Checkpointer 工厂：PG 优先，内存兜底，保证离线测试不断。统一 get/put 接口。"""
import warnings


class MemoryCheckpointer:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def put(self, thread_id: str, state: dict) -> None:
        self._store[thread_id] = dict(state)

    def get(self, thread_id: str) -> dict | None:
        v = self._store.get(thread_id)
        return dict(v) if v is not None else None


def _config_for(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _unwrap_checkpoint(raw):
    if raw is None:
        return None
    if isinstance(raw, dict) and "channel_values" not in raw and "checkpoint" not in raw:
        # Plain state dict (e.g. mock saver returning state directly).
        return dict(raw)
    ckpt = getattr(raw, "checkpoint", None)
    if isinstance(ckpt, dict):
        return dict(ckpt)
    if isinstance(raw, dict) and isinstance(raw.get("checkpoint"), dict):
        return dict(raw["checkpoint"])
    if isinstance(raw, dict):
        return dict(raw)
    return None


class _SaverAdapter:
    """把 langgraph 原生 saver 包成 get/put，并保留原生对象做真 checkpoint。

    put/get(thread_id, state) 为兼容接口，内部委托原生 saver 的
    put(config, checkpoint, ...)/get_tuple(config)（RunnableConfig
    configurable.thread_id）。内存 mirror 仅作离线兜底。
    """

    def __init__(self, inner):
        self._inner = inner
        self._mem: dict[str, dict] = {}

    @property
    def native(self):
        return self._inner

    @property
    def is_native(self) -> bool:
        inner = self._inner
        return hasattr(inner, "get_tuple") and hasattr(inner, "put")

    def get_tuple(self, config: dict):
        """原生形状透传，供 LangGraph 编译时使用。"""
        return self._inner.get_tuple(config)

    def put(self, thread_id: str, state: dict) -> None:
        payload = dict(state)
        # 离线 mirror 先行，保证原生失败时仍可读。
        self._mem[thread_id] = dict(payload)
        inner = self._inner
        if not hasattr(inner, "put"):
            return
        config = _config_for(thread_id)
        try:
            try:
                inner.put(config, dict(payload), {}, {})
            except TypeError:
                inner.put(config, dict(payload))
        except Exception as exc:
            warnings.warn(f"native checkpointer put failed, using in-memory mirror: {exc}")

    def get(self, thread_id: str) -> dict | None:
        inner = self._inner
        if hasattr(inner, "get_tuple"):
            config = _config_for(thread_id)
            try:
                raw = inner.get_tuple(config)
                unwrapped = _unwrap_checkpoint(raw)
                if unwrapped is not None:
                    self._mem[thread_id] = dict(unwrapped)
                    return dict(unwrapped)
            except Exception as exc:
                warnings.warn(f"native checkpointer get failed, using in-memory mirror: {exc}")
        v = self._mem.get(thread_id)
        return dict(v) if v is not None else None


def get_checkpointer(dsn: str | None = None):
    import os
    dsn = dsn or os.environ.get("PG_DSN") or os.environ.get("POSTGRES_DSN")
    if dsn:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore
            saver = PostgresSaver.from_conn_string(dsn)
            saver.setup()
            return _SaverAdapter(saver)
        except Exception as exc:
            warnings.warn(f"PostgresSaver unavailable ({exc}), falling back to memory saver")
    try:
        from langgraph.checkpoint.memory import MemorySaver  # type: ignore
        return _SaverAdapter(MemorySaver())
    except Exception as exc:
        warnings.warn(f"langgraph saver unavailable ({exc}), using in-memory checkpointer")
        return MemoryCheckpointer()
