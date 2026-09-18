# SCM Integration v2 Design

- Date: 2026-09-18
- Decision: 方案 B — 单一 spec，3 阶段交付，3 个 PR（用户已确认）
- Scope: 补齐 v1 推迟项；读路径不变；写路径仍只做占位+HITL
- Status: approved by user, pending implementation plans

## 1. Background

v1（PR #16）已交付 `integrations/scm/` 的 3 只读口 + Policy 分支 + 离线回退，但有 7 处缺口阻碍生产可用：

1. 写口只注册了 `scm.purchase.create`，`scm.order.cancel` / `scm.stock.adjust` 漏注册 → Planner 选 tool 后 Policy 走到 `need_approval`，但 registry 找不到 tool，Observation 会是 `unknown tool`。
2. `need_approval` 实际已由 `agent/tools/executor.py:38-41` 的 `guarded_executor` 走 `ApprovalStore.request`，但 `tools.py:32,63` 的占位 lambda 让人误以为需要 tool 层处理。需在 spec 中明确**复用 executor，不再在 tool 层重复**。
3. `client.py` 只在 401 时重试，503/504/ConnectError 直接抛 → 联调时网络抖动会刷屏 `tool error`。
4. `workflow/scenarios.py` 只有 `review_contract` / `analyze_sales`，roadmap 三场景（IT Ops / 合同合规 / 销售分析）首位的 IT Ops 缺失。
5. `/chat` 返回 `reply: "need approval apr-X: ..."`，caller 拿不到结构化 `aid`，HITL 闭环断在 gateway。
6. `review_contract` 完全不调 scm，supplier 风险信息缺位。
7. `integrations/scm/client.py` 无 trace 埋点，跨服务调用失败时无法在 `observability/tracing.py` 中回溯。
8. `integrations/scm/auth.py:load_tenant_map()` 解析失败静默回退，配置错误无感。

## 2. Architecture (Phase Map)

```
Phase 1 — Foundation  (PR: feat/scm-integration-v2-foundation)
  integrations/scm/tools.py        注册 scm.order.cancel + scm.stock.adject + 修 tools.py 占位
  integrations/scm/client.py      503/504/ConnectError 重试 1 次（仅 GET，0.3s 退避）
  integrations/scm/auth.py        SCM_TENANT_MAP 坏 JSON / 空 dict → warning + 回退默认
  tests/test_scm_integration_v2.py  RED → GREEN

Phase 2 — Scenarios  (PR: feat/scm-integration-v2-scenarios)
  integrations/scm/tools.py        新增 scm.supplier.get（只读）+ SCM_READ_TOOLS 加入
  integrations/scm/policy_map.py   同步
  workflow/scenarios.py            新增 run_it_ops(question, tenant_id='t1')
                                  review_contract 加 supplier 钩
  tests/test_scm_integration_v2.py  RED → GREEN

Phase 3 — Surface  (PR: feat/scm-integration-v2-surface)
  integrations/scm/client.py      _send 前后 Tracer.log_event（scm_call stage）
  integrations/scm/auth.py / env   引入 SCM_TRACE_ID env（contextvar 路径，见 §4.7）
  apps/api/main.py                status="paused" + pause_reason="need_approval" 时 payload 加 approval_id
  tests/test_scm_integration_v2.py  RED → GREEN
```

不变点（v1 已建立的契约，三阶段都遵守）：
- `agent/tools/executor.py:28-41` `guarded_executor` 仍是 Policy+HITL 唯一强制检查点；不重写。
- `security/policy.py:30-37` `scm.*` 分支复用；`security/approval.py:ApprovalStore` 复用。
- `agent/runtime/status.py` `AgentStatus` 枚举已含 `paused`，`ALLOWED_TRANSITIONS` 允许 `running→paused→running`，**不引入新状态**。
- 离线回退（无 `SCM_*` env）继续返回 mock 字符串，`pytest -q` 全程 GREEN。
- `.env` 不提交，PR 模板检查仍然适用；`.env.example` 只加注释，不写真实口令。

## 3. Components

### Phase 1 — Foundation

