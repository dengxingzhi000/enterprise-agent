# Durable LangGraph Checkpoint Design (2026-09-16, C方案)

## 目标
Task 1~8 完成后停止堆技术栈，进入 Agent Engineering 第一刀：用 LangGraph Checkpoint 一次性补上可靠性+Durable（超时/重试/幂等/循环检测/Checkpoint/暂停恢复），覆盖报销与故障双链路，从 Demo 能跑跨到企业可靠运行。

## 背景
- 现状：34 测试全绿，但 `agent/runtime/loop.py` 为 naive loop，无超时/重试/Checkpoint/Context 管理；`workflow/graph_lang.py` 为 fallback 模式（langgraph 未安装）。
- 约束：远程 PG/Redis 在 `192.168.80.156`，库名 TBD；CI 只有 `pip install -e .` + `pytest -q`，无 PG；`.env` 不提交真 key；TDD RED→GREEN 纪律。

## 关键决策（已确认）
1. 下一阶段首切：可靠性+Durable 优先（不先做 Context 工程/安全加固）。
2. 持久化：直连 PG/Redis，PG 做主 checkpoint，Redis 只做幂等/去重。
3. 范围（标准包）：超时+重试（指数退避）+幂等键+循环检测+Checkpoint+人工审批暂停/恢复。
4. 验证：都要——报销暂停恢复 + 故障超时重试链，杀进程也能同 thread_id 恢复。
5. 路线：C 方案——现在切 LangGraph Checkpoint（A 手写加固/B 事件溯源延后）。

## 架构
```
FastAPI Gateway
  ↓
Agent Runtime（保留 loop.py/state.py 做兼容门面，内部委托 LangGraph）
  ↓
LangGraph StateGraph（fetch→check→policy→judge→human/auto）
  ↓
Checkpointer：
  ├─ 首选 PostgresSaver（PG_DSN，thread_id=task_id）
  ├─ fallback：MemorySaver（pytest/无PG，保证测试不断）
  └─ Redis：短时锁/幂等，不做主 checkpoint
  ↓
Tool 层：超时+重试包在节点外，幂等键=task_id+step，循环检测=visit 计数
  ↓
HITL：LangGraph interrupt + ApprovalStore（apr-*）双写，批准后 resume
```

原则：不删手写 `run_expense_workflow`；`build_expense_graph(checkpointer=...)` 有 checkpointer 用真图，否则 fallback；PG 连不上不挂测试。

## 组件
- `workflow/graph_lang.py`：`build_expense_graph(policy_threshold, checkpointer=None)` 编译真图并 `compile(checkpointer=...)`；新增 `get_checkpointer()` 工厂（PostgresSaver 优先，异常→MemorySaver）。
- 依赖：`langgraph` + `langgraph-checkpoint-postgres` + `psycopg[binary]`（缺席也不挂）。
- Tool 容错（节点外装饰器）：`with_timeout(5s)+retry(3次，1s/2s/4s指数退避)`；幂等键 `f"{thread_id}:{node}:{attempt}"` 存 Redis（连不上→内存 dict）；`LoopDetector` 对 trace visit 计数超 8→failed。
- HITL：`judge` 输出 `need_human=True` 时 `interrupt()` 暂停，同步写 `ApprovalStore.request()`；`approve()` 后 `graph.invoke(None, config={"configurable":{"thread_id":task_id}})` 恢复。
- `AgentTask` 轻扩：`task_id/thread_id/tenant_id/status/checkpoint_id/token_usage/cost`，只加字段不改现有测试。

## 数据流
### 报销暂停恢复
POST /expense {task_id} → fetch→check→policy→judge(need_human=True) → interrupt 暂停 + ApprovalStore[apr-1=pending] + PG checkpoint(thread_id) → 人工 approve → 同 thread_id resume → decision + trace 连续 → 杀进程重放：同 thread_id 新实例恢复到 judge 后，不重跑 fetch。

### 故障超时重试链
ToolB（超时 5s）→ Retry 3 次指数退避 → 仍失败→Fallback（缓存/降级值）→ Fallback 失败→ApprovalStore 建单转人工 → trace 记 timeout→retry→fallback→human → 幂等：同 task_id+node 重试不重复调 Tool。

## 错误处理
- Tool 超时→重试→Fallback→人工，4 层写 trace + Tracer.log_event；未知 action 直接 failed。
- PG 下线→降 MemorySaver + warning；Redis 下线→内存 dict；checkpoint 缺失/损坏→failed(reason=checkpoint_missing)，允许同 task_id 重建。
- 循环：同 node visit>8 判 loop_detected=failed。
- 幂等冲突：同 task_id:node 重放返回已存 observation，不二次调 Tool。

## 测试
- 新文件 `tests/test_durable_langgraph.py`（TDD RED 先行）：
  1. 报销暂停→批准→恢复，断言 decision/trace 连续。
  2. 杀进程恢复：新 checkpointer 实例同 thread_id 恢复。
  3. Tool 超时→重试→Fallback→人工全链路（mock timeout）。
  4. PG 缺席自动 fallback（CI 必过）。
  5. 幂等重放不重复调 Tool。
- 成功标准：双场景在 PG 与 MemorySaver 下都绿；`pytest -q` 离线全过（含原 34）。
- 配置：`.env` 新增 `PG_DSN`（库名确认后填，默认指向 192.168.80.156）；不提交真 key；langgraph 缺席走 fallback。

## 范围外（延后）
- Context Engineering（Context Manager/压缩/Token 预算）→ 下一 spec。
- 事件溯源/Saga/Compensation 全量 Durable → A 稳定后演进。
- RBAC/ABAC/审计/防注入全量安全 → 安全加固 spec。
- Eval 平台化（成功率/幻觉率/成本回归）→ AgentOps spec。

## 自检
- 无占位：仅 PG 库名待用户确认，已显式标为 `.env PG_DSN` 待填，不阻塞 fallback 测试。
- 一致性：架构↔组件↔数据流↔错误处理↔测试均围绕 thread_id=task_id + PostgresSaver 主/MemorySaver 备，无矛盾。
- 范围：单 spec 只做 C 方案可靠性+Durable，不含 Context/多智能体/平台。
- 无歧义：超时 5s、重试 3 次、退避 1s/2s/4s、循环阈值 8、幂等键格式均已定死。
