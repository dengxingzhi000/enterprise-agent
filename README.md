<div align="center">

**English** · [简体中文](./README.zh-CN.md)

# Enterprise AI Operations Agent

### A hand-written Agent Runtime — not a LangChain wrapper.

**Self-built Planner/Executor loop with Tool/MCP, RAG, Memory, Policy/HITL,
Workflow, and Eval/Observability. Every stage advanced with TDD.**

[![CI](https://img.shields.io/github/actions/workflow/status/dengxingzhi000/enterprise-agent/ci.yml?branch=main&style=flat-square&logo=github&label=ci)](https://github.com/dengxingzhi000/enterprise-agent/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/dengxingzhi000/enterprise-agent?color=ffcb47&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/stargazers)
[![Forks](https://img.shields.io/github/forks/dengxingzhi000/enterprise-agent?color=8ae8ff&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/network/members)
[![Issues](https://img.shields.io/github/issues/dengxingzhi000/enterprise-agent?color=ff80eb&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/issues)
[![Release](https://img.shields.io/github/v/release/dengxingzhi000/enterprise-agent?include_prereleases&color=ffcb47&labelColor=black&style=flat-square&logo=github)](https://github.com/dengxingzhi000/enterprise-agent/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-007396?logo=python&logoColor=white&style=flat-square)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-%3E%3D0.115-009688?logo=fastapi&logoColor=white&style=flat-square)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](#license)

**[Quick start](#quick-start) · [Capabilities](#capabilities) · [Architecture](#architecture) · [HITL](#human-in-the-loop) · [FAQ](#faq) · [Docs](#documentation)**

```bash
pip install -e . && uvicorn apps.api.main:app --port 8762
```

</div>

> [!IMPORTANT]
> **The three SCM write tools are placeholders.** `scm.purchase.create`,
> `scm.order.cancel`, and `scm.stock.adjust` are registered so the planner can
> name them, but each one returns a fixed `"need approval: … pending human
> review"` string. **None of them mutate anything.** They are never reached in
> practice because `guarded_executor` intercepts at
> `PolicyEngine.need_approval` first; they exist only to defend against a
> misconfigured policy. Everything else here talks to real HTTP or real local
> code.

> [!NOTE]
> **Self-built Runtime first, LangGraph later.** `loop` / `state` / `planner` /
> `executor` are all hand-written and driven by TDD, each layer independently
> testable. LangGraph rework is planned as a controlled comparison, not a
> starting dependency. Three target scenarios: **IT operations → contract
> compliance → data analysis**; `run_it_ops` is wired today.

---

The hard part of an LLM agent is not calling tools. It is recovering when a
multi-step task fails halfway, suspending and resuming when a human has to
approve something, and being able to reconstruct afterwards why each step was
taken. This project puts those three things in the Runtime itself rather than
leaving them to the business layer above.

`enterprise-agent` is an Agent Runtime written from zero: a hand-built
Planner/Executor loop, a Tool Registry that admits MCP / DB / RAG tools
through one interface, Policy with Human-in-the-Loop approval, Workflow
orchestration, and Eval plus Trace observability.

Every `SCM_*` external dependency degrades to a mock when unset, so **the full
test suite and the offline path run with no credentials at all** — not as a
compromise, but so 128 tests never depend on a service being up.

Current v0.4.1 covers SCM integration v2 and the closed HITL loop: **128
tests passed** (99 at the v0.4.0 baseline, 29 added in v0.4.1).

## Quick start

> [!NOTE]
> **Python 3.12 or newer.** CI runs the matrix on 3.12 and 3.13.

### Prerequisites

| Tool | Version | Required? |
|---|---|---|
| **Python** | 3.12+ | yes |
| **DeepSeek API key** | — | no — the planner falls back to `echo` and every tool returns mock data |
| **scm-platform** | running | no — without `SCM_GATEWAY_URL` the SCM tools mock themselves |

### Install and run

```bash
git clone https://github.com/dengxingzhi000/enterprise-agent.git
cd enterprise-agent

py -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -e .

copy .env.example .env          # Linux/macOS: cp .env.example .env
                                  # DEEPSEEK_API_KEY may be left empty

pytest -q                       # 128 passed
uvicorn apps.api.main:app --port 8762 --reload
```

Then open <http://localhost:8762/docs> and `POST /chat`.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness — returns `{"status": "ok", "stage": 1}` |
| `POST` | `/chat` | Runs one agent task; see the request and response below |
| `GET` | `/docs` | OpenAPI UI |

```bash
curl -X POST http://localhost:8762/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "订单 20260915001 为什么没发货?", "tenant_id": "t1", "user_id": "u1"}'
```

A completed run returns `reply`, `status`, `task_id`, `trace_id`, and — when the
agent had tokens — `token_usage` and `cost`. A run that hits an approval gate
returns `status: "paused"` plus `approval_id`, `approval_tool`, and
`approval_args`.

### Environment variables

Everything has a working default. `pip install -e .` alone is enough to run
the tests and the offline path.

| Variable | Default | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | empty | Model key; empty means the `echo` fallback planner |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Model id, also the pricing key for cost accounting |
| `SCM_GATEWAY_URL` | unset | **Unset ⇒ every `scm.*` tool uses its mock.** Set it and they become real REST calls |
| `SCM_AUTH_URL` | `http://localhost:8106` | scm-platform auth service |
| `SCM_USERNAME` / `SCM_PASSWORD` | empty | scm-platform credentials |
| `SCM_TENANT_MAP` | `{"t1":"tenant_001"}` | Maps the agent's `tenant_id` onto SCM's `tenant` param |
| `SCM_TIMEOUT_SECONDS` | `5` | Per-request timeout |
| `SCM_RETRY_BACKOFF_SECONDS` | `0.3` | Sleep before the single retry on 5xx / `ConnectError` / `Timeout` |
| `AGENT_PORT` | `8762` | Port the gateway expects |
| `POSTGRES_DSN` / `PG_DSN` | unset | Memory store; `PG_DSN` wins if both are set |
| `PG_OFFLINE` | unset | Force the memory store offline regardless of DSN |
| `CONTEXT_BUDGET_TOKENS` | `8000` | Assembler enforces total usage ≤ budget |
| `CONTEXT_RESERVED_TOKENS` | `1000` | Held back for the reply |
| `CONTEXT_COMPRESS_RATIO` | `0.8` | Compress once usage exceeds this fraction of available |
| `CONVERSATION_KEEP_RECENT` | `3` | Recent conversation turns kept verbatim |
| `OBSERVATION_KEEP_RECENT` | `5` | Recent observations kept verbatim |
| `MODEL_PRICING_INPUT` / `_OUTPUT` | `0.001` / `0.002` | Per-1k-token pricing for `AgentTask.cost` |
| `AGENT_STATUS_HISTORY` | `50` | Cap on the status-history ring buffer |

> [!WARNING]
> **`SCM_TENANT_MAP` fails open, not closed.** A malformed JSON, an empty dict,
> or an unknown tenant produces a warning and falls back to the default tenant
> rather than raising. That means **tenant isolation degrades silently.** In
> production, treat that warning as an error.

> [!NOTE]
> `langgraph`, `redis`, and `tiktoken` are deliberately **not** hard
> requirements. `workflow/checkpoint.py` warns and uses an in-memory checkpointer
> when `langgraph` is absent; token counting falls back to a heuristic without
> `tiktoken`. Offline CI has to stay green.

## Capabilities

| Icon | Area | What it gives you | Implementation and constraints |
|---|---|---|---|
| 🔁 | **Agent loop** | Hand-built Planner/Executor loop, not a framework wrapper | `agent/runtime`, each stage TDD'd independently |
| 🧰 | **Tool registry** | One dispatch path for MCP / DB / RAG tools | `agent/tools`; every write tool registered so the planner never hits `unknown tool` |
| 🛡️ | **Policy** | Read ⇒ allow, write ⇒ need approval, unknown ⇒ deny | `integrations/scm/policy_map.py`, default deny |
| ✋ | **Human-in-the-loop** | Task suspends on approval and resumes by id | `guarded_executor` → `paused` transition → `approval_id` in the response |
| 📉 | **Observability** | Every tool call and result traced via `contextvar` | `observability/`; `scm_call` / `scm_result` events |
| 🧠 | **Context & memory** | Budgeted assembly, compression, persistent memory | `agent/context`, `agent/memory`; degrades when PG is down |
| 📚 | **Retrieval** | RAG over the knowledge base | `knowledge/` |
| 🔀 | **Workflow** | Multi-step orchestration and checkpoints | `workflow/`, with a durable LangGraph path when installed |
| 📊 | **Evaluation** | Eval suites | `evaluation/` |
| 🔒 | **Security** | Separate policy and validation layer | `security/` |
| 🔁 | **Reliability** | One retry with configurable backoff on 5xx / `ConnectError` / `Timeout` | `SCM_RETRY_BACKOFF_SECONDS` |
| 💰 | **Cost** | Per-task token usage and cost accumulation | `AgentTask`, priced off `DEEPSEEK_MODEL` |

## Architecture

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
   │   │ budget+compress│                │ DeepSeek / echo  │ │  │
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
   │   metrics  logs.   git.  db.   knowledge  scm.* (4 read)
   │   .get     search   diff   query   .search     │
   │                                                 └── 3 write tools: placeholders
   └──────────────────────────────────────────────────────────┘
                               │
                               ▼
        workflow/ · evaluation/ · observability/ · infrastructure/pg
```

Three properties of that diagram are the point of the project:

**The loop is inspectable.** `run()` in `agent/runtime/loop.py` is 100 lines of
plain Python with no framework underneath. Every exit path — `finish_received`,
`executor_error`, `unknown_action`, `need_approval`, `max_iterations` — sets a
status, records tokens, emits a trace event, and returns. Nothing is hidden in
a framework callback.

**The HITL gate is a state transition, not an exception.** When
`guarded_executor` sees a write tool and `PolicyEngine.need_approval` fires, the
observation carries a `"need approval"` result. The loop recognises that prefix,
transitions to `paused`, and **breaks cleanly** — the task object stays valid
and `approval_id` is handed back. Resuming is a normal continuation, not a
recovery path.

**Mocks are the default, not the fallback.** `register_scm_tools` checks
`_use_mock()` — which is just "is `SCM_GATEWAY_URL` set". Unset means mock. That
is what makes 128 offline tests possible and CI hermetic.

### Project structure

```
enterprise-agent/
├── apps/
│   └── api/main.py          # FastAPI gateway: /health, /chat
├── agent/
│   ├── runtime/             # loop · planner · state · status · agent_task · counter
│   ├── tools/               # registry · executor (guarded) · builtin
│   ├── context/             # assembler, budget, compression
│   └── memory/              # persistent store
├── integrations/
│   └── scm/                 # client · auth · tools · policy_map
├── security/                # PolicyEngine · ApprovalStore
├── workflow/                # graph · durable · checkpoint · scenarios
├── knowledge/               # RAG retrieval
├── evaluation/              # eval suites
├── observability/           # Tracer and trace store
├── infrastructure/pg/       # connector, schema
├── tests/                   # 128 tests
└── docs/superpowers/        # specs/ (design) + plans/ (TDD plans)
```

### Stage progress

Each stage was advanced independently under TDD:

scaffolding → Runtime → Tool/MCP → RAG → Memory → Policy/HITL → Workflow →
Eval/Observability → LangGraph rework

## Human-in-the-loop

The approval loop is the feature most agent frameworks leave to the caller, so
it is worth stating exactly what happens.

```
   POST /chat ──▶ planner wants a write tool
                     │
                     ▼
        PolicyEngine.need_approval(tool, user)
                     │
        ┌────────────┴────────────┐
        │ allow                   │ need_approval
        ▼                         ▼
   tool runs              guarded_executor returns
                           observation "need approval: …"
                                │
                                ▼
                    loop sees the prefix, breaks
                                │
                                ▼
              status=paused, transition recorded,
              approval_id + approval_tool + approval_args
                        in the /chat response
                                │
                                ▼
             caller resolves the approval, then
             resumes with the same task_id
```

`scm_policy_decision` is the whole policy in five lines: read tools are
`allow`, write tools are `need_approval`, **anything unregistered is `deny`**.
The default is closed.

## FAQ

<details>
<summary><strong>Will it run without a DeepSeek API key?</strong></summary>

Yes. The planner falls back to `echo` and every `SCM_*` tool returns mock data.
That is exactly why the 128 tests depend on no external service, and `pytest -q`
should be fully green offline.

</details>

<details>
<summary><strong>Why not just use LangGraph or LangChain?</strong></summary>

The route is self-built Runtime first. `loop` / `state` / `planner` /
`executor` are hand-written under TDD so each layer's behaviour is testable
and explainable on its own. LangGraph is planned as a rework for a controlled
comparison rather than a dependency taken on at the start — which is why
`workflow/graph_lang.py` and `workflow/durable.py` exist alongside the
hand-rolled path, and why `langgraph` stays an optional dependency.

</details>

<details>
<summary><strong>What does the SCM integration actually do?</strong></summary>

Four read tools talk to [scm-platform](https://github.com/dengxingzhi000/scm-platform)
over REST, with tenant mapping and one retry on 5xx / `ConnectError` /
`Timeout`:

| Tool | Calls | Purpose |
|---|---|---|
| `scm.order.get` | `GET /api/orders/{order_no}` | Order 5xx triage |
| `scm.inventory.query` | `GET /api/inventory` | Stock lookup |
| `scm.sales.report` | `GET /api/analytics/sales` | Sales aggregation |
| `scm.supplier.get` | `GET /api/suppliers/{id}` | Supplier risk |

The three write tools — `scm.purchase.create`, `scm.order.cancel`,
`scm.stock.adjust` — are **placeholders**, as flagged at the top of this file.
Registering them is deliberate: without them the planner can emit a tool name
the registry has never heard of and the executor raises `unknown tool` before
the policy layer ever gets to approve it.

</details>

<details>
<summary><strong>Is HITL actually wired end to end?</strong></summary>

The suspend-and-resume path is: `/chat` returns `status: "paused"` with an
`approval_id`, and the trace records the transition. `workflow/durable.py` and
`tests/test_durable_langgraph.py` cover the durable checkpoint path.

What is **not** implemented is a resume endpoint. `apps/api/main.py` accepts a
`task_id` on the request, but there is no `/approvals/{id}` route that resolves
an approval and drives the task to completion. Today a paused task is a
suspended object, not a round trip.

</details>

<details>
<summary><strong>How does context get kept inside a token budget?</strong></summary>

`ContextAssembler` enforces `CONTEXT_BUDGET_TOKENS` minus
`CONTEXT_RESERVED_TOKENS`. Past `CONTEXT_COMPRESS_RATIO` of the available
budget it triggers compression, keeping the most recent
`CONVERSATION_KEEP_RECENT` turns and `OBSERVATION_KEEP_RECENT` observations
verbatim and summarising the rest. The resulting report is stored on
`context_report` and emitted as a `context_assemble` trace event, so you can see
what the model was actually given.

Token counting needs `tiktoken`; without it the runtime falls back to a
heuristic estimate rather than failing.

</details>

<details>
<summary><strong>What happens when PostgreSQL is down?</strong></summary>

The memory store degrades silently and warns — `tests/test_memory_pg.py`
covers this explicitly (`test_memory_store_outage_degrades_silently`). An
unavailable memory layer should not take down an agent task.

Set `PG_OFFLINE=1` to skip it deliberately. Be aware that "silently" is doing
real work in that sentence: a persistent-memory outage looks like a working
agent that has forgotten everything.

</details>

## Documentation

| Document | Contents |
|---|---|
| [Design specs](./docs/superpowers/specs/) | One design document per feature |
| [Implementation plans](./docs/superpowers/plans/) | One TDD plan per stage, checkbox form |
| [Security model](./SECURITY.md) | Threat model and the private reporting channel |
| [Changelog](./CHANGELOG.md) | What changed in each release |
| [Contributing](./CONTRIBUTING.md) | Branch conventions and what CI checks |

Security reports go through [SECURITY.md](./SECURITY.md) — not the issue
tracker.

## Star history

<a href="https://www.star-history.com/?repos=dengxingzhi000%2Fenterprise-agent&amp;type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dengxingzhi000/enterprise-agent&amp;type=date&amp;theme=dark&amp;legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dengxingzhi000/enterprise-agent&amp;type=date" />
    <img alt="Enterprise AI Operations Agent GitHub star history" src="https://api.star-history.com/chart?repos=dengxingzhi000/enterprise-agent&amp;type=date" />
  </picture>
</a>

## Related projects

- **[scm-platform](https://github.com/dengxingzhi000/scm-platform)** — the Java microservices supply-chain platform (Spring Boot 4 + Spring Cloud 2025) this agent operates on: order 5xx triage, expense-compliance review, and sales analysis all target it.

## Contributing

Read [CONTRIBUTING.md](./CONTRIBUTING.md) first — it covers the branch
conventions and exactly what CI checks.

1. Fork the repository
2. Create a branch (`git checkout -b feat/…`)
3. `pytest -q` before pushing — CI runs it on Python 3.12 and 3.13
4. Open a pull request using the template

Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
Participation is governed by the [Code of Conduct](./CODE_OF_CONDUCT.md).

## License

[Apache License 2.0](./LICENSE)

---

<div align="center">

**Built with ❤️ by [dengxingzhi](https://github.com/dengxingzhi000)**

</div>
