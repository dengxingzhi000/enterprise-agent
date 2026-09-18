# SCM Integration v2 — Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 v1 缺口 #1（写口全注册）、#3（5xx/ConnectError 重试）、#8（tenant_map 启动校验）；不动 Policy/executor/Runtime。

**Architecture:** TDD 顺序：写口占位 → 重试 → 配置校验。每任务独立 RED→GREEN→commit。Phase 1 完成时 `pytest -q` 应 104 passed（v1 99 + Phase 1 新增 5）。

**Tech Stack:** Python 3.12+, httpx>=0.27（已有）, pytest-asyncio auto。

**Base branch:** `feat/scm-integration`（v1 提交流）；新分支 `feat/scm-integration-v2-foundation` 基于此。

---

### Task 1: 写口完整注册 (#1)

**Files:**
- Modify: `integrations/scm/tools.py:30-33, 60-64`
- Test: `tests/test_scm_integration_v2.py`（新建）

- [ ] **Step 1: 切分支**

```bash
cd D:\ProgramProject\enterprise-agent
git checkout feat/scm-integration
git pull origin feat/scm-integration
git checkout -b feat/scm-integration-v2-foundation
```

- [ ] **Step 2: 写 failing test**

`tests/test_scm_integration_v2.py`:
```python
"""SCM integration v2: Phase 1 (Foundation) + Phase 2 + Phase 3 tests."""
import os

import pytest


def test_write_tools_all_registered():
    """Phase 1 #1: scm.order.cancel + scm.stock.adjust 也要在 registry 里。"""
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    names = set(reg.list_tools())
    assert "scm.purchase.create" in names
    assert "scm.order.cancel" in names
    assert "scm.stock.adjust" in names


def test_write_tools_all_classified_need_approval():
    """Phase 1 #1 联动：所有写口经 PolicyEngine 走 need_approval。"""
    from security.policy import PolicyEngine
    p = PolicyEngine()
    for tool in ("scm.purchase.create", "scm.order.cancel", "scm.stock.adjust"):
        d = p.check({"tenant_id": "t1", "role": "admin"}, tool, {"tenant_id": "t1"})
        assert d["decision"] == "need_approval", f"{tool}: {d}"


def test_unknown_scm_tool_denied():
    """Phase 1 #1 联动：未知 scm.* 必须 deny（防御 typo）。"""
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "admin"}, "scm.order.destroy", {"tenant_id": "t1"})
    assert d["decision"] == "deny"
```

- [ ] **Step 3: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py -v`
Expected: 第一个测试 FAIL with `assert "scm.order.cancel" in names`；`test_unknown_scm_tool_denied` PASS（policy_map.py 已有 deny 分支），`test_write_tools_all_classified_need_approval` PASS（policy_map 已声明）。

- [ ] **Step 4: 改 tools.py 注册两个写口**

`integrations/scm/tools.py` 修改两处：

mock 分支（约 27-33 行）改为：
```python
    if _use_mock() and client is None:
        registry.register(Tool("scm.order.get", "查SCM订单(只读)", _mock_order))
        registry.register(Tool("scm.inventory.query", "查SCM库存(只读)", _mock_inventory))
        registry.register(Tool("scm.sales.report", "查销售聚合(只读)", _mock_sales))
        # 写口占位：返回need-approval字符串。实际不会被调用，因为 guarded_executor
        # 在 PolicyEngine.need_approval 时已拦截；保留仅为防御 Policy 配置失误。
        registry.register(Tool("scm.purchase.create", "建采购单(占位, 走HITL)",
                               lambda a: "need approval: scm.purchase.create pending human review"))
        registry.register(Tool("scm.order.cancel", "取消SCM订单(占位, 走HITL)",
                               lambda a: "need approval: scm.order.cancel pending human review"))
        registry.register(Tool("scm.stock.adjust", "调整SCM库存(占位, 走HITL)",
                               lambda a: "need approval: scm.stock.adjust pending human review"))
        return registry
```

真实分支（约 60-64 行）改为：
```python
    registry.register(Tool("scm.order.get", "查SCM订单(只读)", _order_get))
    registry.register(Tool("scm.inventory.query", "查SCM库存(只读)", _inv_query))
    registry.register(Tool("scm.sales.report", "查销售聚合(只读)", _sales_report_alias(_sales)))
    registry.register(Tool("scm.purchase.create", "建采购单(占位, 走HITL)",
                           lambda a: "need approval: scm.purchase.create pending human review"))
    registry.register(Tool("scm.order.cancel", "取消SCM订单(占位, 走HITL)",
                           lambda a: "need approval: scm.order.cancel pending human review"))
    registry.register(Tool("scm.stock.adjust", "调整SCM库存(占位, 走HITL)",
                           lambda a: "need approval: scm.stock.adjust pending human review"))
    return registry
