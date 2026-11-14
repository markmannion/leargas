import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, voice


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("/speech-to-text"):
            return httpx.Response(200, json={"text": " How many windows? ", "language_code": "eng"})
        return httpx.Response(200, content=b"ID3fake", headers={"content-type": "audio/mpeg"})

    real = httpx.AsyncClient
    monkeypatch.setattr(voice.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    return seen


def test_status_off(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    c = TestClient(main.app)
    assert c.get("/voice/status").json() == {"enabled": False}
    assert c.post("/voice/speak", json={"text": "hi"}).status_code == 503


def test_transcribe(calls):
    r = TestClient(main.app).post("/voice/transcribe", content=b"abc", headers={"content-type": "audio/webm;codecs=opus"})
    assert r.json() == {"text": "How many windows?", "language_code": "eng"}
    assert calls[0].headers["xi-api-key"] == "test-key"
    assert b'filename="question.webm"' in calls[0].content


def test_speak(calls):
    r = TestClient(main.app).post("/voice/speak", json={"text": "Twelve windows."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3fake"
    assert "/text-to-speech/" in calls[0].url.path
