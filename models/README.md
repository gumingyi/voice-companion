运行 `.venv\Scripts\python scripts\download_model.py` 从 Vosk 官方下载小中文模型。
首次运行 Start.cmd 也会自动下载。模型为 Apache 2.0，来源 https://alphacephei.com/vosk/models 。
也可手动解压其他 Vosk 中文模型并在设置里选择包含 `am` 的目录。
小模型主要用于低资源启动，专业术语和远场语音识别需用实际材料评测。
`download_record.json` 记录下载文件 SHA-256，仅用于复现，不等于上游数字签名。