**3.1 `integrations/scm/tools.py` — 写口全注册**
- 新增注册 `scm.order.cancel` 和 `scm.stock.adjust`，lambda 跟 `scm.purchase.create` 一致返回占位字符串（实际不会被调用，仅用于让 tool name 在 registry 里能被 `policy.check` 引用）。
- 描述里加 `(占位, 走HITL)` 标识，Planner 看到就知道"可调但需审批"。
- `tools.py:32,63` 的占位 lambda 注释改为"dead code；guarded_executor 在 Policy.need_approval 时已拦截，保留仅为防御未来 Policy 配置失误"。

**3.2 `integrations/scm/client.py` — 5xx + ConnectError 重试**
- `ScmClient.get()` 包一层 `_retry_get(path, params)`：捕获 `httpx.HTTPStatusError`（5xx）/ `httpx.ConnectError` / `httpx.TimeoutException` → sleep 0.3s → 重试 1 次 → 仍失败返回 `(code, body)` 中 `code=0, body={"error": "transport: ..."}`，不抛异常。
- 401 路径不变（刷 token 重试 1 次）。
- POST/PUT 不做重试（v2 范围内不调 scm 写接口；写口只走 ApprovalStore，不发 HTTP）。

**3.3 `integrations/scm/auth.py` — tenant_map 校验**
- `load_tenant_map()`：
  - `os.environ.get("SCM_TENANT_MAP", "")` 缺省空字符串，不再硬编码 `{"t1":"tenant_001"}` 默认值在源码中。
  - `json.loads` 失败 → `warnings.warn("SCM_TENANT_MAP invalid JSON, falling back to defaults", stacklevel=2)` + 返回 `{"t1": "tenant_001"}`。
  - 解析成功但结果为空 dict 或非 dict → 同上 warning + 默认值。
- `to_scm_tenant(agent_tenant)`：agent tenant 不在 map 中时 `warnings.warn(f"no scm tenant mapping for {agent_tenant}, passing through")` + 原值透传（不丢请求，只是日志告警）。

### Phase 2 — Scenarios

**3.4 `workflow/scenarios.py` — run_it_ops**
- `def run_it_ops(question: str, tenant_id: str = "t1") -> dict:`
- 步骤：
  1. `reg.call("metrics.get", {"service": "mall"})` → 取指标快照。
  2. `reg.call("logs.search", {"query": question, "tenant_id": tenant_id})` → 取相关日志。
  3. 解析 logs 是否含 `error/timeout/500/失败` 任一关键词；若命中 → `reg.call("scm.order.get", {"order_no": <提取订单号或留空>, "tenant_id": tenant_id})`（仅当 tool 可用）。
  4. 任一步异常 → 静默回退 `knowledge.search`（与 v1 `analyze_sales` 一致）。
- 返回 `{"report": str, "trace": [list of tool names]}`
- 报告模板：包含 question + 指标 + 日志 + 受影响订单 + 初步诊断（"支付链路超时，需按运维手册排查支付网关"）。

**3.5 `workflow/scenarios.py` — review_contract supplier 钩**
- `review_contract(contract)`：
  - 现有风险判断保留（amount > 10000 或 clauses 含 RISKY_CLAUSES）。
  - **新增**：risk 命中后 `reg.call("scm.supplier.get", {"supplier_id": contract.get("supplier_id",""), "tenant_id": "t1"})` 把 supplier 风险评分拼进 `opinion`。
  - supplier 调失败（非 Policy deny）→ 不影响主结论，仅 `opinion` 末尾追加 `(supplier 信息暂不可用)`。
- trace 新增 `"scm.supplier.get"` 当实际调用发生。

**3.6 `integrations/scm/tools.py` — scm.supplier.get**
- 加入 `SCM_READ_TOOLS`（policy_map.py）。
- 注册 tool：`GET /api/suppliers/{supplier_id}?tenant={scm_tenant}`。
- Mock 返回：`f"supplier={args.get('supplier_id','SP-001')} rating=B credit_score=72 risk=medium (mock)"`。

### Phase 3 — Surface

