#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ============================================================
# 文件名称：api_server.py
# 创建时间：2026-04-07
# 创建者 ：LimxTeam
# 设计哲学：极简 HTTP 服务骨架，先保证可用性与可观测性，再逐步挂接业务接口
# 功能描述：提供 API 服务入口，实现健康检查、市场 K 线查询与代码检索接口，输出统一 JSON 响应
# 技术特性：Python 标准库实现、结构化错误响应、参数化查询服务接入、可配置监听地址与端口、跨域访问支持
#
# ── 函数/方法表 ──────────────────────────────────────────────
# │ 函数名 │ 描述 │
# │──────────────────────────│───────────────────────────────│
# │ run_server() │ 启动 HTTP 服务 │
# │ ApiRequestHandler.do_GET() │ 处理 GET 请求并路由到业务接口 │
# │ ApiRequestHandler._send_json() │ 发送 JSON 响应 │
# │ ApiRequestHandler._handle_market_bars() │ 处理市场 K 线查询接口 │
# │ ApiRequestHandler._handle_code_search() │ 处理股票代码检索接口 │
# │ ApiRequestHandler.do_OPTIONS() │ 处理浏览器跨域预检请求 │
#
# ── 状态/变量表 ───────────────────────────────────────────────
# │ 变量名 │ 类型 │ 描述 │
# │──────────────────────────│──────────────────│────────────│
# │ DEFAULT_HOST │ str │ 默认监听地址 │
# │ DEFAULT_PORT │ int │ 默认监听端口 │
# │ SERVER_NAME │ str │ 服务名称 │
#
# ── 更新历史 ──────────────────────────────────────────────────
# │ 日期 │ 作者 │ 描述 │
# │─────────────│──────────│───────────────────────────────│
# │ 2026-04-07 │ LimxTeam │ 初始创建，完成 API 服务骨架与健康检查 │
# │ 2026-04-07 │ LimxTeam │ 新增 /api/market/bars 接口与错误映射 │
# │ 2026-04-07 │ LimxTeam │ 增加 CORS 响应头与 OPTIONS 预检处理 │
# │ 2026-04-07 │ LimxTeam │ 新增 /api/market/codes/search 接口 │
# │ 2026-04-08 │ LimxTeam │ 底层查询服务适配合并后的 month 级 Parquet 存储 │
# │ 2026-04-08 │ LimxTeam │ 支持前端按 interval 切换分钟线与日线数据源 │
# │ 2026-04-07 │ LimxTeam │ 因子接口新增 refresh 参数与快照 mode/group_id 路由 │
# ============================================================

from __future__ import annotations

import argparse
import errno
import json
import re
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from backtest_job_service import cancel_backtest_job, create_backtest_job, get_backtest_job
from fundamental_data_service import query_fundamental_panel, warmup_fundamental_views
from market_data_service import (
    delete_backtest_history,
    delete_backtest_portfolio_attachment,
    export_market_factor_rank_csv,
    get_backtest_history_detail,
    get_backtest_portfolio_attachment_meta,
    MarketDataError,
    MarketDataNotFoundError,
    MarketDataValidationError,
    list_signal_factors,
    list_backtest_history,
    query_latest_backtest_orders,
    query_latest_backtest_position_snapshot,
    query_latest_backtest_summary,
    list_market_index_codes,
    query_index_market_bars,
    query_market_bars,
    query_market_factor_couple_series,
    query_market_factor_snapshot,
    query_market_signal,
    query_morph_candlestick_signals,
    read_backtest_portfolio_attachment_file,
    save_backtest_portfolio_attachment,
    search_market_codes,
    get_watchlist_state,
    save_watchlist_state,
)


