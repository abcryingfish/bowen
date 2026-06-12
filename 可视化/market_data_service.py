#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ============================================================
# 文件名称：market_data_service.py
# 创建时间：2026-04-07
# 创建者 ：LimxTeam
# 设计哲学：参数先校验后查询，按周期切换数据根目录，统一查询抽象以保证分钟线与日线共用服务能力
# 功能描述：提供 Parquet 市场数据查询服务，支持按 code/interval/time 范围读取分钟线和日线，并支持代码检索
# 技术特性：DuckDB 无状态连接、严格参数校验、按周期路由数据根目录、统一返回结构、窗口内最新段优先返回、代码索引缓存
#
# ── 函数/方法表 ──────────────────────────────────────────────
# │ 函数名 │ 描述 │
# │──────────────────────────│───────────────────────────────│
# │ query_market_bars() │ 查询并返回标准化 bars + meta │
# │ validate_query_params() │ 校验 code/interval/time/limit 参数 │
# │ get_base_path_by_interval() │ 根据周期返回对应数据根目录 │
# │ build_partition_paths() │ 按时间范围构建月度 parquet 路径 │
# │ search_market_codes() │ 按关键词检索股票代码（最多 5 条） │
#
# ── 状态/变量表 ───────────────────────────────────────────────
# │ 变量名 │ 类型 │ 描述 │
# │──────────────────────────│──────────────────│────────────│
# │ MINUTE_BASE_PATH │ str │ 分钟数据根目录 │
# │ DAILY_BASE_PATH │ str │ 日线数据根目录 │
# │ SUPPORTED_INTERVALS │ tuple[str, ...] │ 当前支持的周期集合 │
# │ DEFAULT_LIMIT │ int │ 默认返回条数 │
# │ MAX_LIMIT │ int │ 最大返回条数 │
#
# ── 更新历史 ──────────────────────────────────────────────────
# │ 日期 │ 作者 │ 描述 │
# │─────────────│──────────│───────────────────────────────│
# │ 2026-04-07 │ LimxTeam │ 初始创建，完成查询服务与参数校验 │
# │ 2026-04-07 │ LimxTeam │ 调整查询排序，优先返回时间窗口内最新数据段 │
# │ 2026-04-07 │ LimxTeam │ 新增股票代码检索能力（返回 5 条候选） │
# │ 2026-04-08 │ LimxTeam │ 适配 year/month/merged.parquet 合并存储结构 │
# │ 2026-04-08 │ LimxTeam │ 固定分钟数据根目录为 stock_basic_data_mins │
# │ 2026-04-08 │ LimxTeam │ 新增日线数据目录支持，并按周期动态切换数据源 │
# │ 2026-04-07 │ LimxTeam │ 新增因子目录配置加载，支持分组与核心因子快照模式 │
# │ 2026-04-07 │ LimxTeam │ 因子目录配置路径迁移至 因子分类/factor_catalog.json │
# ============================================================

from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
import uuid
import csv
from pathlib import Path
from threading import Lock
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import duckdb
from pypinyin import Style, pinyin

from daily_adjustment_service import adjust_daily_bars, normalize_adjust_mode
from temp_today_market_cache import (
    merge_bars_with_parquet_priority,
    query_today_daily_bar,
    query_today_minute_bars,
    should_supplement_daily,
    should_supplement_minute,
    today_cache_path,
)

MINUTE_BASE_PATH = r"D:\database\stock_basic_data_mins"
DAILY_BASE_PATH = r"D:\database\stock_basic_data_daily"
INDEX_DAILY_BASE_PATH = r"D:\database\index_data_daily"
PORTFOLIO_MINUTE_BASE_PATH = r"D:\database\stock_portfolio_data_mins"
PORTFOLIO_DAILY_BASE_PATH = r"D:\database\stock_portfolio_data_daily"
SIGNAL_DAILY_BASE_PATH = r"D:\database\signal_daily"
SIGNAL_DAILY_MORPH_BASE_PATH = r"D:\database\signal_daily_形态"
MORPH_CANDLESTICK_SOURCE_DIR = "candlestick_no_vol"
MORPH_CANDLESTICK_MANIFEST_FILE = "morph_candlestick_manifest.json"
MORPH_CANDLESTICK_LEVELS = frozenset({"level1", "level2", "level3"})
STOCK_UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "全市场股票代码" / "universe.parquet"
BACKTEST_SUMMARY_BASE_PATH = Path(r"D:\database\total_record")
BACKTEST_POSITION_BASE_PATH = Path(r"D:\database\bs_dialy")
PORTFOLIO_PICT_BASE_PATH = Path(r"D:\database\store_porfolio_pict")
PORTFOLIO_PICT_INDEX_NAME = "attachments_index.json"
PORTFOLIO_PICT_MAX_BYTES = 5 * 1024 * 1024
_PORTFOLIO_PICT_INDEX_LOCK = Lock()
RUN_TAG_PATTERN = re.compile(r"^[0-9A-Za-z_\-]+$")
_ALLOWED_PICT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MIME_BY_SUFFIX: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# 组合净值曲线代码集合
PORTFOLIO_CURVE_CODES = {"000000.YKRS", "0000000.YKRS", "000001.YKRS"}
BUY_HOLD_CURVE_CODE = "000001.YKRS"
PORTFOLIO_INITIAL_CASH = 10_000_000.0
MERGED_FILE_NAME = "merged.parquet"
DEFAULT_INDEX_CODES: tuple[str, ...] = ("000001.SH", "399001.SZ")
INDEX_CODE_LABELS: dict[str, str] = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
}
_index_market_code_cache: set[str] | None = None
FACTOR_DIR_PREFIX = "factor="
BACKTEST_SUMMARY_FILE_GLOB = "summary_*.json"
BACKTEST_POSITION_FILE_GLOB = "position_log_*.parquet"
BACKTEST_ORDER_FILE_GLOB = "order_log_*.*"
FACTOR_CATALOG_PATH = Path(__file__).resolve().parents[1] / "因子分类" / "factor_catalog.json"
SUPPORTED_INTERVALS = ("1min", "1day")
TEMP_TODAY_MARKET_CACHE_PATH = os.environ.get("TEMP_TODAY_MARKET_CACHE_PATH", "")

# 目录 JSON 常用中文名与宽表可能出现的英文列名（与 ZXW因子/MACD因子.py factor_name_map 对齐）
_FACTOR_DISPLAY_TO_INTERNAL: dict[str, tuple[str, ...]] = {
    "MAC总": ("mac_total",),
    "DIF": ("dif",),
    "DEA": ("dea",),
    "MAC": ("mac",),
    "红柱": ("red_bar",),
    "金叉": ("golden_cross",),
    "绿柱": ("green_bar",),
    "死叉": ("death_cross",),
    "P标弧底": ("p_mark_arc_bottom",),
    "P弧新低初": ("p_new_low_start",),
    "P新低初背离": ("p_initial_bottom_divergence",),
    "P新低延续背离": ("p_continued_bottom_divergence",),
    "P标弧顶(MAC总)": ("p_mark_arc_top",),
    "P弧新高初(MAC总)": ("p_new_high_start",),
    "P新高初背离(MAC总)": ("p_initial_top_divergence",),
    "P新高延续背离(MAC总)": ("p_continued_top_divergence",),
    "MAC总顶背离": ("top_divergence_in_mac_total",),
    "底背离": ("bottom_divergence",),
    "底背离&红柱": ("bottom_divergence_and_red_bar",),
    "底背离&金叉": ("bottom_divergence_and_golden_cross",),
    "金叉&红柱": ("golden_cross_and_red_bar",),
    "FTR": ("ftr",),
    "P标弧顶": ("p_mark_arc_top",),
    "P弧新高初": ("p_new_high_start",),
    "P新高初背离": ("p_initial_top_divergence",),
    "P新高延续背离": ("p_continued_top_divergence",),
    "顶背离": ("top_divergence",),
    "顶背离&绿柱": ("top_divergence_and_green_bar",),
    "顶背离&死叉": ("top_divergence_and_death_cross",),
    "死叉&绿柱": ("death_cross_and_green_bar",),
    "MAC卖出总": ("mac_sell_total",),
    "后穿D数": ("back_cross_d_count",),
    "最高P至今": ("highest_p_since",),
    "PHL": ("phl",),
    "U域": ("u_zone",),
    "SHL": ("shl",),
    "LHL": ("lhl",),
    "低距L": ("low_range_l",),
    "顶距H": ("top_range_h",),
    "TLL": ("tll",),
    "阴形量": ("negative_shape_volume",),
    "纯阴量": ("pure_negative_volume",),
    "前D阳顶": ("prior_d_positive_top",),
    "后穿F数": ("back_cross_f_count",),
    "后阴顶穿": ("negative_top_break",),
    "基础下笔反K时长": ("base_lower_stroke_reverse_k_duration",),
    "下笔反K": ("lower_stroke_reverse_k",),
    "阴J贯穿": ("negative_j_break",),
    "S笔反K": ("upper_stroke_reverse_k",),
    "RSV": ("rsv",),
    "K值": ("k_value",),
    "D值": ("d_value",),
    "J值": ("j_raw",),
    "J值超卖因子": ("j_oversold_factor",),
    "J值超买因子": ("j_overbought_factor",),
    "R条件": ("r_condition", "KDJ信号"),
    "KDJ信号": ("r_condition", "R条件"),
    "迷你底": ("mini_bottom",),
    "小底": ("small_bottom",),
    "大底": ("major_bottom",),
    "近历史大底": ("near_historical_bottom",),
    "历史大底": ("historical_bottom",),
    "抄底总分": ("bottom_fishing_score",),
    "逃顶总分": ("top_escape_score",),
    "平阳量": ("flat_positive_volume",),
    "后穿情形": ("back_cross_situation",),
    "MAX上笔反K": ("max_upper_stroke_reverse_k",),
    "五年底": ("five_year_bottom",),
    "两年底": ("two_year_bottom",),
    "大底抬升": ("major_bottom_lift",),
    "两五大底抬升": ("two_five_year_bottom_lift",),
    "价同比数": ("price_yoy_ratio",),
    "K同比数": ("k_yoy_ratio",),
    "年内双底": ("yearly_double_bottom",),
    "近年内双底": ("recent_yearly_double_bottom",),
    "年内底": ("yearly_bottom",),
    "近年内底": ("recent_yearly_bottom",),
    "年内双底抬升": ("yearly_double_bottom_lift",),
    "K线底数": ("kline_bottom_rank_raw",),
    "K线底基": ("kline_bottom_base",),
    "K底": ("k_bottom",),
    "相对低顶": ("relative_low_top",),
    "K底要求": ("k_bottom_requirement",),
    "K线底1": ("kline_bottom_1",),
    "K底来要求": ("k_bottom_arrival_requirement",),
    "K底来幅": ("k_bottom_arrival_base",),
    "K线底2": ("kline_bottom_2",),
    "K线底": ("kline_bottom",),
    "历史大顶": ("historical_top",),
    "五年顶": ("five_year_top",),
    "近历史大顶": ("near_historical_top",),
    "两年顶": ("two_year_top",),
    "大顶回落": ("major_top_drop",),
    "两五大顶回落": ("two_five_year_top_drop",),
    "年内双顶": ("yearly_double_top",),
    "近年内双顶": ("recent_yearly_double_top",),
    "年内顶": ("yearly_top",),
    "近年内顶": ("recent_yearly_top",),
    "年内双顶回落": ("yearly_double_top_drop",),
    "K线顶数": ("kline_top_rank_raw",),
    "K线顶基": ("kline_top_base",),
    "K顶": ("k_top",),
    "相对高底": ("relative_high_bottom",),
    "K顶要求": ("k_top_requirement",),
    "K线顶1": ("kline_top_1",),
    "K顶来要求": ("k_top_arrival_requirement",),
    "K顶来幅": ("k_top_arrival_base",),
    "K线顶2": ("kline_top_2",),
    "K线顶": ("kline_top",),
    "洪迷你底": ("hong_mini_bottom",),
    "洪小底": ("hong_small_bottom",),
    "洪大底": ("hong_major_bottom",),
    "洪近历史大底": ("hong_near_historical_bottom",),
    "洪历史大底": ("hong_historical_bottom",),
    "洪抄底总分": ("hong_bottom_fishing_score",),
    "单峰密度指标": ("single_peak_density_value", "单峰密度指标"),
    "筹码单峰密度": ("chip_single_peak_density", "筹码单峰密度"),
    "核心宽度占比指标": ("single_peak_core_ratio_value", "核心宽度占比指标"),
    "核心宽度占比条件": ("chip_single_peak_core_ratio_condition", "核心宽度占比条件"),
    "筹码单峰态": ("chip_single_peak_state", "筹码单峰态"),
    "峰中心价格": ("single_peak_center_price", "峰中心价格"),
    "成本34": ("cost_34pct_interp", "成本34"),
    "成本35": ("cost_35pct_interp", "成本35"),
    "成本66": ("cost_66pct_interp", "成本66"),
    "成本67": ("cost_67pct_interp", "成本67"),
    "低位单峰": ("chip_single_peak_low", "低位单峰"),
    "中位单峰": ("chip_single_peak_mid", "中位单峰"),
    "高位单峰": ("chip_single_peak_high", "高位单峰"),
    "替代成本价": ("single_peak_replacement_cost", "替代成本价"),
    "筹码单峰优": ("chip_single_peak_best", "筹码单峰优"),
    "集中度": ("chip_concentration", "集中度"),
    "核心集中度": ("core_chip_concentration", "核心集中度"),
    "核心占比": ("core_chip_ratio", "核心占比"),
    "筹码中心位置": ("chip_center_position", "筹码中心位置"),
    "集中度评分": ("chip_concentration_score", "集中度评分"),
    "核心集中度评分": ("core_chip_concentration_score", "核心集中度评分"),
    "核心占比评分": ("core_chip_ratio_score", "核心占比评分"),
    "集中总分": ("chip_concentration_total_score", "集中总分"),
    "RSI6": ("rsi_6", "RSI6"),
    "RSI12": ("rsi_12", "RSI12"),
    "RSI24": ("rsi_24", "RSI24"),
    "RSI48": ("rsi_48", "RSI48"),
    "RSI96": ("rsi_96", "RSI96"),
    "RSI120": ("rsi_120", "RSI120"),
    "RSI超卖": ("rsi_6_oversold", "RSI超卖"),
    "RSI超买": ("rsi_6_overbought", "RSI超买"),
    "RSI金叉": ("rsi_6_cross_up_rsi_12", "RSI金叉"),
    "RSI死叉": ("rsi_6_cross_down_rsi_12", "RSI死叉"),
    "RSI多头排列": ("rsi_multi_bullish", "RSI多头排列"),
    "RSI空头排列": ("rsi_multi_bearish", "RSI空头排列"),
    "RSI极端超卖": ("rsi_6_extreme_oversold", "RSI极端超卖"),
    "RSI买入信号": ("rsi_6_extreme_oversold", "RSI极端超卖", "RSI买入信号"),
    "RSI总分": ("rsi_total_score", "RSI总分"),
    # OBV类因子
    "OBV": ("obv",),
    "OBV斜率20": ("obv_slope_20",),
    "OBV斜率60": ("obv_slope_60",),
    "OBV斜率120": ("obv_slope_120",),
    "OBV多头排列": ("obv_bullish_arrange",),
    "OBV相对位置": ("obv_position_ratio",),
    "OBV顶背离": ("obv_bearish_divergence",),
    "OBV底背离": ("obv_bullish_divergence",),
    "OBV动量20": ("obv_mom_20",),
    "OBV动量60": ("obv_mom_60",),
    "OBV加速度": ("obv_accel",),
    "OBV波动率": ("obv_volatility",),
    "OBV集中度": ("obv_concentration",),
    "OBV价共振": ("obv_price_combo",),
    "OBV突破": ("obv_breakout",),
    "OBV总分": ("obv_total_score",),
    "唐奇安下轨": ("唐奇安下轨",),
    "唐奇安下破": ("唐奇安下破",),
    "动态波动率通道": ("动态波动率通道",),
    "动态波动率下破": ("动态波动率下破",),
    "20日新高占比": ("new_high_ratio_20d", "20日新高占比"),
    "20日新低占比": ("new_low_ratio_20d", "20日新低占比"),
    "总卖出信号": ("total_sell_signal", "总卖出信号"),
    "布林上轨": ("boll_upper", "布林上轨"),
    "布林中轨": ("boll_mid", "布林中轨"),
    "布林下轨": ("boll_lower", "布林下轨"),
    "上穿上布林带": ("cross_up_boll_upper", "上穿上布林带"),
    "下穿上布林带": ("cross_down_boll_upper", "下穿上布林带"),
    "上穿下布林带": ("cross_up_boll_lower", "上穿下布林带"),
    "下穿下布林带": ("cross_down_boll_lower", "下穿下布林带"),
    "MA5": ("ma_5", "MA5"),
    "MA10": ("ma_10", "MA10"),
    "MA15": ("ma_15", "MA15"),
    "MA20": ("ma_20", "MA20"),
    "MA30": ("ma_30", "MA30"),
    "MA40": ("ma_40", "MA40"),
    "MA50": ("ma_50", "MA50"),
    "MA60": ("ma_60", "MA60"),
    "MA70": ("ma_70", "MA70"),
    "MA120": ("ma_120", "MA120"),
    "价格下穿MA5": ("dead_cross_price_ma5", "价格下穿MA5"),
    "价格下穿MA10": ("dead_cross_price_ma10", "价格下穿MA10"),
    "价格下穿MA15": ("dead_cross_price_ma15", "价格下穿MA15"),
    "价格下穿MA20": ("dead_cross_price_ma20", "价格下穿MA20"),
    "价格下穿MA30": ("dead_cross_price_ma30", "价格下穿MA30"),
    "价格下穿MA40": ("dead_cross_price_ma40", "价格下穿MA40"),
    "价格下穿MA50": ("dead_cross_price_ma50", "价格下穿MA50"),
    "价格下穿MA60": ("dead_cross_price_ma60", "价格下穿MA60"),
    "价格下穿MA70": ("dead_cross_price_ma70", "价格下穿MA70"),
    "价格下穿MA120": ("dead_cross_price_ma120", "价格下穿MA120"),
    "MA5下穿MA10": ("dead_cross_ma5_ma10", "MA5下穿MA10"),
    "MA5下穿MA15": ("dead_cross_ma5_ma15", "MA5下穿MA15"),
    "MA15下穿MA20": ("dead_cross_ma15_ma20", "MA15下穿MA20"),
    "量比20": ("volume_ratio_20", "量比20"),
    "小放量下跌": ("small_volume_drop", "小放量下跌"),
    "中放量下跌": ("medium_volume_drop", "中放量下跌"),
    "大放量下跌": ("large_volume_drop", "大放量下跌"),
    "放量下跌": ("volume_drop_signal", "放量下跌"),
    "放量1.2倍": ("volume_surge_1_2x", "放量1.2倍"),
    "放量1.5倍": ("volume_surge_1_5x", "放量1.5倍"),
    "放量1.8倍": ("volume_surge_1_8x", "放量1.8倍"),
    "放量2倍": ("volume_surge_2x", "放量2倍"),
    "放量3倍": ("volume_surge_3x", "放量3倍"),
    "总买入信号": ("total_buy_signal",),
    "总买入信号改": ("total_buy_signal_adjusted",),
    "总买入信号（去两弱）": ("total_buy_signal_no_two_weak",),
    "总买入超强底": ("super_strong_bottom",),
    "强底": ("tdx_strong_bottom",),
    "超强底": ("tdx_super_strong_bottom",),
    "五日内六级": ("tdx_five_day_level6",),
    "五日内六级（去掉集中总）": ("tdx_five_day_level6_no_concentration",),
    "MAC总信号": ("tdx_signal_e",),
    "K线底信号": ("tdx_signal_k",),
    "集中总信号": ("tdx_signal_a",),
    "筹码峰信号": ("tdx_signal_b",),
    "均线类信号": ("tdx_signal_i",),
    "KDJ超卖R信号": ("tdx_signal_r",),
    "ZXW因子": ("zxw_factor", "ZXW因子"),
    "ZXW因子+破30日均线": ("zxw_factor_below_ma30",),
    "ZXW因子+破60日均线": ("zxw_factor_below_ma60",),
    "卖出因子（1.5-60）": ("sell_factor_1_5_60",),
    "卖出因子（2-60）": ("sell_factor_2_60",),
    "卖出因子（1.5-120）": ("sell_factor_1_5_120",),
    "卖出因子（2-120）": ("sell_factor_2_120",),
}


