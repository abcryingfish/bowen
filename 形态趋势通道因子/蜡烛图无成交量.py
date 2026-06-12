import os
import time

import pandas as pd
import numpy as np

try:
    from numba import njit, prange

    _NUMBA_AVAILABLE = True
except Exception:  # pragma: no cover
    _NUMBA_AVAILABLE = False
    prange = range  # type: ignore


def _timing_enabled() -> bool:
    return os.getenv("ZXW_FACTOR_DEBUG_TIMING", "0") == "1"


def _use_numba(n_rows: int, n_cols: int) -> bool:
    if os.getenv("ZXW_DISABLE_NUMBA", "0") == "1" or not _NUMBA_AVAILABLE:
        return False
    raw = os.getenv("ZXW_FACTOR_MIN_SIZE", "50000").strip()
    min_size = max(1, int(raw or "50000"))
    return n_rows * n_cols >= min_size


def _rolling_min_py(arr: np.ndarray, window: int) -> np.ndarray:
    n_rows, n_cols = arr.shape
    window = max(int(window), 1)
    out = np.empty((n_rows, n_cols), dtype=np.float64)
    out.fill(np.nan)
    for j in range(n_cols):
        for i in range(n_rows):
            start = max(0, i - window + 1)
            has_val = False
            vmin = 0.0
            for k in range(start, i + 1):
                v = arr[k, j]
                if np.isnan(v):
                    continue
                if not has_val or v < vmin:
                    vmin = v
                    has_val = True
            if has_val:
                out[i, j] = vmin
    return out


def _rolling_max_py(arr: np.ndarray, window: int) -> np.ndarray:
    n_rows, n_cols = arr.shape
    window = max(int(window), 1)
    out = np.empty((n_rows, n_cols), dtype=np.float64)
    out.fill(np.nan)
    for j in range(n_cols):
        for i in range(n_rows):
            start = max(0, i - window + 1)
            has_val = False
            vmax = 0.0
            for k in range(start, i + 1):
                v = arr[k, j]
                if np.isnan(v):
                    continue
                if not has_val or v > vmax:
                    vmax = v
                    has_val = True
            if has_val:
                out[i, j] = vmax
    return out


def _rolling_all_true_py(arr: np.ndarray, window: int, shift_after: int) -> np.ndarray:
    n_rows, n_cols = arr.shape
    window = max(int(window), 1)
    shift_after = max(int(shift_after), 0)
    out = np.zeros((n_rows, n_cols), dtype=np.float64)
    for j in range(n_cols):
        csum = np.zeros(n_rows + 1, dtype=np.int64)
        col = arr[:, j]
        for i in range(n_rows):
            csum[i + 1] = csum[i] + (1 if col[i] else 0)
        for i in range(window - 1, n_rows):
            if csum[i + 1] - csum[i + 1 - window] == window:
                out[i, j] = 1.0
    if shift_after and shift_after < n_rows:
        shifted = np.zeros_like(out)
        shifted[shift_after:, :] = out[: n_rows - shift_after, :]
        return shifted
    return out


if _NUMBA_AVAILABLE:

    @njit(cache=False, fastmath=False, parallel=True)
    def _rolling_min_numba(arr: np.ndarray, window: int) -> np.ndarray:
        n_rows, n_cols = arr.shape
        window = max(window, 1)
        out = np.empty((n_rows, n_cols), dtype=np.float64)
        for j in prange(n_cols):
            for i in range(n_rows):
                start = 0
                if i >= window - 1:
                    start = i - window + 1
                has_val = False
                vmin = 0.0
                for k in range(start, i + 1):
                    v = arr[k, j]
                    if np.isnan(v):
                        continue
                    if not has_val or v < vmin:
                        vmin = v
                        has_val = True
                if has_val:
                    out[i, j] = vmin
                else:
                    out[i, j] = np.nan
        return out

    @njit(cache=False, fastmath=False, parallel=True)
    def _rolling_max_numba(arr: np.ndarray, window: int) -> np.ndarray:
        n_rows, n_cols = arr.shape
        window = max(window, 1)
        out = np.empty((n_rows, n_cols), dtype=np.float64)
        for j in prange(n_cols):
            for i in range(n_rows):
                start = 0
                if i >= window - 1:
                    start = i - window + 1
                has_val = False
                vmax = 0.0
                for k in range(start, i + 1):
                    v = arr[k, j]
                    if np.isnan(v):
                        continue
                    if not has_val or v > vmax:
                        vmax = v
                        has_val = True
                if has_val:
                    out[i, j] = vmax
                else:
                    out[i, j] = np.nan
        return out

    @njit(cache=False, fastmath=False, parallel=True)
    def _rolling_all_true_numba(arr: np.ndarray, window: int, shift_after: int) -> np.ndarray:
        n_rows, n_cols = arr.shape
        window = max(window, 1)
        out = np.zeros((n_rows, n_cols), dtype=np.float64)
        for j in prange(n_cols):
            csum = np.zeros(n_rows + 1, dtype=np.int64)
            for i in range(n_rows):
                if arr[i, j]:
                    csum[i + 1] = csum[i] + 1
                else:
                    csum[i + 1] = csum[i]
            for i in range(window - 1, n_rows):
                if csum[i + 1] - csum[i + 1 - window] == window:
                    out[i, j] = 1.0
        if shift_after > 0 and shift_after < n_rows:
            shifted = np.zeros_like(out)
            shifted[shift_after:, :] = out[: n_rows - shift_after, :]
            return shifted
        return out