def _parse_multipart_form_simple(content_type: str, body: bytes) -> tuple[str | None, bytes | None, str | None]:
    """解析 multipart/form-data，提取 run_tag 文本与 file 文件体及原始文件名。"""
    if not content_type or "multipart/form-data" not in content_type.lower():
        raise ValueError("Content-Type 须为 multipart/form-data")
    m = re.search(r"boundary=([^;\s]+)", content_type, re.IGNORECASE)
    if not m:
        raise ValueError("缺少 boundary")
    boundary_token = m.group(1).strip().strip('"').encode("ascii", errors="ignore")
    if not boundary_token:
        raise ValueError("boundary 无效")
    boundary = b"--" + boundary_token
    parts = body.split(boundary)
    run_tag_val: str | None = None
    file_data: bytes | None = None
    file_name: str | None = None
    for part in parts[1:]:
        if part.startswith(b"--"):
            break
        chunk = part
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        header_end = chunk.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        headers_raw = chunk[:header_end].decode("latin-1", errors="replace")
        payload = chunk[header_end + 4 :]
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        cd_line = ""
        for line in headers_raw.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                cd_line = line
                break
        if not cd_line:
            continue
        name_m = re.search(r'name="([^"]+)"', cd_line)
        if not name_m:
            continue
        field_name = name_m.group(1)
        fn_m = re.search(r'filename="([^"]*)"', cd_line)
        if field_name == "run_tag":
            run_tag_val = payload.decode("utf-8", errors="replace").strip()
        elif field_name == "file" and fn_m is not None:
            file_name = fn_m.group(1) or "upload.bin"
            file_data = payload
    return run_tag_val, file_data, file_name


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
SERVER_NAME = "market-data-api"


class ReuseThreadingHTTPServer(ThreadingHTTPServer):
    """允许快速重启；工作线程设为 daemon，避免 Ctrl+C 后僵死占用端口。"""

    allow_reuse_address = True
    daemon_threads = True


