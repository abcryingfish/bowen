# -*- coding: utf-8 -*-
"""ZXW策略技术因子生成脚本。

本文件由同名 notebook 按 cell 顺序机械转换生成，业务逻辑保持不变。
运行前请确认 D:\\database 相关数据路径可用；脚本会按原 notebook 逻辑读写因子数据。
"""

try:
    from IPython.display import display
except Exception:
    def display(obj=None, *args, **kwargs):
        if obj is not None:
            print(obj)


# %% cell 1
import duckdb
import pandas as pd
from typing import Optional, Iterable
import numpy as np
import os
import re
import json
import importlib
import time
import sys
from pathlib import Path
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from MACD因子 import get_factor_lookback_config as get_macd_lookback_config
from KDJ因子 import get_factor_lookback_config as get_kdj_lookback_config
from 抄底因子 import get_factor_lookback_config as get_bottom_fishing_lookback_config
from 洪抄底 import get_factor_lookback_config as get_hong_bottom_fishing_lookback_config
from RSI import get_factor_lookback_config as get_rsi_lookback_config
from OBV因子 import get_factor_lookback_config as get_obv_lookback_config
from 唐奇安下通道 import get_factor_lookback_config as get_donchian_lower_lookback_config
from 动态波动率通道 import get_factor_lookback_config as get_dynamic_volatility_channel_lookback_config
from 筹码结构因子 import get_factor_lookback_config as get_chip_structure_lookback_config
from 新HL占比 import get_factor_lookback_config as get_new_hl_ratio_lookback_config
from 布林带策略 import get_factor_lookback_config as get_boll_strategy_lookback_config
from 总买入信号_独立全量 import get_factor_lookback_config as get_total_buy_signal_lookback_config
from 总卖出信号 import get_factor_lookback_config as get_total_sell_signal_lookback_config
from 卖出MACD import get_factor_lookback_config as get_macd_sell_lookback_config
from 总卖出信号测试 import get_factor_lookback_config as get_total_sell_pair_test_lookback_config
from 卖出因子_量能 import get_factor_lookback_config as get_sell_factor_volume_lookback_config
from 均线因子 import get_factor_lookback_config as get_moving_average_lookback_config
from 放量下跌因子 import get_factor_lookback_config as get_volume_drop_lookback_config
from 通达信强底信号 import get_factor_lookback_config as get_tdx_bottom_alert_lookback_config
from 板块动量策略常用因子 import get_factor_lookback_config as get_momentum_common_lookback_config
from 股票动量风格评分 import get_factor_lookback_config as get_stock_momentum_style_lookback_config
from 低波因子 import get_factor_lookback_config as get_low_volatility_lookback_config
from 股票低波风格评分 import get_factor_lookback_config as get_stock_low_volatility_style_lookback_config
from 流动性因子 import get_factor_lookback_config as get_liquidity_lookback_config
from 股票流动性综合评分 import get_factor_lookback_config as get_stock_liquidity_composite_lookback_config
from 股票市场数据因子 import get_factor_lookback_config as get_stock_market_data_lookback_config
from 股票纯市值风格评分 import get_factor_lookback_config as get_stock_size_style_pure_lookback_config
from 股票基本面原始因子 import get_factor_lookback_config as get_stock_fundamental_raw_lookback_config
from 股票价值标准化因子 import get_factor_lookback_config as get_stock_value_normalized_lookback_config
from 股票价值模型综合评分 import get_factor_lookback_config as get_stock_value_model_lookback_config
from 股票价值模型行业标准化评分 import get_factor_lookback_config as get_stock_value_model_industry_normalized_lookback_config
from 股票价值模型多板块标准化评分 import get_factor_lookback_config as get_stock_value_model_multi_board_normalized_lookback_config
from 股票成长原始因子 import get_factor_lookback_config as get_stock_growth_raw_lookback_config
from 股票成长标准化因子 import get_factor_lookback_config as get_stock_growth_normalized_lookback_config
from 股票成长行业标准化因子 import get_factor_lookback_config as get_stock_growth_industry_normalized_lookback_config
from 股票成长多板块标准化因子 import get_factor_lookback_config as get_stock_growth_multi_board_normalized_lookback_config
from 股票红利原始因子 import get_factor_lookback_config as get_stock_dividend_raw_lookback_config
from 股票红利标准化因子 import get_factor_lookback_config as get_stock_dividend_normalized_lookback_config
from MACD因子 import build_d_class_factor_bundle
from KDJ因子 import build_kdj_factor_bundle
from 抄底因子 import build_bottom_fishing_factor_bundle
from 洪抄底 import build_bottom_fishing_factor_bundle as build_hong_bottom_fishing_factor_bundle
from RSI import build_rsi_factor_bundle
from OBV因子 import build_obv_factor_bundle
from 唐奇安下通道 import build_donchian_lower_channel_factor_bundle
from 动态波动率通道 import build_dynamic_volatility_channel_factor_bundle
from 筹码结构因子 import build_chip_structure_factor_bundle
from 新HL占比 import build_new_hl_ratio_factor_bundle
from 布林带策略 import build_boll_strategy_factor_bundle
from 总买入信号_独立全量 import build_total_buy_signal_bundle
from 总卖出信号 import build_total_sell_signal_bundle
from 卖出MACD import build_macd_sell_factor_bundle
from 总卖出信号测试 import build_total_sell_pair_test_bundle
from 卖出因子_量能 import build_sell_factor_volume_bundle
from 均线因子 import build_moving_average_factor_bundle
from 放量下跌因子 import build_volume_drop_factor_bundle
from 通达信强底信号 import build_tdx_bottom_alert_bundle
from 板块动量策略常用因子 import build_industry_factor_bundle, build_momentum_factor_bundle
from 股票动量风格评分 import (
    FACTOR_NAME_MAP as MOMENTUM_STYLE_FACTOR_NAME_MAP,
    build_stock_momentum_style_bundle,
)
from 低波因子 import build_low_volatility_factor_bundle
from 股票低波风格评分 import (
    FACTOR_NAME_MAP as LOW_VOLATILITY_STYLE_FACTOR_NAME_MAP,
    build_stock_low_volatility_style_bundle,
)
from 流动性因子 import build_liquidity_factor_bundle
from 股票流动性综合评分 import (
    FACTOR_NAME_MAP as LIQUIDITY_COMPOSITE_FACTOR_NAME_MAP,
    build_stock_liquidity_composite_bundle,
)
from 股票市场数据因子 import build_stock_market_data_factor_bundle
from 股票纯市值风格评分 import (
    FACTOR_NAME_MAP as SIZE_STYLE_PURE_FACTOR_NAME_MAP,
    build_stock_size_style_pure_bundle,
)
from 股票基本面原始因子 import build_stock_fundamental_raw_factor_bundle
from 股票价值标准化因子 import (
    DERIVED_FACTOR_NAME_MAP as VALUE_NORMALIZED_FACTOR_NAME_MAP,
    build_stock_value_normalized_factor_bundle,
)
from 股票价值模型综合评分 import (
    FACTOR_NAME_MAP as VALUE_MODEL_FACTOR_NAME_MAP,
    MODEL_START_DATE as VALUE_MODEL_START_DATE,
    build_stock_value_model_composite_score_bundle,
)
from 股票价值模型行业标准化评分 import (
    FACTOR_NAME_MAP as VALUE_MODEL_INDUSTRY_NORMALIZED_FACTOR_NAME_MAP,
    MODEL_START_DATE as VALUE_MODEL_INDUSTRY_NORMALIZED_START_DATE,
    build_stock_value_model_industry_normalized_score_bundle,
)
from 股票价值模型多板块标准化评分 import (
    FACTOR_NAME_MAP as VALUE_MODEL_MULTI_BOARD_NORMALIZED_FACTOR_NAME_MAP,
    MODEL_START_DATE as VALUE_MODEL_MULTI_BOARD_NORMALIZED_START_DATE,
    build_stock_value_model_multi_board_normalized_score_bundle,
)
from 股票成长原始因子 import build_stock_growth_raw_factor_bundle
from 股票成长标准化因子 import (
    DERIVED_FACTOR_NAME_MAP as GROWTH_NORMALIZED_FACTOR_NAME_MAP,
    build_stock_growth_normalized_factor_bundle,
)
from 股票成长行业标准化因子 import (
    FACTOR_NAME_MAP as GROWTH_INDUSTRY_NORMALIZED_FACTOR_NAME_MAP,
    MODEL_START_DATE as GROWTH_INDUSTRY_NORMALIZED_START_DATE,
    build_stock_growth_industry_normalized_factor_bundle,
)
from 股票成长多板块标准化因子 import (
    FACTOR_NAME_MAP as GROWTH_MULTI_BOARD_NORMALIZED_FACTOR_NAME_MAP,
    MODEL_START_DATE as GROWTH_MULTI_BOARD_NORMALIZED_START_DATE,
    build_stock_growth_multi_board_normalized_factor_bundle,
)
from 股票红利原始因子 import build_stock_dividend_raw_factor_bundle
from 股票红利标准化因子 import (
    DERIVED_FACTOR_NAME_MAP as DIVIDEND_NORMALIZED_FACTOR_NAME_MAP,
    build_stock_dividend_normalized_factor_bundle,
)
from 纯技术面因子_bundle import (
    get_factor_lookback_config as get_pure_technical_lookback_config,
    iter_pure_technical_factor_bundles,
)
from valid_bar_utils import compute_bundles_with_valid_bar
BASE_PATH = r"D:\database\stock_basic_data_daily"   # 配置：股票日频数据根目录（只保留 year/month 分区）
INDEX_BASE_PATH = r"D:\database\index_data_daily"   # 指数日频数据根目录
ETF_BASE_PATH = r"D:\database\ETF_basic_data_daily"   # ETF 日频数据根目录
MARKET_DAILY_SOURCE_PATHS = [BASE_PATH, INDEX_BASE_PATH, ETF_BASE_PATH]
VIEW_NAME = "stock_day_merged"

# =========================
# 运行参数（统一入口）
# =========================
RUN_MODE = "auto"  # 固定自动模式：按缺失检测补写，不做人工 full/incremental 切换
# 仅配置起点；终点固定为运行当天的本机日历日（无需再填 END_DATE）
START_DATE = "2010-01-01"

# None 表示全市场（自动排除 .YKRS）
TARGET_CODES: Optional[list[str]] = None

# 选择需要执行的因子文件（bundle）
# 默认全量启用：一次性补齐全部因子
SELECTED_BUNDLES = [
    "macd",
    "kdj",
    "bottom_fishing",
    "hong_bottom_fishing",
    "rsi",
    "obv",
    "donchian_lower",
    "dynamic_volatility_channel",
    "chip_structure",
    "new_hl_ratio",
    "boll_strategy",
    "total_buy_signal",
    "total_sell_signal",
    "macd_sell",
    "total_sell_pair_test",
    "sell_factor_volume",
    "moving_average",
    "volume_drop",
    "tdx_bottom_alert",
    "momentum_common",
    "stock_momentum_style",
    "low_volatility",
    "stock_low_volatility_style_score",
    "liquidity",
    "stock_liquidity_composite",
    "stock_market_data",
    "stock_size_style_pure",
    "stock_fundamental_raw",
    "stock_value_normalized",
    "stock_value_model",
    "stock_value_model_industry_normalized",
    "stock_value_model_multi_board_normalized",
    "stock_growth_raw",
    "stock_growth_normalized",
    "stock_growth_industry_normalized",
    "stock_growth_multi_board_normalized",
    "stock_dividend_raw",
    "stock_dividend_normalized",
    "pure_technical",
]

# 可选：仅回补指定因子；None 表示按已启用 bundle 的全部因子自动补写
TARGET_FACTORS: Optional[list[str]] = None

LOOKBACK_BUFFER_DAYS = 20

BUNDLE_LOOKBACK_LOADERS = {
    "macd": get_macd_lookback_config,
    "kdj": get_kdj_lookback_config,
    "bottom_fishing": get_bottom_fishing_lookback_config,
    "hong_bottom_fishing": get_hong_bottom_fishing_lookback_config,
    "rsi": get_rsi_lookback_config,
    "obv": get_obv_lookback_config,
    "donchian_lower": get_donchian_lower_lookback_config,
    "dynamic_volatility_channel": get_dynamic_volatility_channel_lookback_config,
    "chip_structure": get_chip_structure_lookback_config,
    "new_hl_ratio": get_new_hl_ratio_lookback_config,
    "boll_strategy": get_boll_strategy_lookback_config,
    "total_buy_signal": get_total_buy_signal_lookback_config,
    "total_sell_signal": get_total_sell_signal_lookback_config,
    "macd_sell": get_macd_sell_lookback_config,
    "total_sell_pair_test": get_total_sell_pair_test_lookback_config,
    "sell_factor_volume": get_sell_factor_volume_lookback_config,
    "moving_average": get_moving_average_lookback_config,
    "volume_drop": get_volume_drop_lookback_config,
    "tdx_bottom_alert": get_tdx_bottom_alert_lookback_config,
    "momentum_common": get_momentum_common_lookback_config,
    "stock_momentum_style": get_stock_momentum_style_lookback_config,
    "low_volatility": get_low_volatility_lookback_config,
    "stock_low_volatility_style_score": get_stock_low_volatility_style_lookback_config,
    "liquidity": get_liquidity_lookback_config,
    "stock_liquidity_composite": get_stock_liquidity_composite_lookback_config,
    "stock_market_data": get_stock_market_data_lookback_config,
    "stock_size_style_pure": get_stock_size_style_pure_lookback_config,
    "stock_fundamental_raw": get_stock_fundamental_raw_lookback_config,
    "stock_value_normalized": get_stock_value_normalized_lookback_config,
    "stock_value_model": get_stock_value_model_lookback_config,
    "stock_value_model_industry_normalized": get_stock_value_model_industry_normalized_lookback_config,
    "stock_value_model_multi_board_normalized": get_stock_value_model_multi_board_normalized_lookback_config,
    "stock_growth_raw": get_stock_growth_raw_lookback_config,
    "stock_growth_normalized": get_stock_growth_normalized_lookback_config,
    "stock_growth_industry_normalized": get_stock_growth_industry_normalized_lookback_config,
    "stock_growth_multi_board_normalized": get_stock_growth_multi_board_normalized_lookback_config,
    "stock_dividend_raw": get_stock_dividend_raw_lookback_config,
    "stock_dividend_normalized": get_stock_dividend_normalized_lookback_config,
    "pure_technical": get_pure_technical_lookback_config,
}

BUNDLE_MODULE_NAMES = {
    "macd": "MACD因子",
    "kdj": "KDJ因子",
    "bottom_fishing": "抄底因子",
    "hong_bottom_fishing": "洪抄底",
    "rsi": "RSI",
    "obv": "OBV因子",
    "donchian_lower": "唐奇安下通道",
    "dynamic_volatility_channel": "动态波动率通道",
    "chip_structure": "筹码结构因子",
    "new_hl_ratio": "新HL占比",
    "boll_strategy": "布林带策略",
    "total_buy_signal": "总买入信号_独立全量",
    "total_sell_signal": "总卖出信号",
    "macd_sell": "卖出MACD",
    "total_sell_pair_test": "总卖出信号测试",
    "sell_factor_volume": "卖出因子_量能",
    "moving_average": "均线因子",
    "volume_drop": "放量下跌因子",
    "tdx_bottom_alert": "通达信强底信号",
    "momentum_common": "板块动量策略常用因子",
    "stock_momentum_style": "股票动量风格评分",
    "low_volatility": "低波因子",
    "stock_low_volatility_style_score": "股票低波风格评分",
    "liquidity": "流动性因子",
    "stock_liquidity_composite": "股票流动性综合评分",
    "stock_market_data": "股票市场数据因子",
    "stock_size_style_pure": "股票纯市值风格评分",
    "stock_fundamental_raw": "股票基本面原始因子",
    "stock_value_normalized": "股票价值标准化因子",
    "stock_value_model": "股票价值模型综合评分",
    "stock_value_model_industry_normalized": "股票价值模型行业标准化评分",
    "stock_value_model_multi_board_normalized": "股票价值模型多板块标准化评分",
    "stock_growth_raw": "股票成长原始因子",
    "stock_growth_normalized": "股票成长标准化因子",
    "stock_growth_industry_normalized": "股票成长行业标准化因子",
    "stock_growth_multi_board_normalized": "股票成长多板块标准化因子",
    "stock_dividend_raw": "股票红利原始因子",
    "stock_dividend_normalized": "股票红利标准化因子",
    "pure_technical": "纯技术面因子_bundle",
}

AUTO_PLAN_FROM_FACTOR_LIBRARY = True
FACTOR_LIBRARY_BASE_DIR = r"D:\database\signal_daily"
CATALOG_CACHE_PATH = os.path.join(FACTOR_LIBRARY_BASE_DIR, "_meta", "bundle_factor_catalog_cache.json")
POST_WRITE_DERIVED_BUNDLES = {
    "stock_momentum_style",
    "stock_low_volatility_style_score",
    "stock_liquidity_composite",
    "stock_size_style_pure",
    "stock_value_normalized",
    "stock_value_model",
    "stock_value_model_industry_normalized",
    "stock_value_model_multi_board_normalized",
    "stock_growth_normalized",
    "stock_growth_industry_normalized",
    "stock_growth_multi_board_normalized",
    "stock_dividend_normalized",
}

# 行业因子输出代码为 .THS 行业代码，不参与股票行情代码覆盖率检查。
NON_STOCK_FACTOR_KEYS = {
    "sector_volatility_zscore_20d_252d",
    "sector_return_zscore_8d_252d",
    "sector_ewma_rms_zscore_252d",
    "industry_pb_percentile_3y_mcap",
    "industry_pb_percentile_3y_median",
    "industry_pb_percentile_mcap",
    "industry_pb_percentile_median",
    "industry_profit_yoy_mcap",
    "industry_profit_yoy_median",
}

SECTOR_MARKET_FACTOR_KEYS = {
    "momentum_20d",
    "momentum_60d",
    "momentum_120d",
    "momentum_252d",
    "pure_momentum",
    "pure_momentum_60d",
    "pure_momentum_252d",
    "close_above_ma60",
    "annual_vol_60d",
}
SECTOR_ONLY_MARKET_FACTOR_KEYS = {
    "sector_volatility_zscore_20d_252d",
    "sector_return_zscore_8d_252d",
    "sector_ewma_rms_zscore_252d",
}
SECTOR_AGGREGATE_FACTOR_KEYS = {
    "industry_pb_percentile_3y_mcap",
    "industry_pb_percentile_3y_median",
    "industry_pb_percentile_mcap",
    "industry_pb_percentile_median",
    "industry_profit_yoy_mcap",
    "industry_profit_yoy_median",
}

# 行业聚合因子的输出代码是 .THS；计算输入仍需使用股票成分代码。
THS_ONLY_FACTOR_KEYS = set(SECTOR_AGGREGATE_FACTOR_KEYS)
STOCK_ONLY_FACTOR_KEYS = {
    "total_market_value",
    "floating_market_value",
    "free_float_market_value",
    "ln_free_float_market_value",
    "turnover_rate",
    "avg_trading_value_20d",
    "avg_trading_value_60d",
    "avg_turnover_20d",
    "avg_turnover_60d",
    "amihud_20d",
    "trading_value_volatility_20d",
    "zero_trading_value_ratio_20d",
    "annual_vol_20d",
    "annual_vol_60d",
    "annual_vol_252d",
    "downside_vol_20d",
    "downside_vol_60d",
    "max_drawdown_60d",
    "atr_volatility_14d",
    "volatility_ratio_20_60d",
    "return_on_equity_ttm",
    "sales_gross_margin_ttm",
    "operating_cashflow_to_revenue_ttm",
    "debt_to_asset_ratio",
    "revenue_cagr_3y_ttm",
    "revenue_growth_yoy_ttm",
    "operating_profit_growth_yoy_ttm",
    "adjusted_net_profit_growth_yoy_ttm",
    "basic_eps_growth_yoy_ttm",
    "operating_cashflow_growth_yoy_ttm",
    "revenue_growth_acceleration_ttm",
    "adjusted_net_profit_growth_acceleration_ttm",
    "return_on_equity_change_yoy_ttm",
    "sales_gross_margin_change_yoy_ttm",
    "research_expense_growth_yoy_ttm",
    "research_expense_to_revenue_ttm",
    "price_to_book_ratio",
    "cash_dividend_per_share_ttm_adjusted",
    "realized_dividend_yield_ttm",
    "cash_dividend_event_count_3y",
    "cash_dividend_active_year_ratio_5y",
    "cash_dividend_consecutive_years",
    "cash_dividend_cagr_3y",
    "cash_dividend_cut_count_5y",
}
STOCK_ONLY_FACTOR_KEYS.update(GROWTH_NORMALIZED_FACTOR_NAME_MAP.values())
STOCK_ONLY_FACTOR_KEYS.update(DIVIDEND_NORMALIZED_FACTOR_NAME_MAP.values())
STOCK_ONLY_FACTOR_KEYS.update(VALUE_NORMALIZED_FACTOR_NAME_MAP.values())
STOCK_ONLY_FACTOR_KEYS.update(VALUE_MODEL_FACTOR_NAME_MAP.values())
STOCK_ONLY_FACTOR_KEYS.update(SIZE_STYLE_PURE_FACTOR_NAME_MAP.values())
STOCK_ONLY_FACTOR_KEYS.update(MOMENTUM_STYLE_FACTOR_NAME_MAP.values())
STOCK_ONLY_FACTOR_KEYS.update(LOW_VOLATILITY_STYLE_FACTOR_NAME_MAP.values())
STOCK_ONLY_FACTOR_KEYS.update(LIQUIDITY_COMPOSITE_FACTOR_NAME_MAP.values())
SECTOR_OUTPUT_FACTOR_KEYS = THS_ONLY_FACTOR_KEYS | SECTOR_ONLY_MARKET_FACTOR_KEYS
BATCH_WATERMARK_FILE = "factor_batch_watermark.json"


