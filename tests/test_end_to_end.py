"""Real HTTP + Controller + real WebSocket. Provider is explicitly a test fixture,
not evidence of a successful authenticated DeepSeek call.
"""
import asyncio
import json
import socket
import threading
import time
import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from PySide6.QtWidgets import QApplication
from websockets.asyncio.client import connect
import uvicorn
from assistant_app.settings import defaults, ConfigStore
from assistant_app.controller import Controller

class TestKeys:
    def get(self, _): return "test-only"

def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def test_detected_question_to_model_to_companion(tmp_path):
    app = QApplication.instance() or QApplication([])
    fake = FastAPI()
    requests = []
    @fake.post("/chat/completions")
    async def chat():
        requests.append(1)
        async def body():
            for word in ["自动", "回答", "测试"]:
                yield "data: " + json.dumps({"choices": [{"delta": {"content": word}}]}) + "\n\n"
                await asyncio.sleep(.15)
            yield "data: [DONE]\n\n"
        return StreamingResponse(body(), media_type="text/event-stream")
    fake_port = port()
    server = uvicorn.Server(uvicorn.Config(fake, host="127.0.0.1", port=fake_port, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    until = time.monotonic() + 5
    while not server.started and time.monotonic() < until:
        time.sleep(.02)
    assert server.started
    config = defaults()
    config["audio"].update(auto_submit=True, manual_capture=False, live_transcription=False, answer_on_pause=False)
    config["providers"][0]["base_url"] = f"http://127.0.0.1:{fake_port}"
    ctrl = Controller(config, ConfigStore(tmp_path), TestKeys())
    mobile_port = port()
    ctrl.companion.start("127.0.0.1", mobile_port)
    base = f"http://127.0.0.1:{mobile_port}"
    token = ctrl.companion.pair_link().split("#pair=")[1]
    try:
        with httpx.Client(base_url=base, headers={"Origin": base}, trust_env=False) as client:
            assert client.post("/pair", json={"token": token}).status_code == 200
            cookie = "companion=" + client.cookies.get("companion")
        async def verify():
            async with connect(f"ws://127.0.0.1:{mobile_port}/ws", origin=base, additional_headers={"Cookie": cookie}, proxy=None) as ws:
                await ws.recv()
                ctrl.recognized("我认为这个方法可行")
                await asyncio.sleep(.1)
                assert not requests
                ctrl.recognized("请解释什么是闭环控制")
                ctrl.recognized("请解释什么是闭环控制？")  # mixed-lane duplicate
                seen = []
                while True:
                    state = json.loads(await asyncio.wait_for(ws.recv(), 3))
                    if state["history"]:
                        last = state["history"][-1]
                        seen.append(last["answer"])
                        if last["status"] == "done":
                            assert last["answer"] == "自动回答测试"
                            break
                assert any(x == "自动" for x in seen)
                assert len(requests) == 1
            async with connect(f"ws://127.0.0.1:{mobile_port}/ws", origin=base, additional_headers={"Cookie": cookie}, proxy=None) as ws:
                restored = json.loads(await ws.recv())
                assert restored["history"][-1]["answer"] == "自动回答测试"
        asyncio.run(verify())
    finally:
        ctrl.close()
        server.should_exit = True
        thread.join(4)
    assert not thread.is_alive()
    assert not ctrl.thread.is_alive()
