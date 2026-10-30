import json
import os
import ctypes
from pathlib import Path
from typing import Protocol

class SpeechRecognizer(Protocol):
    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str: ...

class VoskRecognizer:
    def __init__(self, model_path):
        from vosk import Model, SetLogLevel
        path = Path(model_path)
        if not (path / "am").is_dir():
            raise ValueError("未找到 Vosk 模型：请运行 scripts/download_model.py 或在设置中选择解压后的模型目录")
        SetLogLevel(-1)
        # Vosk's Windows C runtime opens narrow paths. A relative ASCII path
        # works even when the current project directory has Chinese characters.
        relative = os.path.relpath(path.resolve(), Path.cwd()) if path.resolve().drive == Path.cwd().drive else str(path.resolve())
        native = relative
        if not native.isascii():
            buffer = ctypes.create_unicode_buffer(32768)
            size = ctypes.windll.kernel32.GetShortPathNameW(str(path.resolve()), buffer, len(buffer))
            if not size or not buffer.value.isascii():
                raise ValueError("Vosk 原生库不支持此模型路径；请把模型放在项目 models 下并使用纯英文模型文件夹名")
            native = buffer.value
        self.model = Model(native)

    def streaming_session(self, sample_rate=16000):
        return VoskStream(self.model, sample_rate)

    def transcribe(self, pcm, sample_rate=16000):
        from vosk import KaldiRecognizer
        recognizer = KaldiRecognizer(self.model, sample_rate)
        parts = []
        for start in range(0, len(pcm), 8000):
            if recognizer.AcceptWaveform(pcm[start:start + 8000]):
                parts.append(json.loads(recognizer.Result()).get("text", ""))
        parts.append(json.loads(recognizer.FinalResult()).get("text", ""))
        return " ".join(x for x in parts if x)

class VoskStream:
    """Persistent decoder: partial hypotheses may change; finish commits the tail."""
    def __init__(self, model, sample_rate=16000):
        from vosk import KaldiRecognizer
        self.recognizer = KaldiRecognizer(model, sample_rate)
        self.completed = []

    def feed(self, pcm):
        if self.recognizer.AcceptWaveform(pcm):
            text = json.loads(self.recognizer.Result()).get("text", "")
            if text:
                self.completed.append(text)
            partial = ""
        else:
            partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
        return " ".join(self.completed + ([partial] if partial else []))

    def finish(self):
        text = json.loads(self.recognizer.FinalResult()).get("text", "")
        if text:
            self.completed.append(text)
        return " ".join(self.completed)
