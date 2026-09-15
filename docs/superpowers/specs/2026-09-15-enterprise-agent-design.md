# Enterprise Agent Design (v0.1, 路线A)

## 目标
企业内部 AI 工作助手 + Agent 平台。三场景全做，顺序：运维 → 合规 → 分析。

## 架构
Gateway(FastAPI) → Runtime(Planner/Executor loop, 自研) → Tool Registry → MCP/DB/RAG → Policy/HITL → Workflow → Eval/Obs。后期 LangGraph 重构。

## 关键决策
- Python 3.12+, DeepSeek (OpenAI兼容), 远程DB 192.168.80.156 (admin/123456, 库名待确认)
- 独立仓库 D:\ProgramProject\enterprise-agent，与 scm-platform 同级
- 自研优先：Stage1手写 loop/state/planner/executor + Mock，再接真模型
- 企业约束：Chunk带 tenant_id/department/permission/version；Tool前走Policy；高风险走HITL

## 阶段
0脚手架 ✅ → 1 Runtime → 2 Tool/MCP → 3 RAG → 4 Memory → 5 Policy/HITL → 6 Workflow → 7 Eval/Obs → 8 LangGraph重构

## 自检
- 无TBD：远程库名/端口下阶段确认，不阻塞Stage0/1
- 一致性：Runtime接口与Plan Task1一致
- 范围：单计划覆盖8阶段，每阶段独立可测