```

- [ ] **Step 5: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_write_tools_all_registered tests/test_scm_integration_v2.py::test_write_tools_all_classified_need_approval tests/test_scm_integration_v2.py::test_unknown_scm_tool_denied -v`
Expected: 3 passed。

- [ ] **Step 6: 跑全套确认无回归**

Run: `pytest -q`
Expected: 102 passed（v1 的 99 + 新增 3 = 102）。

- [ ] **Step 7: 提交**

```bash
git add integrations/scm/tools.py tests/test_scm_integration_v2.py
git commit -m "feat(scm): register all 3 write-tool placeholders

scm.order.cancel and scm.stock.adjust were declared in policy_map
but never registered in the Registry; Planner could call them,
Policy.need_approval would fire, but registry.call would raise
unknown tool. Now all 3 write tools are registered with the same
placeholder lambda. guarded_executor still intercepts before the
lambda runs."
```

---

### Task 2: 5xx + ConnectError 重试 (#3)

**Files:**
- Modify: `integrations/scm/client.py:212-217`（`get()` 方法）
- Modify: `.env.example`（追加 `SCM_RETRY_BACKOFF_SECONDS`）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 写 failing tests**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_5xx_retry(monkeypatch):
    """Phase 1 #3: 503 必须重试 1 次。"""
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        import httpx
        if calls["n"] == 1:
            req = httpx.Request(method, "http://x" + path)
            resp = httpx.Response(503, request=req)
            raise httpx.HTTPStatusError("503", request=req, response=resp)
        return (200, {"ok": True})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5)
    code, body = c.get("/api/x")
    assert code == 200
    assert body == {"ok": True}
    assert calls["n"] == 2


def test_connect_error_retry(monkeypatch):
    """Phase 1 #3: ConnectError 必须重试 1 次。"""
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        import httpx
        if calls["n"] == 1:
            raise httpx.ConnectError("conn refused")
        return (200, {"ok": True})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5)
    code, body = c.get("/api/x")
    assert code == 200
    assert calls["n"] == 2


def test_no_retry_on_4xx(monkeypatch):
    """Phase 1 #3: 4xx 不重试。"""
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        return (404, {"error": "not found"})
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5)
    code, body = c.get("/api/x")
    assert code == 404
    assert calls["n"] == 1


def test_5xx_give_up_after_retry(monkeypatch):
    """Phase 1 #3: 重试仍 5xx → 返回 code=0 + error body，不抛。"""
    from integrations.scm.client import ScmClient
    calls = {"n": 0}
    def fake_send(self, method, path, **kw):
        calls["n"] += 1
        import httpx
        req = httpx.Request(method, "http://x" + path)
        resp = httpx.Response(503, request=req)
        raise httpx.HTTPStatusError("503", request=req, response=resp)
    monkeypatch.setattr(ScmClient, "_send", fake_send)
    c = ScmClient(gateway_url="http://x", auth_url="http://a", username="u", password="p", timeout=5,
                  backoff_seconds=0)
    code, body = c.get("/api/x")
    assert code == 0
    assert "error" in body
    assert calls["n"] == 2
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_5xx_retry tests/test_scm_integration_v2.py::test_connect_error_retry tests/test_scm_integration_v2.py::test_no_retry_on_4xx tests/test_scm_integration_v2.py::test_5xx_give_up_after_retry -v`
Expected: 全部 FAIL（`test_no_retry_on_4xx` PASS 因为现状就是 4xx 不重试，但 `test_5xx_give_up_after_retry` 会因 `backoff_seconds` kwarg 不存在而 TypeError）。

- [ ] **Step 3: 改 client.py 加 retry + backoff 参数**

`integrations/scm/client.py` 顶部 import 加 `import time as _time` 和 `import os`。

`__init__` 改为：
```python
    def __init__(self, gateway_url="", auth_url="", username="", password="", timeout=5, backoff_seconds=None):
        self.gateway_url = gateway_url or os.environ.get("SCM_GATEWAY_URL", "")
        self.auth_url = auth_url or os.environ.get("SCM_AUTH_URL", "")
        self.username = username or os.environ.get("SCM_USERNAME", "")
        self.password = password or os.environ.get("SCM_PASSWORD", "")
        self.timeout = int(os.environ.get("SCM_TIMEOUT_SECONDS", str(timeout)))
        self.backoff_seconds = backoff_seconds if backoff_seconds is not None else float(
            os.environ.get("SCM_RETRY_BACKOFF_SECONDS", "0.3"))
        self._tokens = TokenCache()
