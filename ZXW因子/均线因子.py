from __future__ import annotations

from typing import Any, Iterable
import warnings

import numpy as np
import pandas as pd


def _cross_down_price(price: pd.DataFrame, ma_line: pd.DataFrame) -> pd.DataFrame:
    """
    死叉定义：当日价格 <= 均线，且前一日价格 > 均线。
    """
    prev_price = price.shift(1)
    prev_ma = ma_line.shift(1)
    return (price <= ma_line) & (prev_price > prev_ma)


def build_moving_average_factor_bundle(
    C: pd.DataFrame,
    windows: Iterable[int] = (5, 10, 15, 20, 30, 40, 50, 60, 70, 120),
) -> dict[str, Any]:
    index, columns = C.index, C.columns

    win_list = sorted({int(w) for w in windows if int(w) > 0})
    if len(win_list) < 2:
        raise ValueError("windows 至少需要包含两个正整数。")

    ma_map: dict[int, pd.DataFrame] = {
        w: C.rolling(window=w, min_periods=1).mean() for w in win_list
    }

    factor_dfs: dict[str, pd.DataFrame] = {}
    factor_name_map: dict[str, str] = {}

    for w in win_list:
        eng_name = f"ma_{w}"
        ch_name = f"MA{w}"
        factor_dfs[eng_name] = ma_map[w].reindex(index=index, columns=columns).astype(float)
        factor_name_map[ch_name] = eng_name

    close_price = C.reindex(index=index, columns=columns).astype(float)
    for w in win_list:
        signal_down = _cross_down_price(close_price, ma_map[w]).reindex(index=index, columns=columns)
        eng_name_down = f"dead_cross_price_ma{w}"
        ch_name_down = f"价格下穿MA{w}"
        factor_dfs[eng_name_down] = signal_down.astype(float)
        factor_name_map[ch_name_down] = eng_name_down

    # 额外保留指定的均线下穿均线信号
    extra_pairs = [(5, 10), (5, 15), (15, 20)]
    for short_w, long_w in extra_pairs:
        if short_w not in ma_map or long_w not in ma_map:
            continue
        signal_down = (ma_map[short_w] <= ma_map[long_w]) & (
            ma_map[short_w].shift(1) > ma_map[long_w].shift(1)
        )
        eng_name_down = f"dead_cross_ma{short_w}_ma{long_w}"
        ch_name_down = f"MA{short_w}下穿MA{long_w}"
        factor_dfs[eng_name_down] = signal_down.reindex(index=index, columns=columns).astype(float)
        factor_name_map[ch_name_down] = eng_name_down

    zxw_ma = build_ma_class_zxw_bundle(C)
    factor_dfs.update(zxw_ma["factor_dfs"])
    factor_name_map.update(zxw_ma["factor_name_map"])

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


