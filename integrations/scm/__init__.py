"""SCM-platform integration: client/auth/tools/policy_map.

LLM 永远不直调 client；统一经 Registry Tool + PolicyEngine 管控。
无 SCM_GATEWAY_URL 配置时 tools 回退 Mock，保证离线可测。
"""
try:
    from .tools import register_scm_tools
except ImportError:
    register_scm_tools = None  # tools.py lands in Task 3

__all__ = ["register_scm_tools"]
