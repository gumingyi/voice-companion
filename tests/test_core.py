import asyncio
import copy
import json
import struct
import sys
import time
from types import SimpleNamespace
import pytest
import httpx
from assistant_app.audio import Segmenter
from assistant_app.questions import normalize, is_question, Deduplicator
from assistant_app.settings import defaults, validate, ConfigStore
from assistant_app.prompts import assemble, read_material
from assistant_app.providers import OpenAICompatible, ProviderError
from assistant_app.hotkeys import parse_hotkey

def test_quiet_callback_capture_can_stop(monkeypatch):
    from assistant_app.audio import AudioEngine
    closed = []
    class Stream:
        def is_active(self): return False
        def close(self): closed.append(True)
        def read(self, *args, **kwargs): raise AssertionError("Blocking read must never be used")
    class PyAudio:
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def get_default_wasapi_loopback(self):
            return {"maxInputChannels": 2, "defaultSampleRate": 48000, "index": 1, "isLoopbackDevice": True, "name": "test output"}
        def open(self, **kwargs):
            assert callable(kwargs["stream_callback"])
            self.stream = Stream()
            return self.stream
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(PyAudio=PyAudio, paInt16=8, paComplete=1, paContinue=0))
    engine = AudioEngine(lambda: SimpleNamespace(transcribe=lambda _: ""), lambda _: None, lambda _: None, lambda *_: None)
    engine.start(defaults()["audio"])
    until = time.monotonic() + 2
    while not engine.streams and time.monotonic() < until:
        time.sleep(.01)
    assert engine.streams
    started = time.monotonic()
    assert engine.stop()
    assert time.monotonic() - started < 1
    assert closed and not engine.streams and not engine.running

@pytest.mark.parametrize("text,context,expected", [
    ("什么是模型预测控制", False, True), ("请介绍你的课题创新点", False, True),
    ("我认为这个方案可以采用", False, False), ("谢谢大家", False, False),
    ("为什么", False, False), ("为什么", True, True), ("继续解释", True, True),
    ("具体怎么实现", True, True), ("我不知道为什么系统报错", False, False),
    ("你好", False, False), ("能否解释稳定性条件", False, True)])
def test_questions(text, context, expected):
    assert is_question(text, context) is expected

def test_dedup():
    assert normalize("什 么 是 控 制 工 程") == "什么是控制工程"
    d = Deduplicator()
    assert not d.duplicate("什么是模型预测控制", 1)
    assert d.duplicate("什么是模型预测控制？", 2)
    assert not d.duplicate("什么是模型预测控制", 20)

def test_vad():
    vad = Segmenter(silence_ms=200, min_speech_ms=100)
    silent = bytes(1600)
    loud = struct.pack("<h", 1000) * 800
    for _ in range(5):
        assert vad.feed(silent) is None
    assert vad.feed(loud) is None
    assert vad.feed(loud) is None
    for _ in range(3):
        assert vad.feed(silent) is None
    assert len(vad.feed(silent)) > 3200
    assert vad.feed(silent) is None
    vad.feed(loud)
    for _ in range(4):
        assert vad.feed(silent) is None  # rejects <100ms speech

def test_bounded_segment():
    vad = Segmenter(max_segment_ms=100, min_speech_ms=50)
    pcm = struct.pack("<h", 1000) * 800
    assert vad.feed(pcm) is None
    assert vad.feed(pcm)

def test_prompt_budget_and_material(tmp_path):
    c = defaults()
    t = c["templates"][0]
    messages = assemble(t, "为什么", [{"question": "什么是控制", "answer": "控制是…", "status": "done"}], "已读资料", 1000)
    assert "已读资料" in messages[0]["content"]
    assert messages[1]["content"] == "什么是控制"
    with pytest.raises(ValueError):
        assemble(t, "q", [], "很长" * 1000, 500)
    t = copy.deepcopy(t)
    t["system"] += "{unknown}"
    with pytest.raises(ValueError):
        assemble(t, "q", [], "", 1000)
    path = tmp_path / "b.txt"
    path.write_text("实际材料", encoding="utf-8")
    assert read_material(path) == "实际材料"

def test_config_and_hotkeys(tmp_path):
    c = defaults()
    assert validate(c)
    store = ConfigStore(tmp_path)
    store.save(c)
    assert store.load() == c
    assert "api_key" not in store.path.read_text(encoding="utf-8")
    assert parse_hotkey("ctrl+alt+enter") == (3, 13)
    for mutate in [lambda x: x["mobile"].update(host="0.0.0.0"), lambda x: x["providers"][0].update(api_key="secret"), lambda x: x["hotkeys"].update(submit=x["hotkeys"]["listen"]), lambda x: x["providers"][0].update(base_url="http://example.com"), lambda x: x["providers"][0].update(protocol="anthropic")]:
        bad = copy.deepcopy(c)
        mutate(bad)
        with pytest.raises(ValueError):
            validate(bad)

def provider(handler, retries=0):
    config = defaults()["providers"][0]
    config["retries"] = retries
    return OpenAICompatible(config, "fake-test-key", transport=httpx.MockTransport(handler))

def test_stream_and_usage():
    def handler(request):
        assert request.url.path == "/chat/completions"
        assert json.loads(request.content)["stream"]
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"答案"}}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":8}}\n\ndata: [DONE]\n\n')
    async def run():
        return [x async for x in provider(handler).stream([{"role": "user", "content": "问题"}])]
    result = asyncio.run(run())
    assert next(x["text"] for x in result if "text" in x) == "答案"
    assert next(x["usage"] for x in result if "usage" in x)["total_tokens"] == 8

@pytest.mark.parametrize("code,retryable", [(401, False), (403, False), (404, False), (429, True), (500, True)])
def test_errors_no_secret_echo(code, retryable):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(code, text="fake-test-key")
    async def run():
        return [x async for x in provider(handler, retries=1).stream([])]
    with pytest.raises(ProviderError) as exc:
        asyncio.run(run())
    assert "fake-test-key" not in str(exc.value)
    assert len(calls) == (2 if retryable else 1)

def test_timeout_and_truncation():
    def timeout(request):
        raise httpx.ReadTimeout("fake-test-key")
    async def run(p):
        return [x async for x in p.stream([])]
    with pytest.raises(ProviderError, match="超时"):
        asyncio.run(run(provider(timeout)))
    with pytest.raises(ProviderError, match="中断"):
        asyncio.run(run(provider(lambda r: httpx.Response(200, text='data: {"choices":[{"delta":{"content":"一半"}}]}\n\n'))))

def test_model_list():
    result = asyncio.run(provider(lambda r: httpx.Response(200, json={"data": [{"id": "deepseek-flash"}]})).models())
    assert result == ["deepseek-flash"]
