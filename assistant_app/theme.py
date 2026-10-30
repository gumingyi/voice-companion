"""Native Qt presentation layer. No timers, network calls or raster assets."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from pathlib import Path

_ICONS = {}
_PATHS = {
    "mic": '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5.5 10v2a6.5 6.5 0 0 0 13 0v-2M12 18.5V22M8 22h8"/>',
    "send": '<path d="m3 4 19 8-19 8 4-8-4-8ZM7 12h15"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="white"/><circle cx="15" cy="17" r="3" fill="white"/>',
    "phone": '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 5h4M11 19h2"/>',
    "copy": '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h4"/>',
    "refresh": '<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 2M18 18a8 8 0 0 1-13-2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "preview": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "chat": '<path d="M5 4h14a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3H9l-6 4V7a3 3 0 0 1 2-3Z"/><path d="M8 10h9M8 14h6"/>',
}

def ui_icon(name, color="#64748b", size=20):
    key = name, color, size
    if key not in _ICONS:
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>'
        pix = QPixmap(size * 2, size * 2)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        QSvgRenderer(svg.encode()).render(painter, QRectF(0, 0, size * 2, size * 2))
        painter.end()
        pix.setDevicePixelRatio(2)
        _ICONS[key] = QIcon(pix)
    return _ICONS[key]

STYLE = """
QWidget {font-family:'Microsoft YaHei UI','Microsoft YaHei';font-size:13px;color:#243247;}
QMainWindow,QDialog,QWidget#workspace {background:#f3f6f8;}
QLabel {background:transparent;border:0;}
QLabel[textRole="brand"] {font-size:23px;font-weight:700;color:#142b3b;}
QLabel[textRole="subtitle"] {font-size:12px;color:#758796;}
QLabel[textRole="section"] {font-size:15px;font-weight:600;color:#26394b;}
QLabel[textRole="muted"] {font-size:12px;color:#7b8b99;}
QLabel[textRole="field"] {font-size:11px;color:#708191;}
QLabel[textRole="emptyTitle"] {font-size:19px;font-weight:600;color:#40556b;}
QLabel[textRole="emptyBody"] {font-size:13px;color:#92a0ad;}
QLabel#brandMark {background:#127d79;border-radius:12px;}
QLabel#statePill {padding:6px 14px;border-radius:13px;background:#e8eff3;color:#708394;font-size:12px;}
QLabel#statePill[tone="live"] {background:#e1f3eb;color:#158265;}
QLabel#statePill[tone="busy"] {background:#e8efff;color:#5474b7;}
QLabel#statePill[tone="error"] {background:#fbeaea;color:#be655e;}
QLabel#countBadge {font-size:11px;color:#8696a5;background:#f0f4f7;border-radius:8px;padding:2px 7px;}
QLabel#metrics {font-size:11px;color:#6c7d8f;background:#f6f8fa;border-radius:8px;padding:8px 10px;}
QFrame[surface="true"] {background:#ffffff;border:1px solid #e4eaef;border-radius:14px;}
QFrame#captureBar {background:#eaf1f3;border:1px solid #dee8ec;border-radius:14px;}
QPushButton {background:#ffffff;border:1px solid #dfe6ec;border-radius:8px;padding:8px 12px;min-height:18px;color:#506276;}
QPushButton:hover {background:#f2f7f8;border-color:#c5d8dd;color:#1c6d70;}
QPushButton:pressed {background:#e5eff0;}
QPushButton:focus {border:1px solid #58a8a2;}
QPushButton:disabled {color:#b0bac5;background:#f4f6f8;border-color:#e8edf2;}
QPushButton[role="primary"] {background:#147f7a;border-color:#147f7a;color:white;font-weight:600;}
QPushButton[role="primary"]:hover {background:#0d716d;border-color:#0d716d;}
QPushButton[role="primary"][recording="true"] {background:#bc6861;border-color:#bc6861;}
QPushButton[role="quiet"] {background:transparent;border-color:transparent;padding:7px 10px;color:#728396;}
QPushButton[role="quiet"]:hover {background:#edf3f6;color:#237d7d;}
QPushButton[role="danger"] {background:transparent;border-color:transparent;color:#b46760;}
QPushButton[role="danger"]:hover {background:#fcf0ef;}
QPushButton[role="danger"]:disabled,QPushButton[role="quiet"]:disabled {background:transparent;border-color:transparent;color:#b5c0ca;}
QPlainTextEdit,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {background:#fbfcfd;border:1px solid #dee6ed;border-radius:7px;padding:8px;color:#34465b;selection-background-color:#cce9e4;selection-color:#163f3e;}
QPlainTextEdit:focus,QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus {border-color:#75b9b0;background:white;}
QPlainTextEdit#questionEditor,QPlainTextEdit#answerEditor {border:0;background:transparent;padding:0;color:#33465a;selection-background-color:#cce9e4;}
QComboBox {padding:7px 28px 7px 10px;min-height:18px;}
QComboBox::drop-down {border:0;width:25px;}
QSpinBox,QDoubleSpinBox {padding-right:25px;}
QSpinBox::up-button,QDoubleSpinBox::up-button {subcontrol-origin:border;subcontrol-position:top right;width:22px;height:16px;border:0;background:transparent;}
QSpinBox::down-button,QDoubleSpinBox::down-button {subcontrol-origin:border;subcontrol-position:bottom right;width:22px;height:16px;border:0;background:transparent;}
QSpinBox::up-button:hover,QSpinBox::down-button:hover,QDoubleSpinBox::up-button:hover,QDoubleSpinBox::down-button:hover {background:#edf4f5;}
QComboBox QAbstractItemView {background:white;border:1px solid #dbe5ec;outline:0;selection-background-color:#e4f3ef;selection-color:#246f6b;padding:4px;}
QCheckBox {spacing:6px;background:transparent;color:#748597;font-size:12px;}
QCheckBox::indicator {width:15px;height:15px;border-radius:4px;border:1px solid #c5d2db;background:white;}
QCheckBox::indicator:checked {background:#278d82;border:1px solid #278d82;}
QCheckBox::indicator:hover {border-color:#439f96;}
QCheckBox:focus {color:#127d79;}
QListWidget#historyList {border:0;background:transparent;outline:0;padding:0;}
QListWidget#historyList::item {border:1px solid transparent;border-radius:9px;padding:7px 12px;margin-bottom:4px;color:#697c8d;}
QListWidget#historyList::item:hover {background:#f4f8fa;}
QListWidget#historyList::item:selected {background:#edf7f3;border:1px solid #d5e9e1;color:#276e65;}
QListWidget {background:white;border:1px solid #e1e8ee;border-radius:8px;padding:6px;outline:0;}
QProgressBar {background:#dce6ea;border:0;border-radius:3px;max-height:6px;min-height:6px;}
QProgressBar::chunk {background:#55aa94;border-radius:3px;}
QSplitter::handle {background:transparent;}
QSplitter::handle:hover {background:#dce8eb;border-radius:5px;}
QStackedWidget {background:transparent;border:0;}
QScrollBar:vertical {background:transparent;width:7px;margin:3px 0;}
QScrollBar::handle:vertical {background:#d6e0e7;border-radius:3px;min-height:24px;}
QScrollBar::handle:vertical:hover {background:#abbec8;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:none;}
QScrollBar:horizontal {background:transparent;height:7px;}
QScrollBar::handle:horizontal {background:#d6e0e7;border-radius:3px;min-width:24px;}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {width:0;}
QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal {background:none;}
QTabWidget::pane {background:white;border:1px solid #e1e8ee;border-radius:10px;top:-1px;}
QTabBar::tab {background:transparent;color:#8291a1;padding:12px 15px;border-bottom:2px solid transparent;}
QTabBar::tab:selected {color:#157e76;border-bottom-color:#278d82;}
QTabBar::tab:hover {background:#edf4f5;}
QScrollArea {border:0;background:transparent;}
QWidget[settingsPage="true"] {background:white;border:0;}
QMenu {background:white;border:1px solid #dfe7ed;border-radius:8px;padding:5px;}
QMenu::item {padding:8px 25px 8px 12px;border-radius:5px;}
QMenu::item:selected {background:#eaf5f1;color:#246d62;}
QToolTip {background:#28454f;color:white;border:0;padding:6px;border-radius:4px;}
"""
STYLE += 'QCheckBox::indicator:checked {image:url("' + (Path(__file__).with_name("assets") / "check.svg").as_posix() + '");}'
STYLE += 'QComboBox::down-arrow {width:14px;height:14px;image:url("' + (Path(__file__).with_name("assets") / "chevron.svg").as_posix() + '");}'
STYLE += 'QSpinBox::down-arrow,QDoubleSpinBox::down-arrow {width:10px;height:10px;image:url("' + (Path(__file__).with_name("assets") / "chevron.svg").as_posix() + '");}'
STYLE += 'QSpinBox::up-arrow,QDoubleSpinBox::up-arrow {width:10px;height:10px;image:url("' + (Path(__file__).with_name("assets") / "chevron-up.svg").as_posix() + '");}'