def build_ma_class_zxw_bundle(C: pd.DataFrame) -> dict[str, Any]:
    """
    通达信「均线类」0～6、全套中间量与 MA13/20/21/30/34/60/120/180/250。
    MA/STD 满窗（min_periods=周期）；无效值落盘为 0。
    """
    index, columns = C.index, C.columns
    C = C.reindex(index=index, columns=columns).astype(float)

    def _ma(n: int) -> pd.DataFrame:
        return C.rolling(window=n, min_periods=n).mean()

    def _std20(series: pd.DataFrame) -> pd.DataFrame:
        return series.rolling(window=20, min_periods=20).std()

    def _nanmin_df(*dfs: pd.DataFrame) -> pd.DataFrame:
        arr = np.stack([d.to_numpy(dtype=float) for d in dfs], axis=0)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice encountered", category=RuntimeWarning)
            values = np.nanmin(arr, axis=0)
        return pd.DataFrame(values, index=index, columns=columns)

    def _nanmax_df(*dfs: pd.DataFrame) -> pd.DataFrame:
        arr = np.stack([d.to_numpy(dtype=float) for d in dfs], axis=0)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice encountered", category=RuntimeWarning)
            values = np.nanmax(arr, axis=0)
        return pd.DataFrame(values, index=index, columns=columns)

    def _f(df: pd.DataFrame) -> pd.DataFrame:
        return df.reindex(index=index, columns=columns).fillna(0.0).astype(float)

    def _sig(df: pd.DataFrame) -> pd.DataFrame:
        return df.fillna(False).astype(float)

    ma13 = _ma(13)
    ma20 = _ma(20)
    ma21 = _ma(21)
    ma30 = _ma(30)
    ma34 = _ma(34)
    ma60 = _ma(60)
    ma120 = _ma(120)
    ma180 = _ma(180)
    ma250 = _ma(250)

    ma_min = _nanmin_df(ma13, ma20, ma30, ma60, ma120, ma180, ma250)
    ma_max = _nanmax_df(ma13, ma20, ma30, ma60, ma120, ma180, ma250)
    ma_second_max = _nanmax_df(ma13, ma20, ma30, ma60, ma120)

    std_ma13_20 = _std20(ma13)
    std_ma20_20 = _std20(ma20)
    std_ma30_20 = _std20(ma30)
    std_ma60_20 = _std20(ma60)
    chu_jun_bo_dong = _nanmax_df(
        _nanmax_df(std_ma13_20, std_ma20_20),
        _nanmax_df(std_ma30_20, std_ma60_20),
    )
    chu_jun_bo_dong = (chu_jun_bo_dong / ma20.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    duo_tou_a_jia = (
        (C > ma13) & (ma13 > ma34) & (ma34 > ma60) & (ma60 > ma120) & (ma120 > ma250)
    )
    duo_a = C >= ma_max

    zhi_you_250_ya1 = (C < ma250) & (C > ma13) & (C > ma34) & (C > ma60) & (C > ma120)
    zhi_you_250_ya21 = (C < ma250) & (C > ma120) & (ma13 > ma34) & (ma34 > ma60)
    zhi_250_ya1_zhi_ping = (C < ma250) & (C > ma120) & (chu_jun_bo_dong < 0.06)
    zhi_you_250_ya22 = (
        (C < ma250) & (C > ma120) & (ma13 < ma34) & (ma34 < ma60) & (ma60 < ma120)
    )
    zhi_you_250_ya23 = (
        (C < ma250)
        & (C > ma120)
        & (C > ma13)
        & (C > ma34)
        & (C > ma60)
        & ~zhi_you_250_ya21
        & ~zhi_you_250_ya22
    )

    xiao_60_duo = (C < ma250) & (C < ma120) & (C > ma13) & (ma13 > ma34) & (ma34 > ma60)
    xiao_60_kong = (ma13 < ma34) & (ma34 < ma60) & (ma60 < ma120)
    xiao_30_duo = (ma13 > ma20) & (ma20 > ma34) & (C > ma34)
    nian_ban_shuang_ya31 = ((C < ma250) | (C < ma120)) & (chu_jun_bo_dong < 0.06)

    zhi_cheng1 = C > ma13
    zhi_cheng2 = C > ma21
    zhi_cheng3 = C > ma34
    zhi_cheng4 = C > ma60
    zhi_cheng5 = C > ma120
    zhi_cheng6 = C > ma250
    quan_kong_tou = (ma13 <= ma34) & (ma34 <= ma60) & (ma60 <= ma120) & (ma120 <= ma250)
    zhi_cheng_shu = (
        zhi_cheng1.astype(int)
        + zhi_cheng2.astype(int)
        + zhi_cheng3.astype(int)
        + zhi_cheng4.astype(int)
        + zhi_cheng5.astype(int)
        + zhi_cheng6.astype(int)
    )
    da2_jun_zhi_cheng = zhi_cheng5 & zhi_cheng6 & (ma120 >= ma250)
    zhong_duo_zhi = (zhi_cheng_shu >= 4) & ~quan_kong_tou
    xiao_zhi = (zhi_cheng_shu <= 3) & (zhi_cheng_shu >= 2) & ~quan_kong_tou
    fei_quan_po = ~(C < ma_min * 0.975)

    c1 = duo_tou_a_jia & fei_quan_po
    c2 = duo_a & fei_quan_po
    c3 = (zhi_you_250_ya1 | zhong_duo_zhi) & fei_quan_po
    c4 = (zhi_you_250_ya21 | da2_jun_zhi_cheng) & fei_quan_po
    c5 = (zhi_you_250_ya23 | xiao_60_duo | zhi_250_ya1_zhi_ping) & fei_quan_po
    c6 = (zhi_you_250_ya22 | nian_ban_shuang_ya31 | xiao_zhi | xiao_30_duo) & fei_quan_po

    def _bn(df: pd.DataFrame) -> np.ndarray:
        return df.reindex(index=index, columns=columns).fillna(False).to_numpy(dtype=bool)

    ma_lei = np.where(
        _bn(c1),
        1.0,
        np.where(
            _bn(c2),
            2.0,
            np.where(
                _bn(c3),
                3.0,
                np.where(
                    _bn(c4),
                    4.0,
                    np.where(_bn(c5), 5.0, np.where(_bn(c6), 6.0, 0.0)),
                ),
            ),
        ),
    )
    ma_lei_df = pd.DataFrame(ma_lei, index=index, columns=columns).fillna(0.0)

    factor_dfs: dict[str, pd.DataFrame] = {
        "ma_13_zxw": _f(ma13),
        "ma_20_zxw": _f(ma20),
        "ma_21_zxw": _f(ma21),
        "ma_30_zxw": _f(ma30),
        "ma_34_zxw": _f(ma34),
        "ma_60_zxw": _f(ma60),
        "ma_120_zxw": _f(ma120),
        "ma_180_zxw": _f(ma180),
        "ma_250_zxw": _f(ma250),
        "ma_min_zxw": _f(ma_min),
        "ma_max_zxw": _f(ma_max),
        "ma_second_max_zxw": _f(ma_second_max),
        "chu_jun_bo_dong_max_zxw": _f(chu_jun_bo_dong),
        "duo_tou_a_jia_zxw": _sig(duo_tou_a_jia),
        "duo_a_zxw": _sig(duo_a),
        "zhi_you_250_ya1_zxw": _sig(zhi_you_250_ya1),
        "zhi_you_250_ya21_zxw": _sig(zhi_you_250_ya21),
        "zhi_250_ya1_zhi_ping_zxw": _sig(zhi_250_ya1_zhi_ping),
        "zhi_you_250_ya22_zxw": _sig(zhi_you_250_ya22),
        "zhi_you_250_ya23_zxw": _sig(zhi_you_250_ya23),
        "xiao_60_duo_zxw": _sig(xiao_60_duo),
        "xiao_60_kong_zxw": _sig(xiao_60_kong),
        "xiao_30_duo_zxw": _sig(xiao_30_duo),
        "nian_ban_shuang_ya31_zxw": _sig(nian_ban_shuang_ya31),
        "zhi_cheng1_zxw": _sig(zhi_cheng1),
        "zhi_cheng2_zxw": _sig(zhi_cheng2),
        "zhi_cheng3_zxw": _sig(zhi_cheng3),
        "zhi_cheng4_zxw": _sig(zhi_cheng4),
        "zhi_cheng5_zxw": _sig(zhi_cheng5),
        "zhi_cheng6_zxw": _sig(zhi_cheng6),
        "zhi_cheng_shu_zxw": _f(zhi_cheng_shu),
        "quan_kong_tou_zxw": _sig(quan_kong_tou),
        "da2_jun_zhi_cheng_zxw": _sig(da2_jun_zhi_cheng),
        "zhong_duo_zhi_zxw": _sig(zhong_duo_zhi),
        "xiao_zhi_zxw": _sig(xiao_zhi),
        "fei_quan_po_zxw": _sig(fei_quan_po),
        "ma_class_zxw": _f(ma_lei_df),
    }
    factor_name_map: dict[str, str] = {
        "MA13": "ma_13_zxw",
        "MA20": "ma_20_zxw",
        "MA21": "ma_21_zxw",
        "MA30": "ma_30_zxw",
        "MA34": "ma_34_zxw",
        "MA60": "ma_60_zxw",
        "MA120": "ma_120_zxw",
        "MA180": "ma_180_zxw",
        "MA250": "ma_250_zxw",
        "均线最小值": "ma_min_zxw",
        "均线最大值": "ma_max_zxw",
        "均线次大值": "ma_second_max_zxw",
        "初均波动最大值": "chu_jun_bo_dong_max_zxw",
        "多头A加": "duo_tou_a_jia_zxw",
        "多A": "duo_a_zxw",
        "只有250压1": "zhi_you_250_ya1_zxw",
        "只有250压21": "zhi_you_250_ya21_zxw",
        "只250压1支平": "zhi_250_ya1_zhi_ping_zxw",
        "只有250压22": "zhi_you_250_ya22_zxw",
        "只有250压23": "zhi_you_250_ya23_zxw",
        "小60多": "xiao_60_duo_zxw",
        "小60空": "xiao_60_kong_zxw",
        "小30多": "xiao_30_duo_zxw",
        "年半双压31": "nian_ban_shuang_ya31_zxw",
        "支撑1": "zhi_cheng1_zxw",
        "支撑2": "zhi_cheng2_zxw",
        "支撑3": "zhi_cheng3_zxw",
        "支撑4": "zhi_cheng4_zxw",
        "支撑5": "zhi_cheng5_zxw",
        "支撑6": "zhi_cheng6_zxw",
        "支撑数总计": "zhi_cheng_shu_zxw",
        "全空头": "quan_kong_tou_zxw",
        "大2均支撑": "da2_jun_zhi_cheng_zxw",
        "中多支": "zhong_duo_zhi_zxw",
        "小支": "xiao_zhi_zxw",
        "非全破": "fei_quan_po_zxw",
        "均线类": "ma_class_zxw",
    }
    return {"factor_dfs": factor_dfs, "factor_name_map": factor_name_map}


BUNDLE_ID = "moving_average"
_DEFAULT_LOOKBACK_DAYS = 60

_DEFAULT_WINDOWS = (5, 10, 15, 20, 30, 40, 50, 60, 70, 120)
FACTOR_LOOKBACK_DAYS: dict[str, int] = {}
for _w in _DEFAULT_WINDOWS:
    FACTOR_LOOKBACK_DAYS[f"ma_{_w}"] = int(_w)
for _w in _DEFAULT_WINDOWS:
    FACTOR_LOOKBACK_DAYS[f"dead_cross_price_ma{_w}"] = int(_w) + 1
FACTOR_LOOKBACK_DAYS["dead_cross_ma5_ma10"] = 11
FACTOR_LOOKBACK_DAYS["dead_cross_ma5_ma15"] = 16
FACTOR_LOOKBACK_DAYS["dead_cross_ma15_ma20"] = 21
# 通达信满窗：MA250；STD(MA60,20) 约需 60+20-1=79 根
_ZXW_CHUJUN_LOOKBACK = 79
_ZXW_MA_CLASS_LOOKBACK = 280

_ZXW_MA_LINE_LOOKBACK: dict[str, int] = {
    "ma_13_zxw": 13,
    "ma_20_zxw": 20,
    "ma_21_zxw": 21,
    "ma_30_zxw": 30,
    "ma_34_zxw": 34,
    "ma_60_zxw": 60,
    "ma_120_zxw": 120,
    "ma_180_zxw": 180,
    "ma_250_zxw": 250,
    "ma_min_zxw": 250,
    "ma_max_zxw": 250,
    "ma_second_max_zxw": 120,
    "chu_jun_bo_dong_max_zxw": _ZXW_CHUJUN_LOOKBACK,
}

_ZXW_MA_CLASS_FACTOR_KEYS = (
    "ma_13_zxw",
    "ma_20_zxw",
    "ma_21_zxw",
    "ma_30_zxw",
    "ma_34_zxw",
    "ma_60_zxw",
    "ma_120_zxw",
    "ma_180_zxw",
    "ma_250_zxw",
    "ma_min_zxw",
    "ma_max_zxw",
    "ma_second_max_zxw",
    "chu_jun_bo_dong_max_zxw",
    "duo_tou_a_jia_zxw",
    "duo_a_zxw",
    "zhi_you_250_ya1_zxw",
    "zhi_you_250_ya21_zxw",
    "zhi_250_ya1_zhi_ping_zxw",
    "zhi_you_250_ya22_zxw",
    "zhi_you_250_ya23_zxw",
    "xiao_60_duo_zxw",
    "xiao_60_kong_zxw",
    "xiao_30_duo_zxw",
    "nian_ban_shuang_ya31_zxw",
    "zhi_cheng1_zxw",
    "zhi_cheng2_zxw",
    "zhi_cheng3_zxw",
    "zhi_cheng4_zxw",
    "zhi_cheng5_zxw",
    "zhi_cheng6_zxw",
    "zhi_cheng_shu_zxw",
    "quan_kong_tou_zxw",
    "da2_jun_zhi_cheng_zxw",
    "zhong_duo_zhi_zxw",
    "xiao_zhi_zxw",
    "fei_quan_po_zxw",
    "ma_class_zxw",
)

for _k, _days in _ZXW_MA_LINE_LOOKBACK.items():
    FACTOR_LOOKBACK_DAYS[_k] = int(_days)
for _k in _ZXW_MA_CLASS_FACTOR_KEYS:
    if _k not in FACTOR_LOOKBACK_DAYS:
        FACTOR_LOOKBACK_DAYS[_k] = _ZXW_MA_CLASS_LOOKBACK


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(
            _DEFAULT_LOOKBACK_DAYS,
            _ZXW_MA_CLASS_LOOKBACK,
            max(FACTOR_LOOKBACK_DAYS.values(), default=0),
        ),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
