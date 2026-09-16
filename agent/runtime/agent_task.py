"""AgentTask 包装层 + 状态机 + history。"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .state import AgentState
from .status import ALLOWED_TRANSITIONS


class AgentTaskError(Exception):
    pass


class InvalidTransition(AgentTaskError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentTask:
    task_id: str
    tenant_id: str
    state: AgentState
    status: str = "pending"
    checkpoint_id: str | None = None
    token_usage: dict = field(default_factory=lambda: {"input": 0, "output": 0, "total": 0})
    cost: float = 0.0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    history: list[dict] = field(default_factory=list)

    @classmethod
    def from_state(cls, state: AgentState, tenant_id: str = "default") -> "AgentTask":
        tid = getattr(state, "task_id", None) or str(uuid.uuid4())
        return cls(task_id=tid, tenant_id=tenant_id, state=state)

    def transition(self, to: str, reason: str = "") -> None:
        allowed = ALLOWED_TRANSITIONS.get(self.status, set())
        if to not in allowed:
            raise InvalidTransition(f"{self.status} -> {to} not allowed")
        prev = self.status
        self.status = to
        self.updated_at = _now()
        self.history.append({"from": prev, "to": to, "reason": reason, "ts": self.updated_at})

    def attach_checkpoint(self, thread_id: str) -> None:
        if not thread_id:
            raise AgentTaskError("thread_id required")
        self.checkpoint_id = thread_id
        self.updated_at = _now()

    def record_tokens(self, input_n: int, output_n: int) -> None:
        if input_n < 0 or output_n < 0:
            raise ValueError("token counts must be >= 0")
        self.token_usage["input"] += input_n
        self.token_usage["output"] += output_n
        self.token_usage["total"] += input_n + output_n
        self.updated_at = _now()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "checkpoint_id": self.checkpoint_id,
            "token_usage": dict(self.token_usage),
            "cost": self.cost,
            "answer": self.state.answer,
            "history": list(self.history),
        }