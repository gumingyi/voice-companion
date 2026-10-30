"""WASAPI loopback and microphone capture; independent lanes avoid clock drift.

No PCM is written to disk. Queue limits bound RAM and latency. Energy VAD is
deliberately configurable; it is not an acoustic echo cancellation system.
"""
import audioop
from collections import deque
import queue
import threading
import time

class Segmenter:
    def __init__(self, silence_ms=1000, min_speech_ms=500, max_segment_ms=25000, rms_threshold=300):
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.max_segment_ms = max_segment_ms
        self.threshold = rms_threshold
        self.reset()

    def reset(self):
        self.chunks = []
        self.pre = deque(maxlen=5)
        self.voiced = self.silence = self.duration = 0

    def feed(self, pcm):
        ms = len(pcm) / 32  # 16kHz int16 mono
        voice = audioop.rms(pcm, 2) >= self.threshold
        if not self.chunks and not voice:
            self.pre.append(pcm)
            return None
        if not self.chunks:
            self.chunks.extend(self.pre)
            self.pre.clear()
        self.chunks.append(pcm)
        self.duration += ms
        self.voiced += ms if voice else 0
        self.silence = 0 if voice else self.silence + ms
        if self.silence >= self.silence_ms or self.duration >= self.max_segment_ms:
            result = b"".join(self.chunks) if self.voiced >= self.min_speech_ms else None
            self.reset()
            return result
        return None

    def finish(self):
        result = b"".join(self.chunks) if self.voiced >= self.min_speech_ms else None
        self.reset()
        return result

