from ast import Return
import pandas as pd
import numpy as np


'''MACD的参数，对应优缺点

MACD：Moving Average Convergence and Divergence

EMA： Exponential Moving Average         得到： EMA12 , EMA26
DIF: Difference                          得到： EMA12 - EMA26
DEA: Difference Exponential Average      得到： EMA(DIF(9))
Histogram（柱状线）                       得到： DIF - DEA

优点：平滑价格，过滤部分短期价格波动，避免情绪化交易，多周期适用（常用于反转）
缺点：震荡市表现不佳，且信号滞后性，
'''
import pandas as pd
import numpy as np
from itertools import chain

class MACD:
    def __init__(self):
        # 信号强度映射表 (保持不变)
        self.signal_strength = {
            "golden_cross": 0.5, "death_cross": -0.5,
            "above_zero_golden": 0.7, "below_zero_death": -0.7,
            "zero_break_above": 0.6, "zero_break_below": -0.6,
            "zero_pullback_bull": 0.5, "zero_pullback_bear": -0.5,
            "top_divergence": -0.6, "bottom_divergence": 0.6,
            "hist_turn_positive": 0.4, "hist_turn_negative": -0.4,
            "hist_expansion_bull": 0.3, "hist_expansion_bear": -0.3,
            "hist_contraction_bull": -0.2, "hist_contraction_bear": 0.2,
            "second_golden_cross": 0.6, "second_death_cross": -0.6,
            "hidden_top_divergence": -0.5, "hidden_bottom_divergence": 0.5,
            "double_top_divergence": -0.8, "double_bottom_divergence": 0.8,
            "hist_top_divergence": -0.6, "hist_bottom_divergence": 0.6,
            "extreme_high": -0.7, "extreme_low": 0.7,
            "cohesion_bull_divergence": 0.7, "cohesion_bear_divergence": -0.7,
            "hist_confirm_positive": 0.5, "hist_confirm_negative": -0.5,
            "divergence_repair_bull": 0.4, "divergence_repair_bear": -0.4,
        }
        self.all_signals = list(self.signal_strength.keys())

    def get_macd_components(self, close_adj, fast_period=12, slow_period=26, signal_period=9):
        """
        计算MACD核心组件
        【注】MACD对加法复权数据是天然兼容的（平移不变性），无需特殊数学修正。
        """
        ema_fast = close_adj.ewm(span=fast_period, adjust=False).mean()
        ema_slow = close_adj.ewm(span=slow_period, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal_period, adjust=False).mean()
        histogram = dif - dea
        return dif, dea, histogram

    def golden_death_matrix_detailed(self, dif, dea):
        """金叉/死叉 (逻辑安全)"""
        golden_cross = ((dif.shift(1) <= dea.shift(1)) & (dif > dea)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((dif.shift(1) >= dea.shift(1)) & (dif < dea)).astype(float) * self.signal_strength["death_cross"]
        
        above_zero = (dif > 0) & (dea > 0)
        above_zero_golden = golden_cross.where(above_zero, 0) * (self.signal_strength["above_zero_golden"] / self.signal_strength["golden_cross"])
        
        below_zero = (dif < 0) & (dea < 0)
        below_zero_death = death_cross.where(below_zero, 0) * (self.signal_strength["below_zero_death"] / self.signal_strength["death_cross"])
        
        return {"golden_cross": golden_cross, "death_cross": death_cross, "above_zero_golden": above_zero_golden, "below_zero_death": below_zero_death}

    def second_cross_signals(self, dif, dea, window=5):
        """二次金叉 (逻辑安全)"""
        golden_cross = (dif.shift(1) <= dea.shift(1)) & (dif > dea)
        death_cross = (dif.shift(1) >= dea.shift(1)) & (dif < dea)
        
        recent_golden = golden_cross.rolling(window).sum().shift(1) > 0
        recent_decline = (dif < dif.shift(1)).rolling(3).sum() >= 2
        second_golden = (recent_golden & recent_decline & golden_cross).astype(float) * self.signal_strength["second_golden_cross"]
        
        recent_death = death_cross.rolling(window).sum().shift(1) > 0
        recent_rise = (dif > dif.shift(1)).rolling(3).sum() >= 2
        second_death = (recent_death & recent_rise & death_cross).astype(float) * self.signal_strength["second_death_cross"]
        
        return {"second_golden_cross": second_golden, "second_death_cross": second_death}

    def divergence_signals_detailed(self, dif, close_adj, window=5):
        """常规背离 (基于极值位置比较，逻辑安全)"""
        price_high = close_adj.rolling(window).max()
        dif_high = dif.rolling(window).max()
        top_divergence = ((close_adj == price_high) & (dif < dif_high.shift(1))).astype(float) * self.signal_strength["top_divergence"]
        
        price_low = close_adj.rolling(window).min()
        dif_low = dif.rolling(window).min()
        bottom_divergence = ((close_adj == price_low) & (dif > dif_low.shift(1))).astype(float) * self.signal_strength["bottom_divergence"]

        return {"top_divergence": top_divergence, "bottom_divergence": bottom_divergence}

    def hidden_divergence_signals(self, dif, close_adj, window=5, threshold_points=5):
        """
        隐性背离 (期货修正版)
        【修改】原代码使用 pct_change() < 2%。
        【修正】改用 diff() 和 固定点数/ATR 阈值。
        这里简化为固定点数判定，意味着价格横盘震荡。
        """
        # 计算价格变动点数
        price_change = (close_adj - close_adj.shift(window)).abs()
        
        # 判定“价格小幅变动”：变动点数小于阈值
        is_price_flat = price_change < threshold_points
        
        price_high = close_adj.rolling(window).max()
        hidden_top = ((close_adj == price_high) & is_price_flat & (dif < dif.shift(1))).astype(float) * self.signal_strength["hidden_top_divergence"]
        
        price_low = close_adj.rolling(window).min()
        hidden_bottom = ((close_adj == price_low) & is_price_flat & (dif > dif.shift(1))).astype(float) * self.signal_strength["hidden_bottom_divergence"]
        
        return {"hidden_top_divergence": hidden_top, "hidden_bottom_divergence": hidden_bottom}

    def multiple_divergence_signals(self, dif, close_adj, window=5):
        """多次背离 (逻辑安全)"""
        price_high = close_adj.rolling(window).max()
        price_low = close_adj.rolling(window).min()
        dif_high = dif.rolling(window).max() 
        dif_low = dif.rolling(window).min()
        
        top_div_condition = (close_adj == price_high) & (dif < dif_high.shift(1))
        bottom_div_condition = (close_adj == price_low) & (dif > dif_low.shift(1))
        
        double_top = (top_div_condition & top_div_condition.shift(window).fillna(False)).astype(float) * self.signal_strength["double_top_divergence"]
        double_bottom = (bottom_div_condition & bottom_div_condition.shift(window).fillna(False)).astype(float) * self.signal_strength["double_bottom_divergence"]
        
        return {"double_top_divergence": double_top, "double_bottom_divergence": double_bottom}

    def histogram_divergence_signals(self, histogram, close_adj, window=5):
        """柱状背离 (逻辑安全)"""
        price_high = close_adj.rolling(window).max()
        price_low = close_adj.rolling(window).min()
        hist_high = histogram.rolling(window).max()
        hist_low = histogram.rolling(window).min()
        
        hist_top_divergence = ((close_adj == price_high) & (histogram < hist_high.shift(1))).astype(float) * self.signal_strength["hist_top_divergence"]
        hist_bottom_divergence = ((close_adj == price_low) & (histogram > hist_low.shift(1))).astype(float) * self.signal_strength["hist_bottom_divergence"]
        
        return {"hist_top_divergence": hist_top_divergence, "hist_bottom_divergence": hist_bottom_divergence}

    def extreme_deviation_signals(self, dif, dea, lookback_period=120):
        """极端偏离 (基于Rank/Quantile，逻辑安全)"""
        dif_high_quantile = dif.rolling(lookback_period).quantile(0.9)
        dif_low_quantile = dif.rolling(lookback_period).quantile(0.1)
        
        extreme_high = (dif > dif_high_quantile).astype(float) * self.signal_strength["extreme_high"]
        extreme_low = (dif < dif_low_quantile).astype(float) * self.signal_strength["extreme_low"]
        
        return {"extreme_high": extreme_high, "extreme_low": extreme_low}

    def cohesion_divergence_signals(self, dif, dea, histogram, cohesion_threshold=0.1):
        """黏合发散 (逻辑安全)"""
        # abs() 在 DIF, DEA 差值上是安全的
        cohesion_condition = (dif - dea).abs() < cohesion_threshold
        cohesion_period = cohesion_condition.rolling(3).sum() >= 2
        divergence_condition = histogram.abs() > histogram.shift(1).abs() * 1.5
        
        cohesion_bull = (cohesion_period.shift(1) & divergence_condition & (histogram > 0)).astype(float) * self.signal_strength["cohesion_bull_divergence"]
        cohesion_bear = (cohesion_period.shift(1) & divergence_condition & (histogram < 0)).astype(float) * self.signal_strength["cohesion_bear_divergence"]
        
        return {"cohesion_bull_divergence": cohesion_bull, "cohesion_bear_divergence": cohesion_bear}

    def histogram_confirmation_signals(self, histogram):
        """柱状确认 (逻辑安全)"""
        hist_positive_confirmed = ((histogram > 0) & (histogram.shift(1) > 0) & (histogram.shift(2) <= 0)).astype(float) * self.signal_strength["hist_confirm_positive"]
        hist_negative_confirmed = ((histogram < 0) & (histogram.shift(1) < 0) & (histogram.shift(2) >= 0)).astype(float) * self.signal_strength["hist_confirm_negative"]
        return {"hist_confirm_positive": hist_positive_confirmed, "hist_confirm_negative": hist_negative_confirmed}

    def divergence_repair_signals(self, dif, close_adj, window=10):
        """
        背离修复 (期货修正版)
        【修改】pct_change < 0.01 (震荡) -> 改为 diff().abs() < threshold
        """
        price_high = close_adj.rolling(window).max()
        price_low = close_adj.rolling(window).min()
        dif_high = dif.rolling(window).max()
        dif_low = dif.rolling(window).min()
        
        prev_top_div = (close_adj.shift(window) == price_high.shift(window)) & (dif.shift(window) < dif_high.shift(window+1))
        prev_bottom_div = (close_adj.shift(window) == price_low.shift(window)) & (dif.shift(window) > dif_low.shift(window+1))
        
        # 修正：使用差分绝对值判断横盘，假设 10个点以内算横盘
        price_consolidation = (close_adj.diff(5).abs() < 10) 
        
        dif_rising = dif > dif.shift(5)
        divergence_repair_bull = (prev_top_div & price_consolidation & dif_rising).astype(float) * self.signal_strength["divergence_repair_bull"]
        
        dif_falling = dif < dif.shift(5)
        divergence_repair_bear = (prev_bottom_div & price_consolidation & dif_falling).astype(float) * self.signal_strength["divergence_repair_bear"]
        
        return {"divergence_repair_bull": divergence_repair_bull, "divergence_repair_bear": divergence_repair_bear}

    def histogram_signals_detailed(self, histogram):
        """柱状图信号 (逻辑安全)"""
        hist_turn_positive = ((histogram.shift(1) <= 0) & (histogram > 0)).astype(float) * self.signal_strength["hist_turn_positive"]
        hist_turn_negative = ((histogram.shift(1) >= 0) & (histogram < 0)).astype(float) * self.signal_strength["hist_turn_negative"]
        
        hist_expansion_bull = ((histogram > 0) & (histogram > histogram.shift(1))).astype(float) * self.signal_strength["hist_expansion_bull"]
        hist_expansion_bear = ((histogram < 0) & (histogram < histogram.shift(1))).astype(float) * self.signal_strength["hist_expansion_bear"]
        
        hist_contraction_bull = ((histogram > 0) & (histogram < histogram.shift(1))).astype(float) * self.signal_strength["hist_contraction_bull"]
        hist_contraction_bear = ((histogram < 0) & (histogram > histogram.shift(1))).astype(float) * self.signal_strength["hist_contraction_bear"]

        return {
            "hist_turn_positive": hist_turn_positive, "hist_turn_negative": hist_turn_negative,
            "hist_expansion_bull": hist_expansion_bull, "hist_expansion_bear": hist_expansion_bear,
            "hist_contraction_bull": hist_contraction_bull, "hist_contraction_bear": hist_contraction_bear
        }

    def get_factor_matrices(self, Open, High, Low, Close, Volume, 
                           HighAdj, LowAdj, CloseAdj, # 必需 Adj
                           fast_period=12, slow_period=26, signal_period=9):
        """拆分因子矩阵"""
        dif, dea, hist = self.get_macd_components(CloseAdj, fast_period, slow_period, signal_period)

        golden_death = self.golden_death_matrix_detailed(dif, dea)
        second_cross = self.second_cross_signals(dif, dea)
        div = self.divergence_signals_detailed(dif, CloseAdj)
        hidden_div = self.hidden_divergence_signals(dif, CloseAdj)
        multi_div = self.multiple_divergence_signals(dif, CloseAdj)
        hist_div = self.histogram_divergence_signals(hist, CloseAdj)
        extreme = self.extreme_deviation_signals(dif, dea)
        cohesion = self.cohesion_divergence_signals(dif, dea, hist)
        hist_conf = self.histogram_confirmation_signals(hist)
        div_repair = self.divergence_repair_signals(dif, CloseAdj)
        hist_sigs = self.histogram_signals_detailed(hist)

        all_factors = {**golden_death, **second_cross, **div, **hidden_div, **multi_div, 
                    **hist_div, **extreme, **cohesion, **hist_conf, **div_repair, **hist_sigs}
        
        for name in all_factors:
            all_factors[name].iloc[:slow_period] = 0.0
                
        return all_factors