def _resolve_factor_column_name(requested: str, available: set[str]) -> str | None:
    """将目录/配置中的因子名解析为当前 Parquet 中实际存在的列名。"""
    s = str(requested).strip()
    if not s:
        return None
    if s in available:
        return s
    for alt in _FACTOR_DISPLAY_TO_INTERNAL.get(s, ()):
        if alt in available:
            return alt
    for _display, alts in _FACTOR_DISPLAY_TO_INTERNAL.items():
        if s in alts:
            if s in available:
                return s
            if _display in available:
                return _display
            for alt2 in alts:
                if alt2 in available:
                    return alt2
    return None


def _build_factor_display_label_map(available_factors: list[str]) -> dict[str, str]:
    available_set = set(available_factors)
    label_map: dict[str, str] = {name: name for name in available_factors}
    for display_name, aliases in _FACTOR_DISPLAY_TO_INTERNAL.items():
        if display_name in available_set:
            label_map[display_name] = display_name
        for alias in aliases:
            if alias in available_set and (alias not in label_map or label_map[alias] == alias):
                label_map[alias] = display_name
    return label_map
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000

# 因子耦合：全历史按 UTC 日历日起点扫描；单因子读 DuckDB 最大日点数（防止响应过大）
FACTOR_COUPLE_FULL_HISTORY_FROM_TS = 946684800  # 2000-01-01 00:00:00 UTC
FACTOR_COUPLE_MAX_FACTORS = 20
FACTOR_COUPLE_MAX_DAILY_ROWS = 200_000

DEFAULT_LOOKBACK_SECONDS = 24 * 60 * 60
DAILY_DEFAULT_LOOKBACK_SECONDS = 730 * 24 * 60 * 60
CODE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SEARCH_QUERY_ALLOWED_PATTERN = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9._-]+$")
FACTOR_DIR_INVALID_CHAR_PATTERN = re.compile(r'[\\/:*?"<>|]')
CODE_SEARCH_LIMIT = 5
CODE_SEARCH_REFRESH_INTERVAL_SECONDS = 300

_code_index_lock = Lock()
_code_index_cache_by_path: dict[str, list[str]] = {}
_code_index_cache_ts_by_path: dict[str, float] = {}
_bar_boundary_lock = Lock()
_bar_boundary_cache_by_key: dict[tuple[str, str], dict[str, int | None]] = {}
_bar_boundary_cache_ts_by_key: dict[tuple[str, str], float] = {}
_factor_index_lock = Lock()
_factor_index_cache_by_path: dict[str, list[str]] = {}
_factor_index_cache_ts_by_path: dict[str, float] = {}
_factor_catalog_lock = Lock()
_factor_catalog_cache: dict[str, Any] = {"data": None, "loaded_at": 0.0}

_stock_universe_lock = Lock()
_stock_universe_cache: list[dict[str, str]] = []
_stock_universe_mtime: float = 0.0


def _build_name_pinyin_aliases(name: str) -> tuple[str, ...]:
    text = str(name or "").strip()
    if not text:
        return ()
    try:
        syllables = pinyin(text, style=Style.NORMAL, heteronym=True)
    except Exception:
        return ()

    aliases: list[str] = [""]
    initials_aliases: list[str] = [""]
    for options in syllables:
        normalized_options: list[str] = []
        for option in options or []:
            cleaned = re.sub(r"[^A-Za-z0-9]+", "", str(option or "").strip()).upper()
            if cleaned and cleaned not in normalized_options:
                normalized_options.append(cleaned)
        if not normalized_options:
            continue
        next_aliases: list[str] = []
        next_initials_aliases: list[str] = []
        for prefix in aliases:
            for cleaned in normalized_options:
                candidate = f"{prefix}{cleaned}"
                if candidate not in next_aliases:
                    next_aliases.append(candidate)
                if len(next_aliases) >= 32:
                    break
            if len(next_aliases) >= 32:
                break
        for prefix in initials_aliases:
            for cleaned in normalized_options:
                candidate = f"{prefix}{cleaned[:1]}"
                if candidate not in next_initials_aliases:
                    next_initials_aliases.append(candidate)
                if len(next_initials_aliases) >= 32:
                    break
            if len(next_initials_aliases) >= 32:
                break
        aliases = next_aliases or aliases
        initials_aliases = next_initials_aliases or initials_aliases
    merged: list[str] = []
    for alias in [*aliases, *initials_aliases]:
        if alias and alias not in merged:
            merged.append(alias)
    return tuple(merged)


class MarketDataError(Exception):
    """市场数据服务基础异常。"""


class MarketDataValidationError(MarketDataError):
    """参数校验失败异常。"""


class MarketDataNotFoundError(MarketDataError):
    """分区或数据不存在异常。"""


@dataclass(frozen=True)
class QueryParams:
    """市场数据查询参数对象。"""

    code: str
    interval: str
    from_ts: int
    to_ts: int
    limit: int
    last_seen_bar_time: Optional[int]


def get_base_path_by_interval(interval: str) -> str:
    if interval == "1min":
        return MINUTE_BASE_PATH
    if interval == "1day":
        return DAILY_BASE_PATH
    raise MarketDataValidationError(f"interval 仅支持: {', '.join(SUPPORTED_INTERVALS)}")


def is_portfolio_curve_code(code: str) -> bool:
    """判断是否为组合净值曲线代码。"""
    return code is not None and code.upper() in PORTFOLIO_CURVE_CODES


def _refresh_index_market_code_cache() -> set[str]:
    """合并默认指数与 index_data_daily 分区中已落盘的 htsc_code。"""
    global _index_market_code_cache
    codes: set[str] = {c.upper() for c in DEFAULT_INDEX_CODES}
    if os.path.exists(INDEX_DAILY_BASE_PATH):
        try:
            codes.update(c.upper() for c in _scan_all_codes_from_path(INDEX_DAILY_BASE_PATH))
        except MarketDataError:
            pass
    _index_market_code_cache = codes
    return codes


def get_index_market_code_set() -> set[str]:
    if _index_market_code_cache is None:
        return _refresh_index_market_code_cache()
    return _index_market_code_cache


def is_index_market_code(code: str) -> bool:
    """是否为指数日频代码（走 index_data_daily）。"""
    parsed = str(code or "").strip().upper()
    return bool(parsed) and parsed in get_index_market_code_set()


def list_market_index_codes(force_refresh: bool = False) -> dict[str, Any]:
    """返回可选指数列表，供组合结果页 portfolio-extra-select 使用。"""
    if force_refresh:
        _refresh_index_market_code_cache()
    code_set = get_index_market_code_set()
    ordered: list[str] = []
    for code in DEFAULT_INDEX_CODES:
        upper = code.upper()
        if upper in code_set and upper not in ordered:
            ordered.append(upper)
    for code in sorted(code_set):
        if code not in ordered:
            ordered.append(code)
    items = [
        {
            "code": code,
            "name": INDEX_CODE_LABELS.get(code, code),
        }
        for code in ordered
    ]
    return {
        "items": items,
        "meta": {
            "count": len(items),
            "base_path": INDEX_DAILY_BASE_PATH,
            "server_time": int(time.time()),
        },
    }


def query_index_market_bars(
    code: Any,
    from_ts: Any = None,
    to_ts: Any = None,
    limit: Any = None,
    last_seen_bar_time: Any = None,
) -> dict[str, Any]:
    """查询指数日频 K 线（固定走 index_data_daily，供组合结果页叠加）。"""
    return query_market_bars(
        code=code,
        interval="1day",
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        last_seen_bar_time=last_seen_bar_time,
        base_path=INDEX_DAILY_BASE_PATH,
        adjust="none",
    )


def get_portfolio_daily_base_path(run_tag: str) -> str:
    """组合日频曲线按 run_tag 分目录存储与读取。"""
    parsed = _validate_run_tag_format(str(run_tag or "").strip())
    return os.path.join(PORTFOLIO_DAILY_BASE_PATH, f"run_tag={parsed}")


def get_base_path_by_code_and_interval(code: str, interval: str, run_tag: str | None = None) -> str:
    """根据股票代码和周期返回对应数据根目录。组合曲线走独立目录。"""
    if is_portfolio_curve_code(code):
        if interval == "1min":
            return PORTFOLIO_MINUTE_BASE_PATH
        if interval == "1day":
            if run_tag:
                return get_portfolio_daily_base_path(run_tag)
            raise MarketDataValidationError("组合曲线查询须提供 run_tag")
    if is_index_market_code(code):
        if interval != "1day":
            raise MarketDataValidationError("指数数据当前仅支持 interval=1day")
        return INDEX_DAILY_BASE_PATH
    return get_base_path_by_interval(interval)


def _parse_optional_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise MarketDataValidationError(f"{field_name} 不能为布尔值")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip() != "":
        try:
            return int(value.strip())
        except ValueError as exc:
            raise MarketDataValidationError(f"{field_name} 必须为整数时间戳") from exc
    raise MarketDataValidationError(f"{field_name} 参数无效")


def _parse_limit(value: Any) -> int:
    if value is None or value == "":
        return DEFAULT_LIMIT
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataValidationError("limit 必须为整数") from exc
    if parsed <= 0:
        raise MarketDataValidationError("limit 必须大于 0")
    return min(parsed, MAX_LIMIT)


def validate_query_params(
    code: Any,
    interval: Any,
    from_ts: Any = None,
    to_ts: Any = None,
    limit: Any = None,
    last_seen_bar_time: Any = None,
) -> QueryParams:
    """校验并标准化查询参数。"""
    parsed_code = str(code).strip() if code is not None else ""
    if not parsed_code:
        raise MarketDataValidationError("code 不能为空")
    if not CODE_PATTERN.match(parsed_code):
        raise MarketDataValidationError("code 仅允许字母、数字、点、下划线和中划线")

    parsed_interval = str(interval).strip() if interval is not None else ""
    if parsed_interval not in SUPPORTED_INTERVALS:
        raise MarketDataValidationError(f"interval 仅支持: {', '.join(SUPPORTED_INTERVALS)}")

    parsed_from_ts = _parse_optional_int(from_ts, "from")
    parsed_to_ts = _parse_optional_int(to_ts, "to")
    now_ts = int(time.time())

    if parsed_to_ts is None:
        parsed_to_ts = now_ts
    if parsed_from_ts is None:
        default_lookback_seconds = (
            DAILY_DEFAULT_LOOKBACK_SECONDS if parsed_interval == "1day" else DEFAULT_LOOKBACK_SECONDS
        )
        parsed_from_ts = parsed_to_ts - default_lookback_seconds

    if parsed_from_ts > parsed_to_ts:
        raise MarketDataValidationError("from 不能大于 to")

    if parsed_interval == "1min" and (parsed_from_ts % 60 != 0 or parsed_to_ts % 60 != 0):
        raise MarketDataValidationError("from 和 to 必须精确到分钟（秒数需为 60 的倍数）")

    parsed_limit = _parse_limit(limit)
    parsed_last_seen = _parse_optional_int(last_seen_bar_time, "last_seen_bar_time")

    return QueryParams(
        code=parsed_code,
        interval=parsed_interval,
        from_ts=parsed_from_ts,
        to_ts=parsed_to_ts,
        limit=parsed_limit,
        last_seen_bar_time=parsed_last_seen,
    )


def _iter_year_month(from_ts: int, to_ts: int) -> list[tuple[int, int]]:
    start_dt = datetime.utcfromtimestamp(from_ts)
    end_dt = datetime.utcfromtimestamp(to_ts)
    year = start_dt.year
    month = start_dt.month
    result: list[tuple[int, int]] = []
    while (year < end_dt.year) or (year == end_dt.year and month <= end_dt.month):
        result.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


