import pandas as pd
import numpy as np
from itertools import chain
'''
from strategys.技术面.ROC import ROC
trans = ROC()
# 这里分别得到不同的买入卖出信号矩阵
signal_apo_buy,signal_apo_sell = trans.get_total_signal_matrix(Close_data,Volume)
signals_apo_search = trans.get_detailed_signals_dataframe(Close_data,Volume)'''


class ROC:
    """
    ROC (Rate of Change) 变动率指标技术面综合分析类。
    实现核心ROC指标计算和多种ROC形态的向量化检测。
    """

    def __init__(self):
        # ROC信号强度定义 (正值: 买入/看涨, 负值: 卖出/看跌)
        self.signal_strength = {
            # 基础金叉死叉
            "golden_cross": 0.5,
            "death_cross": -0.5,
            # 零轴/正负值突破
            "positive_breakthrough": 0.6,
            "negative_breakthrough": -0.6,
            "zero_line_breakthrough": 0.7,
            "zero_line_pullback": -0.4, # 零轴回踩（空头确认）
            "bull_bear_transition": 0.7, # 与 zero_line_breakthrough 逻辑一致
            # 背离
            "top_divergence": -0.8,
            "bottom_divergence": 0.8,
            # 趋势/强度
            "trend_acceleration": 0.5, # 动量加速
            "trend_deceleration": -0.3, # 动量减速（顶部减速，视为看跌减速）
            "strong_zone": 0.4,
            "weak_zone": -0.4,
            "breakthrough_confirmation": 0.6,
            "pullback_confirmation": -0.4,
            # 极值/反转
            "overbought_signal": -0.5,
            "oversold_signal": 0.5,
            "extreme_reversal_buy": 0.9,
            "extreme_reversal_sell": -0.9,
            # 复杂形态（双顶底等）
            "double_bottom": 0.7,
            "double_top": -0.7,
            "triple_bottom": 0.9,
            "triple_top": -0.9,
            "head_shoulders_bottom": 0.8,
            "head_shoulders_top": -0.8,
            # 辅助信号
            "volume_surge": 0.1, # 放量
            # 楔形/三角形/通道等（在原代码中定义模糊，赋予中性/低强度）
            "rising_wedge": 0.1,
            "falling_wedge": -0.1,
            "triangle_convergence": 0.1,
            "triangle_divergence": -0.1,
            "channel_breakthrough": 0.2,
            "channel_pullback": 0.1,
        }

        self.continuous_signal_names = [
            "relative_value",
            "slope_rate",
            "range_position",
        ]
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names

    def get_roc_components(self, Close_data, Volume, roc_period=12, signal_period=5):
        """向量化计算ROC核心组件"""
        
        # 1. ROC Line (变动率线)
        roc_line = ((Close_data - Close_data.shift(roc_period)) / 
                    (Close_data.shift(roc_period) + 1e-6)) * 100
        
        # 2. ROC SMA/EMA (信号线，采用原代码的5周期SMA和EMA)
        roc_sma = roc_line.rolling(window=signal_period, min_periods=1).mean()
        roc_ema = roc_line.ewm(span=signal_period, adjust=False).mean()
        
        # 3. 辅助指标
        roc_slope = roc_line - roc_line.shift(1)
        roc_momentum = roc_slope - roc_slope.shift(1) # 二阶动量
        roc_volatility = roc_line.rolling(window=10).std()
        
        # 4. 成交量指标 (使用20周期MA)
        volume_ma = Volume.rolling(window=20, min_periods=1).mean()
        volume_ratio = Volume / volume_ma
        
        return roc_line, roc_sma, roc_ema, roc_slope, roc_momentum, roc_volatility, volume_ratio

    def single_bar_signals(self, roc_line, roc_sma, roc_slope, roc_volatility):
        """向量化检测基于单根/连续两根K线的ROC信号"""
        signals = {}
        roc_line_prev = roc_line.shift(1)
        roc_sma_prev = roc_sma.shift(1)
        
        # 辅助变量
        above_zero = roc_line > 0
        below_zero = roc_line < 0
        roc_slope_prev = roc_slope.shift(1)
        
        # 1. ROC金叉/死叉 (ROC线 vs ROC SMA)
        golden_cross = ((roc_line_prev <= roc_sma_prev) & (roc_line > roc_sma)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((roc_line_prev >= roc_sma_prev) & (roc_line < roc_sma)).astype(float) * self.signal_strength["death_cross"]
        
        # 2. 零轴突破 / 零轴回踩
        positive_cross = (roc_line_prev <= 0) & above_zero
        negative_cross = (roc_line_prev > 0) & (roc_line <= 0)
        signals["zero_line_breakthrough"] = positive_cross.astype(float) * self.signal_strength["zero_line_breakthrough"]
        signals["zero_line_pullback"] = negative_cross.astype(float) * self.signal_strength["zero_line_pullback"]
        
        # 零轴突破相关 (正值突破/多空转换)
        signals["positive_breakthrough"] = positive_cross.astype(float) * self.signal_strength["positive_breakthrough"]
        signals["bull_bear_transition"] = positive_cross.astype(float) * self.signal_strength["bull_bear_transition"]
        signals["negative_breakthrough"] = negative_cross.astype(float) * self.signal_strength["negative_breakthrough"]

        # 3. ROC趋势加速/减速 (基于斜率的逻辑)
        # 加速: 斜率增加且为正 ROC Line > 0
        is_accel = (roc_slope > roc_slope_prev) & above_zero
        # 减速: 斜率减小且为负 ROC Line < 0 (原代码的减速逻辑)
        is_decel = (roc_slope < roc_slope_prev) & below_zero
        signals["trend_acceleration"] = is_accel.astype(float) * self.signal_strength["trend_acceleration"]
        signals["trend_deceleration"] = is_decel.astype(float) * self.signal_strength["trend_deceleration"]

        # 4. ROC超买/超卖信号 (动态阈值：+/- 2倍波动率)
        vol_2x = roc_volatility * 2
        is_overbought = (roc_line > vol_2x)
        is_oversold = (roc_line < vol_2x * -1)
        
        # 强势/弱势区间 (原代码的固定阈值: +/- 5%)
        is_strong_zone = (roc_line > 5)
        is_weak_zone = (roc_line < -5)
        
        signals["overbought_signal"] = is_overbought.astype(float) * self.signal_strength["overbought_signal"]
        signals["oversold_signal"] = is_oversold.astype(float) * self.signal_strength["oversold_signal"]
        signals["strong_zone"] = is_strong_zone.astype(float) * self.signal_strength["strong_zone"]
        signals["weak_zone"] = is_weak_zone.astype(float) * self.signal_strength["weak_zone"]

        # 5. ROC极值反转 (极值+斜率反转)
        vol_2_5x = roc_volatility * 2.5
        is_extreme_reversal_sell = (roc_line > vol_2_5x) & (roc_slope < 0)
        is_extreme_reversal_buy = (roc_line < vol_2_5x * -1) & (roc_slope > 0)
        signals["extreme_reversal_sell"] = is_extreme_reversal_sell.astype(float) * self.signal_strength["extreme_reversal_sell"]
        signals["extreme_reversal_buy"] = is_extreme_reversal_buy.astype(float) * self.signal_strength["extreme_reversal_buy"]
        
        # 6. 基础金叉/死叉 (整合入结果)
        signals["golden_cross"] = golden_cross
        signals["death_cross"] = death_cross
        
        return signals

    def zero_cross_signals(self, roc_line):
        """ROC 零轴上/下穿信号（简化版，用于因子拆分）"""
        signals = {}
        prev = roc_line.shift(1)
        signals["zero_line_breakthrough"] = ((prev <= 0) & (roc_line > 0)).astype(float) * self.signal_strength["zero_line_breakthrough"]
        signals["zero_line_pullback"] = ((prev > 0) & (roc_line <= 0)).astype(float) * self.signal_strength["zero_line_pullback"]
        return signals

    def ma_cross_signals_simple(self, roc_line, ma_line):
        """简单的ROC线与MA线交叉信号"""
        signals = {}
        roc_prev = roc_line.shift(1)
        ma_prev = ma_line.shift(1)

        # ROC 上穿 MA
        golden = ((roc_prev <= ma_prev) & (roc_line > ma_line)).astype(float) * self.signal_strength["golden_cross"]
        # ROC 下穿 MA
        death = ((roc_prev >= ma_prev) & (roc_line < ma_line)).astype(float) * self.signal_strength["death_cross"]

        signals["ma_golden_cross"] = golden
        signals["ma_death_cross"] = death
        return signals

    def extreme_signals(self, roc_line, lookback_period=120):
        """极端偏离信号：基于分位数的高低位识别"""
        high_q = roc_line.rolling(lookback_period).quantile(0.9)
        low_q = roc_line.rolling(lookback_period).quantile(0.1)

        extreme_high = (roc_line > high_q).astype(float) * self.signal_strength["extreme_reversal_sell"]
        extreme_low = (roc_line < low_q).astype(float) * self.signal_strength["extreme_reversal_buy"]

        return {
            "extreme_high": extreme_high,
            "extreme_low": extreme_low
        }

    def multi_bar_signals(self, roc_line):
        """向量化检测基于3-4根K线的形态（双/三重顶底, 头肩顶底）"""
        signals = {}
        
        # N周期前的值
        roc_curr = roc_line
        roc_prev1 = roc_line.shift(1)
        roc_prev2 = roc_line.shift(2)
        roc_prev3 = roc_line.shift(3)
        
        # 原代码中的阈值是固定值 2
        THRESHOLD = 2.0 
        
        # ****************************
        # 简单形态：双底/双顶 (需要3个点)
        # ****************************
        # 双底: V-A-V (V1, A, V2), V1/V2相似, A为峰值 < -2
        is_double_bottom = (roc_prev2 < roc_prev1) & \
                           (roc_curr < roc_prev1) & \
                           (np.abs(roc_prev2 - roc_curr) < THRESHOLD) & \
                           (roc_prev1 < -THRESHOLD)
        signals["double_bottom"] = is_double_bottom.astype(float) * self.signal_strength["double_bottom"]

        # 双顶: A-V-A (A1, V, A2), A1/A2相似, V为谷值 > 2
        is_double_top = (roc_prev2 > roc_prev1) & \
                        (roc_curr > roc_prev1) & \
                        (np.abs(roc_prev2 - roc_curr) < THRESHOLD) & \
                        (roc_prev1 > THRESHOLD)
        signals["double_top"] = is_double_top.astype(float) * self.signal_strength["double_top"]

        # ****************************
        # 复杂形态：三重底/顶 (需要4个点)
        # ****************************
        # 三重底: V1-A1-V2-A2 (V1, A1, V2, A2), V1, V2, V3 (V3=curr) 相似, A1/A2为峰值 < -2
        is_triple_bottom = (roc_prev3 < roc_prev2) & (roc_prev1 < roc_prev2) & (roc_curr < roc_prev2) & \
                           (np.abs(roc_prev3 - roc_prev1) < THRESHOLD) & \
                           (np.abs(roc_prev1 - roc_curr) < THRESHOLD) & \
                           (roc_prev2 < -THRESHOLD)
        signals["triple_bottom"] = is_triple_bottom.astype(float) * self.signal_strength["triple_bottom"]

        # 三重顶
        is_triple_top = (roc_prev3 > roc_prev2) & (roc_prev1 > roc_prev2) & (roc_curr > roc_prev2) & \
                        (np.abs(roc_prev3 - roc_prev1) < THRESHOLD) & \
                        (np.abs(roc_prev1 - roc_curr) < THRESHOLD) & \
                        (roc_prev2 > THRESHOLD)
        signals["triple_top"] = is_triple_top.astype(float) * self.signal_strength["triple_top"]

        # ****************************
        # 复杂形态：头肩底/顶 (需要4个点)
        # ****************************
        # 头肩底: S1-H-S2, S1/S2高, H低 (原代码的简化逻辑)
        is_hsb = (roc_prev3 > roc_prev1) & (roc_prev2 < roc_prev3) & \
                 (roc_prev2 < roc_curr) & (roc_curr > roc_prev1) & (roc_prev2 < -5)
        signals["head_shoulders_bottom"] = is_hsb.astype(float) * self.signal_strength["head_shoulders_bottom"]

        # 头肩顶: S1-H-S2, S1/S2低, H高
        is_hst = (roc_prev3 < roc_prev1) & (roc_prev2 > roc_prev3) & \
                 (roc_prev2 > roc_curr) & (roc_curr < roc_prev1) & (roc_prev2 > 5)
        signals["head_shoulders_top"] = is_hst.astype(float) * self.signal_strength["head_shoulders_top"]

        return signals


    def divergence_signals(self, roc_line, close_prices, lookback_period=10):
        """向量化检测顶底背离形态（价格和ROC的比较）"""
        signals = {}
        
        # 使用N周期滚动最大/最小值 (N=10)
        close_high = close_prices.rolling(window=lookback_period, min_periods=5).max()
        close_low = close_prices.rolling(window=lookback_period, min_periods=5).min()
        roc_high = roc_line.rolling(window=lookback_period, min_periods=5).max()
        roc_low = roc_line.rolling(window=lookback_period, min_periods=5).min()

        # 1. ROC顶背离（价格创新高但ROC未创新高） - 比较当前（i）和 i-5 的高点
        is_top_divergence = (close_prices > close_high.shift(5)) & \
                            (roc_line < roc_high.shift(5)) & \
                            (roc_line > 0)
        signals["top_divergence"] = is_top_divergence.astype(float) * self.signal_strength["top_divergence"]

        # 2. ROC底背离（价格创新低但ROC未创新低） - 比较当前（i）和 i-5 的低点
        is_bottom_divergence = (close_prices < close_low.shift(5)) & \
                               (roc_line > roc_low.shift(5)) & \
                               (roc_line < 0)
        signals["bottom_divergence"] = is_bottom_divergence.astype(float) * self.signal_strength["bottom_divergence"]

        return signals

    def pattern_signals(self, roc_line, close_prices, window=5):
        """向量化检测楔形/三角形/通道/确认形态 (基于原代码的简化逻辑)"""
        signals = {}
        
        # 5日滚动数据
        roc_roll = roc_line.rolling(window=window)
        price_roll = close_prices.rolling(window=window)
        
        roc_max = roc_roll.max()
        roc_min = roc_roll.min()
        price_max = price_roll.max()
        
        # 5周期差值
        roc_diff = roc_line - roc_line.shift(4)
        price_diff = close_prices - close_prices.shift(4)

        # 1. 楔形上升/下降 (ROC和价格同向移动)
        is_rising_wedge = (roc_diff > 0) & (price_diff > 0)
        is_falling_wedge = (roc_diff < 0) & (price_diff < 0)
        signals["rising_wedge"] = is_rising_wedge.astype(float) * self.signal_strength["rising_wedge"]
        signals["falling_wedge"] = is_falling_wedge.astype(float) * self.signal_strength["falling_wedge"]

        # 2. 三角形收敛/发散 (基于ROC极差的变化)
        roc_range = roc_max - roc_min
        roc_range_prev = roc_line.shift(2).rolling(window=3).max() - roc_line.shift(2).rolling(window=3).min()
        
        is_convergence = roc_range < roc_range_prev
        is_divergence = roc_range > roc_range_prev
        signals["triangle_convergence"] = is_convergence.astype(float) * self.signal_strength["triangle_convergence"]
        signals["triangle_divergence"] = is_divergence.astype(float) * self.signal_strength["triangle_divergence"]

        # 3. 通道突破/回踩 (基于ROC的极值突破)
        is_channel_breakthrough = (roc_line > roc_max.shift(1) * 1.1) | (roc_line < roc_min.shift(1) * 1.1)
        is_channel_pullback = (roc_line <= roc_max.shift(1) * 0.9) & (roc_line >= roc_min.shift(1) * 0.9)
        signals["channel_breakthrough"] = is_channel_breakthrough.astype(float) * self.signal_strength["channel_breakthrough"]
        signals["channel_pullback"] = is_channel_pullback.astype(float) * self.signal_strength["channel_pullback"]

        # 4. 突破/回调确认
        is_breakthrough_confirmation = (roc_line > roc_max.shift(1)) & (close_prices > price_max.shift(1))
        is_pullback_confirmation = (roc_line < roc_max.shift(1) * 0.8) & (close_prices < price_max.shift(1) * 0.98)
        signals["breakthrough_confirmation"] = is_breakthrough_confirmation.astype(float) * self.signal_strength["breakthrough_confirmation"]
        signals["pullback_confirmation"] = is_pullback_confirmation.astype(float) * self.signal_strength["pullback_confirmation"]

        return signals
    
    def volume_surge_signal(self, volume_ratio, volume_surge_threshold=1.5):
        """向量化检测放量信号"""
        is_volume_surge = (volume_ratio > volume_surge_threshold).astype(float) * self.signal_strength["volume_surge"]
        return {"volume_surge": is_volume_surge}

    def continuous_signals(self, roc_line, roc_slope, lookback_period=20):
        """返回可用于排序/回归的连续 ROC 特征。"""
        relative_value = (roc_line / 100.0).clip(lower=-1.0, upper=1.0).fillna(0.0)
        slope_rate = (roc_slope / 100.0).clip(lower=-1.0, upper=1.0).fillna(0.0)

        roc_min = roc_line.rolling(window=lookback_period, min_periods=1).min()
        roc_max = roc_line.rolling(window=lookback_period, min_periods=1).max()
        roc_range = (roc_max - roc_min).replace(0.0, np.nan)
        range_position = (
            (2.0 * (roc_line - roc_min) / roc_range) - 1.0
        ).clip(lower=-1.0, upper=1.0).fillna(0.0)

        return {
            "relative_value": relative_value,
            "slope_rate": slope_rate,
            "range_position": range_position,
        }


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                roc_period=12, signal_period=5, divergence_threshold=0.02, volume_surge_threshold=1.5, enabled_signals=None):
        """
        整合启用的信号，生成最终的ROC信号强度矩阵
        
        参数:
            close_prices: pd.DataFrame，行=时间，列=标的，值=收盘价
            volume: pd.DataFrame，行=时间，列=标的，值=成交量
            ... (ROC参数)
            enabled_signals: list，指定启用的信号名称

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（>0买入，<0卖出）
        """
        
        if enabled_signals is None:
            enabled_signals = list(self.signal_strength.keys())
        
        # 1. 计算ROC核心组件
        roc_line, roc_sma, _, roc_slope, _, roc_volatility, volume_ratio = self.get_roc_components(
            Close_data, Volume, roc_period, signal_period
        )
        
        # 2. 获取所有信号矩阵
        single_bar = self.single_bar_signals(roc_line, roc_sma, roc_slope, roc_volatility)
        multi_bar = self.multi_bar_signals(roc_line)
        divergence = self.divergence_signals(roc_line, Close_data)
        patterns = self.pattern_signals(roc_line, Close_data)
        vol_surge = self.volume_surge_signal(volume_ratio, volume_surge_threshold)
        
        all_signals_dict = {**single_bar, **multi_bar, **divergence, **patterns, **vol_surge}
        
        # 3. 初始化累加矩阵
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 4. 累加信号强度
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_name in enabled_signals and signal_matrix is not None:
                # 填充 NaN 为 0 (处理滚动/shift操作导致的起始 NaN)
                signal_matrix = signal_matrix.reindex_like(Close_data).fillna(0.0)
                
                buy_mask = signal_matrix > 0
                sum_buy += signal_matrix.where(buy_mask, 0)
                
                sell_mask = signal_matrix < 0
                sum_sell += signal_matrix.where(sell_mask, 0)
        
        # 清除前 roc_period 个周期的信号（ROC线本身未计算）
        sum_buy[:roc_period] = 0.0
        sum_sell[:roc_period] = 0.0

        return sum_buy, sum_sell


    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name):
        """将信号矩阵转换为DataFrame记录列表"""
        
        stacked = signal_matrix.stack()
        non_zero_signals = stacked[stacked != 0]
        
        if len(non_zero_signals) == 0:
            return []
        
        dates, stocks = zip(*non_zero_signals.index)
        
        result_df = pd.DataFrame({
            'Date': dates,
            'Contract': stocks,
            'direction': np.where(non_zero_signals.values > 0, "buy", "sell"),
            'signal_name': signal_name,
            'strength': np.abs(non_zero_signals.values)
        })
        
        return result_df.to_dict('records')


    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                       roc_period=12, signal_period=5, divergence_threshold=0.02, volume_surge_threshold=1.5):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息
        """
        
        # 1. 计算ROC核心组件
        roc_line, roc_sma, _, roc_slope, _, roc_volatility, volume_ratio = self.get_roc_components(
            Close_data, Volume, roc_period, signal_period
        )
        
        # 2. 获取所有信号矩阵
        single_bar = self.single_bar_signals(roc_line, roc_sma, roc_slope, roc_volatility)
        multi_bar = self.multi_bar_signals(roc_line)
        divergence = self.divergence_signals(roc_line, Close_data)
        patterns = self.pattern_signals(roc_line, Close_data)
        vol_surge = self.volume_surge_signal(volume_ratio, volume_surge_threshold)

        # 3. 统一处理所有信号记录
        signal_processors = [single_bar, multi_bar, divergence, patterns, vol_surge]
        
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name)
            for processor in signal_processors
            for signal_name, signal_matrix in processor.items()
        ))
        
        # 4. 创建并返回排序后的DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
            signals_df = signals_df[signals_df['strength'] != 0]
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      roc_period=12, signal_period=5, divergence_threshold=0.02, 
                                      volume_surge_threshold=1.5, enabled_signals=None):
        """【新增方法】生成Multi-index格式的信号矩阵"""
        
        roc_line, roc_sma, _, roc_slope, _, roc_volatility, volume_ratio = self.get_roc_components(
            Close_data, Volume, roc_period, signal_period
        )
        
        single_bar = self.single_bar_signals(roc_line, roc_sma, roc_slope, roc_volatility)
        multi_bar = self.multi_bar_signals(roc_line)
        divergence = self.divergence_signals(roc_line, Close_data)
        patterns = self.pattern_signals(roc_line, Close_data)
        vol_surge = self.volume_surge_signal(volume_ratio, volume_surge_threshold)
        
        all_signals_dict = {**single_bar, **multi_bar, **divergence, **patterns, **vol_surge}
        
        if enabled_signals is not None:
            all_signals_dict = {k: v for k, v in all_signals_dict.items() if k in enabled_signals}
        
        signal_series_list = []
        signal_names = []
        
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_matrix is not None:
                signal_matrix = signal_matrix.reindex_like(Close_data).fillna(0.0)
                stacked_series = signal_matrix.stack()
                signal_series_list.append(stacked_series)
                signal_names.append(signal_name)
        
        if signal_series_list:
            signals_multi_index = pd.concat(signal_series_list, axis=1, keys=signal_names)
            signals_multi_index = signals_multi_index.fillna(0)
            
            if len(Close_data) > roc_period:
                valid_start_date = Close_data.index[roc_period]
                signals_multi_index = signals_multi_index[
                    signals_multi_index.index.get_level_values(0) >= valid_start_date
                ]
            
            current_dates = signals_multi_index.index.get_level_values(0)
            if pd.api.types.is_datetime64_any_dtype(current_dates):
                date_int32 = current_dates.strftime('%Y%m%d').astype('int32')
            elif pd.api.types.is_integer_dtype(current_dates):
                date_int32 = current_dates.astype('int32')
            else:
                date_int32 = pd.to_datetime(current_dates).strftime('%Y%m%d').astype('int32')
            
            contract_str = signals_multi_index.index.get_level_values(1).astype('string')
            new_index = pd.MultiIndex.from_arrays([date_int32, contract_str], names=['Date', 'Contract'])
            signals_multi_index.index = new_index
            signals_multi_index = signals_multi_index.astype('float32')
        else:
            signals_multi_index = pd.DataFrame(
                columns=signal_names if signal_names else [],
                index=pd.MultiIndex.from_tuples([], names=['Date', 'Contract'])
            )
            
        return signals_multi_index
    

    def get_factor_matrices(self, Close_data, Volume, roc_period=12, ma_period=9, signal_period=5):
        """
        拆分ROC的所有原子信号矩阵（每个信号一个矩阵）。
        """
        # 计算核心组件（含成交量衍生指标）
        roc_line, roc_sma, roc_ema, roc_slope, roc_momentum, roc_volatility, volume_ratio = self.get_roc_components(
            Close_data, Volume, roc_period, signal_period
        )
        
        single_bar = self.single_bar_signals(roc_line, roc_sma, roc_slope, roc_volatility)
        multi_bar = self.multi_bar_signals(roc_line)
        divergence = self.divergence_signals(roc_line, Close_data)
        patterns = self.pattern_signals(roc_line, Close_data)
        vol_surge = self.volume_surge_signal(volume_ratio)
        # MA 交叉信号：复用已有 single_bar 的 roc_sma；若指定 ma_period，与 signal_period 不同，则使用新的 SMA
        ma_line = roc_sma if ma_period == signal_period else roc_line.rolling(window=ma_period, min_periods=1).mean()
        ma_cross = self.ma_cross_signals_simple(roc_line, ma_line)
        zero = self.zero_cross_signals(roc_line)
        extreme = self.extreme_signals(roc_line)
        continuous = self.continuous_signals(roc_line, roc_slope)

        all_factors = {
            **single_bar,
            **multi_bar,
            **divergence,
            **patterns,
            **vol_surge,
            **ma_cross,
            **zero,
            **extreme,
            **continuous,
        }

        for name, df in all_factors.items():
            if df is not None:
                df = df.reindex_like(Close_data).fillna(0.0)
                df.iloc[:roc_period * 2] = 0.0
                all_factors[name] = df
            else:
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
                
        return all_factors
