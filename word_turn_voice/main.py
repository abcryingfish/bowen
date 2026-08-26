"""Offline UTF-8 text tailer and Chinese TTS announcer."""
from __future__ import annotations

import json
import logging
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DEFAULT_CONFIG = ROOT / "config.example.json"
STATE_PATH = ROOT / "state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("word_turn_voice")
_file_handler = logging.FileHandler(ROOT / "voice.log", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
LOG.addHandler(_file_handler)


def load_config() -> dict[str, Any]:
    path = CONFIG_PATH if CONFIG_PATH.exists() else DEFAULT_CONFIG
    with path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    config["input_file"] = str((ROOT / config["input_file"]).resolve())
    return config


def split_sentences(text: str, flush: bool = False) -> tuple[list[str], str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Keep short notifications responsive while retaining Chinese punctuation pauses.
    parts = re.split(r"(?<=[。！？；!?;])|\n+", text)
    if not parts:
        return [], ""
    remainder = "" if flush else parts.pop()
    return [p.strip() for p in parts if p.strip()], remainder


class TTSBackend:
    def speak(self, text: str) -> None:
        raise NotImplementedError


class SherpaOnnxBackend(TTSBackend):
    def __init__(self, cfg: dict[str, Any]):
        try:
            import sherpa_onnx
            import sounddevice as sd
            import soundfile as sf
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx/sounddevice/soundfile 未安装") from exc
        self._sf = sf
        self._sd = sd
        model = lambda key: str((ROOT / cfg[key]).resolve())
        tcfg = sherpa_onnx.OfflineTtsConfig()
        tcfg.model.vits.model = model("model")
        tcfg.model.vits.tokens = model("tokens")
        tcfg.model.vits.lexicon = model("lexicon") if cfg.get("lexicon") else ""
        tcfg.model.vits.data_dir = model("data_dir") if cfg.get("data_dir") else ""
        tcfg.rule_fsts = ",".join(
            str((ROOT / model_path.strip()).resolve())
            for model_path in str(cfg.get("rule_fsts", "")).split(",")
            if model_path.strip()
        )
        tcfg.model.num_threads = int(cfg.get("num_threads", 4))
        tcfg.model.debug = False
        # sherpa-onnx exposes provider on the model config in newer releases.
        provider = "cuda" if cfg.get("provider", "cuda") == "cuda" else "cpu"
        if hasattr(tcfg.model, "provider"):
            tcfg.model.provider = provider
        elif hasattr(tcfg, "provider"):
            tcfg.provider = provider
        self._tts = sherpa_onnx.OfflineTts(tcfg)
        self._speed = float(cfg.get("speed", 1.0))
        self._volume = float(cfg.get("volume", 1.0))
        self._leading_silence_ms = max(0, int(cfg.get("leading_silence_ms", 1500)))
        self._trailing_silence_ms = max(0, int(cfg.get("trailing_silence_ms", 120)))
        self._output_device = cfg.get("output_device")
        self._speaker_id = int(cfg.get("speaker_id", 0))

    def speak(self, text: str) -> None:
        import numpy as np

        samples, sample_rate = self.generate_audio(text)
        errors = []
        for device in self._output_candidates(self._output_device):
            try:
                info = self._sd.query_devices(device, "output") if device is not None else self._sd.query_devices(kind="output")
                target_rate = int(info["default_samplerate"])
                output_samples = samples if target_rate == sample_rate else self._resample(samples, sample_rate, target_rate)
                if target_rate != sample_rate:
                    LOG.info("音频重采样: %d Hz -> %d Hz", sample_rate, target_rate)
                leading = np.zeros(round(target_rate * self._leading_silence_ms / 1000), dtype=np.float32)
                trailing = np.zeros(round(target_rate * self._trailing_silence_ms / 1000), dtype=np.float32)
                output_samples = np.concatenate((leading, output_samples, trailing))
                self._sd.check_output_settings(device=device, channels=1, samplerate=target_rate, dtype="float32")
                self._sd.play(output_samples, target_rate, device=device)
                self._sd.wait()
                LOG.info("播放完成: %s", text)
                return
            except Exception as exc:
                errors.append(f"{info['name'] if 'info' in locals() else device}: {exc}")
                LOG.warning("音频设备播放失败，尝试备用设备: %s", errors[-1])
                try:
                    self._sd.stop()
                except Exception:
                    pass
        raise RuntimeError("所有音频输出设备均播放失败：" + " | ".join(errors))

    def generate_audio(self, text: str):
        import numpy as np

        clean_text = text.lstrip("\ufeff").strip()
        if not clean_text:
            raise ValueError("没有可生成的文字")
        audio = self._tts.generate(clean_text, sid=self._speaker_id, speed=self._speed)
        if audio is None or len(audio.samples) == 0:
            raise RuntimeError("sherpa-onnx 未生成音频")
        samples = np.asarray(audio.samples, dtype=np.float32) * self._volume
        return samples, int(audio.sample_rate)

    @staticmethod
    def _resample(samples, source_rate: int, target_rate: int):
        import numpy as np

        target_length = max(1, round(len(samples) * target_rate / source_rate))
        source_positions = np.arange(len(samples), dtype=np.float64)
        target_positions = np.linspace(0, len(samples) - 1, target_length, dtype=np.float64)
        return np.interp(target_positions, source_positions, samples).astype(np.float32)

    def save_mp3(self, text: str, output_path: Path, bitrate_kbps: int = 128) -> None:
        import lameenc
        import numpy as np

        samples, sample_rate = self.generate_audio(text)
        leading = np.zeros(round(sample_rate * self._leading_silence_ms / 1000), dtype=np.float32)
        trailing = np.zeros(round(sample_rate * self._trailing_silence_ms / 1000), dtype=np.float32)
        samples = np.concatenate((leading, samples, trailing))
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(bitrate_kbps)
        encoder.set_in_sample_rate(sample_rate)
        encoder.set_channels(1)
        encoder.set_quality(2)
        mp3_data = encoder.encode(pcm) + encoder.flush()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(mp3_data)
        LOG.info(
            "MP3 已生成（首部静音 %dms，尾部静音 %dms）: %s",
            self._leading_silence_ms,
            self._trailing_silence_ms,
            output_path,
        )

    def _output_candidates(self, requested: str | None) -> list[int | None]:
        host_apis = self._sd.query_hostapis()
        devices = self._sd.query_devices()
        candidates = []

        # The Windows mapper follows the output device selected in Windows Settings.
        for index, info in enumerate(devices):
            host_name = host_apis[info["hostapi"]]["name"]
            if info["max_output_channels"] > 0 and host_name != "Windows WDM-KS" and (
                "声音映射器" in info["name"] or "主声音驱动程序" in info["name"]
            ) and index not in candidates:
                candidates.append(index)
        # PortAudio's current default is a final fallback when no mapper is exposed.
        candidates.append(None)
        LOG.info("音频输出候选设备: %s", candidates)
        return candidates


class Pyttsx3Backend(TTSBackend):
    def __init__(self, cfg: dict[str, Any]):
        try:
            import pyttsx3
        except ImportError as exc:
            raise RuntimeError("pyttsx3 未安装") from exc
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", int(180 * float(cfg.get("speed", 1.0))))
        self._engine.setProperty("volume", float(cfg.get("volume", 1.0)))

    def speak(self, text: str) -> None:
        self._engine.say(text)
        self._engine.runAndWait()


def create_backend(config: dict[str, Any]) -> TTSBackend:
    tcfg = config.get("tts", {})
    backend = tcfg.get("backend", "sherpa_onnx")
    if backend == "pyttsx3":
        return Pyttsx3Backend(tcfg)
    if backend == "sherpa_onnx":
        return SherpaOnnxBackend(tcfg)
    raise ValueError(f"不支持的 TTS 后端: {backend}")


def load_offset(path: Path, start_at_end: bool) -> int:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if state.get("file") == str(path):
                return int(state.get("offset", 0))
        except (OSError, ValueError, TypeError):
            LOG.warning("state.json 无法读取，将重新定位")
    return path.stat().st_size if start_at_end and path.exists() else 0


def save_offset(path: Path, offset: int) -> None:
    STATE_PATH.write_text(json.dumps({"file": str(path), "offset": offset}, ensure_ascii=False, indent=2), encoding="utf-8")


def run() -> None:
    config = load_config()
    input_path = Path(config["input_file"])
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.touch(exist_ok=True)
    try:
        tts = create_backend(config)
    except Exception as exc:
        LOG.error("TTS 初始化失败: %s", exc)
        LOG.error("请安装 requirements.txt 并检查 config.json 的模型路径；也可将 backend 改为 pyttsx3")
        raise SystemExit(2)
    LOG.info("TTS 后端已初始化: %s", config.get("tts", {}).get("backend"))
    offset = load_offset(input_path, bool(config.get("start_at_end", True)))
    pending_text = ""
    tasks: queue.Queue[str] = queue.Queue(maxsize=int(config.get("max_queue_size", 20)))
    mode = config.get("queue_mode", "fifo")

    def speaker() -> None:
        while True:
            text = tasks.get()
            try:
                LOG.info("播报: %s", text)
                tts.speak(text)
            except Exception:
                LOG.exception("播报失败")
            finally:
                tasks.task_done()

    threading.Thread(target=speaker, daemon=True, name="tts-speaker").start()
    LOG.info("监听文件: %s", input_path)
    while True:
        try:
            size = input_path.stat().st_size
            if size < offset:
                offset = 0
            if size > offset:
                with input_path.open("r", encoding="utf-8") as f:
                    f.seek(offset)
                    added = f.read()
                    offset = f.tell()
                save_offset(input_path, offset)
                LOG.info("读取新增文本 %d 字节，切分前缓冲长度=%d", len(added.encode("utf-8")), len(pending_text))
                sentences, pending_text = split_sentences(pending_text + added)
                for sentence in sentences:
                    LOG.info("加入播报队列: %s", sentence)
                    if mode == "latest" and not tasks.empty():
                        while not tasks.empty():
                            try: tasks.get_nowait(); tasks.task_done()
                            except queue.Empty: break
                    try: tasks.put_nowait(sentence)
                    except queue.Full: LOG.warning("播报队列已满，丢弃文本: %s", sentence)
            time.sleep(float(config.get("poll_interval_seconds", 2.0)))
        except UnicodeDecodeError:
            LOG.error("输入文件不是 UTF-8，已跳过本轮")
            time.sleep(2)
        except KeyboardInterrupt:
            LOG.info("已停止")
            return


if __name__ == "__main__":
    run()