def _list_partition_data_files(month_dir: str) -> list[str]:
    """返回一个月分区内可读的数据文件：merged 优先，再读增量 part。"""
    if not os.path.isdir(month_dir):
        return []

    paths: list[str] = []
    merged_path = os.path.join(month_dir, MERGED_FILE_NAME)
    if os.path.exists(merged_path) and os.path.isfile(merged_path):
        paths.append(merged_path.replace("\\", "/"))

    for file_name in sorted(os.listdir(month_dir)):
        if not file_name.startswith("part_") or not file_name.endswith(".parquet"):
            continue
        part_path = os.path.join(month_dir, file_name)
        if os.path.isfile(part_path):
            paths.append(part_path.replace("\\", "/"))
    return paths


def build_partition_paths(base_path: str, from_ts: int, to_ts: int) -> list[str]:
    """按时间范围构建存在的月度数据文件路径集合（merged + part）。"""
    paths: list[str] = []
    for year, month in _iter_year_month(from_ts, to_ts):
        month_str = f"{month:02d}"
        month_dir = os.path.join(
            base_path,
            f"year={year}",
            f"month={month_str}",
        )
        paths.extend(_list_partition_data_files(month_dir))
    return paths


def _sanitize_factor_dir_name(factor_name: str) -> str:
    safe_name = FACTOR_DIR_INVALID_CHAR_PATTERN.sub("_", str(factor_name).strip())
    safe_name = safe_name.rstrip(" .")
    return safe_name or "未命名因子"


def _list_factor_names_from_dirs(base_path: str) -> list[str]:
    if not os.path.exists(base_path):
        return []
    factor_names: list[str] = []
    for name in os.listdir(base_path):
        if not name.startswith(FACTOR_DIR_PREFIX):
            continue
        full_path = os.path.join(base_path, name)
        if not os.path.isdir(full_path):
            continue
        factor_name = name[len(FACTOR_DIR_PREFIX) :].strip()
        if factor_name:
            factor_names.append(factor_name)
    return sorted(set(factor_names))


def _build_factor_partition_paths(base_path: str, factor_name: str, from_ts: int, to_ts: int) -> list[str]:
    safe_factor = _sanitize_factor_dir_name(factor_name)
    factor_base = os.path.join(base_path, f"{FACTOR_DIR_PREFIX}{safe_factor}")
    if not os.path.exists(factor_base):
        return []
    paths: list[str] = []
    for year, month in _iter_year_month(from_ts, to_ts):
        month_str = f"{month:02d}"
        month_dir = os.path.join(
            factor_base,
            f"year={year}",
            f"month={month_str}",
        )
        paths.extend(_list_partition_data_files(month_dir))
    return paths


def query_latest_backtest_summary() -> dict[str, Any]:
    """读取最新一份 backtrader summary JSON。"""
    if not BACKTEST_SUMMARY_BASE_PATH.exists():
        raise MarketDataNotFoundError(f"回测摘要目录不存在: {BACKTEST_SUMMARY_BASE_PATH}")

    candidates = sorted(
        BACKTEST_SUMMARY_BASE_PATH.glob(BACKTEST_SUMMARY_FILE_GLOB),
        key=lambda item: (item.stat().st_mtime, item.name),
        reverse=True,
    )
    if not candidates:
        raise MarketDataNotFoundError("未找到 summary JSON，请先运行 backtrader/流程.ipynb")

    latest_path = candidates[0]
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataError(f"读取回测摘要失败: {exc}") from exc

    if not isinstance(payload, dict):
        raise MarketDataError("summary JSON 格式无效，需为对象")

    payload["summary_path"] = str(latest_path)
    payload["server_time"] = int(time.time())
    return payload


def _parse_run_tag_from_summary_path(path: Path) -> str:
    stem = path.stem
    return stem.replace("summary_", "", 1) if stem.startswith("summary_") else stem


def _format_run_tag_time(run_tag: str, fallback_ts: float) -> str:
    for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d_%H%M"):
        try:
            return datetime.strptime(run_tag, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_ts).strftime("%Y-%m-%d %H:%M:%S")


def _safe_read_summary_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


_SUMMARY_LIST_SCALAR_KEYS: tuple[str, ...] = (
    "回测名称",
    "年化收益率 (%)",
    "累计收益率（扣手续费）",
    "夏普比率",
    "最大回撤 (%)",
    "log((Rp-Rb)/下半方差（P）)",
)
_SUMMARY_LIST_LITE_FULL_PARSE_BYTES = 256 * 1024
_SUMMARY_LIST_LITE_PREFIX_BYTES = 512 * 1024


