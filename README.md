# 听课稿 · LectureInk

Windows 原生桌面听课翻译工具：直接理解音频，生成持续累积的中文／双语文稿。

Native Windows lecture translation with direct audio understanding and a continuous bilingual transcript.

## 下载 v0.1

在 [Releases](https://github.com/Alan1112223331/LectureInk/releases/latest) 下载 `LectureInk-v0.1-Windows-x64.zip`，解压后运行 `LectureInk.exe`。

Windows 10（1903 或更新版本）／Windows 11，64 位。最终用户不需要安装 Python 或其他依赖，需要联网并填写自己的硅基流动 API Key。EXE 未做代码签名。

## 功能

- 系统声音或麦克风输入，可选择具体设备。
- 使用硅基流动 `Qwen/Qwen3-Omni-30B-A3B-Instruct` 直接理解音频并生成原文和中文，不在本地转录。
- 本地 Silero VAD 先检测人声，降低静音、底噪触发无关文字的概率。
- 中文／双语显示，文稿持续累积，支持选择、复制、字号调整及 TXT、Markdown、HTML 导出。
- 可填写课程主题和术语表，并结合最近的文稿保持用词连贯。
- 默认 8 秒快速预览，保留重叠音频和短后文；待确认末句放在预览区，疑似句子边界错误会复听校正。
- 会话及原始音频自动保存，网络失败后可重试未处理部分。

## 使用

1. 打开“连接设置”，填写 API Key。
2. 选择声音来源和设备，按需填写课程主题／术语。
3. 点“开始听课”，播放课程或对麦克风讲话。
4. 结束时先暂停课程，再点“结束并处理剩余音频”。

首次预览需要先积累约 10 秒音频，再加模型处理时间；本程序按段上传音频，并流式接收文字。自动折行只改变显示，不将每个网络数据块变成独立段落。专业术语、公式和口音仍可能误译，“需核对”不是经过校准的置信度。

完整操作与恢复说明见 [使用说明](使用说明.md)。

## 数据与密钥

被提交的音频，以及填写的主题、术语和最近文稿，会发送给硅基流动。原始音频和会话保存在本机 `%LOCALAPPDATA%\LectureInk\sessions`。选择记住密钥时使用 Windows DPAPI 加密。

仓库和发布包不含 API Key、个人设置、课堂录音或用户文稿。`tests/assets/speech.wav` 是由固定公开文本重新合成的测试样本，说明见 [测试音频来源](tests/assets/README.md)。

## 从源码运行与构建

在 Windows x64 安装 Python 3.13 后：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\app.py
```

运行检查并生成独立 EXE：

```powershell
.\build.ps1
```

输出为 `dist\single\LectureInk.exe`。测试使用模拟接口和合成音频，不要求真实 API Key。构建配置会排除不兼容的第三方 ICU DLL，使用 Windows 提供的 ICU。

## 第三方组件

组件及许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [third_party/licenses](third_party/licenses)。Silero 模型的固定版本与校验值保存在 `src/assets/silero-source.json`。