```

`get` 方法（约 212-217 行）替换为：
```python
    def get(self, path: str, params: dict | None = None):
        params = params or {}
        try:
            code, body = self._send("GET", path, params=params)
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
            # 5xx / transport error: 重试 1 次
            if self.backoff_seconds > 0:
                _time.sleep(self.backoff_seconds)
            try:
                code, body = self._send("GET", path, params=params)
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e2:
                return (0, {"error": f"transport after retry: {e2}", "path": path})
            return (code, body)
        if code == 401:
            self._login()
            try:
                code, body = self._send("GET", path, params=params)
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e2:
                return (0, {"error": f"transport after 401-retry: {e2}", "path": path})
        return (code, body)
```

- [ ] **Step 4: 改 .env.example**

末尾追加：
```
# Phase 1 #3: 重试退避秒数（5xx/ConnectError 重试 1 次前 sleep）
SCM_RETRY_BACKOFF_SECONDS=0.3
```

- [ ] **Step 5: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_5xx_retry tests/test_scm_integration_v2.py::test_connect_error_retry tests/test_scm_integration_v2.py::test_no_retry_on_4xx tests/test_scm_integration_v2.py::test_5xx_give_up_after_retry -v`
Expected: 4 passed。

- [ ] **Step 6: 跑全套确认无回归**

Run: `pytest -q`
Expected: 106 passed（102 + 4 = 106）。

- [ ] **Step 7: 提交**

```bash
git add integrations/scm/client.py .env.example tests/test_scm_integration_v2.py
git commit -m "feat(scm): retry 5xx/ConnectError/Timeout once

client.ScmClient.get() now catches httpx.HTTPStatusError (5xx),
httpx.ConnectError, httpx.TimeoutException, sleeps SCM_RETRY_BACKOFF_SECONDS
(default 0.3), retries once. After retry exhaustion returns (0, {error})
instead of raising. 401 path keeps separate token-refresh retry. 4xx
unchanged (no retry).
```

---

### Task 3: tenant_map 启动校验 (#8)

**Files:**
- Modify: `integrations/scm/auth.py:6-12`（`load_tenant_map`）
- Modify: `integrations/scm/auth.py:15`（`to_scm_tenant`）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 写 failing tests**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_tenant_map_warning_on_bad_json(monkeypatch, recwarn):
    """Phase 1 #8: 坏 JSON → warning + 默认 map。"""
    monkeypatch.setenv("SCM_TENANT_MAP", "{not valid json")
    from integrations.scm import auth
    auth.load_tenant_map.cache_clear() if hasattr(auth.load_tenant_map, "cache_clear") else None
    m = auth.load_tenant_map()
    assert m == {"t1": "tenant_001"}
    assert any("SCM_TENANT_MAP" in str(w.message) for w in recwarn.list)


def test_tenant_map_warning_on_empty(monkeypatch, recwarn):
    """Phase 1 #8: 空 dict → warning + 默认。"""
    monkeypatch.setenv("SCM_TENANT_MAP", "{}")
    from integrations.scm import auth
    auth.load_tenant_map.cache_clear() if hasattr(auth.load_tenant_map, "cache_clear") else None
    m = auth.load_tenant_map()
    assert m == {"t1": "tenant_001"}
    assert any("SCM_TENANT_MAP" in str(w.message) for w in recwarn.list)


def test_to_scm_tenant_unknown_warns(monkeypatch, recwarn):
    """Phase 1 #8: agent tenant 不在 map 中 → warning + 透传。"""
    monkeypatch.setenv("SCM_TENANT_MAP", '{"t2":"tenant_002"}')
    from integrations.scm import auth
    auth.load_tenant_map.cache_clear() if hasattr(auth.load_tenant_map, "cache_clear") else None
    scm_t = auth.to_scm_tenant("t9")
    assert scm_t == "t9"  # 透传
    assert any("no scm tenant mapping" in str(w.message).lower() for w in recwarn.list)
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_tenant_map_warning_on_bad_json tests/test_scm_integration_v2.py::test_tenant_map_warning_on_empty tests/test_scm_integration_v2.py::test_to_scm_tenant_unknown_warns -v`
Expected: 全部 FAIL（因为旧逻辑 silent except 后返回硬编码 map，没有 warning）。

- [ ] **Step 3: 改 auth.py**

`integrations/scm/auth.py` 整体替换为：
```python
"""SCM auth: login换token + tenant映射。LLM永远摸不到token。"""
import json
import os
import time
import warnings

