"""agent/runtime/counter.py: Token Counter + Pricing（Tiktoken 优先 / 启发兜底）。"""
import os
import warnings
from dataclasses import dataclass


class EncodingUnavailable(Exception):
    pass


@dataclass
class Pricing:
    model: str
    input_per_1k: float
    output_per_1k: float


class BaseCounter:
    def count_messages(self, messages: list[dict]) -> dict:
        raise NotImplementedError


class HeuristicCounter(BaseCounter):
    def count_messages(self, messages: list[dict]) -> dict:
        total = 0
        for m in messages:
            text = (m.get("content") or "") if isinstance(m, dict) else str(m)
            total += max(1, len(text) // 4)
        return {"input": total, "output": 0}


class TiktokenCounter(BaseCounter):
    def __init__(self, encoding_name: str = "cl100k_base"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding_name)
        except Exception as e:  # noqa: BLE001
            raise EncodingUnavailable(str(e))

    def count_messages(self, messages: list[dict]) -> dict:
        total = 0
        for m in messages:
            text = (m.get("content") or "") if isinstance(m, dict) else str(m)
            total += len(self._enc.encode(text))
        return {"input": total, "output": 0}


def get_counter() -> BaseCounter:
    try:
        return TiktokenCounter()
    except EncodingUnavailable as e:
        warnings.warn(f"tiktoken unavailable, fallback heuristic: {e}")
        return HeuristicCounter()


_DEFAULT_PRICING: dict[str, Pricing] = {
    "deepseek-chat": Pricing("deepseek-chat", 0.001, 0.002),
}


def get_pricing(model: str) -> Pricing:
    """返回 Pricing；未定价模型返回 0 + warn。"""
    if model in _DEFAULT_PRICING:
        return _DEFAULT_PRICING[model]
    inp = float(os.environ.get("MODEL_PRICING_INPUT", "0") or "0")
    out = float(os.environ.get("MODEL_PRICING_OUTPUT", "0") or "0")
    if inp > 0 or out > 0:
        return Pricing(model, inp, out)
    warnings.warn(f"no pricing for model={model}; cost will be 0")
    return Pricing(model, 0.0, 0.0)