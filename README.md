<div align="center">

# Enterprise AI Operations Agent

### 自研 Agent Runtime —— 覆盖 Tool/MCP、RAG、Memory、Policy/HITL、Workflow、Eval/Observability。

**不是 LangChain 封装，而是一个手写 Planner/Executor 循环的 Runtime，
每一个阶段都用 TDD 独立推进。**

[![CI](https://img.shields.io/github/actions/workflow/status/dengxingzhi000/enterprise-agent/ci.yml?branch=main&style=flat-square&logo=github&label=ci)](https://github.com/dengxingzhi000/enterprise-agent/actions)
[![Stars](https://img.shields.io/github/stars/dengxingzhi000/enterprise-agent?color=ffcb47&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/stargazers)
[![Forks](https://img.shields.io/github/forks/dengxingzhi000/enterprise-agent?color=8ae8ff&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/network/members)
[![Release](https://img.shields.io/github/v/release/dengxingzhi000/enterprise-agent?include_prereleases&labelColor=black&style=flat-square)](https://github.com/dengxingzhi000/enterprise-agent/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue?labelColor=black&style=flat-square&logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](./LICENSE)

[快速开始](#快速开始) · [能力矩阵](#能力矩阵) · [架构](#架构) · [FAQ](#faq) · [关联项目](#关联项目)

<code>pip install -e . &amp;&amp; uvicorn apps.api.main:app --port 8762</code>

</div>

> [!NOTE]
> **技术路线：自研 Runtime 优先。** `loop` / `state` / `planner` / `executor`
> 全部手写并以 TDD 推进，后期再用 LangGraph 重构做对照实验。
> 三个目标场景：**IT 运维 → 合同合规 → 数据分析**，目前 `run_it_ops` 已接通。

---

大模型 Agent 的难点不在于能不能调用工具，而在于多步任务中途失败时能否恢复、
需要人工审批时能否挂起并恢复、以及每一步决策能否事后追溯。这个项目把这三件事
做进了 Runtime 本身，而不是留给上层业务代码。

`enterprise-agent` 是一个从零手写的 Agent Runtime：自研 Planner/Executor 循环，
配套 Tool Registry、MCP/DB/RAG 集成、Policy 与 Human-in-the-Loop 审批、
Workflow 编排，以及 Eval 与 Trace 可观测性。所有 `SCM_*` 外部依赖都可降级为
mock，因此**不配置任何密钥也能完整跑通测试与离线链路**。

当前 v0.4.1 聚焦 SCM 集成 v2 与 HITL 闭环，测试覆盖 **128 passed**
（v0.4.0 基线 99 + v0.4.1 新增 29）。

## 快速开始

### 前置依赖

- **Python 3.12+**
- **可选**：DeepSeek API Key —— 不配置时走 echo 降级，所有工具使用 mock 实现

### 安装与运行

```bash
git clone https://github.com/dengxingzhi000/enterprise-agent.git
cd enterprise-agent

py -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -e .

copy .env.example .env          # Linux/macOS: cp .env.example .env
                                  # 填入 DEEPSEEK_API_KEY（可留空走 echo 降级）

pytest -q                       # 128 passed
uvicorn apps.api.main:app --port 8762 --reload
```

然后打开 <http://localhost:8762/docs>，向 `POST /chat` 发请求。

> [!TIP]
> **`SCM_*` 环境变量不配置时，所有 `scm.*` 工具走 mock 实现**，离线也能完整跑通。
> 这不是降级妥协，而是为了让 128 个测试不依赖任何外部服务而刻意设计的。

### 环境变量

| 变量                        | 默认值   | 说明                                                              |
| --------------------------- | -------- | ----------------------------------------------------------------- |
| `DEEPSEEK_API_KEY`          | 空       | 模型 Key；留空走 echo 降级                                        |
| `SCM_*`                     | 未设置   | SCM 集成配置；未设置时工具走 mock                                 |
| `SCM_RETRY_BACKOFF_SECONDS` | —        | 5xx / ConnectError / Timeout 的自动重试退避间隔                   |
| `tenant_map`                | 默认回退 | 启动时校验；坏 JSON / 空 dict / 未知 tenant 转 warning 并回退默认 |

> [!NOTE]
> `tenant_map` 的启动校验是 v0.4.1 新增的。配置损坏时不再直接崩溃，而是打
> warning 并回退到默认 tenant —— 但这意味着**租户隔离会静默降级**，生产环境
> 应把该 warning 当作错误处理。

## 能力矩阵

| 能力         | 提供什么                                            | 关键实现与约束                                        |
| ------------ | --------------------------------------------------- | ----------------------------------------------------- |
| Agent 循环   | 自研 Planner/Executor 循环，非框架封装              | `agent/runtime`，每个阶段独立 TDD                     |
| 工具注册     | Tool Registry 统一调度，MCP / DB / RAG 工具同构接入 | `agent/tools`；写口工具全部注册，避免 `unknown tool`  |
| 人工审批     | Policy 驱动的 HITL，`/chat` 暴露 `approval_id`      | `Policy.need_approval` 触发 Runtime paused transition |
| 可观测性     | Tracer 以 contextvar 驱动，记录每次调用与结果       | `scm_call` / `scm_result` 事件，`observability/`      |
| 上下文与记忆 | 上下文压缩 + 持久化检查点                           | `agent/context`、`agent/memory`                       |
| 知识检索     | RAG 检索接入                                        | `knowledge/`                                          |
| 工作流编排   | Workflow 组合多步任务                               | `workflow/`                                           |
| 评估         | Eval 套件                                           | `evaluation/`                                         |
| 安全         | 独立安全策略与校验层                                | `security/`                                           |
| 可靠性       | 5xx / `ConnectError` / `Timeout` 自动重试，退避可配 | `SCM_RETRY_BACKOFF_SECONDS`                           |

## 架构

```text
用户 → Agent Gateway (FastAPI :8762) → Agent Runtime (Planner/Executor loop)
  → Tool Registry → MCP/DB/RAG → Policy/HITL → Workflow → Eval/Trace
```

### 项目结构

```text
enterprise-agent/
├── agent/              # Runtime 核心
│   ├── runtime/        # Planner/Executor 循环
│   ├── tools/          # Tool Registry
│   ├── context/        # 上下文管理与压缩
│   └── memory/         # 记忆持久化
├── apps/               # FastAPI 应用与 API 层
├── workflow/           # 工作流编排
├── integrations/       # MCP / SCM 外部集成
├── knowledge/          # RAG 检索
├── security/           # 安全策略
├── evaluation/         # Eval 套件
├── observability/      # Tracer 与 Trace
├── infrastructure/     # 基础设施抽象
├── tests/              # 128 个测试
└── docs/superpowers/   # specs（设计）+ plans（实施计划）
```

### 阶段进度

每个阶段独立 TDD 推进：

脚手架 → Runtime → Tool/MCP → RAG → Memory → Policy/HITL → Workflow → Eval/Obs → LangGraph 重构

## FAQ

<details>
<summary><strong>不配置 DeepSeek API Key 能跑吗？</strong></summary>

能。模型调用会走 echo 降级，所有 `SCM_*` 工具走 mock 实现。这正是 128 个测试
不依赖任何外部服务的原因，`pytest -q` 在完全离线的环境下也应全绿。

</details>

<details>
<summary><strong>为什么不用 LangGraph / LangChain？</strong></summary>

技术路线是自研 Runtime 优先：`loop` / `state` / `planner` / `executor` 手写并以
TDD 推进，这样每一层的行为都可测试、可解释。后期会用 LangGraph 重构做对照实验，
而不是一开始就绑定框架。

</details>

<details>
<summary><strong>SCM 集成是做什么的？</strong></summary>

`SCM_*` 工具用于操作 [scm-platform](https://github.com/dengxingzhi000/scm-platform)：
订单 5xx 排查（`scm.order.get`）、库存调整（`scm.stock.adjust`）、订单取消
（`scm.order.cancel`）、供应商风险查询（`scm.supplier.get`）与合同评审钩子
（`review_contract`）。所有写口工具都已注册，配了审批策略后不会再触发
`unknown tool`。

</details>

<details>
<summary><strong>HITL 审批流程怎么走通？</strong></summary>

Policy 的 `need_approval` 触发后，Runtime 进入 paused transition，并在
`/chat` 响应里暴露 `approval_id`。调用方凭该 ID 推进审批，Runtime 再恢复执行。

</details>

## 文档

- `docs/superpowers/specs/` — 设计文档（每个特性一份）
- `docs/superpowers/plans/` — 实施计划（每阶段一份，TDD checkbox 形式）
- [SECURITY.md](./SECURITY.md) — 安全模型与漏洞报告通道

## 关联项目

- **[scm-platform](https://github.com/dengxingzhi000/scm-platform)** — Java 微服务供应链业务平台（Spring Boot 4 + Spring Cloud 2025），本 Agent 的运维/分析操作对象：订单 5xx 排查、报销合规审查、销售数据分析均以它为目标系统。

## 贡献指南

欢迎贡献！提交 PR 前请先阅读 [SECURITY.md](./SECURITY.md) 中的安全模型，
并遵循[约定式提交](https://www.conventionalcommits.org/zh-hans/)。
本项目采用 Apache License 2.0，详见 [LICENSE](./LICENSE)。

---

<div align="center">

**Built with ❤️ by [dengxingzhi](https://github.com/dengxingzhi000)**

</div>
