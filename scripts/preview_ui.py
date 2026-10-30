"""Render real Qt screens for visual QA. Content is explicitly a layout fixture;
no audio is captured, no API requests and no user credential reads are made.
"""
from pathlib import Path
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from PySide6.QtWidgets import QApplication
from assistant_app.settings import defaults, ConfigStore
from assistant_app.controller import Controller
from assistant_app.ui import MainWindow, SettingsDialog, STYLE

class NoKeys:
    def get(self, _): return ""

def main():
    out = ROOT / "docs" / "verification" / "ui"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    c = defaults()
    ctrl = Controller(c, ConfigStore(out / "preview_data"), NoKeys())
    window = MainWindow(ctrl)
    def settle():
        for _ in range(10):
            app.processEvents()
            time.sleep(.02)
    report = {"content": "explicit UI layout fixture; no API or audio", "sizes": []}
    try:
        window.show()
        settle()
        window.grab().save(str(out / "desktop_empty.png"))
        fixture = [
            {"id": "preview-1", "question": "为什么需要分别研究局部控制和整体协调？", "answer": "【界面预览示例】局部控制与整体协调关注的问题不同。", "status": "done", "model": "界面预览示例", "elapsed": 0, "usage": {}},
            {"id": "preview-2", "question": "控制方法的效果应该如何验证？", "answer": "【界面预览示例】可通过统一工况的对照实验和消融分析检验。", "status": "done", "model": "界面预览示例", "elapsed": 0, "usage": {}},
            {"id": "preview-3", "question": "请解释分层控制的研究思路，以及如何验证其效果。", "answer": "【界面预览示例】\n\n分层控制将局部调节和整体协调分开设计，使各层处理适合自身时间尺度的任务。\n\n在这个研究方案中，下层维持各火道温度闭环，上层以较慢周期协调火道组，减少局部调节之间的相互干扰。协调指令仍需经过约束检查。\n\n验证时，可以在相同扰动和模型失配条件下，与独立控制、固定规则协同方法比较，观察火道间温差、跟踪误差和阀门动作量。\n\n这些属于拟研究与验证的思路，不能代替实际实验结论。", "status": "done", "model": "界面预览示例", "elapsed": 0, "usage": {}},
        ]
        window.question.setPlainText(fixture[-1]["question"])
        window.render({"status": "界面预览 · 此处为布局示例内容，未调用模型", "history": fixture, "transcript": fixture[-1]["question"]})
        for width, height, name in [(1180, 780, "desktop_answer.png"), (980, 680, "desktop_compact.png"), (960, 660, "desktop_minimum.png"), (1440, 900, "desktop_wide.png")]:
            window.resize(width, height)
            settle()
            root_rect = window.centralWidget().rect()
            bounds = {}
            for key, widget in [("listen", window.listen_button), ("question", window.question), ("answer", window.answer_stack), ("model", window.model), ("template", window.template), ("background", window.background)]:
                point = widget.mapTo(window.centralWidget(), widget.rect().topLeft())
                bounds[key] = {"x": point.x(), "y": point.y(), "w": widget.width(), "h": widget.height(), "inside": root_rect.contains(point) and root_rect.contains(point.x() + widget.width() - 1, point.y() + widget.height() - 1)}
            report["sizes"].append({"requested": [width, height], "actual": [window.width(), window.height()], "controls": bounds})
            window.metrics.setText("界面预览示例 · 展示文字排版与布局，未调用模型接口")
            window.grab().save(str(out / name))
        settings = SettingsDialog(window)
        settings.show()
        settle()
        settings.grab().save(str(out / "settings_models.png"))
        settings.tabs.setCurrentIndex(1)
        settle()
        settings.grab().save(str(out / "settings_audio.png"))
        settings.reject()
    finally:
        window.close()
    (out / "layout_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert all(control["inside"] for entry in report["sizes"] for control in entry["controls"].values())
    print(json.dumps({"screens": 7, "all_major_controls_inside": True, "actual_sizes": [e["actual"] for e in report["sizes"]]}))

if __name__ == "__main__":
    main()
