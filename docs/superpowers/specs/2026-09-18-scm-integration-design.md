# SCM Integration Design (enterprise-agent ↔ scm-platform)

- Date: 2026-09-18
- Decision: 方案 B — 独立 `integrations/scm/` 模块 + 注册为 Tool（用户已确认）
- Scope: 首批只读 3 件套；写操作只做 Policy 映射、不实现
- Status: approved by user, pending implementation plan

## 1. Background

`enterprise-agent` 当前 Tool 全是 Mock（`agent/tools/builtin.py`：`metrics.get/logs.search/git.diff/db.query/knowledge.search`），
三场景（`workflow/scenarios.py`：`review_contract/analyze_sales`）跑的是假闭环。

`scm-platform` 是 20+ Spring Cloud 微服务（Gateway `:8761`、Auth `:8106`、Order `:8203`、Inventory `:8202`、
Mall `:8301`、Analytics `:8308` 等），多租户（`tenant_id` 列 + `TenantContextHolder`），CQRS + 读写分离，
关键写操作要求幂等（`IdempotentAspect`，Redis 24h request_id）。

已确认需求：读写都要、全业务域，但首版先跑通只读，避免一次性接入 20+ 服务拖死联调。

两个现实冲突：
1. 端口撞车：两边 Gateway 都是 `:8761`（`apps/api/main.py` vs scm-gateway）。
2. 通用 Registry 不能被外部系统污染：tenant/鉴权/重试/Policy 分级必须隔离。

## 2. Architecture

```
Client → FastAPI Gateway (:8762, 避开 scm :8761)
  → AgentRuntime Loop (Planner/Executor, max 8)
  → guarded_executor + PolicyEngine (唯一执行口)
  → Registry { builtin.* + scm.order.get + scm.inventory.query + scm.sales.report }
  → integrations/scm/client.py (httpx, 超时/重试/request_id)
  → scm-gateway :8761 → 各 Java 服务
```

不变点：
- `agent/tools/registry.py` 契约不动；`agent/tools/executor.py:28` 的 `guarded_executor` 仍是唯一强制检查点。
- `security/policy.py:10` 跨租户 deny 逻辑复用；`security/approval.py` 的 HITL 流程复用。
- 无 SCM 配置或 SCM 不可达时回退 Mock，保证 `pytest -q` 离线仍绿。

## 3. Components (`integrations/scm/` 新顶层包)

> 必须同步改 `pyproject.toml:31` 的 `packages.find` include，加上 `integrations*`，否则 `pip install -e .` 装不上。

- `client.py` — 统一 HTTP 封装
  - `base_url` 取 `SCM_GATEWAY_URL`；超时 5s；重试 1 次（仅 GET/幂等）；自动带 `X-Request-Id`（uuid4）。
  - 401 时刷 token 重试 1 次；超时/4xx/5xx 转字符串返回，不抛异常（复用 `executor.py:23` 惯例）。
  - 结果截断 2000 字符后返回，避免 Observation 爆 context。
- `auth.py` — 认证与租户映射
  - `POST {SCM_AUTH_URL}/login`（`SCM_USERNAME/SCM_PASSWORD`）换 token；内存缓存 + 过期前 60s 刷新。
  - `agent tenant_id → scm tenant_id` 只在这里映射（`SCM_TENANT_MAP` JSON，如 `{"t1":"tenant_001"}`）。
  - LLM / Planner / Tool args 永远接触不到真实 token。
- `tools.py` — Tool 适配（首批 3 只读）
  - `scm.order.get({order_no, tenant_id})` → `GET /api/orders/{order_no}`。
  - `scm.inventory.query({sku, tenant_id})` → `GET /api/inventory?sku={sku}`。
  - `scm.sales.report({range, tenant_id})` → `GET /api/analytics/sales?range={range}`（mall/order-center/analytics 聚合口，range 枚举 `7d/30d`）。
  - 注册函数 `register_scm_tools(registry)` 供 `build_default_registry()` 调用。
- `policy_map.py` — 读写分级
  - `SCM_READ_TOOLS = {"scm.order.get","scm.inventory.query","scm.sales.report"}` → `allow`（low-risk read）。
  - `SCM_WRITE_TOOLS = {"scm.purchase.create","scm.order.cancel","scm.stock.adjust"}` → `need_approval`（首版只写映射 + 占位 Tool 描述、不实现 HTTP）。
  - `PolicyEngine.check` 新增分支：`scm.*` 先做跨租户检查，再按上述集合判定；未知 `scm.*` 一律 `deny`。
