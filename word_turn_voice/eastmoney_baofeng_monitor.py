"""Poll Eastmoney's public quote endpoint and append BaoFeng Energy updates."""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "dist" / "word_turn_voice" / "inbox.txt"
API_ENDPOINTS = (
    "https://push2.eastmoney.com/api/qt/stock/get",
    "https://72.push2.eastmoney.com/api/qt/stock/get",
    "https://push2delay.eastmoney.com/api/qt/stock/get",
)
FIELDS = "f43,f57,f58,f60,f169,f170"
CN_DIGITS = "零一二三四五六七八九"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("eastmoney_baofeng_monitor")


def fetch_quote() -> dict:
    query = urlencode({"invt": "2", "fltt": "1", "secid": "1.600989", "fields": FIELDS})
    errors = []
    payload = None
    for endpoint in API_ENDPOINTS:
        result = subprocess.run(
            [
                "curl.exe", "--http1.1", "-L", "-k", "--fail", "--silent", "--show-error",
                "--connect-timeout", "5", "--max-time", "12",
                "--header", "User-Agent: Mozilla/5.0",
                f"{endpoint}?{query}",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout.decode("utf-8"))
                break
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"{endpoint}: JSON 解析失败 {exc}")
        else:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            errors.append(f"{endpoint}: curl {result.returncode} {error}")
    if payload is None:
        raise RuntimeError("；".join(errors))
    data = payload.get("data")
    if payload.get("rc") != 0 or not data or data.get("f57") != "600989":
        raise RuntimeError(f"东方财富返回异常: {payload}")
    price = data.get("f43")
    change_percent = data.get("f170")
    if not isinstance(price, (int, float)) or not isinstance(change_percent, (int, float)):
        raise RuntimeError(f"行情字段缺失: {data}")
    return {
        "name": data.get("f58", "宝丰能源"),
        "code": data["f57"],
        "price": price / 100,
        "change_percent": change_percent / 100,
        "change_amount": (data.get("f169") or 0) / 100,
    }


def format_message(quote: dict) -> str:
    now = datetime.now().strftime("%H:%M")
    change = quote["change_percent"]
    if change > 0:
        direction = "上涨"
    elif change < 0:
        direction = "下跌"
    else:
        direction = "涨跌幅为"
    raw_change = f"{abs(change):.2f}"
    integer, decimal = raw_change.split(".")
    integer_text = "零" if int(integer) == 0 else "".join(CN_DIGITS[int(d)] for d in integer)
    change_text = integer_text + "点" + "".join(CN_DIGITS[int(d)] for d in decimal)
    return (
        f"{now}，{quote['name']}，当前价格 {quote['price']:.2f} 元，"
        f"当前{direction}百分之{change_text}。"
    )


def append_message(output: Path, message: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as file:
        file.write(message + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="每分钟播报宝丰能源实时涨跌幅")
    parser.add_argument("--interval", type=float, default=60.0, help="轮询间隔秒数，默认 60")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="写入的 UTF-8 文本文件")
    parser.add_argument("--once", action="store_true", help="只查询并写入一次")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval 必须大于 0")

    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\word_turn_voice_baofeng_monitor")
    if ctypes.windll.kernel32.GetLastError() == 183:
        LOG.error("宝丰能源行情监控已经在运行，本次启动退出")
        return 2

    next_run = time.monotonic()
    while True:
        try:
            message = format_message(fetch_quote())
            append_message(args.output, message)
            LOG.info("已追加: %s", message)
        except Exception as exc:
            LOG.warning("本次行情获取失败，不写入错误播报: %s", exc)
        if args.once:
            return 0
        next_run += args.interval
        time.sleep(max(0, next_run - time.monotonic()))


if __name__ == "__main__":
    raise SystemExit(main())
