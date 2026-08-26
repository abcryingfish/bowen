# -*- coding: utf-8 -*-
"""纯技术面因子的统一向量化适配层。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
import pandas as pd

from valid_bar_utils import compute_bundles_with_valid_bar
from 纯技术面因子.ADX import ADX
from 纯技术面因子.AMA import AMA, build_ama_factor_matrices_with_state
from 纯技术面因子.APO import APO
from 纯技术面因子.AROON import AROON
from 纯技术面因子.BOLL import BOLL
from 纯技术面因子.CCI import CCI
from 纯技术面因子.CMO import CMO
from 纯技术面因子.DEMA import DEMA
from 纯技术面因子.MACD import MACD
from 纯技术面因子.MFI import MFI
from 纯技术面因子.MOM import MOM
from 纯技术面因子.PPO import PPO
from 纯技术面因子.ROC import ROC
from 纯技术面因子.RSI import RSI
from 纯技术面因子.STOCH import STOCH
from 纯技术面因子.ULTOSC import ULTOSC
from 纯技术面因子.WILLR import WILLR
from 纯技术面因子.WMA import WMA


BUNDLE_ID = "pure_technical"
# 无有效触发、方向语义不成立、重复或名称与实现不符的信号统一在此退役；
# 它们不再出现在目录、迭代输出和后续生成计划中。
RETIRED_FACTOR_IDS = frozenset(
    {
        "MOM_triangle_convergence",
        "PPO_triangle_convergence",
        "ROC_triangle_convergence",
        "ADX_trend_confirmation",
        "ADX_trend_weakening",
        "DEMA_golden_cross",
        "DEMA_death_cross",
        "DEMA_zero_line_breakthrough",
        "DEMA_zero_line_pullback",
        "DEMA_bottom_divergence",
        "CMO_triple_bottom",
        "CMO_triple_top",
        "CMO_head_shoulders_bottom",
        "CMO_head_shoulders_top",
        "ULTOSC_expansion",
        "ULTOSC_contraction",
        "ULTOSC_bull_bear_transition",
        "ULTOSC_double_bottom",
        "ULTOSC_double_top",
        "WILLR_willr_divergence",
        "WILLR_willr_convergence",
        "WILLR_bull_bear_transition",
        "WMA_wma_divergence",
        "WMA_wma_convergence",
    }
)
DEFAULT_LOOKBACK_DAYS = 520
DEFAULT_CATALOG_CACHE_PATH = Path(
    r"D:\database\signal_daily\_meta\pure_technical_factor_catalog_cache.json"
)
INDICATOR_NAMES = (
    "ADX",
    "AMA",
    "APO",
    "AROON",
    "BOLL",
    "CCI",
    "CMO",
    "DEMA",
    "MACD",
    "MFI",
    "MOM",
    "PPO",
    "ROC",
    "RSI",
    "STOCH",
    "ULTOSC",
    "WILLR",
    "WMA",
)
_FACTOR_ID_PATTERN = re.compile(r"^[A-Z0-9]+_[a-z0-9_]+$")
_MODULE_DIR = Path(__file__).resolve().parent / "纯技术面因子"
_CATALOG_MEMORY: dict[str, object] | None = None
_CATALOG_MEMORY_SIGNATURE: dict[str, str] | None = None

_SIGNAL_PHRASE_CN = {
    "golden_cross": "金叉",
    "death_cross": "死叉",
    "top_divergence": "顶背离",
    "bottom_divergence": "底背离",
    "zero_line_breakthrough": "上穿零轴",
    "zero_line_pullback": "下穿零轴",
    "bull_bear_transition": "多空转换",
    "overbought_signal": "超买信号",
    "oversold_signal": "超卖信号",
    "extreme_reversal_top": "极端顶部反转",
    "extreme_reversal_bottom": "极端底部反转",
    "extreme_reversal_buy": "极端反转买入",
    "extreme_reversal_sell": "极端反转卖出",
    "head_shoulders_bottom": "头肩底",
    "head_shoulders_top": "头肩顶",
    "rising_wedge": "上升楔形",
    "falling_wedge": "下降楔形",
    "triangle_convergence": "收敛三角形",
    "triangle_divergence": "扩散三角形",
    "channel_breakthrough": "通道突破",
    "channel_pullback": "通道回落",
    "breakthrough_confirmation": "突破确认",
    "pullback_confirmation": "回落确认",
    "volume_surge": "放量",
}
_SIGNAL_TOKEN_CN = {
    "above": "上方", "acceleration": "加速", "alignment": "排列", "bear": "空头",
    "band": "带", "bearish": "空头", "below": "下方", "bottom": "底部", "breakdown": "跌破",
    "breakthrough": "突破", "bull": "多头", "bullish": "多头", "buy": "买入",
    "channel": "通道", "cohesion": "聚合", "confirm": "确认", "confirmation": "确认",
    "contraction": "收缩", "convergence": "收敛", "cross": "交叉", "cycle": "周期",
    "d": "D线", "dea": "DEA", "death": "死叉", "deceleration": "减速", "deviation": "偏离", "dif": "DIF", "divergence": "背离",
    "double": "双重", "down": "向下", "downtrend": "下跌趋势", "efficiency": "效率",
    "exhaustion": "衰竭", "expansion": "扩张", "extreme": "极端", "falling": "下降",
    "flow": "资金流", "golden": "金叉", "head": "头部", "hidden": "隐藏",
    "high": "高位", "hist": "柱体", "histogram": "柱体", "in": "流入",
    "k": "K线", "kd": "KD", "line": "轴", "low": "低位", "lower": "下轨",
    "ma": "均线", "mfi": "MFI", "middle": "中轨", "momentum": "动量",
    "money": "资金", "negative": "转负", "normalized": "归一化", "oscillating": "震荡", "oscillator": "振荡器",
    "out": "流出", "overbought": "超买", "oversold": "超卖", "positive": "转正",
    "ppo": "PPO", "price": "价格", "pullback": "回落", "range": "区间", "position": "位置",
    "recovery": "恢复", "repair": "修复", "resistance": "阻力", "resonance": "共振",
    "ratio": "比率", "rate": "速率", "relative": "相对", "slope": "斜率",
    "reversal": "反转", "rising": "上升", "second": "二次", "sell": "卖出",
    "strength": "强度", "directional": "方向性", "bias": "偏向", "score": "分数",
    "shoulders": "肩", "signal": "信号", "squeeze": "挤压", "spread": "差值", "stagnation": "停滞",
    "strengthen": "增强", "strong": "强势", "support": "支撑", "surge": "放量",
    "top": "顶部", "transition": "转换", "trend": "趋势", "triangle": "三角形",
    "triple": "三重", "turn": "转向", "up": "向上", "upper": "上轨",
    "uptrend": "上涨趋势", "value": "值", "volume": "成交量", "weak": "弱势", "weakening": "减弱",
    "wedge": "楔形", "width": "宽度", "willr": "WILLR", "wma": "WMA", "zero": "零", "zone": "区域",
}


def _translate_signal_key(signal_key: str) -> str:
    key = str(signal_key).strip()
    if key in _SIGNAL_PHRASE_CN:
        return _SIGNAL_PHRASE_CN[key]
    tokens = key.split("_")
    unknown = [token for token in tokens if token not in _SIGNAL_TOKEN_CN]
    if unknown:
        raise ValueError(f"纯技术面信号缺少中文词元映射: {key} -> {unknown}")
    return "".join(_SIGNAL_TOKEN_CN[token] for token in tokens)


def _factor_display_name(factor_id: str) -> str:
    indicator, signal_key = str(factor_id).split("_", 1)
    return f"{indicator}_{_translate_signal_key(signal_key)}"


def _build_catalog(factor_ids: Sequence[str]) -> dict[str, object]:
    labels = {factor_id: _factor_display_name(factor_id) for factor_id in factor_ids}
    if len(labels) != len(set(labels.values())):
        duplicates = sorted({label for label in labels.values() if list(labels.values()).count(label) > 1})
        raise ValueError(f"纯技术面中文显示名冲突: {duplicates}")
    groups = []
    for indicator in INDICATOR_NAMES:
        children = [factor_id for factor_id in factor_ids if factor_id.startswith(f"{indicator}_")]
        groups.append(
            {
                "group_id": f"pure_technical_{indicator.lower()}",
                "group_name": f"纯技术-{indicator}",
                "indicator": indicator,
                "children": children,
            }
        )
    return {
        "bundle_id": BUNDLE_ID,
        "factor_name_map": {labels[factor_id]: factor_id for factor_id in factor_ids},
        "factor_labels": labels,
        "groups": groups,
    }


def _write_catalog_cache(
    path: Path,
    *,
    signature: dict[str, str],
    catalog: dict[str, object],
) -> None:
    factor_labels = dict(catalog["factor_labels"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "signature": signature,
                "factor_ids": list(factor_labels),
                "factor_labels": factor_labels,
                "groups": catalog["groups"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _compute_indicator(
    indicator: str,
    *,
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
    H_adj: pd.DataFrame,
    L_adj: pd.DataFrame,
    C_adj: pd.DataFrame,
    ama_state_cache_path: str | Path | None = None,
    ama_state_only: bool = False,
) -> dict[str, pd.DataFrame]:
    if indicator == "ADX":
        return ADX().get_factor_matrices(H, L, C)
    if indicator == "AMA":
        if ama_state_cache_path is not None:
            return build_ama_factor_matrices_with_state(
                C,
                state_cache_path=ama_state_cache_path,
                state_only=ama_state_only,
            )
        return AMA().get_factor_matrices(O, H, L, C, V)
    if indicator == "APO":
        return APO().get_factor_matrices(O, H, L, C, V)
    if indicator == "AROON":
        return AROON().get_factor_matrices(O, H, L, C, V)
    if indicator == "BOLL":
        return BOLL().get_factor_matrices(O, H, L, C, V)
    if indicator == "CCI":
        return CCI().get_factor_matrices(O, H, L, C, V)
    if indicator == "CMO":
        return CMO().get_factor_matrices(O, H, L, C, V)
    if indicator == "DEMA":
        return DEMA().get_factor_matrices(O, H, L, C, V)
    if indicator == "MACD":
        return MACD().get_factor_matrices(O, H, L, C, V, H_adj, L_adj, C_adj)
    if indicator == "MFI":
        return MFI().get_factor_matrices(O, H, L, C, V)
    if indicator == "MOM":
        return MOM().get_factor_matrices(C, V)
    if indicator == "PPO":
        return PPO().get_factor_matrices(C, V)
    if indicator == "ROC":
        return ROC().get_factor_matrices(C, V)
    if indicator == "RSI":
        return RSI().get_factor_matrices(O, H, L, C, V, H_adj, L_adj, C_adj)
    if indicator == "STOCH":
        return STOCH().get_factor_matrices(O, H, L, C, V)
    if indicator == "ULTOSC":
        return ULTOSC().get_factor_matrices(H, L, C, V)
    if indicator == "WILLR":
        return WILLR().get_factor_matrices(O, H, L, C, V)
    if indicator == "WMA":
        return WMA().get_factor_matrices(O, H, L, C, V)
    raise ValueError(f"未知纯技术面指标: {indicator}")


def _validate_and_prefix(
    indicator: str,
    factor_dfs: dict[str, pd.DataFrame],
    *,
    index: pd.Index,
    columns: pd.Index,
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for signal_key, frame in factor_dfs.items():
        factor_id = f"{indicator}_{str(signal_key).strip()}"
        if factor_id in RETIRED_FACTOR_IDS:
            continue
        if not _FACTOR_ID_PATTERN.fullmatch(factor_id):
            raise ValueError(f"因子唯一名不符合规范: {factor_id}")
        if factor_id in result:
            raise ValueError(f"因子唯一名重复: {factor_id}")
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{factor_id} 输出不是 DataFrame: {type(frame)!r}")
        if not frame.index.equals(index) or not frame.columns.equals(columns):
            raise ValueError(f"{factor_id} 输出轴与输入矩阵不一致")
        result[factor_id] = frame
    return result


def _compute_single_bundle_raw(
    *,
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
    selected_bundles,
    T=None,
    enable_bottom_cache=True,
    valid_bar=None,
):
    del T, enable_bottom_cache, valid_bar
    indicator = str(next(iter(selected_bundles))).strip().upper()
    raw = _compute_indicator(
        indicator,
        O=O,
        H=H,
        L=L,
        C=C,
        V=V,
        H_adj=H,
        L_adj=L,
        C_adj=C,
    )
    prefixed = _validate_and_prefix(indicator, raw, index=C.index, columns=C.columns)
    factor_labels = {name: _factor_display_name(name) for name in prefixed}
    return {indicator}, [
        {
            "bundle_id": BUNDLE_ID,
            "indicator": indicator,
            "factor_dfs": prefixed,
            "factor_name_map": {label: name for name, label in factor_labels.items()},
            "factor_labels": factor_labels,
        }
    ]


def _normalize_indicators(selected_indicators: Sequence[str] | None) -> list[str]:
    if not selected_indicators:
        return list(INDICATOR_NAMES)
    requested = {str(name).strip().upper() for name in selected_indicators if str(name).strip()}
    unknown = sorted(requested.difference(INDICATOR_NAMES))
    if unknown:
        raise ValueError(f"未知纯技术面指标: {', '.join(unknown)}")
    return [name for name in INDICATOR_NAMES if name in requested]


def iter_pure_technical_factor_bundles(
    *,
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
    H_adj: pd.DataFrame | None = None,
    L_adj: pd.DataFrame | None = None,
    C_adj: pd.DataFrame | None = None,
    valid_bar: pd.DataFrame | None = None,
    selected_indicators: Sequence[str] | None = None,
    selected_factors: Sequence[str] | None = None,
    ama_state_cache_path: str | Path | None = None,
    ama_state_only: bool = False,
) -> Iterator[dict[str, object]]:
    """按指标逐个生成 bundle，避免同时持有全部 401 个矩阵。"""
    adjusted = (
        H_adj if H_adj is not None else H,
        L_adj if L_adj is not None else L,
        C_adj if C_adj is not None else C,
    )
    adjusted_matches_primary = (
        adjusted[0] is H and adjusted[1] is L and adjusted[2] is C
    )
    target_factors = {str(name).strip() for name in (selected_factors or []) if str(name).strip()}

    for indicator in _normalize_indicators(selected_indicators):
        if target_factors and not any(name.startswith(f"{indicator}_") for name in target_factors):
            continue

        if indicator == "AMA" and ama_state_cache_path is not None:
            ama_close = C
            mask = None
            if valid_bar is not None:
                mask = valid_bar.reindex(index=C.index, columns=C.columns).fillna(False)
                # AMA 是按有效 K 线递归的状态指标。前向填充价格只用于矩阵对齐，
                # 停牌或缺失交易日不能作为一根重复价格 K 线推进状态。
                ama_close = C.where(mask)
            raw = _compute_indicator(
                indicator,
                O=O,
                H=H,
                L=L,
                C=ama_close,
                V=V,
                H_adj=adjusted[0],
                L_adj=adjusted[1],
                C_adj=adjusted[2],
                ama_state_cache_path=ama_state_cache_path,
                ama_state_only=ama_state_only,
            )
            prefixed = _validate_and_prefix(indicator, raw, index=C.index, columns=C.columns)
            if mask is not None:
                prefixed = {name: frame.where(mask, 0.0) for name, frame in prefixed.items()}
            factor_labels = {name: _factor_display_name(name) for name in prefixed}
            output = {
                "bundle_id": BUNDLE_ID,
                "indicator": indicator,
                "factor_dfs": prefixed,
                "factor_name_map": {label: name for name, label in factor_labels.items()},
                "factor_labels": factor_labels,
            }
        elif valid_bar is not None and adjusted_matches_primary:
            _, outputs = compute_bundles_with_valid_bar(
                _compute_single_bundle_raw,
                O=O,
                H=H,
                L=L,
                C=C,
                V=V,
                selected_bundles=[indicator],
                valid_bar=valid_bar,
            )
            output = outputs[0]
        else:
            raw = _compute_indicator(
                indicator,
                O=O,
                H=H,
                L=L,
                C=C,
                V=V,
                H_adj=adjusted[0],
                L_adj=adjusted[1],
                C_adj=adjusted[2],
            )
            prefixed = _validate_and_prefix(indicator, raw, index=C.index, columns=C.columns)
            if valid_bar is not None:
                mask = valid_bar.reindex(index=C.index, columns=C.columns).fillna(False)
                prefixed = {name: frame.where(mask) for name, frame in prefixed.items()}
            factor_labels = {name: _factor_display_name(name) for name in prefixed}
            output = {
                "bundle_id": BUNDLE_ID,
                "indicator": indicator,
                "factor_dfs": prefixed,
                "factor_name_map": {label: name for name, label in factor_labels.items()},
                "factor_labels": factor_labels,
            }

        if target_factors:
            factor_dfs = {
                name: frame
                for name, frame in output["factor_dfs"].items()
                if name in target_factors
            }
            if not factor_dfs:
                continue
            output = {
                **output,
                "factor_dfs": factor_dfs,
                "factor_name_map": {
                    label: name
                    for label, name in output["factor_name_map"].items()
                    if name in factor_dfs
                },
                "factor_labels": {
                    name: label
                    for name, label in output["factor_labels"].items()
                    if name in factor_dfs
                },
            }
        yield output


def _module_signature() -> dict[str, str]:
    bundle_stat = Path(__file__).stat()
    signature: dict[str, str] = {
        "bundle": f"{Path(__file__).name}:{bundle_stat.st_size}:{bundle_stat.st_mtime_ns}"
    }
    for indicator in INDICATOR_NAMES:
        path = _MODULE_DIR / f"{indicator}.py"
        stat = path.stat()
        signature[indicator] = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"
    return signature


def _synthetic_matrices() -> tuple[pd.DataFrame, ...]:
    index = pd.date_range("2024-01-01", periods=160, freq="B")
    columns = ["SYNTH_A.SZ", "SYNTH_B.SH"]
    rng = np.random.default_rng(20260722)
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, (len(index), len(columns))), axis=0),
        index=index,
        columns=columns,
    )
    open_ = close + rng.normal(0.0, 0.3, close.shape)
    high = pd.DataFrame(np.maximum(open_, close), index=index, columns=columns) + 1.0
    low = pd.DataFrame(np.minimum(open_, close), index=index, columns=columns) - 1.0
    volume = pd.DataFrame(
        rng.integers(10_000, 1_000_000, close.shape), index=index, columns=columns
    ).astype(float)
    return open_, high, low, close, volume


def _discover_factor_ids() -> list[str]:
    O, H, L, C, V = _synthetic_matrices()
    factor_ids: list[str] = []
    for output in iter_pure_technical_factor_bundles(O=O, H=H, L=L, C=C, V=V):
        factor_ids.extend(output["factor_dfs"].keys())
    if len(factor_ids) != len(set(factor_ids)):
        duplicates = sorted({name for name in factor_ids if factor_ids.count(name) > 1})
        raise ValueError(f"纯技术面因子唯一名冲突: {duplicates}")
    return factor_ids


def get_factor_catalog(
    *,
    force_refresh: bool = False,
    cache_path: str | Path = DEFAULT_CATALOG_CACHE_PATH,
) -> dict[str, object]:
    global _CATALOG_MEMORY, _CATALOG_MEMORY_SIGNATURE
    signature = _module_signature()
    path = Path(cache_path)

    if (
        not force_refresh
        and _CATALOG_MEMORY is not None
        and _CATALOG_MEMORY_SIGNATURE == signature
    ):
        if not path.is_file():
            _write_catalog_cache(path, signature=signature, catalog=_CATALOG_MEMORY)
        return dict(_CATALOG_MEMORY)
    if not force_refresh and path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("signature") == signature and isinstance(cached.get("factor_ids"), list):
                factor_ids = [str(name) for name in cached["factor_ids"]]
                catalog = _build_catalog(factor_ids)
                _CATALOG_MEMORY = catalog
                _CATALOG_MEMORY_SIGNATURE = signature
                if not isinstance(cached.get("factor_labels"), dict) or not isinstance(cached.get("groups"), list):
                    _write_catalog_cache(path, signature=signature, catalog=catalog)
                return dict(catalog)
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    factor_ids = _discover_factor_ids()
    catalog = _build_catalog(factor_ids)
    _write_catalog_cache(path, signature=signature, catalog=catalog)
    _CATALOG_MEMORY = catalog
    _CATALOG_MEMORY_SIGNATURE = signature
    return dict(catalog)


def get_factor_lookback_config() -> dict[str, object]:
    factor_ids = list(get_factor_catalog()["factor_name_map"].values())
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": DEFAULT_LOOKBACK_DAYS,
        "factor_lookback_days": {name: DEFAULT_LOOKBACK_DAYS for name in factor_ids},
        "full_history_factor_keys": sorted(name for name in factor_ids if name.startswith("AMA_")),
    }


__all__ = [
    "BUNDLE_ID",
    "INDICATOR_NAMES",
    "get_factor_catalog",
    "get_factor_lookback_config",
    "iter_pure_technical_factor_bundles",
]
