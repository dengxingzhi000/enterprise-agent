# Enterprise AI Operations Agent

**企业内部 AI 工作助手 + Agent 平台** — 自研 Agent Runtime，覆盖 Tool/MCP、RAG、Memory、Policy/HITL、Workflow、Eval/Observability。

[![CI](https://img.shields.io/github/actions/workflow/status/dengxingzhi000/enterprise-agent/ci.yml?branch=main&style=flat-square&logo=github&label=ci)](https://github.com/dengxingzhi000/enterprise-agent/actions)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue?labelColor=black&style=flat-square&logo=python)](./pyproject.toml)
[![Release](https://img.shields.io/github/v/release/dengxingzhi000/enterprise-agent?include_prereleases&labelColor=black&style=flat-square)](../../releases)
[![License](https://img.shields.io/badge/license-Apache%202.0-white?labelColor=black&style=flat-square)](./LICENSE)

> 路线：自研 Runtime 优先（`loop/state/planner/executor` 手写 + TDD），后期用 LangGraph 重构对照。三场景：IT 运维 → 合同合规 → 数据分析。

## v0.4.1 — SCM Integration v2 + HITL 闭环

最新发布补齐了 7 项 v0.4.0 roadmap 缺口：

- **写口占位全注册**（scm.order.cancel / scm.stock.adjust）— `Policy.need_approval` 后不再触发 `unknown tool`
- **5xx + ConnectError + Timeout 自动重试**（`SCM_RETRY_BACKOFF_SECONDS` 可配）— 联调网络抖动不再刷屏
- **IT Ops 场景 (`run_it_ops`)** — metrics + logs + scm.order.get 模板；Roadmap 三场景首项已接通
- **`/chat` 暴露 `approval_id`** — Runtime paused transition + payload 暴露，HITL 闭环可达
- **`scm.supplier.get` + `review_contract` 供应商钩** — 合同评审接入真实供应商风险
- **Tracer `scm_call`/`scm_result` 事件** — contextvar 驱动的可观测性
- **`tenant_map` 启动校验** — 坏 JSON / 空 dict / 未知 tenant 现在 warning + 回退默认

测试覆盖：**128 passed**（v0.4.0 baseline 99 + v0.4.1 新增 29）。

## 架构

```text
用户 → Agent Gateway (FastAPI :8762) → Agent Runtime (Planner/Executor loop)
  → Tool Registry → MCP/DB/RAG → Policy/HITL → Workflow → Eval/Trace
```

阶段进度（每阶段独立 TDD）：脚手架 → Runtime → Tool/MCP → RAG → Memory → Policy/HITL → Workflow → Eval/Obs → LangGraph 重构

## 运行

```bash
cd enterprise-agent
py -m venv .venv
.venv\Scripts\activate
pip install -e .
copy .env.example .env  # 填入 DEEPSEEK_API_KEY（可留空走 echo 降级）
pytest -q                  # 128 passed
uvicorn apps.api.main:app --port 8762 --reload
# 打开 http://localhost:8762/docs → POST /chat
```

`SCM_*` 环境变量未配置时，所有 `scm.*` tool 走 mock 实现，离线也能跑。

## 关联项目

- **[scm-platform](https://github.com/dengxingzhi000/scm-platform)** — Java 微服务供应链业务平台（Spring Boot 4 + Spring Cloud 2025），本 Agent 的运维/分析操作对象：订单 5xx 排查、报销合规审查、销售数据分析均以它为目标系统。

## 文档

- `docs/superpowers/specs/` — 设计文档（每个特性一份）
- `docs/superpowers/plans/` — 实施计划（每阶段一份，TDD checkbox 形式）
- `SECURITY.md` — 安全模型与漏洞报告通道