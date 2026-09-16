"""agent/context/extract.py: 启发式 extractive 摘要（首句+关键词+尾句），零依赖。"""
import re

_SENT_SPLIT = re.compile(r"[.!?。！？\n]+")
_STOPWORDS = set("""a an the of to in on for with and or but is are was were be been being it its this that
                these those at by from as into about over under up down out off so than then too very
                我 你 他 她 它 我们 你们 他们 这 那 的 了 是 在 有 和 与 或 但 也 都 就 还 而 及 以
                对 上 下 出 入 到 被 让 把 给 用""".split())

def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    return parts or [text.strip()]

def _keywords(text: str, top: int = 5) -> list[str]:
    seen_lower: set[str] = set()
    seen: list[str] = []
    for tok in text.split():
        t = tok.strip(".,;:!?()[]{}<>\"'`·、，。；：！？()【】《》 ")
        if len(t) < 3 or t.lower() in _STOPWORDS or not any(ch.isalnum() for ch in t):
            continue
        low = t.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        seen.append(t)
        if len(seen) >= top:
            break
    return seen

def extract(text: str, max_chars: int = 200) -> str:
    if not text or not text.strip():
        return "[empty-content]"
    sents = _split_sentences(text)
    head = sents[0][:80]
    tail = sents[-1][:80] if len(sents) > 1 else ""
    kws = _keywords(text)
    if not kws:
        return "[empty-content]"
    parts = [head, "关键词:" + ",".join(kws)]
    if tail and tail != head:
        parts.append(tail)
    out = "…".join(parts)
    if max_chars < 3:
        return out[:max_chars]
    if len(out) > max_chars:
        out = out[: max_chars - 3] + "..."
    return out