# 声答 · 实时语音问答助手 0.5（Windows + 手机伴侣）

Windows 实时语音问答助手，支持本地中文转写、DeepSeek 流式回答、全局快捷键和局域网手机伴侣。适用于经过允许的面试、学术答辩、会议与技术交流。默认不保存原始音频，不自动开始采集；参考答案需自行核实。

## 界面更新

灰白工作区、青绿色主按钮与统一线性图标；左侧编辑问题和浏览历史，右侧专注参考答案，底部集中收音控制。顶部直接切换模型、模板与资料，并显示收音/生成/异常状态。空白与等待状态有明确提示，设置页统一中文保存按钮与表单样式。手机端采用相同配色。

界面使用原生Qt和缓存SVG图标，不增加网络素材或持续动画，保留首字即时与后续增量刷新。字体大小仍可调。检查覆盖1180×780、980×680、960×660与1440宽度；布局检查记录保留在开发环境，不随发布提供。详见docs/UI.md。

## 启动与升级

从本仓库的 Releases 下载 VoiceCompanion-Windows-x64-v0.5.zip。退出托盘中的旧程序，完整解压后运行 VoiceCompanion/VoiceCompanion.exe。保留整个目录的_internal、models和scripts，不能只复制exe。便携版无需Python，不含用户Key。

源码运行：双击Start.cmd，首次使用会创建项目.venv、安装requirements.txt并下载约42MB Vosk中文模型。需要Windows 10/11 x64与Python 3.10 x64（推荐；源码支持3.10～3.12，暂不支持3.13）。建议在项目独立虚拟环境中安装依赖。

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python scripts\download_model.py
.\.venv\Scripts\python main.py
```

也可指定解释器：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 -PythonPath 'C:\Python310\python.exe'
```

新版本沿用本机配置、模板、背景资料及Windows凭据。首次运行会按需迁移设置，不包含或导出Key。

## 日常使用

- Ctrl+Alt+L开始收音，文字逐步显示；再按一次结束，确认尾句后自动生成。初次加载识别模型需要时间。
- Ctrl+Alt+Enter手动生成；收音中使用会先结束并等待最终文本。
- Ctrl+Alt+X取消生成；Ctrl+Alt+N新会话；Ctrl+Alt+M切换模型；Ctrl+Alt+H显示/隐藏；Ctrl+Alt+S设置。全部可修改并检查占用。
- 放弃本段/停止设备用于取消本段并释放设备；新会话也会停止当前收音。最小化和失去焦点不自动停采，关闭窗口会退出释放资源。
- 在音频设置关闭结束后自动生成，可以先核对文字再提交；关闭实时转写可改为暂停后整段识别。单段默认上限60秒。

## 回答延迟与快速模式

- 连接池复用HTTP连接，退出时关闭；取消请求不会关闭整个共享池。
- 首个正文立即推送，其余片段以最多约20次/秒合并更新。答案增量追加，历史列表仅在条目/状态变化时重建，避免每个字都刷新全界面。
- 主窗口可切换快速回答：保留全部选中的背景资料，默认只携带最近2轮完整对话，先给简短结论。关闭快速回答可使用完整预算内历史和原模板长度。
- DeepSeek官方配置可在快速模式下明确关闭思考；不擅自切换模型。其他兼容供应商不自动加入DeepSeek特有参数。
- 请求状态显示准备、等待接口、已连接等待正文、服务端思考、重试或正文输出，并显示转写收尾、首字和总耗时。
- 已被服务端接受的超时请求不自动重复发送；连接失败及明确429/5xx按配置有限重试，避免隐形等待与重复费用。

本机当前真实简短测试：首字约0.72～1.33秒，最后一次桌面可见首字1.33秒、两句回答约1.92秒完成。这些样本不能保证其他问题的响应时间。服务排队、问题复杂度、上下文、网络及模型均影响速度，详见docs/PERFORMANCE.md。

## 模型与Key

