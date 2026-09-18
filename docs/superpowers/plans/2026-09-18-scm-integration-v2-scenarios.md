# SCM Integration v2 — Phase 2: Scenarios Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 v1 缺口 #4（IT Ops 场景）、#6（supplier 钩）；IT Ops 三场景居首；review_contract 真正接入 scm 数据。

**Architecture:** TDD 顺序：先加 `scm.supplier.get` tool + Policy 入口；再实现 `run_it_ops` 模板；最后给 `review_contract` 加 supplier 钩。Phase 2 完成时 `pytest -q` 应 116 passed（Phase 1 后 109 + Phase 2 新增 7）。

**Tech Stack:** Python 3.12+, pytest-asyncio auto；与 Phase 1 一致。

**Base branch:** `feat/scm-integration-v2-foundation`（Phase 1 PR 合并后基于此）；新分支 `feat/scm-integration-v2-scenarios` 基于此。

**重要前提：** Phase 1 PR #17 已合并到 `feat/scm-integration`。Phase 2 起始分支是更新后的 `feat/scm-integration`，不是 `feat/scm-integration-v2-foundation`（后者作为 PR 完成后会被 merge 而消失）。

---

### Task 1: scm.supplier.get 只读 tool (#6)

**Files:**
- Modify: `integrations/scm/policy_map.py:1-3`（`SCM_READ_TOOLS`）
- Modify: `integrations/scm/tools.py:13-23`（mock 函数）、30-33（mock 注册）、60-64（真实注册）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 切分支**

```bash
cd D:\ProgramProject\enterprise-agent
git checkout feat/scm-integration
git pull origin feat/scm-integration
git checkout -b feat/scm-integration-v2-scenarios
```

- [ ] **Step 2: 写 failing tests**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_scm_supplier_get_registered():
    """Phase 2 #6: scm.supplier.get 必须在 registry 里。"""
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    assert "scm.supplier.get" in reg.list_tools()


def test_scm_supplier_get_read_allowed():
    """Phase 2 #6 联动：PolicyEngine allow。"""
    from security.policy import PolicyEngine
    p = PolicyEngine()
    d = p.check({"tenant_id": "t1", "role": "employee"},
                "scm.supplier.get", {"supplier_id": "SP-001", "tenant_id": "t1"})
    assert d["decision"] == "allow"


def test_scm_supplier_get_mock_payload():
    """Phase 2 #6: 离线 mock 返回 supplier 风险字段。"""
    from agent.tools.registry import Registry
    from integrations.scm.tools import register_scm_tools
    reg = Registry()
    register_scm_tools(reg)
    out = reg.call("scm.supplier.get", {"supplier_id": "SP-001", "tenant_id": "t1"})
    s = str(out)
    assert "SP-001" in s
    assert "credit_score" in s or "rating" in s
```

- [ ] **Step 3: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_scm_supplier_get_registered tests/test_scm_integration_v2.py::test_scm_supplier_get_read_allowed tests/test_scm_integration_v2.py::test_scm_supplier_get_mock_payload -v`
Expected: 全部 FAIL（`test_scm_supplier_get_read_allowed` 会因 `unknown tool` deny）。

- [ ] **Step 4: 改 policy_map.py**

`integrations/scm/policy_map.py` 替换为：
```python
"""SCM读写分级：读=allow，写=need_approval，未知=deny。"""
SCM_READ_TOOLS = {
    "scm.order.get",
    "scm.inventory.query",
    "scm.sales.report",
    "scm.supplier.get",  # v2 Phase 2: 合同 supplier 风险查询
}
SCM_WRITE_TOOLS = {"scm.purchase.create", "scm.order.cancel", "scm.stock.adjust"}


def scm_policy_decision(tool: str) -> str:
    if tool in SCM_READ_TOOLS:
        return "allow"
    if tool in SCM_WRITE_TOOLS:
        return "need_approval"
    return "deny"
```

- [ ] **Step 5: 改 tools.py**

在 mock 函数区（13-23 行）追加：
```python
def _mock_supplier(args: dict):
    sid = args.get("supplier_id", "SP-001")
    return f"supplier={sid} rating=B credit_score=72 risk=medium (mock)"
```

mock 注册分支（30-33 行附近）在写口占位前插入：
```python
        registry.register(Tool("scm.supplier.get", "查SCM供应商风险(只读)", _mock_supplier))
```

真实分支（60-64 行附近）加 `_supplier_get` 闭包并注册。在 `_sales` 函数后（约 58 行）加：
```python
    def _supplier_get(args: dict):
        args = args or {}
        try:
            code, body = c.get(
                f"/api/suppliers/{args.get('supplier_id','')}",
                params={"tenant": to_scm_tenant(args.get("tenant_id", "t1"))},
            )
            return str(body)[:2000] if code == 200 else f"tool error scm.supplier.get: {code} {str(body)[:500]}"
        except Exception as e:
            return f"tool error scm.supplier.get: {e}"
```

