# AGENTS.md — Enterprise Agent

Compact guidance for future OpenCode sessions. Only repo-specific, hard-to-infer facts.

## What this repo is
- Self-built Enterprise AI Operations Agent (Python 3.13+, FastAPI, DeepSeek via OpenAI-compatible API).
- Architecture: `FastAPI Gateway (:8761) → Agent Runtime (Planner/Executor loop) → Tool Registry → MCP/DB/RAG → Policy/HITL → Workflow → Eval/Obs`.
- Strategy: hand-rolled Runtime first (TDD), then LangGraph parity check at Stage 8.
- Three target scenarios (in order): IT Ops → Contract Compliance → Sales Analytics. Operates against the sibling `scm-platform` repo.

## Setup & run (Windows, PowerShell)
```powershell
cd D:\ProgramProject\enterprise-agent
py -m venv .venv
.\.venv\Scripts\activate
pip install -e .
copy .env.example .env   # fill DEEPSEEK_API_KEY (real or sk-xxxx for echo fallback)
pytest -q                # currently 34 passed
uvicorn apps.api.main:app --port 8761 --reload
# DeepSeek connectivity sanity check:
python scripts/check_deepseek.py
```
- `.env` is git-ignored; never commit `DEEPSEEK_API_KEY` or any real key (PR template explicitly checks this).
- Without a real key the runtime degrades to echo (`[runtime-echo] <task>`) — see `agent/runtime/llm_planner.py:14` — so tests still pass offline.

## TDD discipline (REQUIRED)
This repo is built RED → GREEN per stage. Before any implementation:
1. Write a failing test in `tests/test_<stage>.py` (file naming reflects stage: `test_health`, `test_runtime_loop`, `test_planner_llm`, `test_tools`, `test_knowledge`, `test_memory`, `test_policy`, `test_workflow`, `test_eval_obs`, `test_stage8`).
2. Run `pytest -q` to confirm RED.
3. Implement the minimum to go GREEN; refactor only after green.
- PR template enforces: `pytest -q` green + RED-first tests + no secrets.
- `pytest-asyncio` is `asyncio_mode = "auto"` — plain `def test_` works for async too.

## Package layout (single installable, top-level packages)
- `apps/api/main.py` — FastAPI gateway; `/health` and `/chat` (→ `AgentRuntime`).
- `agent/runtime/` — `state.py` (AgentState), `loop.py` (Planner→Executor→Observation→Reflection, max 8), `planner.py` (defaults), `llm_planner.py` (DeepSeek + JSON parser).
- `agent/tools/` — `registry.py` (in-memory Tool catalog), `executor.py`, `builtin.py`.
- `knowledge/` — `document.py`, `ingestion.py` (chunking with metadata), `store.py`, `seed.py` (in-memory default store).
- `security/` — `policy.py` (PolicyEngine: HIGH_RISK needs approval, cross-tenant denied, role/scope matrix) and `approval.py` (ApprovalStore).
- `workflow/` — `graph.py` (hand-rolled), `nodes/expense.py`, `graph_lang.py` (LangGraph parity with fallback), `scenarios.py` (contract + sales analyzers).
- `observability/tracing.py` — Tracer (start_trace/log_event/end_trace/get_trace).
- `evaluation/evaluator.py` — case-based evaluator.

## Cross-cutting invariants (do not break)
- **Planner JSON contract** (`agent/runtime/llm_planner.py:6`): LLM must only emit `{"action":"finish",...}` or `{"action":"call_tool","tool":...,"args":...}`. Anything else → fallback to `finish` with raw text. This is also the prompt-injection defense per `SECURITY.md`.
- **Tenant/permission filtering** in `knowledge/store.py` and `security/policy.py` must never be bypassable. Chunks always carry `tenant_id / department / permission / version`.
- **Policy check before tool execution** — LLM never calls tools directly; `guarded_executor` + `PolicyEngine` are the enforcement points.
- **LangGraph fallback**: `workflow/graph_lang.py` auto-falls-back to `run_expense_workflow` when `langgraph` is not importable (it currently is NOT installed — `pytest -q` passes via fallback). Don't assume LangGraph is available.

## Stage roadmap (see `docs/superpowers/plans/2026-09-15-enterprise-agent-roadmap.md`)
Stage 0 scaffold ✅ → 1 Runtime ✅ → 2 Tool/MCP → 3 RAG (in-memory now, pgvector later) → 4 Memory (Conv/Task/User/Org/Episodic) → 5 Policy/HITL → 6 Workflow → 7 Eval/Obs → 8 LangGraph refactor + 三场景.
- Remote Postgres + Redis live at `192.168.80.156` (`admin/123456`, exact DB name TBD — defer until Stage 3+).
- Spec/plan source of truth: `docs/superpowers/specs/2026-09-15-enterprise-agent-design.md` and the matching `plans/` file. Trust those over README prose.

## Things easy to miss
- `.idea/` is local PyCharm state (partially git-ignored via `.idea/.gitignore`); ignore it.
- `enterprise_agent.egg-info/`, `.pytest_cache/`, `.venv/`, `__pycache__/` are all in `.gitignore`.
- `.superpowers/` is git-ignored (do not commit superpowers skill cache).
- CI runs on Python 3.12 and 3.13 via `.github/workflows/ci.yml` — only `pip install -e .` then `pytest -q`. No lint/typecheck steps configured yet.
- `tests/test_health.py::test_chat_echo` and `tests/test_planner_llm.py::test_chat_goes_through_runtime` depend on echo-fallback when no key; they are not integration tests against DeepSeek.

## Where to look first when investigating
1. `pyproject.toml` + `.env.example` — deps, Python version, required env.
2. `apps/api/main.py` — real entrypoint and wire-up.
3. `agent/runtime/loop.py` + `state.py` — runtime contract used by every scenario.
4. `docs/superpowers/plans/2026-09-15-enterprise-agent-roadmap.md` — current stage + next steps.
5. `SECURITY.md` — security model and reporting channel (GitHub private vulnerability reporting, not public issues).