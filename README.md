# Enterprise AI Operations Agent

**企业内部 AI 工作助手 + Agent 平台** — 自研 Agent Runtime，覆盖 Tool/MCP、RAG、Memory、Policy/HITL、Workflow、Eval/Observability。

[![CI](https://img.shields.io/github/actions/workflow/status/dengxingzhi000/enterprise-agent/ci.yml?branch=main&style=flat-square&logo=github&label=ci)](https://github.com/dengxingzhi000/enterprise-agent/actions)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue?labelColor=black&style=flat-square&logo=python)](./pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache%202.0-white?labelColor=black&style=flat-square)](./LICENSE)

> 路线：自研 Runtime 优先（`loop/state/planner/executor` 手写 + TDD），后期用 LangGraph 重构对照。三场景：IT 运维 → 合同合规 → 数据分析。

## 架构

```text
用户 → Agent Gateway (FastAPI :8761) → Agent Runtime (Planner/Executor loop)
  → Tool Registry → MCP/DB/RAG → Policy/HITL → Workflow → Eval/Trace
```

8 阶段（TDD，每阶段独立可测，当前 34 passed）：`脚手架 → Runtime → Tool/MCP → RAG → Memory → Policy/HITL → Workflow → Eval/Obs → LangGraph重构`

## 运行

```bash
cd enterprise-agent
py -m venv .venv
.venv\Scripts\activate
pip install -e .
copy .env.example .env  # 填入 DEEPSEEK_API_KEY
pytest -q
uvicorn apps.api.main:app --port 8761 --reload
# 打开 http://localhost:8761/docs → POST /chat
```

## 关联项目

- **[scm-platform](https://github.com/dengxingzhi000/scm-platform)** — Java 微服务供应链业务平台（Spring Boot 4 + Spring Cloud 2025），本 Agent 的运维/分析操作对象：订单 5xx 排查、报销合规审查、销售数据分析均以它为目标系统。