def _json_extract_scalar_from_text(text: str, key: str) -> Any | None:
    """从 JSON 文本片段中提取单个顶层标量字段（数字或字符串）。"""
    escaped_key = re.escape(key)
    num_match = re.search(
        rf'"{escaped_key}"\s*:\s*(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)',
        text,
    )
    if num_match:
        raw = num_match.group(1)
        if "." in raw or "e" in raw.lower():
            try:
                return float(raw)
            except ValueError:
                pass
        else:
            try:
                return int(raw)
            except ValueError:
                pass
    str_match = re.search(rf'"{escaped_key}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    if str_match:
        try:
            return json.loads(f'"{str_match.group(1)}"')
        except json.JSONDecodeError:
            return str_match.group(1)
    if re.search(rf'"{escaped_key}"\s*:\s*null\b', text):
        return None
    return None


def _json_extract_nested_string_from_text(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    if not match:
        return None
    try:
        value = json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        value = match.group(1)
    parsed = str(value or "").strip()
    return parsed or None


def _read_summary_list_lite(path: Path) -> dict[str, Any] | None:
    """列表页只读 summary 文件头与卡片展示指标，避免解析持仓大表等大字段。"""
    try:
        file_size = path.stat().st_size
    except OSError:
        return None

    if file_size <= _SUMMARY_LIST_LITE_FULL_PARSE_BYTES:
        return _safe_read_summary_file(path)

    try:
        prefix = path.read_bytes()[:_SUMMARY_LIST_LITE_PREFIX_BYTES].decode("utf-8", errors="ignore")
    except OSError:
        return None

    payload: dict[str, Any] = {}
    for key in _SUMMARY_LIST_SCALAR_KEYS:
        value = _json_extract_scalar_from_text(prefix, key)
        if value is not None and value != "":
            payload[key] = value

    run_name = _json_extract_nested_string_from_text(prefix, "run_name")
    if run_name:
        payload["回测配置"] = {"run_name": run_name}

    if _metric_preview_from_summary(payload):
        return payload

    return _safe_read_summary_file(path)


def _metric_preview_from_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """列表页卡片与合并组统计所需的少量指标（不含持仓大表等）。"""
    preview: dict[str, Any] = {}
    metric_key_groups = (
        ["年化收益率 (%)", "累计收益率（扣手续费）"],
        ["夏普比率"],
        ["最大回撤 (%)"],
        ["log((Rp-Rb)/下半方差（P）)"],
    )
    for keys in metric_key_groups:
        for k in keys:
            v = payload.get(k)
            if v is not None and v != "":
                preview[k] = v
                break
    return preview


def _lite_config_for_list(config: dict[str, Any]) -> dict[str, Any]:
    """列表分组（Optuna run_name 等）所需的最小 config。"""
    rn = config.get("run_name")
    if isinstance(rn, str) and rn.strip():
        return {"run_name": rn.strip()}
    return {}


_HISTORY_LIST_PATHS_CACHE: list[Path] | None = None
_HISTORY_LIST_PATHS_CACHE_EXPIRES_AT: float = 0.0
_HISTORY_LIST_PATHS_CACHE_TTL_SEC = 3.0


def invalidate_backtest_history_paths_cache() -> None:
    """summary 路径列表缓存失效（删除回测等后调用）。"""
    global _HISTORY_LIST_PATHS_CACHE, _HISTORY_LIST_PATHS_CACHE_EXPIRES_AT
    _HISTORY_LIST_PATHS_CACHE = None
    _HISTORY_LIST_PATHS_CACHE_EXPIRES_AT = 0.0


def _sorted_backtest_summary_paths() -> list[Path]:
    """按 mtime 倒序的 summary 路径列表（短期缓存，减轻分页连刷时的 glob 开销）。"""
    global _HISTORY_LIST_PATHS_CACHE, _HISTORY_LIST_PATHS_CACHE_EXPIRES_AT
    now = time.time()
    if _HISTORY_LIST_PATHS_CACHE is not None and now < _HISTORY_LIST_PATHS_CACHE_EXPIRES_AT:
        return _HISTORY_LIST_PATHS_CACHE
    if not BACKTEST_SUMMARY_BASE_PATH.exists():
        _HISTORY_LIST_PATHS_CACHE = []
        _HISTORY_LIST_PATHS_CACHE_EXPIRES_AT = now + _HISTORY_LIST_PATHS_CACHE_TTL_SEC
        return _HISTORY_LIST_PATHS_CACHE
    paths = sorted(
        BACKTEST_SUMMARY_BASE_PATH.glob(BACKTEST_SUMMARY_FILE_GLOB),
        key=lambda item: (item.stat().st_mtime, item.name),
        reverse=True,
    )
    _HISTORY_LIST_PATHS_CACHE = paths
    _HISTORY_LIST_PATHS_CACHE_EXPIRES_AT = now + _HISTORY_LIST_PATHS_CACHE_TTL_SEC
    return paths


def list_backtest_history(limit: int | None = None, offset: int = 0) -> dict[str, Any]:
    """读取历史回测的列表摘要（不含完整 summary JSON）。

    - ``limit`` / ``offset``：分页窗口（按文件路径排序后的切片）；仅读取该页对应摘要文件。
    - ``limit`` 为 ``None`` 或 ``<=0``：从 ``offset`` 起返回剩余全部（兼容旧客户端）。
    """
    if offset < 0:
        offset = 0

    candidates = _sorted_backtest_summary_paths()
    total = len(candidates)
    base_meta = {
        "total": total,
        "offset": offset,
        "limit": limit,
        "summary_base_path": str(BACKTEST_SUMMARY_BASE_PATH),
        "server_time": int(time.time()),
    }

    if total == 0:
        return {
            "items": [],
            "meta": {
                **base_meta,
                "returned": 0,
                "has_more": False,
                "next_offset": 0,
                "count": 0,
            },
        }

    if limit is None or limit <= 0:
        slice_paths = candidates[offset:]
    else:
        slice_paths = candidates[offset : offset + limit]

    items: list[dict[str, Any]] = []
    for path in slice_paths:
        payload = _read_summary_list_lite(path)
        if payload is None:
            continue
        stat = path.stat()
        run_tag = _parse_run_tag_from_summary_path(path)
        config = payload.get("回测配置") if isinstance(payload.get("回测配置"), dict) else {}
        strategy_name = str(payload.get("回测名称") or config.get("run_name") or run_tag).strip()
        if not strategy_name:
            strategy_name = run_tag
        saved_paths = {
            "summary": str(path),
            "position_log": str(BACKTEST_POSITION_BASE_PATH / f"position_log_{run_tag}.parquet"),
            "order_log": str(BACKTEST_POSITION_BASE_PATH / f"order_log_{run_tag}.parquet"),
        }
        items.append(
            {
                "id": run_tag,
                "task_time": _format_run_tag_time(run_tag, stat.st_mtime),
                "strategy_name": strategy_name,
                "preview": _metric_preview_from_summary(payload),
                "config": _lite_config_for_list(config),
                "saved_paths": saved_paths,
                "summary_path": str(path),
                "mtime": int(stat.st_mtime),
            }
        )

    slice_len = len(slice_paths)
    returned = len(items)
    next_offset = offset + slice_len
    return {
        "items": items,
        "meta": {
            **base_meta,
            "returned": returned,
            "has_more": next_offset < total,
            "next_offset": next_offset,
            "count": total,
        },
    }


def get_backtest_history_detail(run_tag: Any) -> dict[str, Any]:
    """按 run_tag 读取单条完整 summary，供成果页展开详情时请求。"""
    parsed_run_tag = str(run_tag or "").strip()
    if not parsed_run_tag:
        raise MarketDataValidationError("run_tag 不能为空")
    if not RUN_TAG_PATTERN.fullmatch(parsed_run_tag):
        raise MarketDataValidationError("run_tag 格式无效")

    path = BACKTEST_SUMMARY_BASE_PATH / f"summary_{parsed_run_tag}.json"
    if not path.is_file():
        raise MarketDataNotFoundError(f"未找到回测摘要: {parsed_run_tag}")

    payload = _safe_read_summary_file(path)
    if payload is None:
        raise MarketDataError(f"读取回测摘要失败: {path}")

    stat = path.stat()
    run_key = _parse_run_tag_from_summary_path(path)
    config = payload.get("回测配置") if isinstance(payload.get("回测配置"), dict) else {}
    strategy_name = str(payload.get("回测名称") or config.get("run_name") or run_key).strip()
    if not strategy_name:
        strategy_name = run_key
    saved_paths = {
        "summary": str(path),
        "position_log": str(BACKTEST_POSITION_BASE_PATH / f"position_log_{run_key}.parquet"),
        "order_log": str(BACKTEST_POSITION_BASE_PATH / f"order_log_{run_key}.parquet"),
    }
    item: dict[str, Any] = {
        "id": run_key,
        "task_time": _format_run_tag_time(run_key, stat.st_mtime),
        "strategy_name": strategy_name,
        "summary": payload,
        "config": config,
        "saved_paths": saved_paths,
        "summary_path": str(path),
        "mtime": int(stat.st_mtime),
    }
    return {"item": item}


def _validate_run_tag_format(run_tag: str) -> str:
    parsed = str(run_tag or "").strip()
    if not parsed:
        raise MarketDataValidationError("run_tag 不能为空")
    if not RUN_TAG_PATTERN.fullmatch(parsed):
        raise MarketDataValidationError("run_tag 格式无效")
    return parsed


def _portfolio_pict_index_path() -> Path:
    return PORTFOLIO_PICT_BASE_PATH / PORTFOLIO_PICT_INDEX_NAME


def _ensure_portfolio_pict_dir() -> None:
    PORTFOLIO_PICT_BASE_PATH.mkdir(parents=True, exist_ok=True)


def _load_portfolio_pict_index_unlocked() -> dict[str, Any]:
    path = _portfolio_pict_index_path()
    if not path.exists():
        return {"attachments": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"attachments": {}}
    if not isinstance(raw, dict):
        return {"attachments": {}}
    att = raw.get("attachments")
    if not isinstance(att, dict):
        raw["attachments"] = {}
    return raw


def _save_portfolio_pict_index_unlocked(data: dict[str, Any]) -> None:
    _ensure_portfolio_pict_dir()
    path = _portfolio_pict_index_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _delete_stored_pict_file_if_exists(stored_filename: str) -> None:
    fn = str(stored_filename or "").strip()
    if not fn or "/" in fn or "\\" in fn or ".." in fn:
        return
    fp = PORTFOLIO_PICT_BASE_PATH / fn
    if fp.is_file():
        try:
            fp.unlink()
        except OSError:
            pass


def delete_backtest_portfolio_attachment(run_tag: Any) -> dict[str, Any]:
    """仅删除成果页「组合附图」，不删 summary / 订单等。"""
    parsed = _validate_run_tag_format(str(run_tag or "").strip())
    entry: dict[str, Any] | None = None
    with _PORTFOLIO_PICT_INDEX_LOCK:
        data = _load_portfolio_pict_index_unlocked()
        attachments: dict[str, Any] = data.setdefault("attachments", {})
        if not isinstance(attachments, dict):
            data["attachments"] = {}
            attachments = data["attachments"]
        popped = attachments.pop(parsed, None)
        if isinstance(popped, dict):
            entry = popped
            fn = str(entry.get("filename", "")).strip()
            _delete_stored_pict_file_if_exists(fn)
            _save_portfolio_pict_index_unlocked(data)
    if entry is None:
        raise MarketDataNotFoundError(f"未找到附图: {parsed}")
    return {
        "run_tag": parsed,
        "deleted": True,
        "meta": {"server_time": int(time.time())},
    }


def get_backtest_portfolio_attachment_meta(run_tag: Any) -> dict[str, Any]:
    parsed = _validate_run_tag_format(str(run_tag or "").strip())
    with _PORTFOLIO_PICT_INDEX_LOCK:
        data = _load_portfolio_pict_index_unlocked()
        attachments = data.get("attachments") if isinstance(data.get("attachments"), dict) else {}
        entry = attachments.get(parsed)
    if not isinstance(entry, dict):
        return {"run_tag": parsed, "has_attachment": False}
    return {
        "run_tag": parsed,
        "has_attachment": True,
        "image_id": str(entry.get("image_id", "")),
        "mime": str(entry.get("mime", "application/octet-stream")),
        "updated_at": int(entry.get("updated_at") or 0),
    }


def read_backtest_portfolio_attachment_file(run_tag: Any) -> tuple[bytes, str]:
    parsed = _validate_run_tag_format(str(run_tag or "").strip())
    with _PORTFOLIO_PICT_INDEX_LOCK:
        data = _load_portfolio_pict_index_unlocked()
        attachments = data.get("attachments") if isinstance(data.get("attachments"), dict) else {}
        entry = attachments.get(parsed)
    if not isinstance(entry, dict):
        raise MarketDataNotFoundError(f"未找到附图: {parsed}")
    fn = str(entry.get("filename", "")).strip()
    if not fn or "/" in fn or "\\" in fn or ".." in fn:
        raise MarketDataError("附图索引损坏")
    fp = PORTFOLIO_PICT_BASE_PATH / fn
    if not fp.is_file():
        raise MarketDataNotFoundError(f"附图文件不存在: {fn}")
    mime = str(entry.get("mime") or "application/octet-stream")
    try:
        blob = fp.read_bytes()
    except OSError as exc:
        raise MarketDataError(f"读取附图失败: {exc}") from exc
    return blob, mime


def save_backtest_portfolio_attachment(
    run_tag: Any,
    file_bytes: bytes,
    client_filename: str,
) -> dict[str, Any]:
    parsed = _validate_run_tag_format(str(run_tag or "").strip())
    if not file_bytes:
        raise MarketDataValidationError("图片内容不能为空")
    if len(file_bytes) > PORTFOLIO_PICT_MAX_BYTES:
        raise MarketDataValidationError(f"图片不能超过 {PORTFOLIO_PICT_MAX_BYTES} 字节")

    suffix = Path(str(client_filename or "").strip()).suffix.lower()
    if suffix not in _ALLOWED_PICT_SUFFIXES:
        raise MarketDataValidationError("仅支持 png / jpg / jpeg / webp")

    mime = _MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
    image_id = str(uuid.uuid4())
    stored_filename = f"{image_id}{suffix}"

    _ensure_portfolio_pict_dir()
    target_path = PORTFOLIO_PICT_BASE_PATH / stored_filename

    with _PORTFOLIO_PICT_INDEX_LOCK:
        data = _load_portfolio_pict_index_unlocked()
        attachments: dict[str, Any] = data.setdefault("attachments", {})
        if not isinstance(attachments, dict):
            data["attachments"] = {}
            attachments = data["attachments"]
        old = attachments.get(parsed)
        if isinstance(old, dict):
            old_fn = str(old.get("filename", "")).strip()
            _delete_stored_pict_file_if_exists(old_fn)
        try:
            target_path.write_bytes(file_bytes)
        except OSError as exc:
            raise MarketDataError(f"写入附图失败: {exc}") from exc
        attachments[parsed] = {
            "image_id": image_id,
            "filename": stored_filename,
            "mime": mime,
            "updated_at": int(time.time()),
        }
        _save_portfolio_pict_index_unlocked(data)

    return {
        "run_tag": parsed,
        "image_id": image_id,
        "filename": stored_filename,
        "mime": mime,
        "meta": {"server_time": int(time.time())},
    }


def _remove_portfolio_attachment_for_run_tag(parsed_run_tag: str) -> bool:
    """删除该 run_tag 的附图（若存在）。返回是否删除了附图记录。"""
    removed = False
    with _PORTFOLIO_PICT_INDEX_LOCK:
        data = _load_portfolio_pict_index_unlocked()
        attachments: dict[str, Any] = data.setdefault("attachments", {})
        if not isinstance(attachments, dict):
            return False
        popped = attachments.pop(parsed_run_tag, None)
        if isinstance(popped, dict):
            removed = True
            fn = str(popped.get("filename", "")).strip()
            _delete_stored_pict_file_if_exists(fn)
        if removed:
            _save_portfolio_pict_index_unlocked(data)
    return removed


def delete_backtest_history(run_tag: Any) -> dict[str, Any]:
    """删除指定 run_tag 的 summary / position_log / order_log；并删除同 run_tag 的成果页附图（若存在）。"""
    parsed_run_tag = _validate_run_tag_format(str(run_tag or "").strip())

    pict_removed = _remove_portfolio_attachment_for_run_tag(parsed_run_tag)

    candidates = [
        BACKTEST_SUMMARY_BASE_PATH / f"summary_{parsed_run_tag}.json",
        BACKTEST_POSITION_BASE_PATH / f"position_log_{parsed_run_tag}.parquet",
        BACKTEST_POSITION_BASE_PATH / f"order_log_{parsed_run_tag}.parquet",
        BACKTEST_POSITION_BASE_PATH / f"order_log_{parsed_run_tag}.csv",
    ]
    deleted: list[str] = []
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise MarketDataError(f"删除回测历史失败: {path}，原因: {exc}") from exc
        deleted.append(str(path))

    curve_run_dir = Path(PORTFOLIO_DAILY_BASE_PATH) / f"run_tag={parsed_run_tag}"
    if curve_run_dir.exists() and curve_run_dir.is_dir():
        try:
            shutil.rmtree(curve_run_dir)
            deleted.append(str(curve_run_dir))
        except OSError as exc:
            raise MarketDataError(f"删除组合曲线目录失败: {curve_run_dir}，原因: {exc}") from exc

    if not deleted and not pict_removed:
        raise MarketDataNotFoundError(f"未找到回测历史或附图: {parsed_run_tag}")

    invalidate_backtest_history_paths_cache()

    return {
        "run_tag": parsed_run_tag,
        "deleted": deleted,
        "pict_removed": pict_removed,
        "meta": {
            "count": len(deleted),
            "server_time": int(time.time()),
        },
    }


def _resolve_backtest_artifact_path(
    glob_pattern: str,
    run_tag: str | None,
    artifact_prefix: str,
) -> Path:
    """按 run_tag 定位 order_log / position_log；未指定时取最新 mtime。"""
    if run_tag:
        parsed = _validate_run_tag_format(str(run_tag).strip())
        path = BACKTEST_POSITION_BASE_PATH / f"{artifact_prefix}_{parsed}.parquet"
        if not path.exists():
            raise MarketDataNotFoundError(f"未找到 {artifact_prefix}_{parsed}.parquet")
        return path
    if not BACKTEST_POSITION_BASE_PATH.exists():
        raise MarketDataNotFoundError(f"组合持仓目录不存在: {BACKTEST_POSITION_BASE_PATH}")
    candidates = sorted(
        BACKTEST_POSITION_BASE_PATH.glob(glob_pattern),
        key=lambda item: (item.stat().st_mtime, item.name),
        reverse=True,
    )
    if not candidates:
        raise MarketDataNotFoundError(f"未找到 {artifact_prefix} 记录，请先运行回测")
    return candidates[0]


def query_latest_backtest_position_snapshot(
    code: Any,
    time_ts: Any,
    run_tag: Any = None,
) -> dict[str, Any]:
    parsed_code = str(code).strip() if code is not None else ""
    if not parsed_code:
        raise MarketDataValidationError("code 不能为空")
    if parsed_code not in PORTFOLIO_CURVE_CODES:
        raise MarketDataValidationError("当前 code 不支持组合持仓快照")

    parsed_time = _parse_optional_int(time_ts, "time")
    if parsed_time is None:
        raise MarketDataValidationError("time 不能为空")

    latest_path = _resolve_backtest_artifact_path(
        BACKTEST_POSITION_FILE_GLOB,
        str(run_tag).strip() if run_tag else None,
        "position_log",
    )
    target_date = datetime.utcfromtimestamp(parsed_time).strftime("%Y-%m-%d")
    sql = """
    SELECT
        CAST(code AS VARCHAR) AS code,
        TRY_CAST(position_size AS DOUBLE) AS position_size,
        TRY_CAST(position_price AS DOUBLE) AS position_price,
        TRY_CAST(close AS DOUBLE) AS close,
        TRY_CAST(market_value AS DOUBLE) AS market_value,
        TRY_CAST(weight_pct AS DOUBLE) AS weight_pct,
        TRY_CAST(unrealized_pnl AS DOUBLE) AS unrealized_pnl,
        TRY_CAST(contribution_pct AS DOUBLE) AS contribution_pct,
        TRY_CAST(daily_pnl_pct AS DOUBLE) AS daily_pnl_pct,
        CAST(run_tag AS VARCHAR) AS run_tag
    FROM read_parquet(?)
    WHERE CAST(date AS VARCHAR) = ?
    ORDER BY
        TRY_CAST(weight_pct AS DOUBLE) DESC NULLS LAST,
        TRY_CAST(market_value AS DOUBLE) DESC NULLS LAST,
        CAST(code AS VARCHAR) ASC
    """

    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, [latest_path.as_posix(), target_date]).fetchall()
    except duckdb.Error as exc:
        raise MarketDataError(f"DuckDB 组合持仓快照查询失败: {exc}") from exc
    finally:
        conn.close()

    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric != numeric:
            return None
        return numeric

    items: list[dict[str, Any]] = []
    run_tag = ""
    for row in rows:
        row_run_tag = str(row[9] or "").strip()
        if row_run_tag and not run_tag:
            run_tag = row_run_tag
        items.append(
            {
                "code": str(row[0] or "").strip(),
                "position_size": _safe_float(row[1]),
                "position_price": _safe_float(row[2]),
                "close": _safe_float(row[3]),
                "market_value": _safe_float(row[4]),
                "weight_pct": _safe_float(row[5]),
                "unrealized_pnl": _safe_float(row[6]),
                "contribution_pct": _safe_float(row[7]),
                "daily_pnl_pct": _safe_float(row[8]),
            }
        )

    if not run_tag:
        stem = latest_path.stem
        if stem.startswith("position_log_"):
            run_tag = stem.replace("position_log_", "", 1)

    return {
        "time": parsed_time,
        "date": target_date,
        "run_tag": run_tag,
        "no_data": len(items) == 0,
        "items": items,
        "meta": {
            "code": parsed_code,
            "count": len(items),
            "position_log_path": str(latest_path),
            "server_time": int(time.time()),
        },
    }


def query_latest_backtest_orders(
    code: Any,
    from_ts: Any = None,
    to_ts: Any = None,
    run_tag: Any = None,
) -> dict[str, Any]:
    """读取回测 order_log，并返回指定个股实际成交记录。"""
    parsed_code = str(code).strip().upper() if code is not None else ""
    if not parsed_code:
        raise MarketDataValidationError("code 不能为空")
    if parsed_code.endswith(".YKRS"):
        return {
            "items": [],
            "no_data": True,
            "meta": {
                "code": parsed_code,
                "count": 0,
                "server_time": int(time.time()),
            },
        }

    parsed_from = _parse_optional_int(from_ts, "from")
    parsed_to = _parse_optional_int(to_ts, "to")
    if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
        raise MarketDataValidationError("from 不能大于 to")

    latest_path = _resolve_backtest_artifact_path(
        BACKTEST_ORDER_FILE_GLOB,
        str(run_tag).strip() if run_tag else None,
        "order_log",
    )
    from_date = datetime.utcfromtimestamp(parsed_from).strftime("%Y-%m-%d") if parsed_from is not None else "0001-01-01"
    to_date = datetime.utcfromtimestamp(parsed_to).strftime("%Y-%m-%d") if parsed_to is not None else "9999-12-31"
    reader_sql = "read_parquet(?)" if latest_path.suffix.lower() == ".parquet" else "read_csv_auto(?)"

    sql = f"""
    SELECT
        CAST(date AS VARCHAR) AS date,
        CAST(code AS VARCHAR) AS code,
        CAST(signal AS VARCHAR) AS signal,
        CAST(status AS VARCHAR) AS status,
        CAST(side AS VARCHAR) AS side,
        TRY_CAST(executed_size AS DOUBLE) AS executed_size,
        TRY_CAST(executed_price AS DOUBLE) AS executed_price,
        TRY_CAST(executed_value AS DOUBLE) AS executed_value,
        TRY_CAST(commission AS DOUBLE) AS commission,
        TRY_CAST(target_value AS DOUBLE) AS target_value,
        TRY_CAST(position_after AS DOUBLE) AS position_after,
        TRY_CAST(cash_after AS DOUBLE) AS cash_after,
        TRY_CAST(portfolio_value_after AS DOUBLE) AS portfolio_value_after
    FROM {reader_sql}
    WHERE UPPER(CAST(code AS VARCHAR)) = ?
      AND UPPER(CAST(status AS VARCHAR)) = 'COMPLETED'
      AND UPPER(CAST(side AS VARCHAR)) IN ('BUY', 'SELL')
      AND CAST(date AS VARCHAR) >= ?
      AND CAST(date AS VARCHAR) <= ?
    ORDER BY CAST(date AS VARCHAR), UPPER(CAST(side AS VARCHAR))
    """

    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, [latest_path.as_posix(), parsed_code, from_date, to_date]).fetchall()
    except duckdb.Error as exc:
        raise MarketDataError(f"DuckDB 回测订单查询失败: {exc}") from exc
    finally:
        conn.close()

    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric != numeric:
            return None
        return numeric

    items: list[dict[str, Any]] = []
    for row in rows:
        date_text = str(row[0] or "").strip()
        try:
            time_value = int(datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            time_value = None
        items.append(
            {
                "time": time_value,
                "date": date_text,
                "code": str(row[1] or "").strip(),
                "signal": str(row[2] or "").strip(),
                "status": str(row[3] or "").strip(),
                "side": str(row[4] or "").strip().upper(),
                "executed_size": _safe_float(row[5]),
                "executed_price": _safe_float(row[6]),
                "executed_value": _safe_float(row[7]),
                "commission": _safe_float(row[8]),
                "target_value": _safe_float(row[9]),
                "position_after": _safe_float(row[10]),
                "cash_after": _safe_float(row[11]),
                "portfolio_value_after": _safe_float(row[12]),
            }
        )

    run_tag = ""
    stem = latest_path.stem
    if stem.startswith("order_log_"):
        run_tag = stem.replace("order_log_", "", 1)

    return {
        "items": items,
        "no_data": len(items) == 0,
        "meta": {
            "code": parsed_code,
            "count": len(items),
            "from": parsed_from,
            "to": parsed_to,
            "run_tag": run_tag,
            "order_log_path": str(latest_path),
            "server_time": int(time.time()),
        },
    }


def _build_sql(path_count: int) -> str:
    if path_count <= 0:
        raise MarketDataValidationError("path_count 必须大于 0")
    path_placeholders = ", ".join(["?"] * path_count)
    return f"""
    WITH raw AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS normalized_code,
            COALESCE(
                TRY_CAST(time AS BIGINT),
                CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
            ) AS time_sec,
            TRY_CAST(open AS DOUBLE) AS open,
            TRY_CAST(high AS DOUBLE) AS high,
            TRY_CAST(low AS DOUBLE) AS low,
            TRY_CAST(close AS DOUBLE) AS close,
            TRY_CAST(volume AS DOUBLE) AS volume
        FROM read_parquet([{path_placeholders}], union_by_name = true)
    )
    , filtered AS (
        SELECT
            time_sec AS time,
            open,
            high,
            low,
            close,
            COALESCE(volume, 0) AS volume
        FROM raw
        WHERE normalized_code = UPPER(?)
          AND time_sec IS NOT NULL
          AND open IS NOT NULL
          AND high IS NOT NULL
          AND low IS NOT NULL
          AND close IS NOT NULL
          AND time_sec BETWEEN ? AND ?
    )
    , limited_latest AS (
        SELECT *
        FROM filtered
        ORDER BY time DESC
        LIMIT ?
    )
    SELECT *
    FROM limited_latest
    ORDER BY time ASC
    """


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _build_signal_sql(path_count: int) -> str:
    if path_count <= 0:
        raise MarketDataValidationError("path_count 必须大于 0")
    path_placeholders = ", ".join(["?"] * path_count)
    return f"""
    WITH raw AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS normalized_code,
            COALESCE(
                TRY_CAST(time AS BIGINT),
                CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
            ) AS time_sec,
            TRY_CAST(value AS DOUBLE) AS factor_value
        FROM read_parquet([{path_placeholders}], union_by_name = true)
    )
    , filtered AS (
        SELECT
            time_sec AS time,
            COALESCE(factor_value, 0.0) AS value
        FROM raw
        WHERE normalized_code = UPPER(?)
          AND time_sec IS NOT NULL
          AND time_sec BETWEEN ? AND ?
    )
    , daily_ranked AS (
        SELECT
            CAST(FLOOR(time / 86400.0) AS BIGINT) * 86400 AS day_time,
            value,
            ROW_NUMBER() OVER (
                PARTITION BY CAST(FLOOR(time / 86400.0) AS BIGINT)
                ORDER BY time DESC
            ) AS rn
        FROM filtered
    )
    , daily_dedup AS (
        SELECT
            day_time AS time,
            value
        FROM daily_ranked
        WHERE rn = 1
    )
    , limited_latest AS (
        SELECT *
        FROM daily_dedup
        ORDER BY time DESC
        LIMIT ?
    )
    SELECT *
    FROM limited_latest
    ORDER BY time ASC
    """


def _utc_day_start_ts(ts: int) -> int:
    """将 Unix 秒归一到 UTC 日历日初（与因子日锚 floor(time/86400)*86400 一致）。"""
    return int(ts) // 86400 * 86400


def _build_signal_sql_chronological_limited(path_count: int, max_rows: int) -> str:
    """日频去重后按时间升序返回，最多 max_rows 条（用于耦合全历史单因子扫描）。"""
    if path_count <= 0:
        raise MarketDataValidationError("path_count 必须大于 0")
    if max_rows <= 0:
        raise MarketDataValidationError("max_rows 必须大于 0")
    path_placeholders = ", ".join(["?"] * path_count)
    return f"""
    WITH raw AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS normalized_code,
            COALESCE(
                TRY_CAST(time AS BIGINT),
                CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
            ) AS time_sec,
            TRY_CAST(value AS DOUBLE) AS factor_value
        FROM read_parquet([{path_placeholders}], union_by_name = true)
    )
    , filtered AS (
        SELECT
            time_sec AS time,
            COALESCE(factor_value, 0.0) AS value
        FROM raw
        WHERE normalized_code = UPPER(?)
          AND time_sec IS NOT NULL
          AND time_sec BETWEEN ? AND ?
    )
    , daily_ranked AS (
        SELECT
            CAST(FLOOR(time / 86400.0) AS BIGINT) * 86400 AS day_time,
            value,
            ROW_NUMBER() OVER (
                PARTITION BY CAST(FLOOR(time / 86400.0) AS BIGINT)
                ORDER BY time DESC
            ) AS rn
        FROM filtered
    )
    , daily_dedup AS (
        SELECT
            day_time AS time,
            value
        FROM daily_ranked
        WHERE rn = 1
    )
    SELECT time, value
    FROM daily_dedup
    ORDER BY time ASC
    LIMIT {int(max_rows)}
    """


def _effective_couple_component(raw: Any) -> float:
    """NULL/缺失在 SQL 侧已 COALESCE 为 0；非有限数按 0 处理。"""
    if raw is None:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return v


def _fetch_factor_couple_daily_map(
    code: str,
    from_ts: int,
    to_ts: int,
    resolved_factor_name: str,
    base_path: str,
) -> dict[int, float]:
    partition_paths = _build_factor_partition_paths(
        base_path,
        resolved_factor_name,
        from_ts,
        to_ts,
    )
    if not partition_paths:
        return {}
    sql = _build_signal_sql_chronological_limited(len(partition_paths), FACTOR_COUPLE_MAX_DAILY_ROWS)
    query_args: list[Any] = [
        *partition_paths,
        code,
        from_ts,
        to_ts,
    ]
    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, query_args).fetchall()
    except duckdb.Error as exc:
        raise MarketDataError(f"DuckDB 因子耦合查询失败: {exc}") from exc
    finally:
        conn.close()
    by_time: dict[int, float] = {}
    for row in rows:
        signal_time = int(row[0])
        by_time[signal_time] = _effective_couple_component(row[1])
    return by_time


