import asyncio
import json
import time
import httpx
import pytest
from PySide6.QtWidgets import QApplication
from assistant_app.providers import OpenAICompatible, ProviderError
from assistant_app.settings import defaults, ConfigStore
from assistant_app.controller import Controller

class Keys:
    def get(self, _): return "fixture"

def test_fast_mode_only_changes_official_thinking():
    p = defaults()["providers"][0]
    p["extra"] = {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    body = OpenAICompatible(p, "fixture").payload([])
    assert body["thinking"]["type"] == "disabled"
    assert "reasoning_effort" not in body
    p["base_url"] = "https://compatible.example/v1"
    body = OpenAICompatible(p, "fixture").payload([])
    assert body["thinking"]["type"] == "enabled"
    assert body["reasoning_effort"] == "high"

def test_shared_client_lifetime_and_request_credentials():
    headers = []
    def handle(request):
        headers.append(request.headers["Authorization"])
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"x"}}]}\n\ndata: [DONE]\n\n')
    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            for key in ("one", "two"):
                p = OpenAICompatible(defaults()["providers"][0], key, shared_client=client)
                events = [x async for x in p.stream([])]
                assert not client.is_closed
                assert any(x.get("text") == "x" for x in events)
                assert next(x["timings"]["first_token"] for x in events if "first_token" in x.get("timings", {})) >= 0
        finally:
            await client.aclose()
    asyncio.run(run())
    assert headers == ["Bearer one", "Bearer two"]

def test_accepted_read_timeout_is_not_retried_and_reasoning_not_exposed():
    calls, events = [], []
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"reasoning_content":"private-chain"}}]}\n\n'
            raise httpx.ReadTimeout("fixture")
    def handle(request):
        calls.append(1)
        return httpx.Response(200, stream=Broken())
    async def run():
        p = OpenAICompatible(defaults()["providers"][0], "fixture", transport=httpx.MockTransport(handle))
        async for event in p.stream([]):
            events.append(event)
    with pytest.raises(ProviderError, match="超时"):
        asyncio.run(run())
    assert len(calls) == 1
    assert any(x.get("phase") == "reasoning" for x in events)
    assert "private-chain" not in json.dumps(events)

def test_quick_context_keeps_background_and_limits_history(tmp_path):
    app = QApplication.instance() or QApplication([])
    c = defaults()
    c["backgrounds"][0]["text"] = "实际背景资料"
    c["use_background"] = True
    ctrl = Controller(c, ConfigStore(tmp_path), Keys())
    try:
        ctrl.history = [{"question": f"q{i}", "answer": f"a{i}", "status": "done"} for i in range(5)]
        messages = ctrl.messages("为什么")
        assert "实际背景资料" in messages[0]["content"]
        assert [m["content"] for m in messages if m["role"] == "assistant"] == ["a3", "a4"]
        assert len(ctrl.history) == 5
        c["fast_answers"] = False
        assert len([m for m in ctrl.messages("为什么") if m["role"] == "assistant"]) == 5
    finally:
        ctrl.close()

def test_fast_burst_ui_is_coalesced_and_final_text_complete(tmp_path, monkeypatch):
    from assistant_app import controller as module
    from assistant_app.ui import MainWindow
    app = QApplication.instance() or QApplication([])
    class Burst:
        async def stream(self, messages):
            for _ in range(2000):
                yield {"text": "字"}
    monkeypatch.setattr(module, "adapter", lambda *args, **kwargs: Burst())
    ctrl = Controller(defaults(), ConfigStore(tmp_path), Keys())
    window = MainWindow(ctrl)
    updates = []
    ctrl.events.snapshot.connect(lambda _: updates.append(1))
    try:
        ctrl.submit("测试首字显示")
        until = time.monotonic() + 5
        while time.monotonic() < until:
            app.processEvents()
            if ctrl.history and ctrl.history[-1]["status"] == "done":
                app.processEvents()
                break
            time.sleep(.01)
        assert ctrl.history[-1]["status"] == "done"
        assert window.answer.toPlainText() == "字" * 2000
        assert len(updates) < 30
        assert ctrl.history[-1]["timings"]["submit_to_first_token"] >= 0
        pooled = ctrl.client
    finally:
        window.close()
    assert pooled.is_closed
