# Memory Providers + PG Connector spec#3 Design (2026-09-16, v0.3.0第三刀，A方案+大厂企业级)

## 目标
v0.3.0 spec#1+spec#2 合入（70 测试绿），九层 Context 只装了 system/task/conv(运行时)/observation/rag/tooltrace，缺 memory 五层。本 spec 装 5 接口一次到位、实现 Conv/User/Org 三层，PG 主存/InMemory 兜底；Episodic 占位留 spec#4。覆盖企业 Agent "能记住用户/组织/会话/任务/事件"的核心能力。

## 背景
- 现状：spec#2 已合入 `main`，70 测试绿；`agent/context/` 6 provider；`agent/memory/store.py` 仅最小内存存读；`workflow/durable.py` 库名 TBD。
- 约束：离线 `pytest -q` 必须绿（`PG_OFFLINE=1` 开关）；SQLAlchemy/psycopg 进 pyproject 硬依赖（CI 可装）；schema 显式可审；租户/权限强制。
- 工业对齐：等同 Google Cloud SQL / Cloud Spanner 的"连接池+重试+健康+幂等 schema + InMemory fallback"模式；接口面向未来 PG/Redis 无侵入切换。

## 关键决策（已确认）
1. 方向：5 接口占位 + Conv/User/Org 三实现（Episodic 占位）；PG 主存 + InMemory 兜底。
2. 连 PG：`PG_OFFLINE=1` 或缺 `PG_DSN/POSTGRES_DSN` → InMemory；DSN 可用 → `PGConnector`（5 池+重试+健康）。
3. 失败语义：PG outage 不阻断装配，warn + memory 层降级空 + `report.skipped` 透明。
4. 租户安全：所有 row 强制 `tenant_id`，`MemoryStore` 接口隐藏 SQL，`permission` 走 where 过滤，provider 不允许传 `'*'`。
5. schema：幂等 DDL（`CREATE TABLE IF NOT EXISTS` + 索引），启动 `ensure_schema()` 一次，失败 warn 不挂。

## 架构
Agent Runtime (loop.py) → ContextAssembler → Provider[] ← MemoryProvider(s) 注入 → MemoryStore → BaseConnector（PG/InMemory 工厂 `get_connector()` 按 env 选）。PGConnector 用 create_engine(pool_size=5, pool_pre_ping, future) + execute 3 次指数退避(1s/2s/4s) + healthcheck。Schema 模块幂等建五表 memory_user/org/conv/task/episodic（统一字段：id BIGSERIAL PK、tenant_id TEXT NOT NULL、department TEXT、permission TEXT NOT NULL DEFAULT 'public'、version INT DEFAULT 1、created_at/updated_at TIMESTAMPTZ DEFAULT now()，body 字段按层 JSONB）。DEFAULT_PROVIDERS 追加 User/Org/Conv 三层（priority 25/30/35，夹在 observation 与 tooltrace 之间）。EpisodicMemoryProvider 占位 `collect()` 返 `[]`。

## 组件
- `infrastructure/__init__.py`：新顶层包，与 `agent/`、`workflow/`、`security/` 平级。
- `infrastructure/pg/__init__.py`：导出 `get_connector / PGConnector / InMemoryConnector / ensure_schema`。
- `infrastructure/pg/schema.py`：`SCHEMA_DDL` 列表 + `ensure_schema(conn)` 幂等遍历执行。
- `infrastructure/pg/connector.py`：`BaseConnector(execute/fetch_all/fetch_one/healthcheck/ensure_schema)` 抽象；`PGConnector(create_engine + retry + healthcheck + ensure_schema on first use)`；`InMemoryConnector(dict + Lock)`；`get_connector()` 读 `PG_DSN`/`POSTGRES_DSN`/`PG_OFFLINE`，首连失败/超时→InMemory + warn。
- `agent/memory/store.py`：`MemoryStore(connector)` 统一 `put/get/query(layer, tenant_id, permission, dept=None, limit=10)`，强制 where。
- `agent/context/memory_providers.py`：`BaseMemoryProvider(BaseProvider)` + 三实现 `ConvMemoryProvider(keep_recent=10) / UserMemoryProvider / OrgMemoryProvider` + `EpisodicMemoryProvider` 占位。
- `agent/context/providers.py`：`DEFAULT_PROVIDERS` 追加 User/Org/Conv（priority 25/30/35）。
- `apps/api/main.py`：启动调 `get_connector().ensure_schema()`。
- `pyproject.toml`：`sqlalchemy>=2.0` + `psycopg[binary]>=3.1` 进硬依赖。
- `.env.example`：注释加 `PG_OFFLINE=0` `MEMORY_POOL_SIZE=5` `MEMORY_QUERY_LIMIT=10`。

