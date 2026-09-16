"""Tests for context compression features (spec#2)."""

from __future__ import annotations


def test_extract_returns_head_keywords_tail():
    from agent.context.extract import extract
    text = ("订单服务报错500。网关超时导致上游积压。ERROR traceId=abc123. "
            "中间穿插多次重试均失败。最终根因确认：Redis连接池耗尽。")
    out = extract(text, max_chars=200)
    assert "订单服务报错500" in out
    assert "Redis连接池耗尽" in out or "根因" in out
    assert len(out) <= 200


def test_extract_empty_or_stopwords_only():
    from agent.context.extract import extract
    assert extract("", max_chars=200) == "[empty-content]"
    assert extract("the a an of to", max_chars=200) == "[empty-content]"


def test_extract_dedup_case_insensitive():
    from agent.context.extract import extract
    text = "Error X error X ERROR X Redis X pool X Pool X"
    out = extract(text, max_chars=500)
    seg = out.split("关键词:")[1].split("…")[0] if "关键词:" in out else ""
    total = seg.count("Error") + seg.count("error") + seg.count("ERROR")
    assert total == 1, f"case-variants should dedup to 1 keyword, got {seg!r}"
    assert seg.count("Pool") + seg.count("pool") == 1, f"Pool/pool should dedup, got {seg!r}"


def test_extract_short_max_chars():
    from agent.context.extract import extract
    text = "订单服务报错500。Redis连接池耗尽。"
    for mc in (0, 1, 2):
        out = extract(text, max_chars=mc)
        assert len(out) <= mc, f"max_chars={mc} should not exceed limit, got {out!r}"
        assert "..." not in out, f"no '...' suffix expected when max_chars<3, got {out!r}"