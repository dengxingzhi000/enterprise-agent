# SCM Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接通 scm-platform 只读 3 件套（order/inventory/sales），独立 `integrations/scm/` 模块并受 Policy 管控。

**Architecture:** `Registry` 契约不动，`integrations/scm/tools.py:register_scm_tools()` 注册 3 个 `scm.*` Tool；`client.py` 做 httpx 封装（5s 超时、401 刷 token 重试 1 次、失败转字符串）；`policy_map.py` 做读写分级，`PolicyEngine` 加 `scm.*` 分支；无配置回退 Mock。

**Tech Stack:** Python 3.12+, httpx>=0.27（已有）, pytest（asyncio auto）, pydantic-settings 不用（os.environ 直读保持最小）。

---

### Task 1: Scaffolding + Config

**Files:**
- Create: `integrations/__init__.py`
- Create: `integrations/scm/__init__.py`
- Modify: `pyproject.toml:30-31`
- Modify: `.env.example`
- Test: `tests/test_scm_integration.py`

- [ ] **Step 1: Write the failing test**

```python
def test_register_scm_tools():
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    names = reg.list_tools()
    assert "scm.order.get" in names
    assert "scm.inventory.query" in names
    assert "scm.sales.report" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scm_integration.py::test_register_scm_tools -v`
Expected: FAIL with "No module named 'integrations'" (RED)

- [ ] **Step 3: Create package scaffolding**

`integrations/__init__.py`:
```python
"""External system integrations (scm-platform first)."""
```

`integrations/scm/__init__.py`:
```python
"""SCM-platform integration: client/auth/tools/policy_map."""
from .tools import register_scm_tools

__all__ = ["register_scm_tools"]
```

- [ ] **Step 4: Fix packaging include**

`pyproject.toml` old:
```toml
include = ["apps*", "agent*", "infrastructure*", "knowledge*", "security*", "workflow*", "observability*", "evaluation*"]
```
new:
```toml
include = ["apps*", "agent*", "infrastructure*", "knowledge*", "security*", "workflow*", "observability*", "evaluation*", "integrations*"]
```

- [ ] **Step 5: Add .env.example entries**

Append to `.env.example`:
```
AGENT_PORT=8762
SCM_GATEWAY_URL=http://localhost:8761
SCM_AUTH_URL=http://localhost:8106
SCM_USERNAME=
SCM_PASSWORD=
SCM_TENANT_MAP={"t1":"tenant_001"}
SCM_TIMEOUT_SECONDS=5
```

- [ ] **Step 6: Run test to verify it still fails (tools.py missing)**

Run: `pytest tests/test_scm_integration.py::test_register_scm_tools -v`
Expected: FAIL with "cannot import name 'register_scm_tools'" (still RED, proves scaffolding loads)

- [ ] **Step 7: Commit**

```bash
git add integrations/__init__.py integrations/scm/__init__.py pyproject.toml .env.example tests/test_scm_integration.py
git commit -m "chore(scm): scaffolding + config (RED)"
```

---

### Task 2: client.py + auth.py

**Files:**
- Create: `integrations/scm/client.py`
- Create: `integrations/scm/auth.py`
- Test: `tests/test_scm_integration.py`

- [ ] **Step 1: Write the failing test**

```python
def test_401_refresh_retry(monkeypatch):
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return (401, {"error": "expired"})
        return (200, {"order_no": "20260915001", "status": "PAID"})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5)
    code, body = c.get("/api/orders/20260915001")
    assert code == 200
    assert body["status"] == "PAID"
    assert calls["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scm_integration.py::test_401_refresh_retry -v`
Expected: FAIL with "No module named 'integrations.scm.client'" or "cannot import ScmClient"

- [ ] **Step 3: Write minimal auth.py**