def query_market_factor_couple_series(
    code: Any,
    interval: Any,
    factors: Any,
    base_path: Optional[str] = None,
) -> dict[str, Any]:
    """多因子耦合（仅单个 code）：每个 UTC 日上，全部因子有效值均 > 1 则为 1，否则 0。

    有效值：NULL/缺失按 0；非有限按 0。时间范围为 UTC 日锚上的「全历史」（起点 FACTOR_COUPLE_FULL_HISTORY_FROM_TS 至当前服务器时间所在日末秒）。
    """
    parsed_code = str(code).strip() if code is not None else ""
    if not parsed_code:
        raise MarketDataValidationError("code 不能为空")
    if not CODE_PATTERN.match(parsed_code):
        raise MarketDataValidationError("code 仅允许字母、数字、点、下划线和中划线")

    parsed_interval = str(interval).strip() if interval is not None else ""
    if parsed_interval != "1day":
        raise MarketDataValidationError("因子耦合暂仅支持 interval=1day")

    if not isinstance(factors, list):
        raise MarketDataValidationError("factors 必须为数组")
    parsed_factors = [str(item).strip() for item in factors if str(item).strip()]
    if len(parsed_factors) < 1:
        raise MarketDataValidationError("factors 至少需要 1 个因子")
    if len(parsed_factors) > FACTOR_COUPLE_MAX_FACTORS:
        raise MarketDataValidationError(f"factors 最多支持 {FACTOR_COUPLE_MAX_FACTORS} 个")

    resolved_base_path = base_path or SIGNAL_DAILY_BASE_PATH
    if not os.path.exists(resolved_base_path):
        raise MarketDataNotFoundError(f"因子数据根目录不存在: {resolved_base_path}")

    available_factors = _get_cached_factor_names(resolved_base_path)
    resolved_names: list[str] = []
    requested_labels: list[str] = []
    for factor_name in parsed_factors:
        requested_labels.append(factor_name)
        resolved = _resolve_factor_column_name(factor_name, set(available_factors))
        if resolved is None:
            available_factors = _get_cached_factor_names(resolved_base_path, force_refresh=True)
            resolved = _resolve_factor_column_name(factor_name, set(available_factors))
        if resolved is None:
            raise MarketDataValidationError(f"factor 不存在: {factor_name}")
        resolved_names.append(resolved)

    now_ts = int(time.time())
    from_ts = _utc_day_start_ts(FACTOR_COUPLE_FULL_HISTORY_FROM_TS)
    to_ts = _utc_day_start_ts(now_ts) + 86400 - 1

    per_factor_maps: list[dict[int, float]] = []
    truncated_per_factor: list[str] = []
    for resolved in resolved_names:
        m = _fetch_factor_couple_daily_map(
            parsed_code,
            from_ts,
            to_ts,
            resolved,
            resolved_base_path,
        )
        if len(m) >= FACTOR_COUPLE_MAX_DAILY_ROWS:
            truncated_per_factor.append(resolved)
        per_factor_maps.append(m)

    all_times: set[int] = set()
    for m in per_factor_maps:
        all_times.update(m.keys())
    if not all_times:
        raise MarketDataNotFoundError("目标范围内未找到可用于耦合的因子日频数据")

    series: list[dict[str, Any]] = []
    row_budget = FACTOR_COUPLE_MAX_DAILY_ROWS
    truncated_union = False
    for t in sorted(all_times):
        if row_budget <= 0:
            truncated_union = True
            break
        components = [m.get(t, 0.0) for m in per_factor_maps]
        coupled = 1.0 if all(c > 1.0 for c in components) else 0.0
        series.append({"time": t, "value": coupled})
        row_budget -= 1

    return {
        "series": series,
        "meta": {
            "code": parsed_code,
            "interval": parsed_interval,
            "factors": requested_labels,
            "resolved_factors": resolved_names,
            "semantics": "仅当前 code；UTC 日锚；各因子 NULL/缺失→0，非有限→0；当日全部因子值均>1 则耦合为1否则0",
            "time_granularity": "utc_calendar_day",
            "value_type": "float64",
            "from": from_ts,
            "to": to_ts,
            "row_count": len(series),
            "truncated_union_times": truncated_union,
            "truncated_per_factor": truncated_per_factor,
            "server_time": int(time.time()),
            "base_path": resolved_base_path,
        },
    }


def _build_factor_snapshot_sql(path_count: int) -> str:
    if path_count <= 0:
        raise MarketDataValidationError("path_count 必须大于 0")
    path_placeholders = ", ".join(["?"] * path_count)
    return f"""
    WITH raw AS (
        SELECT
            *,
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS normalized_code,
            COALESCE(
                TRY_CAST(time AS BIGINT),
                CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
            ) AS time_sec
        FROM read_parquet([{path_placeholders}], union_by_name = true)
    ),
    filtered AS (
        SELECT *
        FROM raw
        WHERE normalized_code = UPPER(?)
          AND time_sec IS NOT NULL
          AND CAST(FLOOR(time_sec / 86400.0) AS BIGINT) = CAST(FLOOR(? / 86400.0) AS BIGINT)
    )
    SELECT *
    FROM filtered
    ORDER BY time_sec DESC
    LIMIT 1
    """


def _list_all_merged_files(base_path: str) -> list[str]:
    merged_files: list[str] = []
    for root, _, files in os.walk(base_path):
        for file_name in files:
            if file_name == MERGED_FILE_NAME or (file_name.startswith("part_") and file_name.endswith(".parquet")):
                merged_files.append(os.path.join(root, file_name).replace("\\", "/"))
    return sorted(merged_files)


def _list_recent_merged_candidates(base_path: str, max_count: int = 3) -> list[str]:
    """优先返回最近月份的数据文件（merged + part），减少 schema 扫描范围。"""
    year_month_paths: list[tuple[int, int, list[str]]] = []
    if not os.path.exists(base_path):
        return []

    for year_name in os.listdir(base_path):
        if not year_name.startswith("year="):
            continue
        year_str = year_name.split("=", 1)[1].strip()
        if not year_str.isdigit():
            continue
        year = int(year_str)
        year_dir = os.path.join(base_path, year_name)
        if not os.path.isdir(year_dir):
            continue
        for month_name in os.listdir(year_dir):
            if not month_name.startswith("month="):
                continue
            month_str = month_name.split("=", 1)[1].strip()
            if not month_str.isdigit():
                continue
            month = int(month_str)
            month_dir = os.path.join(year_dir, month_name)
            data_files = _list_partition_data_files(month_dir)
            if data_files:
                year_month_paths.append((year, month, data_files))

    year_month_paths.sort(key=lambda x: (x[0], x[1]), reverse=True)
    result: list[str] = []
    for _, _, data_files in year_month_paths[:max_count]:
        result.extend(data_files)
    if result:
        return result
    return []




def _load_stock_universe_records(force_refresh: bool = False) -> list[dict[str, str]]:
    """加载全市场股票代码缓存（htsc_code / name / pinyin_initials）。"""
    global _stock_universe_cache, _stock_universe_mtime
    path = Path(STOCK_UNIVERSE_PATH)
    if not path.is_file():
        return []

    mtime = path.stat().st_mtime
    with _stock_universe_lock:
        if not force_refresh and _stock_universe_cache and mtime == _stock_universe_mtime:
            return list(_stock_universe_cache)

        conn = duckdb.connect(database=":memory:")
        try:
            rows = conn.execute(
                """
                SELECT
                    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS code,
                    COALESCE(CAST(name AS VARCHAR), '') AS name,
                    COALESCE(CAST(pinyin_initials AS VARCHAR), '') AS pinyin_initials
                FROM read_parquet(?)
                WHERE htsc_code IS NOT NULL
                  AND TRIM(CAST(htsc_code AS VARCHAR)) <> ''
                ORDER BY code
                """,
                [str(path)],
            ).fetchall()
        finally:
            conn.close()

        records: list[dict[str, str]] = []
        for row in rows:
            if not row or not row[0]:
                continue
            records.append(
                {
                    "code": str(row[0]).strip().upper(),
                    "name": str(row[1] or "").strip(),
                    "pinyin_initials": str(row[2] or "").strip().upper(),
                    "name_pinyin_aliases": _build_name_pinyin_aliases(row[1] or ""),
                }
            )
        _stock_universe_cache = records
        _stock_universe_mtime = mtime
        return list(records)


def _stock_universe_codes() -> list[str]:
    return [str(item["code"]) for item in _load_stock_universe_records() if item.get("code")]

def _scan_all_codes_from_path(base_path: str) -> list[str]:
    merged_files = _list_all_merged_files(base_path)
    if not merged_files:
        return []

    path_placeholders = ", ".join(["?"] * len(merged_files))
    sql = f"""
    SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
    FROM read_parquet([{path_placeholders}], union_by_name = true)
    WHERE htsc_code IS NOT NULL
      AND TRIM(CAST(htsc_code AS VARCHAR)) <> ''
    ORDER BY htsc_code
    """

    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, merged_files).fetchall()
    except duckdb.Error as exc:
        raise MarketDataError(f"股票代码索引构建失败: {exc}") from exc
    finally:
        conn.close()

    return [str(row[0]).strip() for row in rows if row and str(row[0]).strip()]


def _build_bar_boundary_sql(path_count: int) -> str:
    if path_count <= 0:
        raise MarketDataValidationError("path_count 必须大于 0")
    path_placeholders = ", ".join(["?"] * path_count)
    return f"""
    WITH raw AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS normalized_code,
            COALESCE(
                TRY_CAST(time AS BIGINT),
                CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
            ) AS time_sec
        FROM read_parquet([{path_placeholders}], union_by_name = true)
    )
    SELECT MIN(time_sec), MAX(time_sec)
    FROM raw
    WHERE normalized_code = UPPER(?)
      AND time_sec IS NOT NULL
    """


def _scan_bar_time_boundaries(base_path: str, code: str) -> dict[str, int | None]:
    data_files = _list_all_merged_files(base_path)
    if not data_files:
        return {"first_available_bar_time": None, "last_available_bar_time": None}

    sql = _build_bar_boundary_sql(len(data_files))
    conn = duckdb.connect(database=":memory:")
    try:
        row = conn.execute(sql, [*data_files, str(code or "").strip().upper()]).fetchone()
    except duckdb.Error as exc:
        raise MarketDataError(f"K线时间边界查询失败: {exc}") from exc
    finally:
        conn.close()

    first_time = row[0] if row else None
    last_time = row[1] if row else None
    return {
        "first_available_bar_time": int(first_time) if first_time is not None else None,
        "last_available_bar_time": int(last_time) if last_time is not None else None,
    }


def _get_cached_bar_time_boundaries(base_path: str, code: str) -> dict[str, int | None]:
    normalized_path = _normalize_data_path(base_path)
    normalized_code = str(code or "").strip().upper()
    cache_key = (normalized_path, normalized_code)
    now_ts = time.time()
    with _bar_boundary_lock:
        need_refresh = (
            cache_key not in _bar_boundary_cache_by_key
            or (now_ts - _bar_boundary_cache_ts_by_key.get(cache_key, 0.0)) >= CODE_SEARCH_REFRESH_INTERVAL_SECONDS
        )
        if need_refresh:
            _bar_boundary_cache_by_key[cache_key] = _scan_bar_time_boundaries(base_path, normalized_code)
            _bar_boundary_cache_ts_by_key[cache_key] = now_ts
        return dict(_bar_boundary_cache_by_key.get(cache_key, {}))


