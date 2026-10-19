<div align="center">

**English** · [简体中文](./README.zh-CN.md)

# Enterprise AI Operations Agent

### 一个从零手写的 Agent Runtime，而不是 LangChain 封装。

**自研 Planner/Executor 循环，配套 Tool/MCP、RAG、Memory、Policy/HITL、
Workflow 与 Eval/Observability。每一个阶段都用 TDD 独立推进。**

[![CI](https://img.shields.io/github/actions/workflow/status/dengxingzhi000/enterprise-agent/ci.yml?branch=main&style=flat-square&logo=github&label=ci)](https://github.com/dengxingzhi000/enterprise-agent/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/dengxingzhi000/enterprise-agent?color=ffcb47&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/stargazers)
[![Forks](https://img.shields.io/github/forks/dengxingzhi000/enterprise-agent?color=8ae8ff&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/network/members)
[![Issues](https://img.shields.io/github/issues/dengxingzhi000/enterprise-agent?color=ff80eb&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/issues)
[![Release](https://img.shields.io/github/v/release/dengxingzhi000/enterprise-agent?include_prereleases&color=ffcb47&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-007396?logo=python&logoColor=white&style=flat-square)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-%3E%3D0.115-009688?logo=fastapi&logoColor=white&style=flat-square)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](#许可证)

**[快速开始](#快速开始) · [能力矩阵](#能力矩阵) · [架构](#架构) · [人工审批](#人工审批闭环) · [常见问题](#常见问题) · [文档](#文档)**

```bash
pip install -e . && uvicorn apps.api.main:app --port 8762
```

</div>

> [!IMPORTANT]
> **三个 SCM 写工具是占位实现。** `scm.purchase.create`、`scm.order.cancel`、
> `scm.stock.adjust` 虽然已注册、planner 也能点名调用，但每一个都只返回固定的
> `"need approval: … pending human review"` 字符串，**不会真的改动任何数据**。
> 实际上它们根本走不到——`guarded_executor` 会先在
> `PolicyEngine.need_approval` 处拦截；注册它们只是为了防御 Policy 配置失误。
> 其余部分走的才是真实 HTTP 或真实本地代码。

> [!NOTE]
> **技术路线：自研 Runtime 优先。** `loop` / `state` / `planner` / `executor`
> 全部手写并以 TDD 推进，每一层都可独立测试。LangGraph 重构计划作为对照实验，
> 而不是一开始就绑定框架。三个目标场景：**IT 运维 → 合同合规 → 数据分析**，
> 目前 `run_it_ops` 已接通。

---

大模型 Agent 的难点不在于能不能调用工具，而在于多步任务中途失败时能否恢复、
需要人工审批时能否挂起并恢复、以及每一步决策能否事后追溯。这个项目把这三件事
做进了 Runtime 本身，而不是留给上层业务代码。

`enterprise-agent` 是一个从零手写的 Agent Runtime：自研 Planner/Executor 循环，
配套 Tool Registry（MCP / DB / RAG 工具同构接入）、Policy 与 Human-in-the-Loop
审批、Workflow 编排，以及 Eval 与 Trace 可观测性。

所有 `SCM_*` 外部依赖在未配置时都会退化为 mock，因此**不配置任何密钥也能完整跑通
测试与离线链路**。这不是降级妥协，而是为了让 128 个测试完全不依赖任何外部服务而
刻意设计的。

当前 v0.4.1 聚焦 SCM 集成 v2 与 HITL 闭环：测试覆盖 **128 passed**
（v0.4.0 基线 99 + v0.4.1 新增 29）。

## 快速开始

> [!NOTE]
> **需要 Python 3.12 或更高版本。** CI 在 3.12 与 3.13 两个版本上跑矩阵。

### 前置依赖

| 工具 | 版本 | 是否必需 |
|---|---|---|
| **Python** | 3.12+ | 必需 |
| **DeepSeek API Key** | — | 不需要——planner 走 `echo` 降级，工具全部返回 mock |
| **scm-platform** | 已启动 | 不需要——未设 `SCM_GATEWAY_URL` 时 SCM 工具自行 mock |

### 安装与运行

```bash
git clone https://github.com/dengxingzhi000/enterprise-agent.git
cd enterprise-agent

py -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -e .

copy .env.example .env          # Linux/macOS: cp .env.example .env
                                  # DEEPSEEK_API_KEY 可留空

pytest -q                       # 128 passed
uvicorn apps.api.main:app --port 8762 --reload
```

然后打开 <http://localhost:8762/docs>，向 `POST /chat` 发请求。

### 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 存活检查——返回 `{"status": "ok", "stage": 1}` |
| `POST` | `/chat` | 执行一次 agent 任务 |
| `GET` | `/docs` | OpenAPI 文档 |

```bash
curl -X POST http://localhost:8762/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "订单 20260915001 为什么没发货?", "tenant_id": "t1", "user_id": "u1"}'
```

正常结束会返回 `reply`、`status`、`task_id`、`trace_id`；有 token 消耗时还带
`token_usage` 与 `cost`。命中审批门时返回 `status: "paused"`，并附带
`approval_id`、`approval_tool`、`approval_args`。

### 环境变量

每一项都有可用的默认值。只跑 `pip install -e .` 就足以跑测试与离线链路。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | 模型 Key；留空走 `echo` 降级 planner |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型 id，同时也是成本核算的定价键 |
| `SCM_GATEWAY_URL` | 未设置 | **未设置 ⇒ 所有 `scm.*` 工具走 mock**；设置后才变成真实 REST 调用 |
| `SCM_AUTH_URL` | `http://localhost:8106` | scm-platform 认证服务 |
| `SCM_USERNAME` / `SCM_PASSWORD` | 空 | scm-platform 凭据 |
| `SCM_TENANT_MAP` | `{"t1":"tenant_001"}` | 把 agent 的 `tenant_id` 映射到 SCM 的 `tenant` 参数 |
| `SCM_TIMEOUT_SECONDS` | `5` | 单次请求超时 |
| `SCM_RETRY_BACKOFF_SECONDS` | `0.3` | 5xx / `ConnectError` / `Timeout` 重试一次前的 sleep |
| `AGENT_PORT` | `8762` | 网关期望端口 |
| `POSTGRES_DSN` / `PG_DSN` | 未设置 | 记忆存储；两者都设时 `PG_DSN` 优先 |
| `PG_OFFLINE` | 未设置 | 无论 DSN 如何都强制记忆存储离线 |
| `CONTEXT_BUDGET_TOKENS` | `8000` | Assembler 强制总用量不超过该预算 |
| `CONTEXT_RESERVED_TOKENS` | `1000` | 为回复预留的部分 |
| `CONTEXT_COMPRESS_RATIO` | `0.8` | 用量超过可用预算该比例即触发压缩 |
| `CONVERSATION_KEEP_RECENT` | `3` | 逐字保留的最近对话轮数 |
| `OBSERVATION_KEEP_RECENT` | `5` | 逐字保留的最近 observation 数 |
| `MODEL_PRICING_INPUT` / `_OUTPUT` | `0.001` / `0.002` | `AgentTask.cost` 的每千 token 定价 |
| `AGENT_STATUS_HISTORY` | `50` | 状态历史环形缓冲上限 |

> [!WARNING]
> **`SCM_TENANT_MAP` 失效时是「放行」而不是「拒绝」。** 坏 JSON、空 dict
> 或未知 tenant 都只打 warning 并回退默认 tenant，而不是抛错。
> 这意味着**租户隔离会静默降级**——生产环境请把该 warning 当作错误处理。

> [!NOTE]
> `langgraph`、`redis`、`tiktoken` 都**刻意不是**硬依赖。
> 未安装 `langgraph` 时 `workflow/checkpoint.py` 会告警并退化为内存 checkpointer；
> 没有 `tiktoken` 时 token 计数退化为启发式估算。离线 CI 必须保持全绿。

## 能力矩阵

| 图标 | 领域 | 提供什么 | 关键实现与约束 |
|---|---|---|---|
| 🔁 | **Agent 循环** | 自研 Planner/Executor 循环，非框架封装 | `agent/runtime`，每个阶段独立 TDD |
| 🧰 | **工具注册** | Tool Registry 统一调度，MCP / DB / RAG 工具同构接入 | `agent/tools`；写口工具全部注册，避免 `unknown tool` |
| 🛡️ | **策略** | 读 = allow，写 = need approval，未注册 = deny | `integrations/scm/policy_map.py`，默认拒绝 |
| ✋ | **人工审批** | 任务在审批处挂起，凭 id 恢复 | `guarded_executor` → `paused` transition → 响应里的 `approval_id` |
| 📉 | **可观测性** | Tracer 以 contextvar 驱动，记录每次调用与结果 | `observability/`；`scm_call` / `scm_result` 事件 |
| 🧠 | **上下文与记忆** | 预算化装配、压缩、持久化记忆 | `agent/context`、`agent/memory`；PG 挂掉时降级 |
| 📚 | **知识检索** | RAG 检索接入 | `knowledge/` |
| 🔀 | **工作流编排** | 多步编排与检查点 | `workflow/`，装了 LangGraph 后可走持久化路径 |
| 📊 | **评估** | Eval 套件 | `evaluation/` |
| 🔒 | **安全** | 独立的安全策略与校验层 | `security/` |
| 🔁 | **可靠性** | 5xx / `ConnectError` / `Timeout` 自动重试一次，退避可配 | `SCM_RETRY_BACKOFF_SECONDS` |
| 💰 | **成本** | 按任务累计 token 用量与成本 | `AgentTask`，按 `DEEPSEEK_MODEL` 定价 |

## 架构

```
   ┌──────────────────────────────────────────────────────────┐
   │  POST /chat                                              │
   │  message · tenant_id · user_id · task_id                 │
   └───────────────────────────┬──────────────────────────────┘
                               ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Tracer.start_trace()      trace_id ── contextvar ──┐    │
   └───────────────────────────┬─────────────────────────┼───┘
                               ▼                         │
   ┌──────────────────────────────────────────────────────────┐
   │  agent.runtime.loop.run(state, planner, executor)      │◀─┐
   │                                                          │  │
   │   ┌───────────────┐   plan.action   ┌──────────────────┐ │  │
   │   │ ContextAssembler│───────────────▶│     Planner      │ │  │
   │   │ 预算+压缩      │                │ DeepSeek / echo  │ │  │
   │   └───────────────┘                 └────────┬─────────┘ │  │
   │                                             │           │  │
   │                          ┌──────────────────┴────────┐  │  │
   │                          │                           │  │  │
   │                 action=finish                action=call_tool
   │                          │                           │  │  │
   │                          ▼                           ▼  │  │
   │                     status=done        ┌──────────────────┐
   │                                       │guarded_executor  │──┘
   │                                       │ Policy.need_approval
   │                                       └────────┬─────────┘
   │                          ┌─────────────────────┼─────────────────────┐
   │                          │ allow               │ need_approval       │ deny
   │                          ▼                     ▼                     ▼
   │                   Tool Registry         status=paused          status=failed
   │                          │             + approval_id
   │        ┌─────────┬───────┼────────┬────────────┐
   │        ▼         ▼       ▼        ▼            ▼
   │   metrics  logs.   git.  db.   knowledge  scm.*（4 个读口）
   │   .get     search   diff   query   .search     │
   │                                                 └── 3 个写口工具：占位
   └──────────────────────────────────────────────────────────┘
                               │
                               ▼
        workflow/ · evaluation/ · observability/ · infrastructure/pg
```

这张图里有三处性质，正是这个项目想表达的东西：

**循环是可读的。** `agent/runtime/loop.py` 里的 `run()` 是 100 行纯 Python，
底下没有任何框架。每一个出口——`finish_received`、`executor_error`、
`unknown_action`、`need_approval`、`max_iterations`——都会设置状态、记录
token、发一条 trace 事件再返回。没有任何东西藏在框架回调里。

**HITL 门是状态转移，不是异常。** `guarded_executor` 发现写口工具、
`PolicyEngine.need_approval` 触发时，observation 里带上 `"need approval"`
结果。循环识别这个前缀，转移到 `paused`，然后**干净地 break**——task 对象
保持有效，`approval_id` 回传给调用方。恢复是正常延续，不是异常恢复路径。

**mock 是默认，不是兜底。** `register_scm_tools` 里的 `_use_mock()` 判断的就是
「`SCM_GATEWAY_URL` 有没有设」。没设就是 mock。正是这一点让 128 个离线测试
成立，也让 CI 保持封闭。

### 项目结构

```
enterprise-agent/
├── apps/
│   └── api/main.py          # FastAPI 网关：/health、/chat
├── agent/
│   ├── runtime/             # loop · planner · state · status · agent_task · counter
│   ├── tools/               # registry · executor（guarded）· builtin
│   ├── context/             # assembler、预算、压缩
│   └── memory/              # 持久化存储
├── integrations/
│   └── scm/                 # client · auth · tools · policy_map
├── security/                # PolicyEngine · ApprovalStore
├── workflow/                # graph · durable · checkpoint · scenarios
├── knowledge/               # RAG 检索
├── evaluation/              # eval 套件
├── observability/           # Tracer 与 trace 存储
├── infrastructure/pg/       # connector、schema
├── tests/                   # 128 个测试
└── docs/superpowers/        # specs/（设计）+ plans/（TDD 计划）
```

### 阶段进度

每个阶段都在 TDD 下独立推进：

脚手架 → Runtime → Tool/MCP → RAG → Memory → Policy/HITL → Workflow →
Eval/Obs → LangGraph 重构

## 人工审批闭环

审批闭环是大多数 Agent 框架留给调用方处理的部分，所以这里把实际行为写清楚。

```
   POST /chat ──▶ planner 想调用写口工具
                     │
                     ▼
        PolicyEngine.need_approval(tool, user)
                     │
        ┌────────────┴────────────┐
        │ allow                   │ need_approval
        ▼                         ▼
   工具执行              guarded_executor 返回
                           observation "need approval: …"
                                │
                                ▼
                    循环识别该前缀，break
                                │
                                ▼
              status=paused，记录 transition，
              响应中带上 approval_id
              + approval_tool + approval_args
                                │
                                ▼
             调用方处理完审批后，用同一个
             task_id 恢复执行
```

`scm_policy_decision` 就是全部策略：读口工具 `allow`，写口工具
`need_approval`，**未注册的一律 `deny`**。默认是关着的。

## 常见问题

<details>
<summary><strong>不配置 DeepSeek API Key 能跑吗？</strong></summary>

能。模型调用走 `echo` 降级，所有 `SCM_*` 工具走 mock 实现。这正是 128 个测试
不依赖任何外部服务的原因，`pytest -q` 在完全离线的环境下也应全绿。

</details>

<details>
<summary><strong>为什么不用 LangGraph / LangChain？</strong></summary>

技术路线是自研 Runtime 优先：`loop` / `state` / `planner` / `executor` 手写并以
TDD 推进，这样每一层的行为都可独立测试、可解释。LangGraph 是计划中的重构，
目的是做一次有对照的实验，而不是一开始就绑定框架——这正是
`workflow/graph_lang.py` 与 `workflow/durable.py` 和手写路径并存、
且 `langgraph` 始终作为可选依赖的原因。

</details>

<details>
<summary><strong>SCM 集成到底做了什么？</strong></summary>

四个读口工具通过 REST 调用
[scm-platform](https://github.com/dengxingzhi000/scm-platform)，带租户映射，
并对 5xx / `ConnectError` / `Timeout` 重试一次：

| 工具 | 调用 | 用途 |
|---|---|---|
| `scm.order.get` | `GET /api/orders/{order_no}` | 订单 5xx 排查 |
| `scm.inventory.query` | `GET /api/inventory` | 库存查询 |
| `scm.sales.report` | `GET /api/analytics/sales` | 销售聚合 |
| `scm.supplier.get` | `GET /api/suppliers/{id}` | 供应商风险 |

三个写口工具——`scm.purchase.create`、`scm.order.cancel`、
`scm.stock.adjust`——如顶部所标注，是**占位实现**。注册它们是刻意的：
否则 planner 可能生成一个 registry 从没听过的工具名，executor 会在
Policy 层有机会审批之前就先抛 `unknown tool`。

</details>

<details>
<summary><strong>HITL 真的端到端打通了吗？</strong></summary>

挂起与恢复的路径是通的：`/chat` 返回 `status: "paused"` 并带上
`approval_id`，trace 记录了这次转移。`workflow/durable.py` 与
`tests/test_durable_langgraph.py` 覆盖了持久化检查点路径。

**没有**实现的是恢复接口。`apps/api/main.py` 的请求里接受 `task_id`，
但并不存在用来结清审批并把任务推进到完成的 `/approvals/{id}` 路由。
所以目前的挂起任务是「一个挂起态对象」，还不是一次完整往返。

</details>

<details>
<summary><strong>上下文是怎么控制在 token 预算内的？</strong></summary>

`ContextAssembler` 强制 `CONTEXT_BUDGET_TOKENS` 减去
`CONTEXT_RESERVED_TOKENS`。用量超过可用预算的 `CONTEXT_COMPRESS_RATIO` 时
触发压缩，逐字保留最近 `CONVERSATION_KEEP_RECENT` 轮对话与
`OBSERVATION_KEEP_RECENT` 条 observation，其余做摘要。装配结果写入
`context_report` 并发出 `context_assemble` trace 事件，因此可以确认模型
实际拿到的到底是什么。

token 计数需要 `tiktoken`；没有它时运行时退化为启发式估算，而不是失败。

</details>

<details>
<summary><strong>PostgreSQL 挂掉时会怎样？</strong></summary>

记忆存储会静默降级并告警——`tests/test_memory_pg.py` 明确覆盖了这一点
（`test_memory_store_outage_degrades_silently`）。记忆层不可用不应该拖垮
整个 agent 任务。

可以设 `PG_OFFLINE=1` 主动跳过它。但请注意那句话里「静默」二字是有分量的：
持久化记忆故障，表现出来的是一个「看起来正常、但什么都记不住」的 agent。

</details>

## 文档

| 文档 | 内容 |
|---|---|
| [设计文档](./docs/superpowers/specs/) | 每个特性一份设计文档 |
| [实施计划](./docs/superpowers/plans/) | 每个阶段一份 TDD 计划（checkbox 形式） |
| [安全模型](./SECURITY.md) | 威胁模型与私密报告通道 |
| [更新日志](./CHANGELOG.md) | 每个版本改了什么 |
| [贡献指南](./CONTRIBUTING.md) | 分支约定与 CI 检查项 |

安全问题请走 [SECURITY.md](./SECURITY.md)，不要开 issue。

## Star 历史

<a href="https://www.star-history.com/?repos=dengxingzhi000%2Fenterprise-agent&amp;type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dengxingzhi000/enterprise-agent&amp;type=date&amp;theme=dark&amp;legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dengxingzhi000/enterprise-agent&amp;type=date" />
    <img alt="Enterprise AI Operations Agent GitHub star 历史" src="https://api.star-history.com/chart?repos=dengxingzhi000/enterprise-agent&amp;type=date" />
  </picture>
</a>

## 关联项目

- **[scm-platform](https://github.com/dengxingzhi000/scm-platform)** —— 本 Agent 操作的目标系统：Java 微服务供应链业务平台（Spring Boot 4 + Spring Cloud 2025）。订单 5xx 排查、报销合规审查、销售数据分析均以它为目标。

## 贡献指南

提交 PR 前请先读 [CONTRIBUTING.md](./CONTRIBUTING.md)——里面讲了分支约定，
以及 CI 具体会检查什么。

1. Fork 仓库
2. 创建分支（`git checkout -b feat/…`）
3. 推送前先跑 `pytest -q`——CI 会在 Python 3.12 与 3.13 上各跑一遍
4. 使用 PR 模板开 pull request

提交信息遵循 [约定式提交](https://www.conventionalcommits.org/zh-hans/)。
参与行为受[行为准则](./CODE_OF_CONDUCT.md)约束。

## 许可证

[Apache License 2.0](./LICENSE)

---

<div align="center">

**Built with ❤️ by [dengxingzhi](https://github.com/dengxingzhi000)**

</div>
