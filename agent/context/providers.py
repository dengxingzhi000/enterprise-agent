"""agent/context/providers.py: 6 基础 provider，memory深度版留 spec#2."""
PRIORITY = {"system": 100, "task": 90, "tooltrace": 70, "rag": 60, "observation": 20, "conversation": 10}


class BaseProvider:
    name = "base"
    priority = 0
    def collect(self, state: dict) -> list[dict]:
        raise NotImplementedError


class SystemProvider(BaseProvider):
    name, priority = "system", PRIORITY["system"]
    def collect(self, state):
        t = state.get("system", "你是企业运维助手。")
        return [{"name": self.name, "priority": self.priority, "text": t}]


class TaskProvider(BaseProvider):
    name, priority = "task", PRIORITY["task"]
    def collect(self, state):
        return [{"name": self.name, "priority": self.priority, "text": state.get("task", "")}]


class ConversationProvider(BaseProvider):
    name, priority = "conversation", PRIORITY["conversation"]
    def __init__(self, recent: int = 5):
        self.recent = recent
    def collect(self, state):
        out = []
        for i, m in enumerate(state.get("messages", [])[-self.recent:]):
            out.append({"name": f"conversation[{i}]", "priority": self.priority,
                        "text": f"{m.get('role')}: {m.get('content')}"})
        return out


class ObservationProvider(BaseProvider):
    name, priority = "observation", PRIORITY["observation"]
    def __init__(self, recent: int = 10):
        self.recent = recent
    def collect(self, state):
        out = []
        for i, o in enumerate(state.get("observations", [])[-self.recent:]):
            out.append({"name": f"observation[{i}]", "priority": self.priority,
                        "text": f"{o.get('tool')}: {o.get('result')}"})
        return out


class RagProvider(BaseProvider):
    name, priority = "rag", PRIORITY["rag"]
    def collect(self, state):
        out = []
        for r in state.get("rag", []):
            score = r.get("score", 0.5)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.5
            tier = 40 + int(score * 20)
            tier = max(40, min(60, tier))
            out.append({"name": self.name, "priority": tier, "text": r.get("text", "")})
        return out


class ToolTraceProvider(BaseProvider):
    name, priority = "tooltrace", PRIORITY["tooltrace"]
    def collect(self, state):
        return [{"name": self.name, "priority": self.priority, "text": str(t)}
                for t in state.get("tool_calls", [])]


DEFAULT_PROVIDERS = [SystemProvider(), TaskProvider(), RagProvider(),
                     ObservationProvider(), ConversationProvider(), ToolTraceProvider()]
