import copy
import io
import json
from pathlib import Path
import threading
import time
import sys
import subprocess
import ctypes
import uuid

from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QFont, QPixmap, QIcon, QAction, QDesktopServices, QTextCursor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QPlainTextEdit, QComboBox, QSplitter, QListWidget, QCheckBox,
    QDialog, QDialogButtonBox, QTabWidget, QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
    QMessageBox, QFileDialog, QProgressBar, QSystemTrayIcon, QMenu, QStyle, QScrollArea,
    QFrame, QSizePolicy, QListWidgetItem, QStackedWidget)
from .settings import validate, defaults
from .audio import devices
from .hotkeys import Hotkeys
from .companion import local_addresses, preferred_address
from .prompts import read_material
from .theme import STYLE, ui_icon

def button(text, slot, layout, role="secondary", icon=None):
    widget = QPushButton(text)
    widget.setProperty("role", role)
    widget.setCursor(Qt.PointingHandCursor)
    if icon:
        widget.setIcon(ui_icon(icon, "#ffffff" if role == "primary" else "#728396"))
        widget.setIconSize(QSize(17, 17))
    widget.clicked.connect(slot)
    layout.addWidget(widget)
    return widget

def text_label(text, role="muted"):
    widget = QLabel(text)
    widget.setProperty("textRole", role)
    return widget

def surface(name):
    widget = QFrame()
    widget.setObjectName(name)
    widget.setProperty("surface", True)
    return widget

def error(parent, text):
    QMessageBox.warning(parent, "操作提示", text)