def _rolling_min_frame(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    arr = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(arr.shape[0], arr.shape[1]):
        try:
            values = _rolling_min_numba(arr, int(window))
            return pd.DataFrame(values, index=frame.index, columns=frame.columns)
        except Exception:
            pass
    return frame.rolling(int(window), min_periods=1).min()


def _rolling_max_frame(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    arr = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(arr.shape[0], arr.shape[1]):
        try:
            values = _rolling_max_numba(arr, int(window))
            return pd.DataFrame(values, index=frame.index, columns=frame.columns)
        except Exception:
            pass
    return frame.rolling(int(window), min_periods=1).max()


def _rolling_all_true_frame(mask: pd.DataFrame, window: int, shift_after: int = 0) -> pd.DataFrame:
    arr = np.ascontiguousarray(mask.to_numpy(dtype=bool, copy=False))
    if _use_numba(arr.shape[0], arr.shape[1]):
        try:
            values = _rolling_all_true_numba(arr, int(window), int(shift_after))
            return pd.DataFrame(values, index=mask.index, columns=mask.columns)
        except Exception:
            pass
    values = _rolling_all_true_py(arr, int(window), int(shift_after))
    return pd.DataFrame(values, index=mask.index, columns=mask.columns)


class _OhlcContext:
    """OHLC 预计算缓存：rolling 极值与常用 K 线派生量。"""

    __slots__ = (
        "open",
        "high",
        "low",
        "close",
        "index",
        "columns",
        "_roll_min_close",
        "_roll_max_close",
        "_roll_min_low",
        "_roll_max_high",
        "_body",
        "_lower_shadow",
        "_upper_shadow",
    )

    def __init__(
        self,
        open_prices: pd.DataFrame,
        high_prices: pd.DataFrame,
        low_prices: pd.DataFrame,
        close_prices: pd.DataFrame,
    ) -> None:
        self.open = open_prices
        self.high = high_prices
        self.low = low_prices
        self.close = close_prices
        self.index = close_prices.index
        self.columns = close_prices.columns
        self._roll_min_close: dict[int, pd.DataFrame] = {}
        self._roll_max_close: dict[int, pd.DataFrame] = {}
        self._roll_min_low: dict[int, pd.DataFrame] = {}
        self._roll_max_high: dict[int, pd.DataFrame] = {}
        self._body: pd.DataFrame | None = None
        self._lower_shadow: pd.DataFrame | None = None
        self._upper_shadow: pd.DataFrame | None = None

    def min_close(self, window: int) -> pd.DataFrame:
        if window not in self._roll_min_close:
            self._roll_min_close[window] = _rolling_min_frame(self.close, window)
        return self._roll_min_close[window]

    def max_close(self, window: int) -> pd.DataFrame:
        if window not in self._roll_max_close:
            self._roll_max_close[window] = _rolling_max_frame(self.close, window)
        return self._roll_max_close[window]

    def min_low(self, window: int) -> pd.DataFrame:
        if window not in self._roll_min_low:
            self._roll_min_low[window] = _rolling_min_frame(self.low, window)
        return self._roll_min_low[window]

    def max_high(self, window: int) -> pd.DataFrame:
        if window not in self._roll_max_high:
            self._roll_max_high[window] = _rolling_max_frame(self.high, window)
        return self._roll_max_high[window]

    @property
    def body(self) -> pd.DataFrame:
        if self._body is None:
            self._body = abs(self.close - self.open)
        return self._body

    @property
    def lower_shadow(self) -> pd.DataFrame:
        if self._lower_shadow is None:
            self._lower_shadow = np.minimum(self.open, self.close) - self.low
        return self._lower_shadow

    @property
    def upper_shadow(self) -> pd.DataFrame:
        if self._upper_shadow is None:
            self._upper_shadow = self.high - np.maximum(self.open, self.close)
        return self._upper_shadow


class Pattern:
    def __init__(self):
        # 信号强度映射表
        self.signal_strength = pattern_signal_weights = {
            "harami_bullish": 0.5,   # 1. 看涨孕线，下跌趋势中后一根小K线实体完全包含前一根大阴线实体，底部看涨
            "harami_bearish": -0.5,   # 1. 看跌孕线，上涨趋势中后一根小K线实体完全包含前一根大阳线实体，顶部看跌
            "morning_star_doji": 0.7,   # 2. 十字晨星，下跌趋势末端出现十字星且前后K线形成“先跌后涨”结构，底部反转看涨
            "hammer": 0.6,   # 3. 锤子线，下跌趋势底部出现单根长下影、短实体（实体位于K线上半部分）K线，底部看涨
            "hanging_man": -0.6,   # 4. 上吊线，上涨趋势顶部出现单根长下影、短实体（实体位于K线上半部分）K线，顶部看跌
            "engulfing_bullish": 0.8,   # 5. 看涨吞没，下跌趋势中后一根大阳线完全吞没前一根阴线实体，底部反转看涨
            "engulfing_bearish": -0.8,   # 5. 看跌吞没，上涨趋势中后一根大阴线完全吞没前一根阳线实体，顶部反转看跌
            "dark_cloud_cover": -0.7,   # 6. 乌云盖顶，上涨趋势中前一根大阳线后接高开低走大阴线（阴线实体深入阳线1/2以上），顶部看跌
            "piercing": 0.7,   # 7. 刺透形态，下跌趋势中前一根大阴线后接低开高走大阳线（阳线实体深入阴线1/2以上），底部看涨
            "morning_star": 0.8,   # 8. 启明星，下跌趋势中出现“大阴线→小实体K线→大阳线”组合（小实体与前后跳空），底部反转看涨
            "evening_star": -0.8,   # 9. 黄昏星，上涨趋势中出现“大阳线→小实体K线→大阴线”组合（小实体与前后跳空），顶部反转看跌
            "evening_star_doji": -0.7,   # 10. 十字幕星，黄昏星形态中“小实体K线”替换为十字星，上涨趋势顶部看跌
            "abandoned_baby_bullish": 0.9,   # 11. 看涨弃婴，下跌趋势末端出现跳空十字星且前后均有跳空缺口，底部反转看涨
            "abandoned_baby_bearish": -0.9,   # 11. 看跌弃婴，上涨趋势末端出现跳空十字星且前后均有跳空缺口，顶部反转看跌
            "harami_doji_bullish": 0.6,   # 12. 看涨十字孕线，后一根十字星实体完全包含在前一根大阴线实体内部，底部看涨
            "harami_doji_bearish": -0.6,   # 12. 看跌十字孕线，后一根十字星实体完全包含在前一根大阳线实体内部，顶部看跌
            "tweezers_top": -0.5,   # 13. 平头顶形态，两根及以上K线最高价基本一致（形成水平阻力），上涨趋势顶部看跌
            "tweezers_bottom": 0.5,   # 14. 平头底形态，两根及以上K线最低价基本一致（形成水平支撑），下跌趋势底部看涨
            "belt_hold_bullish": 0.7,   # 15. 看涨捉腰带线，开盘价为最低价且收盘价接近最高价（实体较长），单边上涨趋势看涨
            "belt_hold_bearish": -0.7,   # 16. 看跌捉腰带线，开盘价为最高价且收盘价接近最低价（实体较长），单边下跌趋势看跌
            "counterattack_bullish": 0.6,   # 17. 看涨反击线，下跌趋势中阴线后接阳线（收盘价接近前一天阴线收盘价），多头反击看涨
            "counterattack_bearish": -0.6,   # 18. 看跌反击线，上涨趋势中阳线后接阴线（收盘价接近前一天阳线收盘价），空头反击看跌
            "two_crows": -0.6,   # 19. 两只乌鸦，上涨趋势中前一根大阳线后接两根高开低走阴线（第二根包含第一根），顶部看跌延续
            "three_crows": -0.7,   # 20. 三只乌鸦，上涨趋势末端出现三根连续下跌大阴线（每根收盘价低于前一根），顶部看跌反转
            "three_white_soldiers": 0.7,   # 21. 白色三兵，下跌趋势末端出现三根连续上涨大阳线（每根收盘价高于前一根），底部看涨反转
            "tower_top": -0.6,   # 22. 塔型顶部，上涨趋势中K线从“大阳线→小实体K线→大阴线”过渡（形态如塔尖），顶部看跌反转
            "tower_bottom": 0.6,   # 23. 塔型底部，下跌趋势中K线从“大阴线→小实体K线→大阳线”过渡（形态如塔基），底部看涨反转
            "three_mountains": -0.7,   # 24. 三山形态，上涨趋势中形成三个依次抬高的高点（第三座山成交量萎缩），顶部看跌反转
            "three_rivers": 0.7,   # 25. 三川形态，下跌趋势中形成三个依次降低的低点（第三条川成交量萎缩），底部看涨反转
            "rising_three_methods": 0.5,   # 26. 上升三法，上涨趋势中一根大阳线后接三根小阴线（均在大阳线实体范围内），第五根大阳线破前高，趋势延续看涨
            "falling_three_methods": -0.5,   # 27. 下降三法，下跌趋势中一根大阴线后接三根小阳线（均在大阴线实体范围内），第五根大阴线破前低，趋势延续看跌
            "bullish_marubozu": 0.8,   # 28. 多头母子线，上涨趋势中前一根大阳线后接一根小阳线（小阳线实体包含在大阳线内），趋势延续看涨
            "bearish_marubozu": -0.8,   # 29. 空头母子线，下跌趋势中前一根大阴线后接一根小阴线（小阴线实体包含在大阴线内），趋势延续看跌
            "pregnant_marubozu": -0.3,   # 30. 孕母线，上涨趋势中前一根大阳线后接一根小阴线（小阴线实体包含在大阳线内，又称负面母子线），趋势犹豫看跌
            "tombstone_marubozu": 0.5,   # 31. 墓碑线，下跌趋势中前一根大阴线后接一根小阳线（小阳线实体包含在大阴线内，又称正面母子线），趋势犹豫看涨
            "three_inside_up": 0.7,   # 32. 三内部上涨线，下跌趋势中“短阴线→包含型阳线→突破阳线”组合，底部看涨反转
            "three_inside_down": -0.7,   # 33. 三内部下跌线，上涨趋势中“短阳线→包含型阴线→突破阴线”组合，顶部看跌反转
            "doji_pause": 0.1,   # 34. 停顿线，上涨趋势中连续两根大阳线后出现小阳线或十字星（实体较小），趋势休整弱看涨
            "golden_needle_bottom": 0.8,   # 35. 金针探底，20-25日低位出现单根长下影线十字星（影线长度为实体3倍以上），底部反转看涨
            "rocket_launch": 0.9,   # 36. 火箭发射，底部区域出现大振幅、小实体、长影线的阳线（25天左右效果佳），底部快速上涨看涨
            "man_jiang_hong": 0.8,   # 37. 满江红，10日内至少7根阳线且日涨跌幅在-2%~3%（低振幅，25天左右+牛市环境佳），持续上涨看涨
            "hanging_man_enhanced": -0.7,   # 38. 上吊线（增强版），顶部区域出现阴线大振幅、小实体、长下影线（3/25天效果佳，5-15天效果负），顶部看跌反转
            "heaven_line": -0.7,   # 39. 天堂线，局部高点出现大振幅、长上影线的小实体K线（25天左右效果佳），顶部看跌反转
            "dark_cloud_line": -0.6,   # 40. 乌云线，上涨趋势中阳线后接高开低走大振幅长阴线（5~25天效果佳），顶部看跌反转
            "same_low_price": 0.4,   # 后面有相同高价的   41. 相同低价，连续多根K线最低价一致（误差<0.5%，形成支撑），底部看涨
            "takuri": 0.7,   # 42. 塔库里，底部区域出现单根长下影线、短上影线、小实体K线，底部反转看涨
            "false_breakout_trap_bullish": 0.5,   # 43. 看涨假突破陷阱，价格跌破支撑后快速回弹至突破前区间（成交量萎缩），底部看涨
            "false_breakout_trap_bearish": -0.5,   # 43. 看跌假突破陷阱，价格突破阻力后快速回撤至突破前区间（成交量萎缩），顶部看跌
            "short_body_candle_bullish": 0.1,   # 44. 看涨短实体蜡烛，单根K线实体很小（幅度<1%，市场犹豫），后续偏向多头弱看涨
            "short_body_candle_bearish": -0.1,   # 44. 看跌短实体蜡烛，单根K线实体很小（幅度<1%，市场犹豫），后续偏向空头弱看跌
            "long_legged_doji_bullish": 0.3,   # 45. 看涨长脚十字星，单根长上下影线十字星（实体几乎为0，关键转折点），后续偏向多头看涨
            "long_legged_doji_bearish": -0.3,   # 45. 看跌长脚十字星，单根长上下影线十字星（实体几乎为0，关键转折点），后续偏向空头看跌
            "three_outside_up": 0.8,   # 46. 三外部上涨，下跌趋势中“长阴线→吞没阳线→突破阳线”组合，强烈底部看涨反转
            "three_outside_down": -0.8,   # 47. 三外部下跌，上涨趋势中“长阳线→吞没阴线→突破阴线”组合，强烈顶部看跌反转
            "marubozu_bullish": 0.9,   # 50. 看涨光头光脚线，无上下影线的大阳线（极强多头趋势），单边力量强劲看涨
            "marubozu_bearish": -0.9,   # 51. 看跌光头光脚线，无上下影线的大阴线（极强空头趋势），单边力量强劲看跌
            # "no_shadow_bullish": 0.8,   # 52. 看涨缺影线，无上下影线的阳线（同光头光脚阳线），单边力量强劲看涨
            # "no_shadow_bearish": -0.8,   # 53. 看跌缺影线，无上下影线的阴线（同光头光脚阴线），单边力量强劲看跌
            "spinning_top_bullish": 0.1,   # 54. 看涨纺锤线，单根小实体、长上下影线K线（市场犹豫），后续偏向多头弱看涨
            "spinning_top_bearish": -0.1,   # 54. 看跌纺锤线，单根小实体、长上下影线K线（市场犹豫），后续偏向空头弱看跌
            "high_wave_bullish": 0.4,   # 55. 看涨高浪线，单根大振幅、长上下影线、小实体K线（激烈博弈），后续偏向多头弱看涨
            "high_wave_bearish": -0.4,   # 55. 看跌高浪线，单根大振幅、长上下影线、小实体K线（激烈博弈），后续偏向空头弱看跌
            "homing_pigeon_bullish": 0.5,   # 56. 看涨家鸽形态，上涨趋势大阳线后接小阴线，趋势延续看涨
            "homing_pigeon_bearish": -0.5,   # 57. 看跌家鸽形态，下跌趋势大阴线后接小阳线，趋势延续看跌
            "same_high_price": -0.4    # 58. 相同高价，连续多根K线最高价一致（误差<0.5%），阻力位看跌
}
        
        self.all_signals = list(self.signal_strength.keys())
        self._ctx: _OhlcContext | None = None
        self._ohlc_token: tuple[int, int, int, int] | None = None
        self._pattern_cache_key: tuple[str, ...] | None = None
        self._pattern_cache: dict[str, dict] = {}

    def _ensure_ohlc_context(
        self,
        open_prices: pd.DataFrame,
        high_prices: pd.DataFrame,
        low_prices: pd.DataFrame,
        close_prices: pd.DataFrame,
    ) -> None:
        token = (id(open_prices), id(high_prices), id(low_prices), id(close_prices))
        if self._ohlc_token != token:
            self._ctx = _OhlcContext(open_prices, high_prices, low_prices, close_prices)
            self._ohlc_token = token
            self._pattern_cache_key = None
            self._pattern_cache = {}

    def _min_close(self, window: int, close_prices: pd.DataFrame) -> pd.DataFrame:
        if self._ctx is not None:
            return self._ctx.min_close(window)
        return _rolling_min_frame(close_prices, window)

    def _max_close(self, window: int, close_prices: pd.DataFrame) -> pd.DataFrame:
        if self._ctx is not None:
            return self._ctx.max_close(window)
        return _rolling_max_frame(close_prices, window)

    def _min_low(self, window: int, low_prices: pd.DataFrame) -> pd.DataFrame:
        if self._ctx is not None:
            return self._ctx.min_low(window)
        return _rolling_min_frame(low_prices, window)

    def _max_high(self, window: int, high_prices: pd.DataFrame) -> pd.DataFrame:
        if self._ctx is not None:
            return self._ctx.max_high(window)
        return _rolling_max_frame(high_prices, window)

    def _kline_body(self, open_prices: pd.DataFrame, close_prices: pd.DataFrame) -> pd.DataFrame:
        if self._ctx is not None:
            return self._ctx.body
        return abs(close_prices - open_prices)

    def _kline_lower_shadow(self, open_prices: pd.DataFrame, close_prices: pd.DataFrame, low_prices: pd.DataFrame) -> pd.DataFrame:
        if self._ctx is not None:
            return self._ctx.lower_shadow
        return np.minimum(open_prices, close_prices) - low_prices

    def _kline_upper_shadow(self, open_prices: pd.DataFrame, close_prices: pd.DataFrame, high_prices: pd.DataFrame) -> pd.DataFrame:
        if self._ctx is not None:
            return self._ctx.upper_shadow
        return high_prices - np.maximum(open_prices, close_prices)

    def is_doji(self, open_prices, high_prices, low_prices, close_prices, threshold=0.01):
        """判断是否为十字星"""
        body = abs(close_prices - open_prices)
        range_size = high_prices - low_prices
        return (body / (range_size + 1e-8)) < threshold

    def is_small_candle(self, open_prices, close_prices, threshold=0.02):
        """判断是否为小实体K线"""
        body = abs(close_prices - open_prices)
        return (body / (open_prices + 1e-8)) < threshold

    def harami_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """孕线形态"""
        body1 = abs(close_prices.shift(1) - open_prices.shift(1))
        body2 = abs(close_prices - open_prices)
        range_condition = (
            (high_prices < high_prices.shift(1)) & 
            (low_prices > low_prices.shift(1))
        )
        
        downtrend = close_prices.shift(2) < close_prices.shift(5)
        harami_bullish = range_condition & (body1 > body2 * 2) & (close_prices.shift(1) < open_prices.shift(1)) & downtrend
        
        uptrend = close_prices.shift(2) > close_prices.shift(5)
        harami_bearish = range_condition & (body1 > body2 * 2) & (close_prices.shift(1) > open_prices.shift(1)) & uptrend
        
        return {
            "harami_bullish": harami_bullish.astype(float) * self.signal_strength["harami_bullish"],
            "harami_bearish": harami_bearish.astype(float) * self.signal_strength["harami_bearish"]
        }

    def morning_star_doji_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """十字晨星"""
        downtrend = close_prices.shift(2) < close_prices.shift(10)
        doji_star = self.is_doji(open_prices.shift(1), high_prices.shift(1), low_prices.shift(1), close_prices.shift(1))
        confirmation = close_prices > open_prices
        
        morning_star = downtrend & doji_star & confirmation
        
        return {"morning_star_doji": morning_star.astype(float) * self.signal_strength["morning_star_doji"]}

    def hammer_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """锤子线"""
        body = self._kline_body(open_prices, close_prices)
        lower_shadow = self._kline_lower_shadow(open_prices, close_prices, low_prices)
        upper_shadow = self._kline_upper_shadow(open_prices, close_prices, high_prices)
        
        hammer_condition = (lower_shadow > body * 2) & (upper_shadow < body * 0.5)
        downtrend = close_prices.shift(5) < close_prices.shift(10)
        
        return {"hammer": (hammer_condition & downtrend).astype(float) * self.signal_strength["hammer"]}

    def hanging_man_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """上吊线"""
        body = self._kline_body(open_prices, close_prices)
        lower_shadow = self._kline_lower_shadow(open_prices, close_prices, low_prices)
        upper_shadow = self._kline_upper_shadow(open_prices, close_prices, high_prices)
        
        uptrend = close_prices.shift(5) > close_prices.shift(10)
        hanging_man_condition = (lower_shadow > body * 2) & (upper_shadow < body * 0.5) & uptrend
        
        return {"hanging_man": hanging_man_condition.astype(float) * self.signal_strength["hanging_man"]}

    def engulfing_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """吞没形态"""
        downtrend = close_prices.shift(2) < close_prices.shift(5)
        bullish_engulfing = (
            (close_prices > open_prices) & 
            (close_prices.shift(1) < open_prices.shift(1)) &
            (open_prices < close_prices.shift(1)) & 
            (close_prices > open_prices.shift(1)) &
            downtrend
        )
        
        uptrend = close_prices.shift(2) > close_prices.shift(5)
        bearish_engulfing = (
            (close_prices < open_prices) & 
            (close_prices.shift(1) > open_prices.shift(1)) &
            (open_prices > close_prices.shift(1)) & 
            (close_prices < open_prices.shift(1)) &
            uptrend
        )
        
        return {
            "engulfing_bullish": bullish_engulfing.astype(float) * self.signal_strength["engulfing_bullish"],
            "engulfing_bearish": bearish_engulfing.astype(float) * self.signal_strength["engulfing_bearish"]
        }

    def dark_cloud_cover_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """乌云盖顶"""
        uptrend = close_prices.shift(2) > close_prices.shift(5)
        dark_cloud = (
            uptrend &
            (close_prices.shift(1) > open_prices.shift(1)) &
            (close_prices < open_prices) &
            (open_prices > close_prices.shift(1)) &
            (close_prices < (open_prices.shift(1) + close_prices.shift(1)) / 2)
        )
        
        return {"dark_cloud_cover": dark_cloud.astype(float) * self.signal_strength["dark_cloud_cover"]}

    def piercing_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """刺透形态"""
        downtrend = close_prices.shift(2) < close_prices.shift(5)
        piercing = (
            downtrend &
            (close_prices.shift(1) < open_prices.shift(1)) &
            (close_prices > open_prices) &
            (open_prices < close_prices.shift(1)) &
            (close_prices > (open_prices.shift(1) + close_prices.shift(1)) / 2)
        )
        
        return {"piercing": piercing.astype(float) * self.signal_strength["piercing"]}

    def morning_star_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """启明星"""
        downtrend = close_prices.shift(3) < close_prices.shift(10)
        first_bearish = (open_prices.shift(2) - close_prices.shift(2)) / open_prices.shift(2) > 0.03
        small_body = self.is_small_candle(open_prices.shift(1), close_prices.shift(1), 0.02)
        last_bullish = (close_prices - open_prices) / open_prices > 0.03
        
        gap_down = high_prices.shift(1) < low_prices.shift(2)
        gap_up = low_prices > high_prices.shift(1)
        
        morning_star = downtrend & first_bearish & small_body & last_bullish & gap_down & gap_up
        
        return {"morning_star": morning_star.astype(float) * self.signal_strength["morning_star"]}

    def evening_star_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """黄昏星"""
        uptrend = close_prices.shift(3) > close_prices.shift(10)
        first_bullish = (close_prices.shift(2) - open_prices.shift(2)) / open_prices.shift(2) > 0.03
        small_body = self.is_small_candle(open_prices.shift(1), close_prices.shift(1), 0.02)
        last_bearish = (open_prices - close_prices) / open_prices > 0.03
        
        gap_up = low_prices.shift(1) > high_prices.shift(2)
        gap_down = high_prices < low_prices.shift(1)
        
        evening_star = uptrend & first_bullish & small_body & last_bearish & gap_up & gap_down
        
        return {"evening_star": evening_star.astype(float) * self.signal_strength["evening_star"]}

    def evening_star_doji_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """十字暮星"""
        uptrend = close_prices.shift(3) > close_prices.shift(10)
        first_bullish = (close_prices.shift(2) - open_prices.shift(2)) / open_prices.shift(2) > 0.03
        doji_star = self.is_doji(open_prices.shift(1), high_prices.shift(1), low_prices.shift(1), close_prices.shift(1))
        last_bearish = (open_prices - close_prices) / open_prices > 0.03
        
        evening_star_doji = uptrend & first_bullish & doji_star & last_bearish
        
        return {"evening_star_doji": evening_star_doji.astype(float) * self.signal_strength["evening_star_doji"]}

    def abandoned_baby_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """弃婴形态"""
        downtrend = close_prices.shift(3) < close_prices.shift(10)
        doji = self.is_doji(open_prices.shift(1), high_prices.shift(1), low_prices.shift(1), close_prices.shift(1))
        gap_down = low_prices.shift(1) > high_prices.shift(2)
        gap_up = low_prices > high_prices.shift(1)
        confirmation = close_prices > open_prices
        
        abandoned_baby_bullish = downtrend & doji & gap_down & gap_up & confirmation
        
        uptrend = close_prices.shift(3) > close_prices.shift(10)
        gap_up_bearish = low_prices.shift(1) > high_prices.shift(2)
        gap_down_bearish = high_prices < low_prices.shift(1)
        confirmation_bearish = close_prices < open_prices
        
        abandoned_baby_bearish = uptrend & doji & gap_up_bearish & gap_down_bearish & confirmation_bearish
        
        return {
            "abandoned_baby_bullish": abandoned_baby_bullish.astype(float) * self.signal_strength["abandoned_baby_bullish"],
            "abandoned_baby_bearish": abandoned_baby_bearish.astype(float) * self.signal_strength["abandoned_baby_bearish"]
        }

    def harami_doji_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """十字孕线"""
        body1 = abs(close_prices.shift(1) - open_prices.shift(1))
        doji2 = self.is_doji(open_prices, high_prices, low_prices, close_prices)
        range_condition = (
            (high_prices < high_prices.shift(1)) & 
            (low_prices > low_prices.shift(1))
        )
        
        downtrend = close_prices.shift(2) < close_prices.shift(5)
        harami_doji_bullish = range_condition & (body1 > 0) & doji2 & (close_prices.shift(1) < open_prices.shift(1)) & downtrend
        
        uptrend = close_prices.shift(2) > close_prices.shift(5)
        harami_doji_bearish = range_condition & (body1 > 0) & doji2 & (close_prices.shift(1) > open_prices.shift(1)) & uptrend
        
        return {
            "harami_doji_bullish": harami_doji_bullish.astype(float) * self.signal_strength["harami_doji_bullish"],
            "harami_doji_bearish": harami_doji_bearish.astype(float) * self.signal_strength["harami_doji_bearish"]
        }

    def tweezers_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """平头形态"""
        same_high = abs(high_prices - high_prices.shift(1)) / high_prices.shift(1) < 0.005
        uptrend = close_prices.shift(3) > close_prices.shift(10)
        tweezers_top = same_high & uptrend
        
        same_low = abs(low_prices - low_prices.shift(1)) / low_prices.shift(1) < 0.005
        downtrend = close_prices.shift(3) < close_prices.shift(10)
        tweezers_bottom = same_low & downtrend
        
        return {
            "tweezers_top": tweezers_top.astype(float) * self.signal_strength["tweezers_top"],
            "tweezers_bottom": tweezers_bottom.astype(float) * self.signal_strength["tweezers_bottom"]
        }

    def belt_hold_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """捉腰带线"""
        no_upper_shadow = high_prices == np.maximum(open_prices, close_prices)
        no_lower_shadow = low_prices == np.minimum(open_prices, close_prices)
        big_body_bullish = (close_prices - open_prices) / open_prices > 0.03
        open_near_low = (open_prices - low_prices) / (high_prices - low_prices + 1e-8) < 0.1
        
        belt_hold_bullish = no_upper_shadow & no_lower_shadow & big_body_bullish & open_near_low
        
        big_body_bearish = (open_prices - close_prices) / open_prices > 0.03
        open_near_high = (high_prices - open_prices) / (high_prices - low_prices + 1e-8) < 0.1
        
        belt_hold_bearish = no_upper_shadow & no_lower_shadow & big_body_bearish & open_near_high
        
        return {
            "belt_hold_bullish": belt_hold_bullish.astype(float) * self.signal_strength["belt_hold_bullish"],
            "belt_hold_bearish": belt_hold_bearish.astype(float) * self.signal_strength["belt_hold_bearish"]
        }

    def counterattack_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """反击线"""
        downtrend = close_prices.shift(2) < close_prices.shift(5)
        first_bearish = (open_prices.shift(1) - close_prices.shift(1)) / open_prices.shift(1) > 0.02
        second_bullish = (close_prices - open_prices) / open_prices > 0.02
        same_close = abs(close_prices - close_prices.shift(1)) / close_prices.shift(1) < 0.005
        
        counterattack_bullish = downtrend & first_bearish & second_bullish & same_close
        
        uptrend = close_prices.shift(2) > close_prices.shift(5)
        first_bullish = (close_prices.shift(1) - open_prices.shift(1)) / open_prices.shift(1) > 0.02
        second_bearish = (open_prices - close_prices) / open_prices > 0.02
        
        counterattack_bearish = uptrend & first_bullish & second_bearish & same_close
        
        return {
            "counterattack_bullish": counterattack_bullish.astype(float) * self.signal_strength["counterattack_bullish"],
            "counterattack_bearish": counterattack_bearish.astype(float) * self.signal_strength["counterattack_bearish"]
        }

    def crows_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """乌鸦形态"""
        uptrend = close_prices.shift(3) > close_prices.shift(10)
        first_bullish = close_prices.shift(2) > open_prices.shift(2)
        two_bearish = (close_prices.shift(1) < open_prices.shift(1)) & (close_prices < open_prices)
        gap_up = (open_prices.shift(1) > close_prices.shift(2)) & (open_prices > open_prices.shift(1))
        
        two_crows = uptrend & first_bullish & two_bearish & gap_up
        
        three_bearish = (
            (close_prices < open_prices) &
            (close_prices.shift(1) < open_prices.shift(1)) &
            (close_prices.shift(2) < open_prices.shift(2))
        )
        falling_close = (
            (close_prices < close_prices.shift(1)) &
            (close_prices.shift(1) < close_prices.shift(2))
        )
        
        three_crows = uptrend & three_bearish & falling_close

        two_crows_signal = two_crows.astype(float) * self.signal_strength["two_crows"]
        three_crows_signal = three_crows.astype(float) * self.signal_strength["three_crows"]

        total_crows_signal = three_crows_signal.where(
            three_crows_signal != 0,
            two_crows_signal
        )

        return {"crows": total_crows_signal}

    def three_white_soldiers_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """白色三兵"""
        downtrend = close_prices.shift(4) < close_prices.shift(10)
        three_bullish = (
            (close_prices > open_prices) &
            (close_prices.shift(1) > open_prices.shift(1)) &
            (close_prices.shift(2) > open_prices.shift(2))
        )
        rising_close = (
            (close_prices > close_prices.shift(1)) &
            (close_prices.shift(1) > close_prices.shift(2))
        )
        
        three_soldiers = downtrend & three_bullish & rising_close
        
        return {"three_white_soldiers": three_soldiers.astype(float) * self.signal_strength["three_white_soldiers"]}

    def tower_patterns(self, open_prices, high_prices, low_prices, close_prices):
        """塔型形态"""
        uptrend = close_prices.shift(5) > close_prices.shift(15)
        big_bullish = (close_prices.shift(2) - open_prices.shift(2)) / open_prices.shift(2) > 0.04
        small_body = self.is_small_candle(open_prices.shift(1), close_prices.shift(1), 0.02)
        big_bearish = (open_prices - close_prices) / open_prices > 0.04
        
        tower_top = uptrend & big_bullish & small_body & big_bearish
        
        downtrend = close_prices.shift(5) < close_prices.shift(15)
        big_bearish_bottom = (open_prices.shift(2) - close_prices.shift(2)) / open_prices.shift(2) > 0.04
        big_bullish_bottom = (close_prices - open_prices) / open_prices > 0.04
        
        tower_bottom = downtrend & big_bearish_bottom & small_body & big_bullish_bottom
        
        return {
            "tower_top": tower_top.astype(float) * self.signal_strength["tower_top"],
            "tower_bottom": tower_bottom.astype(float) * self.signal_strength["tower_bottom"]
        }

    def three_mountains_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """三山形态"""
        high_1 = high_prices.shift(4)
        high_2 = high_prices.shift(2)
        high_3 = high_prices
        
        similar_highs = (
            (high_3 > high_2) & (high_2 > high_1) &
            (abs(high_3 - high_2) / high_2 < 0.03) &
            (abs(high_2 - high_1) / high_1 < 0.03)
        )
        
        neckline = np.minimum(np.minimum(low_prices.shift(3), low_prices.shift(1)), low_prices)
        breakdown = close_prices < neckline
        
        three_mountains = similar_highs & breakdown
        
        return {"three_mountains": three_mountains.astype(float) * self.signal_strength["three_mountains"]}

    def three_rivers_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """三川形态"""
        low_1 = low_prices.shift(4)
        low_2 = low_prices.shift(2)
        low_3 = low_prices
        
        similar_lows = (
            (low_3 < low_2) & (low_2 < low_1) &
            (abs(low_3 - low_2) / low_2 < 0.03) &
            (abs(low_2 - low_1) / low_1 < 0.03)
        )
        
        neckline = np.maximum(np.maximum(high_prices.shift(3), high_prices.shift(1)), high_prices)
        breakout = close_prices > neckline
        
        three_rivers = similar_lows & breakout
        
        return {"three_rivers": three_rivers.astype(float) * self.signal_strength["three_rivers"]}

    def three_methods_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """三法形态"""
        uptrend = close_prices.shift(5) > close_prices.shift(10)
        first_bullish = (close_prices.shift(4) - open_prices.shift(4)) / open_prices.shift(4) > 0.03
        small_bodies = (
            self.is_small_candle(open_prices.shift(3), close_prices.shift(3), 0.02) &
            self.is_small_candle(open_prices.shift(2), close_prices.shift(2), 0.02) &
            self.is_small_candle(open_prices.shift(1), close_prices.shift(1), 0.02)
        )
        within_range = (
            (high_prices.shift(3) < high_prices.shift(4)) &
            (high_prices.shift(2) < high_prices.shift(4)) &
            (high_prices.shift(1) < high_prices.shift(4)) &
            (low_prices.shift(3) > low_prices.shift(4)) &
            (low_prices.shift(2) > low_prices.shift(4)) &
            (low_prices.shift(1) > low_prices.shift(4))
        )
        last_bullish = (close_prices - open_prices) / open_prices > 0.03
        new_high = close_prices > close_prices.shift(4)
        
        rising_three = uptrend & first_bullish & small_bodies & within_range & last_bullish & new_high
        
        downtrend = close_prices.shift(5) < close_prices.shift(10)
        first_bearish = (open_prices.shift(4) - close_prices.shift(4)) / open_prices.shift(4) > 0.03
        last_bearish = (open_prices - close_prices) / open_prices > 0.03
        new_low = close_prices < close_prices.shift(4)
        
        falling_three = downtrend & first_bearish & small_bodies & within_range & last_bearish & new_low
        
        return {
            "rising_three_methods": rising_three.astype(float) * self.signal_strength["rising_three_methods"],
            "falling_three_methods": falling_three.astype(float) * self.signal_strength["falling_three_methods"]
        }

    def marubozu_patterns(self, open_prices, high_prices, low_prices, close_prices):
        """母子线形态"""
        uptrend = close_prices.shift(2) > close_prices.shift(5)
        first_bullish = (close_prices.shift(1) - open_prices.shift(1)) / open_prices.shift(1) > 0.03
        second_bullish = (close_prices > open_prices)
        within_range = (
            (high_prices < high_prices.shift(1)) &
            (low_prices > low_prices.shift(1))
        )
        small_body = self.is_small_candle(open_prices, close_prices, 0.015)
        
        bullish_marubozu = uptrend & first_bullish & second_bullish & within_range & small_body
        
        downtrend = close_prices.shift(2) < close_prices.shift(5)
        first_bearish = (open_prices.shift(1) - close_prices.shift(1)) / open_prices.shift(1) > 0.03
        second_bearish = (close_prices < open_prices)
        
        bearish_marubozu = downtrend & first_bearish & second_bearish & within_range & small_body
        
        pregnant_marubozu = uptrend & first_bullish & second_bearish & within_range & small_body
        
        tombstone_marubozu = downtrend & first_bearish & second_bullish & within_range & small_body
        
        return {
            "bullish_marubozu": bullish_marubozu.astype(float) * self.signal_strength["bullish_marubozu"],
            "tombstone_marubozu": tombstone_marubozu.astype(float) * self.signal_strength["tombstone_marubozu"],
            "bearish_marubozu": bearish_marubozu.astype(float) * self.signal_strength["bearish_marubozu"],
            "pregnant_marubozu": pregnant_marubozu.astype(float) * self.signal_strength["pregnant_marubozu"]
        }

    def three_inside_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """三内部形态"""
        downtrend = close_prices.shift(3) < close_prices.shift(8)
        short_bearish = self.is_small_candle(open_prices.shift(2), close_prices.shift(2), 0.02) & (close_prices.shift(2) < open_prices.shift(2))
        engulfing_bullish = (
            (close_prices.shift(1) > open_prices.shift(1)) &
            (open_prices.shift(1) < close_prices.shift(2)) &
            (close_prices.shift(1) > open_prices.shift(2))
        )
        confirmation_bullish = (close_prices > open_prices) & (close_prices > close_prices.shift(1))
        
        three_inside_up = downtrend & short_bearish & engulfing_bullish & confirmation_bullish
        
        uptrend = close_prices.shift(3) > close_prices.shift(8)
        short_bullish = self.is_small_candle(open_prices.shift(2), close_prices.shift(2), 0.02) & (close_prices.shift(2) > open_prices.shift(2))
        engulfing_bearish = (
            (close_prices.shift(1) < open_prices.shift(1)) &
            (open_prices.shift(1) > close_prices.shift(2)) &
            (close_prices.shift(1) < open_prices.shift(2))
        )
        confirmation_bearish = (close_prices < open_prices) & (close_prices < close_prices.shift(1))
        
        three_inside_down = uptrend & short_bullish & engulfing_bearish & confirmation_bearish
        
        return {
            "three_inside_up": three_inside_up.astype(float) * self.signal_strength["three_inside_up"],
            "three_inside_down": three_inside_down.astype(float) * self.signal_strength["three_inside_down"]
        }

    def doji_pause_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """停顿线"""
        uptrend = close_prices.shift(3) > close_prices.shift(8)
        two_big_bullish = (
            ((close_prices.shift(2) - open_prices.shift(2)) / open_prices.shift(2) > 0.03) &
            ((close_prices.shift(1) - open_prices.shift(1)) / open_prices.shift(1) > 0.03)
        )
        pause_candle = self.is_small_candle(open_prices, close_prices, 0.015) | self.is_doji(open_prices, high_prices, low_prices, close_prices)
        
        doji_pause = uptrend & two_big_bullish & pause_candle
        
        return {"doji_pause": doji_pause.astype(float) * self.signal_strength["doji_pause"]}

    def golden_needle_bottom_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """金针探底"""
        low_25d = self._min_close(25, close_prices)
        near_low = close_prices < low_25d * 1.02
        
        doji = self.is_doji(open_prices, high_prices, low_prices, close_prices)
        body = self._kline_body(open_prices, close_prices)
        lower_shadow = self._kline_lower_shadow(open_prices, close_prices, low_prices)
        
        long_lower_shadow = lower_shadow > body * 3
        
        golden_needle = near_low & doji & long_lower_shadow
        
        return {"golden_needle_bottom": golden_needle.astype(float) * self.signal_strength["golden_needle_bottom"]}

    def rocket_launch_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """火箭发射"""
        low_25d = self._min_close(25, close_prices)
        near_bottom = close_prices < low_25d * 1.05
        
        amplitude = (high_prices - low_prices) / open_prices > 0.06
        small_body = self.is_small_candle(open_prices, close_prices, 0.02)
        bullish = close_prices > open_prices
        long_shadows = (
            ((high_prices - np.maximum(open_prices, close_prices)) > abs(close_prices - open_prices) * 2) |
            ((np.minimum(open_prices, close_prices) - low_prices) > abs(close_prices - open_prices) * 2)
        )
        
        rocket_launch = near_bottom & amplitude & small_body & bullish & long_shadows
        
        return {"rocket_launch": rocket_launch.astype(float) * self.signal_strength["rocket_launch"]}

    def man_jiang_hong_pattern(self, open_prices, high_prices, low_prices, close_prices, 
                                small_candle_threshold=0.02, volatility_window=7, consecutive_candles=3):
        """满江红"""
        single_small_candle = self.is_small_candle(open_prices, close_prices, small_candle_threshold)

        prev_7d_small_candles = _rolling_all_true_frame(
            single_small_candle,
            window=volatility_window,
            shift_after=3,
        ).astype(bool)

        consecutive_bullish = (
            (close_prices > open_prices) &
            (close_prices.shift(1) > open_prices.shift(1)) &
            (close_prices.shift(2) > open_prices.shift(2))
        )
        
        rising_trend = (
            (close_prices > close_prices.shift(1)) &
            (close_prices.shift(1) > close_prices.shift(2))
        )
        
        bullish_condition = prev_7d_small_candles & consecutive_bullish & rising_trend
        bullish_signal = bullish_condition.astype(float) * self.signal_strength["man_jiang_hong"]

        return {"man_jiang_hong": bullish_signal}

    def hanging_man_enhanced_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """上吊线增强版"""
        high_25d = self._max_close(25, close_prices)
        near_high = close_prices > high_25d * 0.98
        
        body = self._kline_body(open_prices, close_prices)
        lower_shadow = self._kline_lower_shadow(open_prices, close_prices, low_prices)
        upper_shadow = self._kline_upper_shadow(open_prices, close_prices, high_prices)
        
        hanging_man_basic = (lower_shadow > body * 2) & (upper_shadow < body * 0.5)
        bearish = close_prices < open_prices
        high_amplitude = (high_prices - low_prices) / open_prices > 0.04
        
        hanging_man_enhanced = near_high & hanging_man_basic & bearish & high_amplitude
        
        return {"hanging_man_enhanced": hanging_man_enhanced.astype(float) * self.signal_strength["hanging_man_enhanced"]}

    def heaven_line_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """天堂线"""
        high_25d = self._max_close(25, close_prices)
        near_high = close_prices > high_25d * 0.98
        
        body = self._kline_body(open_prices, close_prices)
        upper_shadow = self._kline_upper_shadow(open_prices, close_prices, high_prices)
        lower_shadow = self._kline_lower_shadow(open_prices, close_prices, low_prices)
        
        long_upper_shadow = upper_shadow > body * 3
        short_lower_shadow = lower_shadow < body * 0.5
        small_body = self.is_small_candle(open_prices, close_prices, 0.02)
        high_amplitude = (high_prices - low_prices) / open_prices > 0.05
        
        heaven_line = near_high & long_upper_shadow & short_lower_shadow & small_body & high_amplitude
        
        return {"heaven_line": heaven_line.astype(float) * self.signal_strength["heaven_line"]}

    def dark_cloud_line_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """乌云线"""
        uptrend = close_prices.shift(2) > close_prices.shift(10)
        prev_bullish = close_prices.shift(1) > open_prices.shift(1)
        current_bearish = close_prices < open_prices
        gap_up = open_prices > close_prices.shift(1)
        high_amplitude = (high_prices - low_prices) / open_prices > 0.04
        
        dark_cloud_line = uptrend & prev_bullish & current_bearish & gap_up & high_amplitude
        
        return {"dark_cloud_line": dark_cloud_line.astype(float) * self.signal_strength["dark_cloud_line"]}

    def same_price_patterns(self, open_prices, high_prices, low_prices, close_prices):
        """相同价格形态"""
        same_low_2day = abs(low_prices - low_prices.shift(1)) / low_prices.shift(1) < 0.005
        same_low_3day = (
            (abs(low_prices - low_prices.shift(1)) / low_prices.shift(1) < 0.005) &
            (abs(low_prices.shift(1) - low_prices.shift(2)) / low_prices.shift(2) < 0.005)
        )
        same_low = same_low_2day | same_low_3day
        
        same_high_2day = abs(high_prices - high_prices.shift(1)) / high_prices.shift(1) < 0.005
        same_high_3day = (
            (abs(high_prices - high_prices.shift(1)) / high_prices.shift(1) < 0.005) &
            (abs(high_prices.shift(1) - high_prices.shift(2)) / high_prices.shift(2) < 0.005)
        )
        same_high = same_high_2day | same_high_3day
        
        return {
            "same_low_price": same_low.astype(float) * self.signal_strength["same_low_price"],
            "same_high_price": same_high.astype(float) * self.signal_strength["same_high_price"]
        }

    def takuri_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """塔库里"""
        low_20d = self._min_close(20, close_prices)
        near_bottom = close_prices < low_20d * 1.05
        
        body = self._kline_body(open_prices, close_prices)
        lower_shadow = self._kline_lower_shadow(open_prices, close_prices, low_prices)
        upper_shadow = self._kline_upper_shadow(open_prices, close_prices, high_prices)
        
        long_lower_shadow = lower_shadow > body * 3
        short_upper_shadow = upper_shadow < body * 0.5
        small_body = self.is_small_candle(open_prices, close_prices, 0.015)
        
        takuri = near_bottom & long_lower_shadow & short_upper_shadow & small_body
        
        return {"takuri": takuri.astype(float) * self.signal_strength["takuri"]}

    def false_breakout_trap_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """假突破陷阱"""
        support_break = low_prices.shift(1) < self._min_low(20, low_prices).shift(2)
        recovery = (close_prices > open_prices) & (close_prices > (high_prices.shift(1) + low_prices.shift(1)) / 2)
        
        false_breakout_bullish = support_break & recovery
        
        resistance_break = high_prices.shift(1) > self._max_high(20, high_prices).shift(2)
        pullback = (close_prices < open_prices) & (close_prices < (high_prices.shift(1) + low_prices.shift(1)) / 2)
        
        false_breakout_bearish = resistance_break & pullback
        
        return {
            "false_breakout_trap_bullish": false_breakout_bullish.astype(float) * self.signal_strength["false_breakout_trap_bullish"],
            "false_breakout_trap_bearish": false_breakout_bearish.astype(float) * self.signal_strength["false_breakout_trap_bearish"]
        }

    def short_body_candle_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """短实体蜡烛"""
        short_body = self.is_small_candle(open_prices, close_prices, 0.01)
        
        uptrend = close_prices.shift(3) > close_prices.shift(8)
        downtrend = close_prices.shift(3) < close_prices.shift(8)
        
        short_body_bullish = short_body & uptrend
        short_body_bearish = short_body & downtrend
        
        return {
            "short_body_candle_bullish": short_body_bullish.astype(float) * self.signal_strength["short_body_candle_bullish"],
            "short_body_candle_bearish": short_body_bearish.astype(float) * self.signal_strength["short_body_candle_bearish"]
        }

    def long_legged_doji_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """长脚十字星"""
        doji = self.is_doji(open_prices, high_prices, low_prices, close_prices)
        long_legs = (high_prices - low_prices) / open_prices > 0.05
        
        long_legged_doji = doji & long_legs
        
        high_20d = self._max_close(20, close_prices)
        low_20d = self._min_close(20, close_prices)
        
        near_high = close_prices > high_20d * 0.98
        near_low = close_prices < low_20d * 1.02
        
        long_legged_bullish = long_legged_doji & near_low
        long_legged_bearish = long_legged_doji & near_high
        
        return {
            "long_legged_doji_bullish": long_legged_bullish.astype(float) * self.signal_strength["long_legged_doji_bullish"],
            "long_legged_doji_bearish": long_legged_bearish.astype(float) * self.signal_strength["long_legged_doji_bearish"]
        }

    def three_outside_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """三外部形态"""
        downtrend = close_prices.shift(3) < close_prices.shift(8)
        long_bearish = (open_prices.shift(2) - close_prices.shift(2)) / open_prices.shift(2) > 0.04
        engulfing_bullish = (
            (close_prices.shift(1) > open_prices.shift(1)) &
            (open_prices.shift(1) < close_prices.shift(2)) &
            (close_prices.shift(1) > open_prices.shift(2))
        )
        breakout_bullish = (close_prices > open_prices) & (close_prices > close_prices.shift(1))
        
        three_outside_up = downtrend & long_bearish & engulfing_bullish & breakout_bullish
        
        uptrend = close_prices.shift(3) > close_prices.shift(8)
        long_bullish = (close_prices.shift(2) - open_prices.shift(2)) / open_prices.shift(2) > 0.04
        engulfing_bearish = (
            (close_prices.shift(1) < open_prices.shift(1)) &
            (open_prices.shift(1) > close_prices.shift(2)) &
            (close_prices.shift(1) < open_prices.shift(2))
        )
        breakout_bearish = (close_prices < open_prices) & (close_prices < close_prices.shift(1))
        
        three_outside_down = uptrend & long_bullish & engulfing_bearish & breakout_bearish
        
        return {
            "three_outside_up": three_outside_up.astype(float) * self.signal_strength["three_outside_up"],
            "three_outside_down": three_outside_down.astype(float) * self.signal_strength["three_outside_down"]
        }

    def marubozu_extreme_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """光头光脚线"""
        no_upper_shadow_bullish = high_prices == np.maximum(open_prices, close_prices)
        no_lower_shadow_bullish = low_prices == np.minimum(open_prices, close_prices)
        big_body_bullish = (close_prices - open_prices) / open_prices > 0.04
        
        marubozu_bullish = no_upper_shadow_bullish & no_lower_shadow_bullish & big_body_bullish
        
        big_body_bearish = (open_prices - close_prices) / open_prices > 0.04
        
        marubozu_bearish = no_upper_shadow_bullish & no_lower_shadow_bullish & big_body_bearish
        
        return {
            "marubozu_bullish": marubozu_bullish.astype(float) * self.signal_strength["marubozu_bullish"],
            "marubozu_bearish": marubozu_bearish.astype(float) * self.signal_strength["marubozu_bearish"]
        }

    def spinning_top_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """纺锤线"""
        small_body = self.is_small_candle(open_prices, close_prices, 0.015)
        long_upper_shadow = (high_prices - np.maximum(open_prices, close_prices)) > abs(close_prices - open_prices)
        long_lower_shadow = (np.minimum(open_prices, close_prices) - low_prices) > abs(close_prices - open_prices)
        
        spinning_top = small_body & long_upper_shadow & long_lower_shadow
        
        uptrend = close_prices.shift(3) > close_prices.shift(8)
        downtrend = close_prices.shift(3) < close_prices.shift(8)
        
        spinning_top_bullish = spinning_top & uptrend
        spinning_top_bearish = spinning_top & downtrend
        
        return {
            "spinning_top_bullish": spinning_top_bullish.astype(float) * self.signal_strength["spinning_top_bullish"],
            "spinning_top_bearish": spinning_top_bearish.astype(float) * self.signal_strength["spinning_top_bearish"]
        }

    def high_wave_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """高浪线"""
        small_body = self.is_small_candle(open_prices, close_prices, 0.01)
        high_amplitude = (high_prices - low_prices) / open_prices > 0.06
        long_upper_shadow = (high_prices - np.maximum(open_prices, close_prices)) > abs(close_prices - open_prices) * 2
        long_lower_shadow = (np.minimum(open_prices, close_prices) - low_prices) > abs(close_prices - open_prices) * 2
        
        high_wave = small_body & high_amplitude & long_upper_shadow & long_lower_shadow
        
        high_20d = self._max_close(20, close_prices)
        low_20d = self._min_close(20, close_prices)
        
        near_high = close_prices > high_20d * 0.98
        near_low = close_prices < low_20d * 1.02
        
        high_wave_bullish = high_wave & near_low
        high_wave_bearish = high_wave & near_high
        
        return {
            "high_wave_bullish": high_wave_bullish.astype(float) * self.signal_strength["high_wave_bullish"],
            "high_wave_bearish": high_wave_bearish.astype(float) * self.signal_strength["high_wave_bearish"]
        }

    def homing_pigeon_pattern(self, open_prices, high_prices, low_prices, close_prices):
        """家鸽形态"""
        uptrend = close_prices.shift(2) > close_prices.shift(5)
        first_bullish = (close_prices.shift(1) - open_prices.shift(1)) / open_prices.shift(1) > 0.03
        second_bearish = (close_prices < open_prices)
        within_range = (
            (high_prices < high_prices.shift(1)) &
            (low_prices > low_prices.shift(1))
        )
        
        homing_pigeon_bullish = uptrend & first_bullish & second_bearish & within_range
        
        downtrend = close_prices.shift(2) < close_prices.shift(5)
        first_bearish = (open_prices.shift(1) - close_prices.shift(1)) / open_prices.shift(1) > 0.03
        second_bullish = (close_prices > open_prices)
        
        homing_pigeon_bearish = downtrend & first_bearish & second_bullish & within_range
        
        return {
            "homing_pigeon_bullish": homing_pigeon_bullish.astype(float) * self.signal_strength["homing_pigeon_bullish"],
            "homing_pigeon_bearish": homing_pigeon_bearish.astype(float) * self.signal_strength["homing_pigeon_bearish"]
        }



    def _resolve_pattern_fn(self, mapping_entry):
        if isinstance(mapping_entry, tuple):
            return mapping_entry[0]
        return mapping_entry

    def _get_or_compute_patterns(self, enabled_signals, signal_mapping) -> dict[str, dict]:
        cache_key = tuple(sorted(enabled_signals))
        if self._pattern_cache_key == cache_key and self._pattern_cache:
            return self._pattern_cache
        cache: dict[str, dict] = {}
        for name in enabled_signals:
            if name in signal_mapping:
                cache[name] = self._resolve_pattern_fn(signal_mapping[name])()
        self._pattern_cache_key = cache_key
        self._pattern_cache = cache
        return cache

    def get_total_signal_matrix(self, open_prices, high_prices, low_prices, close_prices, Volume, enabled_signals=None):
        """
        整合启用的信号，生成最终的形态信号强度矩阵
        
        参数:
            open_prices, high_prices, low_prices, close_prices: pd.DataFrame，OHLC数据
            Volume: pd.DataFrame，成交量数据
            enabled_signals: list 或 str，指定启用的信号名称。
                           - None: 启用所有信号
                           - 'Pattern': 启用预设的形态组合（十字孕线、母子线、乌云盖顶等）
                           - list: 自定义信号列表
        
        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
        
        # 0. 如果 enabled_signals 是预设字符串 'Pattern'，使用预定义的信号组合
        if enabled_signals == 'Pattern':
            enabled_signals = [
                'harami_doji',           # 十字孕线
                'marubozu',              # 母子线
                'dark_cloud_cover',      # 乌云盖顶
                'three_inside',          # 三内部上涨/下跌
                'doji_pause',            # 停顿线
                'golden_needle',         # 金针探底
                'rocket_launch',         # 火箭发射
                'man_jiang_hong',        # 满江红
                'hanging_man',           # 上吊线
                'heaven_line',           # 天堂线
                'dark_cloud_line',       # 乌云线
            ]
        
        # 1. 建立信号名称到计算函数的映射（lambda延迟执行）
        signal_mapping = {
            'harami': lambda: self.harami_pattern(open_prices, high_prices, low_prices, close_prices),
            'morning_star_doji': lambda: self.morning_star_doji_pattern(open_prices, high_prices, low_prices, close_prices),
            'hammer': lambda: self.hammer_pattern(open_prices, high_prices, low_prices, close_prices),
            'hanging_man': lambda: self.hanging_man_pattern(open_prices, high_prices, low_prices, close_prices),
            'engulfing': lambda: self.engulfing_pattern(open_prices, high_prices, low_prices, close_prices),
            'dark_cloud_cover': lambda: self.dark_cloud_cover_pattern(open_prices, high_prices, low_prices, close_prices),
            'piercing': lambda: self.piercing_pattern(open_prices, high_prices, low_prices, close_prices),
            'morning_star': lambda: self.morning_star_pattern(open_prices, high_prices, low_prices, close_prices),
            'evening_star': lambda: self.evening_star_pattern(open_prices, high_prices, low_prices, close_prices),
            'evening_star_doji': lambda: self.evening_star_doji_pattern(open_prices, high_prices, low_prices, close_prices),
            'abandoned_baby': lambda: self.abandoned_baby_pattern(open_prices, high_prices, low_prices, close_prices),
            'harami_doji': lambda: self.harami_doji_pattern(open_prices, high_prices, low_prices, close_prices),
            'tweezers': lambda: self.tweezers_pattern(open_prices, high_prices, low_prices, close_prices),
            'belt_hold': lambda: self.belt_hold_pattern(open_prices, high_prices, low_prices, close_prices),
            'counterattack': lambda: self.counterattack_pattern(open_prices, high_prices, low_prices, close_prices),
            'crows': lambda: self.crows_pattern(open_prices, high_prices, low_prices, close_prices),
            'three_white_soldiers': lambda: self.three_white_soldiers_pattern(open_prices, high_prices, low_prices, close_prices),
            'tower': lambda: self.tower_patterns(open_prices, high_prices, low_prices, close_prices),
            'three_mountains': lambda: self.three_mountains_pattern(open_prices, high_prices, low_prices, close_prices),
            'three_rivers': lambda: self.three_rivers_pattern(open_prices, high_prices, low_prices, close_prices),
            'three_methods': lambda: self.three_methods_pattern(open_prices, high_prices, low_prices, close_prices),
            'marubozu': lambda: self.marubozu_patterns(open_prices, high_prices, low_prices, close_prices),
            'three_inside': lambda: self.three_inside_pattern(open_prices, high_prices, low_prices, close_prices),
            'doji_pause': lambda: self.doji_pause_pattern(open_prices, high_prices, low_prices, close_prices),
            'golden_needle': lambda: self.golden_needle_bottom_pattern(open_prices, high_prices, low_prices, close_prices),
            'rocket_launch': lambda: self.rocket_launch_pattern(open_prices, high_prices, low_prices, close_prices),
            'man_jiang_hong': lambda: self.man_jiang_hong_pattern(open_prices, high_prices, low_prices, close_prices),
            'hanging_man_enhanced': lambda: self.hanging_man_enhanced_pattern(open_prices, high_prices, low_prices, close_prices),
            'heaven_line': lambda: self.heaven_line_pattern(open_prices, high_prices, low_prices, close_prices),
            'dark_cloud_line': lambda: self.dark_cloud_line_pattern(open_prices, high_prices, low_prices, close_prices),
            'same_price': lambda: self.same_price_patterns(open_prices, high_prices, low_prices, close_prices),
            'takuri': lambda: self.takuri_pattern(open_prices, high_prices, low_prices, close_prices),
            'false_breakout': lambda: self.false_breakout_trap_pattern(open_prices, high_prices, low_prices, close_prices),
            'short_body': lambda: self.short_body_candle_pattern(open_prices, high_prices, low_prices, close_prices),
            'long_legged_doji': lambda: self.long_legged_doji_pattern(open_prices, high_prices, low_prices, close_prices),
            'three_outside': lambda: self.three_outside_pattern(open_prices, high_prices, low_prices, close_prices),
            'marubozu_extreme': lambda: self.marubozu_extreme_pattern(open_prices, high_prices, low_prices, close_prices),
            'spinning_top': lambda: self.spinning_top_pattern(open_prices, high_prices, low_prices, close_prices),
            'high_wave': lambda: self.high_wave_pattern(open_prices, high_prices, low_prices, close_prices),
            'homing_pigeon': lambda: self.homing_pigeon_pattern(open_prices, high_prices, low_prices, close_prices),
        }
        
        # 2. 定义每个信号如何累加（buy_keys列表, sell_keys列表）
        signal_accumulation = {
            'harami': (['harami_bullish'], ['harami_bearish']),
            'morning_star_doji': (['morning_star_doji'], []),
            'hammer': (['hammer'], []),
            'hanging_man': ([], ['hanging_man']),
            'engulfing': (['engulfing_bullish'], ['engulfing_bearish']),
            'dark_cloud_cover': ([], ['dark_cloud_cover']),
            'piercing': (['piercing'], []),
            'morning_star': (['morning_star'], []),
            'evening_star': ([], ['evening_star']),
            'evening_star_doji': ([], ['evening_star_doji']),
            'abandoned_baby': (['abandoned_baby_bullish'], ['abandoned_baby_bearish']),
            'harami_doji': (['harami_doji_bullish'], ['harami_doji_bearish']),
            'tweezers': (['tweezers_bottom'], ['tweezers_top']),
            'belt_hold': (['belt_hold_bullish'], ['belt_hold_bearish']),
            'counterattack': (['counterattack_bullish'], ['counterattack_bearish']),
            'crows': ([], ['crows']),
            'three_white_soldiers': (['three_white_soldiers'], []),
            'tower': (['tower_bottom'], ['tower_top']),
            'three_mountains': ([], ['three_mountains']),
            'three_rivers': (['three_rivers'], []),
            'three_methods': (['rising_three_methods'], ['falling_three_methods']),
            'marubozu': (['bullish_marubozu', 'tombstone_marubozu'], ['bearish_marubozu', 'pregnant_marubozu']),
            'three_inside': (['three_inside_up'], ['three_inside_down']),
            'doji_pause': (['doji_pause'], []),
            'golden_needle': (['golden_needle_bottom'], []),
            'rocket_launch': (['rocket_launch'], []),
            'man_jiang_hong': (['man_jiang_hong'], []),
            'hanging_man_enhanced': ([], ['hanging_man_enhanced']),
            'heaven_line': ([], ['heaven_line']),
            'dark_cloud_line': ([], ['dark_cloud_line']),
            'same_price': (['same_low_price'], ['same_high_price']),
            'takuri': (['takuri'], []),
            'false_breakout': (['false_breakout_trap_bullish'], ['false_breakout_trap_bearish']),
            'short_body': (['short_body_candle_bullish'], ['short_body_candle_bearish']),
            'long_legged_doji': (['long_legged_doji_bullish'], ['long_legged_doji_bearish']),
            'three_outside': (['three_outside_up'], ['three_outside_down']),
            'marubozu_extreme': (['marubozu_bullish'], ['marubozu_bearish']),
            'spinning_top': (['spinning_top_bullish'], ['spinning_top_bearish']),
            'high_wave': (['high_wave_bullish'], ['high_wave_bearish']),
            'homing_pigeon': (['homing_pigeon_bullish'], ['homing_pigeon_bearish']),
        }
        
        # 3. 如果没有指定启用的信号，使用所有信号
        if enabled_signals is None:
            enabled_signals = list(signal_mapping.keys())

        self._ensure_ohlc_context(open_prices, high_prices, low_prices, close_prices)
        debug_timing = _timing_enabled()
        t0 = time.perf_counter() if debug_timing else 0.0

        pattern_results = self._get_or_compute_patterns(enabled_signals, signal_mapping)
        
        # 4. 初始化累加矩阵
        sum_buy = pd.DataFrame(0, index=close_prices.index, columns=close_prices.columns)
        sum_sell = pd.DataFrame(0, index=close_prices.index, columns=close_prices.columns)
        
        # 5. 根据 enabled_signals 选择性计算并累加
        for signal_name in enabled_signals:
            if signal_name not in pattern_results:
                continue
            result = pattern_results[signal_name]
            
            # 获取该信号的累加规则
            buy_keys, sell_keys = signal_accumulation[signal_name]
            
            # 累加到 buy 信号
            for key in buy_keys:
                if key in result:
                    sum_buy += result[key]
            
            # 累加到 sell 信号
            for key in sell_keys:
                if key in result:
                    sum_sell += result[key]

        if debug_timing:
            elapsed = time.perf_counter() - t0
            print(f"[TIMING] get_total_signal_matrix core={elapsed:.4f}s rows={len(close_prices)} cols={len(close_prices.columns)}")
        
        return sum_buy, sum_sell


    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name, date_index, stock_columns):
        """逐列扫描非零信号，避免 stack 全表。"""
        values = signal_matrix.to_numpy(dtype=np.float64, copy=False)
        dates_arr = np.asarray(date_index)
        stocks_arr = np.asarray(stock_columns)
        n_rows, n_cols = values.shape
        records: list[dict] = []
        for j in range(n_cols):
            col = values[:, j]
            nz_idx = np.flatnonzero(col)
            if nz_idx.size == 0:
                continue
            stock = stocks_arr[j]
            col_vals = col[nz_idx]
            for i, v in zip(nz_idx, col_vals):
                records.append(
                    {
                        "Date": dates_arr[i],
                        "Contract": stock,
                        "direction": "buy" if v > 0 else "sell",
                        "signal_name": signal_name,
                        "strength": abs(float(v)),
                    }
                )
        return records
    
    def get_detailed_signals_dataframe(self, open_prices, high_prices, low_prices, close_prices, volume, enabled_signals=None):
        """
        获取详细的形态信号DataFrame，包含每个形态信号的明细信息

        参数:
            open_prices, high_prices, low_prices, close_prices: pd.DataFrame，OHLC数据
            volume: pd.DataFrame，成交量数据
            enabled_signals: list 或 str，指定启用的信号名称。
                           - None: 启用所有信号
                           - 'Pattern': 启用预设的形态组合（十字孕线、母子线、乌云盖顶等）
                           - list: 自定义信号列表
                           
                           可用的信号名称: 'harami', 'morning_star_doji', 'hammer', 'hanging_man', 
                           'engulfing', 'dark_cloud_cover', 'piercing', 'morning_star', 'evening_star',
                           'evening_star_doji', 'abandoned_baby', 'harami_doji', 'tweezers', 'belt_hold',
                           'counterattack', 'crows', 'three_white_soldiers', 'tower', 'three_mountains',
                           'three_rivers', 'three_methods', 'marubozu', 'three_inside', 'doji_pause',
                           'golden_needle', 'rocket_launch', 'man_jiang_hong', 'hanging_man_enhanced',
                           'heaven_line', 'dark_cloud_line', 'same_price', 'takuri', 'false_breakout',
                           'short_body', 'long_legged_doji', 'three_outside', 'marubozu_extreme',
                           'spinning_top', 'high_wave', 'homing_pigeon'

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_category, signal_name, strength
        """
        from itertools import chain
        
        # 0. 如果 enabled_signals 是预设字符串 'Pattern'，使用预定义的信号组合
        if enabled_signals == 'Pattern':
            enabled_signals = [
                'harami_doji',           # 十字孕线
                'marubozu',              # 母子线
                'dark_cloud_cover',      # 乌云盖顶
                'three_inside',          # 三内部上涨/下跌
                'doji_pause',            # 停顿线
                'golden_needle',         # 金针探底
                'rocket_launch',         # 火箭发射
                'man_jiang_hong',        # 满江红
                'hanging_man',           # 上吊线
                'heaven_line',           # 天堂线
                'dark_cloud_line',       # 乌云线
            ]
        
        # 获取日期索引和股票列名
        date_index = close_prices.index
        stock_columns = close_prices.columns
        
        # 建立信号名称到计算函数和类别的映射
        signal_mapping = {
            'harami': (lambda: self.harami_pattern(open_prices, high_prices, low_prices, close_prices), "孕线形态"),
            'morning_star_doji': (lambda: self.morning_star_doji_pattern(open_prices, high_prices, low_prices, close_prices), "十字晨星"),
            'hammer': (lambda: self.hammer_pattern(open_prices, high_prices, low_prices, close_prices), "锤子线"),
            'hanging_man': (lambda: self.hanging_man_pattern(open_prices, high_prices, low_prices, close_prices), "上吊线"),
            'engulfing': (lambda: self.engulfing_pattern(open_prices, high_prices, low_prices, close_prices), "吞没形态"),
            'dark_cloud_cover': (lambda: self.dark_cloud_cover_pattern(open_prices, high_prices, low_prices, close_prices), "乌云盖顶"),
            'piercing': (lambda: self.piercing_pattern(open_prices, high_prices, low_prices, close_prices), "刺透形态"),
            'morning_star': (lambda: self.morning_star_pattern(open_prices, high_prices, low_prices, close_prices), "启明星"),
            'evening_star': (lambda: self.evening_star_pattern(open_prices, high_prices, low_prices, close_prices), "黄昏星"),
            'evening_star_doji': (lambda: self.evening_star_doji_pattern(open_prices, high_prices, low_prices, close_prices), "十字暮星"),
            'abandoned_baby': (lambda: self.abandoned_baby_pattern(open_prices, high_prices, low_prices, close_prices), "弃婴形态"),
            'harami_doji': (lambda: self.harami_doji_pattern(open_prices, high_prices, low_prices, close_prices), "十字孕线"),
            'tweezers': (lambda: self.tweezers_pattern(open_prices, high_prices, low_prices, close_prices), "平头形态"),
            'belt_hold': (lambda: self.belt_hold_pattern(open_prices, high_prices, low_prices, close_prices), "捉腰带线"),
            'counterattack': (lambda: self.counterattack_pattern(open_prices, high_prices, low_prices, close_prices), "反击线"),
            'crows': (lambda: self.crows_pattern(open_prices, high_prices, low_prices, close_prices), "乌鸦形态"),
            'three_white_soldiers': (lambda: self.three_white_soldiers_pattern(open_prices, high_prices, low_prices, close_prices), "白色三兵"),
            'tower': (lambda: self.tower_patterns(open_prices, high_prices, low_prices, close_prices), "塔型形态"),
            'three_mountains': (lambda: self.three_mountains_pattern(open_prices, high_prices, low_prices, close_prices), "三山形态"),
            'three_rivers': (lambda: self.three_rivers_pattern(open_prices, high_prices, low_prices, close_prices), "三川形态"),
            'three_methods': (lambda: self.three_methods_pattern(open_prices, high_prices, low_prices, close_prices), "三法形态"),
            'marubozu': (lambda: self.marubozu_patterns(open_prices, high_prices, low_prices, close_prices), "母子线形态"),
            'three_inside': (lambda: self.three_inside_pattern(open_prices, high_prices, low_prices, close_prices), "三内部形态"),
            'doji_pause': (lambda: self.doji_pause_pattern(open_prices, high_prices, low_prices, close_prices), "停顿线"),
            'golden_needle': (lambda: self.golden_needle_bottom_pattern(open_prices, high_prices, low_prices, close_prices), "金针探底"),
            'rocket_launch': (lambda: self.rocket_launch_pattern(open_prices, high_prices, low_prices, close_prices), "火箭发射"),
            'man_jiang_hong': (lambda: self.man_jiang_hong_pattern(open_prices, high_prices, low_prices, close_prices), "满江红"),
            'hanging_man_enhanced': (lambda: self.hanging_man_enhanced_pattern(open_prices, high_prices, low_prices, close_prices), "上吊线增强版"),
            'heaven_line': (lambda: self.heaven_line_pattern(open_prices, high_prices, low_prices, close_prices), "天堂线"),
            'dark_cloud_line': (lambda: self.dark_cloud_line_pattern(open_prices, high_prices, low_prices, close_prices), "乌云线"),
            'same_price': (lambda: self.same_price_patterns(open_prices, high_prices, low_prices, close_prices), "相同价格形态"),
            'takuri': (lambda: self.takuri_pattern(open_prices, high_prices, low_prices, close_prices), "塔库里"),
            'false_breakout': (lambda: self.false_breakout_trap_pattern(open_prices, high_prices, low_prices, close_prices), "假突破陷阱"),
            'short_body': (lambda: self.short_body_candle_pattern(open_prices, high_prices, low_prices, close_prices), "短实体蜡烛"),
            'long_legged_doji': (lambda: self.long_legged_doji_pattern(open_prices, high_prices, low_prices, close_prices), "长脚十字星"),
            'three_outside': (lambda: self.three_outside_pattern(open_prices, high_prices, low_prices, close_prices), "三外部形态"),
            'marubozu_extreme': (lambda: self.marubozu_extreme_pattern(open_prices, high_prices, low_prices, close_prices), "光头光脚线"),
            'spinning_top': (lambda: self.spinning_top_pattern(open_prices, high_prices, low_prices, close_prices), "纺锤线"),
            'high_wave': (lambda: self.high_wave_pattern(open_prices, high_prices, low_prices, close_prices), "高浪线"),
            'homing_pigeon': (lambda: self.homing_pigeon_pattern(open_prices, high_prices, low_prices, close_prices), "家鸽形态"),
        }
        
        # 如果没有指定启用的信号，使用所有信号
        if enabled_signals is None:
            enabled_signals = list(signal_mapping.keys())

        self._ensure_ohlc_context(open_prices, high_prices, low_prices, close_prices)
        debug_timing = _timing_enabled()
        t0 = time.perf_counter() if debug_timing else 0.0
        t_compute = t0

        pattern_results = self._get_or_compute_patterns(enabled_signals, signal_mapping)

        signal_processors = []
        for signal_name in enabled_signals:
            if signal_name in pattern_results:
                _, category = signal_mapping[signal_name]
                signal_processors.append((pattern_results[signal_name], category))
            elif signal_name in signal_mapping:
                _, category = signal_mapping[signal_name]
                signal_processors.append((pattern_results[signal_name], category))
            else:
                print(f"警告: 未知的信号名称 '{signal_name}'，已忽略")

        if debug_timing:
            t_compute = time.perf_counter()
            print(f"[TIMING] get_detailed_signals compute={t_compute - t0:.4f}s")
        
        # 统一处理所有信号记录
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name, date_index, stock_columns)
            for processor, category in signal_processors
            for signal_name, signal_matrix in processor.items()
        ))
        
        # 合并所有记录并创建DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
        else:
            signals_df = pd.DataFrame(columns=['Date', 'Contract', 'direction', 'signal_category', 'signal_name', 'strength'])

        if debug_timing:
            print(f"[TIMING] get_detailed_signals assemble={time.perf_counter() - t_compute:.4f}s total={time.perf_counter() - t0:.4f}s")
        
        return signals_df

    def get_multi_index_signal_matrix(self, open_prices, high_prices, low_prices, close_prices, Volume, 
                                      enabled_signals=None):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        这是一个通用方法，可以被其他类似的技术指标类复用。
        
        参数:
            open_prices, high_prices, low_prices, close_prices: pd.DataFrame，OHLC数据
            Volume: pd.DataFrame，成交量数据
            enabled_signals: list 或 str，指定启用的信号名称
                           - None: 启用所有信号
                           - 'Pattern': 启用预设的形态组合（十字孕线、母子线、乌云盖顶等）
                           - list: 自定义信号列表（使用信号组合名称，如 'harami', 'engulfing' 等）
        
        返回:
            signals_multi_index: pd.DataFrame
                - Index: MultiIndex (Date, Contract)
                    - Date: int32格式（如 20240101）
                    - Contract: string格式
                - Columns: 各个信号组合名称（如 'harami', 'engulfing', 'crows' 等）
                - Values: float格式，对应信号的强度值（保留正负和0）
        
        使用示例:
            # 获取所有信号
            df = trans.get_multi_index_signal_matrix(
                open_prices, high_prices, low_prices, close_prices, Volume
            )
            
            # 获取预设的Pattern信号组合
            df = trans.get_multi_index_signal_matrix(
                open_prices, high_prices, low_prices, close_prices, Volume,
                enabled_signals='Pattern'
            )
            
            # 获取特定信号组合
            df = trans.get_multi_index_signal_matrix(
                open_prices, high_prices, low_prices, close_prices, Volume,
                enabled_signals=['harami', 'engulfing', 'hammer']
            )
            
            # 查询特定日期和合约的信号
            df.loc[(20240101, 'AAPL'), :]
            
            # 查询特定信号的所有记录（非零）
            df[df['harami'] != 0]['harami']
        """
        
        # 0. 如果 enabled_signals 是预设字符串 'Pattern'，使用预定义的信号组合
        if enabled_signals == 'Pattern':
            enabled_signals = [
                'harami_doji',           # 十字孕线
                'marubozu',              # 母子线
                'dark_cloud_cover',      # 乌云盖顶
                'three_inside',          # 三内部上涨/下跌
                'doji_pause',            # 停顿线
                'golden_needle',         # 金针探底
                'rocket_launch',         # 火箭发射
                'man_jiang_hong',        # 满江红
                'hanging_man',           # 上吊线
                'heaven_line',           # 天堂线
                'dark_cloud_line',       # 乌云线
            ]
        
        # 1. 建立信号名称到计算函数的映射（lambda延迟执行）
        signal_mapping = {
            'harami': lambda: self.harami_pattern(open_prices, high_prices, low_prices, close_prices),
            'morning_star_doji': lambda: self.morning_star_doji_pattern(open_prices, high_prices, low_prices, close_prices),
            'hammer': lambda: self.hammer_pattern(open_prices, high_prices, low_prices, close_prices),
            'hanging_man': lambda: self.hanging_man_pattern(open_prices, high_prices, low_prices, close_prices),
            'engulfing': lambda: self.engulfing_pattern(open_prices, high_prices, low_prices, close_prices),
            'dark_cloud_cover': lambda: self.dark_cloud_cover_pattern(open_prices, high_prices, low_prices, close_prices),
            'piercing': lambda: self.piercing_pattern(open_prices, high_prices, low_prices, close_prices),
            'morning_star': lambda: self.morning_star_pattern(open_prices, high_prices, low_prices, close_prices),
            'evening_star': lambda: self.evening_star_pattern(open_prices, high_prices, low_prices, close_prices),
            'evening_star_doji': lambda: self.evening_star_doji_pattern(open_prices, high_prices, low_prices, close_prices),
            'abandoned_baby': lambda: self.abandoned_baby_pattern(open_prices, high_prices, low_prices, close_prices),
            'harami_doji': lambda: self.harami_doji_pattern(open_prices, high_prices, low_prices, close_prices),
            'tweezers': lambda: self.tweezers_pattern(open_prices, high_prices, low_prices, close_prices),
            'belt_hold': lambda: self.belt_hold_pattern(open_prices, high_prices, low_prices, close_prices),
            'counterattack': lambda: self.counterattack_pattern(open_prices, high_prices, low_prices, close_prices),
            'crows': lambda: self.crows_pattern(open_prices, high_prices, low_prices, close_prices),
            'three_white_soldiers': lambda: self.three_white_soldiers_pattern(open_prices, high_prices, low_prices, close_prices),
            'tower': lambda: self.tower_patterns(open_prices, high_prices, low_prices, close_prices),
            'three_mountains': lambda: self.three_mountains_pattern(open_prices, high_prices, low_prices, close_prices),
            'three_rivers': lambda: self.three_rivers_pattern(open_prices, high_prices, low_prices, close_prices),
            'three_methods': lambda: self.three_methods_pattern(open_prices, high_prices, low_prices, close_prices),
            'marubozu': lambda: self.marubozu_patterns(open_prices, high_prices, low_prices, close_prices),
            'three_inside': lambda: self.three_inside_pattern(open_prices, high_prices, low_prices, close_prices),
            'doji_pause': lambda: self.doji_pause_pattern(open_prices, high_prices, low_prices, close_prices),
            'golden_needle': lambda: self.golden_needle_bottom_pattern(open_prices, high_prices, low_prices, close_prices),
            'rocket_launch': lambda: self.rocket_launch_pattern(open_prices, high_prices, low_prices, close_prices),
            'man_jiang_hong': lambda: self.man_jiang_hong_pattern(open_prices, high_prices, low_prices, close_prices),
            'hanging_man_enhanced': lambda: self.hanging_man_enhanced_pattern(open_prices, high_prices, low_prices, close_prices),
            'heaven_line': lambda: self.heaven_line_pattern(open_prices, high_prices, low_prices, close_prices),
            'dark_cloud_line': lambda: self.dark_cloud_line_pattern(open_prices, high_prices, low_prices, close_prices),
            'same_price': lambda: self.same_price_patterns(open_prices, high_prices, low_prices, close_prices),
            'takuri': lambda: self.takuri_pattern(open_prices, high_prices, low_prices, close_prices),
            'false_breakout': lambda: self.false_breakout_trap_pattern(open_prices, high_prices, low_prices, close_prices),
            'short_body': lambda: self.short_body_candle_pattern(open_prices, high_prices, low_prices, close_prices),
            'long_legged_doji': lambda: self.long_legged_doji_pattern(open_prices, high_prices, low_prices, close_prices),
            'three_outside': lambda: self.three_outside_pattern(open_prices, high_prices, low_prices, close_prices),
            'marubozu_extreme': lambda: self.marubozu_extreme_pattern(open_prices, high_prices, low_prices, close_prices),
            'spinning_top': lambda: self.spinning_top_pattern(open_prices, high_prices, low_prices, close_prices),
            'high_wave': lambda: self.high_wave_pattern(open_prices, high_prices, low_prices, close_prices),
            'homing_pigeon': lambda: self.homing_pigeon_pattern(open_prices, high_prices, low_prices, close_prices),
        }
        
        # 2. 如果没有指定启用的信号，使用所有信号组合
        if enabled_signals is None:
            enabled_signals = list(signal_mapping.keys())
        
        # 3. 根据 enabled_signals 计算信号，并将所有子信号合并为一个信号组合矩阵
        # 策略：对于返回多个子信号的函数（如harami返回harami_bullish和harami_bearish），
        #      我们将它们合并成一个矩阵（取所有子信号的和或优先非零值）
        
        combined_signal_matrices = {}
        
        for signal_name in enabled_signals:
            if signal_name not in signal_mapping:
                print(f"警告: 未知的信号名称 '{signal_name}'，已忽略")
                continue
            
            # 调用计算函数，返回的是字典 {子信号名: 矩阵}
            result_dict = signal_mapping[signal_name]()
            
            # 将所有子信号矩阵合并为一个矩阵
            # 合并策略：直接相加（因为子信号通常不会同时触发，且正负已经被区分）
            combined_matrix = pd.DataFrame(0.0, index=close_prices.index, columns=close_prices.columns)
            
            for sub_signal_name, sub_signal_matrix in result_dict.items():
                if sub_signal_matrix is not None:
                    combined_matrix = combined_matrix + sub_signal_matrix
            
            combined_signal_matrices[signal_name] = combined_matrix
        
        # 4. 将每个信号组合矩阵(Date × Contract)转换为Multi-index Series
        # 然后合并成一个DataFrame
        signal_series_list = []
        signal_names = []
        
        for signal_name, signal_matrix in combined_signal_matrices.items():
            if signal_matrix is not None:
                # 将矩阵stack成Multi-index Series
                # stack()会自动创建MultiIndex (Date, Contract)
                stacked_series = signal_matrix.stack()
                signal_series_list.append(stacked_series)
                signal_names.append(signal_name)
        
        # 5. 合并所有Series为DataFrame
        if signal_series_list:
            # 使用concat按列合并，keys参数指定列名
            signals_multi_index = pd.concat(
                signal_series_list, 
                axis=1, 
                keys=signal_names
            )
            
            # 填充NaN为0（某些信号可能在某些(Date, Contract)组合上为空）
            signals_multi_index = signals_multi_index.fillna(0)
            
            # 6. 转换数据类型
            # Date索引转换为int32格式（如果原始是datetime，转换为YYYYMMDD格式）
            current_dates = signals_multi_index.index.get_level_values(0)
            
            # 检查日期类型并转换
            if pd.api.types.is_datetime64_any_dtype(current_dates):
                # datetime转int32 (YYYYMMDD格式)
                date_int32 = current_dates.strftime('%Y%m%d').astype('int32')
            elif pd.api.types.is_integer_dtype(current_dates):
                # 已经是整数，直接转换为int32
                date_int32 = current_dates.astype('int32')
            else:
                # 其他类型，尝试转换
                date_int32 = pd.to_datetime(current_dates).strftime('%Y%m%d').astype('int32')
            
            # Contract索引转换为string格式
            contract_str = signals_multi_index.index.get_level_values(1).astype('string')
            
            # 重建索引
            new_index = pd.MultiIndex.from_arrays(
                [date_int32, contract_str],
                names=['Date', 'Contract']
            )
            signals_multi_index.index = new_index
            
            # Values转换为float类型
            signals_multi_index = signals_multi_index.astype('float32')
            
        else:
            # 如果没有信号，创建空DataFrame
            signals_multi_index = pd.DataFrame(
                columns=signal_names if signal_names else [],
                index=pd.MultiIndex.from_tuples([], names=['Date', 'Contract'])
            )
            # 设置正确的数据类型
            signals_multi_index.index = signals_multi_index.index.set_levels(
                signals_multi_index.index.levels[0].astype('int32'), level=0
            ) if len(signals_multi_index.index.levels) > 0 else signals_multi_index.index
            
        return signals_multi_index


if __name__ == "__main__":
    # 入口：转调 工具/形态蜡烛信号生成.py，默认全市场分批生成。
    import runpy
    import sys
    from pathlib import Path

    gen_script = Path(__file__).resolve().parent.parent / "工具" / "形态蜡烛信号生成.py"
    sys.argv[0] = str(gen_script)
    runpy.run_path(str(gen_script), run_name="__main__")