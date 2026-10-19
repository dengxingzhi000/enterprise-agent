# Contributing to Enterprise AI Operations Agent

Thanks for taking the time. This document covers the branch conventions, the
test expectations, and what CI will check.

## The design constraint that shapes everything

**The Runtime must stay inspectable.** This project deliberately does not sit
on LangGraph or LangChain — `loop` / `state` / `planner` / `executor` are
hand-written so each layer can be tested and explained on its own. A
contribution that hides control flow inside a framework callback works against
the point of the project. If you do need a capability a framework provides, the
plan is to build it and compare, not to depend on it up front.

Two things follow from that, and both are enforced by review:

- **Every exit path of the loop must be observable.** Each terminal state —
  `finish_received`, `executor_error`, `unknown_action`, `need_approval`,
  `max_iterations` — sets a status, records tokens, emits a trace event, and
  returns. Do not add an early `return` that skips any of those.
- **Optional dependencies stay optional.** `langgraph`, `redis`, and
  `tiktoken` are not in `pyproject.toml`'s hard requirements, and the reason is
  in the file itself: offline CI has to stay green. A missing optional
  dependency degrades with a warning; it never fails a test run.

## Prerequisites

| Tool | Version |
|---|---|
| **Python** | 3.12+ — CI runs the matrix on 3.12 and 3.13 |

Nothing else is required. `pip install -e .` is enough to run the whole test
suite.

## The check CI runs

Run this before every push. It is exactly what `.github/workflows/ci.yml`
executes.

```bash
pip install -e .
pytest -q
```

To match the matrix, run it on both interpreters:

```bash
py -3.12 -m venv .venv312 && .venv312\Scripts\activate && pip install -e . && pytest -q
py -3.13 -m venv .venv313 && .venv313\Scripts\activate && pip install -e . && pytest -q
```

The suite must be **128 passing, offline, with no credentials**. If a test you
added needs a DeepSeek key, an scm-platform instance, or a database, it is
written wrong — the mock path is the default precisely so that this stays
possible.

## Things that look like improvements but are not

**Do not make `SCM_*` required.** `_use_mock()` returns true when
`SCM_GATEWAY_URL` is unset. That single line is what lets the suite run with no
external service. Treating it as a bug to fix would break 128 tests.

**Do not remove the placeholder write tools.** `scm.purchase.create`,
`scm.order.cancel`, and `scm.stock.adjust` return a fixed `"need approval"`
string and mutate nothing. That is intentional. Without them registered, the
planner can emit a tool name the registry has never heard of, and the executor
raises `unknown tool` before the policy layer ever gets a chance to approve it.
They are a guard against a policy misconfiguration, not an unfinished feature
to delete.

**Do not make the `tenant_map` fallback strict without a discussion.** Bad JSON,
an empty dict, or an unknown tenant currently warns and falls back to the
default tenant. That is a silent tenant-isolation degradation, and it is
documented as such — but turning it into a hard failure changes the failure
mode of the whole agent, so raise it before changing it.

## Working on the HITL path

The suspend path is implemented: `/chat` returns `status: "paused"` with an
`approval_id`, and the trace records the transition. The resume endpoint is
**not** — `/approval/{aid}/decide` and `/chat/{task_id}/resume` are v3
candidates listed in [CHANGELOG.md](./CHANGELOG.md).

If you build either, the test that matters is an integration test that starts
from the public `/chat` route and runs to completion. v0.4.1 shipped a blocking
defect precisely because the unit tests mocked around the real wiring and the
production path silently never reached `guarded_executor`.

## Branch and commit conventions

```
main            integration branch
feat/…          new capability
fix/…           bug fixes
docs/…          documentation only
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/), as
the existing history does:

```
feat(scm): add supplier risk lookup to review_contract
fix(loop): record tokens on the max_iterations path
docs(readme): explain why write tools are placeholders
```

## Adding a dependency

Do not add a new hard requirement to `pyproject.toml` without a test proving
the suite still passes with it absent. If the capability is genuinely optional,
comment it in the dependency block the way `langgraph` and `tiktoken` are, and
make the runtime degrade with a warning.

Security-sensitive additions should be discussed in an issue first — see
[SECURITY.md](./SECURITY.md).

## Reporting bugs

Use the [bug report template](./.github/ISSUE_TEMPLATE/bug_report.yml). An
agent bug report needs the `task_id` and `trace_id` from the `/chat` response
and the relevant trace events; those are what make a multi-step failure
reconstructable.

Participation is governed by the [Code of Conduct](./CODE_OF_CONDUCT.md).
