import pandas as pd
import numpy as np
from itertools import chain



'''from strategys.技术面.RSI import RSI
trans = RSI()
# 这里分别得到不同的买入卖出信号矩阵
signal_apo_buy,signal_apo_sell = trans.get_total_signal_matrix(Close_data,Volume)
signals_apo_search = trans.get_detailed_signals_dataframe(Close_data,Volume)
'''
import pandas as pd
import numpy as np
from itertools import chain

class RSI:
    """
    RSI (Relative Strength Index) 相对强弱指标 - 期货加法复权修正版。
    """

    def __init__(self):
        # 信号强度 (保持不变)
        self.signal_strength = {
            "golden_cross": 0.5, "death_cross": -0.5,
            "overbought_breakthrough": -0.6, "oversold_breakthrough": 0.6,
            "midline_breakthrough": 0.5, "midline_pullback": -0.5,
            "overbought_signal": -0.4, "oversold_signal": 0.4,
            "strong_zone": 0.3, "weak_zone": -0.3,
            "top_divergence": -0.8, "bottom_divergence": 0.8,
            "trend_acceleration": 0.5, "trend_deceleration": -0.3,
            "bull_bear_transition": 0.5,
            "extreme_reversal_sell": -0.9, "extreme_reversal_buy": 0.9,
            "double_bottom": 0.7, "double_top": -0.7,
            "triple_bottom": 0.9, "triple_top": -0.9,
            "volume_surge": 0.1,
            "rising_wedge": 0.1, "falling_wedge": -0.1,
            "triangle_convergence": 0.1, "triangle_divergence": -0.1,
            "channel_breakthrough": 0.2, "channel_pullback": 0.1,
            "breakthrough_confirmation": 0.4, "pullback_confirmation": -0.4,
        }
        self.continuous_signal_names = [
            "normalized_value",
            "slope_rate",
            "range_position",
        ]
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names

    def get_rsi_components(self, close_adj, high_adj, low_adj, volume, rsi_period=14, signal_period=5):
        """
        计算 RSI 核心组件 (期货修正版)
        增加 ATR 计算用于价格形态的阈值判定
        """
        
        # 1. 计算价格变化 (Diff 在加法复权下是安全的)
        price_change = close_adj.diff()
        gain = price_change.where(price_change > 0, 0)
        loss = -price_change.where(price_change < 0, 0)
        
        # 2. 计算平均涨跌幅 (EMA)
        avg_gain = gain.ewm(span=rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(span=rsi_period, adjust=False).mean()
        
        # 3. 计算 RS 和 RSI
        rs = avg_gain / (avg_loss + 1e-6)
        rsi_line = 100 - (100 / (1 + rs))
        
        # 4. RSI 信号线
        rsi_sma = rsi_line.rolling(window=signal_period, min_periods=1).mean()
        
        # 5. 辅助指标
        rsi_slope = rsi_line.diff()
        
        # 6. 成交量
        volume_ma = volume.rolling(window=20, min_periods=1).mean()
        volume_ratio = volume / (volume_ma + 1e-6)
        
        # 7. 【新增】计算 ATR (用于价格形态判定的点数阈值)
        c_prev = close_adj.shift(1)
        tr = pd.DataFrame(np.maximum(high_adj - low_adj, 
                          np.maximum((high_adj - c_prev).abs(), (low_adj - c_prev).abs())),
                          index=close_adj.index, columns=close_adj.columns)
        atr = tr.rolling(window=rsi_period).mean()
        
        return rsi_line, rsi_sma, rsi_slope, volume_ratio, atr

    # single_bar_signals 和 multi_bar_signals 仅涉及 RSI 数值，无需修改
    def single_bar_signals(self, rsi_line, rsi_sma, rsi_slope):
        signals = {}
        rsi_prev = rsi_line.shift(1)
        sma_prev = rsi_sma.shift(1)
        
        # 交叉
        golden_cross = ((rsi_prev <= sma_prev) & (rsi_line > rsi_sma)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((rsi_prev >= sma_prev) & (rsi_line < rsi_sma)).astype(float) * self.signal_strength["death_cross"]
        
        # 突破
        signals["overbought_breakthrough"] = ((rsi_prev <= 70) & (rsi_line > 70)).astype(float) * self.signal_strength["overbought_breakthrough"]
        signals["oversold_breakthrough"] = ((rsi_prev >= 30) & (rsi_line < 30)).astype(float) * self.signal_strength["oversold_breakthrough"]
        
        # 趋势
        signals["trend_acceleration"] = ((rsi_slope > rsi_slope.shift(1)) & (rsi_line > 50)).astype(float) * self.signal_strength["trend_acceleration"]
        
        # 状态
        signals["overbought_signal"] = (rsi_line > 70).astype(float) * self.signal_strength["overbought_signal"]
        signals["oversold_signal"] = (rsi_line < 30).astype(float) * self.signal_strength["oversold_signal"]
        
        signals["golden_cross"] = golden_cross
        signals["death_cross"] = death_cross
        return signals

    def divergence_signals(self, rsi_line, close_adj, atr, lookback_period=10):
        """
        背离信号 (期货修正版)
        【修改】使用 ATR 缓冲判断价格极值
        """
        signals = {}
        close_high = close_adj.rolling(lookback_period).max()
        close_low = close_adj.rolling(lookback_period).min()
        rsi_high = rsi_line.rolling(lookback_period).max()
        rsi_low = rsi_line.rolling(lookback_period).min()

        threshold = atr * 0.5

        # 顶背离：价格创新高 (Close > High - Threshold)，RSI未创新高
        is_top_divergence = (close_adj > close_high.shift(5) - threshold) & \
                            (rsi_line < rsi_high.shift(5)) & \
                            (rsi_line > 50)
        signals["top_divergence"] = is_top_divergence.astype(float) * self.signal_strength["top_divergence"]

        # 底背离
        is_bottom_divergence = (close_adj < close_low.shift(5) + threshold) & \
                               (rsi_line > rsi_low.shift(5)) & \
                               (rsi_line < 50)
        signals["bottom_divergence"] = is_bottom_divergence.astype(float) * self.signal_strength["bottom_divergence"]

        return signals

    def pattern_signals(self, rsi_line, close_adj, atr, window=5):
        """
        形态信号
        【修改】所有涉及价格百分比比较的逻辑改为 ATR 逻辑
        """
        signals = {}
        
        rsi_max = rsi_line.rolling(window).max()
        price_max = close_adj.rolling(window).max()
        
        # 通道突破 (RSI自身数值比较，无需修改)
        is_channel_breakthrough = (rsi_line > rsi_max.shift(1)) 
        signals["channel_breakthrough"] = is_channel_breakthrough.astype(float) * self.signal_strength["channel_breakthrough"]

        # 突破/回调确认
        # 突破: RSI新高 且 价格新高
        is_breakthrough_confirmation = (rsi_line > rsi_max.shift(1)) & (close_adj > price_max.shift(1))
        
        # 回调确认: RSI回调 但 价格跌幅有限 (原逻辑 Price < Max * 0.98 -> 现逻辑 Price < Max - 0.5*ATR)
        # 这对于负数价格也是安全的 (例如 -100 < -98 - 2)
        threshold_price = atr * 0.5
        is_pullback_confirmation = (rsi_line < rsi_max.shift(1) * 0.9) & (close_adj < price_max.shift(1) - threshold_price)
        
        signals["breakthrough_confirmation"] = is_breakthrough_confirmation.astype(float) * self.signal_strength["breakthrough_confirmation"]
        signals["pullback_confirmation"] = is_pullback_confirmation.astype(float) * self.signal_strength["pullback_confirmation"]

        return signals
    
    def volume_surge_signal(self, volume_ratio, volume_surge_threshold=1.5):
        is_volume_surge = (volume_ratio > volume_surge_threshold).astype(float) * self.signal_strength["volume_surge"]
        return {"volume_surge": is_volume_surge}

    def continuous_signals(self, rsi_line, rsi_slope, lookback_period=20):
        """返回可用于排序/回归的连续 RSI 特征。"""
        normalized_value = ((rsi_line - 50.0) / 50.0).clip(
            lower=-1.0, upper=1.0
        ).fillna(0.0)
        slope_rate = (rsi_slope / 50.0).clip(lower=-1.0, upper=1.0).fillna(0.0)

        rsi_min = rsi_line.rolling(window=lookback_period, min_periods=1).min()
        rsi_max = rsi_line.rolling(window=lookback_period, min_periods=1).max()
        rsi_range = (rsi_max - rsi_min).replace(0.0, np.nan)
        range_position = (
            (2.0 * (rsi_line - rsi_min) / rsi_range) - 1.0
        ).clip(lower=-1.0, upper=1.0).fillna(0.0)

        return {
            "normalized_value": normalized_value,
            "slope_rate": slope_rate,
            "range_position": range_position,
        }

    def get_total_signal_matrix(self, Open, High, Low, Close, Volume, 
                                HighAdj, LowAdj, CloseAdj, # 必需 Adj
                                rsi_period=14, signal_period=5, 
                                enabled_signals=None):
        
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        sum_buy = pd.DataFrame(0.0, index=CloseAdj.index, columns=CloseAdj.columns)
        sum_sell = pd.DataFrame(0.0, index=CloseAdj.index, columns=CloseAdj.columns)

        # 1. 计算组件 (含 ATR)
        rsi_line, rsi_sma, rsi_slope, vol_ratio, atr = self.get_rsi_components(
            CloseAdj, HighAdj, LowAdj, Volume, rsi_period, signal_period
        )

        # 2. 获取信号
        single = self.single_bar_signals(rsi_line, rsi_sma, rsi_slope)
        div = self.divergence_signals(rsi_line, CloseAdj, atr)
        patterns = self.pattern_signals(rsi_line, CloseAdj, atr)
        vol_surge = self.volume_surge_signal(vol_ratio)
        
        all_signals = {**single, **div, **patterns, **vol_surge}

        # 3. 累加
        for signal_name, signal_matrix in all_signals.items():
            if signal_name in enabled_signals and signal_matrix is not None:
                buy_mask = signal_matrix > 0
                sum_buy += signal_matrix.where(buy_mask, 0)
                
                sell_mask = signal_matrix < 0
                sum_sell += signal_matrix.where(sell_mask, 0)

        sum_buy = sum_buy.fillna(0)
        sum_sell = sum_sell.fillna(0)
        
        sum_buy[:rsi_period] = 0.0
        sum_sell[:rsi_period] = 0.0

        return sum_buy, sum_sell

    def get_factor_matrices(self, Open, High, Low, Close, Volume, 
                           HighAdj, LowAdj, CloseAdj,
                           rsi_period=14, signal_period=5):
        """拆分因子"""
        rsi_line, rsi_sma, rsi_slope, vol_ratio, atr = self.get_rsi_components(
            CloseAdj, HighAdj, LowAdj, Volume, rsi_period, signal_period
        )
        
        single = self.single_bar_signals(rsi_line, rsi_sma, rsi_slope)
        div = self.divergence_signals(rsi_line, CloseAdj, atr)
        patterns = self.pattern_signals(rsi_line, CloseAdj, atr)
        vol_surge = self.volume_surge_signal(vol_ratio)
        continuous = self.continuous_signals(rsi_line, rsi_slope)

        all_factors = {**single, **div, **patterns, **vol_surge, **continuous}

        for name, df in all_factors.items():
            df = df.reindex_like(CloseAdj).astype(float).fillna(0.0)
            df.iloc[:rsi_period * 2] = 0.0
            all_factors[name] = df

        return all_factors
