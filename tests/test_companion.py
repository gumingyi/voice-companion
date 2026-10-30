import asyncio
import json
import socket
import time
import sys
import httpx
import pytest
from websockets.asyncio.client import connect
from assistant_app.companion import Companion

def test_windowed_executable_without_console(monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    service = Companion()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        try:
            service.start("127.0.0.1", port)
            assert service.server.started
        finally:
            service.stop()

@pytest.fixture
def service():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    service = Companion()
    service.start("127.0.0.1", port)
    yield service
    service.stop()
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0

def pair(service):
    base = f"http://127.0.0.1:{service.port}"
    token = service.pair_link().split("#pair=")[1]
    client = httpx.Client(base_url=base, headers={"Origin": base}, trust_env=False)
    response = client.post("/pair", json={"token": token})
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    return client, token, base

def test_pair_security(service):
    client, token, base = pair(service)
    try:
        assert client.post("/pair", json={"token": token}).status_code == 401
        assert client.post("/pair", headers={"Origin": "http://evil.test"}, json={"token": token}).status_code == 403
        assert client.get("/", headers={"Host": "evil.test"}).status_code == 403
        assert "no-store" in client.get("/").headers["cache-control"]
        assert "api_key" not in client.get("/").text.lower()
        assert client.post("/unpair").status_code == 200
    finally:
        client.close()
    assert not service.devices()

def test_expiry_and_rate_limit(service):
    token = service.pair_link().split("#pair=")[1]
    service.invite_until = 0
    base = f"http://127.0.0.1:{service.port}"
    with httpx.Client(base_url=base, headers={"Origin": base}, trust_env=False) as client:
        assert client.post("/pair", json={"token": token}).status_code == 401
        for _ in range(7):
            assert client.post("/pair", json={"token": "bad"}).status_code == 401
        assert client.post("/pair", json={"token": "bad"}).status_code == 429

def test_real_websocket_stream_reconnect_revoke(service):
    client, _, base = pair(service)
    cookie = "companion=" + client.cookies.get("companion")
    uri = f"ws://127.0.0.1:{service.port}/ws"
    async def run():
        async with connect(uri, origin=base, additional_headers={"Cookie": cookie}, proxy=None) as ws:
            assert json.loads(await ws.recv())["history"] == []
            entry = {"id": "one", "question": "测试问题", "answer": "第一个", "status": "generating", "model": "test", "api_key": "should-not-leak"}
            started = time.monotonic()
            service.publish("正在生成", "私密转写", [entry])
            snapshot = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert snapshot["history"][0]["answer"] == "第一个"
            assert time.monotonic() - started < 2
            assert not snapshot["transcript"]
            assert "should-not-leak" not in json.dumps(snapshot)
            entry["answer"] += "增量"
            service.publish("正在生成", "私密转写", [entry])
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["history"][0]["answer"] == "第一个增量"
        async with connect(uri, origin=base, additional_headers={"Cookie": cookie}, proxy=None) as ws:
            assert json.loads(await ws.recv())["history"][0]["answer"] == "第一个增量"
            service.revoke()
            with pytest.raises(Exception):
                await asyncio.wait_for(ws.recv(), 2)
        with pytest.raises(Exception):
            async with connect(uri, origin="http://evil.test", additional_headers={"Cookie": cookie}, proxy=None):
                pass
    asyncio.run(run())
    client.close()
