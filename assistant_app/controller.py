import asyncio
import copy
import json
import threading
import time
import uuid
import httpx
from PySide6.QtCore import QObject, Signal
from .audio import AudioEngine
from .speech import VoskRecognizer
from .live_audio import StreamingAudioEngine
from .providers import adapter, ProviderError
from .prompts import assemble
from .questions import Deduplicator, normalize, is_question
from .companion import Companion

class Events(QObject):
    snapshot = Signal(object)
    transcript = Signal(str)
    level = Signal(str, int)
    error = Signal(str)
    info = Signal(str)
    hotkey = Signal(str)

class Controller:
    def __init__(self, config, store, credentials):
        self.config, self.store, self.credentials = config, store, credentials
        self.events = Events()
        self.lock = threading.RLock()
        self.history = []
        self.status, self.transcript = "就绪 · 请确认获得音频采集与辅助问答授权", ""
        self.selected_provider = config["default_provider"]
        self.task = None
        self.closing = False
        self._last_publish = 0
        self.pending_submit_at = None
        self.client = None
        self.dedup = Deduplicator()
        self.companion = Companion()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="model-requests", daemon=True)
        self.thread.start()
        self.preview_text = ""
        self.rebuild_audio()
        if config["save_history"]:
            path = store.root / "history.json"
            if path.exists():
                try:
                    self.history = json.loads(path.read_text(encoding="utf-8"))[-30:]
                    for item in self.history:
                        if item.get("status") == "generating":
                            item["status"] = "cancelled"
                except (ValueError, TypeError):
                    self.events.error.emit("本地历史记录格式错误，未载入")

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        if self.client:
            self.loop.run_until_complete(self.client.aclose())
        self.loop.close()

    def publish(self, force=False):
        if self.closing:
            return
        now = time.monotonic()
        with self.lock:
            if not force and now - self._last_publish < .05:
                return
            self._last_publish = now
            visible = (self.transcript + "\n" + self.preview_text).strip() if self.preview_text else self.transcript
            snapshot = {"status": self.status, "history": copy.deepcopy(self.history), "transcript": visible}
        self.events.snapshot.emit(snapshot)
        self.companion.publish(snapshot["status"], snapshot["transcript"], snapshot["history"], self.config["mobile"]["share_transcript"])

    def set_status(self, status):
        with self.lock:
            self.status = status
        self.publish(force=True)

    def rebuild_audio(self):
        kind = StreamingAudioEngine if self.config["audio"].get("live_transcription", False) else AudioEngine
        args = (lambda: VoskRecognizer(self.config["audio"]["model_path"]), self.recognized, self.set_status, self.events.level.emit)
        self.audio = kind(*args, on_partial=self.preview) if kind is StreamingAudioEngine else kind(*args)

    def spelling(self, text):
        text = normalize(text)
        for source, target in self.config["audio"].get("term_replacements", {}).items():
            text = text.replace(source, target)
        return text

    def preview(self, text):
        if self.closing:
            return
        with self.lock:
            self.preview_text = self.spelling(text)
            visible = (self.transcript + "\n" + self.preview_text).strip()
        self.events.transcript.emit(visible)
        self.publish()

    def recognized(self, text):
        text = self.spelling(text)
        with self.lock:
            self.preview_text = ""
            if not self.config["audio"].get("live_transcription", False) and self.dedup.duplicate(text):
                return
            if self.config["audio"].get("manual_capture", True):
                self.transcript = (self.transcript + "\n" + text).strip()
            else:
                self.transcript = text
            context = any(x["status"] == "done" for x in self.history)
        self.events.transcript.emit(self.transcript)
        self.publish()
        if self.config["audio"]["auto_submit"] and not self.config["audio"].get("live_transcription", False) and is_question(text, context):
            self.submit(text)
        else:
            self.set_status("已转写：未自动提交，可编辑后手动回答")

    def messages(self, question):
        config = self.config
        template = next(t for t in config["templates"] if t["id"] == config["template"])
        if config.get("fast_answers", True):
            template = dict(template)
            template["system"] += "\n当前使用快速口头参考模式：先直接给一句结论，再补充必要理由；通常150～220字。若当前问题明确要求详细解释或推导，再适当展开。必须保留事实边界与关键限制。"
        bg = next(b["text"] for b in config["backgrounds"] if b["id"] == config["background_id"]) if config["use_background"] else ""
        with self.lock:
            history = [h for h in self.history if h.get("status") == "done"]
            if config.get("fast_answers", True):
                count = config.get("fast_history_pairs", 2)
                history = history[-count:] if count else []
            messages = assemble(template, question, history, bg, config["context_chars"])
        return messages

    def provider_adapter(self, config, key):
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=False,
                                            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4, keepalive_expiry=120))
        return adapter(config, key, shared_client=self.client)

    def submit(self, question):
        if self.closing:
            return
        entered = time.monotonic()
        intent_at = self.pending_submit_at or entered
        self.pending_submit_at = None
        question = normalize(question)
        try:
            messages = self.messages(question)
        except ValueError as exc:
            self.events.error.emit(str(exc))
            return
        provider_id = self.selected_provider
        config = copy.deepcopy(self.config)
        preparation = time.monotonic() - entered
        self.loop.call_soon_threadsafe(self._launch, question, messages, provider_id, config, intent_at, entered, preparation)

    def _launch(self, question, messages, provider_id, config, intent_at, entered, preparation):
        self._cancel()
        self.task = self.loop.create_task(self._generate(question, messages, provider_id, config, intent_at, entered, preparation))

    def _cancel(self):
        if self.task and not self.task.done():
            self.task.cancel()

    def cancel(self):
        self.loop.call_soon_threadsafe(self._cancel)

    async def _generate(self, question, messages, provider_id, config, intent_at, entered, preparation):
        entry = {"id": uuid.uuid4().hex, "question": question, "answer": "", "status": "generating", "model": "", "elapsed": 0, "usage": {}, "phase": "preparing", "started_at": intent_at,
                 "timings": {"transcription_tail": round(entered - intent_at, 3), "prepare": round(preparation, 3)}}
        with self.lock:
            self.history.append(entry)
            self.history[:] = self.history[-30:]
        providers = [provider_id]
        if config["fallback_provider"] and config["fallback_provider"] != provider_id:
            providers.append(config["fallback_provider"])
        started = time.monotonic()
        try:
            for index, pid in enumerate(providers):
                provider = next((p for p in config["providers"] if p["id"] == pid and p["enabled"]), None)
                if not provider:
                    raise ProviderError("选中的模型配置不存在或已禁用")
                entry["model"] = provider["name"] + " / " + provider["model"]
                self.set_status("正在生成答案：" + entry["model"])
                try:
                    credential_at = time.monotonic()
                    key = self.credentials.get(pid)
                    entry["timings"]["credential"] = round(time.monotonic() - credential_at, 3)
                except Exception:
                    raise ProviderError("无法读取 Windows 凭据管理器") from None
                try:
                    provider = dict(provider)
                    provider["fast_mode"] = config.get("fast_answers", True) and provider.get("fast_mode", False)
                    async for chunk in self.provider_adapter(provider, key).stream(messages):
                        with self.lock:
                            first_text = bool(chunk.get("text")) and not entry["answer"]
                            entry["answer"] += chunk.get("text", "")
                            entry["usage"].update(chunk.get("usage", {}))
                            entry["timings"].update(chunk.get("timings", {}))
                            entry["phase"] = chunk.get("phase", entry["phase"])
                            entry["attempt"] = chunk.get("attempt", entry.get("attempt", 1))
                            entry["elapsed"] = round(time.monotonic() - started, 2)
                            if first_text:
                                entry["timings"]["submit_to_first_token"] = round(time.monotonic() - intent_at, 3)
                        self.publish(force=first_text or chunk.get("phase") in ("request", "waiting_text", "reasoning", "retrying"))
                    entry["status"] = "done"
                    self.set_status("答案已完成")
                    break
                except ProviderError:
                    if entry["answer"] or index == len(providers) - 1:
                        raise
                    self.set_status("主模型失败，正在尝试备用模型")
        except asyncio.CancelledError:
            entry["status"] = "cancelled"
            # Don't let the cancelled task overwrite a newer request's global status.
            if self.task is asyncio.current_task():
                self.set_status("已取消生成")
        except ProviderError as exc:
            entry["status"] = "error"
            self.set_status("生成失败：" + str(exc))
            self.events.error.emit(str(exc))
        except Exception:
            entry["status"] = "error"
            self.set_status("生成失败：内部错误，请检查配置")
        finally:
            entry["elapsed"] = round(time.monotonic() - intent_at, 2)
            entry["timings"]["total"] = entry["elapsed"]
            self.publish(force=True)
            self.persist()

    def persist(self):
        path = self.store.root / "history.json"
        try:
            if self.config["save_history"]:
                with self.lock:
                    text = json.dumps(self.history, ensure_ascii=False, indent=2)
                temp = path.with_suffix(".tmp")
                temp.write_text(text, encoding="utf-8")
                temp.replace(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            self.events.error.emit("历史记录保存或删除失败，请检查文件权限")

    def clear(self):
        async def clear_task():
            if self.task and not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            with self.lock:
                self.history.clear()
                self.transcript = ""
                self.preview_text = ""
                self.dedup.clear()
            self.events.transcript.emit("")
            self.set_status("已开启新会话")
            self.persist()
        asyncio.run_coroutine_threadsafe(clear_task(), self.loop)

    def test_provider(self, pid):
        config = copy.deepcopy(next(p for p in self.config["providers"] if p["id"] == pid))
        async def test():
            try:
                provider = self.provider_adapter(config, self.credentials.get(pid))
                models = await provider.models()
                if config["model"] not in models:
                    raise ProviderError("连接成功，但配置的模型未出现在 /models 返回列表中")
                self.events.info.emit("模型可用性检查通过。正在发送简短流式测试请求（可能计费）…")
                pieces = []
                async for chunk in provider.stream([{"role": "user", "content": "请只回答：连接成功"}]):
                    pieces.append(chunk.get("text", ""))
                self.events.info.emit("真实流式连接测试通过：" + "".join(pieces)[:100])
            except ProviderError as exc:
                self.events.error.emit(str(exc))
            except Exception:
                self.events.error.emit("连接测试失败，请检查凭据管理器和配置")
        asyncio.run_coroutine_threadsafe(test(), self.loop)

    def close(self):
        self.closing = True
        self.audio.stop()
        self.companion.stop()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.persist()