真实注册（约 60-64 行）改为：
```python
    registry.register(Tool("scm.order.get", "查SCM订单(只读)", _order_get))
    registry.register(Tool("scm.inventory.query", "查SCM库存(只读)", _inv_query))
    registry.register(Tool("scm.sales.report", "查销售聚合(只读)", _sales_report_alias(_sales)))
    registry.register(Tool("scm.supplier.get", "查SCM供应商风险(只读)", _supplier_get))
    registry.register(Tool("scm.purchase.create", "建采购单(占位, 走HITL)",
                           lambda a: "need approval: scm.purchase.create pending human review"))
    registry.register(Tool("scm.order.cancel", "取消SCM订单(占位, 走HITL)",
                           lambda a: "need approval: scm.order.cancel pending human review"))
    registry.register(Tool("scm.stock.adjust", "调整SCM库存(占位, 走HITL)",
                           lambda a: "need approval: scm.stock.adjust pending human review"))
    return registry
```

- [ ] **Step 6: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_scm_supplier_get_registered tests/test_scm_integration_v2.py::test_scm_supplier_get_read_allowed tests/test_scm_integration_v2.py::test_scm_supplier_get_mock_payload -v`
Expected: 3 passed。

- [ ] **Step 7: 跑全套确认无回归**

Run: `pytest -q`
Expected: 112 passed（109 + 3 = 112）。

- [ ] **Step 8: 提交**

```bash
git add integrations/scm/policy_map.py integrations/scm/tools.py tests/test_scm_integration_v2.py
git commit -m "feat(scm): add scm.supplier.get read tool (#6)

New tool GET /api/suppliers/{supplier_id}?tenant=... added to
SCM_READ_TOOLS. Mock returns supplier rating + credit_score + risk.
Used by review_contract (Phase 2 Task 3) to enrich contract risk opinion."
```

---

### Task 2: run_it_ops 场景 (#4)

**Files:**
- Modify: `workflow/scenarios.py`（在文件末尾追加 `run_it_ops`）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 写 failing tests**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_run_it_ops_basic():
    """Phase 2 #4: run_it_ops 返回 report + trace，trace 含 metrics + logs。"""
    from workflow.scenarios import run_it_ops
    out = run_it_ops("近7天为什么下降")
    assert "report" in out
    assert "trace" in out
    assert "metrics.get" in out["trace"]
    assert "logs.search" in out["trace"]


def test_run_it_ops_extracts_order_no():
    """Phase 2 #4: question 含订单号（如'O-1234567'）时 trace 加 scm.order.get。"""
    from workflow.scenarios import run_it_ops
    out = run_it_ops("订单 O-20260915001 支付超时")
    assert "scm.order.get" in out["trace"]


def test_run_it_ops_no_order_no_keeps_template():
    """Phase 2 #4: 无订单号时 trace 不含 scm.order.get。"""
    from workflow.scenarios import run_it_ops
    out = run_it_ops("服务异常")
    assert "scm.order.get" not in out["trace"]
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_run_it_ops_basic tests/test_scm_integration_v2.py::test_run_it_ops_extracts_order_no tests/test_scm_integration_v2.py::test_run_it_ops_no_order_no_keeps_template -v`
Expected: 全部 FAIL with `cannot import name 'run_it_ops'`。

- [ ] **Step 3: 在 scenarios.py 追加 run_it_ops**