class ApiRequestHandler(BaseHTTPRequestHandler): 
    """API 请求处理器。"""

    server_version = "MarketDataApi/1.1" 

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _send_bytes(self, status: HTTPStatus, content_type: str, data: bytes) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # 统一保留标准日志输出，便于排查线上请求问题
        super().log_message(format, *args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)

        if parsed.path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": SERVER_NAME,
                    "server_time": int(time.time()),
                    "features": ["index_codes", "index_bars", "fundamental", "run_tag_scoped_queries", "watchlist"],
                },
            )
            return

        if parsed.path == "/api/market/bars":
            self._handle_market_bars(query)
            return

        if parsed.path == "/api/market/codes/search":
            self._handle_code_search(query)
            return

        if parsed.path == "/api/market/fundamental":
            self._handle_market_fundamental(query)
            return

        if parsed.path == "/api/market/index-codes":
            self._handle_market_index_codes(query)
            return

        if parsed.path == "/api/market/index/bars":
            self._handle_market_index_bars(query)
            return

        if parsed.path == "/api/market/factors":
            self._handle_factor_list(query)
            return

        if parsed.path == "/api/market/signal":
            self._handle_market_signal(query)
            return

        if parsed.path == "/api/market/morph-candlestick":
            self._handle_morph_candlestick(query)
            return

        if parsed.path == "/api/market/factor-snapshot":
            self._handle_factor_snapshot(query)
            return

        if parsed.path == "/api/market/factor-export-rank":
            self._handle_factor_export_rank(query)
            return

        if parsed.path == "/api/backtest/summary/latest":
            self._handle_backtest_summary_latest()
            return

        if parsed.path == "/api/backtest/history":
            self._handle_backtest_history(query)
            return

        if parsed.path == "/api/backtest/history/detail":
            self._handle_backtest_history_detail(query)
            return

        if parsed.path == "/api/backtest/history/attachment/meta":
            self._handle_backtest_portfolio_attachment_meta(query)
            return

        if parsed.path == "/api/backtest/history/attachment/file":
            self._handle_backtest_portfolio_attachment_file(query)
            return

        if parsed.path == "/api/backtest/positions/snapshot":
            self._handle_backtest_position_snapshot(query)
            return

        if parsed.path == "/api/backtest/orders":
            self._handle_backtest_orders(query)
            return

        if parsed.path == "/api/backtest/jobs":
            self._handle_backtest_job_status(query)
            return

        if parsed.path == "/api/backtest/models":
            self._handle_backtest_models_catalog()
            return

        if parsed.path == "/api/watchlist":
            self._handle_watchlist_get()
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "请求的接口不存在",
                    "path": parsed.path,
                }
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/backtest/run":
            self._handle_backtest_run()
            return

        if parsed.path == "/api/backtest/job/cancel":
            self._handle_backtest_job_cancel()
            return

        if parsed.path == "/api/backtest/history/delete":
            self._handle_backtest_history_delete()
            return

        if parsed.path == "/api/backtest/history/attachment":
            self._handle_backtest_portfolio_attachment_upload()
            return

        if parsed.path == "/api/market/factor-couple":
            self._handle_factor_couple()
            return

        if parsed.path == "/api/watchlist":
            self._handle_watchlist_post()
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "请求的接口不存在",
                    "path": parsed.path,
                }
            },
        )

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/backtest/history/attachment":
            self._handle_backtest_portfolio_attachment_delete()
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "请求的接口不存在",
                    "path": parsed.path,
                }
            },
        )

    def _first_query_value(self, query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key)
        if not values:
            return None
        return values[0]

    def _read_json_body(self) -> dict:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise MarketDataValidationError("Content-Length 无效") from exc
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MarketDataValidationError(f"JSON 请求体无效: {exc}") from exc
        if not isinstance(body, dict):
            raise MarketDataValidationError("JSON 请求体必须是对象")
        return body

    def _read_request_body_bytes(self) -> bytes:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise MarketDataValidationError("Content-Length 无效") from exc
        if content_length <= 0:
            return b""
        return self.rfile.read(content_length)

    def _handle_market_bars(self, query: dict[str, list[str]]) -> None:
        try:
            result = query_market_bars(
                code=self._first_query_value(query, "code"),
                interval=self._first_query_value(query, "interval"),
                from_ts=self._first_query_value(query, "from"),
                to_ts=self._first_query_value(query, "to"),
                limit=self._first_query_value(query, "limit"),
                last_seen_bar_time=self._first_query_value(query, "last_seen_bar_time"),
                run_tag=self._first_query_value(query, "run_tag"),
                adjust=self._first_query_value(query, "adjust"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_market_index_bars(self, query: dict[str, list[str]]) -> None:
        try:
            result = query_index_market_bars(
                code=self._first_query_value(query, "code"),
                from_ts=self._first_query_value(query, "from"),
                to_ts=self._first_query_value(query, "to"),
                limit=self._first_query_value(query, "limit"),
                last_seen_bar_time=self._first_query_value(query, "last_seen_bar_time"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_market_index_codes(self, query: dict[str, list[str]]) -> None:
        try:
            refresh = self._first_query_value(query, "refresh") in ("1", "true", "True")
            result = list_market_index_codes(force_refresh=refresh)
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_market_fundamental(self, query: dict[str, list[str]]) -> None:
        try:
            result = query_fundamental_panel(code=self._first_query_value(query, "code"))
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_code_search(self, query: dict[str, list[str]]) -> None:
        try:
            result = search_market_codes(
                keyword=self._first_query_value(query, "q"),
                limit=self._first_query_value(query, "limit"),
                interval=self._first_query_value(query, "interval"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_factor_list(self, query: dict[str, list[str]]) -> None:
        try:
            result = list_signal_factors(
                interval=self._first_query_value(query, "interval"),
                refresh=self._first_query_value(query, "refresh"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_market_signal(self, query: dict[str, list[str]]) -> None:
        try:
            result = query_market_signal(
                code=self._first_query_value(query, "code"),
                interval=self._first_query_value(query, "interval"),
                factor=self._first_query_value(query, "factor"),
                from_ts=self._first_query_value(query, "from"),
                to_ts=self._first_query_value(query, "to"),
                limit=self._first_query_value(query, "limit"),
                last_seen_signal_time=self._first_query_value(query, "last_seen_signal_time"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_morph_candlestick(self, query: dict[str, list[str]]) -> None:
        try:
            result = query_morph_candlestick_signals(
                code=self._first_query_value(query, "code"),
                level=self._first_query_value(query, "level"),
                from_ts=self._first_query_value(query, "from"),
                to_ts=self._first_query_value(query, "to"),
                limit=self._first_query_value(query, "limit"),
                fields=self._first_query_value(query, "fields"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_factor_couple(self) -> None:
        try:
            payload = self._read_json_body()
            raw_factors = payload.get("factors")
            if not isinstance(raw_factors, list):
                raw_factors = payload.get("factor_names")
            result = query_market_factor_couple_series(
                code=payload.get("code"),
                interval=payload.get("interval") or "1day",
                factors=raw_factors if isinstance(raw_factors, list) else [],
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_factor_snapshot(self, query: dict[str, list[str]]) -> None:
        try:
            result = query_market_factor_snapshot(
                code=self._first_query_value(query, "code"),
                interval=self._first_query_value(query, "interval"),
                time_ts=self._first_query_value(query, "time"),
                mode=self._first_query_value(query, "mode"),
                group_id=self._first_query_value(query, "group_id"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_factor_export_rank(self, query: dict[str, list[str]]) -> None:
        try:
            result = export_market_factor_rank_csv(
                time_ts=self._first_query_value(query, "time"),
                factor=self._first_query_value(query, "factor"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_summary_latest(self) -> None:
        try:
            result = query_latest_backtest_summary()
            self._send_json(HTTPStatus.OK, result)
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_position_snapshot(self, query: dict[str, list[str]]) -> None:
        try:
            result = query_latest_backtest_position_snapshot(
                code=self._first_query_value(query, "code"),
                time_ts=self._first_query_value(query, "time"),
                run_tag=self._first_query_value(query, "run_tag"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_orders(self, query: dict[str, list[str]]) -> None:
        try:
            result = query_latest_backtest_orders(
                code=self._first_query_value(query, "code"),
                from_ts=self._first_query_value(query, "from"),
                to_ts=self._first_query_value(query, "to"),
                run_tag=self._first_query_value(query, "run_tag"),
            )
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务内部错误",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_watchlist_get(self) -> None:
        try:
            state = get_watchlist_state()
            self._send_json(HTTPStatus.OK, state)
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": {"code": "INTERNAL_ERROR", "message": "读取自选股失败", "detail": str(exc)}},
            )

    def _handle_watchlist_post(self) -> None:
        try:
            payload = self._read_json_body()
            result = save_watchlist_state(payload)
            self._send_json(HTTPStatus.OK, result)
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": {"code": "INTERNAL_ERROR", "message": "保存自选股失败", "detail": str(exc)}},
            )

    def _handle_backtest_models_catalog(self) -> None:
        import sys
        from pathlib import Path

        bt_dir = Path(__file__).resolve().parents[1] / "backtrader"
        s = str(bt_dir)
        if s not in sys.path:
            sys.path.append(s)
        try:
            from model_registry import list_models_public

            self._send_json(HTTPStatus.OK, {"models": list_models_public()})
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "读取回测模型目录失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_run(self) -> None:
        try:
            payload = self._read_json_body()
            result = create_backtest_job(payload)
            self._send_json(HTTPStatus.ACCEPTED, result)
        except (MarketDataValidationError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "回测任务创建失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_job_cancel(self) -> None:
        try:
            payload = self._read_json_body()
            result = cancel_backtest_job(payload.get("job_id"))
            self._send_json(HTTPStatus.OK, result)
        except (MarketDataValidationError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except KeyError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"任务不存在: {exc}",
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "终止任务失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_history(self, query: dict[str, list[str]]) -> None:
        limit: int | None = None
        offset = 0
        raw_limit = self._first_query_value(query, "limit")
        if raw_limit is not None and str(raw_limit).strip() != "":
            try:
                parsed_limit = int(str(raw_limit).strip())
                if parsed_limit > 0:
                    limit = parsed_limit
            except ValueError:
                limit = None
        raw_off = self._first_query_value(query, "offset")
        if raw_off is not None and str(raw_off).strip() != "":
            try:
                offset = int(str(raw_off).strip())
            except ValueError:
                offset = 0
        if offset < 0:
            offset = 0
        try:
            result = list_backtest_history(limit=limit, offset=offset)
            self._send_json(HTTPStatus.OK, result)
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "回测历史读取失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_history_detail(self, query: dict[str, list[str]]) -> None:
        try:
            run_tag = self._first_query_value(query, "run_tag")
            if not run_tag:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "error": {
                            "code": "INVALID_ARGUMENT",
                            "message": "缺少 run_tag 参数",
                        }
                    },
                )
                return
            result = get_backtest_history_detail(run_tag)
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "回测详情读取失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_history_delete(self) -> None:
        try:
            payload = self._read_json_body()
            result = delete_backtest_history(payload.get("run_tag"))
            self._send_json(HTTPStatus.OK, result)
        except (MarketDataValidationError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "回测历史删除失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_portfolio_attachment_meta(self, query: dict[str, list[str]]) -> None:
        try:
            run_tag = self._first_query_value(query, "run_tag")
            result = get_backtest_portfolio_attachment_meta(run_tag)
            self._send_json(HTTPStatus.OK, result)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "附图元数据读取失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_portfolio_attachment_file(self, query: dict[str, list[str]]) -> None:
        try:
            run_tag = self._first_query_value(query, "run_tag")
            blob, mime = read_backtest_portfolio_attachment_file(run_tag)
            self._send_bytes(HTTPStatus.OK, mime, blob)
        except MarketDataValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "附图读取失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_portfolio_attachment_upload(self) -> None:
        try:
            content_type = self.headers.get("Content-Type", "")
            body = self._read_request_body_bytes()
            run_tag, file_data, client_name = _parse_multipart_form_simple(content_type, body)
            if not run_tag:
                raise MarketDataValidationError("run_tag 不能为空")
            if not file_data:
                raise MarketDataValidationError("file 不能为空")
            result = save_backtest_portfolio_attachment(run_tag, file_data, client_name or "upload.png")
            self._send_json(HTTPStatus.OK, result)
        except (MarketDataValidationError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "附图上传失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_portfolio_attachment_delete(self) -> None:
        try:
            payload = self._read_json_body()
            result = delete_backtest_portfolio_attachment(payload.get("run_tag"))
            self._send_json(HTTPStatus.OK, result)
        except (MarketDataValidationError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataNotFoundError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": str(exc),
                    }
                },
            )
        except MarketDataError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "MARKET_DATA_ERROR",
                        "message": str(exc),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "附图删除失败",
                        "detail": str(exc),
                    }
                },
            )

    def _handle_backtest_job_status(self, query: dict[str, list[str]]) -> None:
        try:
            result = get_backtest_job(self._first_query_value(query, "id"))
            self._send_json(HTTPStatus.OK, result)
        except ValueError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": str(exc),
                    }
                },
            )
        except KeyError as exc:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "DATA_NOT_FOUND",
                        "message": f"回测任务不存在: {exc.args[0]}",
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "回测任务状态查询失败",
                        "detail": str(exc),
                    }
                },
            )


def _describe_port_conflict(host: str, port: int, exc: OSError) -> str:
    winaddrinuse = getattr(errno, "WSAEADDRINUSE", 10048)
    if exc.errno not in (errno.EADDRINUSE, winaddrinuse):
        return str(exc)
    return (
        f"无法绑定 {host}:{port}（端口已被占用）。\n"
        "常见原因：重复启动了 api_server，或上次未完全退出。\n"
        "处理：关闭所有 api_server 窗口后，运行 start_api_server.bat（会自动结束占用 8000 的旧进程）。"
    )


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """启动 API 服务。"""
    try:
        server = ReuseThreadingHTTPServer((host, port), ApiRequestHandler)
    except OSError as exc:
        print(f"[{SERVER_NAME}] 启动失败: {_describe_port_conflict(host, port, exc)}")
        raise SystemExit(1) from exc
    try:
        warmup_fundamental_views()
        print(f"[{SERVER_NAME}] fundamental views warmed")
    except Exception as exc:
        print(f"[{SERVER_NAME}] fundamental warmup skipped: {exc}")
    print(f"[{SERVER_NAME}] listening on http://{host}:{port}")
    print(f"[{SERVER_NAME}] health check: http://{host}:{port}/api/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n收到中断信号，正在关闭服务...")
    finally:
        server.server_close()
        server.socket.close()
        print("服务已停止")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="市场数据 API 服务")
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口，默认 8000")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_server(host=args.host, port=args.port)