_DEFAULT_TENANT_MAP = {"t1": "tenant_001"}


def load_tenant_map() -> dict:
    raw = os.environ.get("SCM_TENANT_MAP", "")
    if not raw:
        return dict(_DEFAULT_TENANT_MAP)
    try:
        m = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        warnings.warn("SCM_TENANT_MAP invalid JSON, falling back to defaults", stacklevel=2)
        return dict(_DEFAULT_TENANT_MAP)
    if not isinstance(m, dict) or not m:
        warnings.warn("SCM_TENANT_MAP must be non-empty JSON object, falling back to defaults",
                      stacklevel=2)
        return dict(_DEFAULT_TENANT_MAP)
    return m


def to_scm_tenant(agent_tenant: str) -> str:
    m = load_tenant_map()
    if agent_tenant not in m:
        warnings.warn(f"no scm tenant mapping for {agent_tenant!r}, passing through",
                      stacklevel=2)
        return agent_tenant
    return m[agent_tenant]


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

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_tenant_map_warning_on_bad_json tests/test_scm_integration_v2.py::test_tenant_map_warning_on_empty tests/test_scm_integration_v2.py::test_to_scm_tenant_unknown_warns -v`
Expected: 3 passed。

注意：上面测试里 `auth.load_tenant_map.cache_clear()` 在没有缓存时是 no-op（因为我们没加 `@lru_cache`），所以删掉也没事。但保留调用是为了防御未来加缓存。Phase 1 不加缓存。

- [ ] **Step 5: 跑全套确认无回归**

Run: `pytest -q`
Expected: 109 passed（106 + 3 = 109）。

- [ ] **Step 6: 提交**

```bash
git add integrations/scm/auth.py tests/test_scm_integration_v2.py
git commit -m "feat(scm): warn on tenant_map parse/config errors (#8)

Previously load_tenant_map silently caught JSON errors. Now:
- missing SCM_TENANT_MAP env -> default {'t1': 'tenant_001'}
- invalid JSON -> warning + default
- empty / non-dict JSON -> warning + default
- agent tenant not in map -> warning + pass-through (don't drop request)

LLM/Planner still never see real SCM tenant_id; warnings are
operator-facing only."
```

---

### Task 4: Phase 1 总验证 + PR

**Files:** 无新文件，仅验证。

- [ ] **Step 1: 跑全套确认 GREEN**

Run: `pytest -q`
Expected: 109 passed（v1 99 + Phase 1 新增 10 测试；前 3 任务分别贡献 3+4+3=10）。

- [ ] **Step 2: 确认仅改预期文件**

Run: `git diff --stat origin/feat/scm-integration..HEAD`
Expected 改动集：
- `integrations/scm/tools.py`
- `integrations/scm/client.py`
- `integrations/scm/auth.py`
- `.env.example`
- `tests/test_scm_integration_v2.py`

- [ ] **Step 3: 跑 v1 SCM 套件确认无回归**

Run: `pytest tests/test_scm_integration.py -v`
Expected: 8 passed（v1 的 8 测试不动）。

- [ ] **Step 4: 推送 + 开 PR**

```bash
git push -u origin feat/scm-integration-v2-foundation
gh pr create --base feat/scm-integration --head feat/scm-integration-v2-foundation \
  --title "feat(scm): v2 phase 1 foundation (write tools + 5xx retry + tenant validation)" \
  --body "## What
Phase 1 of scm-integration-v2 spec. Closes gaps #1, #3, #8.

- integrations/scm/tools.py: register scm.order.cancel + scm.stock.adjust
  placeholders so guarded_executor never reports 'unknown tool' after
  Policy.need_approval fires
- integrations/scm/client.py: ScmClient.get() retries once on 5xx /
  ConnectError / TimeoutException with SCM_RETRY_BACKOFF_SECONDS sleep;
  gives up as (0, {error: ...}) instead of raising
- integrations/scm/auth.py: SCM_TENANT_MAP bad JSON / empty dict now
  warns + falls back to defaults; unknown agent tenant warns + passes
  through (no request drops)
- .env.example: SCM_RETRY_BACKOFF_SECONDS=0.3

## Why
Stage 8 needs the full HITL surface (approval_id exposed in Phase 3
needs write tools registered) and resilient network (5xx retry) for
real SCM-platform integration tests.

## How verified
- pytest -q: 109 passed (v1 baseline 99 + Phase 1 new 10)
- v1 SCM tests (test_scm_integration.py) still 8/8 pass
- No secrets committed (.env stays local; .env.example only env keys)"
```

Expected: PR URL 返回；下一步等评审或继续 Phase 2。