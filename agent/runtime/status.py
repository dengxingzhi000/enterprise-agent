"""状态机允许转换表。"""
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending":   {"running", "cancelled"},
    "running":   {"paused", "done", "failed", "cancelled"},
    "paused":    {"running", "cancelled"},
    "done":      set(),
    "failed":    set(),
    "cancelled": set(),
}