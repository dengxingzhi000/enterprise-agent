"""内存Tracer：User→Planner→Tool→Reflection→Final全链路。OTel/Prom是下一步。"""
import time
from itertools import count


class Tracer:
    _shared: "Tracer | None" = None

    def __init__(self):
        self._traces: dict[str, dict] = {}
        self._seq = count(1)
        Tracer._shared = self

    def start_trace(self, task: str) -> str:
        tid = f"tr-{next(self._seq)}"
        self._traces[tid] = {"id": tid, "task": task, "events": [],
                             "status": "running", "start": time.perf_counter()}
        return tid

    def log_event(self, trace_id: str, stage: str, data: dict):
        self._traces[trace_id]["events"].append(
            {"stage": stage, "data": data or {}, "ts": time.perf_counter()})

    def end_trace(self, trace_id: str, status: str = "done"):
        tr = self._traces[trace_id]
        tr["status"] = status
        tr["end"] = time.perf_counter()
        tr["latency_ms"] = (tr["end"] - tr["start"]) * 1000

    def get_trace(self, trace_id: str) -> dict:
        tr = self._traces[trace_id]
        tr.setdefault("latency_ms", 0.0)
        return tr
