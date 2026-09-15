# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest (`main` / latest release) | ✅ Security updates applied |
| Older releases | ❌ No longer supported |

## Reporting a Vulnerability

**Do NOT report security vulnerabilities through public GitHub issues.**

Use [GitHub Private Vulnerability Reporting](../../security/advisories/new)
(Security tab → Advisories → Report a vulnerability).

### What to Include

1. **Type** (e.g., prompt injection → tool abuse, cross-tenant data leak, auth bypass, hardcoded key)
2. **Affected component** (e.g., `agent/runtime`, `agent/tools`, `security/policy`, `apps/api`)
3. **Steps to reproduce** — minimal PoC
4. **Potential impact** — what an attacker could achieve
5. **Affected version** — commit hash or release tag

### Response Timeline

| Phase | Timeline |
|-------|----------|
| **Acknowledgment** | Within 48 hours |
| **Triage** | Within 7 days |
| **Fix + release** | Coordinated disclosure |

## Agent-Specific Notes

This project is an AI agent with tool access. Particularly relevant:

- **Prompt injection → unauthorized tool calls** (the Planner must only emit
  `finish`/`call_tool` JSON; `guarded_executor` + `PolicyEngine` are the enforcement points)
- **Cross-tenant leakage** in `knowledge/store.py` and `security/policy.py`
  (tenant/permission filtering must never be bypassed)
- **Secret leakage**: `DEEPSEEK_API_KEY` lives only in local `.env` (git-ignored);
  never commit keys or traces containing them

Out of scope: model hallucinations without a concrete exploit path,
DoS/resource exhaustion, third-party service vulnerabilities.

## Acknowledgments

*No vulnerabilities reported yet.*