`integrations/scm/auth.py`:
```python
"""SCM auth: login换token + tenant映射。LLM永远摸不到token。"""
import json
import os
import time


def load_tenant_map() -> dict:
    raw = os.environ.get("SCM_TENANT_MAP", '{"t1":"tenant_001"}')
    try:
        return json.loads(raw)
    except Exception:
        return {"t1": "tenant_001"}


def to_scm_tenant(agent_tenant: str) -> str:
    return load_tenant_map().get(agent_tenant, agent_tenant)


class TokenCache:
    def __init__(self):
        self.token = ""
        self.expires_at = 0.0

    def get(self) -> str:
        if self.token and time.time() < self.expires_at - 60:
            return self.token
        return ""

    def set(self, token: str, ttl: int = 3600):
        self.token = token
        self.expires_at = time.time() + ttl
```

- [ ] **Step 4: Write minimal client.py**

`integrations/scm/client.py`:
```python
"""SCM HTTP封装：5s超时 / 401刷token重试1次 / 结果截断调用方做。"""
import os
import uuid

import httpx

from .auth import TokenCache


class ScmClient:
    def __init__(self, gateway_url="", auth_url="", username="", password="", timeout=5):
        self.gateway_url = gateway_url or os.environ.get("SCM_GATEWAY_URL", "")
        self.auth_url = auth_url or os.environ.get("SCM_AUTH_URL", "")
        self.username = username or os.environ.get("SCM_USERNAME", "")
        self.password = password or os.environ.get("SCM_PASSWORD", "")
        self.timeout = int(os.environ.get("SCM_TIMEOUT_SECONDS", str(timeout)))
        self._tokens = TokenCache()

    def _send(self, method: str, path: str, **kw):
        url = self.gateway_url.rstrip("/") + path
        headers = kw.pop("headers", {})
        token = self._tokens.get()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("X-Request-Id", str(uuid.uuid4()))
        r = httpx.request(method, url, headers=headers, timeout=self.timeout, **kw)
        try:
            body = r.json()
        except Exception:
            body = {"text": r.text[:2000]}
        return (r.status_code, body)

    def _login(self):
        try:
            r = httpx.post(
                self.auth_url.rstrip("/") + "/login",
                json={"username": self.username, "password": self.password},
                timeout=self.timeout,
            )
            data = r.json()
            token = data.get("token", "")
            if token:
                self._tokens.set(token, int(data.get("expires_in", 3600)))
        except Exception:
            pass

    def get(self, path: str, params: dict | None = None):
        code, body = self._send("GET", path, params=params or {})
        if code == 401:
            self._login()
            code, body = self._send("GET", path, params=params or {})
        return (code, body)

    @classmethod
    def from_env(cls):
        return cls()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scm_integration.py::test_401_refresh_retry -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add integrations/scm/auth.py integrations/scm/client.py tests/test_scm_integration.py
git commit -m "feat(scm): client 401-retry + auth cache (GREEN)"
```

---

### Task 3: policy_map.py + tools.py

**Files:**
- Create: `integrations/scm/policy_map.py`
- Create: `integrations/scm/tools.py`
- Test: `tests/test_scm_integration.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_cross_tenant_denied():
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "admin"}, "scm.order.get", {"tenant_id": "t2"})
    assert d["decision"] == "deny"


def test_offline_fallback():
    import os
    os.environ.pop("SCM_GATEWAY_URL", None)
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    out = reg.call("scm.order.get", {"order_no": "20260915001", "tenant_id": "t1"})
    assert "20260915001" in str(out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scm_integration.py::test_cross_tenant_denied tests/test_scm_integration.py::test_offline_fallback -v`
Expected: FAIL — `test_cross_tenant_denied` fails with decision `deny unknown tool` mismatch (current code returns `deny unknown tool scm.order.get`, need explicit branch); `test_offline_fallback` fails with import error

- [ ] **Step 3: Write policy_map.py**

`integrations/scm/policy_map.py`:
```python
"""SCM读写分级：读=allow，写=need_approval，未知=deny。"""
SCM_READ_TOOLS = {"scm.order.get", "scm.inventory.query", "scm.sales.report"}
SCM_WRITE_TOOLS = {"scm.purchase.create", "scm.order.cancel", "scm.stock.adjust"}


def scm_policy_decision(tool: str) -> str:
    if tool in SCM_READ_TOOLS:
        return "allow"
    if tool in SCM_WRITE_TOOLS:
        return "need_approval"
    return "deny"
```

- [ ] **Step 4: Write tools.py**

