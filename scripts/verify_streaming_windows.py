"""Real WASAPI + Vosk streaming + Qt end-key + local HTTP test model.
Timing applies to the local fixture service, not DeepSeek network/model latency.
"""
from pathlib import Path
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import winsound

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from PySide6.QtWidgets import QApplication
import uvicorn
from assistant_app.settings import defaults, ConfigStore
from assistant_app.speech import VoskRecognizer
from assistant_app.controller import Controller
from assistant_app.ui import MainWindow, STYLE

class Keys:
    def get(self, _): return "fixture-only"

def main():
    output = ROOT / "docs" / "verification"
    output.mkdir(exist_ok=True)
    fixture = output / "synthetic_chinese.wav"
    if not fixture.exists():
        generated = output / "make_fixture.generated.ps1"
        generated.write_text((ROOT / "scripts" / "make_fixture.ps1").read_text(encoding="utf-8-sig"), encoding="utf-16")
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(generated), "-OutputPath", str(fixture)], check=True, capture_output=True)
        generated.unlink()
    result = {"audio": "explicit Windows Huihui synthetic Chinese fixture", "model": "local HTTP SSE fixture; no DeepSeek call", "previews": []}
    requests = []
    api = FastAPI()
    @api.post("/chat/completions")
    async def chat(request: Request):
        data = await request.json()
        requests.append({"at": time.monotonic(), "question": data["messages"][-1]["content"]})
        async def body():
            for text in ["【本地测试夹具】", "实时转写结束后", "已自动发起回答。"]:
                yield "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n"
                await asyncio.sleep(.1)
            yield "data: [DONE]\n\n"
        return StreamingResponse(body(), media_type="text/event-stream")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api, host="127.0.0.1", port=port, log_level="critical", log_config=None, access_log=False))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    config = defaults()
    config["audio"]["rms_threshold"] = 150
    config["providers"][0].update(base_url=f"http://127.0.0.1:{port}", model="fixture-stream", name="本地测试夹具")
    ctrl = Controller(config, ConfigStore(output / "streaming_test_data"), Keys())
    model_ready = threading.Event()
    def factory():
        started = time.monotonic()
        model = VoskRecognizer(config["audio"]["model_path"])
        result["model_load_seconds"] = round(time.monotonic() - started, 3)
        model_ready.set()
        return model
    ctrl.audio.factory = factory
    window = MainWindow(ctrl)
    snapshots = []
    ctrl.events.transcript.connect(lambda text: result["previews"].append({"at": time.monotonic(), "text": text}))
    ctrl.events.snapshot.connect(lambda s: snapshots.append((time.monotonic(), s)))
    def wait(condition, seconds=15):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.processEvents()
            if condition(): return
            time.sleep(.01)
        raise AssertionError("Integration wait timed out")
    try:
        wait(lambda: server.started)
        window.show()
        window.toggle_listen()
        wait(lambda: bool(ctrl.audio.streams) and model_ready.is_set())
        result["model_ready_before_test_playback"] = True
        started = time.monotonic()
        player = threading.Thread(target=lambda: winsound.PlaySound(str(fixture), winsound.SND_FILENAME))
        player.start()
        wait(lambda: not player.is_alive(), 25)
        played_until = time.monotonic()
        result["preview_before_capture_end"] = any(p["text"] and p["at"] < played_until for p in result["previews"])
        result["requests_before_end"] = len(requests)
        paused_at = time.monotonic()
        window.toggle_listen()  # Same path as Ctrl+Alt+L, including auto answer.
        wait(lambda: ctrl.history and ctrl.history[-1]["status"] == "done")
        result["final_transcript"] = ctrl.transcript
        result["request_count"] = len(requests)
        result["submitted_question"] = requests[0]["question"]
        result["end_to_http_request_seconds"] = round(requests[0]["at"] - paused_at, 3)
        first_answer = next(t for t, s in snapshots if s["history"] and s["history"][-1]["answer"])
        result["end_to_first_fixture_answer_seconds"] = round(first_answer - paused_at, 3)
        result["first_preview_seconds"] = round(next(p["at"] for p in result["previews"] if p["text"]) - started, 3)
        result["preview_updates"] = len(result["previews"])
        result["previews"] = [p["text"] for p in result["previews"]]
        result["paused_after_answer"] = ctrl.audio.paused.is_set()
        window.grab().save(str(output / "streaming_desktop.png"))
        assert result["preview_before_capture_end"]
        assert not result["requests_before_end"]
        assert result["request_count"] == 1
        assert "闭环控制" in result["final_transcript"]
        assert "闭环控制" in result["submitted_question"]
    finally:
        window.close()
        server.should_exit = True
        server_thread.join(4)
    result["audio_released"] = not ctrl.audio.streams and not ctrl.audio.running
    result["model_thread_stopped"] = not ctrl.thread.is_alive()
    (output / "streaming_windows_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))

if __name__ == "__main__":
    main()
