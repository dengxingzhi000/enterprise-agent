"""agent/context/budget.py"""


class TokenBudget:
    def __init__(self, total: int = 8000, reserved_for_output: int = 1000):
        self.total = total if total and total > 0 else 10 ** 9
        self.reserved = reserved_for_output or 0

    @property
    def available(self) -> int:
        return max(0, self.total - self.reserved)

    def check(self, segments: list[dict]) -> tuple[bool, int, list[dict]]:
        usage = sum(s.get("tokens", 0) for s in segments)
        if usage <= self.available:
            return True, usage, []
        dropped: list[dict] = []
        kept = sorted(segments, key=lambda s: s.get("priority", 0))
        while kept and sum(s.get("tokens", 0) for s in kept) > self.available:
            dropped.append(kept.pop(0))
        return False, usage, dropped
