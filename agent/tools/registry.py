"""Tool Registry: 企业工具生态的入口。Stage2先内存版，Stage5加Policy，Stage8换MCP。"""
from dataclasses import dataclass
from collections.abc import Callable


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[[dict], object]


class Registry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def call(self, name: str, args: dict):
        return self._tools[name].func(args or {})
