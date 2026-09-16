"""agent/context/assembler.py"""
from .budget import TokenBudget
from .counter import get_counter
from .providers import get_default_providers


class ContextAssembler:
    def __init__(self, budget: TokenBudget | None = None, providers=None, counter=None,
                 trigger_ratio: float = 0.8,
                 conversation_keep_recent: int = 3,
                 observation_keep_recent: int = 5):
        self.budget = budget or TokenBudget()
        self.providers = providers if providers is not None else get_default_providers()
        self.counter = counter or get_counter()
        self.counter_used = type(self.counter).__name__.replace("Counter", "").lower()
        self.trigger_ratio = trigger_ratio
        self.conv_keep = conversation_keep_recent
        self.obs_keep = observation_keep_recent
    def assemble(self, state: dict) -> tuple[list[dict], dict]:
        segs: list[dict] = []
        skipped: list[str] = []
        for p in self.providers:
            try:
                for s in p.collect(state) or []:
                    s = dict(s)
                    s["tokens"] = self.counter.count(s.get("text", ""))
                    s["idx"] = len(segs)
                    segs.append(s)
            except Exception:  # noqa: BLE001 - 单层故障跳过，不阻断
                skipped.append(p.name)
        usage = sum(s["tokens"] for s in segs)
        compressed: list[dict] = []
        if usage > self.trigger_ratio * self.budget.available and self.budget.available > 0:
            by_layer: dict[str, list[dict]] = {}
            for s in segs:
                by_layer.setdefault(s["name"].split("[")[0].split(":")[0], []).append(s)
            layer_keep = {"conversation": self.conv_keep, "observation": self.obs_keep}
            new_segs: list[dict] = []
            for layer, layer_segs in by_layer.items():
                if layer not in layer_keep or len(layer_segs) <= layer_keep[layer]:
                    new_segs.extend(layer_segs)
                    continue
                target_provider = next((p for p in self.providers if p.name == layer), None)
                if target_provider is None:
                    new_segs.extend(layer_segs)
                    continue
                try:
                    kept, summary = target_provider.compress(layer_segs, layer_keep[layer])
                    if summary is None:
                        new_segs.extend(layer_segs)
                        continue
                    summary = dict(summary)
                    summary["tokens"] = self.counter.count(summary.get("text", ""))
                    summary["idx"] = len(new_segs)
                    new_segs.append(summary)
                    for k in kept:
                        k = dict(k); k["idx"] = len(new_segs); new_segs.append(k)
                    compressed.append({"provider": layer,
                                       "before": len(layer_segs),
                                       "after": 1 + len(kept),
                                       "kept": len(kept)})
                except Exception:
                    skipped.append(target_provider.name)
                    new_segs.extend(layer_segs)
            segs = new_segs
        fits, usage, dropped = self.budget.check(segs)
        # 极端兜底：system/task 永不丢弃（即使仍超预算，后续靠截断收敛）
        dropped = [d for d in dropped if d.get("name") not in ("system", "task")]
        dropped_idx = {d["idx"] for d in dropped if "idx" in d}
        kept = [s for s in segs if s.get("idx") not in dropped_idx and not s.get("skipped")]
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
                  "fits": fits, "skipped": skipped, "compressed": compressed}
        return msgs, report
