"""抓取东方财富个股人气榜的每日粉丝特征。

接口返回的是加密 JavaScript：
``https://gbcdn.dfcfw.com/rank/fanshistory/year/{MARKET}{CODE}.js``。
脚本按本地股票池顺序异步请求，默认每 0.5 秒启动一只股票，并将四项粉丝因子保存为
前端可直接读取的 ``signal_daily/factor=*/year=*/month=*/merged.parquet``。

示例：
    .venv\\Scripts\\python.exe 工具\\获得股票粉丝特征.py \\
        --sleep-sec 0.5 --output-dir D:\\database\\signal_daily

    .venv\\Scripts\\python.exe 工具\\获得股票粉丝特征.py \\
        --import-history D:\\database\\stock_fans_history
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
from typing import Any, Iterable

import polars as pl
import requests
from Crypto.Cipher import AES
from requests.adapters import HTTPAdapter


LOGGER = logging.getLogger("stock_fans")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = PROJECT_ROOT / "全市场股票代码" / "universe.parquet"
DEFAULT_OUTPUT_DIR = Path(r"D:\database\signal_daily")
FANS_HISTORY_URL = "https://gbcdn.dfcfw.com/rank/fanshistory/year/{req_code}.js"
RANK_HISTORY_URL = "https://gbcdn.dfcfw.com/rank/history/year/{req_code}.js?type=0"
PAYLOAD_RE = re.compile(r"var\s+rankHistoryFans\s*=\s*'([^']+)'", re.ASCII)
RANK_PAYLOAD_RE = re.compile(r"var\s+rankHistory\s*=\s*'([^']+)'", re.ASCII)
AES_KEY = hashlib.md5(b"getUtilsFromFile").hexdigest().encode("ascii")
AES_IV = b"getClassFromFile"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
}
FACTOR_FIELDS = {
    "新粉丝占比（%）": "new_uid_rate",
    "老粉丝占比（%）": "old_uid_rate",
    "新粉丝占比变化": "new_uid_change_rank",
    "老粉丝占比变化": "old_uid_change_rank",
    "历史人气排名": "history_rank",
}


@dataclass(frozen=True)
class Stock:
    htsc_code: str
    req_code: str
    name: str = ""


def configure_console() -> None:
    """尽量让 Windows 控制台使用 UTF-8，避免中文名称显示乱码。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def parse_code(raw_code: str) -> Stock:
    """把 000001.SZ、SZ000001 或纯数字代码统一成请求格式。"""
    value = str(raw_code).strip().upper()
    if not value:
        raise ValueError("股票代码不能为空")

    if "." in value:
        code, exchange = value.split(".", 1)
    elif value[:2] in {"SH", "SZ"}:
        exchange, code = value[:2], value[2:]
    else:
        code, exchange = value, ""

    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"无法识别股票代码: {raw_code}")
    if not exchange:
        # 与东方财富页面脚本的 A 股市场判断保持一致。
        exchange = "SH" if code[0] in {"5", "6", "9"} or code[:3] in {"009", "110", "126"} else "SZ"
    if exchange not in {"SH", "SZ"}:
        raise ValueError(f"仅支持沪深 A 股，收到: {raw_code}")
    return Stock(htsc_code=f"{code}.{exchange}", req_code=f"{exchange}{code}")