def _batch_watermark_path(base_dir: str) -> Path:
    return Path(base_dir) / "_meta" / BATCH_WATERMARK_FILE


def _load_batch_watermark(base_dir: str) -> dict[str, object] | None:
    path = _batch_watermark_path(base_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"整批完成水位文件无效: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"整批完成水位必须是 JSON 对象: {path}")
    return payload


def _get_batch_complete_date(base_dir: str) -> pd.Timestamp | None:
    payload = _load_batch_watermark(base_dir)
    if payload is None:
        return None
    if payload.get("status") != "complete":
        raise ValueError("整批完成水位 status 必须为 complete")
    raw_date = payload.get("last_complete_date")
    try:
        complete_date = pd.Timestamp(raw_date).floor("D")
    except (TypeError, ValueError) as exc:
        raise ValueError("整批完成水位 last_complete_date 无效") from exc
    if pd.isna(complete_date):
        raise ValueError("整批完成水位 last_complete_date 无效")
    return complete_date


def _write_batch_watermark_atomic(base_dir: str, payload: dict[str, object]) -> Path:
    path = _batch_watermark_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.stem}.{os.getpid()}.tmp"
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return path


def _validate_factor_frames_for_batch(
    *,
    factor_dfs_dict: dict[str, pd.DataFrame],
    factor_name_map_dict: dict[str, str],
    target_date: pd.Timestamp,
    all_market_codes: set[str],
    ths_codes: set[str],
    ths_only_factor_keys: set[str],
) -> dict[str, int]:
    target_dt = pd.Timestamp(target_date).floor("D")
    _ = (all_market_codes, ths_codes)
    checked_keys: set[str] = set()
    all_market_factor_count = 0
    ths_factor_count = 0

    for factor_name, raw_key in factor_name_map_dict.items():
        factor_key = str(raw_key).strip()
        if not factor_key or factor_key in checked_keys:
            continue
        if factor_key not in factor_dfs_dict:
            raise ValueError(f"{factor_name} 因子矩阵未生成，不能推进整批完成水位")
        checked_keys.add(factor_key)
        frame = factor_dfs_dict[factor_key]
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"{factor_name} 因子矩阵为空，不能推进整批完成水位")
        frame_dates = pd.DatetimeIndex(pd.to_datetime(frame.index)).floor("D")
        if target_dt not in frame_dates:
            raise ValueError(f"{factor_name} 未计算到目标日期 {target_dt.date()}")

        if factor_key in ths_only_factor_keys:
            ths_factor_count += 1
        else:
            all_market_factor_count += 1

    if not checked_keys:
        raise ValueError("本次没有可校验的因子，不能推进整批完成水位")
    return {
        "factor_count": len(checked_keys),
        "all_market_factor_count": all_market_factor_count,
        "ths_factor_count": ths_factor_count,
    }


def _build_factor_scope_execution_plans(
    *,
    factor_plan_df: pd.DataFrame,
    bundle_factor_catalog: dict[str, dict[str, str]],
    selected_bundles: list[str],
    standard_market_codes: set[str],
    stock_codes: set[str],
    sector_codes: set[str],
    factor_lookback_days: dict[str, int],
    buffer_days: int,
    all_market_codes: set[str] | None = None,
) -> list[dict[str, object]]:
    """按因子输入范围生成相互独立的执行计划。"""
    if not isinstance(factor_plan_df, pd.DataFrame) or factor_plan_df.empty:
        return []

    needed = factor_plan_df[
        factor_plan_df["status"].isin(["missing", "stale"])
        & factor_plan_df["plan_start"].notna()
        & factor_plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        return []

    needed_by_key = {
        str(row["factor_en"]).strip(): row
        for _, row in needed.iterrows()
        if str(row.get("factor_en", "")).strip()
    }
    stock_only_factor_keys = globals().get(
        "STOCK_ONLY_FACTOR_KEYS",
        {
            "total_market_value",
            "floating_market_value",
            "free_float_market_value",
            "ln_free_float_market_value",
            "turnover_rate",
            "return_on_equity_ttm",
            "sales_gross_margin_ttm",
            "operating_cashflow_to_revenue_ttm",
            "debt_to_asset_ratio",
            "revenue_cagr_3y_ttm",
            "revenue_growth_yoy_ttm",
            "operating_profit_growth_yoy_ttm",
            "adjusted_net_profit_growth_yoy_ttm",
            "basic_eps_growth_yoy_ttm",
            "operating_cashflow_growth_yoy_ttm",
            "revenue_growth_acceleration_ttm",
            "adjusted_net_profit_growth_acceleration_ttm",
            "return_on_equity_change_yoy_ttm",
            "sales_gross_margin_change_yoy_ttm",
            "research_expense_growth_yoy_ttm",
            "research_expense_to_revenue_ttm",
            "price_to_book_ratio",
        },
    )
    normalized_scope_codes = {
        "standard_market": {
            str(code).strip().upper() for code in standard_market_codes if str(code).strip()
        },
        "all_market": {
            str(code).strip().upper()
            for code in (all_market_codes or (set(standard_market_codes) | set(sector_codes)))
            if str(code).strip()
        },
        "stock_market": {
            str(code).strip().upper() for code in stock_codes if str(code).strip()
        },
        "sector_market": {
            str(code).strip().upper() for code in sector_codes if str(code).strip()
        },
        "sector_aggregate": {
            str(code).strip().upper() for code in stock_codes if str(code).strip()
        },
        "ths_aggregate": {
            str(code).strip().upper() for code in stock_codes if str(code).strip()
        },
    }
    grouped_plans: dict[tuple[object, ...], dict[str, object]] = {}
    post_write_bundles = globals().get(
        "POST_WRITE_DERIVED_BUNDLES",
        {"stock_growth_normalized", "stock_dividend_normalized"},
    )
    for raw_bundle in selected_bundles:
        bundle = str(raw_bundle).strip().lower()
        if bundle in post_write_bundles:
            continue
        factor_map = bundle_factor_catalog.get(bundle, {})
        bundle_targets = {
            str(eng).strip()
            for eng in factor_map.values()
            if str(eng).strip() in needed_by_key
        }
        if not bundle_targets:
            continue

        for factor_key in sorted(bundle_targets):
            row = needed_by_key[factor_key]
            if factor_key in stock_only_factor_keys:
                scope = "stock_market"
            elif factor_key in SECTOR_ONLY_MARKET_FACTOR_KEYS:
                scope = "sector_market"
            elif factor_key in THS_ONLY_FACTOR_KEYS:
                scope = "ths_aggregate"
            else:
                scope = "all_market"

            codes = sorted(normalized_scope_codes[scope])
            if not codes:
                continue
            plan_start = pd.Timestamp(row["plan_start"]).floor("D")
            plan_end = pd.Timestamp(row["plan_end"]).floor("D")
            lookback_days = int(factor_lookback_days.get(factor_key, 0) or 0)
            query_start = plan_start - pd.Timedelta(days=lookback_days + int(buffer_days))
            group_key = (
                bundle,
                scope,
                tuple(codes),
                plan_start,
                plan_end,
            )
            if group_key not in grouped_plans:
                grouped_plans[group_key] = {
                    "bundle": bundle,
                    "scope": scope,
                    "target_keys": [],
                    "codes": codes,
                    "plan_start": plan_start,
                    "plan_end": plan_end,
                    "query_start": query_start,
                    "lookback_days": lookback_days,
                }
            else:
                grouped_plans[group_key]["query_start"] = min(
                    pd.Timestamp(grouped_plans[group_key]["query_start"]).floor("D"),
                    query_start,
                )
                grouped_plans[group_key]["lookback_days"] = max(
                    int(grouped_plans[group_key]["lookback_days"]),
                    lookback_days,
                )
            grouped_plans[group_key]["target_keys"].append(factor_key)

    return list(grouped_plans.values())


def _build_execution_code_windows(execution_plans: list[dict[str, object]]) -> pd.DataFrame:
    earliest_by_code: dict[str, pd.Timestamp] = {}
    for plan in execution_plans:
        query_start = pd.Timestamp(plan["query_start"]).floor("D")
        for raw_code in plan.get("codes", []):
            code = str(raw_code).strip().upper()
            if not code:
                continue
            current = earliest_by_code.get(code)
            if current is None or query_start < current:
                earliest_by_code[code] = query_start
    return pd.DataFrame(
        [
            {"htsc_code": code, "query_start": query_start}
            for code, query_start in sorted(earliest_by_code.items())
        ],
        columns=["htsc_code", "query_start"],
    )


def _group_execution_plans_for_compute(
    execution_plans: list[dict[str, object]],
) -> list[dict[str, object]]:
    """合并输入范围相同的计划，让组合因子继续共享基础计算。"""
    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for plan in execution_plans:
        bundle = str(plan.get("bundle", "")).strip().lower()
        scope = str(plan.get("scope", "market")).strip()
        codes = sorted({
            str(code).strip().upper()
            for code in plan.get("codes", [])
            if str(code).strip()
        })
        if not bundle or not codes:
            continue
        plan_end = pd.Timestamp(plan["plan_end"]).floor("D")
        group_key = (scope, tuple(codes), plan_end)
        if group_key not in grouped:
            grouped[group_key] = {
                "bundles": [],
                "scope": scope,
                "target_keys": [],
                "codes": codes,
                "query_start": pd.Timestamp(plan["query_start"]).floor("D"),
                "plan_start": pd.Timestamp(plan["plan_start"]).floor("D"),
                "plan_end": plan_end,
            }
        item = grouped[group_key]
        if bundle not in item["bundles"]:
            item["bundles"].append(bundle)
        item["target_keys"].extend(
            str(key).strip()
            for key in plan.get("target_keys", [])
            if str(key).strip()
        )
        item["query_start"] = min(
            pd.Timestamp(item["query_start"]).floor("D"),
            pd.Timestamp(plan["query_start"]).floor("D"),
        )
        item["plan_start"] = min(
            pd.Timestamp(item["plan_start"]).floor("D"),
            pd.Timestamp(plan["plan_start"]).floor("D"),
        )

    for item in grouped.values():
        item["target_keys"] = sorted(set(item["target_keys"]))
    return list(grouped.values())


def _prepare_execution_market_long(source: pd.DataFrame) -> pd.DataFrame:
    """一次性标准化行情长表并建立代码、日期索引，供所有执行批次复用。"""
    required_columns = [
        "time",
        "htsc_code",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    missing_columns = set(required_columns) - set(source.columns)
    if missing_columns:
        raise KeyError(f"行情长表缺少列: {sorted(missing_columns)}")

    prepared = source.loc[:, required_columns].copy()
    prepared["close_unadjusted"] = (
        source["close_unadjusted"] if "close_unadjusted" in source.columns else source["close"]
    )
    prepared["htsc_code"] = prepared["htsc_code"].astype(str).str.strip().str.upper()
    prepared["time"] = pd.to_datetime(prepared["time"], errors="coerce").dt.floor("D")
    prepared = prepared[
        prepared["time"].notna()
        & prepared["htsc_code"].ne("")
        & prepared["htsc_code"].ne("NAN")
    ]
    prepared = prepared.drop_duplicates(subset=["htsc_code", "time"], keep="last")
    return prepared.set_index(["htsc_code", "time"]).sort_index()


def _build_execution_plan_market_frames(
    source: pd.DataFrame,
    *,
    codes: list[str] | set[str] | tuple[str, ...],
    query_start: pd.Timestamp,
    plan_end: pd.Timestamp,
) -> dict[str, pd.DataFrame] | None:
    """只把单个执行批次需要的长表切片展开为宽矩阵。"""
    if not isinstance(source, pd.DataFrame) or source.empty:
        return None
    if not isinstance(source.index, pd.MultiIndex) or list(source.index.names) != ["htsc_code", "time"]:
        raise ValueError("执行行情长表必须先通过 _prepare_execution_market_long 建立索引")
    required_columns = {"open", "high", "low", "close", "close_unadjusted", "volume"}
    missing_columns = required_columns - set(source.columns)
    if missing_columns:
        raise KeyError(f"行情长表缺少列: {sorted(missing_columns)}")

    normalized_codes = {
        str(code).strip().upper() for code in codes if str(code).strip()
    }
    if not normalized_codes:
        return None
    start_dt = pd.Timestamp(query_start).floor("D")
    end_dt = pd.Timestamp(plan_end).floor("D")
    code_level = source.index.levels[source.index.names.index("htsc_code")]
    available_codes = sorted(normalized_codes & set(code_level.astype(str)))
    if not available_codes:
        return None

    try:
        local = source.loc[
            pd.IndexSlice[available_codes, start_dt:end_dt],
            ["open", "high", "low", "close", "close_unadjusted", "volume"],
        ].reset_index()
    except KeyError:
        return None
    if local.empty:
        return None
    wide = (
        local.set_index(["time", "htsc_code"])[
            ["open", "high", "low", "close", "close_unadjusted", "volume"]
        ]
        .sort_index()
        .unstack("htsc_code")
    )
    valid_bar = wide["close"].notna()
    return {
        "O": wide["open"].ffill().astype(float),
        "H": wide["high"].ffill().astype(float),
        "L": wide["low"].ffill().astype(float),
        "C": wide["close"].ffill().astype(float),
        "C_UNADJUSTED": wide["close_unadjusted"].astype(float),
        "V": wide["volume"].fillna(0).astype(float),
        "valid_bar": valid_bar,
    }


def _bundle_module_signature(selected_bundles: list[str]) -> dict[str, str]:
    signature: dict[str, str] = {}
    for bundle in selected_bundles:
        key = str(bundle).strip().lower()
        loader = BUNDLE_LOOKBACK_LOADERS.get(key)
        if loader is None:
            continue
        module_name = BUNDLE_MODULE_NAMES.get(key) or getattr(loader, "__module__", "")
        file_sig = ""
        try:
            mod = importlib.import_module(module_name)
            module_file = getattr(mod, "__file__", None)
            if module_file and os.path.exists(module_file):
                st = os.stat(module_file)
                file_sig = f"{Path(module_file).name}:{st.st_mtime_ns}"
        except Exception:
            pass
        signature[key] = f"{module_name}|{file_sig}"
    return signature


def _load_catalog_cache(cache_path: str) -> dict:
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_catalog_cache(cache_path: str, payload: dict) -> None:
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _compute_selected_bundles_for_planning(O, H, L, C, V, selected_bundles, T=None):
    selected_bundle_set = {str(x).strip().lower() for x in selected_bundles}
    bundle_outputs = []

    if "macd" in selected_bundle_set:
        bundle_outputs.append(build_d_class_factor_bundle(O=O, H=H, L=L, C=C))
    if "kdj" in selected_bundle_set:
        bundle_outputs.append(build_kdj_factor_bundle(O=O, H=H, L=L, C=C))
    if "bottom_fishing" in selected_bundle_set:
        bundle_outputs.append(build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C))
    if "hong_bottom_fishing" in selected_bundle_set:
        bundle_outputs.append(build_hong_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C))
    if "rsi" in selected_bundle_set:
        bundle_outputs.append(build_rsi_factor_bundle(C=C))
    if "obv" in selected_bundle_set:
        bundle_outputs.append(build_obv_factor_bundle(C=C, V=V))
    if "donchian_lower" in selected_bundle_set:
        bundle_outputs.append(build_donchian_lower_channel_factor_bundle(C=C, n=10))
    if "dynamic_volatility_channel" in selected_bundle_set:
        bundle_outputs.append(
            build_dynamic_volatility_channel_factor_bundle(
                H=H,
                L=L,
                C=C,
                high_window=20,
                atr_window=14,
                atr_multiplier=1.5,
            )
        )
    if "chip_structure" in selected_bundle_set:
        bundle_outputs.append(
            build_chip_structure_factor_bundle(
                H=H,
                L=L,
                C=C,
                V=V,
                T=T,
            )
        )
    if "new_hl_ratio" in selected_bundle_set:
        bundle_outputs.append(build_new_hl_ratio_factor_bundle(C=C, window=20))
    if "boll_strategy" in selected_bundle_set:
        bundle_outputs.append(build_boll_strategy_factor_bundle(C=C, window=20, k=2.0))
    if "total_buy_signal" in selected_bundle_set:
        bundle_outputs.append(build_total_buy_signal_bundle(O=O, H=H, L=L, C=C, V=V))
    if "total_sell_signal" in selected_bundle_set:
        bundle_outputs.append(build_total_sell_signal_bundle(C=C))
    if "macd_sell" in selected_bundle_set:
        bundle_outputs.append(build_macd_sell_factor_bundle(O=O, H=H, L=L, C=C))
    if "total_sell_pair_test" in selected_bundle_set:
        bundle_outputs.append(build_total_sell_pair_test_bundle(O=O, H=H, L=L, C=C, V=V))
    if "sell_factor_volume" in selected_bundle_set:
        bundle_outputs.append(build_sell_factor_volume_bundle(O=O, H=H, L=L, C=C, V=V))
    if "moving_average" in selected_bundle_set:
        bundle_outputs.append(build_moving_average_factor_bundle(C=C, windows=(5, 10, 15, 20, 30, 40, 50, 60, 70, 120)))
    if "volume_drop" in selected_bundle_set:
        bundle_outputs.append(build_volume_drop_factor_bundle(C=C, V=V, volume_window=20))
    if "tdx_bottom_alert" in selected_bundle_set:
        bundle_outputs.append(build_tdx_bottom_alert_bundle(O=O, H=H, L=L, C=C, V=V, valid_bar=C.notna()))
    if "low_volatility" in selected_bundle_set:
        bundle_outputs.append(build_low_volatility_factor_bundle(C=C, H=H, L=L, V=V))

    return bundle_outputs


def _build_bundle_catalog_with_synthetic_data(selected_bundles: list[str]) -> dict[str, dict[str, str]]:
    bundle_keys = [str(x).strip().lower() for x in selected_bundles if str(x).strip()]
    catalog: dict[str, dict[str, str]] = {}

    # 1) 优先使用 bundle 模块里预声明的 get_factor_catalog（零计算开销）
    for bundle_key in bundle_keys:
        loader = BUNDLE_LOOKBACK_LOADERS.get(bundle_key)
        if loader is None:
            continue
        module_name = BUNDLE_MODULE_NAMES.get(bundle_key) or getattr(loader, "__module__", "")
        try:
            mod = importlib.import_module(module_name)
            get_catalog = getattr(mod, "get_factor_catalog", None)
            if callable(get_catalog):
                meta = get_catalog()
                factor_map = dict(meta.get("factor_name_map", {}))
                if factor_map:
                    catalog[bundle_key] = factor_map
        except Exception:
            pass

    remaining = [b for b in bundle_keys if b not in catalog]
    if not remaining:
        return catalog

    # 2) 尝试从本地缓存读取历史探测结果
    signature = _bundle_module_signature(remaining)
    cache_payload = _load_catalog_cache(CATALOG_CACHE_PATH)
    if cache_payload.get("signature") == signature:
        cache_catalog = cache_payload.get("catalog", {})
        if isinstance(cache_catalog, dict):
            for bundle_key in remaining:
                item = cache_catalog.get(bundle_key)
                if isinstance(item, dict) and item:
                    catalog[bundle_key] = dict(item)

    remaining = [b for b in remaining if b not in catalog]
    if not remaining:
        return catalog

    # 3) 对缺失项才做 synthetic 回退探测，且降样本减少耗时
    sample_rows = 120
    sample_cols = 12
    idx = pd.date_range(end=pd.Timestamp.today().floor("D"), periods=sample_rows, freq="D")
    cols = [f"S{i:04d}.SZ" for i in range(sample_cols)]

    rng = np.random.default_rng(20260512)
    base = pd.DataFrame(rng.normal(loc=100.0, scale=5.0, size=(sample_rows, sample_cols)), index=idx, columns=cols)
    O = base.copy()
    C = base + pd.DataFrame(rng.normal(loc=0.0, scale=1.0, size=(sample_rows, sample_cols)), index=idx, columns=cols)
    high_pad = np.abs(pd.DataFrame(rng.normal(loc=1.0, scale=0.3, size=(sample_rows, sample_cols)), index=idx, columns=cols))
    low_pad = np.abs(pd.DataFrame(rng.normal(loc=1.0, scale=0.3, size=(sample_rows, sample_cols)), index=idx, columns=cols))
    H = np.maximum(O, C) + high_pad
    L = np.minimum(O, C) - low_pad
    V = pd.DataFrame(rng.integers(1000, 100000, size=(sample_rows, sample_cols)), index=idx, columns=cols).astype(float)

    computed_catalog: dict[str, dict[str, str]] = {}
    for bundle_key in remaining:
        try:
            outputs = _compute_selected_bundles_for_planning(
                O=O,
                H=H,
                L=L,
                C=C,
                V=V,
                selected_bundles=[bundle_key],
            )
            merged_name_map: dict[str, str] = {}
            for item in outputs:
                merged_name_map.update(item.get("factor_name_map", {}))
            if merged_name_map:
                catalog[bundle_key] = merged_name_map
                computed_catalog[bundle_key] = merged_name_map
        except Exception as exc:
            print(f"[WARN] 预估 bundle 因子目录失败，已跳过: {bundle_key}，原因: {exc}")

    if computed_catalog:
        _save_catalog_cache(
            CATALOG_CACHE_PATH,
            {
                "signature": signature,
                "catalog": computed_catalog,
            },
        )

    return catalog


