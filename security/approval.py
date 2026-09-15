"""Human-in-the-loop: 高风险操作先建审批单，批了才能执行。"""
from itertools import count


class ApprovalStore:
    def __init__(self):
        self._items: dict[str, dict] = {}
        self._seq = count(1)

    def request(self, user: dict, tool: str, args: dict) -> str:
        aid = f"apr-{next(self._seq)}"
        self._items[aid] = {"id": aid, "user": user, "tool": tool,
                            "args": args or {}, "status": "pending"}
        return aid

    def get(self, approval_id: str) -> dict:
        return self._items[approval_id]

    def approve(self, approval_id: str, approver: str) -> dict:
        item = self._items[approval_id]
        item["status"] = "approved"
        item["approver"] = approver
        return item

    def reject(self, approval_id: str, approver: str) -> dict:
        item = self._items[approval_id]
        item["status"] = "rejected"
        item["approver"] = approver
        return item