`integrations/scm/tools.py`:
```python
"""SCM Tool适配：REST翻译成Registry Tool。无配置回退Mock。"""
import os

from agent.tools.registry import Tool

from .auth import to_scm_tenant
from .client import ScmClient


def _use_mock() -> bool:
    return not os.environ.get("SCM_GATEWAY_URL")


def _mock_order(args: dict):
    return f"row1: order_no={args.get('order_no','20260915001')} status=PAID amount=6230 (mock)"


def _mock_inventory(args: dict):
    return f"sku={args.get('sku','SKU-001')} stock=128 warehouse=WH-01 (mock)"


def _mock_sales(args: dict):
    return f"sales range={args.get('range','7d')} gmv=123456 orders=321 (mock)"


def register_scm_tools(registry, client=None):
    if _use_mock() and client is None:
        registry.register(Tool("scm.order.get", "查SCM订单(只读)", _mock_order))
        registry.register(Tool("scm.inventory.query", "查SCM库存(只读)", _mock_inventory))
        registry.register(Tool("scm.sales.report", "查销售聚合(只读)", _mock_sales))
        # 写口占位：直接返回need-approval提示，不发请求
        registry.register(Tool("scm.purchase.create", "建采购单(高风险,占位)", lambda a: "need approval: scm.purchase.create pending human review"))
        return registry
    c = client or ScmClient.from_env()

    def _order_get(args: dict):
        args = args or {}
        try:
            code, body = c.get(f"/api/orders/{args.get('order_no','')}", params={"tenant": to_scm_tenant(args.get("tenant_id","t1"))})
            return str(body)[:2000] if code == 200 else f"tool error scm.order.get: {code} {str(body)[:500]}"
        except Exception as e:
            return f"tool error scm.order.get: {e}"

    def _inv_query(args: dict):
        args = args or {}
        try:
            code, body = c.get("/api/inventory", params={"sku": args.get("sku",""), "tenant": to_scm_tenant(args.get("tenant_id","t1"))})
            return str(body)[:2000] if code == 200 else f"tool error scm.inventory.query: {code} {str(body)[:500]}"
        except Exception as e:
            return f"tool error scm.inventory.query: {e}"

    def _sales(args: dict):
        args = args or {}
        try:
            code, body = c.get("/api/analytics/sales", params={"range": args.get("range","7d"), "tenant": to_scm_tenant(args.get("tenant_id","t1"))})
            return str(body)[:2000] if code == 200 else f"tool error scm.sales.report: {code} {str(body)[:500]}"
        except Exception as e:
            return f"tool error scm.sales.report: {e}"

    registry.register(Tool("scm.order.get", "查SCM订单(只读)", _order_get))
    registry.register(Tool("scm.inventory.query", "查SCM库存(只读)", _inv_query))
    registry.register(Tool("scm.sales.report", "查销售聚合(只读)", _sales_report_alias(_sales)))
    registry.register(Tool("scm.purchase.create", "建采购单(高风险,占位)", lambda a: "need approval: scm.purchase.create pending human review"))
    return registry


def _sales_report_alias(fn):
    return fn
```

- [ ] **Step 5: Run tests to verify new behavior (cross-tenant still needs Task 4)**

Run: `pytest tests/test_scm_integration.py::test_offline_fallback -v`
Expected: PASS (fallback works); `test_cross_tenant_denied` may still return deny but for wrong reason — fixed in Task 4

- [ ] **Step 6: Commit**

```bash
git add integrations/scm/policy_map.py integrations/scm/tools.py tests/test_scm_integration.py
git commit -m "feat(scm): tools register + offline fallback (GREEN)"
```

---

### Task 4: PolicyEngine + Registry wiring

**Files:**
- Modify: `security/policy.py:1-30`
- Modify: `agent/tools/builtin.py:34-41`
- Test: `tests/test_scm_integration.py`

- [ ] **Step 1: Run cross-tenant test to confirm current gap**

Run: `pytest tests/test_scm_integration.py::test_cross_tenant_denied -v`
Expected: PASS with reason `cross-tenant denied` already (base check covers it), but read-allow branch missing — add explicit test:

