"""The readiness endpoint must isolate slow or failed model upstreams."""
import asyncio
import importlib.util
from pathlib import Path

import httpx
from starlette.requests import Request


def test_model_lists_are_probed_concurrently_and_fail_independently(monkeypatch):
    spec = importlib.util.spec_from_file_location("model_proxy", Path(__file__).resolve().parents[2] / "infra/model_proxy.py")
    proxy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy)

    async def run():
        started = set()
        all_started = asyncio.Event()

        async def handler(request):
            started.add(request.url.host)
            if len(started) == 3:
                all_started.set()
            # A sequential implementation times out here before hitting the other upstreams.
            await asyncio.wait_for(all_started.wait(), timeout=1)
            if request.url.host == "down.test":
                raise httpx.ConnectError("offline")
            if request.url.host == "bad.test":
                return httpx.Response(200, json={"data": None})
            return httpx.Response(200, json={"data": [{"id": "gemma-base"}]})

        await proxy.client.aclose()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(proxy, "client", client)
            monkeypatch.setattr(proxy, "API_KEY", "")
            monkeypatch.setattr(proxy, "ROUTES", {"base": "http://up.test", "ft": "http://down.test", "bad": "http://bad.test"})
            response = await proxy.models(Request({"type": "http", "headers": []}))
            assert response == {"object": "list", "data": [{"id": "gemma-base"}]}

    asyncio.run(run())
