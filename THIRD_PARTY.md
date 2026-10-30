# 第三方组件

本程序使用动态链接的PySide6/Qt、PyAudioWPatch/PortAudio、Vosk/Kaldi及其离线中文模型，以及FastAPI、Uvicorn、HTTPX、keyring、qrcode、Pillow、websockets、pypdf和相关依赖。版本见requirements-lock.txt。便携包中third_party_licenses目录保存可取得的已安装包许可文本，组件内部许可仍适用。

- PySide6/Qt：LGPLv3/GPLv3或商业许可，动态库保留在_internal中。官方：https://doc.qt.io/qtforpython-6/licenses.html 。修改或再分发时请遵守相应许可。
- Vosk API及本项目选用的vosk-model-small-cn-0.22：Apache 2.0；模型来源：https://alphacephei.com/vosk/models ，下载记录见models/download_record.json（源码安装时生成）。
- 其他组件依其各自MIT/BSD/Apache等许可提供。打包工具PyInstaller采用带例外的GPL许可，见其官方说明及已安装版本许可。
- Playwright仅用于可选开发测试，不作为程序运行依赖，不在便携包中嵌入用户浏览器或浏览器个人资料。

本交付没有附带第三方服务API Key。使用模型服务需要用户自己的合法账号及相应服务条款。
