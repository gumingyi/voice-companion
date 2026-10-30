# 上传与发布

仓库根目录应为 voice_assistant，不要上传上级目录的论文、答辩稿和演示文稿。

## 首次上传源码

1. 在 GitHub 新建空仓库，建议先选择 Private。不要勾选生成 README、.gitignore 或 License，以免与本地文件冲突。
2. 复制仓库的 HTTPS 地址，例如 https://github.com/YOUR_NAME/voice-companion.git。
3. 在本项目目录打开 PowerShell，运行以下命令，将示例地址替换为真实地址：

```powershell
git add .
git diff --cached --stat
git commit -m "Initial release v0.5"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/voice-companion.git
git push -u origin main
```

本地如果尚未初始化，先运行 `git init`。已有 origin 时先用 `git remote -v` 核对，不要重复添加或盲目覆盖。Git for Windows 的凭据管理器可在推送时打开浏览器登录 GitHub。不要在聊天中粘贴密码或令牌，也不要把令牌嵌入仓库地址。

`.gitignore` 排除了虚拟环境、识别模型、构建产物、发布压缩包、个人答辩资料、本机验证附件和常见本地配置。提交前仍应检查暂存内容，尤其是新加的截图与文档。API Key 保存在 Windows 凭据管理器中，不随源码上传。

## 让别人下载运行

源码推送成功后，在仓库的 Releases 页面新建 v0.5 发布，上传本机 release/VoiceCompanion-Windows-x64-v0.5.zip 和 SHA256.json。便携版包含中文识别模型和 Python 运行时，应作为 Release 附件分发，不提交到 Git 历史。

接收者使用 Windows 10/11 x64，下载便携版并完整解压，运行 VoiceCompanion/VoiceCompanion.exe。保留 _internal、models、scripts 目录。首次运行填写自己的模型 API Key，并选择音频设备。

源码压缩包通过 Git 跟踪文件清单生成，不包含被忽略的个人资料与本机验证附件。发布前仍须检查打包内容。

## 后续更新

```powershell
git add .
git diff --cached --stat
git commit -m "Describe the change"
git push
```

本仓库不包含本机验证截图与结果附件，README 和验证说明中提到的部分本机路径不会随 Git 克隆提供。安装依赖并下载模型后，可按 README 重新运行测试。先不要为项目随意添加开源许可证；公开分发前由作者决定自己的源码授权，第三方依赖说明见 THIRD_PARTY.md。