def _build_market_bars_meta(
    params: QueryParams,
    resolved_base_path: str,
    parsed_run_tag: str | None,
    adjust_mode: str,
    bars: list[dict[str, Any]],
    extra_meta: dict[str, Any],
    bar_boundaries: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    latest_time = bars[-1]["time"] if bars else None
    has_new_data = False
    if latest_time is not None:
        if params.last_seen_bar_time is None:
            has_new_data = True
        else:
            has_new_data = latest_time > params.last_seen_bar_time

    meta: dict[str, Any] = {
        "code": params.code,
        "interval": params.interval,
        "server_time": int(time.time()),
        "last_bar_time": latest_time,
        "has_new_data": has_new_data,
        "row_count": len(bars),
        "from": params.from_ts,
        "to": params.to_ts,
        "base_path": resolved_base_path,
        "run_tag": parsed_run_tag or "",
        "adjust": adjust_mode,
    }
    if bar_boundaries:
        meta.update(bar_boundaries)
    meta.update(extra_meta)
    return meta


def _resolve_temp_today_cache_path() -> Path:
    configured = str(TEMP_TODAY_MARKET_CACHE_PATH or "").strip()
    if configured:
        return Path(configured)
    return today_cache_path()


def _can_use_temp_today_cache(
    params: QueryParams,
    base_path: Optional[str],
    resolved_base_path: str,
    parsed_run_tag: str | None,
) -> bool:
    if base_path is not None or parsed_run_tag:
        return False
    if is_portfolio_curve_code(params.code) or is_index_market_code(params.code):
        return False
    return _normalize_data_path(resolved_base_path) == _normalize_data_path(
        get_base_path_by_interval(params.interval)
    )


def _supplement_bars_from_temp_today_cache(
    params: QueryParams,
    bars: list[dict[str, Any]],
    extra_meta: dict[str, Any],
    base_path: Optional[str],
    resolved_base_path: str,
    parsed_run_tag: str | None,
) -> list[dict[str, Any]]:
    if not _can_use_temp_today_cache(params, base_path, resolved_base_path, parsed_run_tag):
        return bars

    cache_path = _resolve_temp_today_cache_path()
    if not cache_path.is_file():
        return bars

    try:
        if params.interval == "1min":
            sqlite_bars = query_today_minute_bars(
                cache_path,
                params.code,
                params.from_ts,
                params.to_ts,
                params.limit,
            )
            if not sqlite_bars:
                return bars
            sqlite_latest = max(int(bar["time"]) for bar in sqlite_bars)
            if not should_supplement_minute(bars, sqlite_latest):
                return bars
        elif params.interval == "1day":
            sqlite_bars = query_today_daily_bar(
                cache_path,
                params.code,
                params.from_ts,
                params.to_ts,
            )
            if not sqlite_bars:
                return bars
            sqlite_latest = max(int(bar["time"]) for bar in sqlite_bars)
            if not should_supplement_daily(bars, sqlite_latest):
                return bars
        else:
            return bars
    except Exception as exc:
        extra_meta["temp_today_cache_error"] = str(exc)
        return bars

    merged = merge_bars_with_parquet_priority(bars, sqlite_bars, params.limit)
    extra_meta["temp_today_supplemented"] = len(merged) > len(bars)
    extra_meta["temp_today_cache_path"] = str(cache_path)
    extra_meta["temp_today_bar_count"] = len(sqlite_bars)
    return merged


def _normalize_data_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path or "")))


def _should_use_stock_universe(base_path: str) -> bool:
    return _normalize_data_path(base_path) == _normalize_data_path(DAILY_BASE_PATH)


def _get_cached_codes(base_path: str) -> list[str]:
    if _should_use_stock_universe(base_path):
        universe_codes = _stock_universe_codes()
        if universe_codes:
            return universe_codes

    now_ts = time.time()
    with _code_index_lock:
        need_refresh = (
            base_path not in _code_index_cache_by_path
            or (now_ts - _code_index_cache_ts_by_path.get(base_path, 0.0)) >= CODE_SEARCH_REFRESH_INTERVAL_SECONDS
        )
        if need_refresh:
            _code_index_cache_by_path[base_path] = _scan_all_codes_from_path(base_path)
            _code_index_cache_ts_by_path[base_path] = now_ts
        return list(_code_index_cache_by_path.get(base_path, []))


def _scan_factor_names_from_path(base_path: str) -> list[str]:
    return _list_factor_names_from_dirs(base_path)


def _get_cached_factor_names(base_path: str, force_refresh: bool = False) -> list[str]:
    now_ts = time.time()
    with _factor_index_lock:
        need_refresh = (
            force_refresh
            or
            base_path not in _factor_index_cache_by_path
            or (now_ts - _factor_index_cache_ts_by_path.get(base_path, 0.0)) >= CODE_SEARCH_REFRESH_INTERVAL_SECONDS
        )
        if need_refresh:
            _factor_index_cache_by_path[base_path] = _scan_factor_names_from_path(base_path)
            _factor_index_cache_ts_by_path[base_path] = now_ts
        return list(_factor_index_cache_by_path.get(base_path, []))


def _build_default_factor_catalog(available_factors: list[str]) -> dict[str, Any]:
    core_candidates = ["MAC总", "mac_total", "DIF", "DEA", "MAC"]
    core_factors = [f for f in core_candidates if f in available_factors]
    if not core_factors and available_factors:
        core_factors = [available_factors[0]]
    return {
        "groups": [
            {
                "group_id": "all_factors",
                "group_name": "全部因子",
                "core_factors": list(core_factors),
                "core_factor_labels": list(core_factors),
                "children": list(available_factors),
            }
        ],
        "core_factors": list(core_factors),
        "core_factor_labels": list(core_factors),
    }


def _normalize_factor_catalog(raw_catalog: Any, available_factors: list[str]) -> dict[str, Any]:
    available_set = set(available_factors)
    if not isinstance(raw_catalog, dict):
        return _build_default_factor_catalog(available_factors)

    raw_groups = raw_catalog.get("groups")
    if not isinstance(raw_groups, list):
        return _build_default_factor_catalog(available_factors)

    groups: list[dict[str, Any]] = []
    grouped_factors: set[str] = set()
    for item in raw_groups:
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("group_id", "")).strip()
        if not group_id:
            continue
        group_name = str(item.get("group_name", group_id)).strip() or group_id

        raw_children = item.get("children", [])
        if not isinstance(raw_children, list):
            raw_children = []
        children = []
        for name in raw_children:
            raw_label = str(name).strip()
            if not raw_label:
                continue
            resolved = _resolve_factor_column_name(raw_label, available_set)
            if resolved and resolved not in children:
                children.append(resolved)
        if not children:
            continue

        raw_core = item.get("core_factors", [])
        if not isinstance(raw_core, list):
            raw_core = []
        group_core: list[str] = []
        group_core_labels: list[str] = []
        for name in raw_core:
            raw_label = str(name).strip()
            if not raw_label:
                continue
            resolved = _resolve_factor_column_name(raw_label, available_set)
            if resolved is None or resolved not in children:
                continue
            if resolved not in group_core:
                group_core.append(resolved)
                group_core_labels.append(raw_label)

        groups.append(
            {
                "group_id": group_id,
                "group_name": group_name,
                "core_factors": group_core,
                "core_factor_labels": group_core_labels,
                "children": children,
            }
        )
        grouped_factors.update(children)

    # 未配置分组但存在因子时，兜底为“全部因子”单组
    if not groups:
        return _build_default_factor_catalog(available_factors)

    # 把未被配置覆盖的因子自动归入“未分类”
    ungrouped = [f for f in available_factors if f not in grouped_factors]
    if ungrouped:
        groups.append(
            {
                "group_id": "ungrouped",
                "group_name": "未分类",
                "core_factors": [],
                "core_factor_labels": [],
                "children": ungrouped,
            }
        )

    raw_core_factors = raw_catalog.get("core_factors", [])
    if not isinstance(raw_core_factors, list):
        raw_core_factors = []
    core_factors: list[str] = []
    core_factor_labels: list[str] = []
    for name in raw_core_factors:
        raw_label = str(name).strip()
        if not raw_label:
            continue
        resolved = _resolve_factor_column_name(raw_label, available_set)
        if resolved and resolved not in core_factors:
            core_factors.append(resolved)
            core_factor_labels.append(raw_label)
    if not core_factors:
        # 未配置全局核心因子时，自动使用各分组核心并去重
        for group in groups:
            gf = group.get("core_factors", [])
            gl = group.get("core_factor_labels", [])
            for i, factor_name in enumerate(gf):
                if factor_name in available_set and factor_name not in core_factors:
                    core_factors.append(factor_name)
                    lbl = gl[i] if i < len(gl) and str(gl[i]).strip() else str(factor_name)
                    core_factor_labels.append(str(lbl).strip())
    if not core_factors and available_factors:
        core_factors = [available_factors[0]]
        core_factor_labels = [available_factors[0]]

    return {"groups": groups, "core_factors": core_factors, "core_factor_labels": core_factor_labels}


def _load_factor_catalog(available_factors: list[str], force_refresh: bool = False) -> dict[str, Any]:
    now_ts = time.time()
    with _factor_catalog_lock:
        need_refresh = (
            force_refresh
            or _factor_catalog_cache.get("data") is None
            or (now_ts - float(_factor_catalog_cache.get("loaded_at", 0.0))) >= CODE_SEARCH_REFRESH_INTERVAL_SECONDS
        )

        if need_refresh:
            raw_catalog: Any = None
            if FACTOR_CATALOG_PATH.exists():
                try:
                    raw_catalog = json.loads(FACTOR_CATALOG_PATH.read_text(encoding="utf-8"))
                except Exception:
                    raw_catalog = None
            _factor_catalog_cache["data"] = raw_catalog
            _factor_catalog_cache["loaded_at"] = now_ts

        return _normalize_factor_catalog(_factor_catalog_cache.get("data"), available_factors)


def _normalize_limit(value: Any) -> int:
    if value is None or value == "":
        return CODE_SEARCH_LIMIT
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataValidationError("limit 必须为整数") from exc
    if parsed <= 0:
        raise MarketDataValidationError("limit 必须大于 0")
    return min(parsed, CODE_SEARCH_LIMIT)


def search_market_codes(
    keyword: Any,
    limit: Any = None,
    interval: Any = None,
    base_path: Optional[str] = None,
) -> dict[str, Any]:
    """按关键词检索市场代码，最多返回 5 条匹配结果。"""
    parsed_interval = str(interval).strip() if interval is not None and str(interval).strip() else "1min"
    if parsed_interval not in SUPPORTED_INTERVALS:
        raise MarketDataValidationError(f"interval 仅支持: {', '.join(SUPPORTED_INTERVALS)}")

    resolved_base_path = base_path or get_base_path_by_interval(parsed_interval)
    if not os.path.exists(resolved_base_path):
        raise MarketDataNotFoundError(f"数据根目录不存在: {resolved_base_path}")

    query = str(keyword).strip() if keyword is not None else ""
    if not query:
        raise MarketDataValidationError("q 不能为空")
    if not SEARCH_QUERY_ALLOWED_PATTERN.match(query):
        raise MarketDataValidationError("q 仅允许字母、数字、点、下划线和中划线")

    max_limit = _normalize_limit(limit)
    query_upper = query.upper()

    universe_records = _load_stock_universe_records()
    matched_items: list[dict[str, str]] = []
    seen_codes: set[str] = set()

    def _append_item(item: dict[str, str]) -> None:
        code = str(item.get("code") or "").strip().upper()
        if not code or code in seen_codes:
            return
        seen_codes.add(code)
        matched_items.append(
            {
                "code": code,
                "name": str(item.get("name") or "").strip(),
                "pinyin_initials": str(item.get("pinyin_initials") or "").strip().upper(),
            }
        )

    if universe_records:
        code_prefix = [r for r in universe_records if r["code"].startswith(query_upper)]
        code_contains = [
            r for r in universe_records
            if query_upper in r["code"] and not r["code"].startswith(query_upper)
        ]
        pinyin_prefix = [
            r for r in universe_records
            if r.get("pinyin_initials") and r["pinyin_initials"].startswith(query_upper)
        ]
        pinyin_contains = [
            r for r in universe_records
            if r.get("pinyin_initials")
            and query_upper in r["pinyin_initials"]
            and not r["pinyin_initials"].startswith(query_upper)
        ]
        name_prefix = [
            r for r in universe_records
            if r.get("name") and str(r["name"]).startswith(query)
        ]
        name_contains = [
            r for r in universe_records
            if r.get("name")
            and query in str(r["name"])
            and not str(r["name"]).startswith(query)
        ]
        alias_prefix = [
            r for r in universe_records
            if any(str(alias).startswith(query_upper) for alias in (r.get("name_pinyin_aliases") or ()))
        ]
        alias_contains = [
            r for r in universe_records
            if any(
                query_upper in str(alias) and not str(alias).startswith(query_upper)
                for alias in (r.get("name_pinyin_aliases") or ())
            )
        ]
        for bucket in (
            code_prefix,
            code_contains,
            name_prefix,
            name_contains,
            pinyin_prefix,
            pinyin_contains,
            alias_prefix,
            alias_contains,
        ):
            for item in bucket:
                _append_item(item)
                if len(matched_items) >= max_limit:
                    break
            if len(matched_items) >= max_limit:
                break
    else:
        all_codes = _get_cached_codes(resolved_base_path)
        portfolio_base_path = (
            PORTFOLIO_MINUTE_BASE_PATH if parsed_interval == "1min" else PORTFOLIO_DAILY_BASE_PATH
        )
        if os.path.exists(portfolio_base_path):
            portfolio_codes = _scan_all_codes_from_path(portfolio_base_path)
            all_codes = list(dict.fromkeys(all_codes + portfolio_codes))

        portfolio_matches = [
            code for code in PORTFOLIO_CURVE_CODES
            if query_upper in code and code not in all_codes
        ]
        if portfolio_matches:
            all_codes = portfolio_matches + all_codes

        prefix_matches = [code for code in all_codes if code.upper().startswith(query_upper)]
        contains_matches = [
            code for code in all_codes
            if query_upper in code.upper() and not code.upper().startswith(query_upper)
        ]
        for code in prefix_matches + contains_matches:
            _append_item({"code": code, "name": "", "pinyin_initials": ""})
            if len(matched_items) >= max_limit:
                break

    merged_items = matched_items[:max_limit]
    merged_codes = [item["code"] for item in merged_items]

    return {
        "codes": merged_codes,
        "items": merged_items,
        "meta": {
            "query": query,
            "interval": parsed_interval,
            "count": len(merged_codes),
            "limit": max_limit,
            "base_path": resolved_base_path,
            "universe_path": str(STOCK_UNIVERSE_PATH),
            "server_time": int(time.time()),
        },
    }


def list_signal_factors(
    interval: Any = None,
    base_path: Optional[str] = None,
    refresh: Any = None,
) -> dict[str, Any]:
    parsed_interval = str(interval).strip() if interval is not None and str(interval).strip() else "1day"
    if parsed_interval != "1day":
        raise MarketDataValidationError("因子接口暂仅支持 interval=1day")

    resolved_base_path = base_path or SIGNAL_DAILY_BASE_PATH
    if not os.path.exists(resolved_base_path):
        raise MarketDataNotFoundError(f"因子数据根目录不存在: {resolved_base_path}")

    force_refresh = str(refresh).strip().lower() in {"1", "true", "yes", "y"} if refresh is not None else False
    factors = _get_cached_factor_names(resolved_base_path, force_refresh=force_refresh)
    if not factors:
        raise MarketDataNotFoundError("未找到可用因子字段")

    catalog = _load_factor_catalog(factors, force_refresh=force_refresh)
    factor_labels = _build_factor_display_label_map(factors)
    return {
        "factors": factors,
        "groups": catalog.get("groups", []),
        "core_factors": catalog.get("core_factors", []),
        "core_factor_labels": catalog.get("core_factor_labels", []),
        "factor_labels": factor_labels,
        "meta": {
            "interval": parsed_interval,
            "count": len(factors),
            "group_count": len(catalog.get("groups", [])),
            "base_path": resolved_base_path,
            "catalog_path": str(FACTOR_CATALOG_PATH),
            "server_time": int(time.time()),
        },
    }