def load_stocks(universe_path: Path, raw_codes: Iterable[str] | None, limit: int | None) -> list[Stock]:
    name_by_code: dict[str, str] = {}
    if universe_path.is_file():
        universe = pl.read_parquet(str(universe_path))
        required = {"htsc_code", "exchange"}
        missing = required.difference(universe.columns)
        if missing:
            raise ValueError(f"股票池缺少字段: {sorted(missing)}")
        for row in universe.iter_rows(named=True):
            code = row.get("htsc_code")
            exchange = row.get("exchange")
            if code and exchange in {"SH", "SZ"}:
                name_by_code[str(code).upper()] = str(row.get("name") or "")

    if raw_codes:
        stocks: list[Stock] = []
        for item in raw_codes:
            for part in str(item).split(","):
                if part.strip():
                    stock = parse_code(part)
                    stocks.append(Stock(stock.htsc_code, stock.req_code, name_by_code.get(stock.htsc_code, "")))
    else:
        if not name_by_code:
            raise FileNotFoundError(f"找不到有效股票池: {universe_path}")
        stocks = [
            Stock(code, parse_code(code).req_code, name)
            for code, name in sorted(name_by_code.items())
        ]

    unique: dict[str, Stock] = {stock.htsc_code: stock for stock in stocks}
    stocks = list(unique.values())
    if limit is not None:
        stocks = stocks[:limit]
    if not stocks:
        raise ValueError("没有可抓取的股票")
    return stocks


def filter_completed_stocks(stocks: list[Stock], output_dir: Path, target_date: date) -> tuple[list[Stock], int]:
    """仅当四项因子都已有目标日期时才跳过，便于失败后完整续跑。"""
    completed_sets: list[set[str]] = []
    for factor_id in FACTOR_FIELDS.values():
        merged_path = (
            output_dir
            / f"factor={factor_id}"
            / f"year={target_date.year:04d}"
            / f"month={target_date.month:02d}"
            / "merged.parquet"
        )
        if not merged_path.is_file():
            return stocks, 0
        existing = pl.read_parquet(str(merged_path), columns=["htsc_code", "time"])
        completed_sets.append(
            set(
                existing.filter(pl.col("time").cast(pl.Date) >= target_date)
                .get_column("htsc_code")
                .unique()
                .to_list()
            )
        )
    completed = set.intersection(*completed_sets) if completed_sets else set()
    pending = [stock for stock in stocks if stock.htsc_code not in completed]
    return pending, len(stocks) - len(pending)


def decrypt_payload(encoded_payload: str) -> list[dict[str, Any]]:
    encrypted = base64.b64decode(encoded_payload)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    plaintext = cipher.decrypt(encrypted)
    padding = plaintext[-1]
    if padding < 1 or padding > AES.block_size or plaintext[-padding:] != bytes([padding]) * padding:
        raise ValueError("AES 解密后的 PKCS7 填充无效")
    decoded = plaintext[:-padding].decode("utf-8")
    data = json.loads(decoded)
    if not isinstance(data, list):
        raise ValueError("接口返回的数据不是列表")
    return data


def _fetch_script_payload(session: requests.Session, url: str, pattern: re.Pattern[str], variable: str, stock: Stock, timeout: float, retries: int) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, headers={**REQUEST_HEADERS, "Referer": f"https://guba.eastmoney.com/rank/stock?code={stock.htsc_code[:6]}"}, timeout=timeout)
            response.raise_for_status()
            match = pattern.search(response.content.decode("utf-8-sig"))
            if not match:
                raise ValueError(f"响应中未找到 {variable}")
            return decrypt_payload(match.group(1))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(60.0, 2.0 ** attempt))
    raise RuntimeError(f"{stock.htsc_code} {variable} 抓取失败: {last_error}") from last_error


def fetch_stock(session: requests.Session, stock: Stock, timeout: float, retries: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="stock-fans-pair") as pair_executor:
        fans_future = pair_executor.submit(
            _fetch_script_payload,
            session,
            FANS_HISTORY_URL.format(req_code=stock.req_code),
            PAYLOAD_RE,
            "rankHistoryFans",
            stock,
            timeout,
            retries,
        )
        trend_future = pair_executor.submit(
            _fetch_script_payload,
            session,
            RANK_HISTORY_URL.format(req_code=stock.req_code),
            RANK_PAYLOAD_RE,
            "rankHistory",
            stock,
            timeout,
            retries,
        )
        return fans_future.result(), trend_future.result()