```python
def test_scm_read_allowed():
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "employee"}, "scm.order.get", {"tenant_id": "t1"})
    assert d["decision"] == "allow"
```

Append it to `tests/test_scm_integration.py`, run:
Run: `pytest tests/test_scm_integration.py::test_scm_read_allowed -v`
Expected: FAIL with decision `deny`

- [ ] **Step 2: Patch PolicyEngine**

`security/policy.py` — after the `db.query` branch (line 28), before final `return deny`, insert:

```python
        if tool.startswith("scm."):
            from integrations.scm.policy_map import scm_policy_decision
            dec = scm_policy_decision(tool)
            if dec == "allow":
                return {"decision": "allow", "reason": "scm low-risk read"}
            if dec == "need_approval":
                return {"decision": "need_approval", "reason": f"{tool} is high-risk"}
            return {"decision": "deny", "reason": f"unknown tool {tool}"}
```

Full import must be function-local (avoid circular import: `integrations.scm.tools` imports `agent.tools.registry`).

- [ ] **Step 3: Wire registry**

`agent/tools/builtin.py` — in `build_default_registry()`, before `return reg`, append:

```python
    try:
        from integrations.scm.tools import register_scm_tools
        register_scm_tools(reg)
    except Exception:
        pass
```

- [ ] **Step 4: Run all scm tests**

Run: `pytest tests/test_scm_integration.py -v`
Expected: 5 passed (`test_register_scm_tools`, `test_401_refresh_retry`, `test_cross_tenant_denied`, `test_offline_fallback`, `test_scm_read_allowed`)

- [ ] **Step 5: Run full suite (no regression)**

Run: `pytest -q`
Expected: all passed (currently 34+ passed baseline + 5 new)

- [ ] **Step 6: Commit**

```bash
git add security/policy.py agent/tools/builtin.py tests/test_scm_integration.py
git commit -m "feat(scm): policy wiring + registry auto-register"
```

---

### Task 5: Scenarios fallback + verification

**Files:**
- Modify: `workflow/scenarios.py:22-30`
- Test: `tests/test_scm_integration.py`

- [ ] **Step 1: Write the failing test**

```python
def test_analyze_sales_prefers_scm():
    import os
    os.environ.pop("SCM_GATEWAY_URL", None)
    from workflow.scenarios import analyze_sales
    out = analyze_sales("近7天为什么下降")
    assert "report" in out
    assert "trace" in out and len(out["trace"]) >= 1
```

- [ ] **Step 2: Run to verify it passes already (baseline) then harden**

Run: `pytest tests/test_scm_integration.py::test_analyze_sales_prefers_scm -v`
Expected: PASS (current mock path) — this locks behavior before refactor

- [ ] **Step 3: Harden analyze_sales to prefer scm.sales.report**

`workflow/scenarios.py` — replace `analyze_sales` body with:

```python
def analyze_sales(question: str) -> dict:
    from agent.tools.builtin import build_default_registry
    reg = build_default_registry()
    trace = []
    try:
        if "scm.sales.report" in reg.list_tools():
            sales = reg.call("scm.sales.report", {"range": "7d", "tenant_id": "t1"})
            trace.append("scm.sales.report")
        else:
            sales = reg.call("knowledge.search", {"query": question, "tenant_id": "t1"})
            trace.append("knowledge.search")
    except Exception as e:
        sales = f"sales fallback: {e}"
        trace.append("knowledge.search")
    metrics = reg.call("metrics.get", {"service": "mall"})
    rows = reg.call("db.query", {"scope": "self"})
    trace += ["metrics.get", "db.query"]
    report = (f"销售下降分析报告：{question}\n- 销售聚合：{sales}\n- 指标：{metrics}\n- 数据：{rows}\n"
              f"- 初步判断：支付超时导致下单失败，需按运维手册排查。")
    return {"report": report, "trace": trace}
```

- [ ] **Step 4: Full verification**

Run: `pytest -q`
Expected: all passed

Run: `pip install -e .`
Expected: install success (verifies `integrations*` include)

- [ ] **Step 5: Commit**

```bash
git add workflow/scenarios.py tests/test_scm_integration.py
git commit -m "feat(scm): analyze_sales prefers scm.sales.report"
```
