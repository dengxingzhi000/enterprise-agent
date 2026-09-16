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