**3.7 `integrations/scm/client.py` — Tracer 埋点**
- 新增 contextvar `scm_trace_id: ContextVar[str | None] = ContextVar("scm_trace_id", default=None)`。
- `ScmClient.__init__` 不变；`_send(method, path, **kw)` 在 send 前：
  ```python
  tid = scm_trace_id.get()
  if tid:
      try:
          Tracer._shared.log_event(tid, "scm_call", {"method": method, "path": path})
      except Exception:
          pass
  ```
- send 后 `_send` 末尾再加 `log_event(tid, "scm_result", {"method": method, "path": path, "code": r.status_code})`。
- 测试时通过 `scm_trace_id.set("tr-x")` 设置；运行时不依赖全局 Tracer（`Tracer._shared` 为 None 时 swallow）。

**3.8 `apps/api/main.py` — Gateway 暴露 approval_id**
- `ChatRequest` 不变；`/chat` 处理后：
  - 若 `final.status == "paused"` 且 `final.context.get("pause_reason") == "need_approval"`：
    - payload 增加 `"approval_id": final.context.get("approval_id")`、`"approval_tool": final.context.get("approval_tool")`、`"approval_args": final.context.get("approval_args")`。
  - 其余情况不暴露 aid 字段。
- `pause_reason` / `approval_id` / `approval_tool` / `approval_args` 由 `guarded_executor` 在 need_approval 时写入 `state.context`（executor.py:38-41 已生成 aid，扩展写入 state.context）。

**3.9 `agent/tools/executor.py` — need_approval 写 context**
- `guarded_executor` 在 `decision == "need_approval"` 路径：
  ```python
  if decision == "need_approval":
      aid = None
      if approvals is not None:
          aid = approvals.request(user, tool, args)
      ctx = getattr(state, "context", None)
      if isinstance(ctx, dict):
          ctx["pause_reason"] = "need_approval"
          ctx["approval_id"] = aid
          ctx["approval_tool"] = tool
          ctx["approval_args"] = args
      return {"tool": tool, "result": f"need approval {aid}: {tool} pending human review"}
  ```
- 保证 gateway 拿到的 state.context 里有完整 HITL 元数据。

## 4. Data Flow + Security

### Phase 1 — Foundation
不变。`policy.check → decision ∈ {allow, need_approval, deny}` → `guarded_executor` 拦截。
新增：5xx 重试 + tenant_map warning；Policy 分支不变。

### Phase 2 — Scenarios
1. `POST /chat {message="服务异常排查", tenant_id=t1}` → `run_it_ops` 是 workflow 入口（**不直接经 `/chat`**，是 workflow 层调用；`/chat` 经 Agent Runtime 走 Planner，不直接调 scenario——本阶段只确保 `run_it_ops` 作为独立函数存在并被测试覆盖）。
2. `review_contract({amount, clauses, supplier_id})` → risk 命中 → `scm.supplier.get` 命中 → `opinion` 增 supplier 风险评分。
3. tenant 隔离由 Policy 保证（`args.tenant_id != user.tenant_id → deny`），新 supplier tool 不绕过。

### Phase 3 — Surface
1. `/chat` 收到带 `tenant_id=t1` 的写请求（如 "取消订单 O-123"）。
2. Planner 产出 `{"action":"call_tool","tool":"scm.order.cancel","args":{"order_no":"O-123","tenant_id":"t1"}}`。
3. `guarded_executor` → `policy.check → need_approval` → 写 `state.context["pause_reason|approval_id|approval_tool|approval_args"]` → 返回 `need approval apr-X: ...`。
4. Runtime loop 接到 observation → **不 finish**，**应 transition 到 paused**（具体见 §5 实现说明）。
5. `/chat` 检查 `final.status == "paused"` → payload 加 aid 字段。
6. 调用方拿 `aid` 调 `/approval/{aid}/decide`（v3 范围，不在本 spec）。

## 5. Implementation Notes

**5.1 Runtime loop 与 paused**
- 现状 `loop.py:118-133` 收到 `call_tool` 的 observation 后 `continue` 回到 planner；v2 需在 observation 是 `need approval` 时 `break` 并 transition `running → paused`：
  ```python
  obs_result = str(obs.get("result", ""))
  if obs_result.startswith("need approval"):
      inner.status = "paused"
      task.transition("paused", "need_approval")
      _emit_status(task, "need_approval")
      break
  ```
  - 测试 `test_chat_payload_surfaces_approval_id` 覆盖此路径。

