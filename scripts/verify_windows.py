"""Explicit integration check: plays a synthetic Chinese fixture on default output.
Captures system playback only; it does not open the microphone or contact an LLM.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave
import winsound

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from PySide6.QtWidgets import QApplication
from assistant_app.settings import defaults, ConfigStore
from assistant_app.speech import VoskRecognizer
from assistant_app.controller import Controller
from assistant_app.ui import MainWindow, STYLE
from assistant_app.audio import devices

class NoCredentials:
    def get(self, _): return ""

def main():
    output = ROOT / "docs" / "verification"
    output.mkdir(exist_ok=True)
    fixture = output / "synthetic_chinese.wav"
    # UTF-16LE BOM lets Windows PowerShell reliably parse Chinese source.
    source = (ROOT / "scripts" / "make_fixture.ps1").read_text(encoding="utf-8-sig")
    generated = output / "make_fixture.generated.ps1"
    generated.write_text(source, encoding="utf-16")
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(generated), "-OutputPath", str(fixture)], check=True, capture_output=True)
    generated.unlink()
    result = {"fixture": "Windows Microsoft Huihui Desktop TTS, synthetic Chinese speech", "devices": devices()}
    manual = "--manual" in sys.argv
    result["capture_mode"] = "manual" if manual else "continuous"
    recognizer = VoskRecognizer(str(ROOT / "models" / "vosk-model-small-cn-0.22"))
    with wave.open(str(fixture), "rb") as w:
        result["file_asr"] = recognizer.transcribe(w.readframes(w.getnframes()), w.getframerate())
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    config = defaults()
    config["audio"]["auto_submit"] = False
    config["audio"]["manual_capture"] = manual
    config["audio"]["live_transcription"] = False
    config["audio"]["answer_on_pause"] = False
    config["audio"]["rms_threshold"] = 150
    config["audio"]["model_path"] = str(ROOT / "models" / "vosk-model-small-cn-0.22")
    ctrl = Controller(config, ConfigStore(output / "test_data"), NoCredentials())
    # Reuse already loaded model for deterministic warm start.
    ctrl.audio.factory = lambda: recognizer
    statuses, texts, levels = [], [], []
    ctrl.events.transcript.connect(texts.append)
    ctrl.events.level.connect(lambda mode, value: levels.append(value))
    ctrl.events.snapshot.connect(lambda s: statuses.append(s["status"]))
    window = MainWindow(ctrl)
    try:
        window.show()
        for _ in range(10):
            app.processEvents()
            time.sleep(.03)
        window.grab().save(str(output / "desktop.png"))
        ctrl.audio.start(config["audio"])
        until = time.monotonic() + 6
        while not ctrl.audio.streams and time.monotonic() < until:
            app.processEvents()
            time.sleep(.03)
        result["loopback_opened"] = bool(ctrl.audio.streams)
        window.showMinimized()
        app.processEvents()
        result["minimized_stream_active"] = window.isMinimized() and bool(ctrl.audio.streams)
        player = threading.Thread(target=lambda: winsound.PlaySound(str(fixture), winsound.SND_FILENAME))
        player.start()
        until = time.monotonic() + 30
        while player.is_alive() and time.monotonic() < until:
            app.processEvents()
            time.sleep(.03)
        if manual:
            result["no_transcription_before_pause"] = not texts
            ctrl.audio.pause(True)
        while not texts and time.monotonic() < until:
            app.processEvents()
            time.sleep(.03)
        for _ in range(120):
            app.processEvents()
            time.sleep(.03)
        ctrl.audio.pause(True)
        result["paused"] = ctrl.audio.paused.is_set()
        ctrl.audio.pause(False)
        result["resumed"] = not ctrl.audio.paused.is_set()
        stopping = time.monotonic()
        result["stopped"] = ctrl.audio.stop()
        result["stop_seconds"] = round(time.monotonic() - stopping, 3)
        result["streams_released"] = not ctrl.audio.streams
        result["max_rms"] = max(levels, default=0)
        result["loopback_transcripts"] = texts
        result["statuses"] = list(dict.fromkeys(statuses))
        # Reopen same real device after stop to prove the handle is reusable.
        ctrl.audio.start(config["audio"])
        until = time.monotonic() + 5
        while not ctrl.audio.streams and time.monotonic() < until:
            app.processEvents()
            time.sleep(.03)
        result["device_reopened"] = result["stopped"] and bool(ctrl.audio.streams)
        stopping = time.monotonic()
        result["quiet_stop_released"] = ctrl.audio.stop() and not ctrl.audio.streams
        result["quiet_stop_seconds"] = round(time.monotonic() - stopping, 3)
    finally:
        window.close()
        app.processEvents()
    result["model_loop_stopped"] = not ctrl.thread.is_alive()
    (output / ("windows_manual_result.json" if manual else "windows_result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if not (result["file_asr"] and result["loopback_transcripts"] and result["streams_released"] and result["device_reopened"]):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