def _position_log_path(run_tag: str) -> Path:
    return BACKTEST_POSITION_BASE_PATH / f"position_log_{run_tag}.parquet"


def _date_str_to_utc_unix_day(date_str: str) -> int:
    normalized = str(date_str).strip()[:10]
    dt = datetime.strptime(normalized, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _portfolio_curve_close_from_daily_row(
    code: str,
    portfolio_value: float | None,
    cash_value: float | None,
) -> float | None:
    code_u = code.upper()
    if code_u == "000000.YKRS":
        if portfolio_value is None:
            return None
        return float(portfolio_value) / PORTFOLIO_INITIAL_CASH
    if code_u == "0000000.YKRS":
        if portfolio_value is None or abs(float(portfolio_value)) <= 1e-12:
            return None
        if cash_value is None:
            return None
        return float(cash_value) / float(portfolio_value)
    return None


def _query_portfolio_curve_bars_from_position_log(
    params: QueryParams,
    run_tag: str,
) -> dict[str, Any]:
    """run_tag 曲线目录缺失时，从 position_log 按日聚合重建组合/现金比例曲线。"""
    path = _position_log_path(run_tag)
    if not path.is_file():
        raise MarketDataNotFoundError(f"组合持仓文件不存在: {path}")

    from_date = datetime.utcfromtimestamp(params.from_ts).strftime("%Y-%m-%d")
    to_date = datetime.utcfromtimestamp(params.to_ts).strftime("%Y-%m-%d")
    parquet_path = str(path).replace("\\", "/")

    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(
            """
            SELECT CAST(date AS VARCHAR) AS date_str,
                   MAX(TRY_CAST(portfolio_value AS DOUBLE)) AS portfolio_value,
                   MAX(TRY_CAST(cash_value AS DOUBLE)) AS cash_value
            FROM read_parquet(?)
            WHERE CAST(date AS VARCHAR) >= ?
              AND CAST(date AS VARCHAR) <= ?
            GROUP BY CAST(date AS VARCHAR)
            ORDER BY CAST(date AS VARCHAR) ASC
            """,
            [parquet_path, from_date, to_date],
        ).fetchall()
    except duckdb.Error as exc:
        raise MarketDataError(f"从 position_log 构建曲线失败: {exc}") from exc
    finally:
        conn.close()

    dedup_by_time: dict[int, dict[str, Any]] = {}
    for date_str, portfolio_value, cash_value in rows:
        close = _portfolio_curve_close_from_daily_row(params.code, portfolio_value, cash_value)
        if close is None or math.isnan(close) or math.isinf(close):
            continue
        bar_time = _date_str_to_utc_unix_day(date_str)
        if bar_time < params.from_ts or bar_time > params.to_ts:
            continue
        dedup_by_time[bar_time] = {
            "time": bar_time,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 0.0,
        }

    bars_sorted = [dedup_by_time[t] for t in sorted(dedup_by_time)]
    if not bars_sorted:
        raise MarketDataNotFoundError("position_log 时间范围内无可用曲线数据")

    bars = bars_sorted[-params.limit :] if len(bars_sorted) > params.limit else bars_sorted
    latest_time = bars[-1]["time"] if bars else None
    has_new_data = (
        latest_time is not None
        and (params.last_seen_bar_time is None or latest_time > params.last_seen_bar_time)
    )

    return {
        "bars": bars,
        "meta": {
            "code": params.code,
            "interval": params.interval,
            "server_time": int(time.time()),
            "last_bar_time": latest_time,
            "has_new_data": has_new_data,
            "row_count": len(bars),
            "from": params.from_ts,
            "to": params.to_ts,
            "base_path": str(path),
            "run_tag": run_tag,
            "curve_source": "position_log_fallback",
        },
    }


def query_market_bars(
    code: Any,
    interval: Any,
    from_ts: Any = None,
    to_ts: Any = None,
    limit: Any = None,
    last_seen_bar_time: Any = None,
    base_path: Optional[str] = None,
    run_tag: Any = None,
    adjust: Any = None,
) -> dict[str, Any]:
    """查询市场 K 线与成交量数据，返回标准化 bars 与 meta。"""
    params = validate_query_params(code, interval, from_ts, to_ts, limit, last_seen_bar_time)
    try:
        adjust_mode = normalize_adjust_mode(adjust)
    except ValueError as exc:
        raise MarketDataValidationError(str(exc)) from exc
    parsed_run_tag = str(run_tag).strip() if run_tag else None
    extra_meta: dict[str, Any] = {}
    if base_path:
        resolved_base_path = base_path
    elif is_portfolio_curve_code(params.code):
        if not parsed_run_tag:
            resolved_base_path = get_base_path_by_code_and_interval(
                params.code,
                params.interval,
                run_tag=None,
            )
        else:
            curve_base = get_portfolio_daily_base_path(parsed_run_tag)
            pos_path = _position_log_path(parsed_run_tag)
            if os.path.isdir(curve_base):
                resolved_base_path = curve_base
            elif pos_path.is_file():
                code_u = params.code.upper()
                if code_u == BUY_HOLD_CURVE_CODE and os.path.isdir(PORTFOLIO_DAILY_BASE_PATH):
                    resolved_base_path = PORTFOLIO_DAILY_BASE_PATH
                    extra_meta["curve_source"] = "legacy_merged"
                elif code_u in {"000000.YKRS", "0000000.YKRS"}:
                    return _query_portfolio_curve_bars_from_position_log(params, parsed_run_tag)
                else:
                    raise MarketDataNotFoundError(
                        f"买入持有曲线不可用: run_tag={parsed_run_tag} 无分区目录且无 legacy 数据"
                    )
            else:
                resolved_base_path = curve_base
    else:
        resolved_base_path = get_base_path_by_code_and_interval(params.code, params.interval)

    if not os.path.exists(resolved_base_path):
        raise MarketDataNotFoundError(f"数据根目录不存在: {resolved_base_path}")

    partition_paths = build_partition_paths(
        resolved_base_path,
        params.from_ts,
        params.to_ts,
    )
    if not partition_paths:
        temp_bars = _supplement_bars_from_temp_today_cache(
            params,
            [],
            extra_meta,
            base_path,
            resolved_base_path,
            parsed_run_tag,
        )
        if temp_bars:
            should_adjust_daily_stock = (
                params.interval == "1day"
                and base_path is None
                and not is_portfolio_curve_code(params.code)
                and resolved_base_path == get_base_path_by_interval("1day")
            )
            return {
                "bars": temp_bars,
                "meta": _build_market_bars_meta(
                    params,
                    resolved_base_path,
                    parsed_run_tag,
                    "none" if not should_adjust_daily_stock else adjust_mode,
                    temp_bars,
                    extra_meta,
                    {},
                ),
            }
        raise MarketDataNotFoundError("目标时间范围内未找到对应分区")

    sql = _build_sql(len(partition_paths))
    query_args: list[Any] = [
        *partition_paths,
        params.code,
        params.from_ts,
        params.to_ts,
        params.limit,
    ]

    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, query_args).fetchall()
    except duckdb.Error as exc:
        raise MarketDataError(f"DuckDB 查询失败: {exc}") from exc
    finally:
        conn.close()

    dedup_by_time: dict[int, dict[str, Any]] = {}
    for row in rows:
        bar_time = int(row[0])
        dedup_by_time[bar_time] = {
            "time": bar_time,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }

    bars = [dedup_by_time[t] for t in sorted(dedup_by_time)]
    should_adjust_daily_stock = (
        params.interval == "1day"
        and base_path is None
        and not is_portfolio_curve_code(params.code)
        and resolved_base_path == get_base_path_by_interval("1day")
    )

    try:
        bar_boundaries = _get_cached_bar_time_boundaries(resolved_base_path, params.code)
    except MarketDataError:
        bar_boundaries = {}

    if not bars:
        temp_bars = _supplement_bars_from_temp_today_cache(
            params,
            [],
            extra_meta,
            base_path,
            resolved_base_path,
            parsed_run_tag,
        )
        if temp_bars:
            return {
                "bars": temp_bars,
                "meta": _build_market_bars_meta(
                    params,
                    resolved_base_path,
                    parsed_run_tag,
                    "none" if not should_adjust_daily_stock else adjust_mode,
                    temp_bars,
                    extra_meta,
                    bar_boundaries,
                ),
            }
        if bar_boundaries.get("first_available_bar_time") is not None:
            return {
                "bars": [],
                "meta": _build_market_bars_meta(
                    params,
                    resolved_base_path,
                    parsed_run_tag,
                    "none" if not should_adjust_daily_stock else adjust_mode,
                    [],
                    extra_meta,
                    bar_boundaries,
                ),
            }
        raise MarketDataNotFoundError("目标时间范围内未找到对应股票数据")

    if should_adjust_daily_stock:
        bars, adjust_mode = adjust_daily_bars(params.code, bars, adjust_mode)
    else:
        adjust_mode = "none"

    bars = _supplement_bars_from_temp_today_cache(
        params,
        bars,
        extra_meta,
        base_path,
        resolved_base_path,
        parsed_run_tag,
    )

    meta = _build_market_bars_meta(
        params,
        resolved_base_path,
        parsed_run_tag,
        adjust_mode,
        bars,
        extra_meta,
        bar_boundaries,
    )
    return {"bars": bars, "meta": meta}


def query_market_signal(
    code: Any,
    interval: Any,
    factor: Any,
    from_ts: Any = None,
    to_ts: Any = None,
    limit: Any = None,
    last_seen_signal_time: Any = None,
    base_path: Optional[str] = None,
) -> dict[str, Any]:
    params = validate_query_params(code, interval, from_ts, to_ts, limit, last_seen_signal_time)
    if params.interval != "1day":
        raise MarketDataValidationError("因子信号暂仅支持 interval=1day")

    factor_name = str(factor).strip() if factor is not None else ""
    if not factor_name:
        raise MarketDataValidationError("factor 不能为空")

    resolved_base_path = base_path or SIGNAL_DAILY_BASE_PATH
    if not os.path.exists(resolved_base_path):
        raise MarketDataNotFoundError(f"因子数据根目录不存在: {resolved_base_path}")

    available_factors = _get_cached_factor_names(resolved_base_path)
    resolved_factor_name = _resolve_factor_column_name(factor_name, set(available_factors))
    if resolved_factor_name is None:
        # 新增因子或名称切换后短时间内可能命中旧缓存，这里再强制刷新一次后重试判定。
        available_factors = _get_cached_factor_names(resolved_base_path, force_refresh=True)
        resolved_factor_name = _resolve_factor_column_name(factor_name, set(available_factors))
        if resolved_factor_name is None:
            raise MarketDataValidationError(f"factor 不存在: {factor_name}")

    partition_paths = _build_factor_partition_paths(
        resolved_base_path,
        resolved_factor_name,
        params.from_ts,
        params.to_ts,
    )
    if not partition_paths:
        raise MarketDataNotFoundError("目标时间范围内未找到对应因子分区")

    sql = _build_signal_sql(len(partition_paths))
    query_args: list[Any] = [
        *partition_paths,
        params.code,
        params.from_ts,
        params.to_ts,
        params.limit,
    ]

    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, query_args).fetchall()
    except duckdb.Error as exc:
        raise MarketDataError(f"DuckDB 因子查询失败: {exc}") from exc
    finally:
        conn.close()

    dedup_by_time: dict[int, dict[str, Any]] = {}
    for row in rows:
        signal_time = int(row[0])
        dedup_by_time[signal_time] = {
            "time": signal_time,
            "value": float(row[1]) if row[1] is not None else 0.0,
        }

    signals = [dedup_by_time[t] for t in sorted(dedup_by_time)]
    if not signals:
        raise MarketDataNotFoundError("目标时间范围内未找到对应股票因子数据")

    latest_time = signals[-1]["time"] if signals else None
    has_new_data = False
    if latest_time is not None:
        if params.last_seen_bar_time is None:
            has_new_data = True
        else:
            has_new_data = latest_time > params.last_seen_bar_time

    return {
        "signals": signals,
        "meta": {
            "code": params.code,
            "interval": params.interval,
            "factor": factor_name,
            "resolved_factor": resolved_factor_name,
            "server_time": int(time.time()),
            "last_signal_time": latest_time,
            "has_new_data": has_new_data,
            "row_count": len(signals),
            "from": params.from_ts,
            "to": params.to_ts,
            "base_path": resolved_base_path,
        },
    }


def _resolve_morph_candlestick_source_base(base_path: str) -> str:
    return os.path.join(base_path, MORPH_CANDLESTICK_SOURCE_DIR)


