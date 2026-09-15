"""Stage1b RED: DeepSeek Planner 可注入 + Gateway 走 Runtime。"""
from agent.runtime.state import AgentState
from agent.runtime.llm_planner import build_deepseek_planner


def test_planner_without_key_finishes_echo():
    planner = build_deepseek_planner(client=None, model="deepseek-chat")
    s = AgentState(task="查报销")
    plan = planner(s)
    assert plan["action"] == "finish"
    assert "查报销" in plan["answer"]


def test_planner_with_fake_client_parses_json():
    class FakeMsg:
        content = '{"action": "finish", "answer": "hi done"}'

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            assert "messages" in kwargs
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    planner = build_deepseek_planner(client=FakeClient(), model="deepseek-chat")
    plan = planner(AgentState(task="hi"))
    assert plan["action"] == "finish"
    assert plan["answer"] == "hi done"


def test_chat_goes_through_runtime():
    from fastapi.testclient import TestClient
    from apps.api.main import app

    c = TestClient(app)
    r = c.post("/chat", json={"message": "hello runtime"})
    assert r.status_code == 200
    body = r.json()
    assert "hello runtime" in body["reply"]
    assert body.get("status") == "done"