**5.2 contextvar 设置点**
- `apps/api/main.py` `chat()` 处理前：
  ```python
  from integrations.scm.client import scm_trace_id
  from observability.tracing import Tracer
  tid = Tracer().start_trace(req.message) if Tracer._shared is None else None
  if tid:
      st.context["trace_id"] = tid
  token = scm_trace_id.set(tid) if tid else None
  try:
      final = run(st, planner=planner)
  finally:
      if token is not None:
          scm_trace_id.reset(token)
  ```
- 或更简单：在 `/chat` 入口把 `tid` 写到 `st.context["trace_id"]`，client 通过读 contextvar（**在 `ScmClient._send` 内 `from integrations.scm.client import scm_trace_id` 但需要拿到 trace_id**——contextvar 在同进程任何位置可见）。
- 决策：contextvar 路径——`Tracer.start_trace` 永远创建 Tracer（不再"if shared is None"），`apps/api/main.py` 把 `tid` 同时写到 `st.context["trace_id"]`（用于 `loop.py` 的 trace event）和 `scm_trace_id.set(tid)`（用于 client 埋点）。

**5.3 v1 review_contract 的 Policy 衔接**
- v1 `review_contract` 调 `knowledge.search` 不经 Policy（直接走 function，不经 Runtime loop）。v2 supplier 钩也保持同样模式：**scenario 是同步 function，不经 Agent Runtime**。Policy 仅对 Runtime 中的 call_tool 生效，scenario 内 tool 调用**也走 Policy**——需把 `user` 传进 scenario：`run_it_ops(question, tenant_id='t1', user=None)` 时若 user=None 则构造 `{"tenant_id": tenant_id, "role": "admin"}` 默认值；`review_contract` 同理。
- 但 `reg.call` 当前**不**经 Policy（policy 在 `guarded_executor` 而非 `Registry.call`）。v2 决策：**scenario 内 tool 调用保持现状不引入 Policy 强制**——因为 scenario 本身已被 workflow 层授权；引入会让 `reg.call` 行为变化（影响 65+ 个 v1 测试）。这是 v2 的**显式 trade-off**，记入 §7 风险。

## 6. Config + Ports

`.env.example` 新增/确认（v1 已加的部分保留，v2 追加）：
```
# v2: Phase 3 surface
# Tracer 在 /chat 入口创建；SCM 客户端通过 contextvar 读取 trace_id
# 无须新增 env；保留注释解释机制

# v2: Phase 1 retry
SCM_RETRY_BACKOFF_SECONDS=0.3
```

Agent 端口 `AGENT_PORT=8762` 不变。

## 7. Error Handling

| 情况 | 行为 |
|---|---|
| scm 503/504 | `_retry_get` 重试 1 次后仍 503 → 返回 `(0, {"error": "scm 503 after retry"})` 转字符串 `tool error scm.*: ...` |
| scm ConnectError/Timeout | 同上重试 1 次后仍失败 → 转字符串，不抛 |
| 401 | 不变：刷 token 重试 1 次 |
| 跨租户 | Policy deny（执行前拦截） |
| 写口命中 | `need approval apr-X`；gateway 暴露 aid；Runtime transition 到 paused |
| `run_it_ops` / `review_contract` 内部 tool 异常 | 静默回退 knowledge.search 或省略 supplier 字段 |
| `SCM_TENANT_MAP` 配错 | warning + 回退默认；不抛 |

## 8. Testing (TDD)

新增 `tests/test_scm_integration_v2.py`，按阶段分块：

**Phase 1 测试**
1. `test_write_tools_all_registered` — `len([t for t in reg.list_tools() if t in {"scm.purchase.create","scm.order.cancel","scm.stock.adjust"}]) == 3`
2. `test_5xx_retry` — mock httpx：第一次 503，第二次 200；断言 `code==200` 且调用 2 次
3. `test_connect_error_retry` — mock httpx：第一次 `ConnectError`，第二次 200
4. `test_no_retry_on_4xx` — mock httpx：404 → 1 次调用，不重试
5. `test_tenant_map_warning_on_bad_json` — `monkeypatch.setenv("SCM_TENANT_MAP", "{bad")` + `recwarn`；断言有 warning + `to_scm_tenant("t1") == "tenant_001"`