- `scenarios.py` — 场景切换
  - `analyze_sales` 优先调 `scm.sales.report` + `scm.order.get`，失败回退 Mock。
  - `review_contract` 暂不动数据源（scm 无合同主体服务），只预留 `supplier` 查询 hook。

## 4. Data Flow + Security

1. `POST /chat {message, tenant_id=t1}` → `AgentState.context["tenant_id"]=t1`。
2. Planner 产出 `{"action":"call_tool","tool":"scm.order.get","args":{...}}`（仍受 Planner JSON 契约约束，非契约输出 → finish）。
3. `guarded_executor` → `policy.check(user={tenant_id,role}, tool, args)`：
   - `args.tenant_id != user.tenant_id` → `deny`。
   - read 集合 → `allow`；write 集合 → `need_approval`（走 `ApprovalStore.request`，返回 `need approval {aid}` 不直调）。
4. `client.py` 注入 scm token + scm tenant_id 发请求。
5. 返回截断文本 → Observation → Reflection → 最终 answer（含 `trace`）。

## 5. Config + Ports

`.env` 新增（`.env.example` 同步）：
```
AGENT_PORT=8762
SCM_GATEWAY_URL=http://localhost:8761
SCM_AUTH_URL=http://localhost:8106
SCM_USERNAME=
SCM_PASSWORD=
SCM_TENANT_MAP={"t1":"tenant_001"}
SCM_TIMEOUT_SECONDS=5
```
- Agent 本地启动改 `uvicorn apps/api/main:app --port 8762`。
- 无 `SCM_*` 配置 → `register_scm_tools` 注册 Mock 实现（复用现有假数据格式），测试与离线不受影响。
- `DEEPSEEK_API_KEY` 等既有项不动；禁止提交真实口令（PR 模板检查）。

## 6. Error Handling

| 情况 | 行为 |
|---|---|
| SCM 超时/连接失败 | 返回 `tool error scm.*: timeout after 5s`，进 Observation，Runtime 继续（可重试或 finish） |
| 401 | 刷新 token 重试 1 次；仍 401 → `tool error scm.*: unauthorized` |
| 404 | `tool error scm.*: not found {id}` |
| 403/跨租户 | `Policy DENY`（执行前拦截，不发请求） |
| 写操作（首版） | `need approval {aid}: ... pending human review`，不发真实请求 |

## 7. Testing (TDD)

新增 `tests/test_scm_integration.py`（RED → GREEN）：
1. `test_register_scm_tools` — 注册后 `list_tools()` 含 3 个 `scm.*`。
2. `test_cross_tenant_denied` — `policy.check({tenant_id:t1}, "scm.order.get", {tenant_id:t2})` → `deny`。
3. `test_401_refresh_retry` — mock httpx 首 401 次 200，断言发了 2 次请求且结果正确。
4. `test_offline_fallback` — 无 `SCM_*` env 时调 `scm.order.get` 返回 mock 字符串且不抛异常。
- 约束：`pytest-asyncio auto` 模式；`pytest -q` 全绿；不依赖真实 scm-platform（httpx mock）。

## 8. Non-Goals (首版不做)

- 不实现任何写操作 HTTP（`purchase.create/order.cancel/stock.adjust` 仅 Policy 占位）。
- 不引入 MCP Server / LangGraph 改造（Stage 8 再议）。
- 不直连 Postgres/Redis（走网关 REST；直连是 Stage 3+ 的事）。
- 不做 K8s/Docker 联部署；不处理 scm 内部端口冲突（8201/8209）。

## 9. Rollout

1. 写 failing test（RED）。
2. 建 `integrations/scm/` 5 文件 + `pyproject` include + `.env.example` + Agent 端口文档。
3. `PolicyEngine` 加 `scm.*` 分支；`build_default_registry` 接 `register_scm_tools`。
4. `pytest -q` GREEN；`uvicorn --port 8762` + mock 验证；有真实 scm 时配 env 联调 3 只读口。

## Self-Review (2026-09-18)

- [x] 无 TBD/TODO 占位；range 枚举、超时秒数、截断长度均已定。
- [x] 内一致：只读 3 口在组件/Policy/测试中一致；写口三处一致声明为占位。
- [x] Scope 单一：仅只读首版 + 写映射，不含 MCP/K8s/直连 DB。
- [x] 无歧义：token 不进 LLM、跨租户 deny 在执行前、失败转字符串不抛异常均已明确。