`workflow/scenarios.py` 末尾追加：
```python
import logging
import re

_ORDER_PATTERN = re.compile(r"\bO-\d{6,}\b")


def run_it_ops(question: str, tenant_id: str = "t1") -> dict:
    """IT Ops 场景：metrics + logs 模板；命中异常模式时拉订单详情。

    Scenario 内部 tool 调用不经 Policy 强制（设计 §5.3 显式 trade-off，
    与 analyze_sales 一致；scenario 自身已被 workflow 层授权）。
    """
    from agent.tools.builtin import build_default_registry
    reg = build_default_registry()
    trace = []
    metrics = "metrics 暂不可用"
    logs = "logs 暂不可用"
    order = "订单暂不可用"

    try:
        metrics = reg.call("metrics.get", {"service": "mall"})
        trace.append("metrics.get")
    except Exception as e:
        logging.getLogger(__name__).warning("metrics.get failed: %r", e)

    try:
        logs = reg.call("logs.search", {"query": question, "tenant_id": tenant_id})
        trace.append("logs.search")
    except Exception as e:
        logging.getLogger(__name__).warning("logs.search failed: %r", e)

    logs_text = str(logs)
    if any(k in logs_text for k in ("error", "timeout", "500", "失败")):
        m = _ORDER_PATTERN.search(question)
        if m and "scm.order.get" in reg.list_tools():
            try:
                order = reg.call("scm.order.get", {"order_no": m.group(0),
                                                   "tenant_id": tenant_id})
            except Exception as e:
                logging.getLogger(__name__).warning("scm.order.get failed: %r", e)
            trace.append("scm.order.get")

    report = (
        f"IT Ops 诊断报告：{question}\n"
        f"- 服务指标：{metrics}\n"
        f"- 相关日志：{logs}\n"
        f"- 受影响订单：{order}\n"
        f"- 初步判断：依据日志模式 + 订单状态定位故障源。"
    )
    return {"report": report, "trace": trace}
```

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_run_it_ops_basic tests/test_scm_integration_v2.py::test_run_it_ops_extracts_order_no tests/test_scm_integration_v2.py::test_run_it_ops_no_order_no_keeps_template -v`
Expected: 3 passed。

- [ ] **Step 5: 跑全套确认无回归**

Run: `pytest -q`
Expected: 115 passed（112 + 3 = 115）。

- [ ] **Step 6: 提交**

```bash
git add workflow/scenarios.py tests/test_scm_integration_v2.py
git commit -m "feat(scenarios): add run_it_ops for IT Ops scenario (#4)

New run_it_ops(question, tenant_id='t1') stitches metrics.get +
logs.search, then pulls scm.order.get when question contains an
order number AND log payload shows error/timeout/500/失败. Same
silent-fallback pattern as analyze_sales (no exception leaks to
report). Closes the IT Ops leg of the 3-scenario roadmap."
```

---

### Task 3: review_contract supplier 钩 (#6 续)

**Files:**
- Modify: `workflow/scenarios.py:5-19`（`review_contract`）
- Test: `tests/test_scm_integration_v2.py`

- [ ] **Step 1: 写 failing tests**

在 `tests/test_scm_integration_v2.py` 追加：
```python
def test_review_contract_uses_supplier():
    """Phase 2 #6: risk 命中时 opinion 含 supplier 信息 + trace 含 scm.supplier.get。"""
    from workflow.scenarios import review_contract
    out = review_contract({"amount": 50000, "clauses": [], "supplier_id": "SP-001"})
    assert out["decision"] == "human_review"
    assert "supplier" in out["opinion"].lower() or "SP-001" in out["opinion"]
    assert "scm.supplier.get" in out["trace"]


def test_review_contract_no_supplier_id_skips_hook():
    """Phase 2 #6: 缺 supplier_id 时不调 scm，opinion 不含 supplier 字段。"""
    from workflow.scenarios import review_contract
    out = review_contract({"amount": 50000, "clauses": []})
    assert "scm.supplier.get" not in out["trace"]


def test_supplier_call_failure_does_not_break_review(monkeypatch):
    """Phase 2 #6: scm.supplier.get 失败时 review_contract 仍返回原 decision。"""
    from agent.tools.registry import Registry
    from workflow import scenarios
    orig_call = Registry.call
    def fake_call(self, name, args):
        if name == "scm.supplier.get":
            raise RuntimeError("scm down")
        return orig_call(self, name, args)
    monkeypatch.setattr(Registry, "call", fake_call)
    out = scenarios.review_contract({"amount": 50000, "clauses": [], "supplier_id": "SP-001"})
    assert out["decision"] == "human_review"
    assert "暂不可用" in out["opinion"] or "supplier" in out["opinion"].lower()
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `pytest tests/test_scm_integration_v2.py::test_review_contract_uses_supplier tests/test_scm_integration_v2.py::test_review_contract_no_supplier_id_skips_hook tests/test_scm_integration_v2.py::test_supplier_call_failure_does_not_break_review -v`
Expected: 全部 FAIL（`test_review_contract_uses_supplier` 因 opinion 没 supplier；`test_review_contract_no_supplier_id_skips_hook` PASS 因为当前 review_contract 根本没调 supplier——但记 RED 是为了表明未来行为；这里实际上 Task 3 的 RED 来自 `test_review_contract_uses_supplier` 一定会 FAIL 因为现状 opinion 不含 supplier）。

- [ ] **Step 3: 改 review_contract**

