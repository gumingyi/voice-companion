import os
from pathlib import Path
import sys
import logging
from logging.handlers import RotatingFileHandler

def main():
    from PySide6.QtWidgets import QApplication, QMessageBox
    from assistant_app.settings import ConfigStore, Credentials
    app = QApplication(sys.argv)
    app.setApplicationName("VoiceCompanion")
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    # Single instance per user prevents conflicting audio engines and hotkeys.
    name = "VoiceCompanion-" + os.environ.get("USERNAME", "user")
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(500):
        QMessageBox.information(None, "语音问答助手", "程序已运行。若正在升级，请先从托盘退出旧版，再启动新版；否则请通过托盘图标或显示窗口快捷键打开。")
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    if not server.listen(name):
        return 1
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    os.chdir(base)
    store = ConfigStore()
    # Structured event names only; never log exceptions, prompts, URLs or user data.
    logger = logging.getLogger("voicecompanion")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(store.root / "app.log", maxBytes=200000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.info("application_start")
    try:
        config = store.load()
        credentials = Credentials()
    except Exception:
        QMessageBox.critical(None, "启动失败", f"配置或 Windows 凭据管理器不可用。请检查 {store.path}；原文件保留，不会自动覆盖。")
        return 1
    from assistant_app.controller import Controller
    from assistant_app.ui import MainWindow, STYLE
    app.setStyleSheet(STYLE)
    controller = Controller(config, store, credentials)
    window = MainWindow(controller)
    controller.events.error.connect(lambda _: logger.warning("operation_failed"))
    def exception_hook(kind, value, tb):
        logger.error("unhandled_error")
        controller.events.error.emit("内部错误，请检查配置或重新启动；日志未记录敏感内容")
    sys.excepthook = exception_hook
    window.show()
    if "--smoke-test" in sys.argv:
        from PySide6.QtCore import QTimer
        import json
        import socket
        def smoke_test():
            result = {"window_visible": window.isVisible(), "frozen": bool(getattr(sys, "frozen", False)), "templates": window.template.count()}
            from assistant_app import theme
            result["ui_assets_present"] = all((Path(theme.__file__).with_name("assets") / name).is_file() for name in ("check.svg", "chevron.svg", "chevron-up.svg"))
            try:
                from assistant_app.audio import devices
                from assistant_app.speech import VoskRecognizer
                result["audio_devices"] = {k: len(v) for k, v in devices().items()}
                result["mobile_html"] = (Path(__import__("assistant_app.companion", fromlist=["__file__"]).__file__).with_name("mobile.html")).exists()
                VoskRecognizer(config["audio"]["model_path"])
                result["vosk_loaded"] = True
                with socket.socket() as s:
                    s.bind(("127.0.0.1", 0))
                    port = s.getsockname()[1]
                controller.companion.start("127.0.0.1", port)
                result["web_service_started"] = controller.companion.server.started
                controller.companion.stop()
            except Exception as exc:
                result["error_type"] = type(exc).__name__
                result["error_message"] = str(exc)
            target = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
            target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            window.close()
        QTimer.singleShot(600, smoke_test)
    code = app.exec()
    if not controller.closing:
        window.hotkeys.stop()
        controller.close()
    logger.info("application_stop")
    server.close()
    return code

if __name__ == "__main__":
    sys.exit(main())