## 数据流
每轮 assembler.assemble(state)：spec#1+2 6 provider → memory 三 provider collect → MemoryStore.query(layer, tenant_id, permission, limit=10) → connector SELECT → segs 进预算/压缩/丢弃。PG outage：execute 重试3次仍败 → warn + 降级空 list → provider collect 返 [] → `report.skipped` 加 `memory_*` → 业务继续。CI：`PG_OFFLINE=1` → 工厂直返 InMemoryConnector → 全 dict 读写 → pytest 全绿。

## 错误处理
- `get_connector()` 缺 DSN/`PG_OFFLINE=1` → InMemory + warn；首连超时5s → InMemory + warn。
- `PGConnector.execute` 重试3次仍败 → `OperationalError` → MemoryStore 捕获 → warn + 空 list。
- `ensure_schema()` 失败 warn 不抛（schema 缺失时 InMemory 兜底）；幂等。
- MemoryStore 异常 → provider collect 返 [] → `report.skipped += ['memory_<layer>']`，不阻断。
- 越权调用：MemoryStore `tenant_id` 必填；provider 不暴露 SQL。

## 测试
新文件 `tests/test_memory_pg.py`（TDD RED 先行）：
1. `InMemoryConnector` CRUD + `healthcheck()` 真返 True。
2. `PGConnector` monkeypatch `create_engine` 验重试/healthcheck/ensure_schema 调用形状。
3. `get_connector()` 工厂：`PG_OFFLINE=1`/缺 DSN → InMemory；DSN 设了走 PGConnector。
4. `ensure_schema()` 幂等调两次不报错。
5. `MemoryStore` 跨 tenant 隔离 + permission 过滤生效。
6. `MemoryProvider` 端到端：Conv/User/Org 返对应格式 seg；Episodic 返 []；装配集成测 20 轮 obs + memory 触发压缩。
7. `loop.py` outage 注入：`PGConnector.execute` raise → `state.context["context_report"]["skipped"]` 含 `memory_*`。
约束：SQLAlchemy/psycopg 硬依赖（CI 装得到）；`PG_OFFLINE=1` 离线绿；70 旧测试全过；schema 文件 commit 可审；不提交真 DSN/secret。

## 范围外（spec#4 / 后续）
- `EpisodicMemoryProvider` 真正实现（事件溯源）。
- `AgentTask` 字段接线（task_id/thread_id/status/checkpoint_id/token_usage/cost 补齐）。
- Workflow/Graph 接线 memory。
- OTel/Prom 替换内存 Tracer。
- v0.2.0 遗留：真 PG 杀进程恢复。

## 自检
- 无占位：默认 `MEMORY_POOL_SIZE=5`/`MEMORY_QUERY_LIMIT=10`/`PG_OFFLINE=0`；priority 25/30/35 定死；keep_recent=10；超时5s；重试3次1s/2s/4s。
- 一致性：架构↔组件↔数据流↔错误↔测试均围绕"5 接口占位 + 3 实现 + PG 主 InMemory 备 + outage warn 不阻断"，无矛盾。
- 范围：单 spec 只做 memory provider + connector + schema，不含 AgentTask/Workflow/OTel。
- 无歧义：permission='tenant' 强制、tenant_id 必填、Episodic 占位返 []、`PG_OFFLINE=1` 开关均显式。