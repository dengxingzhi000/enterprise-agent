# AgentTask Wiring spec#4 Design (2026-09-16, v0.4.0第一刀，A方案)

## 目标
v0.3.0 三 spec 全闭环（78 测试绿）后，路线图剩下的核心契约缺口是 AgentTask——task_id/thread_id/status/checkpoint_id/token_usage/cost。本 spec 给 AgentState 套一层 AgentTask 包装，加 ID 生成器、状态机、Token Counter、Pricing 累加、Tracer 事件；保持 AgentState 不变，老测试零修改。

## 背景
- 现状：v0.3.0 已合入 `main`，78 测试绿；`agent/runtime/state.py` 是 AgentState dataclass（task/messages/plan/observations/tool_calls/memory/context/iteration/status/answer）。
- v0.2.0 已用 thread_id 在 durable checkpoint，v0.4.0 需统一对外 ID。
- 约束：离线 `pytest -q` 必须绿；tiktoken 仍注释可选；不破坏 78 旧测试；AgentTask 不能与 AgentState 字段重复。

## 关键决策（已确认）
1. 范围：AgentTask 套 AgentState（外包装），ID 唯一。
2. 状态机：`pending→{running,cancelled}` / `running→{paused,done,failed,cancelled}` / `paused→{running,cancelled}`；终态不可再转。
3. ID：`uuid4` 自动生成；AgentState.task_id 优先回填。
4. Counter：`TiktokenCounter` 懒加载 + 启发兜底；`count_messages([{role,content}])→{input,output}`。
5. Pricing：默认 deepseek-chat input1/M output2/M 估算（env `MODEL_PRICING_INPUT/OUTPUT` 覆盖）。
6. Tracer：每状态转换发 `task_status_changed` 事件。

## 架构
FastAPI `/chat` → AgentTask.from_state(AgentState) (auto uuid4 或复用) → loop.run(task_or_state) 自动 wrap → 每轮 Counter 计 planner view → task.record_tokens(input, output) 累加 token_usage.total + cost → task.transition(reason) 走状态机 + history → Tracer event task_status_changed → ClientJSON {task_id, status, answer, token_usage, cost, history}。

## 组件
- `agent/runtime/status.py`：`ALLOWED_TRANSITIONS` dict；终态 `done/failed/cancelled` 不可再转。
- `agent/runtime/agent_task.py`：`AgentTask` dataclass (`task_id: str`, `tenant_id: str`, `state: AgentState`, `status: str`, `checkpoint_id: str|None`, `token_usage: dict`, `cost: float`, `created_at: str`, `updated_at: str`, `history: list[dict]`)；`InvalidTransition`/`AgentTaskError`；方法 `transition(to, reason="")` `attach_checkpoint(thread_id)` `record_tokens(input_n, output_n)`；类方法 `from_state(state, tenant_id="default")` 含 uuid4 自动生成。
- `agent/runtime/counter.py`：`Pricing(model, input_per_1k, output_per_1k)`；`Counter` 接口 `count_messages([{role,content}])→{input,output}`；`TiktokenCounter`/`HeuristicCounter`/`get_counter()`/`get_pricing(model)` 工厂；tiktoken 缺席或 EncodingUnavailable warn 降级。
- `agent/runtime/loop.py`：`run(task_or_state, ...)` 自动 wrap（isinstance AgentState → AgentTask.from_state）；每轮 Counter + record_tokens；status 转换；emit Tracer event `task_status_changed` 带 trace_id 静默。
- `apps/api/main.py`：`/chat` 接受可选 `task_id`；`version=0.4.0`；`task_id` 复用时走 checkpointer 恢复（v0.2.0 桥）。
- `.env.example`：注释加 `MODEL_PRICING_INPUT=0.001` `MODEL_PRICING_OUTPUT=0.002` `AGENT_STATUS_HISTORY=50`。

## 数据流
POST /chat {task_id?} → AgentTask.from_state 自动 uuid4 → status=pending history=[] → loop.run → transition(running) → 每轮 Counter.count_messages(planner_view)→{input,output}→ record_tokens 累加 cost → finish→transition(done)/paused→transition(paused)/max_iter→transition(failed) → emit Tracer task_status_changed → ClientJSON {task_id, status, answer, token_usage, cost, history}。

## 错误处理
- 非法状态转换 → InvalidTransition 不写 history 不改 status。
- Counter tiktoken 加载失败 → warn + HeuristicCounter。
- 模型未定价 → cost=0.0 + warn 不抛。
- record_tokens 负数 → ValueError。
- attach_checkpoint 空字符串 → ValueError。
- Tracer 发送失败 → 静默吞掉（与 spec#2 一致）。

## 测试
新文件 `tests/test_agent_task.py`（TDD RED 先行，6 个）：
1. `AgentTask.from_state` 自动生成 uuid task_id + 默认 status="pending" history=[]。
2. `transition` 合法路径 `pending→running→paused→running→done` 写 history；非法 `done→running` 抛 InvalidTransition。
3. `record_tokens(input=100, output=50)` 累加 total=150 + cost>0（mock pricing）；负数抛 ValueError。
4. `Counter.count_messages([{role:"user",content:"hi"}])` 返回 input>=1；tiktoken 缺席 fallback 不抛。
5. `loop.run(AgentState,...)` 向后兼容自动 wrap → finish 后 status="done" + history 有转换记录；Tracer 收到 task_status_changed。
6. `loop.run` 触发 max_iterations → status="failed" + history 末条 reason="max_iterations"。

约束：78 旧测试全过；tiktoken 仍注释可选；`pytest -q` 离线绿。

## 范围外（spec#5 / 后续）
- v0.2.0 遗留：真 PG 杀进程跨重启恢复。
- EpisodicMemoryProvider 真实现 + Saga/Compensation。
- Agent Security (RBAC/ABAC/审计/防注入)。
- Workflow 接线 AgentTask（spec#5+）。
- OTel/Prom 替换内存 Tracer。

## 自检
- 无占位：默认 status、ALLOWED_TRANSITIONS、Pricing 默认值、`AGENT_STATUS_HISTORY=50` 全定死。
- 一致性：架构↔组件↔数据流↔错误↔测试均围绕 AgentTask wrap + 状态机 + Counter + Pricing + Tracer 事件，无矛盾。
- 范围：单 spec 只做 AgentTask + Counter + Pricing + loop 接线，不含 v0.2.0 杀恢复/Episodic/Security。
- 无歧义：AgentState 不变向后兼容、ID 唯一、终态不可转、tiktoken 缺席降级均显式。