import asyncio
import json
import os
import time
import uuid
import pytest
from PySide6.QtWidgets import QApplication
from assistant_app.settings import defaults, ConfigStore, Credentials
from assistant_app.controller import Controller

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

class MemoryKeys:
    def get(self, _): return "test-key"

def wait_until(app, predicate, timeout=5):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        app.processEvents()
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("condition timed out")

def test_controller_stream_cancel_fallback_and_clear(app, tmp_path, monkeypatch):
    from assistant_app import controller as module
    c = defaults()
    c["fallback_provider"] = "backup"
    c["providers"].append({**c["providers"][0], "id": "backup", "name": "Backup"})
    class FakeProvider:
        def __init__(self, pid): self.pid = pid
        async def stream(self, messages):
            from assistant_app.providers import ProviderError
            if self.pid == "deepseek":
                raise ProviderError("test fail")
            for text in ["真实", "链路"]:
                await asyncio.sleep(.08)
                yield {"text": text}
    monkeypatch.setattr(module, "adapter", lambda p, _, **kwargs: FakeProvider(p["id"]))
    ctrl = Controller(c, ConfigStore(tmp_path), MemoryKeys())
    try:
        ctrl.submit("什么是测试")
        wait_until(app, lambda: ctrl.history and ctrl.history[-1]["status"] == "done")
        assert ctrl.history[-1]["answer"] == "真实链路"
        assert "Backup" in ctrl.history[-1]["model"]
        ctrl.submit("第二个问题是什么")
        wait_until(app, lambda: len(ctrl.history) == 2 and ctrl.history[-1]["answer"])
        ctrl.cancel()
        wait_until(app, lambda: ctrl.history[-1]["status"] == "cancelled")
        ctrl.clear()
        wait_until(app, lambda: not ctrl.history)
        assert not (tmp_path / "history.json").exists()
    finally:
        ctrl.close()
    assert not ctrl.thread.is_alive()

def test_windows_credentials_round_trip():
    keys = Credentials()
    pid = "test-" + uuid.uuid4().hex
    try:
        keys.set(pid, "temporary-test-credential")
        assert keys.get(pid) == "temporary-test-credential"
    finally:
        keys.set(pid, "")
    assert keys.get(pid) == ""

def test_native_hotkeys_conflict_delivery_release():
    import ctypes
    from threading import Event
    from assistant_app.hotkeys import Hotkeys
    received = Event()
    first = Hotkeys(lambda action: received.set() if action == "submit" else None, lambda _: None)
    second = Hotkeys(lambda _: None, lambda _: None)
    try:
        chosen = None
        for number in range(13, 25):
            try:
                chosen = f"CTRL+SHIFT+ALT+F{number}"
                first.configure({"submit": chosen})
                break
            except ValueError:
                chosen = None
        assert chosen is not None, "No free native hotkey available for integration test"
        with pytest.raises(ValueError, match="占用"):
            second.configure({"submit": chosen})
        # Native Windows message path, with no synthetic keypress in other apps.
        assert ctypes.windll.user32.PostThreadMessageW(first.thread.native_id, 0x0312, 1, 0)
        assert received.wait(2)
        first.stop()
        second.configure({"submit": chosen})
    finally:
        first.stop()
        second.stop()

def test_window_templates_and_minimize(app, tmp_path):
    from assistant_app.ui import MainWindow, SettingsDialog
    ctrl = Controller(defaults(), ConfigStore(tmp_path), MemoryKeys())
    window = MainWindow(ctrl)
    try:
        window.show()
        app.processEvents()
        assert window.template.count() == 6
        window.template.setCurrentIndex(2)
        assert ctrl.config["template"] == "scene-2"
        dialog = SettingsDialog(window)
        dialog.templates.duplicate()
        assert len(dialog.templates.entries) == 7
        dialog.templates.fields["name"].setText("自建模板")
        dialog.save()
        assert ctrl.config["templates"][-1]["name"] == "自建模板"
        window.showMinimized()
        app.processEvents()
        assert window.isMinimized()
        assert ctrl.thread.is_alive()
        window.showNormal()
        app.processEvents()
        out = tmp_path / "desktop.png"
        assert window.grab().save(str(out))
    finally:
        window.close()
        app.processEvents()
    assert not ctrl.thread.is_alive()

def test_generate_shortcut_pauses_and_waits_for_last_transcript(app, tmp_path):
    from threading import Event
    from PySide6.QtCore import QTimer
    from assistant_app.ui import MainWindow
    ctrl = Controller(defaults(), ConfigStore(tmp_path), MemoryKeys())
    class FakeAudio:
        running = True
        settled = False
        streams = []
        paused = Event()
        def pause(self, value):
            if value: self.paused.set()
        def stop(self): return True
    ctrl.audio = FakeAudio()
    calls = []
    ctrl.submit = calls.append
    window = MainWindow(ctrl)
    try:
        window.question.setPlainText("旧文字")
        window.hotkey("submit")
        window.hotkey("submit")
        assert ctrl.audio.paused.is_set() and not calls
        def final_text():
            ctrl.events.transcript.emit("最后一段完整问题")
            ctrl.audio.settled = True
        QTimer.singleShot(150, final_text)
        wait_until(app, lambda: bool(calls))
        assert calls == ["最后一段完整问题"]
    finally:
        window.close()
