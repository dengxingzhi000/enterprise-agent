"""Policy Engine: User/Role → Tool前检查。LLM不能直调工具。"""
HIGH_RISK = {"payment.execute", "data.delete", "contract.approve", "email.send"}
READ_TOOLS = {"metrics.get", "logs.search", "git.diff", "knowledge.search", "db.query"}


class PolicyEngine:
    def check(self, user: dict, tool: str, args: dict) -> dict:
        args = args or {}
        # 跨租户直接拒
        if "tenant_id" in args and args["tenant_id"] != user.get("tenant_id"):
            return {"decision": "deny", "reason": "cross-tenant denied"}

        if tool in HIGH_RISK:
            return {"decision": "need_approval", "reason": f"{tool} is high-risk"}

        if tool in ("metrics.get", "logs.search", "git.diff", "knowledge.search"):
            return {"decision": "allow", "reason": "low-risk read"}

        if tool == "db.query":
            scope = args.get("scope", "self")
            role = user.get("role", "employee")
            if scope == "self":
                return {"decision": "allow", "reason": "own data"}
            if scope == "dept" and role in ("manager", "finance", "admin"):
                return {"decision": "allow", "reason": "dept data"}
            if scope == "all" and role in ("finance", "admin"):
                return {"decision": "allow", "reason": "all data"}
            return {"decision": "deny", "reason": f"role {role} cannot query scope={scope}"}

        return {"decision": "deny", "reason": f"unknown tool {tool}"}
