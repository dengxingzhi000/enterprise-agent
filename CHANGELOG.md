# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Version numbers are cut from the roadmap, not derived automatically, so
0.1.0 → 0.2.0 is not "one more release" — read the entries.

## [Unreleased]

Nothing yet.

## [0.4.1] — 2026-09-18

SCM Integration v2 plus the closed HITL loop. Closes seven gaps from the
v0.4.0 roadmap against a live scm-platform backend.

### Added

- **Write tools registered.** `scm.order.cancel` and `scm.stock.adjust` join
  `scm.purchase.create`. All three are placeholders that return a
  `"need approval: …"` result; registering them stops the planner from
  emitting a name the registry has never seen.
- **Retry on 5xx / `ConnectError` / `Timeout`.** `ScmClient.get` retries once
  with configurable backoff (`SCM_RETRY_BACKOFF_SECONDS`, default 0.3 s) and
  never raises.
- **`run_it_ops` scenario.** `workflow.scenarios` stitches `metrics.get`,
  `logs.search`, and `scm.order.get` into an IT-operations diagnostic path —
  the first of the three roadmap scenarios.
- **`/chat` surfaces `approval_id`.** The payload now exposes `approval_id`,
  `approval_tool`, and `approval_args` when the Runtime ends paused.
- **`scm.supplier.get` plus the `review_contract` supplier hook.** Real
  supplier risk data reaches contract review.
- **`scm_call` / `scm_result` trace events.** A `contextvar`-based hook fires
  whenever `scm_trace_id` is set by `/chat`.
- **`tenant_map` validation.** Bad JSON, an empty dict, or an unknown tenant
  now warns and falls back instead of dropping silently.

### Fixed

A final code review caught one **blocking** defect: the production `/chat`
path never reached `guarded_executor`, so the policy gate was inert in the
deployed gateway even though unit tests passed. Fixed by injecting the
executor as a lambda, plus one real integration test.

### Quality

- 3 PRs (#17, #18, #19), 28 new tests, 128 passing on Python 3.12 and 3.13.

### Deferred to v3

- `/approval/{aid}/decide` HTTP endpoint
- `ApprovalStore` persistence to Postgres
- `/chat/{task_id}/resume` from a paused state
- LangGraph refactor

## [0.4.0] — 2026-09-16

`AgentTask`, `Counter`, and `Pricing`.

### Added

- `AgentTask` dataclass with a uuid4 id and a state machine over
  pending / running / paused / done / failed / cancelled, a 50-entry history
  cap, an invalid-transition guard, and `attach_checkpoint`.
- `Counter` (tiktoken-first, heuristic fallback) and `Pricing`
  (`deepseek-chat` defaults, env-overridable).
- The loop auto-wraps `AgentState` → `AgentTask`, records tokens each round,
  and emits `task_status_changed` trace events.
- Planner and executor exceptions now produce a `failed` transition, so the
  state machine always converges.

### Changed

- `/chat` exposes `task_id`, `token_usage`, and `cost`.

### Quality

- 91 tests passed (78 baseline + 13 new); CI green on 3.12 and 3.13.

### Known follow-ups

- `Tracer._shared` thread safety, before async arrives
- `AgentState.status` redundancy against `AgentTask.status` (Stage 8 refactor)
- `AgentTask` auth and identity
- Carried over from v0.2.0: real-PG kill-process restore across restarts

## [0.3.0] — 2026-09-16

Context engineering and the five-layer memory model.

### Added

**Context — nine-layer assembly, budget, compression**

- Tiktoken-accurate counting with a heuristic fallback; `TokenBudget` with
  priority-based dropping; system and task layers are never dropped.
- Six base providers (System, Task, Conversation, Observation, RAG,
  ToolTrace), three memory providers (User, Org, Conversation), one
  placeholder (Episodic).
- Dependency-free extractive summarisation, triggered above 0.8 × available,
  keeping the most recent turns per layer; the original text is preserved in
  state for the durable path.
- RAG score tiering with a 40–60 clamp, NaN/inf hardening, and unique ids for
  same-named chunks so a dedup pass cannot delete the wrong one.
- Loop wiring: the planner receives the assembled window plus a defensive
  copy; executor and state see the full set.
- `context_quality_gate` asserts usage ≤ 0.7 × baseline with an unchanged
  decision.

**Memory — five interfaces, Postgres primary, in-memory fallback**

- `infrastructure/pg/connector.py`: `InMemoryConnector` for dev and CI plus
  `PGConnector` (pool size 5, `pool_pre_ping`, retries at 1 s / 2 s / 4 s,
  healthcheck).
- `infrastructure/pg/schema.py`: idempotent DDL for five tables plus four
  tenant indexes.
- `agent/memory/store.py`: tenant enforced, `'*'` permission rejected, SQL
  pushdown with `ORDER BY updated_at DESC LIMIT`, warn on outage.
- `agent/context/memory_providers.py`: outage raises `MemoryOutage` and the
  assembler transparently skips the layer.

### Quality

- 70 → 78 tests, passing offline via the `PG_OFFLINE` fallback. CI green on
  3.12 and 3.13. No hardcoded secrets.

### Known follow-ups

- `AgentTask` field wiring
- A real `EpisodicMemoryProvider`
- `@app.on_event("startup")` → lifespan handler
- Replacing the in-memory Tracer with OTel / Prometheus
- Carried over: real-PG kill-process restore (database name TBD)

## [0.2.0] — 2026-09-16

Durable checkpointing.

### Added

- Checkpointer that prefers Postgres and falls back to memory, honouring
  `PG_DSN`.
- Durable expense graph: `thread_id` pause and resume, `interrupt`, and a
  dual-write to `ApprovalStore`.
- Node-level guards: 5 s timeout, 3 retries, 1 s / 2 s / 4 s backoff,
  idempotency keys, loop limit of 8, and fault-chain tracing.

### Quality

- 34 → 43 tests; CI green on 3.12 and 3.13.

### Known limitations

Stated honestly in the release: the real-PG and LangGraph paths were verified
by mock shape only. Kill-process restore against a real database is still
pending database-name confirmation. `langgraph` and `redis` remain optional
dependencies so the offline path stays green.

## [0.1.0] — 2026-09-15

First usable milestone: the hand-built Agent Runtime end to end, TDD, 34
tests.

### Added

- Stage 0 — scaffolding and the FastAPI gateway
- Stages 1/1b — `AgentState`, the Planner/Executor loop, DeepSeek planner
- Stage 2 — Tool Registry plus the four ops tools (metrics, logs, git, db)
- Stage 3 — enterprise RAG with hard tenant and permission filtering
- Stage 4 — five-layer memory (Conversation, Task, User, Org, Episodic)
- Stage 5 — `PolicyEngine` and `ApprovalStore`
- Stage 6 — deterministic workflow (auto-approve or route to a human)
- Stage 7 — `Tracer` and `Evaluator` (TaskSuccess, PolicyViolation)
- Stage 8 — LangGraph alignment layer and the three scenarios

### Changed

The gateway port moved from `:8761` to `:8762` in v0.2.0 so it does not
collide with the scm-platform gateway, which also uses 8761. `.env.example`
now carries `AGENT_PORT=8762` and `SCM_GATEWAY_URL=http://localhost:8761`.

[Unreleased]: https://github.com/dengxingzhi000/enterprise-agent/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/dengxingzhi000/enterprise-agent/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/dengxingzhi000/enterprise-agent/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/dengxingzhi000/enterprise-agent/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dengxingzhi000/enterprise-agent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dengxingzhi000/enterprise-agent/releases/tag/v0.1.0