def fetch_stock_worker(stock: Stock, timeout: float, retries: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    session = requests.Session()
    session.mount("https://", HTTPAdapter(pool_connections=1, pool_maxsize=2))
    try:
        return fetch_stock(session, stock, timeout, retries)
    finally:
        session.close()


def normalize_records(stock: Stock, records: list[dict[str, Any]], trend_records: list[dict[str, Any]], fetched_at: datetime) -> list[dict[str, Any]]:
    rank_by_date: dict[date, float | None] = {}
    for item in trend_records:
        try:
            stamp = datetime.fromisoformat(str(item.get("CALCTIME") or ""))
            rank_by_date[stamp.date()] = _to_float(item.get("RANK"))
        except ValueError:
            continue
    normalized: list[dict[str, Any]] = []
    for item in records:
        raw_time = str(item.get("CALCTIME") or "").strip()
        try:
            calc_time = datetime.fromisoformat(raw_time)
        except ValueError:
            LOGGER.warning("%s 跳过无法解析的 CALCTIME: %r", stock.htsc_code, raw_time)
            continue
        normalized.append(
            {
                "htsc_code": stock.htsc_code,
                "time": calc_time.replace(hour=0, minute=0, second=0, microsecond=0),
                "new_uid_change_rank": _to_float(item.get("NEWUIDCHANGERANK")),
                "new_uid_rate": _to_float(item.get("NEWUIDRATE")),
                "old_uid_change_rank": _to_float(item.get("OLDUIDCHANGERANK")),
                "old_uid_rate": _to_float(item.get("OLDUIDRATE")),
                "history_rank": rank_by_date.get(calc_time.date()),
            }
        )
    return normalized


def _to_float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def write_parts(
    records: list[dict[str, Any]] | pl.DataFrame,
    output_dir: Path,
    run_id: str,
    batch_id: int,
) -> dict[tuple[str, int, int], Path]:
    if isinstance(records, list) and not records:
        return {}
    frame = (pl.DataFrame(records) if isinstance(records, list) else records).with_columns(
        pl.col("time").cast(pl.Datetime("us")),
        pl.col("time").dt.year().alias("_year"),
        pl.col("time").dt.month().alias("_month"),
    )
    paths: dict[tuple[str, int, int], Path] = {}
    for _display_name, source_column in FACTOR_FIELDS.items():
        factor_id = source_column
        factor_frame = frame.select(
            "time",
            "htsc_code",
            pl.col(source_column).cast(pl.Float64).alias("value"),
            "_year",
            "_month",
        )
        for key, chunk in factor_frame.partition_by(["_year", "_month"], as_dict=True).items():
            year, month = key if isinstance(key, tuple) else (key, None)
            month_dir = (
                output_dir
                / f"factor={factor_id}"
                / f"year={int(year):04d}"
                / f"month={int(month):02d}"
            )
            month_dir.mkdir(parents=True, exist_ok=True)
            path = month_dir / f"part_{run_id}_{batch_id:04d}.parquet"
            chunk.drop(["_year", "_month"]).write_parquet(str(path), compression="zstd")
            paths[(factor_id, int(year), int(month))] = path
    return paths


def rebuild_merged(touched_parts: dict[tuple[str, int, int], list[Path]]) -> None:
    for (factor_name, year, month), part_paths in touched_parts.items():
        month_dir = part_paths[0].parent
        merged_path = month_dir / "merged.parquet"
        frames: list[pl.DataFrame] = []
        if merged_path.is_file():
            frames.append(pl.read_parquet(str(merged_path)))
        frames.extend(pl.read_parquet(str(path)) for path in part_paths if path.is_file())
        if not frames:
            continue
        merged = (
            pl.concat(frames, how="diagonal_relaxed")
            .select("time", "htsc_code", pl.col("value").cast(pl.Float64))
            .sort(["htsc_code", "time"])
            .unique(subset=["htsc_code", "time"], keep="last", maintain_order=True)
        )
        temp_path = month_dir / "merged.parquet.tmp"
        merged.write_parquet(str(temp_path), compression="zstd")
        temp_path.replace(merged_path)
        for part_path in part_paths:
            if part_path.is_file() and part_path != merged_path:
                part_path.unlink()
        LOGGER.info("已更新 %s %04d-%02d: %d 条", factor_name, year, month, merged.height)


def flush_batch(
    records: list[dict[str, Any]] | pl.DataFrame,
    output_dir: Path,
    run_id: str,
    batch_id: int,
) -> None:
    """写入当前批次并立即合并，确保长任务中途退出时已有数据可用。"""
    part_paths = write_parts(records, output_dir, run_id, batch_id)
    rebuild_merged({key: [path] for key, path in part_paths.items()})


def import_history(history_dir: Path, output_dir: Path, universe_path: Path) -> None:
    """把旧宽表历史转换为四个前端因子目录，不重新请求网络。"""
    valid_codes = {stock.htsc_code for stock in load_stocks(universe_path, None, None)}
    source_files = sorted(history_dir.glob("year=*/month=*/merged.parquet"))
    if not source_files:
        raise FileNotFoundError(f"历史目录中没有 merged.parquet: {history_dir}")
    run_id = datetime.now().strftime("import_%Y%m%d_%H%M%S")
    total_rows = 0
    for index, source_path in enumerate(source_files, start=1):
        frame = (
            pl.read_parquet(
                str(source_path),
                columns=["htsc_code", "date", *FACTOR_FIELDS.values()],
            )
            .filter(pl.col("htsc_code").is_in(valid_codes))
            .with_columns(pl.col("date").cast(pl.Datetime("us")).alias("time"))
            .drop("date")
        )
        flush_batch(frame, output_dir, run_id, index)
        total_rows += frame.height
        LOGGER.info("历史导入 [%d/%d] %s: %d 条", index, len(source_files), source_path, frame.height)
    LOGGER.info("历史导入完成：%d 条股票日记录，生成 %d 个因子", total_rows, len(FACTOR_FIELDS))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取东方财富个股每日粉丝特征")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE, help=f"股票池 Parquet，默认 {DEFAULT_UNIVERSE}")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help=f"输出目录，默认 {DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--codes", nargs="*", help="指定股票代码，可用 000001.SZ、SZ000001 或逗号分隔")
    parser.add_argument("--limit", type=int, help="从股票池中最多抓取多少只")
    parser.add_argument("--sleep-sec", type=float, default=0.5, help="新请求启动间隔秒数，默认 0.5")
    parser.add_argument("--workers", type=int, default=8, help="并发请求线程数，默认 8")
    parser.add_argument("--timeout", type=float, default=30.0, help="单次请求超时秒数，默认 30")
    parser.add_argument("--retries", type=int, default=3, help="失败重试次数，默认 3")
    parser.add_argument("--batch-size", type=int, default=50, help="每多少只股票写一个 part 文件，默认 50")
    parser.add_argument("--import-history", type=Path, help="从旧粉丝历史目录导入四项因子；启用时不请求网络")
    return parser.parse_args()


def main() -> int:
    configure_console()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if args.sleep_sec < 0 or args.retries < 0 or args.batch_size < 1 or args.timeout <= 0 or args.workers < 1:
        raise ValueError("--sleep-sec、--retries 必须非负，--timeout、--workers、--batch-size 必须大于 0")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit 必须大于 0")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.import_history is not None:
        import_history(args.import_history, args.output_dir, args.universe)
        return 0

    stocks = load_stocks(args.universe, args.codes, args.limit)
    requested_codes = {stock.htsc_code for stock in stocks}
    stocks, skipped_count = filter_completed_stocks(stocks, args.output_dir, datetime.now().date())
    pending_codes = {stock.htsc_code for stock in stocks}
    failure_path = args.output_dir / "failed_stocks.json"
    failures: dict[str, dict[str, str]] = {}
    if failure_path.is_file():
        try:
            failures = {
                str(item["htsc_code"]): item
                for item in json.loads(failure_path.read_text(encoding="utf-8"))
                if str(item.get("htsc_code") or "")
            }
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            LOGGER.warning("失败清单无法解析，将重新建立：%s", failure_path)
        for completed_code in requested_codes - pending_codes:
            failures.pop(completed_code, None)
        if failures:
            failure_path.write_text(json.dumps(sorted(failures.values(), key=lambda item: item["htsc_code"]), ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            failure_path.unlink()
            LOGGER.info("已清理全部陈旧失败记录")
    if skipped_count:
        LOGGER.info("跳过已有 %s 数据的 %d 只股票，剩余 %d 只", datetime.now().date(), skipped_count, len(stocks))
    if not stocks:
        LOGGER.info("所有股票都已有当天数据，无需请求")
        return 0
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_date = datetime.now().date()
    retry_codes = set(failures)
    stocks.sort(key=lambda stock: (stock.htsc_code not in retry_codes, stock.htsc_code))
    batch: list[dict[str, Any]] = []
    def run_round(round_stocks: list[Stock], round_label: str) -> None:
        if not round_stocks:
            return
        LOGGER.info("开始%s抓取 %d 只股票，启动间隔 %.1f 秒、并发 %d", round_label, len(round_stocks), args.sleep_sec, args.workers)
        pending: dict[Any, Stock] = {}
        next_request_at = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="stock-fans") as executor:
            stock_iter = iter(round_stocks)

            def submit_next() -> bool:
                nonlocal next_request_at
                stock = next(stock_iter, None)
                if stock is None:
                    return False
                delay = next_request_at - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                pending[executor.submit(fetch_stock_worker, stock, args.timeout, args.retries)] = stock
                next_request_at = time.monotonic() + args.sleep_sec
                return True

            for _ in range(min(args.workers, len(round_stocks))):
                submit_next()
            completed_count = 0
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    stock = pending.pop(future)
                    completed_count += 1
                    try:
                        records, trend_records = future.result()
                        normalized = normalize_records(stock, records, trend_records, datetime.now())
                        daily_records = [record for record in normalized if record["time"].date() == target_date and record["history_rank"] is not None]
                        if not daily_records:
                            raise RuntimeError(f"接口未返回当天数据 {target_date.isoformat()}")
                        batch.extend(daily_records)
                        failures.pop(stock.htsc_code, None)
                        LOGGER.info("[%s %d/%d] %s 成功", round_label.strip(), completed_count, len(round_stocks), stock.htsc_code)
                    except Exception as exc:
                        failures[stock.htsc_code] = {"htsc_code": stock.htsc_code, "name": stock.name, "error": str(exc)}
                        LOGGER.error("[%s %d/%d] %s 失败: %s", round_label.strip(), completed_count, len(round_stocks), stock.htsc_code, exc)
                    if len(batch) >= args.batch_size:
                        flush_batch(batch, args.output_dir, run_id, completed_count)
                        batch.clear()
                    submit_next()

    run_round(stocks, "首次")
    failed_after_first_round = [stock for stock in stocks if stock.htsc_code in failures]
    if failed_after_first_round:
        LOGGER.warning("首次抓取失败 %d 只，开始本次任务内最后一次重试", len(failed_after_first_round))
        run_round(failed_after_first_round, "重试")
    if batch:
        flush_batch(batch, args.output_dir, run_id, len(stocks))
    if failures:
        failure_path.write_text(json.dumps(sorted(failures.values(), key=lambda item: item["htsc_code"]), ensure_ascii=False, indent=2), encoding="utf-8")
        LOGGER.warning("失败 %d 只，详情见 %s", len(failures), failure_path)
    elif failure_path.exists():
        failure_path.unlink()
        LOGGER.info("本次重试全部成功，已删除失败清单")
    current_failure_count = sum(code in failures for code in pending_codes)
    LOGGER.info("抓取完成：成功 %d/%d，失败 %d", len(stocks) - current_failure_count, len(stocks), current_failure_count)
    return 1 if current_failure_count else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        LOGGER.exception("脚本执行失败")
        raise