def devices():
    import pyaudiowpatch as pa
    with pa.PyAudio() as p:
        loops = list(p.get_loopback_device_info_generator())
        mics = [p.get_device_info_by_index(i) for i in range(p.get_device_count())]
        mics = [d for d in mics if d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice")]
        return {"system": [{"id": int(d["index"]), "name": d["name"]} for d in loops],
                "mic": [{"id": int(d["index"]), "name": d["name"]} for d in mics]}

class AudioEngine:
    def __init__(self, recognizer_factory, on_text, on_status, on_level):
        self.factory, self.on_text, self.on_status, self.on_level = recognizer_factory, on_text, on_status, on_level
        self.stop_event = threading.Event()
        self.paused = threading.Event()
        self.threads = []
        self.streams = []
        self.lock = threading.Lock()
        self.q = queue.Queue(maxsize=6)
        self.generation = 0
        self.last_drop = 0
        self.flush_events = {}
        self.busy = threading.Event()
        self.manual = True

    @property
    def running(self):
        return bool(self.threads)

    def start(self, config):
        if self.running:
            return
        self.stop_event.clear()
        self.paused.clear()
        self.generation += 1
        self.q = queue.Queue(maxsize=6)
        self.manual = config.get("manual_capture", True)
        self.threads = [threading.Thread(target=self._recognize, name="speech", daemon=True)]
        modes = ["system", "mic"] if config["mode"] == "mixed" else [config["mode"]]
        self.flush_events = {mode: threading.Event() for mode in modes}
        for mode in modes:
            self.threads.append(threading.Thread(target=self._capture, args=(mode, config), name="audio-" + mode, daemon=True))
        for thread in self.threads:
            thread.start()

    def pause(self, paused):
        if self.paused.is_set() == paused:
            return
        if not self.manual:
            self.generation += 1
        if paused:
            self.paused.set()
        else:
            for event in self.flush_events.values():
                event.clear()
            self.paused.clear()
        self.on_status("已暂停收音，正在整理本段文字" if paused else "正在收音；按开始/暂停快捷键结束本段")

    @property
    def settled(self):
        return (not self.running or all(e.is_set() for e in self.flush_events.values())) and self.q.unfinished_tasks == 0 and not self.busy.is_set()

    def _capture(self, mode, config):
        import pyaudiowpatch as pa
        stream = None
        try:
            with pa.PyAudio() as p:
                selected = config[mode + "_device"]
                if selected is None:
                    info = p.get_default_wasapi_loopback() if mode == "system" else p.get_default_input_device_info()
                else:
                    info = p.get_device_info_by_index(int(selected))
                if mode == "system" and not info.get("isLoopbackDevice"):
                    raise ValueError("选择的系统设备不是 WASAPI Loopback")
                channels, rate = min(2, int(info["maxInputChannels"])), int(info["defaultSampleRate"])
                raw_queue = queue.Queue(maxsize=40)
                def callback(data, frame_count, time_info, flags):
                    if self.stop_event.is_set():
                        return None, pa.paComplete
                    if self.paused.is_set():
                        return None, pa.paContinue
                    try:
                        raw_queue.put_nowait((self.generation, data))
                    except queue.Full:
                        try:
                            raw_queue.get_nowait()
                            raw_queue.put_nowait((self.generation, data))
                        except (queue.Empty, queue.Full):
                            pass
                    return None, pa.paContinue
                stream = p.open(format=pa.paInt16, channels=channels, rate=rate, input=True,
                                input_device_index=int(info["index"]), frames_per_buffer=max(1, rate // 20), stream_callback=callback)
                with self.lock:
                    self.streams.append(stream)
                segmenter = Segmenter(**{k: config[k] for k in ("silence_ms", "min_speech_ms", "max_segment_ms", "rms_threshold")})
                if self.manual:
                    segmenter.silence_ms = float("inf")
                state = None
                epoch = self.generation
                self.on_status("正在监听：" + info["name"])
                while not self.stop_event.is_set():
                    if self.paused.is_set():
                        if not self.flush_events[mode].is_set():
                            if self.manual:
                                while True:
                                    try:
                                        queued_epoch, queued = raw_queue.get_nowait()
                                    except queue.Empty:
                                        break
                                    if queued_epoch != epoch:
                                        continue
                                    if channels == 2:
                                        queued = audioop.tomono(queued, 2, .5, .5)
                                    queued, state = audioop.ratecv(queued, 2, 1, rate, 16000, state)
                                    full = segmenter.feed(queued)
                                    if full:
                                        self.q.put((epoch, full), timeout=1)
                            segment = segmenter.finish() if self.manual else None
                            if segment:
                                self.q.put((epoch, segment), timeout=1)
                            state = None
                            self.flush_events[mode].set()
                        self.stop_event.wait(.02)
                        continue
                    # WASAPI can stop producing packets when playback ends.
                    # Poll our callback queue, never block inside stream.read().
                    try:
                        frame_epoch, data = raw_queue.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if self.paused.is_set() or epoch != self.generation or frame_epoch != self.generation:
                        segmenter.reset()
                        epoch = self.generation
                        state = None
                        continue
                    if channels == 2:
                        data = audioop.tomono(data, 2, .5, .5)
                    data, state = audioop.ratecv(data, 2, 1, rate, 16000, state)
                    self.on_level(mode, audioop.rms(data, 2))
                    segment = segmenter.feed(data)
                    if segment:
                        try:
                            self.q.put_nowait((epoch, segment))
                            if self.manual:
                                self.pause(True)
                                self.on_status("本段达到时长上限，已自动暂停收音并转写；可核对文字后生成答案")
                        except queue.Full:
                            if time.monotonic() - self.last_drop > 5:
                                self.last_drop = time.monotonic()
                                self.on_status("转写处理过慢，已丢弃一段音频；请提高阈值或使用更快模型")
        except Exception:
            if not self.stop_event.is_set():
                self.on_status("音频采集失败（" + mode + "）：检查设备是否存在、被占用及 Windows 麦克风权限；停止后重新选择设备")
        finally:
            self.flush_events[mode].set()
            if stream is not None:
                try:
                    if stream.is_active():
                        stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
                with self.lock:
                    if stream in self.streams:
                        self.streams.remove(stream)

    def _recognize(self):
        try:
            self.on_status("正在加载本地中文识别模型")
            recognizer = self.factory()
        except Exception as exc:
            self.on_status(str(exc) if isinstance(exc, ValueError) else "本地语音识别模型加载失败，请检查模型目录")
            self.stop_event.set()
            return
        while not self.stop_event.is_set():
            try:
                epoch, pcm = self.q.get(timeout=.2)
            except queue.Empty:
                continue
            if (self.paused.is_set() and not self.manual) or epoch != self.generation:
                self.q.task_done()
                continue
            try:
                self.busy.set()
                self.on_status("正在转写")
                text = recognizer.transcribe(pcm)
                if text.strip() and not self.stop_event.is_set() and (self.manual or not self.paused.is_set()) and epoch == self.generation:
                    self.on_text(text)
                if not self.paused.is_set() and not self.stop_event.is_set():
                    self.on_status("正在监听 / 等待问题结束")
            except Exception:
                self.on_status("语音识别失败；可停止并重新监听")
            finally:
                self.busy.clear()
                self.q.task_done()

    def stop(self):
        self.stop_event.set()
        self.generation += 1
        for thread in self.threads:
            thread.join(timeout=8)
        alive = [t for t in self.threads if t.is_alive()]
        self.threads = alive
        if alive:
            self.on_status("音频线程尚未退出，请等待后再次停止")
        else:
            self.on_status("已停止监听，音频设备已释放")
        return not alive
