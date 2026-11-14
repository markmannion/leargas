import httpx
import pytest

from app import gemma_status, main, router


@pytest.fixture
def probe(monkeypatch):
    now, calls = [100.0], []
    response = {"data": [{"id": "gemma-ft"}, {"id": "gemma-base"}]}
    client_class = httpx.Client

    def handler(request):
        calls.append(request)
        if isinstance(response.get("error"), Exception):
            raise response["error"]
        return httpx.Response(response.get("http_status", 200), json=response)

    monkeypatch.setattr(gemma_status.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(gemma_status.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("MODEL_BASE_URL", "http://gemma.test/v1")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    gemma_status.endpoint.cache_clear()
    yield now, calls, response
    gemma_status.endpoint.cache_clear()


def test_probe_authenticates_and_caches_per_endpoint(probe):
    _, calls, _ = probe
    assert gemma_status.status()["available"]
    assert gemma_status.status("gemma-base")["available"]
    assert len(calls) == 1
    assert str(calls[0].url) == "http://gemma.test/v1/models"
    assert calls[0].headers["authorization"] == "Bearer test-key"


@pytest.mark.parametrize("failure", [
    {"error": httpx.ConnectError("down")},
    {"error": httpx.ReadTimeout("stalled")},
    {"http_status": 401},
    {"http_status": 503},
    {"data": []},
    {"data": None},
])
def test_outage_is_cached_and_recovers_without_restart(probe, failure):
    now, calls, response = probe
    response.clear()
    response.update(failure)
    assert gemma_status.status()["status"] == "unavailable"
    assert not gemma_status.status()["available"]
    assert len(calls) == 1
    response.clear()
    response["data"] = [{"id": "gemma-ft"}]
    now[0] += gemma_status.CHECK_INTERVAL + 1
    assert gemma_status.status()["available"]
    assert len(calls) == 2


def test_only_missing_model_is_unavailable(probe):
    _, _, response = probe
    response["data"] = [{"id": "gemma-base"}]
    assert not gemma_status.status("gemma-ft")["available"]
    assert gemma_status.status("gemma-base")["available"]


def test_inference_failure_cooldown_and_recovery(probe):
    now, _, _ = probe
    assert gemma_status.status()["available"]
    gemma_status.failed("gemma-ft")
    assert not gemma_status.status()["available"]
    assert gemma_status.status("gemma-base")["available"]
    now[0] += gemma_status.CHECK_INTERVAL + 1
    assert gemma_status.status()["available"]


def test_concurrent_probe_does_not_block_or_duplicate(probe):
    _, calls, _ = probe
    endpoint = gemma_status.endpoint("http://gemma.test/v1", "test-key")
    with endpoint.probing:
        assert gemma_status.status()["status"] == "checking"
    assert calls == []


def test_unconfigured_does_not_probe(probe, monkeypatch):
    _, calls, _ = probe
    monkeypatch.delenv("MODEL_BASE_URL")
    assert gemma_status.status()["status"] == "unconfigured"
    assert calls == []


def test_live_health_reports_actual_model_readiness(probe, monkeypatch):
    _, _, response = probe
    monkeypatch.delenv("LEARGAS_MOCK", raising=False)
    monkeypatch.setattr(router, "_import_model_pkg", lambda: None)
    response["data"] = [{"id": "gemma-base"}]
    health = main.health()
    assert health["ok"] and health["mode"] == "live"
    assert health["gemma"] is False
    assert health["gemma_status"]["models"] == {"gemma-ft": "unavailable", "gemma-base": "available"}
