"""Mobile viewport browser test. Not a physical-phone / Wi-Fi acceptance test."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from PySide6.QtWidgets import QApplication
from playwright.sync_api import sync_playwright, expect
from assistant_app import controller as module
from assistant_app.settings import defaults, ConfigStore
from assistant_app.companion import preferred_address

class FixtureProvider:
    async def stream(self, messages):
        for text in ["【本地测试夹具】", "这是一段流式测试文字，", "用于核对手机页面的增量显示。"]:
            await asyncio.sleep(.4)
            yield {"text": text}

class TestKeys:
    def get(self, _): return "test-only"

def main():
    app = QApplication.instance() or QApplication([])
    output = ROOT / "docs" / "verification"
    output.mkdir(exist_ok=True)
    result = {"physical_phone": False, "browser": "Microsoft Edge headless, 390x844 mobile viewport", "model": "explicit local test fixture; no DeepSeek request"}
    module.adapter = lambda p, key, **kwargs: FixtureProvider()
    config = defaults()
    config["audio"].update(auto_submit=True, manual_capture=False, live_transcription=False, answer_on_pause=False)
    config["providers"][0].update(name="本地测试夹具", model="fixture-stream")
    ctrl = module.Controller(config, ConfigStore(output / "browser_test_data"), TestKeys())
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    host = preferred_address() if "--lan" in sys.argv else "127.0.0.1"
    result["bound_address"] = host
    ctrl.companion.start(host, port)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=1)
            page = context.new_page()
            page.goto(ctrl.companion.pair_link())
            expect(page.locator('#state')).to_contain_text('已连接')
            assert "#pair" not in page.url
            result["pair_and_fragment_removed"] = True
            ctrl.recognized("浏览器测试：什么是闭环控制")
            expect(page.locator('#answers')).to_contain_text('本地测试夹具')
            result["incremental_visible"] = "用于核对" not in page.locator("#answers").inner_text()
            expect(page.locator('#answers')).to_contain_text('用于核对手机页面')
            result["completed_visible"] = True
            page.screenshot(path=str(output / ("mobile_lan.png" if "--lan" in sys.argv else "mobile.png")), full_page=True)
            page.evaluate("() => ws.close()")
            expect(page.locator('#state')).to_contain_text('连接断开')
            expect(page.locator('#state')).to_contain_text('已连接')
            result["automatic_reconnect"] = "本地测试夹具" in page.locator("#answers").inner_text()
            page.reload()
            expect(page.locator('#answers')).to_contain_text('本地测试夹具')
            result["cookie_refresh_restore"] = True
            page.get_by_role("button", name="清空本机显示").click()
            assert not page.locator("article").count()
            result["clear_local_display"] = True
            page.get_by_role("button", name="解除配对", exact=True).click()
            expect(page.locator('#state')).to_contain_text('已解除配对')
            result["unpair"] = not ctrl.companion.devices()
            browser.close()
    finally:
        ctrl.close()
    (output / ("mobile_lan_browser_result.json" if "--lan" in sys.argv else "mobile_browser_result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))

if __name__ == "__main__":
    main()
