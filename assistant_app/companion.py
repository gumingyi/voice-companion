import asyncio
import copy
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

def local_addresses():
    addresses = {"127.0.0.1"}
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        value = info[4][0]
        ip = ipaddress.ip_address(value)
        if ip.is_private and not ip.is_link_local and not ip.is_unspecified and not ip.is_multicast:
            addresses.add(value)
    return sorted(addresses)

def preferred_address():
    addresses = local_addresses()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(("192.0.2.1", 9))  # Route lookup only; no UDP payload sent.
            chosen = route.getsockname()[0]
        if chosen in addresses and chosen != "127.0.0.1":
            return chosen
    except OSError:
        pass
    return next((ip for ip in addresses if ip != "127.0.0.1"), "127.0.0.1")

class Companion:
    def __init__(self):
        self.lock = threading.RLock()
        self.snapshot = {"revision": 0, "status": "就绪", "transcript": "", "history": []}
        self.sessions = {}
        self.invite = None
        self.invite_until = 0
        self.failures = {}
        self.server = self.thread = None
        self.host, self.port = "127.0.0.1", 8765
        self.app = self._make_app()

    def publish(self, status, transcript, history, share_transcript=False):
        # Explicit allowlist: configuration, credentials, background and PCM never cross boundary.
        with self.lock:
            self.snapshot = {"revision": self.snapshot["revision"] + 1, "status": status,
                             "transcript": transcript if share_transcript else "",
                             "history": [{k: copy.deepcopy(x[k]) for k in ("id", "question", "answer", "status", "model") if k in x} for x in history[-30:]]}

    def pair_link(self):
        with self.lock:
            self.invite = secrets.token_urlsafe(32)
            self.invite_until = time.monotonic() + 180
            return f"http://{self.host}:{self.port}/#pair={self.invite}"

    def devices(self):
        with self.lock:
            return [{"id": k, "name": v["name"]} for k, v in self.sessions.items() if v["expires"] > time.monotonic()]

    def revoke(self, session=None):
        with self.lock:
            if session:
                self.sessions.pop(session, None)
            else:
                self.sessions.clear()
                self.invite = None

    def _authenticated(self, sid):
        with self.lock:
            entry = self.sessions.get(sid)
            return entry is not None and entry["expires"] > time.monotonic()

    def _valid_host(self, value):
        return value == f"{self.host}:{self.port}"

    def _valid_origin(self, origin):
        return origin == f"http://{self.host}:{self.port}"

    def _make_app(self):
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.middleware("http")
        async def security(request, call_next):
            if not self._valid_host(request.headers.get("host", "")):
                return JSONResponse({"error": "无效主机"}, 403)
            if request.method == "POST" and not self._valid_origin(request.headers.get("origin", "")):
                return JSONResponse({"error": "无效来源"}, 403)
            response = await call_next(request)
            response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
            return response

        @app.get("/", response_class=HTMLResponse)
        async def index():
            return Path(__file__).with_name("mobile.html").read_text(encoding="utf-8")

        @app.post("/pair")
        async def pair(request: Request):
            if int(request.headers.get("content-length", "0")) > 2048:
                return JSONResponse({"error": "请求过大"}, 413)
            peer = request.client.host
            now = time.monotonic()
            with self.lock:
                failures = [t for t in self.failures.get(peer, []) if now - t < 60]
                if len(failures) >= 8:
                    return JSONResponse({"error": "尝试过多，请稍后重试"}, 429)
            try:
                raw = await request.body()
                if len(raw) > 2048:
                    return JSONResponse({"error": "请求过大"}, 413)
                data = json.loads(raw)
                token = data.get("token", "")
                if not isinstance(token, str):
                    raise ValueError()
            except (ValueError, AttributeError):
                return JSONResponse({"error": "配对请求无效"}, 400)
            with self.lock:
                if not self.invite or now > self.invite_until or not secrets.compare_digest(token, self.invite):
                    self.failures[peer] = failures + [now]
                    return JSONResponse({"error": "配对链接已失效，请在电脑重新生成"}, 401)
                self.invite = None  # Single use invite, not a reusable LAN password.
                self.sessions = {k: v for k, v in self.sessions.items() if v["expires"] > now}
                if len(self.sessions) >= 8:
                    return JSONResponse({"error": "设备上限8台，请先解除配对"}, 409)
                sid = secrets.token_urlsafe(32)
                self.sessions[sid] = {"name": f"设备 {len(self.sessions) + 1} ({peer})", "expires": now + 12 * 3600}
            response = JSONResponse({"ok": True})
            response.set_cookie("companion", sid, httponly=True, samesite="strict", max_age=12 * 3600, path="/")
            return response

        @app.post("/unpair")
        async def unpair(request: Request):
            self.revoke(request.cookies.get("companion", ""))
            response = JSONResponse({"ok": True})
            response.delete_cookie("companion")
            return response

        @app.websocket("/ws")
        async def websocket(ws: WebSocket):
            sid = ws.cookies.get("companion", "")
            if not self._valid_host(ws.headers.get("host", "")) or not self._valid_origin(ws.headers.get("origin", "")) or not self._authenticated(sid):
                await ws.close(code=1008)
                return
            await ws.accept()
            revision = -1
            last_send = 0
            try:
                while self._authenticated(sid):
                    with self.lock:
                        snapshot = copy.deepcopy(self.snapshot)
                    if revision != snapshot["revision"] or time.monotonic() - last_send > 10:
                        await asyncio.wait_for(ws.send_json(snapshot), timeout=5)
                        revision, last_send = snapshot["revision"], time.monotonic()
                    await asyncio.sleep(.08)
                await ws.close(code=1008)
            except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError, OSError):
                pass
        return app

    def start(self, host, port):
        self.stop()
        ip = ipaddress.ip_address(host)
        if ip.version != 4 or host not in local_addresses() or not (ip.is_private or ip.is_loopback):
            raise ValueError("请选择本机实际存在的私网 IPv4 地址")
        self.host, self.port = host, int(port)
        # Prebind synchronously so UI sees address/port errors; avoid worker SystemExit.
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.bind((host, self.port))
            self.sock.listen(64)
            # Windowed executables have no stdout/stderr; Uvicorn's default
            # color formatter calls isatty() and fails in that environment.
            config = uvicorn.Config(self.app, host=host, port=self.port, log_level="critical", log_config=None, access_log=False, ws="websockets", ws_max_size=4096, ws_max_queue=4, timeout_graceful_shutdown=1)
            self.server = uvicorn.Server(config)
            self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, name="companion", daemon=True)
            self.thread.start()
            for _ in range(100):
                if self.server.started:
                    return
                if not self.thread.is_alive():
                    break
                time.sleep(.02)
            raise ValueError("手机服务启动失败")
        except Exception:
            self.sock.close()
            self.stop()
            raise

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(4)
            if self.thread.is_alive():
                raise RuntimeError("手机服务未正常退出")
        if hasattr(self, "sock"):
            self.sock.close()
        self.server = self.thread = None
        self.revoke()
