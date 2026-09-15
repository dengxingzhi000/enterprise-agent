"""AgentState: 整个 Runtime 唯一真相来源。"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    task: str
    messages: list[dict] = field(default_factory=list)
    plan: dict | None = None
    observations: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    memory: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    iteration: int = 0
    status: str = "pending"  # pending | running | done | failed
    answer: str = ""
