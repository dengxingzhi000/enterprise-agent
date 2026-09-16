# Context Compression spec#2 Design (2026-09-16, v0.3.0第二刀，A方案)

## 目标
spec#1 装了计数+预算+组装截断，但只丢弃不压缩——长任务老段直接消失，语义丢太多。本 spec 装 **滑动窗口+extractive 摘要**：超预算时老段折成摘要塞进窗口，原言保留 state；顺手闭环 Tracer.log_event 接线。

## 背景
- 现状：spec#1 已合入 `main`，58 测试绿；`agent/context/` 5 文件，6 provider；`agent/runtime/loop.py` 已存 `state.context["context_report"]` 但未发 Tracer。
- 约束：启发式不调 LLM（无网/真 key 都可用）；离线 `pytest -q` 必须绿；tiktoken 仍注释可选；不破坏 43 旧测试；durable/checkpoint 不丢原言。
- 工业对齐：等同 Vertex/BigQuery Agent 的 extractive-summary fallback（不调 LLM 的轻量压缩兜底）。

## 关键决策（已确认）
1. 方向：滑动窗口 + extractive 摘要（不调 LLM，零依赖）。
2. 路径：Provider 加 `compress(segs, keep_recent)` 自治理；assembler 在预算紧张时按层触发。
3. 触发：usage > `trigger_ratio` × available（默认 0.8）。
4. 老段：原言保留 `state.messages/observations`，不进 LLM 窗口但可断言可回放。
5. 顺手补：`Tracer.log_event` 闭环（不引入新 API）。

## 架构
`Provider.collect(state)` → `assembler` 收齐 segs → 预算检查 → 超阈值按层 `provider.compress(segs, keep_recent)` → 摘要段塞回参与丢弃评估 → 正常路径 → `report{usage, dropped, compressed[], counter_used, fits, skipped}` → `loop.py` 写入 `state.context["context_report"]` 并 `Tracer.log_event(trace_id, "context_assemble", report)`（无 trace_id 静默）。

## 组件
- `agent/context/extract.py`：`extract(text, max_chars=200)`——按句子边界切（.!?。！？\n），首句≤80字 + 关键词行（isalpha+小停用词表 topK） + 尾句≤80字，拼接 `[首句]…[关键词:…]…[尾句]`；空/纯停用词返回 `[empty-content]`；超长硬截到 max_chars。
- `agent/context/providers.py`：`BaseProvider.compress(segs, keep_recent)→(kept, summary_seg|None)` 默认实现；`ConversationProvider` 默认 `keep_recent=3`、`ObservationProvider` 默认 `keep_recent=5`；其它 provider 默认退化为"全留"。
- `agent/context/assembler.py`：触发条件 `usage > trigger_ratio*available`；按层调 `compress`，异常跳该层 + `report.skipped` 加名；`report["compressed"] = [{provider, before, after, kept}]`；摘要段仍按原 provider priority 参与丢弃评估（system/task 保底不变）。
- `observability/tracing.py` / `agent/runtime/loop.py`：无新 API；loop 在存 report 后用 `state.context.get("trace_id")` 调 `Tracer.log_event`，无则静默。
- `.env.example`：新增 `CONTEXT_COMPRESS_RATIO=0.8`、`CONVERSATION_KEEP_RECENT=3`、`OBSERVATION_KEEP_RECENT=5`。

## 数据流
第 k 轮 20 条 obs：providers collect → usage=9400 > 0.8×7000 → ObservationProvider.compress(obs_segs, keep_recent=5) 保留 5 条最新+15 条折 1 条 summary_seg → usage 重算 ~4500 装下 → report 写入 state.context → Tracer 发 event → planner view 只看组装窗口；state.observations[0..4]+[5..19] 原言仍全在，checkpoint/durable/replay 不动。

## 错误处理
- extract 收到空/纯停用词 → `[empty-content]` 占位 seg，不阻断。
- 单 provider compress 抛异常 → 跳过该层 + `report.skipped` 加名，不阻断整轮。
- keep_recent ≤0 或 ≥总数 → 退化为全留，不压缩。
- extract 句子切不开 → 硬截 max_chars 兜底，不死循环。
- Tracer 无 trace_id → 静默跳过。
- 压缩后仍超 → spec#1 截断+丢弃路径兜底，无新失败模式。

## 测试
新文件 `tests/test_context_compress.py`（TDD RED 先行）：
1. `extract`：长文本首尾句+关键词行存在；空文本占位返回。
2. `Provider.compress`：20 条 obs/keep_recent=5 → kept=5+1 summary_seg；断言 `len(state.observations)==20` 原言未变。
3. `Assembler` 触发：20 条 obs budget=7000/usage=9400 → 触发后 `usage<available` 且 `report.compressed` 有 observation 条目。
4. `Loop+Tracer`：mock Tracer，断言调一次 `log_event("context_assemble", report)`；无 trace_id 时不调（不抛）。
约束：无新硬依赖；58 旧测试全过；离线绿。

## 范围外（spec#3 / 后续）
- 深度 memory/RAG/tool provider 接入九层；AgentTask 字段接线（task_id/thread_id/status/checkpoint_id/token_usage/cost）；真 tiktoken 装包实测；LLM-quality eval 闭环。

## 自检
- 无占位：keep_recent 默认值（conv=3/obs=5）、trigger_ratio=0.8、max_chars=200 全定死。
- 一致性：架构↔组件↔数据流↔错误↔测试均围绕 "Provider.compress 自治理 + assembler 按层触发 + 原言保留 state"，无矛盾。
- 范围：单 spec 只做压缩摘要+Tracer 闭环，不含深度 provider/AgentTask 接线。
- 无歧义：摘要段仍参与丢弃评估、压缩异常跳该层、Tracer 无 trace_id 静默均显式。