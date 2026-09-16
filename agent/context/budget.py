"""agent/context/budget.py"""


class TokenBudget:
    def __init__(self, total: int = 8000, reserved_for_output: int = 1000):
        self.total = total if total and total > 0 else 10 ** 9
        self.reserved = reserved_for_output or 0

    @property
    def available(self) -> int:
        return max(0, self.total - self.reserved)

    def check(self, segments: list[dict]) -> tuple[bool, int, list[dict]]:
        """检查分段是否在预算内，按优先级从低到高丢弃。

        返回 (fits, usage, dropped)：usage 为丢弃前（PRE-drop）总量；
        调用方用 dropped 段名过滤原 segments 即得 kept。
        """
        usage = sum(s.get("tokens", 0) for s in segments)
        if usage <= self.available:
            return True, usage, []
        dropped: list[dict] = []
        kept = sorted(segments, key=lambda s: s.get("priority", 0))
        while kept and sum(s.get("tokens", 0) for s in kept) > self.available:
            dropped.append(kept.pop(0))
        return False, usage, dropped
