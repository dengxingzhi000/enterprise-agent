"""SCM-platform integration: client/auth/tools/policy_map."""
try:
    from .tools import register_scm_tools
except ImportError:
    register_scm_tools = None  # tools.py lands in Task 3

__all__ = ["register_scm_tools"]