`workflow/scenarios.py` 的 `review_contract` 替换为：
```python
def review_contract(contract: dict) -> dict:
    from knowledge.seed import get_default_store
    amount = contract.get("amount", 0)
    clauses = contract.get("clauses", [])
    supplier_id = contract.get("supplier_id", "")
    hits = get_default_store().search("合同审批 赔偿 预付款", tenant_id="t1",
                                      allowed_permissions=["employee", "finance", "manager", "admin"])
    policy_ref = hits[0].text[:80] if hits else "超阈值需审批"
    risky = amount > 10000 or any(any(r in c for r in RISKY_CLAUSES) for c in clauses)
    if not risky:
        return {"decision": "auto_approve",
                "opinion": f"标准小额合同自动通过：金额{amount}",
                "trace": ["retrieve_policy", "judge_rule", "auto_approve"]}

    trace = ["retrieve_policy", "judge_rule"]
    supplier_info = "(supplier 信息暂不可用)"
    if supplier_id:
        try:
            from agent.tools.builtin import build_default_registry
            reg = build_default_registry()
            sup_out = reg.call("scm.supplier.get", {"supplier_id": supplier_id, "tenant_id": "t1"})
            supplier_info = str(sup_out)
            trace.append("scm.supplier.get")
        except Exception as e:
            logging.getLogger(__name__).warning("scm.supplier.get failed: %r", e)

    return {"decision": "human_review",
            "opinion": f"风险条款需人审：{clauses}；金额{amount}；供应商{supplier_info}。依据：{policy_ref}",
            "trace": trace + ["human_review"]}
```

注意：上面新增的 `import logging` 已在 Task 2 里加过（Task 2 import logging / re）；若尚未加需在文件顶部 import。

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `pytest tests/test_scm_integration_v2.py::test_review_contract_uses_supplier tests/test_scm_integration_v2.py::test_review_contract_no_supplier_id_skips_hook tests/test_scm_integration_v2.py::test_supplier_call_failure_does_not_break_review -v`
Expected: 3 passed。

- [ ] **Step 5: 跑 v1 review_contract 测试确认兼容**

Run: `pytest tests/test_workflow.py -v -k review_contract 2>&1 | head -30`
Expected: v1 review_contract 测试仍 PASS（若 v1 有专门测试）。

若无 v1 review_contract 测试，跳过此步；Phase 1 全套测试已隐含覆盖。

- [ ] **Step 6: 跑全套确认无回归**

Run: `pytest -q`
Expected: 118 passed（115 + 3 = 118）。

- [ ] **Step 7: 提交**

```bash
git add workflow/scenarios.py tests/test_scm_integration_v2.py
git commit -m "feat(scenarios): review_contract supplier risk hook (#6)

When contract has supplier_id and risk threshold is hit, pull
scm.supplier.get and append supplier info to opinion. Tool failure
is non-fatal: review still returns human_review with '(supplier
信息暂不可用)' suffix. No supplier_id → skip the hook entirely
(trace unchanged)."
```

---

### Task 4: Phase 2 总验证 + PR

**Files:** 无新文件。

- [ ] **Step 1: 跑全套确认 GREEN**

Run: `pytest -q`
Expected: 118 passed。

- [ ] **Step 2: 确认改动集**

Run: `git diff --stat origin/feat/scm-integration..HEAD`
Expected 改动集：
- `integrations/scm/policy_map.py`
- `integrations/scm/tools.py`
- `workflow/scenarios.py`
- `tests/test_scm_integration_v2.py`

- [ ] **Step 3: 推送 + 开 PR**

```bash
git push -u origin feat/scm-integration-v2-scenarios
gh pr create --base feat/scm-integration --head feat/scm-integration-v2-scenarios \
  --title "feat(scm): v2 phase 2 scenarios (IT Ops + supplier hook)" \
  --body "## What
Phase 2 of scm-integration-v2 spec. Closes gaps #4 and #6.

- integrations/scm/policy_map.py + tools.py: scm.supplier.get
  read-only tool (GET /api/suppliers/{id}?tenant=...)
- workflow/scenarios.py: new run_it_ops(question, tenant_id='t1')
  for IT Ops diagnostic, stitches metrics.get + logs.search, pulls
  scm.order.get when question contains order number AND logs show
  error/timeout/500/失败
- workflow/scenarios.py: review_contract supplier hook — when risk
  threshold hit AND supplier_id present, append scm.supplier.get to
  opinion; tool failure non-fatal

## Why
Roadmap lists IT Ops as the first of three target scenarios. v1
only had Contract Compliance + Sales Analytics mocks. Adding
scm.supplier.get makes review_contract actually use scm data
instead of being pure mock.

## How verified
- pytest -q: 118 passed (Phase 1 109 + Phase 2 new 9)
- v1 SCM tests (test_scm_integration.py) still 8/8 pass
- v2 Phase 1 tests (test_scm_integration_v2.py Phase 1 part) still 10/10
- No secrets committed"
```

Expected: PR URL 返回；下一步等评审或继续 Phase 3。