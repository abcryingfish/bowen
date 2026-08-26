# word_turn_voice

本地文字转语音播报工具：每隔一段时间检查 UTF-8 文本文件，只读取新增内容，按句切分后进入 FIFO 队列，并播放到 Windows 当前默认音频设备。

## 推荐后端

优先使用 `sherpa-onnx` 的中文离线 TTS 模型。模型文件不随项目提交，放在本机后通过 `config.json` 配置。没有模型时可以启用 `pyttsx3` 回退，但系统 SAPI 音色的自然度会低于神经网络模型。

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
..\.venv\Scripts\python.exe main.py
```

将新增文字追加到 `inbox.txt`。程序默认从文件末尾开始监听，不会启动时重复朗读旧内容。

GUI 中可以直接输入文字，选择中文声音和语速，然后点击“导出 MP3”保存为本地 MP3 文件。MP3 使用本地 LAME 编码器生成，不需要联网或安装 FFmpeg。

当前提供 8 个可直接选择的本地音色：苏映雪、男声-姑娘、符诗玉、冰娇、霸总、小雅、超文和华颜。切换到另一套模型时首次播报会重新加载模型。

监听文件同时支持追加和覆盖修改：追加时只播报新增部分；覆盖、缩短、同长度修改或原地改写时，播报修改后的完整文件内容。文件必须使用 UTF-8 编码。

每次实时播报和导出的 MP3 都会在音频开头加入 1.5 秒静音、结尾加入 120 毫秒静音，用于防止播放器或系统音频输出截断首尾内容。

双击 `dist/word_turn_voice/word_turn_voice.exe` 启动 GUI。请保留旁边的 `_internal` 和 `models` 目录。

## 宝丰能源自动播报

运行 `启动宝丰能源每分钟播报.bat`，脚本会每 60 秒访问东方财富公开行情接口，并把宝丰能源（600989.SH）的当前价格和涨跌幅追加到 `dist/word_turn_voice/inbox.txt`，运行中的语音 EXE 会自动播报。

使用顺序：先双击 `dist/word_turn_voice/word_turn_voice.exe`，再双击项目目录中的 `启动宝丰能源每分钟播报.bat`。两个程序可以分别关闭；行情监控带有单实例保护，重复双击不会产生重复播报。

先测试一次：

```powershell
..\.venv\Scripts\python.exe eastmoney_baofeng_monitor.py --once
```

行情接口需要联网；网络失败时不会写入伪造数据。按 `Ctrl+C` 停止每分钟轮询。

## 模型配置

`config.json` 中 `tts.backend` 可设为 `sherpa_onnx` 或 `pyttsx3`。sherpa-onnx 需要填写 `model`、`tokens` 和 `data_dir`，具体文件名以所下载模型的发布说明为准。

所有文本文件按 UTF-8 读取和写入，避免中文乱码。程序不访问网络。
