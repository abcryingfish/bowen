"""抓取东方财富 chart2wrap 历史趋势排名数据并写入前端因子库。

接口：gbcdn.dfcfw.com/rank/history/year/{SH|SZ}{CODE}.js?type=0。
默认读取本地股票池，0.5 秒启动一个请求、8 线程有界并发；失败首轮后仅重试一次，
仍失败写入 D:\\database\\signal_daily\\trend_rank_failed_stocks.json。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import requests
from Crypto.Cipher import AES
from requests.adapters import HTTPAdapter

LOGGER = logging.getLogger("stock_trend_rank")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = PROJECT_ROOT / "全市场股票代码" / "universe.parquet"
DEFAULT_OUTPUT_DIR = Path(r"D:\database\signal_daily")
URL = "https://gbcdn.dfcfw.com/rank/history/year/{req_code}.js?type=0"
PAYLOAD_RE = re.compile(r"var\s+rankHistory\s*=\s*'([^']+)'", re.ASCII)
AES_KEY = hashlib.md5(b"getUtilsFromFile").hexdigest().encode("ascii")
AES_IV = b"getClassFromFile"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "*/*"}

FACTOR_FIELDS = {
    "历史人气排名": "RANK",
    "历史排名变化": "HISRANKCHANGE",
    "历史排名变化排名": "HISRANKCHANGE_RANK",
    "人气热度分数": "HOTRANKSCORE",
    "当日排名变化": "RANKCHANGE",
    "小时排名变化": "HOURRANKCHANGE",
    "市场股票总数": "MARKETALLCOUNT",
}
FACTOR_IDS = {
    "历史人气排名": "history_rank",
    "历史排名变化": "history_rank_change",
    "历史排名变化排名": "history_rank_change_rank",
    "人气热度分数": "hot_rank_score",
    "当日排名变化": "daily_rank_change",
    "小时排名变化": "hourly_rank_change",
    "市场股票总数": "market_stock_count",
}


@dataclass(frozen=True)
class Stock:
    htsc_code: str
    req_code: str
    name: str = ""


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def parse_code(raw: str) -> Stock:
    value = str(raw).strip().upper()
    if "." in value:
        code, exchange = value.split(".", 1)
    elif value[:2] in {"SH", "SZ"}:
        exchange, code = value[:2], value[2:]
    else:
        code, exchange = value, ("SH" if value[:1] in {"5", "6", "9"} else "SZ")
    if len(code) != 6 or not code.isdigit() or exchange not in {"SH", "SZ"}:
        raise ValueError(f"无法识别沪深股票代码: {raw}")
    return Stock(f"{code}.{exchange}", f"{exchange}{code}")


def load_stocks(universe: Path, codes: list[str] | None, limit: int | None) -> list[Stock]:
    names: dict[str, str] = {}
    if universe.is_file():
        frame = pl.read_parquet(str(universe))
        for row in frame.iter_rows(named=True):
            code, exchange = row.get("htsc_code"), row.get("exchange")
            if code and exchange in {"SH", "SZ"}:
                names[str(code).upper()] = str(row.get("name") or "")
    if codes:
        stocks = [parse_code(part) for item in codes for part in str(item).split(",") if part.strip()]
        stocks = [Stock(s.htsc_code, s.req_code, names.get(s.htsc_code, "")) for s in stocks]
    else:
        stocks = [Stock(code, parse_code(code).req_code, name) for code, name in sorted(names.items())]
    unique = list({s.htsc_code: s for s in stocks}.values())
    if limit is not None:
        unique = unique[:limit]
    if not unique:
        raise ValueError(f"股票池为空或不存在: {universe}")
    return unique


def filter_completed_stocks(stocks: list[Stock], output: Path, target_date: date) -> tuple[list[Stock], int]:
    """四个核心趋势字段当天都有记录时跳过，避免每日重复下载完整历史。"""
    core_factors = tuple(
        FACTOR_IDS[name]
        for name in ("历史人气排名", "历史排名变化", "人气热度分数")
    )
    completed_sets: list[set[str]] = []
    for factor in core_factors:
        paths = list((output / f"factor={factor}").glob("year=*/month=*/merged.parquet"))
        if not paths:
            return stocks, 0
        frame = pl.concat([pl.read_parquet(str(p), columns=["htsc_code", "time"]) for p in paths], how="diagonal_relaxed")
        completed_sets.append(set(frame.filter(pl.col("time").cast(pl.Date) >= target_date).get_column("htsc_code").unique().to_list()))
    completed = set.intersection(*completed_sets)
    pending = [stock for stock in stocks if stock.htsc_code not in completed]
    return pending, len(stocks) - len(pending)


def decrypt_payload(encoded: str) -> list[dict[str, Any]]:
    encrypted = base64.b64decode(encoded)
    plain = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).decrypt(encrypted)
    padding = plain[-1]
    if not 1 <= padding <= AES.block_size or plain[-padding:] != bytes([padding]) * padding:
        raise ValueError("AES 解密填充无效")
    data = json.loads(plain[:-padding].decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("历史排名响应不是列表")
    return data


def fetch_stock(stock: Stock, timeout: float, retries: int) -> list[dict[str, Any]]:
    session = requests.Session()
    session.mount("https://", HTTPAdapter(pool_connections=1, pool_maxsize=1))
    try:
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = session.get(URL.format(req_code=stock.req_code), headers={**HEADERS, "Referer": f"https://guba.eastmoney.com/rank/stock?code={stock.htsc_code[:6]}"}, timeout=timeout)
                response.raise_for_status()
                match = PAYLOAD_RE.search(response.content.decode("utf-8-sig"))
                if not match:
                    raise ValueError("响应中未找到 rankHistory")
                return decrypt_payload(match.group(1))
            except Exception as exc:
                last = exc
                if attempt < retries:
                    time.sleep(min(30.0, 2.0**attempt))
        raise RuntimeError(f"{stock.htsc_code} 抓取失败: {last}") from last
    finally:
        session.close()


def normalize(stock: Stock, records: list[dict[str, Any]]) -> pl.DataFrame:
    rows = []
    for item in records:
        raw_time = str(item.get("CALCTIME") or "").strip()
        try:
            stamp = datetime.fromisoformat(raw_time)
        except ValueError:
            continue
        row = {"htsc_code": stock.htsc_code, "time": stamp}
        for factor, source in FACTOR_FIELDS.items():
            try:
                row[source] = None if item.get(source) in (None, "") else float(item.get(source))
            except (TypeError, ValueError):
                row[source] = None
        rows.append(row)
    return pl.DataFrame(rows, schema={"htsc_code": pl.String, "time": pl.Datetime("us"), **{v: pl.Float64 for v in FACTOR_FIELDS.values()}})


def write_records(frame: pl.DataFrame, output: Path, run_id: str, batch_id: int) -> None:
    if frame.is_empty():
        return
    frame = frame.with_columns(pl.col("time").dt.year().alias("_year"), pl.col("time").dt.month().alias("_month"))
    for factor, source in FACTOR_FIELDS.items():
        factor_id = FACTOR_IDS[factor]
        for (year, month), chunk in frame.select("htsc_code", "time", pl.col(source).alias("value"), "_year", "_month").partition_by(["_year", "_month"], as_dict=True).items():
            folder = output / f"factor={factor_id}" / f"year={int(year):04d}" / f"month={int(month):02d}"
            folder.mkdir(parents=True, exist_ok=True)
            part = folder / f"part_trend_{run_id}_{batch_id:04d}.parquet"
            merged_path = folder / "merged.parquet"
            new = chunk.drop(["_year", "_month"])
            old = pl.read_parquet(str(merged_path)) if merged_path.is_file() else pl.DataFrame(schema=new.schema)
            merged = pl.concat([old, new], how="diagonal_relaxed").unique(subset=["htsc_code", "time"], keep="last", maintain_order=True).sort(["htsc_code", "time"])
            temp = folder / "merged.parquet.tmp"
            merged.write_parquet(str(temp), compression="zstd")
            temp.replace(merged_path)
            if part.exists():
                part.unlink()


def run_round(stocks: list[Stock], args: argparse.Namespace, output: Path, run_id: str, failures: dict[str, dict[str, str]], label: str) -> None:
    if not stocks:
        return
    pending: dict[Any, Stock] = {}
    frame_batch: list[pl.DataFrame] = []
    batch_id = 0
    next_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="trend-rank") as executor:
        iterator = iter(stocks)
        def submit_next() -> bool:
            nonlocal next_at
            stock = next(iterator, None)
            if stock is None:
                return False
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            pending[executor.submit(fetch_stock, stock, args.timeout, args.retries)] = stock
            next_at = time.monotonic() + args.sleep_sec
            return True
        for _ in range(min(args.workers, len(stocks))):
            submit_next()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                stock = pending.pop(future)
                try:
                    frame = normalize(stock, future.result())
                    if frame.is_empty():
                        raise RuntimeError("无可解析的历史排名记录")
                    frame_batch.append(frame)
                    failures.pop(stock.htsc_code, None)
                    LOGGER.info("[%s] %s 成功 %d 条", label, stock.htsc_code, frame.height)
                except Exception as exc:
                    failures[stock.htsc_code] = {"htsc_code": stock.htsc_code, "name": stock.name, "error": str(exc)}
                    LOGGER.error("[%s] %s 失败: %s", label, stock.htsc_code, exc)
                if len(frame_batch) >= args.batch_size:
                    batch_id += 1
                    write_records(pl.concat(frame_batch, how="vertical_relaxed"), output, run_id, batch_id)
                    frame_batch.clear()
                submit_next()
    if frame_batch:
        batch_id += 1
        write_records(pl.concat(frame_batch, how="vertical_relaxed"), output, run_id, batch_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取东方财富 chart2wrap 历史趋势排名")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--codes", nargs="*")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep-sec", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    configure_console()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.sleep_sec < 0 or args.workers < 1 or args.timeout <= 0 or args.retries < 0 or args.batch_size < 1:
        raise ValueError("请求参数无效")
    stocks = load_stocks(args.universe, args.codes, args.limit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stocks, skipped = filter_completed_stocks(stocks, args.output_dir, datetime.now().date())
    if skipped:
        LOGGER.info("跳过当天已有趋势排名的 %d 只股票，剩余 %d 只", skipped, len(stocks))
    if not stocks:
        LOGGER.info("所有股票都已有当天趋势排名，无需请求")
        return 0
    failure_path = args.output_dir / "trend_rank_failed_stocks.json"
    failures: dict[str, dict[str, str]] = {}
    if failure_path.is_file():
        try:
            failures = {str(x["htsc_code"]): x for x in json.loads(failure_path.read_text(encoding="utf-8"))}
        except Exception:
            LOGGER.warning("趋势排名失败清单无法解析，将重建")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    retry_codes = set(failures)
    stocks.sort(key=lambda s: (s.htsc_code not in retry_codes, s.htsc_code))
    run_round(stocks, args, args.output_dir, run_id, failures, "首次")
    failed_stocks = [s for s in stocks if s.htsc_code in failures]
    if failed_stocks:
        LOGGER.warning("趋势排名首次失败 %d 只，重试一次", len(failed_stocks))
        run_round(failed_stocks, args, args.output_dir, run_id, failures, "重试")
    if failures:
        failure_path.write_text(json.dumps(sorted(failures.values(), key=lambda x: x["htsc_code"]), ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    if failure_path.exists():
        failure_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
