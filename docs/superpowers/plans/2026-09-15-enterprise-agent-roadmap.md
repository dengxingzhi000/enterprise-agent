# Enterprise Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 带练方式交付企业级 AI Operations Agent，覆盖 Runtime/Tool/RAG/Memory/Policy/HITL/Workflow/Eval/Obs。

**Architecture:** FastAPI Gateway → 自研 Agent Runtime (Planner/Executor loop) → Tool Registry → MCP/DB/RAG → Policy/HITL → Workflow → Observability。先自研，后 LangGraph 重构。

**Tech Stack:** Python 3.13+, FastAPI, Pydantic, DeepSeek (OpenAI兼容), Postgres/pgvector + Redis (远程192.168.80.156), Docker(后补), OpenTelemetry/Prometheus(后补)。

---

### Task 0: 脚手架 + Gateway (当前阶段)

**Files:**
- Create: `pyproject.toml`, `apps/api/main.py`, `tests/test_health.py`, `.env.example`
- Test: `tests/test_health.py`

- [ ] **Step 1: 安装依赖**
Run: `pip install -e .` in `D:\ProgramProject\enterprise-agent`
Expected: 安装成功

- [ ] **Step 2: 跑测试**
Run: `pytest -q`
Expected: 2 passed

- [ ] **Step 3: 启动网关**
Run: `uvicorn apps.api.main:app --port 8761`
Expected: GET /health 返回 {"status":"ok"}

### Task 1: Agent Runtime (下一阶段)
- Create: `agent/runtime/state.py` (AgentState: task/messages/plan/observations/tool_calls/iteration/status)
- Create: `agent/runtime/loop.py` (Planner→Executor→Observation→Reflection循环, max_iterations=8)
- Create: `agent/runtime/planner.py`, `agent/runtime/executor.py` (先Mock LLM + Mock Tool)
- Test: `tests/test_runtime_loop.py`

### Task 2: Tool/MCP
- Create: `agent/tools/registry.py`, `agent/tools/database.py`, `agent/tools/search.py`
- MCP Server stub for 运维三件套: metrics/logs/git

### Task 3: Knowledge RAG
- ingestion/chunking/metadata(tenant_id/department/permission/version)/embedding/retrieval/rerank

### Task 4: Memory (Conversation/Task/User/Org/Episodic)

### Task 5: Policy + HITL (Role/Resource/Action, 高风险需审批)

### Task 6: Workflow (Deterministic + Agent混合, 以报销/故障排查为例)

### Task 7: Eval + Observability (TaskSuccess/ToolAcc/RAGRecall/PolicyViolation/Latency/Cost + OTel Trace)

### Task 8: LangGraph重构 + 三场景扩展 (运维→合规→分析)
