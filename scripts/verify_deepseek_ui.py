"""One small real official DeepSeek request, using existing local credentials.
Persists timings/counts only. Does not save or print prompts, answers or API keys.
"""
from pathlib import Path
import copy
import json
import os
import sys
import time
from urllib.parse import urlsplit
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from PySide6.QtWidgets import QApplication
from assistant_app.settings import ConfigStore, Credentials
from assistant_app.controller import Controller
from assistant_app.ui import MainWindow

def main():
    c = copy.deepcopy(ConfigStore().load())
    p = next(p for p in c["providers"] if p["id"] == c["default_provider"])
    if urlsplit(p["base_url"]).hostname != "api.deepseek.com":
        raise SystemExit("Official endpoint required")
    p["max_tokens"] = min(p["max_tokens"], 256)
    c["save_history"] = False
    c["fast_answers"] = True
    output = ROOT / "docs" / "verification"
    output.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    ctrl = Controller(c, ConfigStore(output / "latency_test_data"), Credentials())
    window = MainWindow(ctrl)
    result = {"real_api": True, "diagnostic_max_tokens": p["max_tokens"], "content_saved": False}
    submitted = time.monotonic()
    first_visible = None
    try:
        window.question.setPlainText("请只用两句话解释闭环控制的基本原理。")
        window.submit()
        until = time.monotonic() + 50
        while time.monotonic() < until:
            app.processEvents()
            if window.answer.toPlainText() and first_visible is None:
                first_visible = time.monotonic()
            if ctrl.history and ctrl.history[-1]["status"] in ("done", "error"):
                app.processEvents()
                break
            time.sleep(.002)
        entry = ctrl.history[-1]
        result.update(status=entry["status"], timings=entry.get("timings", {}), answer_chars=len(entry["answer"]))
        result["submit_to_visible_seconds"] = round(first_visible - submitted, 3) if first_visible else None
        if first_visible and entry["timings"].get("submit_to_first_token") is not None:
            result["first_token_to_ui_seconds"] = round(first_visible - submitted - entry["timings"]["submit_to_first_token"], 3)
        assert entry["status"] == "done" and first_visible
    finally:
        window.close()
    result["resources_closed"] = not ctrl.thread.is_alive() and (ctrl.client is None or ctrl.client.is_closed)
    (output / "deepseek_ui_latency.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))

if __name__ == "__main__":
    main()
