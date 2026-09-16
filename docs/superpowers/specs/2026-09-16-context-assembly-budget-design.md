# Context Engineering spec#1 Design (2026-09-16, v0.3.0首切，A方案)

## 目标
v0.2.0（Durable）之后进入 Context 工程。终态是九层全量 Context Manager，本 spec 只做 spec#1：计数+预算+组装截断+质量门。成功标准：长故障任务进 LLM 的 token 可控且答案质量不降（相对无管理基线）。

## 背景
- 现状：43 测试绿，v0.2.0 已发；`agent/runtime/loop.py` 把 observation 无脑 append 进 messages，无预算无截断；RAG 为内存版；`workflow/graph_lang.py` 384 行已偏大，本 spec 不动它。
- 约束：离线 `pytest -q` 必须绿；tiktoken 首次用需联网下 BPE；`.env` 不提交真 key；TDD RED→GREEN。

## 关键决策（已确认）
1. v0.3.0 主方向：Context 工程（不先做 PG 闭环/场景落地）。
2. 全量愿景分期：包结构一次到位，功能分 3 个 spec（#1组装预算截断 → #2压缩摘要+深度provider → #3 AgentTask接线）。
3. 计数：tiktoken 精确优先，`HeuristicCounter` 兜底（加载失败 warn 不挂）。
4. 成功标准：预算内质量不降（usage降≥30%且decision一致）。

## 架构
Planner/LLM 调用前经 `ContextAssembler.assemble(task_state, budget)`：providers 按优先级收集 → `TiktokenCounter` 计段 → 超预算按优先级从低到高丢弃/截断 → `loop.py` 每轮用组装后 `llm_messages`（`assembler=None` 时退化现状）。九层 provider 注册表占位，spec#1 实现 6 个基础层。

## 组件
- `agent/context/counter.py`：`BaseCounter.count(text)->int`；`TiktokenCounter`（懒加载，失败抛 `EncodingUnavailable`）；`HeuristicCounter(len//4)`；`get_counter()` 工厂（tiktoken优先，异常→启发式+warning）。
- `agent/context/budget.py`：`TokenBudget(total, reserved_for_output)`；`check(segments)->(fits, usage)`，超限给出按优先级排序的待丢弃清单。
- `agent/context/providers.py`：`BaseProvider(name, priority, collect(state))`；spec#1：System/Task/Conversation(近M)/Observation(近N)/RAG(seeds)/ToolTrace。memory深度版留spec#2。
- `agent/context/assembler.py`：`assemble(state, budget)->(llm_messages, report{usage, dropped, counter_used})`；report进 `Tracer.log_event`。
- `agent/runtime/loop.py`：`run(..., assembler=None)` 可选注入；`evaluation/evaluator.py` 加 `context_quality_gate`。

## 数据流
每轮 observation 全量进 state（checkpoint/durable不受影响）→ assembler收集6层segments → budget.check → 适配则直发；超限则按conversation旧轮→observation旧条→RAG低分→tool_trace顺序丢，仍超则截最低保留段尾部 → planner → 新observation。eval门：同故障任务基线（assembler=None）vs管理后对比 usage 与 decision。

## 错误处理
- tiktoken缺失/BPE失败→warn+启发式，report标注。
- budget≤0→视为unbounded退化现状。
- 单provider异常→跳过该层+`provider_skip` trace，不阻断。
- 极端情况至少保留system+task。

## 测试
新文件 `tests/test_context.py`（TDD RED先行）：
1. tiktoken计数区间断言（防版本漂移用区间不用精确值）。
2. mock ImportError 时 fallback 启发式不断。
3. 超预算丢弃顺序符合优先级。
4. 20轮observation长任务 usage≤budget 有界。
5. 质量门：decision一致且 usage_managed≤0.7×usage_base。
约束：tiktoken进pyproject硬依赖；43旧测试全过；`.env` 加 `CONTEXT_BUDGET_TOKENS`（默认8000，reserved 1000）。

## 范围外（spec#2/#3）
- 长任务压缩/摘要；memory/RAG/tool深度provider；AgentTask字段接线；workflow层接线；PG闭环验证（v0.2.0遗留，另行排期）。

## 自检
- 无占位：M/N轮数由测试定死（conversation近5轮，observation近10条）；区间阈值显式；BPE失败路径显式。
- 一致性：架构↔组件↔数据流↔错误↔测试均围绕 assemble+budget+report，无矛盾；state全量与窗口约束分离清晰。
- 范围：单spec只做组装预算截断+质量门，不含压缩/深度provider。
- 无歧义：默认8000/reserved1000、降幅30%、保留system+task底线均定死。
