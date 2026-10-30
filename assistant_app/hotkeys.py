import ctypes
from ctypes import wintypes
import queue
import threading

MODS = {"ALT": 1, "CTRL": 2, "SHIFT": 4, "WIN": 8}
KEYS = {"ENTER": 13, "SPACE": 32, "ESC": 27, **{f"F{i}": 111 + i for i in range(1, 25)}}

def parse_hotkey(value):
    parts = value.upper().replace(" ", "").split("+")
    if len(parts) < 2 or len(set(parts)) != len(parts) or any(p not in MODS for p in parts[:-1]):
        raise ValueError("快捷键格式示例 CTRL+ALT+L，必须带修饰键")
    key = parts[-1]
    vk = ord(key) if len(key) == 1 and key.isascii() and key.isalnum() else KEYS.get(key)
    if vk is None:
        raise ValueError("不支持的快捷键按键：" + key)
    return sum(MODS[p] for p in parts[:-1]), vk

class Hotkeys:
    def __init__(self, callback, error):
        self.callback, self.error = callback, error
        self.commands = queue.Queue()
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self.thread.start()
        self.ready.wait(3)

    def configure(self, mapping):
        event, result = threading.Event(), []
        self.commands.put((mapping.copy(), event, result))
        if not event.wait(3):
            raise ValueError("快捷键注册线程无响应")
        if result:
            raise ValueError(result[0])

    def _run(self):
        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        active = {}
        previous = {}
        msg = wintypes.MSG()
        self.ready.set()
        def unregister():
            for identifier in active:
                user32.UnregisterHotKey(None, identifier)
            active.clear()
        def register(mapping):
            for identifier, (action, hotkey) in enumerate(mapping.items(), 1):
                modifiers, key = parse_hotkey(hotkey)
                if not user32.RegisterHotKey(None, identifier, modifiers | 0x4000, key):
                    raise ValueError("快捷键被系统或其他程序占用：" + hotkey)
                active[identifier] = action
        try:
            while not self.stop_event.wait(.02):
                try:
                    mapping, event, result = self.commands.get_nowait()
                    unregister()
                    try:
                        register(mapping)
                        previous = mapping
                    except ValueError as exc:
                        unregister()
                        try:
                            register(previous)
                        except ValueError:
                            self.error("原快捷键恢复失败，请重新配置")
                        result.append(str(exc))
                    finally:
                        event.set()
                except queue.Empty:
                    pass
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == 0x0312 and msg.wParam in active:
                        self.callback(active[msg.wParam])
        finally:
            unregister()

    def stop(self):
        self.stop_event.set()
        self.thread.join(3)
