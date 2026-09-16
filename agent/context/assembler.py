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
        skipped: list[str] = []
        for p in self.providers:
            try:
                for s in p.collect(state) or []:
                    s = dict(s)
                    s["tokens"] = self.counter.count(s.get("text", ""))
                    segs.append(s)
            except Exception:  # noqa: BLE001 - 单层故障跳过，不阻断
                skipped.append(p.name)
        fits, usage, dropped = self.budget.check(segs)
        # 极端兜底：system/task 永不丢弃（即使仍超预算，后续靠截断收敛）
        dropped = [d for d in dropped if d.get("name") not in ("system", "task")]
        kept_names = {d["name"] for d in dropped}
        kept = [s for s in segs if s["name"] not in kept_names and not s.get("skipped")]
        # 仍超：截最低优先级保留段尾部（用排序副本选 victim，保持 kept 原序）
        total = sum(s["tokens"] for s in kept)
        if total > self.budget.available and kept:
            ordered = sorted(kept, key=lambda s: s.get("priority", 0))
            victim = ordered[0]
            over = total - self.budget.available
            cut = max(0, len(victim["text"]) - over * 4)
            victim["text"] = victim["text"][:cut]
            victim["tokens"] = self.counter.count(victim["text"])
            victim["truncated"] = True
        msgs: list[dict] = []
        if kept:
            sys_idx = next((i for i, s in enumerate(kept) if s.get("name") == "system"), 0)
            msgs.append({"role": "system", "content": kept[sys_idx]["text"]})
            for i, s in enumerate(kept):
                if i == sys_idx:
                    continue
                msgs.append({"role": "user", "content": s["text"]})
        report = {"usage": sum(s["tokens"] for s in kept), "dropped": [d["name"] for d in dropped],
                  "counter_used": "tiktoken" if self.counter_used.startswith("tiktoken") else "heuristic",
                  "fits": fits, "skipped": skipped}
        return msgs, report
