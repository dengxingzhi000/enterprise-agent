"""agent/context/counter.py: 精确优先，启发兜底，保证离线不断。"""
import warnings


class EncodingUnavailable(Exception):
    pass


class BaseCounter:
    def count(self, text: str) -> int:
        raise NotImplementedError


class HeuristicCounter(BaseCounter):
    def count(self, text: str) -> int:
        return max(1, len(text) // 4)


class TiktokenCounter(BaseCounter):
    def __init__(self, encoding_name: str = "cl100k_base"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding_name)
        except Exception as e:  # noqa: BLE001 - 缺包或BPE下不到都转统一异常
            raise EncodingUnavailable(str(e))

    def count(self, text: str) -> int:
        return max(1, len(self._enc.encode(text)))


def get_counter() -> BaseCounter:
    try:
        return TiktokenCounter()
    except EncodingUnavailable as e:
        warnings.warn(f"tiktoken unavailable, fallback heuristic: {e}")
        return HeuristicCounter()
