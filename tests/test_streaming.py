import asyncio
import json
import sys
import time
from types import SimpleNamespace
from threading import Event
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from assistant_app.settings import defaults, ConfigStore
from assistant_app.controller import Controller
from assistant_app.live_audio import StreamingAudioEngine, merge_sources

class Keys:
    def get(self, _): return "test-only"

def spin(app, condition, timeout=4):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        app.processEvents()
        if condition(): return
        time.sleep(.01)
    raise AssertionError("timed out")

def test_stream_preview_is_replaced_and_never_submitted(tmp_path):
    app = QApplication.instance() or QApplication([])
    ctrl = Controller(defaults(), ConfigStore(tmp_path), Keys())
    calls, shown = [], []
    ctrl.submit = calls.append
    ctrl.events.transcript.connect(shown.append)
    try:
        ctrl.preview("史密斯 预")
        ctrl.preview("史密斯 预估")
        app.processEvents()
        assert ctrl.transcript == ""
        assert shown[-1] == "Smith预估"
        assert "预\n" not in shown[-1]
        assert not calls and not ctrl.history
        ctrl.recognized("史密斯 预估")
        app.processEvents()
        assert ctrl.transcript == "Smith预估"
        assert ctrl.preview_text == ""
    finally:
        ctrl.close()

def test_streaming_capture_decodes_before_pause_and_keeps_tail(monkeypatch):
    ready, preview, final = Event(), Event(), Event()
    callback_holder, finals = [], []
    class Session:
        def feed(self, pcm):
            return "正在识别"
        def finish(self):
            return "正在识别完整尾句"
    class Stream:
        def close(self): pass
    class PyAudio:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get_default_wasapi_loopback(self):
            return {"maxInputChannels": 1, "defaultSampleRate": 16000, "index": 1, "isLoopbackDevice": True, "name": "fixture"}
        def open(self, **kwargs):
            callback_holder.append(kwargs["stream_callback"])
            ready.set()
            return Stream()
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(PyAudio=PyAudio, paInt16=8, paContinue=0, paComplete=1))
    def on_final(text):
        finals.append(text)
        final.set()
    engine = StreamingAudioEngine(lambda: SimpleNamespace(streaming_session=Session), on_final, lambda _: None, lambda *_: None, on_partial=lambda t: preview.set() if t else None)
    try:
        engine.start(defaults()["audio"])
        assert ready.wait(2)
        for _ in range(16):
            callback_holder[0](b'\xe8\x03' * 800, 800, {}, 0)
        assert preview.wait(2)
        assert not engine.paused.is_set() and not finals
        engine.pause(True)
        assert final.wait(2)
        until = time.monotonic() + 2
        while not engine.settled and time.monotonic() < until:
            time.sleep(.01)
        assert engine.settled and finals == ["正在识别完整尾句"]
        engine.pause(False)
        for _ in range(16):
            callback_holder[0](b'\xe8\x03' * 800, 800, {}, 0)
        engine.pause(True)
        until = time.monotonic() + 2
        while len(finals) < 2 and time.monotonic() < until:
            time.sleep(.01)
        assert len(finals) == 2
    finally:
        assert engine.stop()

def test_end_capture_auto_answer_once_after_final_text(tmp_path):
    from assistant_app.ui import MainWindow
    app = QApplication.instance() or QApplication([])
    ctrl = Controller(defaults(), ConfigStore(tmp_path), Keys())
    class FakeAudio:
        running = True
        settled = False
        streams = []
        session_error = False
        paused = Event()
        def pause(self, value):
            if value: self.paused.set()
        def stop(self): return True
    ctrl.audio = FakeAudio()
    calls = []
    ctrl.submit = calls.append
    window = MainWindow(ctrl)
    try:
        window.question.setPlainText("临时字")
        window.toggle_listen()
        assert ctrl.audio.paused.is_set() and not calls
        def finish():
            ctrl.events.transcript.emit("最后确认的完整问题")
            ctrl.audio.settled = True
        QTimer.singleShot(150, finish)
        spin(app, lambda: bool(calls))
        for _ in range(30):
            app.processEvents()
            time.sleep(.01)
        assert calls == ["最后确认的完整问题"]
    finally:
        window.close()

def test_blank_end_does_not_submit_old_preview(tmp_path):
    from assistant_app.ui import MainWindow
    app = QApplication.instance() or QApplication([])
    ctrl = Controller(defaults(), ConfigStore(tmp_path), Keys())
    calls = []
    ctrl.submit = calls.append
    window = MainWindow(ctrl)
    try:
        window.question.clear()
        window._send_question()
        assert not calls
    finally:
        window.close()

def test_old_settings_enable_live_on_upgrade(tmp_path):
    c = defaults()
    c["version"] = 2
    for k in ("live_transcription", "answer_on_pause", "term_replacements"):
        c["audio"].pop(k)
    store = ConfigStore(tmp_path)
    store.path.write_text(json.dumps(c), encoding="utf-8")
    loaded = store.load()
    assert loaded["version"] == 4
    assert loaded["audio"]["live_transcription"] and loaded["audio"]["answer_on_pause"]

def test_merge_two_sources_keeps_one_echo():
    assert merge_sources(["请介绍模型预测控制", "请介绍模型预测控制？"]).count("模型预测控制") == 1
    assert "为什么" in merge_sources(["模型预测控制", "为什么"])