def _normalize_date_str(date_text: str) -> str:
    dt = datetime.strptime(str(date_text).strip(), "%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


def _existing_market_daily_globs(source_paths: Iterable[str | Path]) -> list[str]:
    globs: list[str] = []
    for source_path in source_paths:
        root = Path(source_path)
        if not root.exists():
            print(f"[WARN] 日线数据源不存在，已跳过: {root}")
            continue
        pattern = root / "year=*" / "month=*" / "merged.parquet"
        if not list(root.glob("year=*/month=*/merged.parquet")):
            print(f"[WARN] 日线数据源无 merged.parquet，已跳过: {root}")
            continue
        globs.append(str(pattern).replace("\\", "/"))
    return globs


def _market_daily_view_sql(view_name: str, source_globs: list[str]) -> str:
    if not source_globs:
        raise ValueError("没有可用日线数据源，无法创建技术因子视图")
    path_list = "[" + ", ".join("'" + str(path).replace("'", "''") + "'" for path in source_globs) + "]"
    return f"""
CREATE OR REPLACE VIEW {view_name} AS
SELECT *
FROM read_parquet({path_list}, hive_partitioning=1, union_by_name=true)
"""


def _load_codes_from_market_globs(source_globs: list[str]) -> set[str]:
    if not source_globs:
        return set()
    path_list = "[" + ", ".join("'" + str(path).replace("'", "''") + "'" for path in source_globs) + "]"
    sql = f"""
    SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
    FROM read_parquet({path_list}, hive_partitioning=1, union_by_name=true)
    WHERE htsc_code IS NOT NULL
      AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
    """
    try:
        df_codes = con.execute(sql).df()
    except Exception:
        return set()
    return {str(code).strip().upper() for code in df_codes["htsc_code"].astype(str) if str(code).strip()}


def _sanitize_factor_dir_name(factor_name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(factor_name).strip()).rstrip(" .") or "未命名因子"


def _factor_processed_date_path(base_dir: str, factor_name: str) -> Path:
    safe_name = _sanitize_factor_dir_name(factor_name)
    return Path(base_dir) / f"factor={safe_name}" / "_meta" / "processed_through.json"


def _load_factor_processed_date(
    base_dir: str,
    factor_name: str,
) -> pd.Timestamp | None:
    path = _factor_processed_date_path(base_dir, factor_name)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"因子处理水位文件无效: {path}") from exc
    raw_date = payload.get("last_processed_date")
    try:
        processed_date = pd.Timestamp(raw_date).floor("D")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"因子处理水位日期无效: {path}") from exc
    if pd.isna(processed_date):
        raise ValueError(f"因子处理水位日期无效: {path}")
    return processed_date


