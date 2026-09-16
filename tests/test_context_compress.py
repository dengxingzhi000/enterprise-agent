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


def test_provider_compress_keeps_recent_and_summarizes_old():
    from agent.context.providers import ObservationProvider
    state = {"observations": [{"tool": f"t{i}", "result": f"r{i}"} for i in range(20)]}
    p = ObservationProvider(recent=10)
    collected = p.collect(state)
    kept, summary = p.compress(collected, keep_recent=5)
    assert len(kept) == 5
    assert summary is not None
    assert summary["name"] == "observation:summary"
    assert "…" in summary["text"]  # extract() joins head/keywords/tail with "…"
    assert len(state["observations"]) == 20  # 原言保留


def test_provider_compress_kept_segments_are_copies():
    from agent.context.providers import ObservationProvider
    segs = [{"name": "observation[{}]".format(i), "priority": 20, "text": f"orig-{i}"}
            for i in range(3)]
    p = ObservationProvider()
    kept, summary = p.compress(segs, keep_recent=1)
    assert len(kept) == 1
    kept[0]["text"] = "MUTATED"
    kept[0]["priority"] = 999
    kept[0]["name"] = "changed"
    assert segs[-1]["text"] == "orig-2", "source seg must not be mutated by aliasing"
    assert segs[-1]["priority"] == 20
    assert segs[-1]["name"] == "observation[2]"


def test_provider_compress_zero_keeps_all():
    from agent.context.providers import ObservationProvider
    segs = [{"name": f"s{i}", "priority": 20, "text": f"t{i}"} for i in range(4)]
    p = ObservationProvider()
    kept, summary = p.compress(segs, keep_recent=0)
    assert kept is segs
    assert summary is None


def test_provider_compress_overflow_keeps_all():
    from agent.context.providers import ObservationProvider
    segs = [{"name": f"s{i}", "priority": 20, "text": f"t{i}"} for i in range(4)]
    p = ObservationProvider()
    kept, summary = p.compress(segs, keep_recent=len(segs))
    assert kept is segs
    assert summary is None


def test_assembler_compresses_when_over_trigger_ratio():
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    big = "ERROR trace " * 50
    state = {"task": "查500", "system": "你是助手。",
             "messages": [{"role": "user", "content": f"msg-{i}"} for i in range(20)],
             "observations": [{"tool": "logs.tail", "result": big} for _ in range(20)]}
    asm = ContextAssembler(budget=TokenBudget(total=800, reserved_for_output=100),
                           trigger_ratio=0.5)
    msgs, report = asm.assemble(state)
    assert report["usage"] <= 800
    providers = {c["provider"] for c in report.get("compressed", [])}
    assert "observation" in providers or "conversation" in providers


def test_assembler_compresses_per_layer_not_per_seg():
    """B1 regression: compression must run once per layer, not once per segment.

    With 20 observation segments and obs_keep=5, the assembler should produce
    exactly ONE compressed[] entry (before=20, kept=5, after=6) and emit
    exactly one summary segment — not duplicate the work 20 times.
    """
    from agent.context.assembler import ContextAssembler
    from agent.context.budget import TokenBudget
    from agent.context.providers import (
        DEFAULT_PROVIDERS, ObservationProvider,
    )
    big = "ERROR trace " * 50
    state = {"task": "查500", "system": "你是助手。",
             "messages": [{"role": "user", "content": f"msg-{i}"} for i in range(20)],
             "observations": [{"tool": "logs.tail", "result": big} for _ in range(20)]}
    # Ensure all 20 observations reach the assembler (default recent=10 truncates).
    providers = [p if p.name != "observation"
                 else ObservationProvider(recent=20)
                 for p in DEFAULT_PROVIDERS]
    asm = ContextAssembler(budget=TokenBudget(total=800, reserved_for_output=100),
                           providers=providers,
                           trigger_ratio=0.5,
                           observation_keep_recent=5)
    msgs, report = asm.assemble(state)
    obs_entries = [c for c in report["compressed"] if c["provider"] == "observation"]
    assert len(obs_entries) == 1, (
        f"expected exactly 1 observation compressed[] entry, got "
        f"{len(obs_entries)}: {obs_entries}"
    )
    entry = obs_entries[0]
    assert entry["before"] == 20
    assert entry["kept"] == 5
    # 'after' shape = 1 summary + kept copies; proves exactly one summary was emitted.
    assert entry["after"] == 1 + entry["kept"]
    # Output msgs must include the summary's head text (extract() head segment).
    summary_seen = any("logs" in m["content"] and "summary" not in m["content"]
                       and "ERROR" in m["content"]
                       for m in msgs)
    assert summary_seen, f"expected summary head in msgs, got: {[m['content'][:40] for m in msgs]}"