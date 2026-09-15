from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_chat_echo():
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 200
    assert "hi" in r.json()["reply"]