def _write_factor_processed_date_atomic(
    base_dir: str,
    factor_name: str,
    processed_date: pd.Timestamp,
) -> Path:
    path = _factor_processed_date_path(base_dir, factor_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    target_date = pd.Timestamp(processed_date).floor("D")
    if pd.isna(target_date):
        raise ValueError("因子处理水位日期无效")
    existing_date = _load_factor_processed_date(base_dir, factor_name)
    if existing_date is not None:
        target_date = max(existing_date, target_date)
    payload = {
        "last_processed_date": target_date.strftime("%Y-%m-%d"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return path


def _collect_latest_factor_partition_paths(
    base_dir: str,
    factor_names: set[str] | None = None,
) -> list[str]:
    base_path = Path(base_dir)
    if factor_names:
        factor_dirs = [base_path / f"factor={_sanitize_factor_dir_name(name)}" for name in sorted(factor_names)]
    else:
        factor_dirs = sorted(base_path.glob("factor=*")) if base_path.exists() else []

    latest_paths: list[str] = []
    for factor_dir in factor_dirs:
        latest_files: list[Path] = []
        month_dirs: list[tuple[int, int, Path]] = []
        for month_dir in factor_dir.glob("year=*/month=*"):
            try:
                year = int(month_dir.parent.name.split("=", 1)[1])
                month = int(month_dir.name.split("=", 1)[1])
            except (IndexError, ValueError):
                continue
            month_dirs.append((year, month, month_dir))
        for _, _, month_dir in sorted(month_dirs, reverse=True):
            merged_path = month_dir / "merged.parquet"
            part_paths = [
                path
                for path in sorted(month_dir.glob("part_*.parquet"))
                if re.fullmatch(
                    r"part_\d+_\d+_[0-9a-f]+\.parquet",
                    path.name,
                    flags=re.IGNORECASE,
                )
            ]
            if merged_path.is_file():
                latest_files = [merged_path, *part_paths]
            elif part_paths:
                latest_files = part_paths
            if latest_files:
                break
        latest_paths.extend(str(path) for path in latest_files)
    return latest_paths


def _load_factor_last_date_map(base_dir: str) -> dict[str, pd.Timestamp]:
    """读取 parquet 日期与稀疏因子处理日期，并取每个因子的较大值。"""
    paths = _collect_latest_factor_partition_paths(base_dir)
    out: dict[str, pd.Timestamp] = {}
    if paths:
        placeholders = ", ".join(["?"] * len(paths))
        sql = f"""
        SELECT
            CAST(factor AS VARCHAR) AS factor_partition,
            MAX(CAST(time AS DATE)) AS max_dt
        FROM read_parquet([{placeholders}], hive_partitioning=1, union_by_name=true)
        GROUP BY 1
        """
        try:
            df_map = con.execute(sql, paths).df()
        except Exception:
            df_map = pd.DataFrame()
        for _, row in df_map.iterrows():
            factor_partition = str(row.get("factor_partition", "")).strip()
            max_dt = row.get("max_dt")
            if not factor_partition or pd.isna(max_dt):
                continue
            out[factor_partition] = pd.Timestamp(max_dt).floor("D")

    base_path = Path(base_dir)
    factor_dirs = sorted(base_path.glob("factor=*")) if base_path.exists() else []
    for factor_dir in factor_dirs:
        factor_name = factor_dir.name.split("=", 1)[-1]
        processed_date = _load_factor_processed_date(base_dir, factor_name)
        if processed_date is None:
            continue
        current = out.get(factor_name)
        out[factor_name] = (
            max(current, processed_date) if current is not None else processed_date
        )
    return out


def _get_factor_last_date(
    base_dir: str,
    factor_cn_name: str,
    factor_last_dt_map: Optional[dict[str, pd.Timestamp]] = None,
) -> pd.Timestamp | None:
    safe_name = _sanitize_factor_dir_name(factor_cn_name)
    key = f"{safe_name}"
    if factor_last_dt_map and key in factor_last_dt_map:
        return pd.Timestamp(factor_last_dt_map[key]).floor("D")

    parquet_date: pd.Timestamp | None = None
    paths = _collect_latest_factor_partition_paths(base_dir, {safe_name})
    if paths:
        placeholders = ", ".join(["?"] * len(paths))
        try:
            q = f"""
            SELECT MAX(CAST(time AS DATE)) AS max_dt
            FROM read_parquet([{placeholders}], hive_partitioning=1, union_by_name=true)
            """
            df_max = con.execute(q, paths).df()
        except Exception:
            df_max = pd.DataFrame()
        if not df_max.empty and not pd.isna(df_max.iloc[0, 0]):
            parquet_date = pd.Timestamp(df_max.iloc[0, 0]).floor("D")
    processed_date = _load_factor_processed_date(base_dir, safe_name)
    candidates = [date for date in (parquet_date, processed_date) if date is not None]
    return max(candidates) if candidates else None


def _resolve_non_stock_fallback_target_codes(
    *,
    auto_plan: bool,
    target_codes: Optional[list[str]],
    prequery_target_codes: list[str],
    selected_bundles: list[str],
    non_stock_source_codes: set[str],
    needs_all_codes_for_date_tail: bool,
) -> list[str]:
    if (
        auto_plan
        and not target_codes
        and not prequery_target_codes
        and selected_bundles
        and non_stock_source_codes
        and not needs_all_codes_for_date_tail
    ):
        return sorted(non_stock_source_codes)
    return list(prequery_target_codes)


def build_factor_fill_plan(
    factor_dfs_dict: dict[str, pd.DataFrame],
    factor_name_map_dict: dict[str, str],
    selected_bundles: list[str],
    start_date: str,
    end_date: str,
    base_dir: str,
    buffer_days: int,
    manual_targets: Optional[list[str]] = None,
    available_factor_keys: Optional[set[str]] = None,
    factor_last_dt_map: Optional[dict[str, pd.Timestamp]] = None,
    batch_complete_date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    _ = batch_complete_date
    _, factor_windows = _load_lookback_registry(selected_bundles)
    full_history_factor_keys = _load_full_history_factor_keys(selected_bundles)

    target_tokens = {str(x).strip() for x in (manual_targets or []) if str(x).strip()}
    target_english = set(target_tokens)
    for ch_name, eng_name in factor_name_map_dict.items():
        if str(ch_name).strip() in target_tokens:
            target_english.add(str(eng_name).strip())

    usable_factor_keys = {str(x).strip() for x in (available_factor_keys or set()) if str(x).strip()}
    if not usable_factor_keys:
        usable_factor_keys = {str(k).strip() for k in factor_dfs_dict.keys()}

    rows: list[dict[str, object]] = []
    for ch_name, eng_name in factor_name_map_dict.items():
        eng_key = str(eng_name).strip()
        if eng_key not in usable_factor_keys:
            continue
        if target_english and eng_key not in target_english:
            continue

        lookback_days = int(factor_windows.get(eng_key, 0) or 0)
        last_dt = _get_factor_last_date(
            base_dir=base_dir,
            factor_cn_name=str(ch_name),
            factor_last_dt_map=factor_last_dt_map,
        )
        if last_dt is None:
            plan_start = start_dt
            status = "missing"
            reason = "因子目录不存在或无历史数据"
        elif last_dt < end_dt:
            if eng_key in full_history_factor_keys:
                plan_start = start_dt
                reason = f"因子水位={last_dt.date()}，标记为全历史因子，重新计算至{end_dt.date()}"
            else:
                plan_start = max(start_dt, last_dt + pd.Timedelta(days=1))
                reason = f"因子水位={last_dt.date()}，需尾部补到{end_dt.date()}"
            status = "stale"
        else:
            plan_start = None
            status = "up_to_date"
            reason = f"因子水位={last_dt.date()}，已覆盖目标区间"

        rows.append(
            {
                "factor_cn": str(ch_name),
                "factor_en": eng_key,
                "lookback_days": lookback_days,
                "last_dt": last_dt,
                "status": status,
                "reason": reason,
                "plan_start": plan_start,
                "plan_end": end_dt if plan_start is not None else None,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=["factor_cn", "factor_en", "lookback_days", "last_dt", "status", "reason", "plan_start", "plan_end"]
        )

    plan_df = pd.DataFrame(rows)
    plan_df = plan_df.sort_values(["status", "factor_cn"], ascending=[True, True]).reset_index(drop=True)
    return plan_df


def _load_full_history_factor_keys(selected_bundles: list[str]) -> set[str]:
    """读取需要在过期时从 START_DATE 重算的因子键。"""
    full_history_keys: set[str] = set()
    lookback_loaders = globals().get("BUNDLE_LOOKBACK_LOADERS", {})
    for bundle in selected_bundles:
        key = str(bundle).strip().lower()
        loader = lookback_loaders.get(key)
        if loader is None:
            continue
        config = loader()
        for factor_key in config.get("full_history_factor_keys", []):
            normalized_key = str(factor_key).strip()
            if normalized_key:
                full_history_keys.add(normalized_key)
    return full_history_keys


def _load_lookback_registry(selected_bundles: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    bundle_windows: dict[str, int] = {}
    factor_windows: dict[str, int] = {}
    for bundle in selected_bundles:
        key = str(bundle).strip().lower()
        loader = BUNDLE_LOOKBACK_LOADERS.get(key)
        if loader is None:
            continue
        config = loader()
        bundle_windows[key] = int(config.get("bundle_lookback_days", 0) or 0)
        for factor_name, window in dict(config.get("factor_lookback_days", {})).items():
            factor_key = str(factor_name).strip()
            if not factor_key:
                continue
            factor_windows[factor_key] = max(int(window or 0), int(factor_windows.get(factor_key, 0)))
    return bundle_windows, factor_windows


def _compute_required_lookback_days(
    bundles: list[str],
    target_factors: Optional[list[str]] = None,
) -> int:
    bundle_windows, factor_windows = _load_lookback_registry(bundles)
    bundle_max = max(bundle_windows.values(), default=0)

    factor_keys = [str(x).strip() for x in (target_factors or []) if str(x).strip()]
    if factor_keys:
        factor_max = max((int(factor_windows.get(k, 0)) for k in factor_keys), default=0)
        if factor_max <= 0:
            factor_max = bundle_max
    else:
        factor_max = bundle_max

    return max(bundle_max, factor_max) + int(LOOKBACK_BUFFER_DAYS)


def _format_date_range(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> str:
    start_date = pd.Timestamp(start_dt).floor("D").date()
    end_date = pd.Timestamp(end_dt).floor("D").date()
    return f"{start_date} ~ {end_date}"


def _format_factor_name_lines(
    factor_names: list[str],
    *,
    per_line: int = 8,
) -> list[str]:
    names = [str(name).strip() for name in factor_names if str(name).strip()]
    if not names:
        return ["[因子] 无"]
    width = max(1, int(per_line))
    chunks = [names[index:index + width] for index in range(0, len(names), width)]
    total = len(chunks)
    return [
        f"[因子 {index}/{total}] " + "、".join(chunk)
        for index, chunk in enumerate(chunks, start=1)
    ]


def _format_execution_plan_lines(
    *,
    plan_idx: int,
    plan_total: int,
    bundle_label: str,
    scope: str,
    target_keys: list[str],
    code_count: int,
    query_start: pd.Timestamp,
    plan_start: pd.Timestamp,
    plan_end: pd.Timestamp,
) -> list[str]:
    lines = [
        f"[计划] 批次 {plan_idx}/{plan_total}：{bundle_label}/{scope}，"
        f"因子={len(target_keys)}，代码={int(code_count)}",
        f"[区间] 计算={_format_date_range(query_start, plan_end)}，"
        f"写入={_format_date_range(plan_start, plan_end)}",
    ]
    lines.extend(_format_factor_name_lines(target_keys))
    return lines


def _format_batch_finish_line(
    *,
    plan_idx: int,
    plan_total: int,
    bundle_label: str,
    scope: str,
    factor_count: int,
    elapsed_seconds: float,
) -> str:
    return (
        f"[完成] 批次 {plan_idx}/{plan_total}：{bundle_label}/{scope}，"
        f"生成={int(factor_count)}，耗时={float(elapsed_seconds):.2f}秒"
    )


def _format_save_progress_line(
    *,
    task_idx: int,
    task_total: int,
    factor_name: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    written_months: int,
    written_rows: int,
    elapsed_seconds: float,
) -> str:
    return (
        f"[保存完成] {task_idx}/{task_total} {factor_name}，"
        f"区间={_format_date_range(start_dt, end_dt)}，"
        f"月份={int(written_months)}，行数={int(written_rows)}，"
        f"耗时={float(elapsed_seconds):.2f}秒"
    )


selected_bundle_set = {str(x).strip().lower() for x in SELECTED_BUNDLES}

START_DATE = _normalize_date_str(START_DATE)

con = duckdb.connect()   # 初始化 DuckDB 连接
MARKET_DAILY_SOURCE_GLOBS = _existing_market_daily_globs(MARKET_DAILY_SOURCE_PATHS)
con.execute(_market_daily_view_sql(VIEW_NAME, MARKET_DAILY_SOURCE_GLOBS))    # 创建视图：自动识别 year/month 分区，读取所有 merged.parquet

_source_max_dt = con.execute(f"""
SELECT MAX(CAST(time AS DATE)) AS max_dt
FROM {VIEW_NAME}
WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
""").fetchone()[0]
if _source_max_dt is None:
    raise ValueError("stock_basic_data_daily 无可用日线数据，无法确定 END_DATE")
_source_code_set = set(
    con.execute(f"""
    SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
    FROM {VIEW_NAME}
    WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
    """).df()["htsc_code"].astype(str).tolist()
)
_stock_source_code_set = _load_codes_from_market_globs(_existing_market_daily_globs([BASE_PATH]))
_non_stock_source_code_set = _source_code_set - _stock_source_code_set
_sector_source_code_set = {
    code for code in _source_code_set if str(code).strip().upper().endswith(".THS")
}
_standard_market_source_code_set = _source_code_set - _sector_source_code_set
_today_dt = pd.Timestamp(datetime.now().date()).floor("D")
_source_end_dt = pd.Timestamp(_source_max_dt).floor("D")
END_DATE = min(_today_dt, _source_end_dt).strftime("%Y-%m-%d")
if datetime.strptime(START_DATE, "%Y-%m-%d").date() > datetime.strptime(END_DATE, "%Y-%m-%d").date():
    raise ValueError(f"START_DATE（{START_DATE}）不能晚于源数据终点（{END_DATE}）")
BATCH_COMPLETE_DATE = _get_batch_complete_date(FACTOR_LIBRARY_BASE_DIR)

PREQUERY_PLAN_DF = pd.DataFrame()
PREQUERY_TARGET_FACTOR_KEYS: set[str] = set()
PREQUERY_SELECTED_BUNDLES = [str(x).strip().lower() for x in SELECTED_BUNDLES]
PREQUERY_EFFECTIVE_START_DATE = START_DATE
PREQUERY_BUNDLE_FACTOR_CATALOG: dict[str, dict[str, str]] = {}
PREQUERY_TARGET_CODES: list[str] = []
PREQUERY_EXECUTION_PLANS: list[dict[str, object]] = []
_needs_all_codes_for_date_tail = False

if AUTO_PLAN_FROM_FACTOR_LIBRARY:
    PREQUERY_BUNDLE_FACTOR_CATALOG = _build_bundle_catalog_with_synthetic_data(SELECTED_BUNDLES)
    _catalog_name_map: dict[str, str] = {}
    for _bundle_name, _mapping in PREQUERY_BUNDLE_FACTOR_CATALOG.items():
        _catalog_name_map.update(_mapping)
    _catalog_factor_keys = {str(v).strip() for v in _catalog_name_map.values() if str(v).strip()}

    if _catalog_name_map:
        _factor_last_dt_map = _load_factor_last_date_map(FACTOR_LIBRARY_BASE_DIR)
        PREQUERY_PLAN_DF = build_factor_fill_plan(
            factor_dfs_dict={},
            factor_name_map_dict=_catalog_name_map,
            selected_bundles=SELECTED_BUNDLES,
            start_date=START_DATE,
            end_date=END_DATE,
            base_dir=FACTOR_LIBRARY_BASE_DIR,
            buffer_days=LOOKBACK_BUFFER_DAYS,
            manual_targets=TARGET_FACTORS,
            available_factor_keys=_catalog_factor_keys,
            factor_last_dt_map=_factor_last_dt_map,
            batch_complete_date=BATCH_COMPLETE_DATE,
        )
        _need_compute = PREQUERY_PLAN_DF[PREQUERY_PLAN_DF["status"].isin(["missing", "stale"])].copy()

        if not _need_compute.empty:
            PREQUERY_TARGET_FACTOR_KEYS = {str(x).strip() for x in _need_compute["factor_en"].astype(str)}
            PREQUERY_SELECTED_BUNDLES = [
                b for b, mapping in PREQUERY_BUNDLE_FACTOR_CATALOG.items()
                if any(str(eng).strip() in PREQUERY_TARGET_FACTOR_KEYS for eng in mapping.values())
            ]
            _, _factor_lookback_days = _load_lookback_registry(PREQUERY_SELECTED_BUNDLES)
            _manual_code_set = {
                str(code).strip().upper()
                for code in (TARGET_CODES or [])
                if str(code).strip()
            }
            _standard_plan_codes = set(_standard_market_source_code_set)
            _sector_plan_codes = set(_sector_source_code_set)
            _all_plan_codes = set(_source_code_set)
            if _manual_code_set:
                _standard_plan_codes &= _manual_code_set
                _sector_plan_codes &= _manual_code_set
                _all_plan_codes &= _manual_code_set

            PREQUERY_EXECUTION_PLANS = _build_factor_scope_execution_plans(
                factor_plan_df=PREQUERY_PLAN_DF,
                bundle_factor_catalog=PREQUERY_BUNDLE_FACTOR_CATALOG,
                selected_bundles=PREQUERY_SELECTED_BUNDLES,
                standard_market_codes=_standard_plan_codes,
                all_market_codes=_all_plan_codes,
                stock_codes=set(_stock_source_code_set),
                sector_codes=_sector_plan_codes,
                factor_lookback_days=_factor_lookback_days,
                buffer_days=LOOKBACK_BUFFER_DAYS,
            )
            if PREQUERY_EXECUTION_PLANS:
                PREQUERY_EFFECTIVE_START_DATE = min(
                    pd.Timestamp(plan["plan_start"]).floor("D")
                    for plan in PREQUERY_EXECUTION_PLANS
                ).strftime("%Y-%m-%d")
                PREQUERY_TARGET_CODES = sorted({
                    str(code).strip().upper()
                    for plan in PREQUERY_EXECUTION_PLANS
                    for code in plan["codes"]
                    if str(code).strip()
                })
        else:
            PREQUERY_SELECTED_BUNDLES = []

_fallback_target_codes = _resolve_non_stock_fallback_target_codes(
    auto_plan=AUTO_PLAN_FROM_FACTOR_LIBRARY,
    target_codes=TARGET_CODES,
    prequery_target_codes=PREQUERY_TARGET_CODES,
    selected_bundles=PREQUERY_SELECTED_BUNDLES,
    non_stock_source_codes=_non_stock_source_code_set,
    needs_all_codes_for_date_tail=_needs_all_codes_for_date_tail,
)
if _fallback_target_codes and not PREQUERY_TARGET_CODES:
    PREQUERY_TARGET_CODES = _fallback_target_codes
    print(f"[WARN] 本次自动回补限定为非股票日线标的: {len(PREQUERY_TARGET_CODES)} 只")

_bundles_for_query = [
    bundle
    for bundle in (
        PREQUERY_SELECTED_BUNDLES
        if PREQUERY_SELECTED_BUNDLES
        else [str(x).strip().lower() for x in SELECTED_BUNDLES]
    )
    if bundle not in POST_WRITE_DERIVED_BUNDLES
]
_factors_for_query = sorted(PREQUERY_TARGET_FACTOR_KEYS) if PREQUERY_TARGET_FACTOR_KEYS else TARGET_FACTORS
_effective_start_dt = pd.Timestamp(PREQUERY_EFFECTIVE_START_DATE).floor("D")

REQUIRED_LOOKBACK_DAYS = _compute_required_lookback_days(_bundles_for_query, _factors_for_query)
if PREQUERY_EXECUTION_PLANS:
    QUERY_START_DATE = min(
        pd.Timestamp(plan["query_start"]).floor("D")
        for plan in PREQUERY_EXECUTION_PLANS
    ).strftime("%Y-%m-%d")
else:
    QUERY_START_DATE = (_effective_start_dt - pd.Timedelta(days=REQUIRED_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

print("视图创建完成：", VIEW_NAME)
print("数据路径：", MARKET_DAILY_SOURCE_PATHS)
print("有效日线数据源：", MARKET_DAILY_SOURCE_GLOBS)
print(f"运行模式: {RUN_MODE}（自动缺失检测补写）")
print(f"目标区间: {START_DATE} ~ {END_DATE}（终点=运行当日）")
print(f"整批完成水位: {BATCH_COMPLETE_DATE.date() if BATCH_COMPLETE_DATE is not None else '未初始化'}")
print(f"预估执行bundle: {_bundles_for_query}")
print(f"查询起点(含回看): {QUERY_START_DATE}")
print(f"回看窗口(天): {REQUIRED_LOOKBACK_DAYS}")        
if not PREQUERY_PLAN_DF.empty:
    print("预加载阶段因子库体检概览:")
    display(PREQUERY_PLAN_DF[["factor_cn", "factor_en", "status", "last_dt", "plan_start", "plan_end"]].head(20))


PREQUERY_PLAN_DF[["factor_cn", "factor_en", "status", "last_dt", "plan_start", "plan_end"]]

# 查看有哪些年月分区（可选）
# df_partitions = con.execute(f"SELECT DISTINCT year, month FROM {VIEW_NAME} ORDER BY year, month").df(); print("\n现有分区："); print(df_partitions)

# %% cell 2
# from cgi import print_arguments


# target_codes = ["000905.SZ"]
# codes_str = ", ".join([f"'{code}'" for code in target_codes])

# # df_multi = con.execute(f"SELECT * FROM {VIEW_NAME} WHERE time >= '2010-01-01 00:00:00' AND time <= '2026-04-14 23:59:59' ORDER BY htsc_code, time").df()
# df_multi = con.execute(f"SELECT * FROM {VIEW_NAME} WHERE htsc_code IN ({codes_str}) AND time >= '2026-04-01 00:00:00' AND time <= '2026-04-16 23:59:59' ORDER BY htsc_code, time").df()
# # df_multi[['time','抄底总分']] #and df_multi['time']>'2026-04-01 16:29:18'

# # 这里需要固定时间格式，方便后续的统一时间轴计算
# df_multi['time'] = pd.to_datetime(df_multi['time']).dt.strftime('%Y-%m-%d')

# df_multi#.head(20)

# %% [markdown] cell 3
# # 取多标的

# %% cell 4
# 统一由主流程控制查询区间（含回看窗口），避免每个因子文件重复扫全历史
# 日频数据单次拉取，减少 Python 端多轮 SQL 往返

_execution_code_windows = _build_execution_code_windows(
    globals().get("PREQUERY_EXECUTION_PLANS", [])
)
_execution_code_windows_enabled = not _execution_code_windows.empty
if _execution_code_windows_enabled:
    con.register("_zxw_execution_code_windows", _execution_code_windows)


def _sql_escape_htsc(code: str) -> str:
    return str(code).strip().upper().replace("'", "''")


def _in_clause_for_batch(batch: list[str]) -> str:
    inner = ", ".join([f"'{_sql_escape_htsc(c)}'" for c in batch])
    return f"AND UPPER(TRIM(CAST(s.htsc_code AS VARCHAR))) IN ({inner})"


ADJ_MODE = "backward"
ADJ_FACTOR_DAILY_BASE_PATH = os.environ.get(
    "ZXW_ADJ_FACTOR_DAILY_PATH",
    r"D:\database\stock_adj_daily\adj_factor_daily",
)
ZXW_USE_ADJ_FACTOR_DAILY = str(os.environ.get("ZXW_USE_ADJ_FACTOR_DAILY", "1")).strip() != "0"
ZXW_FACTOR_DEBUG_TIMING = str(os.environ.get("ZXW_FACTOR_DEBUG_TIMING", "0")).strip() == "1"
_ADJ_FACTOR_DAILY_APPLIED = False
_LAST_WINDOW_BASE_SQL = ""


def _zxw_debug_timing(label: str, start_sec: float) -> None:
    if ZXW_FACTOR_DEBUG_TIMING:
        print(f"[TIMING] {label}: {time.perf_counter() - start_sec:.3f}s")


def _month_start_range_for_adj(start_text: str, end_text: str) -> list[pd.Timestamp]:
    start_dt = pd.Timestamp(start_text).floor("D")
    end_dt = pd.Timestamp(end_text).floor("D")
    cursor = pd.Timestamp(year=start_dt.year, month=start_dt.month, day=1)
    end_cursor = pd.Timestamp(year=end_dt.year, month=end_dt.month, day=1)
    months: list[pd.Timestamp] = []
    while cursor <= end_cursor:
        months.append(cursor)
        cursor = cursor + pd.offsets.MonthBegin(1)
    return months


def _adj_factor_daily_paths_for_window(start_text: str, end_text: str) -> list[str]:
    base = Path(ADJ_FACTOR_DAILY_BASE_PATH)
    if not base.exists():
        return []
    paths: list[str] = []
    for month_start in _month_start_range_for_adj(start_text, end_text):
        path = base / f"year={month_start.year:04d}" / f"month={month_start.month:02d}" / "merged.parquet"
        if path.is_file():
            paths.append(str(path).replace("\\", "/"))
    return paths


def _sql_string_list(values: list[str]) -> str:
    return "[" + ", ".join("'" + str(value).replace("'", "''") + "'" for value in values) + "]"


def _adj_factor_daily_join_sql(data_sql: str) -> str | None:
    global _ADJ_FACTOR_DAILY_APPLIED
    if not ZXW_USE_ADJ_FACTOR_DAILY or str(ADJ_MODE).strip().lower() != "backward":
        return None
    paths = _adj_factor_daily_paths_for_window(QUERY_START_DATE, END_DATE)
    if not paths:
        return None
    path_list = _sql_string_list(paths)
    _ADJ_FACTOR_DAILY_APPLIED = True
    return f"""
WITH d AS (
{data_sql}
),
a AS (
    SELECT
        UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
        CAST(time AS DATE) AS time,
        TRY_CAST(adj_factor AS DOUBLE) AS adj_factor
    FROM read_parquet({path_list}, union_by_name=true)
    WHERE CAST(time AS DATE) >= DATE '{QUERY_START_DATE}'
      AND CAST(time AS DATE) <= DATE '{END_DATE}'
)
SELECT d.* REPLACE (
    d.open * COALESCE(a.adj_factor, 1.0) AS open,
    d.high * COALESCE(a.adj_factor, 1.0) AS high,
    d.low * COALESCE(a.adj_factor, 1.0) AS low,
    d.close * COALESCE(a.adj_factor, 1.0) AS close
),
    d.close AS close_unadjusted
FROM d
LEFT JOIN a
  ON UPPER(TRIM(CAST(d.htsc_code AS VARCHAR))) = a.htsc_code
 AND CAST(d.time AS DATE) = a.time
"""


def _select_window_sql(extra_filter: str) -> str:
    global _LAST_WINDOW_BASE_SQL
    if _execution_code_windows_enabled:
        base_sql = f"""
SELECT s.*
FROM {VIEW_NAME} s
INNER JOIN _zxw_execution_code_windows w
  ON UPPER(TRIM(CAST(s.htsc_code AS VARCHAR))) = w.htsc_code
WHERE CAST(s.time AS DATE) >= CAST(w.query_start AS DATE)
  AND CAST(s.time AS DATE) <= DATE '{END_DATE}'
  {extra_filter}
"""
    else:
        base_sql = f"""
SELECT s.*
FROM {VIEW_NAME} s
WHERE CAST(s.time AS DATE) >= DATE '{QUERY_START_DATE}'
  AND CAST(s.time AS DATE) <= DATE '{END_DATE}'
  {extra_filter}
"""
    _LAST_WINDOW_BASE_SQL = base_sql
    joined_sql = _adj_factor_daily_join_sql(base_sql)
    return joined_sql if joined_sql is not None else base_sql


def _execute_window_sql_with_adj_fallback(sql_text: str) -> pd.DataFrame:
    global _ADJ_FACTOR_DAILY_APPLIED
    try:
        return con.execute(sql_text).df()
    except Exception as exc:
        if not _ADJ_FACTOR_DAILY_APPLIED:
            raise
        print(f"[WARN] adj_factor_daily 快路径失败，回退 wide_xdy 复权: {exc}")
        _ADJ_FACTOR_DAILY_APPLIED = False
        return con.execute(_LAST_WINDOW_BASE_SQL).df()


def _distinct_codes_in_window() -> list[str]:
    sql_codes = f"""
    SELECT DISTINCT htsc_code
    FROM {VIEW_NAME}
    WHERE CAST(time AS DATE) >= DATE '{QUERY_START_DATE}'
      AND CAST(time AS DATE) <= DATE '{END_DATE}'
      AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
    ORDER BY htsc_code
    """
    return con.execute(sql_codes).df()["htsc_code"].astype(str).tolist()


# 未指定有效标的时按全市场（排除 .YKRS）；若预检发现仅新增代码缺历史，则自动收缩到缺失代码。
_active_target_codes = list(TARGET_CODES) if TARGET_CODES else list(PREQUERY_TARGET_CODES)
_raw_targets = list(_active_target_codes) if _active_target_codes else []
if _raw_targets:
    _ordered_codes = sorted({str(c).strip().upper() for c in _raw_targets if str(c).strip()})
    if not _ordered_codes:
        _ordered_codes = _distinct_codes_in_window()
else:
    _ordered_codes = _distinct_codes_in_window()

_market_compute_bundles = [
    bundle
    for bundle in globals().get("PREQUERY_SELECTED_BUNDLES", [])
    if bundle not in POST_WRITE_DERIVED_BUNDLES
]
_skip_market_load = AUTO_PLAN_FROM_FACTOR_LIBRARY and len(_market_compute_bundles) == 0

if _skip_market_load:
    print("预加载计划显示无需补写，跳过市场数据读取。")
    df_multi = _execute_window_sql_with_adj_fallback(_select_window_sql("AND FALSE"))
elif not _ordered_codes:
    df_multi = _execute_window_sql_with_adj_fallback(_select_window_sql("AND FALSE"))
else:
    if _execution_code_windows_enabled:
        # 执行窗口表已经同时限定代码和各自起点，无需重复拼接超长 IN 列表。
        _sql = _select_window_sql("AND UPPER(TRIM(CAST(s.htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'")
    elif _raw_targets:
        # 指定标的：单次查询取齐，不再按 100 只分批。
        _sql = _select_window_sql(_in_clause_for_batch(_ordered_codes))
    else:
        # 全市场：单次查询取齐（排除 .YKRS）。
        _sql = _select_window_sql("AND UPPER(TRIM(CAST(s.htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'")

    _market_load_start = time.perf_counter()
    df_multi = _execute_window_sql_with_adj_fallback(_sql)
    _zxw_debug_timing("market_query_with_adj_factor_daily" if _ADJ_FACTOR_DAILY_APPLIED else "market_query", _market_load_start)
    print(f"单次查询完成，记录数={len(df_multi)}")

df_multi["time"] = pd.to_datetime(df_multi["time"]).dt.floor("D")
if "close_unadjusted" not in df_multi.columns:
    df_multi["close_unadjusted"] = df_multi["close"]



if _raw_targets and _ordered_codes:
    print(f"查询标的数: {len(_ordered_codes)}（单次查询）")
else:
    print(f"查询标的: 全市场（已排除 .YKRS），共 {len(_ordered_codes)} 只（单次查询）")
print(f"加载记录数: {len(df_multi)}")

# 这里查看占用内存的
# _df_mem_bytes = int(df_multi.memory_usage(deep=True).sum())
# _df_mem_mb = _df_mem_bytes / (1024 ** 2)
# print(f"DataFrame内存占用: {_df_mem_mb:.2f} MB")

df_multi

# print(f"总记录数: {len(df_multi)}")
# print("\n各股票记录数：")
# print(df_multi.groupby('htsc_code').size())
# print("\n数据预览：")
# print(df_multi.head(10))

# %% cell 5
import gc
from pathlib import Path

import numpy as np
import pandas as pd

ADJ_WIDE_BASE_PATH = r"D:\database\stock_adj_daily\wide_xdy"
ADJ_RAW_BASE_PATH = r"D:\database\stock_adj_daily_raw"
_ZXW_RAW_ADJ_VIEW = "_zxw_stock_adj_raw_events"
_OHLC = ("open", "high", "low", "close")
_RAW_EVENT_COLUMNS = (
    "htsc_code",
    "event_date",
    "interest",
    "stockBonus",
    "stockGift",
    "allotNum",
    "allotPrice",
)


def _zxw_ohlc_cols(df: pd.DataFrame) -> list[str]:
    lower = {c.lower(): c for c in df.columns}
    return [lower[k] for k in _OHLC if k in lower]


def _zxw_load_wide_xdy_series(codes: np.ndarray) -> dict[str, pd.Series]:
    wide_base = Path(ADJ_WIDE_BASE_PATH)
    paths = sorted(wide_base.glob("year=*/month=*/merged.parquet")) if wide_base.exists() else []
    if not paths:
        return {}
    target_codes = {str(code).strip().upper() for code in codes if str(code).strip()}
    result: dict[str, list[pd.Series]] = {}
    for path in paths:
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            print(f"[WARN] ?? wide_xdy ?????: {path} | {exc}")
            continue
        if frame.empty or "htsc_code" not in frame.columns:
            continue
        frame = frame.copy()
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        if target_codes:
            frame = frame[frame["htsc_code"].isin(target_codes)]
        if frame.empty:
            continue
        date_cols: list[tuple[str, pd.Timestamp]] = []
        for col in frame.columns:
            if col in ("htsc_code", "year", "month"):
                continue
            day = pd.to_datetime(str(col), format="%Y/%m/%d", errors="coerce")
            if pd.isna(day):
                continue
            date_cols.append((col, pd.Timestamp(day).normalize()))
        if not date_cols:
            continue
        for _, row in frame.iterrows():
            code = str(row["htsc_code"]).strip().upper()
            mapping: dict[pd.Timestamp, float] = {}
            for col, day in date_cols:
                value = pd.to_numeric(row[col], errors="coerce")
                if pd.isna(value):
                    continue
                mapping[day] = float(value)
            if mapping:
                result.setdefault(code, []).append(pd.Series(mapping, dtype=np.float64))
    out: dict[str, pd.Series] = {}
    for code, parts in result.items():
        series = pd.concat(parts).sort_index()
        series = series[~series.index.duplicated(keep="last")]
        out[code] = series.astype(np.float64)
    return out


def _zxw_backward_factor_series(xdy_series: pd.Series) -> pd.Series:
    values = pd.to_numeric(xdy_series, errors="coerce").astype(np.float64).sort_index()
    if values.empty:
        return pd.Series(dtype=np.float64)
    raw_values = values.to_numpy(dtype=np.float64)
    segment_start = np.ones(len(raw_values), dtype=bool)
    if len(raw_values) > 1:
        segment_start[1:] = raw_values[1:] != raw_values[:-1]
    segment_factors = np.where(segment_start, raw_values, 1.0)
    return pd.Series(np.cumprod(segment_factors), index=values.index, dtype=np.float64)


def _zxw_apply_ratio_adjustment(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    cols = _zxw_ohlc_cols(df)
    if not cols:
        raise KeyError("??? open/high/low/close ??????")
    xdy_by_code = _zxw_load_wide_xdy_series(df["htsc_code"].unique())
    if not xdy_by_code:
        print("??? wide_xdy ??????? raw event ??")
        return df

    out = df.copy()
    out["htsc_code"] = out["htsc_code"].astype(str).str.strip().str.upper()
    out["time"] = pd.to_datetime(out["time"], errors="coerce").dt.normalize()
    adjusted_rows = 0
    for code, idx in out.groupby("htsc_code", sort=False).groups.items():
        xdy_series = xdy_by_code.get(code)
        if xdy_series is None or xdy_series.empty:
            continue
        backward_series = _zxw_backward_factor_series(xdy_series)
        if backward_series.empty:
            continue
        row_pos = out.index.get_indexer(idx)
        days = out.iloc[row_pos]["time"]
        factors = days.map(backward_series).astype(float)
        first_day = backward_series.index.min()
        last_day = backward_series.index.max()
        last_factor = float(backward_series.iloc[-1])
        factors = factors.mask(days > last_day, last_factor)
        factors = factors.mask(days < first_day, 1.0)
        factors = factors.fillna(1.0).to_numpy(dtype=np.float64)
        if mode == "forward":
            factors = factors / (last_factor if last_factor != 0.0 else 1.0)
        values = out.iloc[row_pos][cols].to_numpy(dtype=np.float64, copy=True)
        values = values * factors[:, None]
        out.iloc[row_pos, out.columns.get_indexer(cols)] = values
        adjusted_rows += int(len(row_pos))
    print(f"wide_xdy {ADJ_MODE} ??: ?? {len(xdy_by_code)} ? | ? {adjusted_rows} / {len(out)}")
    return out.reset_index(drop=True)


def _zxw_load_raw_adj_events(codes: np.ndarray) -> pd.DataFrame:
    raw_base = Path(ADJ_RAW_BASE_PATH)
    raw_glob = str(raw_base / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    if not raw_base.exists() or not list(raw_base.glob("year=*/month=*/merged.parquet")):
        return pd.DataFrame(columns=list(_RAW_EVENT_COLUMNS))
    con.execute(
        f"""
CREATE OR REPLACE VIEW {_ZXW_RAW_ADJ_VIEW} AS
SELECT * FROM read_parquet('{raw_glob}', hive_partitioning=1, union_by_name=True)
"""
    )
    code_extra = _in_clause_for_batch(codes) if _raw_targets else ""
    raw_sql = f"""
SELECT
  UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
  CAST(event_date AS DATE) AS event_date,
  TRY_CAST(interest AS DOUBLE) AS interest,
  TRY_CAST(stockBonus AS DOUBLE) AS stockBonus,
  TRY_CAST(stockGift AS DOUBLE) AS stockGift,
  TRY_CAST(allotNum AS DOUBLE) AS allotNum,
  TRY_CAST(allotPrice AS DOUBLE) AS allotPrice
FROM {_ZXW_RAW_ADJ_VIEW}
WHERE htsc_code IS NOT NULL
  AND event_date IS NOT NULL
  AND CAST(event_date AS DATE) <= DATE '{END_DATE}'
  AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
  {code_extra}
"""
    events = con.execute(raw_sql).df()
    if events.empty:
        return pd.DataFrame(columns=list(_RAW_EVENT_COLUMNS))
    events["htsc_code"] = events["htsc_code"].astype(str).str.strip().str.upper()
    events["event_date"] = pd.to_datetime(events["event_date"], errors="coerce").dt.normalize()
    for col in ("interest", "stockBonus", "stockGift", "allotNum", "allotPrice"):
        events[col] = pd.to_numeric(events[col], errors="coerce").fillna(0.0).astype(np.float64)
    return (
        events.dropna(subset=["htsc_code", "event_date"])
        .drop_duplicates(subset=["htsc_code", "event_date"], keep="last")
        .sort_values(["htsc_code", "event_date"])
        .reset_index(drop=True)
    )


def _zxw_apply_ordinary_adjustment(df: pd.DataFrame, events: pd.DataFrame, mode: str) -> pd.DataFrame:
    cols = _zxw_ohlc_cols(df)
    if not cols:
        raise KeyError("??? open/high/low/close ??????")
    if events.empty:
        print("??? raw event ?????OHLC ????")
        return df

    out = df.copy()
    out["htsc_code"] = out["htsc_code"].astype(str).str.strip().str.upper()
    out["time"] = pd.to_datetime(out["time"], errors="coerce").dt.normalize()
    event_map = {
        code: g.sort_values("event_date").reset_index(drop=True)
        for code, g in events.groupby("htsc_code", sort=False)
    }

    adjusted_rows = 0
    for code, idx in out.groupby("htsc_code", sort=False).groups.items():
        ev = event_map.get(code)
        if ev is None or ev.empty:
            continue
        row_pos = out.index.get_indexer(idx)
        days = out.iloc[row_pos]["time"].to_numpy(dtype="datetime64[ns]")
        values = out.iloc[row_pos][cols].to_numpy(dtype=np.float64, copy=True)
        event_iter = ev.iloc[::-1].itertuples(index=False) if mode == "backward" else ev.itertuples(index=False)
        for event in event_iter:
            event_day = np.datetime64(pd.Timestamp(event.event_date).normalize())
            ratio = 1.0 + float(event.stockBonus) + float(event.stockGift) + float(event.allotNum)
            if ratio <= 0.0:
                ratio = 1.0
            cash = float(event.interest) + float(event.allotNum) * float(event.allotPrice)
            if mode == "backward":
                mask = days >= event_day
                values[mask, :] = values[mask, :] * ratio + cash
            else:
                mask = days < event_day
                values[mask, :] = (values[mask, :] - cash) / ratio
        out.iloc[row_pos, out.columns.get_indexer(cols)] = values
        adjusted_rows += int(len(row_pos))
    print(f"raw event {ADJ_MODE} ????: ?? {len(event_map)} ? | ? {adjusted_rows} / {len(out)}")
    return out.reset_index(drop=True)


_mode = str(ADJ_MODE).strip().lower()
if _mode not in ("none", "forward", "backward"):
    raise ValueError("ADJ_MODE ??? none / forward / backward")

if _ADJ_FACTOR_DAILY_APPLIED:
    print("ADJ_MODE:", ADJ_MODE, "| 已使用 adj_factor_daily 快路径完成比例后复权")
elif _mode == "none" or _skip_market_load or len(df_multi) == 0:
    if _mode != "none" and len(df_multi) == 0:
        print("df_multi ???????")
else:
    df_multi["htsc_code"] = df_multi["htsc_code"].astype(str).str.strip().str.upper()
    df_multi["time"] = pd.to_datetime(df_multi["time"], errors="coerce").dt.normalize()
    # Use wide_xdy for ratio-adjusted prices.
    df_multi = _zxw_apply_ratio_adjustment(df_multi, _mode)
    gc.collect()
    df_multi["time"] = pd.to_datetime(df_multi["time"]).dt.floor("D")

print("ADJ_MODE:", ADJ_MODE, "| df_multi ??:", len(df_multi))

# %% cell 6
# df_multi[df_multi['htsc_code']=='600089.SH'].tail(50)

# %% [markdown] cell 7
# # 这里看重复的行数

# %% cell 8
# 查看是否有重复（htsc_code + time）
dup_mask = df_multi.duplicated(subset=['htsc_code', 'time'], keep=False)
n_dup = int(dup_mask.sum())
print(f"重复行数: {n_dup}")

if n_dup > 0:
    print("重复样本（去重前）:")
    print(df_multi[dup_mask].sort_values(['htsc_code', 'time']).head(10))

    before = len(df_multi)
    df_multi = df_multi.drop_duplicates(subset=['htsc_code', 'time'], keep='last').reset_index(drop=True)
    print(f"已去重: {before} -> {len(df_multi)} 行（保留每组最后一条）")
else:
    print("无重复，无需去重")

# %% cell 9
df_multi[df_multi['htsc_code']=='600089.SH'].tail(30)

# %% cell 10
# df_multi = df_multi

# %% [markdown] cell 11
#

# %% [markdown] cell 12
# # 这里得到 不同的属性的表格

# %% cell 13
# dup = df_multi.duplicated(['time', 'htsc_code'], keep=False)
# df_multi[dup].sort_values(['htsc_code', 'time']).tail(20)

# %% cell 14
# 长表只标准化并建立一次索引；每个批次按代码和日期索引切片，不再重复扫描全表。
EXECUTION_MARKET_LONG = _prepare_execution_market_long(df_multi)
del df_multi
gc.collect()

from 筹码结构因子 import load_turnover_wide

TURNOVER_BASE_PATH = r"D:\database\qmt_turnover_data"

# %% [markdown] cell 15
# # 时间测试模块

# %% cell 16
from MACD因子 import build_d_class_factor_bundle
from KDJ因子 import build_kdj_factor_bundle
from 抄底因子 import build_bottom_fishing_factor_bundle
from 洪抄底 import build_bottom_fishing_factor_bundle as build_hong_bottom_fishing_factor_bundle
from RSI import build_rsi_factor_bundle
from OBV因子 import build_obv_factor_bundle
from 唐奇安下通道 import build_donchian_lower_channel_factor_bundle
from 动态波动率通道 import build_dynamic_volatility_channel_factor_bundle
from 筹码结构因子 import build_chip_structure_factor_bundle
from 新HL占比 import build_new_hl_ratio_factor_bundle
from 布林带策略 import build_boll_strategy_factor_bundle
from 总买入信号_独立全量 import build_total_buy_signal_bundle
from 总卖出信号 import build_total_sell_signal_bundle
from 卖出MACD import build_macd_sell_factor_bundle
from 总卖出信号测试 import build_total_sell_pair_test_bundle
from 卖出因子_量能 import build_sell_factor_volume_bundle
from 均线因子 import build_moving_average_factor_bundle
from 放量下跌因子 import build_volume_drop_factor_bundle
from 通达信强底信号 import build_tdx_bottom_alert_bundle
from 股票市场数据因子 import build_stock_market_data_factor_bundle
from 股票基本面原始因子 import build_stock_fundamental_raw_factor_bundle
from 股票成长原始因子 import build_stock_growth_raw_factor_bundle
from 股票红利原始因子 import build_stock_dividend_raw_factor_bundle
from valid_bar_utils import compute_bundles_with_valid_bar
from time import perf_counter


def _merge_bundle_output(output, factor_dfs, factor_name_map):
    factor_dfs.update(output.get("factor_dfs", {}))
    factor_name_map.update(output.get("factor_name_map", {}))


def _compute_selected_bundles_raw(O, H, L, C, V, selected_bundles, T=None, enable_bottom_cache=True, valid_bar=None):
    selected_bundle_set = {str(x).strip().lower() for x in selected_bundles}
    bundle_outputs = []
    shared_factor_dfs = {}
    shared_factor_name_map = {}
    bundle_cache = globals().setdefault("_bundle_cache", {})

    def _add(bundle_key, output):
        bundle_outputs.append(output)
        _merge_bundle_output(output, shared_factor_dfs, shared_factor_name_map)

    def _need(*bundle_keys):
        return any(key in selected_bundle_set for key in bundle_keys)

    if _need("macd", "total_buy_signal", "tdx_bottom_alert", "sell_factor_volume"):
        output = build_d_class_factor_bundle(O=O, H=H, L=L, C=C)
        if "macd" in selected_bundle_set:
            _add("macd", output)
        else:
            _merge_bundle_output(output, shared_factor_dfs, shared_factor_name_map)

    if _need("kdj", "total_buy_signal", "tdx_bottom_alert", "total_sell_pair_test", "sell_factor_volume"):
        output = build_kdj_factor_bundle(O=O, H=H, L=L, C=C)
        if "kdj" in selected_bundle_set:
            _add("kdj", output)
        else:
            _merge_bundle_output(output, shared_factor_dfs, shared_factor_name_map)

    if _need("bottom_fishing", "total_buy_signal", "tdx_bottom_alert", "total_sell_pair_test", "sell_factor_volume"):
        cache_key = ("bottom_fishing", id(O), id(H), id(L), id(C), len(O.index), len(O.columns))
        if enable_bottom_cache and cache_key in bundle_cache:
            output = bundle_cache[cache_key]
        else:
            output = build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C)
            if enable_bottom_cache:
                bundle_cache[cache_key] = output
        if "bottom_fishing" in selected_bundle_set:
            _add("bottom_fishing", output)
        else:
            _merge_bundle_output(output, shared_factor_dfs, shared_factor_name_map)

    if _need("rsi", "total_sell_pair_test"):
        output = build_rsi_factor_bundle(C=C)
        if "rsi" in selected_bundle_set:
            _add("rsi", output)
        else:
            _merge_bundle_output(output, shared_factor_dfs, shared_factor_name_map)

    if _need("total_sell_signal", "total_sell_pair_test"):
        output = build_total_sell_signal_bundle(C=C)
        if "total_sell_signal" in selected_bundle_set:
            _add("total_sell_signal", output)
        else:
            _merge_bundle_output(output, shared_factor_dfs, shared_factor_name_map)

    if _need("moving_average", "tdx_bottom_alert", "total_sell_pair_test"):
        output = build_moving_average_factor_bundle(C=C, windows=(5, 10, 15, 20, 30, 40, 50, 60, 70, 120))
        if "moving_average" in selected_bundle_set:
            _add("moving_average", output)
        else:
            _merge_bundle_output(output, shared_factor_dfs, shared_factor_name_map)

    if _need("chip_structure", "total_buy_signal", "tdx_bottom_alert"):
        output = build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)
        if "chip_structure" in selected_bundle_set:
            _add("chip_structure", output)
        else:
            _merge_bundle_output(output, shared_factor_dfs, shared_factor_name_map)

    if "hong_bottom_fishing" in selected_bundle_set:
        _add("hong_bottom_fishing", build_hong_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C))
    if "obv" in selected_bundle_set:
        _add("obv", build_obv_factor_bundle(C=C, V=V))
    if "donchian_lower" in selected_bundle_set:
        _add("donchian_lower", build_donchian_lower_channel_factor_bundle(C=C, n=10))
    if "dynamic_volatility_channel" in selected_bundle_set:
        _add("dynamic_volatility_channel", build_dynamic_volatility_channel_factor_bundle(H=H, L=L, C=C, high_window=20, atr_window=14, atr_multiplier=1.5))
    if "new_hl_ratio" in selected_bundle_set:
        _add("new_hl_ratio", build_new_hl_ratio_factor_bundle(C=C, window=20))
    if "boll_strategy" in selected_bundle_set:
        _add("boll_strategy", build_boll_strategy_factor_bundle(C=C, window=20, k=2.0))
    if "macd_sell" in selected_bundle_set:
        _add("macd_sell", build_macd_sell_factor_bundle(O=O, H=H, L=L, C=C))
    if "volume_drop" in selected_bundle_set:
        _add("volume_drop", build_volume_drop_factor_bundle(C=C, V=V, volume_window=20))
    if "momentum_common" in selected_bundle_set:
        _add("momentum_common", build_momentum_factor_bundle(C=C))
    if "low_volatility" in selected_bundle_set:
        _add("low_volatility", build_low_volatility_factor_bundle(C=C, H=H, L=L, V=V))

    if "total_buy_signal" in selected_bundle_set:
        _add("total_buy_signal", build_total_buy_signal_bundle(O=O, H=H, L=L, C=C, V=V, precomputed_factors=shared_factor_dfs))
    if "total_sell_pair_test" in selected_bundle_set:
        _add("total_sell_pair_test", build_total_sell_pair_test_bundle(O=O, H=H, L=L, C=C, V=V, precomputed_factors=shared_factor_dfs))
    if "sell_factor_volume" in selected_bundle_set:
        _add("sell_factor_volume", build_sell_factor_volume_bundle(O=O, H=H, L=L, C=C, V=V, precomputed_factors=shared_factor_dfs))
    if "tdx_bottom_alert" in selected_bundle_set:
        _add("tdx_bottom_alert", build_tdx_bottom_alert_bundle(O=O, H=H, L=L, C=C, V=V, valid_bar=valid_bar if valid_bar is not None else C.notna(), precomputed_factors=shared_factor_dfs))

    return selected_bundle_set, bundle_outputs


def _momentum_compute_paths(requested_factor_keys: set[str]) -> tuple[bool, bool]:
    known_market_keys = SECTOR_MARKET_FACTOR_KEYS | SECTOR_ONLY_MARKET_FACTOR_KEYS
    known_factor_keys = known_market_keys | THS_ONLY_FACTOR_KEYS
    unknown_targets = requested_factor_keys - known_factor_keys
    compute_market_path = (
        not requested_factor_keys
        or bool(requested_factor_keys & known_market_keys)
        or bool(unknown_targets)
    )
    compute_aggregate_path = (
        not requested_factor_keys
        or bool(requested_factor_keys & THS_ONLY_FACTOR_KEYS)
        or bool(unknown_targets)
    )
    return compute_market_path, compute_aggregate_path


def compute_selected_bundles(
    O,
    H,
    L,
    C,
    V,
    selected_bundles,
    T=None,
    enable_bottom_cache=True,
    valid_bar=None,
    target_factor_keys=None,
    unadjusted_close=None,
):
    if valid_bar is None:
        valid_bar = globals().get("VALID_BAR", C.notna())
    requested_bundles = [str(item).strip().lower() for item in selected_bundles]
    direct_bundles = {
        "momentum_common",
        "low_volatility",
        "liquidity",
        "stock_market_data",
        "stock_fundamental_raw",
        "stock_growth_raw",
        "stock_dividend_raw",
        "pure_technical",
    }
    shared_bundles = [item for item in requested_bundles if item not in direct_bundles]
    if shared_bundles:
        selected_bundle_set, bundle_outputs = compute_bundles_with_valid_bar(
            _compute_selected_bundles_raw,
            O=O,
            H=H,
            L=L,
            C=C,
            V=V,
            selected_bundles=shared_bundles,
            T=T,
            valid_bar=valid_bar,
            enable_bottom_cache=enable_bottom_cache,
        )
    else:
        selected_bundle_set, bundle_outputs = set(), []

    if "pure_technical" in requested_bundles:
        selected_bundle_set.add("pure_technical")
        requested_factor_keys = {
            str(item).strip()
            for item in (target_factor_keys or [])
            if str(item).strip()
        }
        bundle_outputs.extend(
            iter_pure_technical_factor_bundles(
                O=O,
                H=H,
                L=L,
                C=C,
                V=V,
                valid_bar=valid_bar,
                selected_factors=requested_factor_keys or None,
            )
        )

    if "stock_market_data" in requested_bundles:
        selected_bundle_set.add("stock_market_data")
        known_stock_codes = {
            str(code).strip().upper()
            for code in globals().get("_stock_source_code_set", set())
            if str(code).strip()
        }
        batch_stock_codes = {
            str(code).strip().upper()
            for code in C.columns
            if str(code).strip().upper() in known_stock_codes
        }
        bundle_outputs.append(
            build_stock_market_data_factor_bundle(
                C=C,
                stock_codes=batch_stock_codes,
            )
        )

    if "liquidity" in requested_bundles:
        selected_bundle_set.add("liquidity")
        known_stock_codes = {
            str(code).strip().upper()
            for code in globals().get("_stock_source_code_set", set())
            if str(code).strip()
        }
        batch_stock_codes = {
            str(code).strip().upper()
            for code in C.columns
            if str(code).strip().upper() in known_stock_codes
        }
        bundle_outputs.append(
            build_liquidity_factor_bundle(
                C=C,
                stock_codes=batch_stock_codes,
            )
        )

    if "low_volatility" in requested_bundles:
        known_stock_codes = {
            str(code).strip().upper()
            for code in globals().get("_stock_source_code_set", set())
            if str(code).strip()
        }
        batch_stock_codes = {
            str(code).strip().upper()
            for code in C.columns
            if str(code).strip().upper() in known_stock_codes
        }
        stock_columns = [code for code in C.columns if str(code).strip().upper() in batch_stock_codes]
        stock_valid_bar = (
            valid_bar.loc[:, stock_columns].astype(bool)
            & V.loc[:, stock_columns].gt(0.0)
        )
        low_vol_selected, low_vol_outputs = compute_bundles_with_valid_bar(
            _compute_selected_bundles_raw,
            O=O.loc[:, stock_columns],
            H=H.loc[:, stock_columns],
            L=L.loc[:, stock_columns],
            C=C.loc[:, stock_columns],
            V=V.loc[:, stock_columns],
            selected_bundles=["low_volatility"],
            T=None,
            valid_bar=stock_valid_bar,
            enable_bottom_cache=False,
        )
        selected_bundle_set.update(low_vol_selected)
        bundle_outputs.extend(low_vol_outputs)

    if "stock_fundamental_raw" in requested_bundles:
        selected_bundle_set.add("stock_fundamental_raw")
        known_stock_codes = {
            str(code).strip().upper()
            for code in globals().get("_stock_source_code_set", set())
            if str(code).strip()
        }
        batch_stock_codes = {
            str(code).strip().upper()
            for code in C.columns
            if str(code).strip().upper() in known_stock_codes
        }
        bundle_outputs.append(
            build_stock_fundamental_raw_factor_bundle(
                C=C,
                stock_codes=batch_stock_codes,
                target_factor_keys=target_factor_keys,
            )
        )

    if "stock_growth_raw" in requested_bundles:
        selected_bundle_set.add("stock_growth_raw")
        known_stock_codes = {
            str(code).strip().upper()
            for code in globals().get("_stock_source_code_set", set())
            if str(code).strip()
        }
        batch_stock_codes = {
            str(code).strip().upper()
            for code in C.columns
            if str(code).strip().upper() in known_stock_codes
        }
        bundle_outputs.append(
            build_stock_growth_raw_factor_bundle(
                C=C,
                stock_codes=batch_stock_codes,
                target_factor_keys=target_factor_keys,
            )
        )

    if "stock_dividend_raw" in requested_bundles:
        selected_bundle_set.add("stock_dividend_raw")
        known_stock_codes = {
            str(code).strip().upper()
            for code in globals().get("_stock_source_code_set", set())
            if str(code).strip()
        }
        batch_stock_codes = {
            str(code).strip().upper()
            for code in C.columns
            if str(code).strip().upper() in known_stock_codes
        }
        bundle_outputs.append(
            build_stock_dividend_raw_factor_bundle(
                C=C,
                unadjusted_close=unadjusted_close,
                stock_codes=batch_stock_codes,
            )
        )

    if "momentum_common" in requested_bundles:
        selected_bundle_set.add("momentum_common")
        requested_factor_keys = {
            str(item).strip()
            for item in (target_factor_keys or [])
            if str(item).strip()
        }
        compute_market_path, compute_aggregate_path = _momentum_compute_paths(
            requested_factor_keys
        )
        momentum_output = {
            "bundle_id": "momentum_common",
            "factor_dfs": {},
            "factor_name_map": {},
        }

        if compute_market_path:
            market_columns = C.columns
            if len(market_columns) > 0:
                market_valid_bar = valid_bar.reindex(index=C.index, columns=market_columns).fillna(False)
                _, market_outputs = compute_bundles_with_valid_bar(
                    _compute_selected_bundles_raw,
                    O=O.loc[:, market_columns],
                    H=H.loc[:, market_columns],
                    L=L.loc[:, market_columns],
                    C=C.loc[:, market_columns],
                    V=V.loc[:, market_columns],
                    selected_bundles=["momentum_common"],
                    T=None,
                    valid_bar=market_valid_bar,
                    enable_bottom_cache=False,
                )
                market_output = next(
                    (output for output in market_outputs if output.get("bundle_id") == "momentum_common"),
                    None,
                )
                if market_output is not None:
                    _merge_bundle_output(
                        market_output,
                        momentum_output["factor_dfs"],
                        momentum_output["factor_name_map"],
                    )

        if compute_aggregate_path:
            aggregate_output = build_industry_factor_bundle(
                dates=C.index,
                stock_codes=C.columns,
                valid_bar=valid_bar,
                target_factor_keys=requested_factor_keys,
            )
            _merge_bundle_output(
                aggregate_output,
                momentum_output["factor_dfs"],
                momentum_output["factor_name_map"],
            )
        bundle_outputs.append(momentum_output)

    return selected_bundle_set, bundle_outputs

# %% cell 17
# bundle_outputs

# %% [markdown] cell 18
# # 得到因子

# %% cell 19
from factor_debug_log import factor_log
from time import perf_counter

bundle_factor_catalog = dict(globals().get("PREQUERY_BUNDLE_FACTOR_CATALOG", {}))
factor_plan_df = globals().get("PREQUERY_PLAN_DF", pd.DataFrame())
factor_plan_df = factor_plan_df.copy() if isinstance(factor_plan_df, pd.DataFrame) else pd.DataFrame()
auto_target_keys = {str(x).strip() for x in globals().get("PREQUERY_TARGET_FACTOR_KEYS", set()) if str(x).strip()}
selected_bundles_for_compute = [str(x).strip().lower() for x in globals().get("PREQUERY_SELECTED_BUNDLES", SELECTED_BUNDLES)]

PLANNED_FACTOR_TIME_RANGES: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
if not factor_plan_df.empty:
    need_compute_df = factor_plan_df[factor_plan_df["status"].isin(["missing", "stale"])].copy()
    if not need_compute_df.empty:
        PLANNED_FACTOR_TIME_RANGES = {
            str(row["factor_en"]): (pd.Timestamp(row["plan_start"]).floor("D"), pd.Timestamp(row["plan_end"]).floor("D"))
            for _, row in need_compute_df.iterrows()
        }

active_target_keys = set(auto_target_keys)
if not active_target_keys:
    manual_target_set = {str(x).strip() for x in (TARGET_FACTORS or []) if str(x).strip()}
    if manual_target_set:
        active_target_keys.update(manual_target_set)

selected_bundle_set = set(selected_bundles_for_compute)
factor_dfs = {}
factor_name_map = {}
_source_rows = int(len(EXECUTION_MARKET_LONG))
_source_code_level = EXECUTION_MARKET_LONG.index.levels[
    EXECUTION_MARKET_LONG.index.names.index("htsc_code")
]
_source_time_level = EXECUTION_MARKET_LONG.index.levels[
    EXECUTION_MARKET_LONG.index.names.index("time")
]
_source_cols = int(len(_source_code_level))

factor_log(
    "factor_cell.start",
    selected_bundles=selected_bundles_for_compute,
    active_targets=sorted(active_target_keys),
    planned_ranges=len(PLANNED_FACTOR_TIME_RANGES),
    rows=_source_rows,
    cols=_source_cols,
    start=str(pd.Timestamp(_source_time_level.min()).date()) if len(_source_time_level) else None,
    end=str(pd.Timestamp(_source_time_level.max()).date()) if len(_source_time_level) else None,
)


def _bundle_targets(bundle_key: str) -> set[str]:
    bundle_factor_map = bundle_factor_catalog.get(bundle_key, {})
    return {
        str(eng).strip()
        for _, eng in bundle_factor_map.items()
        if (not active_target_keys) or (str(eng).strip() in active_target_keys)
    }


compute_bundles = []
for _bundle in selected_bundles_for_compute:
    _bundle = str(_bundle).strip().lower()
    if _bundle in POST_WRITE_DERIVED_BUNDLES:
        factor_log("bundle.defer", bundle=_bundle, reason="post_write_derived", sec=0.0)
        continue
    _mapping = bundle_factor_catalog.get(_bundle, {})
    if active_target_keys and _mapping and not _bundle_targets(_bundle):
        factor_log("bundle.skip", bundle=_bundle, reason="no_target_intersection", sec=0.0)
        continue
    compute_bundles.append(_bundle)

if compute_bundles:
    execution_plans = [
        plan
        for plan in globals().get("PREQUERY_EXECUTION_PLANS", [])
        if str(plan.get("bundle", "")).strip().lower() in compute_bundles
    ]
    if not execution_plans:
        _fallback_codes = sorted(str(code) for code in _source_code_level)
        execution_plans = [
            {
                "bundle": bundle,
                "scope": "legacy_market",
                "target_keys": sorted(_bundle_targets(bundle)),
                "codes": _fallback_codes,
                "query_start": pd.Timestamp(QUERY_START_DATE).floor("D"),
                "plan_start": pd.Timestamp(globals().get("EFFECTIVE_START_DATE", START_DATE)).floor("D"),
                "plan_end": pd.Timestamp(END_DATE).floor("D"),
            }
            for bundle in compute_bundles
        ]

    execution_batches = _group_execution_plans_for_compute(execution_plans)
    _all_start = perf_counter()
    for _plan_idx, _execution_plan in enumerate(execution_batches, start=1):
        _bundles = [
            str(bundle).strip().lower()
            for bundle in _execution_plan.get("bundles", [])
            if str(bundle).strip().lower() in compute_bundles
        ]
        _bundle_label = "+".join(_bundles)
        _scope = str(_execution_plan.get("scope", "market")).strip()
        _targets = {
            str(key).strip()
            for key in _execution_plan.get("target_keys", [])
            if str(key).strip()
        }
        if active_target_keys:
            _targets &= active_target_keys
        if not _bundles or not _targets:
            factor_log("bundle.skip", bundle=_bundle_label, scope=_scope, reason="no_target_intersection", sec=0.0)
            continue

        _compute_start = pd.Timestamp(_execution_plan["query_start"]).floor("D")
        _compute_end = pd.Timestamp(_execution_plan["plan_end"]).floor("D")
        _target_display_by_key: dict[str, str] = {}
        for _bundle in _bundles:
            for _ch_name, _eng_name in bundle_factor_catalog.get(_bundle, {}).items():
                _eng_key = str(_eng_name).strip()
                if _eng_key in _targets and _eng_key not in _target_display_by_key:
                    _target_display_by_key[_eng_key] = str(_ch_name).strip() or _eng_key
        _target_display_names = [
            _target_display_by_key.get(_target_key, _target_key)
            for _target_key in sorted(_targets)
        ]
        for _progress_line in _format_execution_plan_lines(
            plan_idx=_plan_idx,
            plan_total=len(execution_batches),
            bundle_label=_bundle_label,
            scope=_scope,
            target_keys=_target_display_names,
            code_count=len(_execution_plan.get("codes", [])),
            query_start=_compute_start,
            plan_start=pd.Timestamp(_execution_plan["plan_start"]).floor("D"),
            plan_end=_compute_end,
        ):
            print(_progress_line)
        _market_frames = _build_execution_plan_market_frames(
            EXECUTION_MARKET_LONG,
            codes=_execution_plan.get("codes", []),
            query_start=_compute_start,
            plan_end=_compute_end,
        )
        if _market_frames is None:
            factor_log("bundle.skip", bundle=_bundle_label, scope=_scope, reason="no_input_data", sec=0.0)
            continue

        _local_O = _market_frames["O"]
        _local_H = _market_frames["H"]
        _local_L = _market_frames["L"]
        _local_C = _market_frames["C"]
        _local_C_unadjusted = _market_frames["C_UNADJUSTED"]
        _local_V = _market_frames["V"]
        _local_valid_bar = _market_frames["valid_bar"]
        _turnover_bundles = {"chip_structure", "total_buy_signal", "tdx_bottom_alert"}
        _local_T = (
            load_turnover_wide(_local_C.index, _local_C.columns, base_dir=TURNOVER_BASE_PATH)
            if bool(set(_bundles) & _turnover_bundles)
            else None
        )

        factor_log(
            "bundle.window",
            bundle=_bundle_label,
            scope=_scope,
            start=str(_compute_start.date()),
            write_start=str(pd.Timestamp(_execution_plan["plan_start"]).date()),
            end=str(_compute_end.date()),
            rows=int(len(_local_C.index)),
            cols=int(len(_local_C.columns)),
            targets=sorted(_targets),
        )
        _task_start = perf_counter()
        factor_log("bundle.start", bundle=_bundle_label, scope=_scope, selected_bundles=_bundles)
        _, _outputs = compute_selected_bundles(
            O=_local_O,
            H=_local_H,
            L=_local_L,
            C=_local_C,
            V=_local_V,
            T=_local_T,
            selected_bundles=_bundles,
            enable_bottom_cache=False,
            valid_bar=_local_valid_bar,
            target_factor_keys=_targets,
            unadjusted_close=_local_C_unadjusted,
        )

        _batch_generated_keys: set[str] = set()
        for output in _outputs:
            _dfs = output.get("factor_dfs", {})
            _map = output.get("factor_name_map", {})
            for _ch, _eng in _map.items():
                _eng_key = str(_eng).strip()
                if _eng_key not in _targets or _eng_key not in _dfs:
                    continue
                _batch_generated_keys.add(_eng_key)
                _new_frame = _dfs[_eng_key]
                if _eng_key in factor_dfs:
                    factor_dfs[_eng_key] = factor_dfs[_eng_key].combine_first(_new_frame)
                else:
                    factor_dfs[_eng_key] = _new_frame
                factor_name_map[_ch] = _eng_key

        _task_sec = perf_counter() - _task_start
        factor_log(
            "bundle.finish",
            bundle=_bundle_label,
            scope=_scope,
            sec=round(float(_task_sec), 3),
            factors=len(factor_dfs),
            mapped_names=len(factor_name_map),
        )
        print(
            _format_batch_finish_line(
                plan_idx=_plan_idx,
                plan_total=len(execution_batches),
                bundle_label=_bundle_label,
                scope=_scope,
                factor_count=len(_batch_generated_keys),
                elapsed_seconds=_task_sec,
            )
        )
        del _outputs, _market_frames, _local_O, _local_H, _local_L, _local_C, _local_C_unadjusted, _local_V, _local_valid_bar, _local_T
        gc.collect()

    _sec = perf_counter() - _all_start
    print(
        f"[计算汇总] 批次={len(execution_batches)}，生成因子={len(factor_dfs)}，"
        f"耗时={_sec:.2f}秒"
    )
else:
    factor_log("factor_cell.noop", reason="no_bundle_needs_compute")

del EXECUTION_MARKET_LONG
gc.collect()

# 过滤到真正需要的因子（自动计划优先；否则使用手动 TARGET_FACTORS）。
active_target_keys = set(auto_target_keys)
if not active_target_keys:
    manual_target_set = {str(x).strip() for x in (TARGET_FACTORS or []) if str(x).strip()}
    if manual_target_set:
        active_target_keys.update(manual_target_set)
        for ch_name, eng_name in factor_name_map.items():
            if str(ch_name).strip() in manual_target_set:
                active_target_keys.add(str(eng_name).strip())

if active_target_keys:
    factor_dfs = {k: v for k, v in factor_dfs.items() if str(k).strip() in active_target_keys}
    factor_name_map = {
        ch_name: eng_name
        for ch_name, eng_name in factor_name_map.items()
        if str(eng_name).strip() in active_target_keys or str(ch_name).strip() in active_target_keys
    }

EFFECTIVE_START_DATE = START_DATE
if PLANNED_FACTOR_TIME_RANGES:
    EFFECTIVE_START_DATE = min(x[0] for x in PLANNED_FACTOR_TIME_RANGES.values()).strftime("%Y-%m-%d")

if "mac_total" in factor_dfs:
    mac_total = factor_dfs["mac_total"]
if "r_condition" in factor_dfs:
    kdj_signal = factor_dfs["r_condition"]
if "bottom_fishing_score" in factor_dfs:
    bottom_fishing_score = factor_dfs["bottom_fishing_score"]
if "rsi_total_score" in factor_dfs:
    rsi_total_score = factor_dfs["rsi_total_score"]

print(f"本次实际执行 bundle: {sorted(selected_bundle_set)}")
print(f"计划后因子数量: {len(factor_dfs)}")
print(f"计划写入起点: {EFFECTIVE_START_DATE}")
if not factor_plan_df.empty:
    print("因子库体检概览:")
    display(factor_plan_df[["factor_cn", "factor_en", "status", "last_dt", "plan_start", "plan_end", "reason"]].head(30))

factor_dfs

# %% [markdown] cell 20
# # 生成因子矩阵

# %% cell 21
# ==========================================
# 将因子矩阵按股票合并成宽表（仅保留目标写入区间）
# 自动模式：仅保留“目标区间里缺失信号”的行（按缺失检测补写）
# 宽表结构：index=time, columns=中文因子名, values=因子值
# ==========================================
import os
from typing import Optional 

import duckdb
import numpy as np
import pandas as pd

OUTPUT_BASE_DIR = r"D:\database\signal_daily"

write_start_ts = pd.Timestamp(globals().get("EFFECTIVE_START_DATE", START_DATE))
write_end_ts = pd.Timestamp(END_DATE)

# 新存储方式直接从 factor_dfs 写入 factor=中文因子名/year/month 长表，
# 这里保留 stock_factor_tables 变量兼容后续临时查看，但跳过旧的逐股票宽表组装。
all_stocks = []
stock_factor_tables = {}
print("新存储方式已启用：跳过旧的按股票宽表组装，保存阶段将直接从 factor_dfs 写入。")

# 预先裁剪有效因子映射，减少逐股票重复查表开销。
usable_factor_items = [
    (ch_name, factor_dfs[eng_name])
    for ch_name, eng_name in factor_name_map.items()
    if eng_name in factor_dfs
]

for stock in all_stocks:
    stock_data = {}
    for ch_name, factor_df in usable_factor_items:
        if stock in factor_df.columns:
            stock_data[ch_name] = factor_df[stock]
    if not stock_data:
        continue

    stock_df = pd.DataFrame(stock_data)
    stock_df.index = pd.to_datetime(stock_df.index).floor("D")
    stock_df = stock_df.loc[(stock_df.index >= write_start_ts) & (stock_df.index <= write_end_ts)]
    if stock_df.empty:
        continue
    stock_factor_tables[stock] = stock_df


def _iter_year_month(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> list[tuple[int, int]]:
    cursor = pd.Timestamp(year=start_dt.year, month=start_dt.month, day=1)
    end_cursor = pd.Timestamp(year=end_dt.year, month=end_dt.month, day=1)
    result: list[tuple[int, int]] = []
    while cursor <= end_cursor:
        result.append((int(cursor.year), int(cursor.month)))
        cursor = cursor + pd.offsets.MonthBegin(1)
    return result


def _collect_existing_partition_paths(base_dir: str, start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> list[str]:
    paths: list[str] = []
    for year, month in _iter_year_month(start_dt, end_dt):
        p = os.path.join(base_dir, f"year={year}", f"month={month:02d}", "merged.parquet")
        if os.path.exists(p):
            paths.append(p.replace("\\", "/"))
    return paths


def _build_target_pairs(factor_tables_dict: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pair_frames: list[pd.DataFrame] = []
    for code, df in factor_tables_dict.items():
        idx = pd.to_datetime(df.index).floor("D")
        if len(idx) == 0:
            continue
        pair_frames.append(pd.DataFrame({"htsc_code": str(code), "time": idx}))

    if not pair_frames:
        return pd.DataFrame(columns=["htsc_code", "time"])

    out = pd.concat(pair_frames, ignore_index=True)
    out = out.drop_duplicates(subset=["htsc_code", "time"], keep="last")
    return out


def _load_existing_complete_pairs(
    base_dir: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    required_cols: list[str],
    target_codes: Optional[list[str]] = None,
) -> pd.DataFrame:
    paths = _collect_existing_partition_paths(base_dir, start_dt, end_dt)
    if not paths:
        return pd.DataFrame(columns=["time", "htsc_code"])

    placeholders = ", ".join(["?"] * len(paths))

    def _quote_ident(col: str) -> str:
        return '"' + str(col).replace('"', '""') + '"'

    conn = duckdb.connect(database=":memory:")
    try:
        schema_sql = f"DESCRIBE SELECT * FROM read_parquet([{placeholders}], union_by_name = true)"
        schema_df = conn.execute(schema_sql, paths).df()
        available_cols = set(schema_df["column_name"].astype(str)) if not schema_df.empty else set()

        if not {"time", "htsc_code"}.issubset(available_cols):
            return pd.DataFrame(columns=["time", "htsc_code"])

        selected_required_cols = [col for col in required_cols if col in available_cols]
        if len(selected_required_cols) < len(required_cols):
            return pd.DataFrame(columns=["time", "htsc_code"])

        nn_expr = " + ".join(
            [f"CASE WHEN {_quote_ident(col)} IS NOT NULL THEN 1 ELSE 0 END" for col in selected_required_cols]
        )
        sql = (
            f"SELECT {_quote_ident('time')} AS time, {_quote_ident('htsc_code')} AS htsc_code, "
            f"({nn_expr}) AS nn_cnt "
            f"FROM read_parquet([{placeholders}], union_by_name = true)"
        )
        old_df = conn.execute(sql, paths).df()
    finally:
        conn.close()

    if old_df.empty:
        return pd.DataFrame(columns=["time", "htsc_code"])

    old_df["time"] = pd.to_datetime(old_df["time"]).dt.floor("D")
    old_df["htsc_code"] = old_df["htsc_code"].astype(str).str.strip()
    old_df = old_df[(old_df["time"] >= start_dt) & (old_df["time"] <= end_dt)]

    if target_codes:
        code_set = {str(code).strip().upper() for code in target_codes if str(code).strip()}
        old_df = old_df[old_df["htsc_code"].str.upper().isin(code_set)]

    old_df = old_df[old_df["nn_cnt"] >= len(required_cols)]
    if old_df.empty:
        return pd.DataFrame(columns=["time", "htsc_code"])

    out = old_df[["time", "htsc_code"]].sort_values(["time", "htsc_code"])
    out = out.drop_duplicates(subset=["time", "htsc_code"], keep="last")
    return out


def _filter_factor_tables_by_pairs(
    factor_tables_dict: dict[str, pd.DataFrame],
    allowed_pairs: set[tuple[str, pd.Timestamp]],
) -> dict[str, pd.DataFrame]:
    allowed_by_code: dict[str, set[pd.Timestamp]] = {}
    for code, ts in allowed_pairs:
        allowed_by_code.setdefault(str(code), set()).add(pd.Timestamp(ts))

    filtered: dict[str, pd.DataFrame] = {}
    for code, df in factor_tables_dict.items():
        code_key = str(code)
        allowed_times = allowed_by_code.get(code_key)
        if not allowed_times:
            continue
        idx = pd.to_datetime(df.index).floor("D")
        keep_mask = idx.isin(allowed_times)
        sliced = df.loc[keep_mask]
        if not sliced.empty:
            filtered[code] = sliced
    return filtered


required_factor_columns = sorted({col for df in stock_factor_tables.values() for col in df.columns})

# auto / incremental 下不再做全历史 pair 扫描：
# 保存阶段会按因子 last_dt + 1 只补尾部；若因子库没有历史，则视为整段缺失。
if RUN_MODE.lower() in {"auto", "incremental"} and stock_factor_tables and required_factor_columns:
    print("自动模式启用：跳过全历史 pair 缺失扫描，保存阶段将按因子 last_dt 只补尾部。")

print(f"目标写入区间: {START_DATE} ~ {END_DATE}")
print(f"可写入股票数量: {len(stock_factor_tables)}")

if stock_factor_tables:
    example_stock = next(iter(stock_factor_tables.keys()))
    print(f"股票 {example_stock} 的因子宽表预览：")
    display(stock_factor_tables[example_stock].head())
else:
    print("当前批次没有需要补写的缺失因子。")

# %% cell 22
stock_factor_tables

# dtype 统一转换下沉至写盘（Polars）阶段执行，避免在这里逐股票逐列重复转换。

# %% cell 23


# stock_factor_tables['000001.SZ']['抄底总分']

# %% [markdown] cell 24
# # 本地历史信号保存

# %% cell 25
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 将所有股票的因子宽表合并，并按 year/month 分区保存为 Parquet
# 增量模式下：旧值优先，仅在旧值为空时用新值补齐
# ==========================================
import os
import shutil
import uuid
from typing import Any
import polars as pl
from pathlib import Path

OUTPUT_BASE_DIR = r"D:\database\signal_daily"


def _align_polars_schema(df: pl.DataFrame, columns_order: list[str]) -> pl.DataFrame:
    aligned = df
    for col in columns_order:
        if col not in aligned.columns:
            aligned = aligned.with_columns(pl.lit(None).alias(col))
    return aligned.select(columns_order)


def _merge_preserve_old_values(old_df: pl.DataFrame, new_df: pl.DataFrame) -> pl.DataFrame:
    key_cols = ["time", "htsc_code"]
    all_cols = list(dict.fromkeys([*old_df.columns, *new_df.columns]))
    value_cols = [c for c in all_cols if c not in key_cols]

    old_aligned = (
        _align_polars_schema(old_df, all_cols)
        .sort(key_cols)
        .unique(subset=key_cols, keep="last")
        .with_columns(pl.lit(0).alias("__prio"))
    )
    new_aligned = (
        _align_polars_schema(new_df, all_cols)
        .sort(key_cols)
        .unique(subset=key_cols, keep="last")
        .with_columns(pl.lit(1).alias("__prio"))
    )

    # 关键语义：保留旧值，仅用新值填补旧值空缺，同时补入新增键
    combined = pl.concat([old_aligned, new_aligned], how="vertical_relaxed")
    agg_exprs = [pl.col(c).drop_nulls().first().alias(c) for c in value_cols]

    merged = (
        combined
        .sort([*key_cols, "__prio"])
        .group_by(key_cols, maintain_order=True)
        .agg(agg_exprs)
        .select(all_cols)
        .sort(key_cols)
    )
    return merged


def _cast_value_columns_to_float32(df: pl.DataFrame) -> pl.DataFrame:
    key_cols = {"time", "htsc_code", "year", "month"}
    cast_exprs: list[pl.Expr] = []
    for col_name, col_dtype in df.schema.items():
        if col_name in key_cols:
            continue
        if col_dtype in (
            pl.Float32,
            pl.Float64,
            pl.Int8,
            pl.Int16,
            pl.Int32,
            pl.Int64,
            pl.UInt8,
            pl.UInt16,
            pl.UInt32,
            pl.UInt64,
            pl.Boolean,
        ) and col_dtype != pl.Float32:
            cast_exprs.append(pl.col(col_name).cast(pl.Float32).alias(col_name))
    return df.with_columns(cast_exprs) if cast_exprs else df


def _cleanup_tmp_file(tmp_path: str) -> None:
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _write_parquet_atomic_with_retry(
    df: pl.DataFrame,
    file_path: str,
    *,
    compression: str = "snappy",
    max_retries: int = 60,
    sleep_seconds: float = 1.0,
) -> None:
    """先写临时文件，再重试替换正式文件，降低 Windows 文件锁影响。"""
    dir_path = os.path.dirname(file_path)
    os.makedirs(dir_path, exist_ok=True)
    tmp_dir = os.path.join(dir_path, ".__tmp_writes__")
    os.makedirs(tmp_dir, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        tmp_path = os.path.join(
            tmp_dir,
            f"tmp_{os.getpid()}_{int(time.time() * 1000)}_{uuid.uuid4().hex}.bin",
        )
        try:
            df.write_parquet(tmp_path, compression=compression)
            os.replace(tmp_path, file_path)
            return
        except OSError as exc:
            last_error = exc
            _cleanup_tmp_file(tmp_path)
            if attempt == 1 or attempt % 5 == 0:
                print(f"临时写入或替换被占用，等待后重试: {file_path} ({attempt}/{max_retries})")
            time.sleep(sleep_seconds)

    raise OSError(f"写入 parquet 失败，文件可能被系统/杀软/其他程序持续占用: {file_path}") from last_error


def _move_corrupt_parquet(file_path: str, reason: str) -> None:
    corrupt_path = f"{file_path}.corrupt.{int(time.time())}"
    print(f"[WARN] 分区文件不可读，跳过旧文件并备份: {file_path} -> {corrupt_path}，原因: {reason}")
    try:
        os.replace(file_path, corrupt_path)
    except OSError as exc:
        print(f"[WARN] 备份损坏文件失败，可能仍被占用: {exc}")


def _read_existing_partition(file_path: str) -> pl.DataFrame | None:
    if not os.path.exists(file_path):
        return None

    try:
        if os.path.getsize(file_path) < 12:
            _move_corrupt_parquet(file_path, "文件小于 12 字节")
            return None
        return pl.read_parquet(file_path).with_columns([
            pl.col("time").cast(pl.Datetime),
            pl.col("htsc_code").cast(pl.Utf8),
        ])
    except Exception as exc:
        _move_corrupt_parquet(file_path, repr(exc))
        return None


def _write_staging_partition(
    staging_dir: str,
    year: int,
    month: int,
    buffered_frames: list[pl.DataFrame],
    part_no: int,
) -> int:
    if not buffered_frames:
        return 0

    part_dir = os.path.join(staging_dir, f"year={int(year)}", f"month={int(month):02d}")
    os.makedirs(part_dir, exist_ok=True)
    part_path = os.path.join(part_dir, f"part_{part_no:05d}_{uuid.uuid4().hex}.parquet")

    new_df = (
        pl.concat(buffered_frames, how="vertical_relaxed", rechunk=True)
        .sort(["time", "htsc_code"])
        .unique(subset=["time", "htsc_code"], keep="last")
        .sort(["time", "htsc_code"])
    )
    _write_parquet_atomic_with_retry(new_df, part_path, compression="snappy")
    return len(new_df)


def _compact_month_partition(
    base_dir: str,
    staging_dir: str,
    year: int,
    month: int,
) -> None:
    final_dir = os.path.join(base_dir, f"year={int(year)}", f"month={int(month):02d}")
    final_path = os.path.join(final_dir, "merged.parquet")
    staging_month_dir = os.path.join(staging_dir, f"year={int(year)}", f"month={int(month):02d}")

    part_paths = sorted(Path(staging_month_dir).glob("part_*.parquet"))
    if not part_paths:
        return

    new_frames = [pl.read_parquet(str(path)) for path in part_paths if path.stat().st_size >= 12]
    if not new_frames:
        print(f"[WARN] {year}-{month:02d} 没有可合并的 staging 文件，跳过")
        return

    new_df = (
        pl.concat(new_frames, how="vertical_relaxed", rechunk=True)
        .sort(["time", "htsc_code"])
        .unique(subset=["time", "htsc_code"], keep="last")
        .sort(["time", "htsc_code"])
    )

    old_df = _read_existing_partition(final_path)
    if old_df is None:
        save_df = new_df
        print(f"✓ 月度合并新建: {year}-{month:02d} -> {final_path} (新 {len(new_df)})")
    else:
        save_df = _merge_preserve_old_values(old_df, new_df)
        print(
            f"↻ 月度合并写入: {year}-{month:02d} -> {final_path} "
            f"(旧 {len(old_df)} + 新 {len(new_df)} => {len(save_df)})"
        )

    _write_parquet_atomic_with_retry(save_df, final_path, compression="snappy")


def save_factors_to_partitioned_parquet(factor_tables_dict: dict, base_dir: str):
    if not factor_tables_dict:
        print("没有可保存的因子数据。")
        return

    flush_every_codes = 200
    run_id = f"run_{os.getpid()}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    staging_dir = os.path.join(base_dir, "_staging", run_id)
    print(f"开始按股票流式写入 staging，目标路径: {base_dir}")
    print(f"staging 临时目录: {staging_dir}")
    total_codes = len(factor_tables_dict)

    partition_buffers: dict[tuple[int, int], list[pl.DataFrame]] = {}
    touched_partitions: set[tuple[int, int]] = set()
    part_counters: dict[tuple[int, int], int] = {}

    def flush_all_buffers() -> None:
        if not partition_buffers:
            return
        keys = list(partition_buffers.keys())
        for year, month in keys:
            key = (int(year), int(month))
            frames = partition_buffers.pop(key, [])
            part_counters[key] = part_counters.get(key, 0) + 1
            rows = _write_staging_partition(staging_dir, key[0], key[1], frames, part_counters[key])
            if rows:
                touched_partitions.add(key)

    for i, (code, df) in enumerate(factor_tables_dict.items(), start=1):
        temp_df = df.reset_index()
        temp_df["time"] = pd.to_datetime(temp_df["time"]).dt.floor("D")
        temp_df = temp_df.drop_duplicates(subset=["time"], keep="last")
        temp_df.insert(1, "htsc_code", code)

        stock_df = (
            pl.from_pandas(temp_df, include_index=False)
            .with_columns([
                pl.col("time").cast(pl.Datetime).alias("time"),
                pl.col("htsc_code").cast(pl.Utf8).alias("htsc_code"),
            ])
            .pipe(_cast_value_columns_to_float32)
            .with_columns([
                pl.col("time").dt.year().alias("year"),
                pl.col("time").dt.month().alias("month"),
            ])
        )

        partition_map = stock_df.partition_by(["year", "month"], as_dict=True, maintain_order=True)
        for (year, month), partition_df in partition_map.items():
            key = (int(year), int(month))
            new_df = partition_df.drop(["year", "month"]).sort(["time", "htsc_code"])
            partition_buffers.setdefault(key, []).append(new_df)

        if i == 1 or i % 200 == 0 or i == total_codes:
            print(f"处理进度: {i}/{total_codes} ({code})")

        if i % flush_every_codes == 0:
            flush_all_buffers()

    flush_all_buffers()

    touched_list = sorted(touched_partitions)
    if touched_list:
        touched_text = ", ".join([f"{y}-{m:02d}" for y, m in touched_list])
        print(f"本次有增量写入的月份分区: {touched_text}")
        print("开始按月份合并 staging 并替换正式分区...")
        for year, month in touched_list:
            _compact_month_partition(base_dir, staging_dir, year, month)

    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)

    print("\n所有因子数据保存完成（staging + 月度合并模式）！")


# ==========================================
# 新版保存：按中文因子名分区 + 年月分区 + 长表 time/htsc_code/value
# 路径示例：D:\database\signal_daily\factor=顶背离\year=2026\month=05\merged.parquet
# 写入语义：旧值优先，仅用新值补旧值空缺或新增键
# ==========================================
INVALID_FACTOR_PATH_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_factor_dir_name(factor_name: str) -> str:
    safe_name = INVALID_FACTOR_PATH_CHARS.sub("_", str(factor_name).strip())
    safe_name = safe_name.rstrip(" .")
    return safe_name or "未命名因子"


def _month_start_range(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> list[pd.Timestamp]:
    cursor = pd.Timestamp(year=start_dt.year, month=start_dt.month, day=1)
    end_cursor = pd.Timestamp(year=end_dt.year, month=end_dt.month, day=1)
    result: list[pd.Timestamp] = []
    while cursor <= end_cursor:
        result.append(cursor)
        cursor = cursor + pd.offsets.MonthBegin(1)
    return result


def _factor_month_to_long_polars(
    factor_df: pd.DataFrame,
    month_start: pd.Timestamp,
    month_end: pd.Timestamp,
    drop_null_values: bool = False,
) -> pl.DataFrame | None:
    idx = pd.to_datetime(factor_df.index).floor("D")
    keep_mask = (idx >= month_start) & (idx <= month_end)
    if not keep_mask.any():
        return None

    sliced = factor_df.loc[keep_mask].copy()
    if sliced.empty:
        return None

    sliced.index = idx[keep_mask]
    sliced.index.name = "time"
    long_df = (
        sliced.reset_index()
        .melt(id_vars="time", var_name="htsc_code", value_name="value")
        .drop_duplicates(subset=["time", "htsc_code"], keep="last")
    )
    if drop_null_values:
        numeric_values = pd.to_numeric(long_df["value"], errors="coerce")
        long_df = long_df.loc[np.isfinite(numeric_values)].copy()
        long_df["value"] = numeric_values.loc[long_df.index]
    if long_df.empty:
        return None

    return (
        pl.from_pandas(long_df, include_index=False)
        .with_columns([
            pl.col("time").cast(pl.Datetime).alias("time"),
            pl.col("htsc_code").cast(pl.Utf8).alias("htsc_code"),
            pl.col("value").cast(pl.Float32).alias("value"),
        ])
        .sort(["time", "htsc_code"])
    )


def _write_factor_month_incremental_part(
    base_dir: str,
    factor_name: str,
    year: int,
    month: int,
    new_df: pl.DataFrame,
) -> tuple[str, int]:
    factor_dir_name = _sanitize_factor_dir_name(factor_name)
    final_dir = os.path.join(base_dir, f"factor={factor_dir_name}", f"year={year}", f"month={month:02d}")
    os.makedirs(final_dir, exist_ok=True)

    part_path = os.path.join(
        final_dir,
        f"part_{int(time.time() * 1000)}_{os.getpid()}_{uuid.uuid4().hex}.parquet",
    )
    _write_parquet_atomic_with_retry(new_df, part_path, compression="snappy")
    return part_path, len(new_df)


def _load_factor_storage_summary(
    base_dir: str,
    factor_names: list[str],
    factor_last_dt_map: dict[str, pd.Timestamp] | None = None,
) -> dict[str, dict[str, object]]:
    last_dates = factor_last_dt_map if factor_last_dt_map is not None else _load_factor_last_date_map(base_dir)
    result: dict[str, dict[str, object]] = {}
    for factor_name in factor_names:
        factor_key = _sanitize_factor_dir_name(factor_name)
        last_dt = last_dates.get(factor_key)
        if last_dt is not None:
            result[str(factor_name)] = {"last_dt": pd.Timestamp(last_dt).floor("D")}
    return result


MAX_SAVE_WORKERS = 10


def _build_factor_save_tasks(
    *,
    ch_name: str,
    eng_name: str,
    factor_df: pd.DataFrame,
    base_dir: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    existing_last_dt: pd.Timestamp | None,
    existing_codes: set[str] | None = None,
    drop_null_values: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(factor_df, pd.DataFrame) or factor_df.empty:
        return []

    start_dt = pd.Timestamp(start_dt).floor("D")
    end_dt = pd.Timestamp(end_dt).floor("D")
    if start_dt > end_dt:
        return []

    _ = existing_codes

    def _task(task_df: pd.DataFrame, task_start: pd.Timestamp, task_end: pd.Timestamp) -> dict[str, Any]:
        return {
            "factor_name": ch_name,
            "factor_key": eng_name,
            "factor_df": task_df,
            "base_dir": base_dir,
            "start_dt": pd.Timestamp(task_start).floor("D"),
            "end_dt": pd.Timestamp(task_end).floor("D"),
            "drop_null_values": bool(drop_null_values),
        }

    if existing_last_dt is None:
        return [_task(factor_df, start_dt, end_dt)]

    tail_start_dt = max(start_dt, pd.Timestamp(existing_last_dt).floor("D") + pd.Timedelta(days=1))
    if tail_start_dt <= end_dt:
        return [_task(factor_df, tail_start_dt, end_dt)]
    return []


def _save_single_factor_task(
    task: dict[str, Any],
) -> tuple[str, int, int, float, pd.Timestamp, pd.Timestamp]:
    task_started_at = perf_counter()
    factor_name = task["factor_name"]
    factor_df = task["factor_df"]
    base_dir = task["base_dir"]
    start_dt = pd.Timestamp(task["start_dt"]).floor("D")
    end_dt = pd.Timestamp(task["end_dt"]).floor("D")

    written_months = 0
    written_rows = 0
    processed_date: pd.Timestamp | None = None
    if bool(task.get("drop_null_values", False)) and isinstance(factor_df, pd.DataFrame):
        input_dates = pd.DatetimeIndex(
            pd.to_datetime(factor_df.index, errors="coerce")
        ).floor("D")
        in_range = input_dates[(input_dates >= start_dt) & (input_dates <= end_dt)]
        if len(in_range) > 0:
            processed_date = pd.Timestamp(in_range.max()).floor("D")
    for month_start in _month_start_range(start_dt, end_dt):
        month_end = min(month_start + pd.offsets.MonthEnd(0), end_dt)
        month_start_clipped = max(month_start, start_dt)
        new_df = _factor_month_to_long_polars(
            factor_df,
            month_start_clipped,
            month_end,
            drop_null_values=bool(task.get("drop_null_values", False)),
        )
        if new_df is None or new_df.is_empty():
            continue
        part_path, part_rows = _write_factor_month_incremental_part(
            base_dir=base_dir,
            factor_name=factor_name,
            year=int(month_start.year),
            month=int(month_start.month),
            new_df=new_df,
        )
        print(
            f"+ 因子增量落盘: {factor_name} {month_start.year}-{month_start.month:02d} "
            f"rows={part_rows} file={os.path.basename(part_path)}"
        )
        written_months += 1
        written_rows += int(part_rows)

    if processed_date is not None:
        _write_factor_processed_date_atomic(
            base_dir=base_dir,
            factor_name=factor_name,
            processed_date=processed_date,
        )
    elapsed_seconds = perf_counter() - task_started_at
    return factor_name, written_months, written_rows, elapsed_seconds, start_dt, end_dt


def save_factor_dfs_to_factor_partitioned_parquet(
    factor_dfs_dict: dict,
    factor_name_map_dict: dict,
    base_dir: str,
    start_date: str,
    end_date: str,
    max_workers: int = MAX_SAVE_WORKERS,
    factor_time_ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]] | None = None,
    factor_last_dt_map: dict[str, pd.Timestamp] | None = None,
    drop_null_factor_keys: set[str] | None = None,
) -> None:
    if not factor_dfs_dict:
        print("没有可保存的因子数据。")
        return

    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(f"START_DATE 不能晚于 END_DATE: {start_date} > {end_date}")

    factor_items = [
        (str(ch_name), eng_name, factor_dfs_dict[eng_name])
        for ch_name, eng_name in factor_name_map_dict.items()
        if eng_name in factor_dfs_dict
    ]
    if not factor_items:
        print("factor_name_map 中没有匹配 factor_dfs 的因子。")
        return

    sparse_factor_keys = {
        str(factor_key).strip()
        for factor_key in (drop_null_factor_keys or set())
        if str(factor_key).strip()
    }

    safe_names: dict[str, str] = {}
    for ch_name, _, _ in factor_items:
        safe = _sanitize_factor_dir_name(ch_name)
        if safe in safe_names and safe_names[safe] != ch_name:
            raise ValueError(f"中文因子目录名清洗后冲突: {safe_names[safe]} / {ch_name} -> {safe}")
        safe_names[safe] = ch_name

    print(f"开始按因子长表增量保存（part 文件），目标路径: {base_dir}")
    print(f"目标写入区间: {start_dt.date()} ~ {end_dt.date()}")
    print(f"可写入因子数量: {len(factor_items)}")
    print("说明: 本流程只追加 part_*.parquet，不在此处做 merged.parquet 月度合并。")

    factor_storage_summary = _load_factor_storage_summary(
        base_dir=base_dir,
        factor_names=[str(ch_name) for ch_name, _, _ in factor_items],
        factor_last_dt_map=factor_last_dt_map,
    )

    tasks: list[dict[str, Any]] = []
    for ch_name, eng_name, factor_df in factor_items:
        if not isinstance(factor_df, pd.DataFrame) or factor_df.empty:
            continue

        task_start_dt = start_dt
        task_end_dt = end_dt
        if factor_time_ranges and str(eng_name) in factor_time_ranges:
            range_start, range_end = factor_time_ranges[str(eng_name)]
            task_start_dt = max(start_dt, pd.Timestamp(range_start).floor("D"))
            task_end_dt = min(end_dt, pd.Timestamp(range_end).floor("D"))

        storage_item = factor_storage_summary.get(str(ch_name), {})
        tasks.extend(
            _build_factor_save_tasks(
                ch_name=str(ch_name),
                eng_name=str(eng_name),
                factor_df=factor_df,
                base_dir=base_dir,
                start_dt=task_start_dt,
                end_dt=task_end_dt,
                existing_last_dt=storage_item.get("last_dt"),
                drop_null_values=str(eng_name) in sparse_factor_keys,
            )
        )

    if not tasks:
        print("没有可写入的有效因子任务（可能已全部写到最新日期）。")
        return

    workers = max(1, int(max_workers))
    workers = min(workers, len(tasks))
    print(f"并行线程数: {workers}")

    failed_tasks: list[tuple[str, dict[str, Any]]] = []
    total_written_rows = 0
    total_written_months = 0
    save_batch_started_at = perf_counter()
    if workers == 1:
        for task_idx, task in enumerate(tasks, start=1):
            (
                factor_name,
                written_months,
                written_rows,
                elapsed_seconds,
                task_start_dt,
                task_end_dt,
            ) = _save_single_factor_task(task)
            total_written_rows += int(written_rows)
            total_written_months += int(written_months)
            print(
                _format_save_progress_line(
                    task_idx=task_idx,
                    task_total=len(tasks),
                    factor_name=factor_name,
                    start_dt=task_start_dt,
                    end_dt=task_end_dt,
                    written_months=written_months,
                    written_rows=written_rows,
                    elapsed_seconds=elapsed_seconds,
                )
            )
    else:
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_task = {executor.submit(_save_single_factor_task, task): task for task in tasks}
                done_count = 0
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    done_count += 1
                    factor_name = task["factor_name"]
                    try:
                        (
                            finished_name,
                            written_months,
                            written_rows,
                            elapsed_seconds,
                            task_start_dt,
                            task_end_dt,
                        ) = future.result()
                        total_written_rows += int(written_rows)
                        total_written_months += int(written_months)
                        print(
                            _format_save_progress_line(
                                task_idx=done_count,
                                task_total=len(tasks),
                                factor_name=finished_name,
                                start_dt=task_start_dt,
                                end_dt=task_end_dt,
                                written_months=written_months,
                                written_rows=written_rows,
                                elapsed_seconds=elapsed_seconds,
                            )
                        )
                    except Exception as exc:
                        print(f"[WARN] 因子任务失败，将顺序重试: {factor_name}，原因: {exc}")
                        failed_tasks.append((factor_name, task))
        except Exception as exc:
            print(f"[WARN] 线程池执行失败，回退顺序执行。原因: {exc}")
            failed_tasks = [(task["factor_name"], task) for task in tasks]

    if failed_tasks:
        print(f"顺序重试失败任务数量: {len(failed_tasks)}")
        for retry_idx, (factor_name, task) in enumerate(failed_tasks, start=1):
            (
                finished_name,
                written_months,
                written_rows,
                elapsed_seconds,
                task_start_dt,
                task_end_dt,
            ) = _save_single_factor_task(task)
            total_written_rows += int(written_rows)
            total_written_months += int(written_months)
            print(
                _format_save_progress_line(
                    task_idx=retry_idx,
                    task_total=len(failed_tasks),
                    factor_name=finished_name,
                    start_dt=task_start_dt,
                    end_dt=task_end_dt,
                    written_months=written_months,
                    written_rows=written_rows,
                    elapsed_seconds=elapsed_seconds,
                ).replace("[保存完成]", "[保存重试完成]", 1)
            )

    save_batch_seconds = perf_counter() - save_batch_started_at
    print(
        f"\n[保存汇总] 任务={len(tasks)}，月份={total_written_months}，"
        f"行数={total_written_rows}，耗时={save_batch_seconds:.2f}秒"
    )
    print("所有因子数据保存完成（按因子分区长表增量 part 模式）！")


# 执行保存
_planned_ranges = globals().get("PLANNED_FACTOR_TIME_RANGES", {})
save_factor_dfs_to_factor_partitioned_parquet(
    factor_dfs,
    factor_name_map,
    OUTPUT_BASE_DIR,
    globals().get("EFFECTIVE_START_DATE", START_DATE),
    END_DATE,
    factor_time_ranges=_planned_ranges if _planned_ranges else None,
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)


def _run_stock_size_style_pure_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    score_keys = set(SIZE_STYLE_PURE_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("纯市值风格评分派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(score_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("纯市值风格评分派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            pd.Timestamp(row["plan_start"]).floor("D"),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        ch_name: factor_key
        for ch_name, factor_key in SIZE_STYLE_PURE_FACTOR_NAME_MAP.items()
        if factor_key in factor_ranges
    }
    print(
        f"\n[派生阶段] 纯市值风格评分，"
        f"区间={run_start.date()} ~ {run_end.date()}，因子={len(selected_name_map)}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        # 不传股票子集，始终使用当月完整沪深股票横截面排名。
        chunk_result = build_stock_size_style_pure_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
            drop_null_factor_keys=set(chunk_factor_dfs),
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(f"[派生完成] 纯市值风格评分 {chunk_start.date()} ~ {chunk_end.date()}")
    return last_result


_size_style_pure_result = _run_stock_size_style_pure_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _size_style_pure_result is not None:
    factor_dfs.update(_size_style_pure_result["factor_dfs"])
    factor_name_map.update(_size_style_pure_result["factor_name_map"])


def _run_stock_momentum_style_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    score_keys = set(MOMENTUM_STYLE_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("股票动量风格评分派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(score_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("股票动量风格评分派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            pd.Timestamp(row["plan_start"]).floor("D"),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        ch_name: factor_key
        for ch_name, factor_key in MOMENTUM_STYLE_FACTOR_NAME_MAP.items()
        if factor_key in factor_ranges
    }
    print(
        f"\n[派生阶段] 股票动量风格评分，"
        f"区间={run_start.date()} ~ {run_end.date()}，因子={len(selected_name_map)}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_momentum_style_bundle(
            signal_base_dir=base_dir,
            market_base_dir=BASE_PATH,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
            drop_null_factor_keys=set(chunk_factor_dfs),
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(f"[派生完成] 股票动量风格评分 {chunk_start.date()} ~ {chunk_end.date()}")
    return last_result


_momentum_style_result = _run_stock_momentum_style_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _momentum_style_result is not None:
    factor_dfs.update(_momentum_style_result["factor_dfs"])
    factor_name_map.update(_momentum_style_result["factor_name_map"])


def _run_stock_liquidity_composite_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    score_keys = set(LIQUIDITY_COMPOSITE_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("股票流动性综合评分派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(score_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("股票流动性综合评分派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            pd.Timestamp(row["plan_start"]).floor("D"),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        ch_name: factor_key
        for ch_name, factor_key in LIQUIDITY_COMPOSITE_FACTOR_NAME_MAP.items()
        if factor_key in factor_ranges
    }
    print(
        f"\n[派生阶段] 股票流动性综合评分，"
        f"区间={run_start.date()} ~ {run_end.date()}，因子={len(selected_name_map)}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_liquidity_composite_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
            drop_null_factor_keys=set(chunk_factor_dfs),
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(f"[派生完成] 股票流动性综合评分 {chunk_start.date()} ~ {chunk_end.date()}")
    return last_result


_liquidity_composite_result = _run_stock_liquidity_composite_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _liquidity_composite_result is not None:
    factor_dfs.update(_liquidity_composite_result["factor_dfs"])
    factor_name_map.update(_liquidity_composite_result["factor_name_map"])


def _run_stock_low_volatility_style_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    score_keys = set(LOW_VOLATILITY_STYLE_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("股票低波风格评分派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(score_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("股票低波风格评分派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            pd.Timestamp(row["plan_start"]).floor("D"),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        ch_name: factor_key
        for ch_name, factor_key in LOW_VOLATILITY_STYLE_FACTOR_NAME_MAP.items()
        if factor_key in factor_ranges
    }
    print(
        f"\n[派生阶段] 股票低波风格评分，"
        f"区间={run_start.date()} ~ {run_end.date()}，因子={len(selected_name_map)}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        # 不传股票子集，始终使用当月完整沪深股票横截面排名。
        chunk_result = build_stock_low_volatility_style_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
            drop_null_factor_keys=set(chunk_factor_dfs),
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(f"[派生完成] 股票低波风格评分 {chunk_start.date()} ~ {chunk_end.date()}")
    return last_result


_low_volatility_style_result = _run_stock_low_volatility_style_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _low_volatility_style_result is not None:
    factor_dfs.update(_low_volatility_style_result["factor_dfs"])
    factor_name_map.update(_low_volatility_style_result["factor_name_map"])


def _run_stock_value_normalized_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    normalized_keys = set(VALUE_NORMALIZED_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("价值标准化派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(normalized_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("价值标准化派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            pd.Timestamp(row["plan_start"]).floor("D"),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        ch_name: factor_key
        for ch_name, factor_key in VALUE_NORMALIZED_FACTOR_NAME_MAP.items()
        if factor_key in factor_ranges
    }
    print(
        f"\n[派生阶段] 价值去极值与标准化因子，"
        f"区间={run_start.date()} ~ {run_end.date()}，因子={len(selected_name_map)}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        # 标准化入口不接收股票子集，始终使用当月完整 A 股横截面。
        chunk_result = build_stock_value_normalized_factor_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(f"[派生完成] 价值标准化 {chunk_start.date()} ~ {chunk_end.date()}")
    return last_result


_value_normalized_result = _run_stock_value_normalized_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _value_normalized_result is not None:
    factor_dfs.update(_value_normalized_result["factor_dfs"])
    factor_name_map.update(_value_normalized_result["factor_name_map"])


def _run_stock_value_model_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    model_keys = set(VALUE_MODEL_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("价值模型综合评分派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(model_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("价值模型综合评分派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            max(pd.Timestamp(row["plan_start"]).floor("D"), VALUE_MODEL_START_DATE),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    factor_ranges = {
        key: date_range
        for key, date_range in factor_ranges.items()
        if date_range[0] <= date_range[1]
    }
    if not factor_ranges:
        print("价值模型综合评分派生阶段跳过：目标区间早于 2015-01-01。")
        return None

    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        ch_name: factor_key
        for ch_name, factor_key in VALUE_MODEL_FACTOR_NAME_MAP.items()
        if factor_key in factor_ranges
    }
    print(
        f"\n[派生阶段] 价值模型综合评分，"
        f"区间={run_start.date()} ~ {run_end.date()}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_value_model_composite_score_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_result["factor_dfs"],
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_result["factor_dfs"],
            "factor_name_map": selected_name_map,
        }
        print(f"[派生完成] 价值模型综合评分 {chunk_start.date()} ~ {chunk_end.date()}")
    return last_result


_value_model_result = _run_stock_value_model_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _value_model_result is not None:
    factor_dfs.update(_value_model_result["factor_dfs"])
    factor_name_map.update(_value_model_result["factor_name_map"])


def _run_stock_growth_normalized_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    stock_codes: set[str],
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    normalized_keys = set(GROWTH_NORMALIZED_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("成长标准化派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(normalized_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("成长标准化派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            pd.Timestamp(row["plan_start"]).floor("D"),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        ch_name: factor_key
        for ch_name, factor_key in GROWTH_NORMALIZED_FACTOR_NAME_MAP.items()
        if factor_key in factor_ranges
    }
    print(
        f"\n[派生阶段] 成长标准化因子，区间={run_start.date()} ~ {run_end.date()}，"
        f"因子={len(selected_name_map)}，股票={len(stock_codes)}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_growth_normalized_factor_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
            stock_codes=stock_codes,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(f"[派生完成] 成长标准化 {chunk_start.date()} ~ {chunk_end.date()}")
    return last_result


_growth_normalized_result = _run_stock_growth_normalized_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    stock_codes=set(_stock_source_code_set),
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _growth_normalized_result is not None:
    factor_dfs.update(_growth_normalized_result["factor_dfs"])
    factor_name_map.update(_growth_normalized_result["factor_name_map"])


def _run_stock_growth_industry_normalized_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    factor_keys = set(GROWTH_INDUSTRY_NORMALIZED_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("成长行业标准化派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(factor_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("成长行业标准化派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            max(
                pd.Timestamp(row["plan_start"]).floor("D"),
                GROWTH_INDUSTRY_NORMALIZED_START_DATE,
            ),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    factor_ranges = {
        key: value for key, value in factor_ranges.items() if value[0] <= value[1]
    }
    if not factor_ranges:
        print("成长行业标准化派生阶段跳过：目标区间早于首个 881 快照。")
        return None
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        name: key
        for name, key in GROWTH_INDUSTRY_NORMALIZED_FACTOR_NAME_MAP.items()
        if key in factor_ranges
    }
    print(
        f"\n[派生阶段] 成长风格综合评分(行业标准化)，"
        f"区间={run_start.date()} ~ {run_end.date()}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_growth_industry_normalized_factor_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
            drop_null_factor_keys=set(chunk_factor_dfs),
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(
            f"[派生完成] 成长风格综合评分(行业标准化) "
            f"{chunk_start.date()} ~ {chunk_end.date()}"
        )
    return last_result


_growth_industry_normalized_result = _run_stock_growth_industry_normalized_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _growth_industry_normalized_result is not None:
    factor_dfs.update(_growth_industry_normalized_result["factor_dfs"])
    factor_name_map.update(_growth_industry_normalized_result["factor_name_map"])


def _run_stock_value_model_industry_normalized_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    factor_keys = set(VALUE_MODEL_INDUSTRY_NORMALIZED_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("价值行业标准化派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(factor_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("价值行业标准化派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            max(
                pd.Timestamp(row["plan_start"]).floor("D"),
                VALUE_MODEL_INDUSTRY_NORMALIZED_START_DATE,
            ),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    factor_ranges = {
        key: value for key, value in factor_ranges.items() if value[0] <= value[1]
    }
    if not factor_ranges:
        print("价值行业标准化派生阶段跳过：目标区间早于首个 881 快照。")
        return None
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        name: key
        for name, key in VALUE_MODEL_INDUSTRY_NORMALIZED_FACTOR_NAME_MAP.items()
        if key in factor_ranges
    }
    print(
        f"\n[派生阶段] 价值模型综合评分(行业标准化)，"
        f"区间={run_start.date()} ~ {run_end.date()}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_value_model_industry_normalized_score_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
            drop_null_factor_keys=set(chunk_factor_dfs),
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(
            f"[派生完成] 价值模型综合评分(行业标准化) "
            f"{chunk_start.date()} ~ {chunk_end.date()}"
        )
    return last_result


_value_model_industry_normalized_result = (
    _run_stock_value_model_industry_normalized_post_write(
        base_dir=OUTPUT_BASE_DIR,
        plan_df=factor_plan_df,
        factor_last_dt_map=globals().get("_factor_last_dt_map"),
    )
)
if _value_model_industry_normalized_result is not None:
    factor_dfs.update(_value_model_industry_normalized_result["factor_dfs"])
    factor_name_map.update(_value_model_industry_normalized_result["factor_name_map"])


def _run_stock_growth_multi_board_normalized_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    factor_keys = set(GROWTH_MULTI_BOARD_NORMALIZED_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("成长多板块标准化派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(factor_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("成长多板块标准化派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            max(
                pd.Timestamp(row["plan_start"]).floor("D"),
                GROWTH_MULTI_BOARD_NORMALIZED_START_DATE,
            ),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    factor_ranges = {
        key: value for key, value in factor_ranges.items() if value[0] <= value[1]
    }
    if not factor_ranges:
        print("成长多板块标准化派生阶段跳过：目标区间早于首个板块快照。")
        return None
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        name: key
        for name, key in GROWTH_MULTI_BOARD_NORMALIZED_FACTOR_NAME_MAP.items()
        if key in factor_ranges
    }
    print(
        f"\n[派生阶段] 成长风格综合评分(多板块标准化)，"
        f"区间={run_start.date()} ~ {run_end.date()}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_growth_multi_board_normalized_factor_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
            drop_null_factor_keys=set(chunk_factor_dfs),
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(
            f"[派生完成] 成长风格综合评分(多板块标准化) "
            f"{chunk_start.date()} ~ {chunk_end.date()}"
        )
    return last_result


_growth_multi_board_normalized_result = (
    _run_stock_growth_multi_board_normalized_post_write(
        base_dir=OUTPUT_BASE_DIR,
        plan_df=factor_plan_df,
        factor_last_dt_map=globals().get("_factor_last_dt_map"),
    )
)
if _growth_multi_board_normalized_result is not None:
    factor_dfs.update(_growth_multi_board_normalized_result["factor_dfs"])
    factor_name_map.update(_growth_multi_board_normalized_result["factor_name_map"])


def _run_stock_value_model_multi_board_normalized_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    factor_keys = set(VALUE_MODEL_MULTI_BOARD_NORMALIZED_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("价值多板块标准化派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(factor_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("价值多板块标准化派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            max(
                pd.Timestamp(row["plan_start"]).floor("D"),
                VALUE_MODEL_MULTI_BOARD_NORMALIZED_START_DATE,
            ),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    factor_ranges = {
        key: value for key, value in factor_ranges.items() if value[0] <= value[1]
    }
    if not factor_ranges:
        print("价值多板块标准化派生阶段跳过：目标区间早于首个板块快照。")
        return None
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        name: key
        for name, key in VALUE_MODEL_MULTI_BOARD_NORMALIZED_FACTOR_NAME_MAP.items()
        if key in factor_ranges
    }
    print(
        f"\n[派生阶段] 价值模型综合评分(多板块标准化)，"
        f"区间={run_start.date()} ~ {run_end.date()}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_value_model_multi_board_normalized_score_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
            drop_null_factor_keys=set(chunk_factor_dfs),
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(
            f"[派生完成] 价值模型综合评分(多板块标准化) "
            f"{chunk_start.date()} ~ {chunk_end.date()}"
        )
    return last_result


_value_model_multi_board_normalized_result = (
    _run_stock_value_model_multi_board_normalized_post_write(
        base_dir=OUTPUT_BASE_DIR,
        plan_df=factor_plan_df,
        factor_last_dt_map=globals().get("_factor_last_dt_map"),
    )
)
if _value_model_multi_board_normalized_result is not None:
    factor_dfs.update(_value_model_multi_board_normalized_result["factor_dfs"])
    factor_name_map.update(_value_model_multi_board_normalized_result["factor_name_map"])


def _run_stock_dividend_normalized_post_write(
    *,
    base_dir: str,
    plan_df: pd.DataFrame,
    stock_codes: set[str],
    factor_last_dt_map: dict[str, pd.Timestamp] | None,
) -> dict[str, object] | None:
    normalized_keys = set(DIVIDEND_NORMALIZED_FACTOR_NAME_MAP.values())
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        print("红利标准化派生阶段跳过：没有因子缺失计划。")
        return None
    needed = plan_df[
        plan_df["factor_en"].astype(str).isin(normalized_keys)
        & plan_df["status"].isin(["missing", "stale"])
        & plan_df["plan_start"].notna()
        & plan_df["plan_end"].notna()
    ].copy()
    if needed.empty:
        print("红利标准化派生阶段跳过：相关因子已是最新。")
        return None

    factor_ranges = {
        str(row["factor_en"]): (
            pd.Timestamp(row["plan_start"]).floor("D"),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in needed.iterrows()
    }
    run_start = min(start for start, _ in factor_ranges.values())
    run_end = max(end for _, end in factor_ranges.values())
    selected_name_map = {
        ch_name: factor_key
        for ch_name, factor_key in DIVIDEND_NORMALIZED_FACTOR_NAME_MAP.items()
        if factor_key in factor_ranges
    }
    print(
        f"\n[派生阶段] 红利标准化因子，区间={run_start.date()} ~ {run_end.date()}，"
        f"因子={len(selected_name_map)}，股票={len(stock_codes)}"
    )

    last_result: dict[str, object] | None = None
    for month_start in _month_start_range(run_start, run_end):
        chunk_start = max(run_start, month_start)
        chunk_end = min(run_end, month_start + pd.offsets.MonthEnd(0))
        chunk_result = build_stock_dividend_normalized_factor_bundle(
            base_dir=base_dir,
            start_date=chunk_start,
            end_date=chunk_end,
            stock_codes=stock_codes,
        )
        chunk_factor_dfs = {
            key: frame
            for key, frame in chunk_result["factor_dfs"].items()
            if key in factor_ranges
        }
        save_factor_dfs_to_factor_partitioned_parquet(
            chunk_factor_dfs,
            selected_name_map,
            base_dir,
            str(chunk_start.date()),
            str(chunk_end.date()),
            factor_time_ranges=factor_ranges,
            factor_last_dt_map=factor_last_dt_map,
        )
        last_result = {
            "bundle_id": chunk_result["bundle_id"],
            "factor_dfs": chunk_factor_dfs,
            "factor_name_map": selected_name_map,
        }
        print(f"[派生完成] 红利标准化 {chunk_start.date()} ~ {chunk_end.date()}")
    return last_result


_dividend_normalized_result = _run_stock_dividend_normalized_post_write(
    base_dir=OUTPUT_BASE_DIR,
    plan_df=factor_plan_df,
    stock_codes=set(_stock_source_code_set),
    factor_last_dt_map=globals().get("_factor_last_dt_map"),
)
if _dividend_normalized_result is not None:
    factor_dfs.update(_dividend_normalized_result["factor_dfs"])
    factor_name_map.update(_dividend_normalized_result["factor_name_map"])


# %% cell 增量信号保存.py 逻辑
SIGNAL_PART_KEY_COLS = ["time", "htsc_code"]


def _signal_part_resolve_target_month_dirs(
    base_dir: Path,
    factor: str | None = None,
    year: int | None = None,
    month: int | None = None,
) -> list[Path]:
    if factor:
        factor_dirs = [base_dir / f"factor={factor}"]
    else:
        factor_dirs = sorted(base_dir.glob("factor=*"))

    month_dirs: list[Path] = []
    for factor_dir in factor_dirs:
        if not factor_dir.exists():
            continue
        year_dirs = [factor_dir / f"year={int(year)}"] if year else sorted(factor_dir.glob("year=*"))
        for year_dir in year_dirs:
            if not year_dir.exists():
                continue
            cur_month_dirs = (
                [year_dir / f"month={int(month):02d}"]
                if month
                else sorted(year_dir.glob("month=*"))
            )
            for month_dir in cur_month_dirs:
                if month_dir.exists():
                    month_dirs.append(month_dir)
    return month_dirs


def _signal_part_compact_month_partition(month_dir: Path, keep_parts: bool = False) -> tuple[int, int]:
    part_paths = sorted(month_dir.glob("part_*.parquet"))
    if not part_paths:
        return 0, 0

    merged_path = month_dir / "merged.parquet"
    new_frames = [pl.read_parquet(str(path)) for path in part_paths if path.stat().st_size >= 12]
    if not new_frames:
        print(f"[SKIP] 无有效 part 文件: {month_dir}")
        return 0, 0

    new_df = (
        pl.concat(new_frames, how="vertical_relaxed", rechunk=True)
        .sort(SIGNAL_PART_KEY_COLS)
        .unique(subset=SIGNAL_PART_KEY_COLS, keep="last")
        .sort(SIGNAL_PART_KEY_COLS)
    )

    old_df = _read_existing_partition(str(merged_path))
    if old_df is None:
        save_df = new_df
        print(f"[NEW] {month_dir} 新建 merged (新 {len(new_df)})")
    else:
        save_df = _merge_preserve_old_values(old_df, new_df)
        print(f"[MERGE] {month_dir} (旧 {len(old_df)} + 新 {len(new_df)} => {len(save_df)})")

    _write_parquet_atomic_with_retry(save_df, str(merged_path), compression="snappy")

    if not keep_parts:
        for path in part_paths:
            try:
                path.unlink()
            except OSError as exc:
                print(f"[WARN] 删除 part 文件失败: {path}，原因: {exc}")

    return len(part_paths), len(save_df)


def _signal_part_default_workers() -> int:
    cpu = os.cpu_count() or 4
    return max(1, min(4, cpu))


def _signal_part_compact_month_partition_task(
    month_dir: Path,
    keep_parts: bool,
) -> tuple[Path, int, int]:
    parts, rows = _signal_part_compact_month_partition(month_dir, keep_parts=keep_parts)
    return month_dir, parts, rows


def compact_signal_daily_parts(
    base_dir: str = r"D:\database\signal_daily",
    factor: str | None = None,
    year: int | None = None,
    month: int | None = None,
    keep_parts: bool = False,
    workers: int | None = None,
) -> None:
    base_path = Path(base_dir)
    if not base_path.exists():
        raise FileNotFoundError(f"base_dir 不存在: {base_path}")

    target_month_dirs = _signal_part_resolve_target_month_dirs(
        base_dir=base_path,
        factor=factor,
        year=year,
        month=month,
    )
    if not target_month_dirs:
        print("没有找到需要处理的月份目录。")
        return

    worker_count = max(1, int(workers if workers is not None else _signal_part_default_workers()))
    print(f"待处理月份目录数: {len(target_month_dirs)}，workers={worker_count}")
    total_parts = 0
    touched_months = 0
    failed_months: list[tuple[Path, Exception]] = []

    if worker_count == 1 or len(target_month_dirs) <= 1:
        for month_dir in target_month_dirs:
            parts, _ = _signal_part_compact_month_partition(month_dir, keep_parts=keep_parts)
            if parts > 0:
                touched_months += 1
                total_parts += parts
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _signal_part_compact_month_partition_task,
                    month_dir,
                    keep_parts,
                ): month_dir
                for month_dir in target_month_dirs
            }
            for future in as_completed(futures):
                month_dir = futures[future]
                try:
                    _, parts, _rows = future.result()
                except Exception as exc:
                    print(f"[ERROR] 处理失败: {month_dir}，原因: {exc}")
                    failed_months.append((month_dir, exc))
                    continue
                if parts > 0:
                    touched_months += 1
                    total_parts += parts

    if failed_months:
        failure_details = "；".join(f"{month_dir}: {exc}" for month_dir, exc in failed_months)
        raise RuntimeError(f"月度 part 合并失败，共 {len(failed_months)} 个目录：{failure_details}")

    print(f"处理完成: 命中月份 {touched_months}，合并 part 文件总数 {total_parts}")


def _finalize_factor_batch(
    *,
    base_dir: str,
    factor_dfs_dict: dict[str, pd.DataFrame],
    factor_name_map_dict: dict[str, str],
    target_date: pd.Timestamp,
    current_complete_date: pd.Timestamp | None = None,
    all_market_codes: set[str],
    ths_codes: set[str],
    ths_only_factor_keys: set[str],
    compact_func=None,
    watermark_writer=None,
    managed_factor_name_map: dict[str, str] | None = None,
    factor_last_date_loader=None,
) -> Path:
    target_dt = pd.Timestamp(target_date).floor("D")
    current_dt = (
        pd.Timestamp(current_complete_date).floor("D")
        if current_complete_date is not None
        else None
    )
    has_factor_updates = bool(factor_dfs_dict or factor_name_map_dict)
    if not has_factor_updates and managed_factor_name_map is None:
        if current_dt is not None and current_dt >= target_dt:
            path = _batch_watermark_path(base_dir)
            print(f"整批完成水位已覆盖行情终点，无需补写: {current_dt.date()}")
            return path
        path = _batch_watermark_path(base_dir)
        print("本次因子计划为空，保留现有整批完成水位。")
        return path
    elif has_factor_updates:
        summary = _validate_factor_frames_for_batch(
            factor_dfs_dict=factor_dfs_dict,
            factor_name_map_dict=factor_name_map_dict,
            target_date=target_date,
            all_market_codes=all_market_codes,
            ths_codes=ths_codes,
            ths_only_factor_keys=ths_only_factor_keys,
        )
    else:
        summary = {}

    selected_compact_func = compact_func or compact_signal_daily_parts
    selected_watermark_writer = watermark_writer or _write_batch_watermark_atomic
    if has_factor_updates:
        for factor_name in factor_name_map_dict:
            selected_compact_func(base_dir=base_dir, factor=factor_name)

    complete_date = target_dt
    if managed_factor_name_map is not None:
        managed_map = {
            str(ch_name): str(eng_name).strip()
            for ch_name, eng_name in managed_factor_name_map.items()
            if str(ch_name).strip() and str(eng_name).strip()
        }
        if not managed_map:
            path = _batch_watermark_path(base_dir)
            print("整批水位保持不变：受管因子目录为空。")
            return path
        selected_last_date_loader = factor_last_date_loader or _load_factor_last_date_map
        persisted_last_dates = selected_last_date_loader(base_dir)
        normalized_last_dates = {
            _sanitize_factor_dir_name(name): pd.Timestamp(last_dt).floor("D")
            for name, last_dt in persisted_last_dates.items()
            if last_dt is not None and not pd.isna(last_dt)
        }
        missing_factor_names = [
            ch_name
            for ch_name in managed_map
            if _sanitize_factor_dir_name(ch_name) not in normalized_last_dates
        ]
        if missing_factor_names:
            path = _batch_watermark_path(base_dir)
            preview = "、".join(missing_factor_names[:5])
            suffix = "..." if len(missing_factor_names) > 5 else ""
            print(
                f"整批水位保持不变：{len(missing_factor_names)} 个受管因子尚无落盘日期"
                f"（{preview}{suffix}）"
            )
            return path

        complete_date = min(
            target_dt,
            min(
                normalized_last_dates[_sanitize_factor_dir_name(ch_name)]
                for ch_name in managed_map
            ),
        )
        managed_keys = list(managed_map.values())
        summary = {
            "factor_count": len(managed_map),
            "all_market_factor_count": sum(
                factor_key not in ths_only_factor_keys
                for factor_key in managed_keys
            ),
            "ths_factor_count": sum(
                factor_key in ths_only_factor_keys
                for factor_key in managed_keys
            ),
        }

    payload: dict[str, object] = {
        "status": "complete",
        "last_complete_date": complete_date.strftime("%Y-%m-%d"),
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        **summary,
    }
    path = selected_watermark_writer(base_dir, payload)
    print(f"整批因子完成水位已更新: {path} -> {payload['last_complete_date']}")
    return path


# 保存、校验和增量 part 合并全部成功后，最后更新整批完成水位。
_managed_factor_name_map = {
    str(ch_name): str(eng_name)
    for bundle_name in SELECTED_BUNDLES
    for ch_name, eng_name in bundle_factor_catalog.get(bundle_name, {}).items()
}
_finalize_factor_batch(
    base_dir=OUTPUT_BASE_DIR,
    factor_dfs_dict=factor_dfs,
    factor_name_map_dict=factor_name_map,
    target_date=pd.Timestamp(END_DATE),
    current_complete_date=BATCH_COMPLETE_DATE,
    all_market_codes=set(_source_code_set),
    ths_codes=set(_sector_source_code_set),
    ths_only_factor_keys=SECTOR_OUTPUT_FACTOR_KEYS,
    managed_factor_name_map=_managed_factor_name_map,
)
