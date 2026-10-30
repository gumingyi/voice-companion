import json
import sys
import time
from types import SimpleNamespace
from threading import Event
from assistant_app.audio import AudioEngine
from assistant_app.settings import defaults, ConfigStore
from assistant_app import companion

def test_old_settings_migrate_to_manual(tmp_path):
    c = defaults()
    c["version"] = 1
    c["audio"].pop("manual_capture")
    c["audio"]["auto_submit"] = True
    store = ConfigStore(tmp_path)
    store.path.write_text(json.dumps(c), encoding="utf-8")
    loaded = store.load()
    assert loaded["audio"]["manual_capture"]
    assert not loaded["audio"]["auto_submit"]
    assert loaded["providers"] == c["providers"]

def test_pause_flushes_manual_speech_only_once(monkeypatch):
    ready, received = Event(), Event()
    texts, calls = [], []
    class Stream:
        def is_active(self): return False
        def close(self): pass
    class PyAudio:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get_default_wasapi_loopback(self):
            return {"maxInputChannels": 1, "defaultSampleRate": 16000, "index": 1, "isLoopbackDevice": True, "name": "fixture"}
        def open(self, **kwargs):
            # 800ms of voiced PCM, below max-segment limit, no trailing silence.
            for _ in range(16):
                kwargs["stream_callback"](b'\xe8\x03' * 800, 800, {}, 0)
            ready.set()
            return Stream()
    def transcribe(pcm):
        calls.append(len(pcm))
        return "暂停后转写"
    def on_text(text):
        texts.append(text)
        received.set()
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(PyAudio=PyAudio, paInt16=8, paComplete=1, paContinue=0))
    engine = AudioEngine(lambda: SimpleNamespace(transcribe=transcribe), on_text, lambda _: None, lambda *_: None)
    try:
        engine.start(defaults()["audio"])
        assert ready.wait(2)
        time.sleep(.15)
        assert not calls
        engine.pause(True)
        assert received.wait(2)
        until = time.monotonic() + 2
        while not engine.settled and time.monotonic() < until:
            time.sleep(.01)
        assert engine.settled and texts == ["暂停后转写"]
        engine.pause(True)
        time.sleep(.1)
        assert len(calls) == 1
    finally:
        assert engine.stop()

def test_preferred_address_excludes_loopback(monkeypatch):
    monkeypatch.setattr(companion, "local_addresses", lambda: ["127.0.0.1", "192.168.43.3"])
    assert companion.preferred_address() == "192.168.43.3"