**Phase 2 测试**
6. `test_run_it_ops_basic` — 返回 `{report, trace}`；trace 含 `metrics.get` + `logs.search`
7. `test_run_it_ops_extracts_order_no` — question 含订单号时 trace 增 `scm.order.get`
8. `test_review_contract_uses_supplier` — risk 命中 → opinion 含 "supplier=" 字样
9. `test_scm_supplier_get_registered` — `scm.supplier.get in reg.list_tools()`
10. `test_supplier_call_failure_does_not_break_review` — mock scm.supplier.get 抛异常；review_contract 仍返回原 decision

**Phase 3 测试**
11. `test_chat_payload_surfaces_approval_id` — mock executor 返回 need approval；`/chat` 测试客户端（FastAPI TestClient）断言 response 含 `approval_id`
12. `test_no_approval_field_when_not_paused` — 普通 chat 返回不含 `approval_id`
13. `test_client_emits_trace_event` — `scm_trace_id.set("tr-x")`；调 `_send`；`Tracer._shared.get_trace("tr-x")` 含 `scm_call` 事件
14. `test_runtime_transitions_to_paused_on_need_approval` — mock executor 返回 need approval；调 `run()`；`final.status == "paused"`

约束：
- `pytest-asyncio auto` 模式。
- `pytest -q` 全绿（含 v1 的 99 + v2 新增 14 测试，目标 113 passed）。
- 不依赖真实 scm-platform（httpx mock + FastAPI TestClient）。
- 每个测试独立运行：Phase 2 测试用 mock 重置 registry 状态；Phase 3 测试用 TestClient 不污染全局。

## 9. Non-Goals (v2 不做)

- `/approval/{aid}/decide` HTTP endpoint（v3 范围）。
- ApprovalStore 持久化（v2 仍 in-memory；持久化走 Postgres 在 Stage 3+）。
- LangGraph 改造、MCP server。
- POST/PUT 重试（v2 范围仍只调 GET 写路径不直发）。
- supplier 风险模型训练（仅返回 mock 字段；真实评分算法走 Stage 8 LangGraph 之后）。
- 直连 Postgres/Redis（仍走 REST 网关）。
- K8s/Docker 联部署。

## 10. Rollout

每阶段独立流程：

```
Phase N:
  1. 切分支 feat/scm-integration-v2-{foundation|scenarios|surface}（基于 feat/scm-integration）
  2. 写 failing tests（RED）
  3. 实现最小通过代码（GREEN）
  4. refactor（仅 GREEN 后）
  5. pytest -q 全绿
  6. git push + gh pr create --base feat/scm-integration
  7. 评审通过后 merge；下一阶段从更新后的 feat/scm-integration 开新分支
```

最终三阶段合入 `feat/scm-integration` 后再决定是单独 PR 还是三阶段分别合入 `main`——决策点在三阶段 PR 评审过程中。

## Self-Review (2026-09-18)

- [x] 无 TBD/TODO：所有 tool 名、URL、重试次数、contextvar 名称、状态机值均已定。
- [x] 内一致：Phase 1 的 Policy 分支不动 → Phase 2 的新 tool SCM_READ_TOOLS 加入 → Phase 3 的 executor 扩展互不冲突。
- [x] Scope 单一：仅补齐 7 项缺口；不动 Stage 8 / LangGraph / MCP / 持久化。
- [x] 无歧义：
  - "占位 lambda 不会被调用"在 §3.1 明确说明原因。
  - "scenario 内 tool 调用不经 Policy"在 §5.3 显式 trade-off。
  - "contextvar 路径"在 §5.2 选定，备选方案（env 注入）已淘汰。
  - "Runtime transition 到 paused"在 §5.1 给出具体 patch 位置。
- [x] 测试覆盖每个决策点：14 测试覆盖 Phase 1/2/3 全部关键路径。
- [x] 风险已列出（§7 + §9）：supplier 路径假设、scenario-Policy trade-off、持久化未做。