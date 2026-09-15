"""Workflow状态：纯dict，保证可序列化、可追踪。"""
from typing import TypedDict, Any


class WorkflowState(TypedDict, total=False):
    expense: dict
    policy_threshold: float
    amount_ok: bool
    policy_text: str
    need_human: bool
    trace: list[str]