class ListEditor(QWidget):
    """Editable collections with explicit fields, portable JSON import/export."""
    def __init__(self, entries, schema, prototype, parent=None):
        super().__init__(parent)
        self.entries = copy.deepcopy(entries)
        self.schema, self.prototype, self.current = schema, prototype, -1
        root = QVBoxLayout(self)
        self.select = QComboBox()
        root.addWidget(self.select)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(20)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.fields = {}
        for name, label, kind in schema:
            if kind == "bool":
                field = QCheckBox()
            elif kind in ("text", "json"):
                field = QPlainTextEdit()
                field.setMinimumHeight(75)
            else:
                field = QLineEdit()
            if name == "id":
                field.setReadOnly(True)
            self.fields[name] = field
            form.addRow(label, field)
        root.addLayout(form)
        row = QHBoxLayout()
        button("新建", self.add, row)
        button("复制", self.duplicate, row)
        button("删除", self.delete, row)
        button("导入 JSON", self.import_json, row)
        button("导出 JSON", self.export_json, row)
        root.addLayout(row)
        self.select.currentIndexChanged.connect(self.choose)
        self.reload()

    def commit(self):
        if not 0 <= self.current < len(self.entries):
            return
        values = {}
        for name, _, kind in self.schema:
            field = self.fields[name]
            value = field.isChecked() if kind == "bool" else field.toPlainText() if kind in ("text", "json") else field.text()
            if kind in ("int", "float", "json"):
                try:
                    value = {"int": int, "float": float, "json": json.loads}[kind](value)
                except (ValueError, TypeError):
                    raise ValueError(name + " 的格式不正确") from None
            values[name] = value
        self.entries[self.current].update(values)

    def reload(self, index=0):
        self.select.blockSignals(True)
        self.select.clear()
        for entry in self.entries:
            self.select.addItem(entry["name"] + " [" + entry["id"] + "]")
        self.current = -1
        self.select.setCurrentIndex(index)
        self.select.blockSignals(False)
        self.choose(index)

    def choose(self, index):
        try:
            self.commit()
        except ValueError as exc:
            self.select.blockSignals(True)
            self.select.setCurrentIndex(self.current)
            self.select.blockSignals(False)
            error(self, str(exc))
            return
        self.current = index
        if index < 0:
            return
        entry = self.entries[index]
        for name, _, kind in self.schema:
            value = entry.get(name, "")
            field = self.fields[name]
            if kind == "bool":
                field.setChecked(bool(value))
            elif kind in ("text", "json"):
                field.setPlainText(json.dumps(value, ensure_ascii=False, indent=2) if kind == "json" else str(value))
            else:
                field.setText(str(value))

    def add(self):
        try:
            self.commit()
            entry = copy.deepcopy(self.prototype)
            entry["id"] = uuid.uuid4().hex
            entry["name"] = "新配置"
            self.entries.append(entry)
            self.reload(len(self.entries) - 1)
        except ValueError as exc:
            error(self, str(exc))

    def duplicate(self):
        try:
            self.commit()
            entry = copy.deepcopy(self.entries[self.current])
            entry["id"] = uuid.uuid4().hex
            entry["name"] += " 副本"
            self.entries.append(entry)
            self.reload(len(self.entries) - 1)
        except ValueError as exc:
            error(self, str(exc))

    def delete(self):
        if len(self.entries) < 2:
            error(self, "至少保留一项")
            return
        del self.entries[self.current]
        self.current = -1
        self.reload()

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入配置（不含密钥）", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.commit()
            incoming = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if not isinstance(incoming, list) or not incoming or len(incoming) > 100:
                raise ValueError("文件应是最多100项的配置数组")
            existing = {x["id"] for x in self.entries}
            for item in incoming:
                if not isinstance(item, dict) or not all(k in item for k, _, _ in self.schema):
                    raise ValueError("导入字段不完整")
                if item["id"] in existing:
                    item["id"] = uuid.uuid4().hex
                existing.add(item["id"])
            self.entries.extend(incoming)
            self.reload()
        except (OSError, ValueError, TypeError) as exc:
            error(self, str(exc))

    def export_json(self):
        try:
            self.commit()
            path, _ = QFileDialog.getSaveFileName(self, "导出配置（不含密钥）", "templates.json", "JSON (*.json)")
            if path:
                Path(path).write_text(json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            error(self, str(exc))

class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.controller = window, window.c
        self.config = copy.deepcopy(self.controller.config)
        c = self.config
        self.setWindowTitle("设置 · 修改后保存生效")
        self.resize(850, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.addWidget(text_label("偏好与配置", "brand"))
        root.addWidget(text_label("模型、音频和个人资料，在这里统一管理。", "subtitle"))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        for provider in c["providers"]:
            provider.setdefault("fast_mode", False)
        self.providers = ListEditor(c["providers"], [("id", "凭据 ID", "str"), ("name", "供应商名称", "str"), ("protocol", "协议（当前仅 openai）", "str"), ("base_url", "API Base URL", "str"), ("model", "模型名", "str"), ("timeout", "超时 / 秒", "float"), ("retries", "流开始前重试次数", "int"), ("max_tokens", "最大输出 tokens", "int"), ("temperature", "Temperature", "float"), ("enabled", "启用", "bool"), ("fast_mode", "快速模式对DeepSeek官方接口关闭思考", "bool"), ("extra", "协议特有参数 JSON", "json")], defaults()["providers"][0])
        provider_page = QWidget()
        pv = QVBoxLayout(provider_page)
        pv.addWidget(QLabel("目前实现 OpenAI 兼容协议；其他厂商需逐一连接测试。复制配置不会复制 Key。"))
        pv.addWidget(self.providers)
        key_row = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("API Key：仅存 Windows 凭据管理器，不回显")
        key_row.addWidget(self.key)
        button("保存 Key", self.save_key, key_row)
        button("删除 Key", self.delete_key, key_row)
        button("测试已保存模型（计费）", self.test_key, key_row)
        pv.addLayout(key_row)
        self.add_tab(provider_page, "模型与凭据")

        audio_page, form = self.form_tab("音频与识别")
        self.mode = QComboBox()
        for label, value in [("系统音频 WASAPI", "system"), ("麦克风", "mic"), ("混合（双路去重）", "mixed")]:
            self.mode.addItem(label, value)
        self.mode.setCurrentIndex(self.mode.findData(c["audio"]["mode"]))
        form.addRow("音频输入", self.mode)
        try:
            available = devices()
        except Exception:
            available = {"system": [], "mic": []}
        self.device_fields = {}
        for kind, label in [("system", "系统输出设备"), ("mic", "麦克风设备")]:
            select = QComboBox()
            select.addItem("Windows 默认设备", None)
            for d in available[kind]:
                select.addItem(d["name"], d["id"])
            select.setCurrentIndex(max(0, select.findData(c["audio"][kind + "_device"])))
            form.addRow(label, select)
            self.device_fields[kind] = select
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        self.model_path = QLineEdit(c["audio"]["model_path"])
        self.model_path.setCursorPosition(0)
        self.model_path.setToolTip(c["audio"]["model_path"])
        model_row.addWidget(self.model_path)
        button("选择模型目录", self.choose_model, model_row)
        form.addRow("本地 Vosk 中文模型", model_row)
        button("中文大模型下载页", lambda: QDesktopServices.openUrl(QUrl("https://alphacephei.com/vosk/models")), model_row)
        form.addRow(QLabel("大模型 vosk-model-cn-0.22 约1.3GB且更占内存；解压后选择模型目录，需自行评测准确率。"))
        self.audio_numbers = {}
        for key, label, lo, hi in [("silence_ms", "静音结束 / 毫秒", 200, 5000), ("min_speech_ms", "最短有效语音 / 毫秒", 100, 5000), ("max_segment_ms", "最长分段 / 毫秒", 5000, 60000), ("rms_threshold", "能量 VAD 阈值（0~32767）", 1, 30000)]:
            field = QSpinBox()
            field.setRange(lo, hi)
            field.setValue(c["audio"][key])
            self.audio_numbers[key] = field
            form.addRow(label, field)
        self.auto_submit = QCheckBox("检测到完整问题后自动回答")
        self.auto_submit.setChecked(c["audio"]["auto_submit"])
        form.addRow(self.auto_submit)
        self.manual_capture = QCheckBox("按快捷键控制每一段收音")
        self.manual_capture.setChecked(c["audio"].get("manual_capture", True))
        form.addRow(self.manual_capture)
        self.live_transcription = QCheckBox("收音时同步识别并显示文字（推荐；关闭则暂停后整段转写）")
        self.live_transcription.setChecked(c["audio"].get("live_transcription", False))
        form.addRow(self.live_transcription)
        self.answer_on_pause = QCheckBox("结束/暂停收音后自动生成答案（不在说话过程中提交）")
        self.answer_on_pause.setChecked(c["audio"].get("answer_on_pause", False))
        form.addRow(self.answer_on_pause)
        self.term_replacements = QPlainTextEdit(json.dumps(c["audio"].get("term_replacements", {}), ensure_ascii=False, indent=2))
        self.term_replacements.setMaximumHeight(120)
        form.addRow("术语拼写替换 JSON（文字替换，不是声学热词）", self.term_replacements)
        form.addRow(QLabel("默认不保存原始音频。修改音频参数前请停止监听。\n小中文模型适合验证；专业术语准确率需用真实材料评估。"))

        self.templates = ListEditor(c["templates"], [("id", "ID", "str"), ("name", "名称", "str"), ("scene", "使用场景", "str"), ("system", "系统提示词", "text"), ("user", "用户提示词", "text"), ("format", "回答格式", "str"), ("length", "输出长度", "str"), ("style", "风格", "str")], defaults()["templates"][0])
        self.add_tab(self.templates, "提示词模板")
        self.backgrounds = ListEditor(c["backgrounds"], [("id", "ID", "str"), ("name", "场景名称", "str"), ("text", "背景资料（只使用实际录入文字）", "text")], defaults()["backgrounds"][0])
        self.backgrounds.fields["text"].setMinimumHeight(250)
        button("导入 TXT / MD / DOCX / PDF 到当前资料", self.import_material, self.backgrounds.layout())
        self.add_tab(self.backgrounds, "个人资料与场景")

        _, form = self.form_tab("快捷键与隐私")
        self.hotkey_fields = {}
        names = {"listen": "开始 / 暂停监听", "submit": "手动提交问题", "cancel": "取消生成", "clear": "新会话", "model": "切换模型", "window": "显示 / 隐藏窗口", "settings": "打开设置"}
        for key, value in c["hotkeys"].items():
            field = QLineEdit(value)
            self.hotkey_fields[key] = field
            form.addRow(names.get(key, key), field)
        self.default_provider = QComboBox()
        self.fallback = QComboBox()
        self.fallback.addItem("无备用模型", "")
        for p in c["providers"]:
            self.default_provider.addItem(p["name"], p["id"])
            self.fallback.addItem(p["name"], p["id"])
        self.default_provider.setCurrentIndex(self.default_provider.findData(c["default_provider"]))
        self.fallback.setCurrentIndex(self.fallback.findData(c["fallback_provider"]))
        form.addRow("默认模型（新增模型保存后可选）", self.default_provider)
        form.addRow("备用模型（仅正文输出前失败切换）", self.fallback)
        self.budget = QSpinBox()
        self.budget.setRange(1000, 100000)
        self.budget.setValue(c["context_chars"])
        form.addRow("总上下文字符预算（不是 token 数）", self.budget)
        self.save_history = QCheckBox("在本机保存最近30条问答（明文，关闭即删除历史文件）")
        self.save_history.setChecked(c["save_history"])
        form.addRow(self.save_history)
        form.addRow(QLabel("配置与手动录入的背景资料会保存到当前用户目录。\n快捷键保存时会检查系统占用，冲突则拒绝新配置。"))

        _, form = self.form_tab("手机服务")
        self.host = QComboBox()
        self.host.addItems(local_addresses())
        self.host.setCurrentText(c["mobile"]["host"])
        form.addRow("绑定本机地址", self.host)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(c["mobile"]["port"])
        form.addRow("端口", self.port)
        self.share_transcript = QCheckBox("向手机发送实时转写文字（问题和答案始终发送）")
        self.share_transcript.setChecked(c["mobile"]["share_transcript"])
        form.addRow(self.share_transcript)
        form.addRow(QLabel("默认127.0.0.1仅本机可访问。选择电脑的局域网IPv4后，\n在主界面启动手机服务并生成配对链接。仅限可信同一Wi-Fi。\n局域网HTTP不加密；不要在公共Wi-Fi上使用。链接3分钟内单次有效。\n服务不会自动开机运行、映射端口或打开防火墙。"))
        controls = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Save).setText("保存设置")
        controls.button(QDialogButtonBox.Save).setProperty("role", "primary")
        controls.button(QDialogButtonBox.Cancel).setText("取消")
        controls.accepted.connect(self.save)
        controls.rejected.connect(self.reject)
        root.addWidget(controls)

    def add_tab(self, widget, title):
        widget.setProperty("settingsPage", True)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)

    def form_tab(self, title):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(20, 20, 20, 20)
        form.setVerticalSpacing(14)
        form.setHorizontalSpacing(20)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.add_tab(page, title)
        return page, form

    def choose_model(self):
        path = QFileDialog.getExistingDirectory(self, "选择包含 am 子目录的模型文件夹")
        if path:
            self.model_path.setText(path)
            self.model_path.setCursorPosition(0)
            self.model_path.setToolTip(path)

    def import_material(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入资料（只提取文字）", "", "资料 (*.txt *.md *.docx *.pdf)")
        if path:
            try:
                content = read_material(path)
                if not content.strip():
                    raise ValueError("未提取到文字，请手动粘贴；扫描 PDF 不支持 OCR")
                self.backgrounds.fields["text"].setPlainText(content)
            except Exception:
                error(self, "无法读取资料，请检查文件格式、编码、大小；扫描件请手动粘贴文字")

    def save_key(self):
        pid = self.providers.entries[self.providers.current]["id"]
        if not self.key.text().strip():
            error(self, "请先输入 Key；删除请使用删除按钮")
            return
        try:
            self.controller.credentials.set(pid, self.key.text())
            self.key.clear()
            QMessageBox.information(self, "凭据", "已保存到 Windows 凭据管理器")
        except Exception:
            error(self, "Windows 凭据保存失败")

    def delete_key(self):
        try:
            self.controller.credentials.set(self.providers.entries[self.providers.current]["id"], "")
            self.key.clear()
        except Exception:
            error(self, "凭据删除失败")

    def test_key(self):
        pid = self.providers.entries[self.providers.current]["id"]
        if pid not in {p["id"] for p in self.controller.config["providers"]}:
            error(self, "请先保存新增模型，再打开设置进行测试")
            return
        self.controller.test_provider(pid)

    def save(self):
        try:
            if self.controller.audio.running:
                raise ValueError("请先停止音频监听，再保存设置")
            for editor in (self.providers, self.templates, self.backgrounds):
                editor.commit()
            c = self.config
            c["providers"], c["templates"], c["backgrounds"] = self.providers.entries, self.templates.entries, self.backgrounds.entries
            c["template"] = c["template"] if c["template"] in {x["id"] for x in c["templates"]} else c["templates"][0]["id"]
            c["background_id"] = c["background_id"] if c["background_id"] in {x["id"] for x in c["backgrounds"]} else c["backgrounds"][0]["id"]
            c["default_provider"] = self.default_provider.currentData()
            c["fallback_provider"] = self.fallback.currentData()
            c["context_chars"] = self.budget.value()
            c["hotkeys"] = {k: f.text() for k, f in self.hotkey_fields.items()}
            c["audio"].update({k: f.value() for k, f in self.audio_numbers.items()})
            c["audio"].update(mode=self.mode.currentData(), model_path=self.model_path.text(), auto_submit=self.auto_submit.isChecked(), manual_capture=self.manual_capture.isChecked(), **{k + "_device": f.currentData() for k, f in self.device_fields.items()})
            c["audio"].update(live_transcription=self.live_transcription.isChecked(), answer_on_pause=self.answer_on_pause.isChecked(), term_replacements=json.loads(self.term_replacements.toPlainText()))
            c["mobile"].update(host=self.host.currentText(), port=self.port.value(), share_transcript=self.share_transcript.isChecked())
            c["save_history"] = self.save_history.isChecked()
            validate(c)
            old_hotkeys = self.controller.config["hotkeys"]
            self.window.hotkeys.configure(c["hotkeys"])
            try:
                self.controller.store.save(c)
            except Exception:
                self.window.hotkeys.configure(old_hotkeys)
                raise
            if c["mobile"] != self.controller.config["mobile"]:
                self.controller.companion.stop()
            self.controller.config = c
            self.controller.rebuild_audio()
            self.window.hotkey_warning = ""
            self.controller.selected_provider = c["default_provider"]
            self.controller.persist()
            self.accept()
        except Exception as exc:
            error(self, str(exc) if isinstance(exc, ValueError) else "设置保存失败，请检查本地文件权限")

class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self.setWindowTitle("声答 · 实时语音问答助手 0.5")
        self.resize(1180, 780)
        self.setMinimumSize(960, 660)
        self.setWindowIcon(ui_icon("mic", "#147f7a", 32))
        root_widget = QWidget()
        root_widget.setObjectName("workspace")
        self.setCentralWidget(root_widget)
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(12)
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setFixedSize(42, 42)
        mark.setAlignment(Qt.AlignCenter)
        mark.setPixmap(ui_icon("mic", "#ffffff", 25).pixmap(25, 25))
        header.addWidget(mark)
        brand = QVBoxLayout()
        brand.setSpacing(1)
        brand.addWidget(text_label("声答", "brand"))
        brand.addWidget(text_label("实时语音问答助手", "subtitle"))
        header.addLayout(brand)
        header.addStretch()
        self.state_pill = QLabel("● 就绪")
        self.state_pill.setObjectName("statePill")
        self.state_pill.setAlignment(Qt.AlignCenter)
        header.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        button("手机伴侣", self.mobile, header, "quiet", "phone")
        button("设置", self.settings, header, "quiet", "settings")
        root.addLayout(header)
        self.shortcut_hint = QLabel()
        self.shortcut_hint.setProperty("textRole", "muted")
        self.shortcut_hint.setWordWrap(True)
        self.shortcut_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._submit_pending = False
        self._submitted = False
        self._discarding = False
        self._was_capturing = False
        self._submission_epoch = 0
        filters = surface("configBar")
        choices = QHBoxLayout(filters)
        choices.setContentsMargins(16, 10, 16, 12)
        choices.setSpacing(20)
        self.model, self.template, self.background = QComboBox(), QComboBox(), QComboBox()
        self.use_background = QCheckBox("启用资料")
        self.use_background.setToolTip("勾选后将当前资料场景加入问题上下文")
        self.use_background.setChecked(controller.config["use_background"])
        self.use_background.toggled.connect(self.set_background)
        self.fast_answer = QCheckBox("快速模式")
        self.fast_answer.setToolTip("简短结论优先，携带最近2轮对话；背景资料完整保留。对下次请求生效。")
        self.fast_answer.setChecked(controller.config.get("fast_answers", True))
        self.fast_answer.toggled.connect(self.set_fast_answer)
        for title, field, option in [("回答模型", self.model, self.fast_answer), ("提示词模板", self.template, None), ("背景资料", self.background, self.use_background)]:
            column = QVBoxLayout()
            column.setSpacing(5)
            label_row = QHBoxLayout()
            label_row.addWidget(text_label(title, "field"))
            label_row.addStretch()
            if option:
                label_row.addWidget(option)
            column.addLayout(label_row)
            field.setMinimumContentsLength(8)
            field.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            column.addWidget(field)
            choices.addLayout(column, 1)
        root.addWidget(filters)
        self.model.currentIndexChanged.connect(self.select_model)
        self.template.currentIndexChanged.connect(lambda: self.select_config("template", self.template))
        self.background.currentIndexChanged.connect(lambda: self.select_config("background_id", self.background))
        split = QSplitter()
        split.setObjectName("mainSplit")
        split.setHandleWidth(12)
        split.setChildrenCollapsible(False)
        left, right = QWidget(), surface("answerPanel")
        ll, rr = QVBoxLayout(left), QVBoxLayout(right)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        rr.setContentsMargins(22, 18, 22, 16)
        rr.setSpacing(12)
        question_panel = surface("questionPanel")
        ql = QVBoxLayout(question_panel)
        ql.setContentsMargins(18, 16, 18, 14)
        ql.setSpacing(10)
        ql.addWidget(text_label("当前问题", "section"))
        self.question_hint = text_label("边听边转写，也可以直接输入问题", "muted")
        ql.addWidget(self.question_hint)
        self.question = QPlainTextEdit()
        self.question.setObjectName("questionEditor")
        self.question.setMinimumHeight(55)
        self.question.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.question.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.question.document().setDocumentMargin(1)
        self.question.setPlaceholderText("在这里输入问题，\n或点击下方“开始收音”…")
        ql.addWidget(self.question, 1)
        actions = QHBoxLayout()
        button("预览提示词", self.preview, actions, "quiet", "preview")
        actions.addStretch()
        button("生成答案", self.submit, actions, "primary", "send")
        ql.addLayout(actions)
        ll.addWidget(question_panel, 3)
        history_panel = surface("historyPanel")
        hl = QVBoxLayout(history_panel)
        hl.setContentsMargins(16, 12, 16, 12)
        hl.setSpacing(8)
        history_header = QHBoxLayout()
        history_header.addWidget(text_label("最近对话", "section"))
        self.history_count = QLabel("0 / 30")
        self.history_count.setObjectName("countBadge")
        history_header.addWidget(self.history_count)
        history_header.addStretch()
        fresh = button("新会话", self.new_session, history_header, "quiet", "plus")
        fresh.setToolTip("清空当前对话并开始新会话")
        hl.addLayout(history_header)
        self.history = QListWidget()
        self.history.setObjectName("historyList")
        self.history.setMinimumHeight(44)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history.setTextElideMode(Qt.ElideRight)
        self.history_empty = text_label("还没有对话记录", "muted")
        self.history_empty.setAlignment(Qt.AlignCenter)
        hl.addWidget(self.history_empty, 1)
        self.history.currentRowChanged.connect(self.select_history)
        hl.addWidget(self.history, 1)
        ll.addWidget(history_panel, 2)
        answer_header = QHBoxLayout()
        answer_header.addWidget(text_label("参考答案", "section"))
        answer_header.addWidget(text_label("实时流式输出", "muted"))
        answer_header.addStretch()
        self.copy_button = button("复制", lambda: QApplication.clipboard().setText(self.answer.toPlainText()), answer_header, "quiet", "copy")
        rr.addLayout(answer_header)
        self.answer = QPlainTextEdit()
        self.answer.setObjectName("answerEditor")
        self.answer.setMinimumSize(150, 70)
        self.answer.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.answer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.answer.document().setDocumentMargin(1)
        self.answer.setReadOnly(True)
        self.answer_stack = QStackedWidget()
        self.empty_answer = QWidget()
        empty = QVBoxLayout(self.empty_answer)
        empty.setContentsMargins(12, 12, 12, 12)
        empty.setSpacing(12)
        empty.addStretch()
        empty_icon = QLabel()
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_icon.setPixmap(ui_icon("chat", "#a9c9c5", 52).pixmap(52, 52))
        empty.addWidget(empty_icon)
        self.empty_title = text_label("等待你的第一个问题", "emptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setWordWrap(True)
        empty.addWidget(self.empty_title)
        self.empty_caption = text_label("开始收音，或在左侧输入问题。\n参考答案将在这里逐字显示。", "emptyBody")
        self.empty_caption.setAlignment(Qt.AlignCenter)
        self.empty_caption.setWordWrap(True)
        empty.addWidget(self.empty_caption)
        empty.addStretch()
        self.answer_stack.addWidget(self.empty_answer)
        self.answer_stack.addWidget(self.answer)
        rr.addWidget(self.answer_stack, 1)
        self.metrics = QLabel("准备就绪 · 答案会在生成后实时显示")
        self.metrics.setObjectName("metrics")
        self.metrics.setWordWrap(True)
        rr.addWidget(self.metrics)
        controls = QHBoxLayout()
        self.cancel_button = button("停止生成", controller.cancel, controls, "danger", "stop")
        self.regenerate_button = button("重新生成", self.regenerate, controls, "quiet", "refresh")
        controls.addStretch()
        controls.addWidget(text_label("字号", "muted"))
        button("A−", lambda: self.font_size(-1), controls, "quiet")
        button("A+", lambda: self.font_size(1), controls, "quiet")
        rr.addLayout(controls)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([370, 740])
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
        capture_bar = surface("captureBar")
        capture = QHBoxLayout(capture_bar)
        capture.setContentsMargins(14, 10, 14, 10)
        capture.setSpacing(12)
        self.listen_button = button("开始收音", self.toggle_listen, capture, "primary", "mic")
        self.listen_button.setMinimumWidth(142)
        self.listen_button.setMinimumHeight(26)
        discard = button("放弃本段", self.stop_audio, capture, "quiet", "stop")
        discard.setToolTip("放弃当前音频，并停止和释放采集设备")
        meters = QVBoxLayout()
        meters.setSpacing(7)
        self.levels = {}
        for mode, label in [("system", "系统"), ("mic", "麦克风")]:
            row = QHBoxLayout()
            source_label = text_label(label, "field")
            source_label.setFixedWidth(40)
            row.addWidget(source_label)
            bar = QProgressBar()
            bar.setRange(0, 32767)
            bar.setTextVisible(False)
            bar.setFixedWidth(96)
            row.addWidget(bar)
            meters.addLayout(row)
            self.levels[mode] = bar
        capture.addLayout(meters)
        capture.addSpacing(8)
        instructions = QVBoxLayout()
        instructions.setSpacing(3)
        self.audio_status = text_label("音频未开始 · 准备好后点击收音", "subtitle")
        instructions.addWidget(self.audio_status)
        instructions.addWidget(self.shortcut_hint)
        capture.addLayout(instructions, 1)
        root.addWidget(capture_bar)
        self.status = QLabel(controller.status)
        self.status.setProperty("textRole", "muted")
        self.status.setWordWrap(True)
        self.status.setToolTip("请确认获得音频采集与辅助问答授权；默认不保存原始音频。")
        root.addWidget(self.status)
        self.snapshot = {"history": []}
        self.current_id = None
        self._history_signature = None
        self._rendered_answer_id = None
        controller.events.snapshot.connect(self.render)
        controller.events.transcript.connect(self.question.setPlainText)
        controller.events.level.connect(lambda mode, value: self.levels[mode].setValue(value))
        controller.events.error.connect(lambda text: self.status.setText("提示：" + text))
        controller.events.info.connect(lambda text: self.status.setText(text))
        controller.events.hotkey.connect(self.hotkey)
        self.hotkeys = Hotkeys(controller.events.hotkey.emit, controller.events.error.emit)
        self.hotkey_warning = ""
        try:
            self.hotkeys.configure(controller.config["hotkeys"])
        except ValueError as exc:
            self.hotkey_warning = str(exc) + "；请在设置修改快捷键"
            self.status.setText(self.hotkey_warning)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        action = menu.addAction("显示窗口")
        action.triggered.connect(self.show_window)
        menu.addAction("暂停监听", lambda: controller.audio.pause(True) if controller.audio.running else None)
        menu.addAction("退出并释放资源", self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()
        self.reload_choices()
        self.font_size(0)
        controller.publish()
        self.audio_timer = QTimer(self)
        self.audio_timer.timeout.connect(self.update_audio_status)
        self.audio_timer.start(100)

    def update_audio_status(self):
        a = self.c.audio
        paused = a.running and a.paused.is_set()
        self.listen_button.setText("结束收音" if a.running and not paused else "开始收音")
        self.audio_status.setText("音频：" + ("已暂停" if a.paused.is_set() else "监听中" if a.streams else "初始化中 / 设备未打开") if a.running else "音频：已停止")
        if self._was_capturing and paused:
            self._after_pause()
        self._was_capturing = a.running and not paused
        self.sync_visual_state()
        self.render_metrics()

    def sync_visual_state(self):
        a = self.c.audio
        recording = bool(a.running and not a.paused.is_set())
        if self.listen_button.property("recording") != recording:
            self.listen_button.setProperty("recording", recording)
            self.listen_button.setIcon(ui_icon("stop" if recording else "mic", "#ffffff"))
            self.listen_button.style().unpolish(self.listen_button)
            self.listen_button.style().polish(self.listen_button)
        latest = self.snapshot["history"][-1] if self.snapshot["history"] else None
        if recording:
            tone, text = "live", "● 收音中"
        elif latest and latest["status"] == "generating":
            tone, text = "busy", "● 正在生成"
        elif any(word in self.status.text() for word in ("失败", "异常", "超时")):
            tone, text = "error", "● 需要处理"
        else:
            tone, text = "idle", "● 已暂停" if a.running else "● 就绪"
        if self.state_pill.property("tone") != tone:
            self.state_pill.setProperty("tone", tone)
            self.state_pill.style().unpolish(self.state_pill)
            self.state_pill.style().polish(self.state_pill)
        self.state_pill.setText(text)
        self.question_hint.setText("正在转写，结束收音后确认最终文字" if recording else "支持编辑，也可以补充问题后重新生成")

    def set_fast_answer(self, checked):
        self.c.config["fast_answers"] = checked
        self.c.store.save(self.c.config)

    def _after_pause(self):
        if self.c.config["audio"].get("answer_on_pause", False) and not self._discarding and not self._submitted and not self._submit_pending:
            if getattr(self.c.audio, "session_error", False):
                self.status.setText("本段收音/识别异常，未自动提交；请核对文字后手动生成")
                return
            self.submit()

    def reload_choices(self):
        c = self.c.config
        ending = "结束后自动生成" if c["audio"].get("answer_on_pause", False) else f"按 {c['hotkeys']['submit']} 生成"
        self.shortcut_hint.setText(f"{c['hotkeys']['listen']} 开始/结束收音 · {ending} · {c['hotkeys']['submit']} 手动生成 · 实时文字在结束时确认")
        for field, entries, selected in [(self.model, [p for p in c["providers"] if p["enabled"]], self.c.selected_provider), (self.template, c["templates"], c["template"]), (self.background, c["backgrounds"], c["background_id"])]:
            field.blockSignals(True)
            field.clear()
            for entry in entries:
                field.addItem(entry["name"], entry["id"])
            field.setCurrentIndex(max(0, field.findData(selected)))
            field.blockSignals(False)

    def select_model(self):
        if self.model.currentData():
            self.c.selected_provider = self.model.currentData()

    def select_config(self, key, field):
        if field.currentData():
            self.c.config[key] = field.currentData()
            self.c.store.save(self.c.config)

    def set_background(self, checked):
        self.c.config["use_background"] = checked
        self.c.store.save(self.c.config)

    def toggle_listen(self):
        if self._submit_pending:
            self.status.setText("正在完成最后一段转写，请稍候")
            return
        if self.c.audio.running and self.c.audio.paused.is_set() and not self.c.audio.settled:
            self.status.setText("正在完成本段转写，请完成后再开始下一段")
            return
        if not self.c.audio.running or self.c.audio.paused.is_set():
            self._discarding = False
            if self._submitted:
                self.question.clear()
                self._submitted = False
                self.c.dedup.clear()
            self.c.transcript = self.question.toPlainText()
            self.c.preview_text = ""
        if self.c.audio.running:
            self.c.audio.pause(not self.c.audio.paused.is_set())
            if self.c.audio.paused.is_set():
                self._after_pause()
        else:
            self.c.audio.start(copy.deepcopy(self.c.config["audio"]))

    def stop_audio(self):
        self._discarding = True
        self._submission_epoch += 1
        self._submit_pending = False
        self.c.pending_submit_at = None
        self.c.preview_text = ""
        self.c.audio.pause(True)
        threading.Thread(target=self.c.audio.stop, name="stop-audio", daemon=True).start()

    def new_session(self):
        self.stop_audio()
        self.c.clear()

    def submit(self):
        if self._submit_pending:
            return
        self._intent_submit_at = time.monotonic()
        if self.c.audio.running:
            self.c.audio.pause(True)
            self._submit_pending = True
            self._submission_epoch += 1
            epoch = self._submission_epoch
            deadline = time.monotonic() + 60
            def wait_for_transcript():
                if self.c.closing or epoch != self._submission_epoch:
                    return
                if self.c.audio.settled:
                    self._submit_pending = False
                    if getattr(self.c.audio, "session_error", False):
                        self.status.setText("识别异常，未自动提交，请停止设备后核对文字再生成")
                        return
                    self._send_question()
                elif time.monotonic() > deadline:
                    self._submit_pending = False
                    self.status.setText("转写等待超时，请停止监听后核对文字再生成")
                else:
                    QTimer.singleShot(100, wait_for_transcript)
            QTimer.singleShot(100, wait_for_transcript)
            return
        self._send_question()

    def _send_question(self):
        if not self.question.toPlainText().strip():
            self.status.setText("未识别到有效问题，请重新收音或输入文字")
            return
        self.current_id = None
        self._submitted = True
        self.c.pending_submit_at = getattr(self, "_intent_submit_at", time.monotonic())
        self.c.submit(self.question.toPlainText())

    def regenerate(self):
        item = self.selected_entry()
        if item:
            self.current_id = None
            self.c.submit(item["question"])

    def selected_entry(self):
        return next((x for x in self.snapshot["history"] if x["id"] == self.current_id), self.snapshot["history"][-1] if self.snapshot["history"] else None)

    def render(self, snapshot):
        previous_ids = [x["id"] for x in self.snapshot["history"]]
        self.snapshot = snapshot
        self.status.setText(snapshot["status"] + (" | " + self.hotkey_warning if self.hotkey_warning else ""))
        entries = snapshot["history"]
        if entries and (not previous_ids or entries[-1]["id"] != previous_ids[-1]):
            self.current_id = entries[-1]["id"]
        signature = tuple((item["id"], item["status"], item["question"][:45]) for item in entries)
        if signature != self._history_signature:
            self._history_signature = signature
            self.history.blockSignals(True)
            self.history.clear()
            for index, item in enumerate(entries):
                state = {"done": "已完成", "generating": "生成中", "cancelled": "已取消", "error": "未完成"}.get(item["status"], item["status"])
                question = item["question"].replace("\n", " ")
                title = question[:22] + ("…" if len(question) > 22 else "")
                model_name = item.get("model", "").split(" / ")[0]
                entry_widget = QListWidgetItem(f"{title}\n{state}" + (f"  ·  {model_name[:16]}" if model_name else ""))
                entry_widget.setSizeHint(QSize(0, 50))
                entry_widget.setToolTip(item["question"])
                self.history.addItem(entry_widget)
                if item["id"] == self.current_id:
                    self.history.setCurrentRow(index)
            self.history.blockSignals(False)
            self.history_count.setText(f"{len(entries)} / 30")
            self.history.setVisible(bool(entries))
            self.history_empty.setVisible(not entries)
        self.render_answer()

    def render_answer(self):
        entry = self.selected_entry()
        text = entry["answer"] if entry else ""
        self.answer_stack.setCurrentWidget(self.answer if text else self.empty_answer)
        self.copy_button.setEnabled(bool(text))
        self.regenerate_button.setEnabled(bool(entry))
        self.cancel_button.setEnabled(any(item["status"] == "generating" for item in self.snapshot["history"]))
        if not text:
            if entry and entry["status"] == "generating":
                self.empty_title.setText("正在准备参考答案")
                self.empty_caption.setText("问题已提交，正在等待首个字。\n收到正文后会实时显示，无需重复提交。")
            elif entry and entry["status"] in ("error", "cancelled"):
                self.empty_title.setText("本次生成未完成" if entry["status"] == "error" else "已取消本次生成")
                self.empty_caption.setText("可以核对问题或模型设置，然后重新生成。")
            else:
                self.empty_title.setText("等待你的第一个问题")
                self.empty_caption.setText("开始收音，或在左侧输入问题。\n参考答案将在这里逐字显示。")
        if self.answer.toPlainText() != text:
            bar = self.answer.verticalScrollBar()
            bottom = bar.value() >= bar.maximum() - 5
            old = bar.value()
            old_text = self.answer.toPlainText()
            if entry and self._rendered_answer_id == entry["id"] and text.startswith(old_text):
                cursor = QTextCursor(self.answer.document())
                cursor.movePosition(QTextCursor.End)
                cursor.insertText(text[len(old_text):])
            else:
                self.answer.setPlainText(text)
            bar.setValue(bar.maximum() if bottom else old)
        self._rendered_answer_id = entry["id"] if entry else None
        self.sync_visual_state()
        self.render_metrics()

    def render_metrics(self):
        entry = self.selected_entry()
        if not entry:
            self.metrics.setText("准备就绪 · 答案会在生成后实时显示")
            return
        elapsed = round(time.monotonic() - entry["started_at"], 1) if entry["status"] == "generating" and entry.get("started_at") else entry.get("elapsed", 0)
        timings = entry.get("timings", {})
        phases = {"preparing": "准备请求", "request": "等待接口响应", "waiting_text": "接口已连接，等待正文", "reasoning": "服务端正在思考", "streaming": "正文流式显示中", "retrying": "重试连接/限流请求"}
        status_label = {"done": "已完成", "error": "生成失败", "cancelled": "已取消", "generating": "生成中"}.get(entry["status"], entry["status"])
        phase = phases.get(entry.get("phase"), status_label) if entry["status"] == "generating" else status_label
        first = timings.get("submit_to_first_token")
        first_label = f"首字 {first:.2f}秒" if first is not None else "等待首字" if entry["status"] == "generating" else ""
        tail = timings.get("transcription_tail", 0)
        parts = [entry["model"], phase, first_label, f"总计 {elapsed}秒"]
        if tail:
            parts.append(f"转写收尾 {tail:.2f}秒")
        total_tokens = entry.get("usage", {}).get("total_tokens")
        if total_tokens is not None:
            parts.append(f"用量 {total_tokens} token")
        self.metrics.setText("  ·  ".join(part for part in parts if part))
        self.metrics.setToolTip("阶段耗时（秒）\n" + "\n".join(f"{key}: {value}" for key, value in timings.items()))

    def select_history(self, row):
        if 0 <= row < len(self.snapshot["history"]):
            entry = self.snapshot["history"][row]
            self.current_id = entry["id"]
            self.question.setPlainText(entry["question"])
            self.render_answer()

    def preview(self):
        try:
            messages = self.c.messages(self.question.toPlainText())
        except ValueError as exc:
            error(self, str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("实际请求提示词预览（不包含 API Key）")
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(json.dumps(messages, ensure_ascii=False, indent=2))
        view.setReadOnly(True)
        layout.addWidget(view)
        layout.addWidget(QLabel("返回主窗口可修改问题；模板与资料在设置中编辑。"))
        dialog.exec()

    def settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.reload_choices()
            self.c.publish()

    def mobile(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("手机伴侣配对")
        dialog.resize(570, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("同一可信 Wi-Fi；需要选择局域网地址。配对链接单次有效180秒。"))
        address = QComboBox()
        for ip in local_addresses():
            if ip != "127.0.0.1":
                address.addItem(ip)
        address.setCurrentText(preferred_address())
        layout.addWidget(QLabel("手机访问地址（已优先选择当前网络，不能使用127.0.0.1）"))
        layout.addWidget(address)
        network_notice = QLabel("网页打不开时：检查同一Wi-Fi、关闭手机VPN/移动数据切换，并检查Windows防火墙。")
        network_notice.setWordWrap(True)
        layout.addWidget(network_notice)
        link_field = QLineEdit()
        link_field.setReadOnly(True)
        layout.addWidget(link_field)
        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)
        layout.addWidget(qr)
        devices_list = QListWidget()
        layout.addWidget(devices_list)
        def refresh():
            devices_list.clear()
            for device in self.c.companion.devices():
                devices_list.addItem(device["name"])
        def start():
            try:
                m = self.c.config["mobile"]
                selected = address.currentText()
                if not selected or selected == "127.0.0.1":
                    raise ValueError("未找到可用局域网地址，请先连接可信Wi-Fi或电脑热点")
                if not self.c.companion.server or self.c.companion.host != selected:
                    m["host"] = selected
                    self.c.companion.start(m["host"], m["port"])
                    self.c.store.save(self.c.config)
                link = self.c.companion.pair_link()
                link_field.setText(link)
                import qrcode
                image = qrcode.make(link)
                output = io.BytesIO()
                image.save(output, format="PNG")
                pixmap = QPixmap()
                pixmap.loadFromData(output.getvalue())
                qr.setPixmap(pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.c.publish()
                network_notice.setText(f"服务已启动：http://{selected}:{m['port']} 。若手机仍打不开网页，可点击下方防火墙修复；随后重新扫码。")
            except Exception as exc:
                error(dialog, str(exc) if isinstance(exc, (ValueError, OSError)) else "手机服务启动失败，请检查网络与端口")
        def firewall():
            selected = address.currentText()
            if selected not in local_addresses() or selected == "127.0.0.1":
                error(dialog, "请先选择当前电脑局域网地址")
                return
            base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
            script = base / "scripts" / "allow_mobile.ps1"
            arguments = subprocess.list2cmdline(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ProgramPath", sys.executable, "-LocalAddress", selected, "-Port", str(self.c.config["mobile"]["port"])])
            outcome = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", arguments, str(base), 0)
            network_notice.setText("已请求管理员授权。修复仅允许同一子网访问本程序的所选地址和端口；完成后重新扫码。" if outcome > 32 else "管理员授权未完成，请手动检查Windows防火墙。")
        row = QHBoxLayout()
        button("启动 / 重新生成配对", start, row)
        button("复制链接", lambda: QApplication.clipboard().setText(link_field.text()), row)
        layout.addLayout(row)
        button("修复本机防火墙（需管理员授权）", firewall, layout)
        row = QHBoxLayout()
        button("解除全部设备", lambda: (self.c.companion.revoke(), refresh(), link_field.clear(), qr.clear()), row)
        button("停止手机服务", lambda: (self.c.companion.stop(), refresh(), link_field.clear(), qr.clear()), row)
        layout.addLayout(row)
        layout.addWidget(QLabel("127.0.0.1 的链接只能在本机打开。服务仅推送文字，手机不能操作模型或采集音频。\n首次连接可能需要在 Windows 防火墙允许“专用网络”。"))
        timer = QTimer(dialog)
        timer.timeout.connect(refresh)
        timer.start(1000)
        refresh()
        dialog.exec()

    def font_size(self, delta):
        self.c.config["font_size"] = max(10, min(32, self.c.config["font_size"] + delta))
        font = QFont("Microsoft YaHei", self.c.config["font_size"])
        self.answer.setFont(font)
        self.question.setFont(font)
        self.answer.setStyleSheet(f"font-size: {self.c.config['font_size']}pt;")
        self.question.setStyleSheet(f"font-size: {self.c.config['font_size']}pt;")

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "history"):
            QTimer.singleShot(0, self._keep_history_selection_visible)

    def _keep_history_selection_visible(self):
        item = self.history.currentItem()
        if item:
            self.history.scrollToItem(item)

    def hotkey(self, action):
        {"listen": self.toggle_listen, "submit": self.submit, "cancel": self.c.cancel, "clear": self.new_session,
         "model": lambda: self.model.setCurrentIndex((self.model.currentIndex() + 1) % max(1, self.model.count())),
         "window": lambda: self.hide() if self.isVisible() and not self.isMinimized() else self.show_window(), "settings": self.settings}.get(action, lambda: None)()

    def closeEvent(self, event):
        self.hotkeys.stop()
        self.c.close()
        self.tray.hide()
        event.accept()