设置→模型与凭据：填写供应商、OpenAI Chat Completions协议Base URL、模型及参数，单独保存Key。Base URL会追加/chat/completions和/models，不填完整completion地址。当前优先支持DeepSeek官方，预置https://api.deepseek.com与deepseek-flash；其他兼容服务需逐一测试。未实现Anthropic/Gemini原生协议和云ASR。

Key仅存Windows Credential Manager，服务名VoiceCompanion.API，按配置ID隔离；复制配置需要另存Key。连接测试会检查/models并发送一句真实请求，可能计费。删除配置前可先删除其Key。程序不跟随重定向、不自动使用环境代理。

## 语音准确率

线上交流优先选实际播放声音的系统输出设备；混合模式是两路采集和文本去重，不是声学回声消除。麦克风尽量减少混响和背景噪声。能量阈值与最短长度用于过滤无效段，不能替代更好的语音模型。

可从https://alphacephei.com/vosk/models下载约1.3GB的vosk-model-cn-0.22，解压到models下英文目录，设置选择包含am的模型根目录。中文大模型在官方测试集较好，但更占内存，本机尚未评测其准确率和延迟。默认小模型适合低资源运行，专业词仍需核对。

术语拼写替换是明确的字面替换，例如史密斯→Smith；不是声学热词。个人资料与提示词影响回答，当前不训练语音模型。临时识别可能修正，结束后才提交最终文本。

## 提示词与个人资料

模板规定回答方式，资料提供事实。模板支持question、history、background、style、format、length变量，使用花括号包围。程序通常通过多轮消息传历史，无需再次手动填history。最终请求受总字符预算限制，背景与当前问题过长会提示，不能把字符数当token数。

可导入UTF-8 TXT/MD、DOCX、有文本层PDF，文件上限10MB；不支持扫描OCR和PPTX直接导入，也没有向量检索。导入后核对提取的文字。设置场景后在主界面勾选使用背景资料，再用预览最终提示词核对实际发送内容。

通用示例位于 examples/templates.json 和 examples/settings.example.json。个人资料由使用者在本机录入或导入，不随发布包分发。修改设置前先停止音频设备。

## 手机连接

1. 手机与电脑连接同一可信Wi-Fi，进入手机配对，确认自动选中的局域网IPv4，启动并生成新二维码；手机不能用127.0.0.1。
2. 网页打不开时检查VPN、访客网络/AP隔离；必要时点击修复本机防火墙并完成管理员授权。规则仅允许同一子网访问指定exe、私网地址和TCP端口，适用于Private/Public类别，不关闭防火墙或映射公网。
3. 令牌单次、3分钟有效；配对Cookie 12小时，重启服务需重新配对。断线自动重连并恢复最近30条快照。
4. 默认发送问题、答案和状态，可选实时转写；不发原始音频、API Key、背景原文或系统提示词，但答案可能引用背景信息。
5. 手机清空本机显示只隐藏本标签记录；电脑新会话清除当前对话；可解除全部配对或停止服务。局域网HTTP不加密，只用于可信网络，公网远程访问未实现。

## 本机存储与日志

配置与手动保存资料位于%LOCALAPPDATA%/VoiceCompanion/settings.json。默认不保存问答历史；启用后保存最近30条明文history.json，关闭即删除该文件。日志只记固定启动/停止/错误事件，不记Key、令牌、提示词或回答。可用VOICE_ASSISTANT_DATA指定数据目录。

## 测试与打包

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python scripts\verify_streaming_windows.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
```

声音集成测试会播放并回采明确的合成语音，不采麦克风、不调用外部模型；其本地HTTP模型是明确的测试夹具。实际DeepSeek测试脚本measure_deepseek_latency.py和verify_deepseek_ui.py会使用本机凭据发少量真实请求，可能计费，仅保存计时与字符数，不保存提示词/回答/Key。不要把固定测试输出当成真实模型验证。

测试与当前验收见docs/VALIDATION.md。常见排查：无音量时检查输出设备；模型失败检查am目录和英文模型目录名；401检查当前配置ID的Key；404检查模型和Base URL；等待正文时间长看阶段计时、关闭思考或精简上下文；快捷键失败检查系统占用。完整答案时间不能仅凭本地网络首字测试保证。
