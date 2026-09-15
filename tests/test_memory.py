"""Stage4 RED: 五层记忆 = Conversation/Task/User/Org/Episodic，先内存版。"""
from agent.memory.store import MemoryStore
from agent.runtime.state import AgentState
from agent.runtime.loop import run


def test_conversation_rolling_window():
    m = MemoryStore()
    for i in range(5):
        m.save_conversation("u1", "t1", "user", f"msg{i}")
    last3 = m.get_conversation("u1", "t1", limit=3)
    assert [x["content"] for x in last3] == ["msg2", "msg3", "msg4"]


def test_task_memory_save_and_get():
    m = MemoryStore()
    m.save_task("task-po-001", summary="采购异常：供应商延迟", status="open", result="")
    t = m.get_task("task-po-001")
    assert t["summary"] == "采购异常：供应商延迟"
    m.save_task("task-po-001", summary="采购异常：供应商延迟", status="done", result="已补货")
    assert m.get_task("task-po-001")["status"] == "done"


def test_episodic_recall_finds_prior_issue():
    m = MemoryStore()
    m.save_episodic("u1", "t1", "处理采购异常PO-001，供应商延迟，已补货")
    m.save_episodic("u1", "t1", "午餐补贴咨询")
    hits = m.recall_episodic("u1", "t1", "继续处理上次那个采购问题", top_k=1)
    assert "PO-001" in hits[0]


def test_user_and_org_profiles():
    m = MemoryStore()
    m.save_user_profile("u1", {"role": "manager", "department": "ops"})
    m.save_org_memory("t1", {"expense_threshold": 5000})
    assert m.get_user_profile("u1")["role"] == "manager"
    assert m.get_org_memory("t1")["expense_threshold"] == 5000


def test_loop_receives_memory_context():
    m = MemoryStore()
    m.save_conversation("u1", "t1", "user", "上次采购PO-001延迟")
    m.save_conversation("u1", "t1", "assistant", "已补货，待验收")

    def planner(state: AgentState):
        # 能看到历史才算记忆生效
        assert any("PO-001" in str(x) for x in state.messages)
        return {"action": "finish", "answer": "继续验收PO-001"}

    s = AgentState(task="继续处理上次那个采购问题")
    s.messages = m.get_conversation("u1", "t1", limit=10)
    final = run(s, planner=planner)
    assert final.status == "done"
    assert "PO-001" in final.answer
