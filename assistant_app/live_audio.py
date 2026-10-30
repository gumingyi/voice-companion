"""Incremental ASR during explicitly bounded capture sessions.

One decoder per source; one recognition worker owns all native decoders. Finish
markers are queued after every captured pre-pause frame. UI can safely wait on
settled before issuing one model request. No question is submitted for partials.
"""
import audioop
from difflib import SequenceMatcher
import queue
import threading
import time
from .audio import AudioEngine
from .questions import normalize, fingerprint

def merge_sources(texts):
    unique = []
    for text in texts:
        text = normalize(text)
        if not text:
            continue
        value = fingerprint(text)
        match = next((i for i, old in enumerate(unique) if value == fingerprint(old) or (min(len(value), len(fingerprint(old))) >= 6 and SequenceMatcher(None, value, fingerprint(old)).ratio() >= .88)), None)
        if match is None:
            unique.append(text)
        elif len(text) > len(unique[match]):
            unique[match] = text
    return "\n".join(unique)

class StreamingAudioEngine(AudioEngine):
    def __init__(self, *args, on_partial=None):
        super().__init__(*args)
        self.on_partial = on_partial or (lambda _: None)
        self.cycle = 0
        self.session_error = False
        self.final_text = ""

    def start(self, config):
        if self.running:
            return
        self.config = config.copy()
        self.manual = True
        self.cycle += 1
        self.session_error = False
        self.final_text = ""
        self.stop_event.clear()
        self.paused.clear()
        self.q = queue.Queue(maxsize=400)  # ~80 seconds of 200ms chunks; bounded PCM RAM.
        self.modes = ["system", "mic"] if config["mode"] == "mixed" else [config["mode"]]
        self.flush_events = {mode: threading.Event() for mode in self.modes}
        self.threads = [threading.Thread(target=self._recognize, name="streaming-speech", daemon=True)]
        self.threads += [threading.Thread(target=self._capture, args=(mode, config), name="live-" + mode, daemon=True) for mode in self.modes]
        for thread in self.threads:
            thread.start()

    def pause(self, paused):
        if self.paused.is_set() == paused:
            return
        if paused:
            self.paused.set()
            self.on_status("已结束收音，正在确认最后几个字")
        else:
            if not self.settled:
                self.on_status("上一段尚未确认完成，请稍候")
                return
            self.cycle += 1
            self.session_error = False
            self.final_text = ""
            for event in self.flush_events.values():
                event.clear()
            self.paused.clear()
            self.on_status("正在边听边识别；再次按快捷键结束并回答")

    def _put(self, kind, cycle, mode, payload):
        while not self.stop_event.is_set():
            try:
                self.q.put((kind, cycle, mode, payload), timeout=.1)
                return
            except queue.Full:
                if not self.session_error:
                    self.session_error = True
                    self.pause(True)
                    self.on_status("识别跟不上收音，已暂停；本段请核对后手动提交")

    def _capture(self, mode, config):
        import pyaudiowpatch as pa
        stream = None
        try:
            with pa.PyAudio() as p:
                selected = config[mode + "_device"]
                info = (p.get_default_wasapi_loopback() if mode == "system" else p.get_default_input_device_info()) if selected is None else p.get_device_info_by_index(int(selected))
                if mode == "system" and not info.get("isLoopbackDevice"):
                    raise ValueError("所选设备不是 Loopback")
                channels, rate = min(2, int(info["maxInputChannels"])), int(info["defaultSampleRate"])
                raw = queue.Queue(maxsize=100)
                def callback(data, frames, timing, flags):
                    if self.stop_event.is_set():
                        return None, pa.paComplete
                    if not self.paused.is_set():
                        try:
                            raw.put_nowait((self.cycle, data))
                        except queue.Full:
                            self.session_error = True
                            self.paused.set()
                    return None, pa.paContinue
                stream = p.open(format=pa.paInt16, channels=channels, rate=rate, input=True, input_device_index=int(info["index"]), frames_per_buffer=max(1, rate // 20), stream_callback=callback)
                with self.lock:
                    self.streams.append(stream)
                seen, flushed, state, voiced = 0, False, None, 0
                pending = bytearray()
                self.on_status("正在边听边识别：" + info["name"])
                while not self.stop_event.is_set():
                    if seen != self.cycle:
                        seen, flushed, state, voiced = self.cycle, False, None, 0
                        pending.clear()
                        started = time.monotonic()
                        self._put("open", seen, mode, None)
                    if not self.paused.is_set() and (time.monotonic() - started) * 1000 >= config["max_segment_ms"]:
                        self.pause(True)
                    try:
                        cycle, data = raw.get(timeout=.05)
                    except queue.Empty:
                        if self.paused.is_set() and not flushed:
                            if pending:
                                self._put("audio", seen, mode, bytes(pending))
                                pending.clear()
                            self._put("finish", seen, mode, voiced >= config["min_speech_ms"])
                            flushed = True
                            self.flush_events[mode].set()
                        continue
                    if cycle != seen or flushed:
                        continue
                    if channels == 2:
                        data = audioop.tomono(data, 2, .5, .5)
                    data, state = audioop.ratecv(data, 2, 1, rate, 16000, state)
                    rms = audioop.rms(data, 2)
                    self.on_level(mode, rms)
                    if rms >= config["rms_threshold"]:
                        voiced += len(data) / 32
                    pending.extend(data)
                    if len(pending) >= 6400:
                        self._put("audio", seen, mode, bytes(pending))
                        pending.clear()
        except Exception:
            if not self.stop_event.is_set():
                self.session_error = True
                self.pause(True)
                self.on_status("实时音频采集失败（" + mode + "）；请停止后检查设备，本段不自动提交")
                self._put("finish", self.cycle, mode, False)
        finally:
            self.flush_events[mode].set()
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
                with self.lock:
                    if stream in self.streams:
                        self.streams.remove(stream)

    def _recognize(self):
        try:
            self.on_status("正在加载中文模型，已收取的音频会排队识别")
            recognizer = self.factory()
            if not callable(getattr(recognizer, "streaming_session", None)):
                raise ValueError("当前识别器不支持实时会话，请关闭实时转写选项")
        except Exception as exc:
            self.session_error = True
            self.on_status(str(exc) if isinstance(exc, ValueError) else "中文模型加载失败，请检查目录或内存")
            self.paused.set()
            self.stop_event.set()
            while True:
                try:
                    self.q.get_nowait()
                    self.q.task_done()
                except queue.Empty:
                    break
            return
        sessions, texts, finished = {}, {}, set()
        active_cycle, last_preview, last_emit = -1, "", 0
        while not self.stop_event.is_set():
            try:
                kind, cycle, mode, payload = self.q.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                self.busy.set()
                if cycle != self.cycle:
                    continue
                if active_cycle != cycle:
                    sessions, texts, finished = {}, {}, set()
                    active_cycle, last_preview = cycle, ""
                if kind == "open":
                    sessions[mode] = recognizer.streaming_session()
                    texts[mode] = ""
                elif kind == "audio" and mode in sessions:
                    texts[mode] = sessions[mode].feed(payload)
                elif kind == "finish":
                    texts[mode] = sessions[mode].finish() if payload and mode in sessions else ""
                    finished.add(mode)
                combined = merge_sources(texts.get(source, "") for source in self.modes)
                if self.stop_event.is_set():
                    continue
                now = time.monotonic()
                if combined != last_preview and (now - last_emit >= .15 or kind == "finish"):
                    self.on_partial(combined)
                    last_preview, last_emit = combined, now
                if kind == "finish" and finished == set(self.modes):
                    self.final_text = combined
                    if combined:
                        self.on_text(combined)
                    else:
                        self.on_partial("")
                        self.on_status("未识别到有效语音，可重新收音或直接输入问题")
            except Exception:
                self.session_error = True
                self.pause(True)
                self.on_status("实时识别失败，本段不会自动提交；请核对文字")
            finally:
                self.busy.clear()
                self.q.task_done()