def _load_morph_candlestick_manifest(source_base: str) -> dict[str, Any]:
    manifest_path = os.path.join(source_base, MORPH_CANDLESTICK_MANIFEST_FILE)
    if not os.path.isfile(manifest_path):
        return {"schema_version": 1, "source": MORPH_CANDLESTICK_SOURCE_DIR, "patterns": {}}
    try:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataError(f"读取形态 manifest 失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise MarketDataError("形态 manifest 格式无效，需为对象")
    return payload


def _morph_patterns_for_level(manifest: dict[str, Any], level: str) -> list[str]:
    level_key = str(level or "").strip()
    patterns = manifest.get("patterns") or {}
    return sorted(
        name
        for name, meta in patterns.items()
        if isinstance(meta, dict) and str(meta.get("level") or "") == level_key
    )


def _build_events_partition_paths(source_base: str, from_ts: int, to_ts: int) -> list[str]:
    events_base = os.path.join(source_base, "events")
    if not os.path.exists(events_base):
        return []
    paths: list[str] = []
    for year, month in _iter_year_month(from_ts, to_ts):
        month_dir = os.path.join(events_base, f"year={year}", f"month={month:02d}")
        paths.extend(_list_partition_data_files(month_dir))
    return paths


def _build_morph_events_sql(path_count: int) -> str:
    if path_count <= 0:
        raise MarketDataValidationError("path_count 必须大于 0")
    path_placeholders = ", ".join(["?"] * path_count)
    return f"""
    WITH raw AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS normalized_code,
            COALESCE(
                TRY_CAST(time AS BIGINT),
                CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
            ) AS time_sec,
            COALESCE(
                TRY_CAST(start_time AS BIGINT),
                CAST(EPOCH(TRY_CAST(start_time AS TIMESTAMP)) AS BIGINT)
            ) AS start_time_sec,
            CAST(signal_name AS VARCHAR) AS signal_name,
            TRY_CAST(value AS DOUBLE) AS event_value,
            CAST(direction AS VARCHAR) AS direction,
            TRY_CAST(bar_span AS INTEGER) AS bar_span,
            CAST(level AS VARCHAR) AS event_level
        FROM read_parquet([{path_placeholders}], union_by_name = true)
    )
    SELECT
        time_sec AS time,
        start_time_sec AS start_time,
        signal_name,
        COALESCE(event_value, 0.0) AS value,
        direction,
        bar_span,
        event_level AS level
    FROM raw
    WHERE normalized_code = UPPER(?)
      AND event_level = ?
      AND time_sec IS NOT NULL
      AND time_sec BETWEEN ? AND ?
    ORDER BY time_sec ASC, signal_name ASC
    LIMIT ?
    """


def query_morph_candlestick_signals(
    code: Any,
    level: Any,
    from_ts: Any = None,
    to_ts: Any = None,
    limit: Any = None,
    base_path: Optional[str] = None,
    fields: Any = None,
) -> dict[str, Any]:
    params = validate_query_params(code, "1day", from_ts, to_ts, limit)
    level_key = str(level).strip() if level is not None else ""
    if level_key not in MORPH_CANDLESTICK_LEVELS:
        raise MarketDataValidationError("level 仅支持: level1, level2, level3")

    fields_key = str(fields or "all").strip().lower()
    include_patterns = fields_key in {"", "all", "patterns"}

    resolved_base_path = base_path or SIGNAL_DAILY_MORPH_BASE_PATH
    source_base = _resolve_morph_candlestick_source_base(resolved_base_path)
    if not os.path.exists(source_base):
        raise MarketDataNotFoundError(f"形态信号根目录不存在: {source_base}")

    manifest = _load_morph_candlestick_manifest(source_base)
    pattern_names = _morph_patterns_for_level(manifest, level_key)
    if include_patterns and not pattern_names:
        raise MarketDataNotFoundError(f"manifest 中未找到 level={level_key} 的形态定义")

    patterns: dict[str, list[dict[str, Any]]] = {}
    conn = duckdb.connect(database=":memory:")
    try:
        if include_patterns:
            for pattern_name in pattern_names:
                partition_paths = _build_factor_partition_paths(
                    source_base,
                    pattern_name,
                    params.from_ts,
                    params.to_ts,
                )
                if not partition_paths:
                    continue
                sql = _build_signal_sql(len(partition_paths))
                query_args: list[Any] = [
                    *partition_paths,
                    params.code,
                    params.from_ts,
                    params.to_ts,
                    params.limit,
                ]
                try:
                    rows = conn.execute(sql, query_args).fetchall()
                except duckdb.Error as exc:
                    raise MarketDataError(f"DuckDB 形态因子查询失败({pattern_name}): {exc}") from exc
                if rows:
                    patterns[pattern_name] = [
                        {
                            "time": int(row[0]),
                            "value": float(row[1]) if row[1] is not None else 0.0,
                        }
                        for row in rows
                    ]

        event_paths = _build_events_partition_paths(source_base, params.from_ts, params.to_ts)
        events: list[dict[str, Any]] = []
        if event_paths:
            events_sql = _build_morph_events_sql(len(event_paths))
            events_args: list[Any] = [
                *event_paths,
                params.code,
                level_key,
                params.from_ts,
                params.to_ts,
                params.limit,
            ]
            try:
                event_rows = conn.execute(events_sql, events_args).fetchall()
            except duckdb.Error as exc:
                raise MarketDataError(f"DuckDB 形态 events 查询失败: {exc}") from exc
            for row in event_rows:
                events.append(
                    {
                        "time": int(row[0]),
                        "start_time": int(row[1]) if row[1] is not None else int(row[0]),
                        "signal_name": str(row[2]),
                        "value": float(row[3]) if row[3] is not None else 0.0,
                        "direction": str(row[4] or ""),
                        "bar_span": int(row[5]) if row[5] is not None else 1,
                        "level": str(row[6] or level_key),
                    }
                )
    finally:
        conn.close()

    if not patterns and not events:
        if fields_key == "events":
            return {
                "patterns": {},
                "events": [],
                "meta": {
                    "code": params.code,
                    "level": level_key,
                    "server_time": int(time.time()),
                    "pattern_count": 0,
                    "event_count": 0,
                    "row_count": 0,
                    "from": params.from_ts,
                    "to": params.to_ts,
                    "base_path": resolved_base_path,
                    "source": MORPH_CANDLESTICK_SOURCE_DIR,
                    "fields": fields_key,
                },
            }
        raise MarketDataNotFoundError("目标时间范围内未找到对应形态信号")

    return {
        "patterns": patterns,
        "events": events,
        "meta": {
            "code": params.code,
            "level": level_key,
            "server_time": int(time.time()),
            "pattern_count": len(patterns),
            "event_count": len(events),
            "row_count": sum(len(items) for items in patterns.values()),
            "from": params.from_ts,
            "to": params.to_ts,
            "base_path": resolved_base_path,
            "source": MORPH_CANDLESTICK_SOURCE_DIR,
            "fields": fields_key if fields_key else "all",
        },
    }


def query_market_factor_snapshot(
    code: Any,
    interval: Any,
    time_ts: Any,
    mode: Any = None,
    group_id: Any = None,
    base_path: Optional[str] = None,
) -> dict[str, Any]:
    parsed_interval = str(interval).strip() if interval is not None else ""
    if parsed_interval != "1day":
        raise MarketDataValidationError("因子快照暂仅支持 interval=1day")

    parsed_code = str(code).strip() if code is not None else ""
    if not parsed_code:
        raise MarketDataValidationError("code 不能为空")
    if not CODE_PATTERN.match(parsed_code):
        raise MarketDataValidationError("code 仅允许字母、数字、点、下划线和中划线")

    parsed_time = _parse_optional_int(time_ts, "time")
    if parsed_time is None:
        raise MarketDataValidationError("time 不能为空")

    parsed_mode = str(mode).strip().lower() if mode is not None else "core"
    if parsed_mode not in {"core", "group", "all", "union"}:
        raise MarketDataValidationError("mode 仅支持: core, group, all, union")

    parsed_group_id = str(group_id).strip() if group_id is not None else ""
    if parsed_mode == "group" and not parsed_group_id:
        raise MarketDataValidationError("mode=group 时 group_id 不能为空")
    if parsed_mode == "union" and not parsed_group_id:
        raise MarketDataValidationError("mode=union 时 group_id 不能为空")

    resolved_base_path = base_path or SIGNAL_DAILY_BASE_PATH
    if not os.path.exists(resolved_base_path):
        raise MarketDataNotFoundError(f"因子数据根目录不存在: {resolved_base_path}")

    available_factors = _get_cached_factor_names(resolved_base_path)
    catalog = _load_factor_catalog(available_factors, force_refresh=False)

    selected_factors: list[str]
    if parsed_mode == "all":
        selected_factors = list(available_factors)
    elif parsed_mode == "core":
        selected_factors = [f for f in catalog.get("core_factors", []) if f in available_factors]
        if not selected_factors:
            selected_factors = list(available_factors)
    elif parsed_mode == "union":
        requested_group_ids = [
            "ungrouped" if str(item).strip() == "__ungrouped__" else str(item).strip()
            for item in parsed_group_id.split(",")
            if str(item).strip()
        ]
        if not requested_group_ids:
            raise MarketDataValidationError("mode=union 时 group_id 不能为空")
        group_map = {
            str(group.get("group_id", "")).strip(): group
            for group in catalog.get("groups", [])
            if str(group.get("group_id", "")).strip()
        }
        missing_group_ids = [group_key for group_key in requested_group_ids if group_key not in group_map]
        if missing_group_ids:
            raise MarketDataValidationError(f"group_id 不存在: {', '.join(missing_group_ids)}")

        selected_factors = []
        seen_factors: set[str] = set()

        def append_factors(names: list[str]) -> None:
            for factor_name in names:
                if factor_name in available_factors and factor_name not in seen_factors:
                    seen_factors.add(factor_name)
                    selected_factors.append(factor_name)

        append_factors(list(catalog.get("core_factors", [])))
        for group_key in requested_group_ids:
            group = group_map[group_key]
            append_factors(list(group.get("children", [])))

        if not selected_factors:
            raise MarketDataNotFoundError("所选核心因子与分组下没有可用因子")
    else:
        group_matched = None
        for group in catalog.get("groups", []):
            if str(group.get("group_id", "")).strip() == parsed_group_id:
                group_matched = group
                break
        if group_matched is None:
            raise MarketDataValidationError(f"group_id 不存在: {parsed_group_id}")
        selected_factors = [f for f in group_matched.get("children", []) if f in available_factors]
        if not selected_factors:
            raise MarketDataNotFoundError("该分组下没有可用因子")

    factors: dict[str, float] = {}
    conn = duckdb.connect(database=":memory:")
    try:
        for factor_name in selected_factors:
            partition_paths = _build_factor_partition_paths(
                resolved_base_path,
                factor_name,
                parsed_time,
                parsed_time,
            )
            if not partition_paths:
                factors[factor_name] = 0.0
                continue

            path_placeholders = ", ".join(["?"] * len(partition_paths))
            sql = f"""
            WITH raw AS (
                SELECT
                    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS normalized_code,
                    COALESCE(
                        TRY_CAST(time AS BIGINT),
                        CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
                    ) AS time_sec,
                    TRY_CAST(value AS DOUBLE) AS factor_value
                FROM read_parquet([{path_placeholders}], union_by_name = true)
            )
            SELECT factor_value
            FROM raw
            WHERE normalized_code = UPPER(?)
              AND time_sec IS NOT NULL
              AND CAST(FLOOR(time_sec / 86400.0) AS BIGINT) = CAST(FLOOR(? / 86400.0) AS BIGINT)
            ORDER BY time_sec DESC
            LIMIT 1
            """
            query_args: list[Any] = [*partition_paths, parsed_code, parsed_time]
            try:
                row = conn.execute(sql, query_args).fetchone()
            except duckdb.Error as exc:
                raise MarketDataError(f"DuckDB 因子快照查询失败: {exc}") from exc

            raw_value = row[0] if row else None
            try:
                value = float(raw_value) if raw_value is not None else 0.0
            except (TypeError, ValueError):
                value = 0.0
            if value != value:  # NaN
                value = 0.0
            factors[factor_name] = value
    finally:
        conn.close()

    return {
        "time": parsed_time,
        "factors": factors,
        "meta": {
            "code": parsed_code,
            "interval": parsed_interval,
            "mode": parsed_mode,
            "group_id": parsed_group_id if parsed_mode in {"group", "union"} else "",
            "count": len(factors),
            "total_factor_count": len(available_factors),
            "base_path": resolved_base_path,
            "server_time": int(time.time()),
        },
    }


def export_market_factor_rank_csv(
    time_ts: Any,
    factor: Any,
    base_path: Optional[str] = None,
) -> dict[str, Any]:
    parsed_time = _parse_optional_int(time_ts, "time")
    if parsed_time is None:
        raise MarketDataValidationError("time 不能为空")

    factor_name = str(factor).strip() if factor is not None else ""
    if not factor_name:
        raise MarketDataValidationError("factor 不能为空")

    resolved_base_path = base_path or SIGNAL_DAILY_BASE_PATH
    if not os.path.exists(resolved_base_path):
        raise MarketDataNotFoundError(f"因子数据根目录不存在: {resolved_base_path}")

    available_factors = _get_cached_factor_names(resolved_base_path)
    resolved_factor_name = _resolve_factor_column_name(factor_name, set(available_factors))
    if resolved_factor_name is None:
        available_factors = _get_cached_factor_names(resolved_base_path, force_refresh=True)
        resolved_factor_name = _resolve_factor_column_name(factor_name, set(available_factors))
        if resolved_factor_name is None:
            raise MarketDataValidationError(f"factor 不存在: {factor_name}")

    partition_paths = _build_factor_partition_paths(
        resolved_base_path,
        resolved_factor_name,
        parsed_time,
        parsed_time,
    )
    if not partition_paths:
        raise MarketDataNotFoundError("目标时间范围内未找到对应因子分区")

    all_codes = [
        code for code in _get_cached_codes(resolved_base_path)
        if code and not str(code).upper().endswith(".YKRS")
    ]
    if not all_codes:
        raise MarketDataNotFoundError("未找到可导出的标的代码")

    day_start = int(parsed_time // 86400) * 86400
    path_placeholders = ", ".join(["?"] * len(partition_paths))
    sql = f"""
    WITH raw AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS code,
            COALESCE(
                TRY_CAST(time AS BIGINT),
                CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
            ) AS time_sec,
            TRY_CAST(value AS DOUBLE) AS factor_value
        FROM read_parquet([{path_placeholders}], union_by_name = true)
    ),
    filtered AS (
        SELECT *
        FROM raw
        WHERE code IS NOT NULL
          AND code <> ''
          AND time_sec IS NOT NULL
          AND CAST(FLOOR(time_sec / 86400.0) AS BIGINT) = CAST(FLOOR(? / 86400.0) AS BIGINT)
          AND code NOT LIKE '%.YKRS'
    ),
    ranked AS (
        SELECT
            code,
            factor_value,
            ROW_NUMBER() OVER (
                PARTITION BY code
                ORDER BY time_sec DESC
            ) AS rn
        FROM filtered
    )
    SELECT
        code,
        factor_value
    FROM ranked
    WHERE rn = 1
    """

    value_by_code: dict[str, float | None] = {}
    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, [*partition_paths, parsed_time]).fetchall()
    except duckdb.Error as exc:
        raise MarketDataError(f"DuckDB 因子导出查询失败: {exc}") from exc
    finally:
        conn.close()

    for row in rows:
        code = str(row[0] or "").strip().upper()
        if not code:
            continue
        raw_value = row[1]
        try:
            parsed_value = float(raw_value) if raw_value is not None else None
        except (TypeError, ValueError):
            parsed_value = None
        if parsed_value is not None and parsed_value != parsed_value:
            parsed_value = None
        value_by_code[code] = parsed_value

    ordered_codes = sorted(set(str(code).upper() for code in all_codes if str(code).strip()))
    export_date = datetime.utcfromtimestamp(day_start).strftime("%Y-%m-%d")
    rows_for_csv: list[tuple[str, str, float | None]] = []
    for code in ordered_codes:
        rows_for_csv.append((export_date, code, value_by_code.get(code)))

    rows_for_csv.sort(
        key=lambda item: (
            item[2] is None,
            -(item[2] if item[2] is not None else 0.0),
            item[1],
        )
    )

    desktop_dir = Path.home() / "Desktop"
    if not desktop_dir.exists():
        desktop_dir = Path.home()
    safe_factor = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", factor_name) or "factor"
    file_name = f"factor_rank_{safe_factor}_{export_date}.csv"
    output_path = desktop_dir / file_name

    try:
        with output_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["时间", "标的代码", "因子值"])
            for row in rows_for_csv:
                value = "" if row[2] is None else row[2]
                writer.writerow([row[0], row[1], value])
    except OSError as exc:
        raise MarketDataError(f"CSV 写入失败: {exc}") from exc

    missing_count = sum(1 for item in rows_for_csv if item[2] is None)
    return {
        "file_path": str(output_path),
        "meta": {
            "time": day_start,
            "date": export_date,
            "factor": factor_name,
            "resolved_factor": resolved_factor_name,
            "row_count": len(rows_for_csv),
            "missing_count": missing_count,
            "base_path": resolved_base_path,
            "server_time": int(time.time()),
        },
    }


WATCHLIST_STATE_PATH = Path(__file__).resolve().parent / "watchlist_state.json"
_WATCHLIST_LOCK = Lock()
_MAX_WATCHLIST_CODES = 200
_DEFAULT_WATCHLIST: dict[str, Any] = {"codes": ["301469.SZ"], "selected": "301469.SZ"}


def _normalize_watchlist_payload(payload: Any) -> dict[str, Any]:
    parsed = payload if isinstance(payload, dict) else {}
    raw_codes = parsed.get("codes")
    codes_list = raw_codes if isinstance(raw_codes, list) else []
    normalized_codes: list[str] = []
    dedup: set[str] = set()
    for item in codes_list:
        code = str(item or "").strip().upper()
        if not code or code in dedup:
            continue
        dedup.add(code)
        normalized_codes.append(code)
        if len(normalized_codes) >= _MAX_WATCHLIST_CODES:
            break
    selected_raw = str(parsed.get("selected") or "").strip().upper()
    selected = selected_raw if selected_raw in normalized_codes else (normalized_codes[0] if normalized_codes else "")
    return {"codes": normalized_codes, "selected": selected}


def get_watchlist_state() -> dict[str, Any]:
    """读取服务端持久化的自选股列表（与前端 quant_watchlist_v1 结构一致）。"""
    with _WATCHLIST_LOCK:
        if not WATCHLIST_STATE_PATH.is_file():
            return dict(_DEFAULT_WATCHLIST)
        try:
            raw = json.loads(WATCHLIST_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MarketDataError(f"自选股状态文件损坏: {exc}") from exc
        state = _normalize_watchlist_payload(raw)
        if not state["codes"]:
            return dict(_DEFAULT_WATCHLIST)
        return state


def save_watchlist_state(payload: Any) -> dict[str, Any]:
    """保存自选股列表到本地 JSON 文件。"""
    state = _normalize_watchlist_payload(payload)
    with _WATCHLIST_LOCK:
        try:
            WATCHLIST_STATE_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise MarketDataError(f"自选股状态写入失败: {exc}") from exc
    return {
        **state,
        "meta": {
            "path": str(WATCHLIST_STATE_PATH),
            "server_time": int(time.time()),
        },
    }
