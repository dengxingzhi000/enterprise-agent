"""agent/context/assembler.py"""
from .budget import TokenBudget
from .counter import get_counter
from .providers import DEFAULT_PROVIDERS


class ContextAssembler:
    def __init__(self, budget: TokenBudget | None = None, providers=None, counter=None):
        self.budget = budget or TokenBudget()
        self.providers = providers if providers is not None else DEFAULT_PROVIDERS
        self.counter = counter or get_counter()
        self.counter_used = type(self.counter).__name__.replace("Counter", "").lower()
    def assemble(self, state: dict) -> tuple[list[dict], dict]:
        segs: list[dict] = []
        for p in self.providers:
            try:
                for s in p.collect(state) or []:
                    s = dict(s)
                    s["tokens"] = self.counter.count(s.get("text", ""))
                    segs.append(s)
            except Exception:  # noqa: BLE001 - 单层故障跳过，不阻断
                segs.append({"name": f"{p.name}:skip", "priority": 0, "tokens": 0,
                             "text": "", "skipped": True})
        fits, usage, dropped = self.budget.check(segs)
        # 极端兜底：system/task 永不丢弃（即使仍超预算，后续靠截断收敛）
        dropped = [d for d in dropped if d.get("name") not in ("system", "task")]
        kept_names = {d["name"] for d in dropped}
        kept = [s for s in segs if s["name"] not in kept_names and not s.get("skipped")]
        # 仍超：截最低优先级保留段尾部
        total = sum(s["tokens"] for s in kept)
        if total > self.budget.available and kept:
            kept.sort(key=lambda s: s.get("priority", 0))
            over = total - self.budget.available
            victim = kept[0]
            cut = max(0, len(victim["text"]) - over * 4)
            victim["text"] = victim["text"][:cut]
            victim["tokens"] = self.counter.count(victim["text"])
            victim["truncated"] = True
        msgs = [{"role": "system", "content": kept[0]["text"]}] if kept else []
        for s in kept[1:]:
            msgs.append({"role": "user", "content": s["text"]})
        report = {"usage": sum(s["tokens"] for s in kept), "dropped": [d["name"] for d in dropped],
                  "counter_used": "tiktoken" if self.counter_used.startswith("tiktoken") else "heuristic",
                  "fits": fits}
        return msgs, report
