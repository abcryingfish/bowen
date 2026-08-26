"""Tkinter GUI for the offline text announcer."""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
import ctypes
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import main

VOICES = {
    "女声-苏映雪": {"speaker_id": 0},
    "男声-姑娘": {"speaker_id": 1},
    "女声-符诗玉": {"speaker_id": 2},
    "女声-冰娇": {"speaker_id": 3},
    "男声-霸总": {"speaker_id": 4},
    "女声-小雅": {
        "model": "models/xiao_ya/zh_CN-xiao_ya-medium.onnx", "tokens": "models/xiao_ya/tokens.txt",
        "lexicon": "models/xiao_ya/lexicon.txt", "data_dir": "",
        "rule_fsts": "models/xiao_ya/date.fst,models/xiao_ya/number.fst,models/xiao_ya/phone.fst", "speaker_id": 0,
    },
    "中文-超文": {
        "model": "models/chaowen/zh_CN-chaowen-medium.onnx", "tokens": "models/chaowen/tokens.txt",
        "lexicon": "models/chaowen/lexicon.txt", "data_dir": "",
        "rule_fsts": "models/chaowen/date.fst,models/chaowen/number.fst,models/chaowen/phone.fst", "speaker_id": 0,
    },
    "女声-华颜": {
        "model": "models/huayan/zh_CN-huayan-medium.onnx", "tokens": "models/huayan/tokens.txt",
        "lexicon": "", "data_dir": "models/huayan/espeak-ng-data", "rule_fsts": "", "speaker_id": 0,
    },
}


class VoiceApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("本地文字转语音")
        self.root.geometry("720x520")
        self.root.minsize(620, 420)
        self.config = main.load_config()
        self.input_path = Path(self.config["input_file"])
        self.backend = None
        self.backend_key = None
        self.last_file_bytes = self.input_path.read_bytes() if self.input_path.exists() else b""
        self.events: queue.Queue[str] = queue.Queue()
        self.tasks: queue.Queue[tuple[str, str, dict, Path | None]] = queue.Queue()
        self.preference_save_job = None
        self._build_ui()
        self._load_backend()
        threading.Thread(target=self._task_worker, daemon=True, name="voice-worker").start()
        self.root.after(300, self._drain_events)
        self.root.after(2000, self._poll_input_file)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="本地文字转语音", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        row = ttk.Frame(frame); row.pack(fill="x", pady=(12, 6))
        ttk.Label(row, text="监听文件").pack(side="left")
        self.file_var = tk.StringVar(value=str(self.input_path))
        ttk.Entry(row, textvariable=self.file_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="选择", command=self._choose_file).pack(side="left")
        settings = ttk.Frame(frame); settings.pack(fill="x", pady=6)
        ttk.Label(settings, text="声音").pack(side="left")
        saved_voice = self.config.get("ui", {}).get("voice", "女声-苏映雪")
        if saved_voice == "女声-姑娘":
            saved_voice = "男声-姑娘"
        self.speaker_var = tk.StringVar(value=saved_voice if saved_voice in VOICES else "女声-苏映雪")
        self.voice_combo = ttk.Combobox(settings, textvariable=self.speaker_var, values=list(VOICES), state="readonly", width=16)
        self.voice_combo.pack(side="left", padx=(8, 20))
        self.voice_combo.bind("<<ComboboxSelected>>", lambda _event: self._schedule_preference_save())
        ttk.Label(settings, text="语速").pack(side="left")
        self.speed_var = tk.DoubleVar(value=float(self.config.get("tts", {}).get("speed", 0.85)))
        ttk.Scale(settings, from_=0.5, to=1.3, variable=self.speed_var, orient="horizontal", length=180).pack(side="left", padx=8)
        self.speed_label = ttk.Label(settings, text=self._speed_text())
        self.speed_label.pack(side="left")
        self.speed_var.trace_add("write", self._on_speed_changed)
        ttk.Label(frame, text="输入文字（点击‘追加并播报’，或直接写入监听文件）").pack(anchor="w", pady=(12, 4))
        self.text = tk.Text(frame, height=9, wrap="word", font=("Microsoft YaHei UI", 11))
        self.text.pack(fill="both", expand=True)
        buttons = ttk.Frame(frame); buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="追加并播报", command=self._append).pack(side="left")
        ttk.Button(buttons, text="立即播报（不写文件）", command=self._speak_now).pack(side="left", padx=8)
        ttk.Button(buttons, text="导出 MP3", command=self._export_mp3).pack(side="left")
        ttk.Button(buttons, text="清空输入", command=lambda: self.text.delete("1.0", "end")).pack(side="left", padx=8)
        self.status = tk.StringVar(value="正在初始化…")
        ttk.Label(frame, textvariable=self.status, foreground="#555").pack(anchor="w")

    def _load_backend(self):
        try:
            cfg = self._selected_config()
            self.backend = main.create_backend({"tts": cfg})
            self.backend_key = (cfg.get("backend"), cfg.get("model"))
            self.status.set(f"已就绪，监听：{self.input_path.name}")
        except Exception as exc:
            self.status.set("TTS 初始化失败")
            messagebox.showerror("初始化失败", str(exc))

    def _choose_file(self):
        selected = filedialog.askopenfilename(filetypes=[("UTF-8 文本", "*.txt"), ("所有文件", "*.*")])
        if selected:
            self.input_path = Path(selected)
            self.last_file_bytes = self.input_path.read_bytes() if self.input_path.exists() else b""
            self.file_var.set(str(self.input_path))
            self.config["input_file"] = str(self.input_path)

    def _selected_config(self):
        cfg = dict(self.config.get("tts", {}))
        cfg.update(VOICES.get(self.speaker_var.get(), VOICES["女声-苏映雪"]))
        cfg["speed"] = float(self.speed_var.get())
        return cfg

    def _speed_text(self):
        speed = self.speed_var.get()
        label = "慢" if speed < 0.8 else "适中" if speed < 1.05 else "快"
        return f"{speed:.2f}x（{label}）"

    def _on_speed_changed(self, *_):
        self.speed_label.config(text=self._speed_text())
        self._schedule_preference_save()

    def _schedule_preference_save(self):
        if self.preference_save_job is not None:
            self.root.after_cancel(self.preference_save_job)
        self.preference_save_job = self.root.after(300, self._save_preferences)

    def _save_preferences(self):
        self.preference_save_job = None
        self.config.setdefault("tts", {})["speed"] = round(float(self.speed_var.get()), 2)
        self.config.setdefault("ui", {})["voice"] = self.speaker_var.get()
        serializable = dict(self.config)
        try:
            serializable["input_file"] = str(self.input_path.relative_to(main.ROOT))
        except ValueError:
            serializable["input_file"] = str(self.input_path)
        main.CONFIG_PATH.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")

    def _queue_speak(self, value: str, cfg: dict):
        self._save_preferences()
        self.tasks.put(("speak", value.lstrip("\ufeff").strip(), cfg, None))

    def _append(self):
        value = self.text.get("1.0", "end").strip()
        if not value:
            return
        self.input_path.parent.mkdir(parents=True, exist_ok=True)
        with self.input_path.open("a", encoding="utf-8") as f:
            f.write(value + "\n")
        self.last_file_bytes = self.input_path.read_bytes()
        cfg = self._selected_config()
        for sentence in main.split_sentences(value, flush=True)[0] or [value]:
            self._queue_speak(sentence, cfg)
        self.text.delete("1.0", "end")
        self.status.set("已追加并开始播报")

    def _speak_now(self):
        value = self.text.get("1.0", "end").strip()
        if not value or self.backend is None:
            return
        self.status.set("正在播报…")
        cfg = self._selected_config()
        self._queue_speak(value, cfg)
        self.text.delete("1.0", "end")

    def _export_mp3(self):
        value = self.text.get("1.0", "end").strip()
        if not value:
            messagebox.showinfo("没有文字", "请先输入需要转换的文字。")
            return
        selected = filedialog.asksaveasfilename(
            defaultextension=".mp3", filetypes=[("MP3 音频", "*.mp3")], initialfile="语音.mp3"
        )
        if selected:
            self.status.set("正在生成 MP3…")
            self._save_preferences()
            self.tasks.put(("mp3", value, self._selected_config(), Path(selected)))

    def _get_backend(self, cfg):
        key = (cfg.get("backend"), cfg.get("model"))
        if self.backend is None or self.backend_key != key:
            self.backend = main.SherpaOnnxBackend(cfg) if cfg.get("backend") == "sherpa_onnx" else main.create_backend({"tts": cfg})
            self.backend_key = key
        if isinstance(self.backend, main.SherpaOnnxBackend):
            self.backend._speaker_id = int(cfg.get("speaker_id", 0))
            self.backend._speed = float(cfg.get("speed", 1.0))
        return self.backend

    def _task_worker(self):
        while True:
            action, value, cfg, output_path = self.tasks.get()
            try:
                backend = self._get_backend(cfg)
                if action == "mp3":
                    backend.save_mp3(value, output_path)
                    self.events.put(f"MP3 已保存：{output_path}")
                else:
                    backend.speak(value)
                    self.events.put("播报完成")
            except Exception as exc:
                self.events.put(f"处理失败：{exc}")
            finally:
                self.tasks.task_done()

    def _poll_input_file(self):
        try:
            if self.input_path.exists():
                current_bytes = self.input_path.read_bytes()
                if current_bytes != self.last_file_bytes:
                    if current_bytes.startswith(self.last_file_bytes):
                        changed_bytes = current_bytes[len(self.last_file_bytes):]
                    else:
                        changed_bytes = current_bytes
                        self.status.set("检测到文件内容被修改，播报当前完整内容")
                    self.last_file_bytes = current_bytes
                    changed = changed_bytes.decode("utf-8-sig").lstrip("\ufeff")
                    sentences, remainder = main.split_sentences(changed, flush=True)
                    if remainder.strip():
                        sentences.append(remainder.strip())
                    cfg = self._selected_config()
                    for sentence in sentences:
                        self._queue_speak(sentence, cfg)
        except Exception as exc:
            self.status.set(f"监听失败：{exc}")
        finally:
            self.root.after(2000, self._poll_input_file)

    def _drain_events(self):
        try:
            while True: self.status.set(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(300, self._drain_events)


if __name__ == "__main__":
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\word_turn_voice_gui")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, "程序已经在运行。", "本地文字转语音", 0x40)
    else:
        root = tk.Tk()
        VoiceApp(root)
        root.mainloop()
