import pandas as pd
import numpy as np
from itertools import chain


'''from strategys.技术面.PPO import PPO
trans = PPO()
# 这里分别得到不同的买入卖出信号矩阵
signal_apo_buy,signal_apo_sell = trans.get_total_signal_matrix(Close_data,Volume)
signals_apo_search = trans.get_detailed_signals_dataframe(Close_data,Volume)'''

class PPO:
    """
    PPO (Percentage Price Oscillator) 百分比价格震荡指标技术面综合分析类。
    实现核心PPO指标计算和多种PPO形态的向量化检测。
    """

    def __init__(self):
        # PPO信号强度定义 (正值: 买入/看涨, 负值: 卖出/看跌)
        self.signal_strength = {
            # 基础金叉死叉
            "golden_cross": 0.5,
            "death_cross": -0.5,
            "above_zero_golden_cross": 0.7,
            "below_zero_death_cross": -0.7,
            # 零轴/柱状图信号
            "zero_line_breakthrough": 0.6,
            "zero_line_pullback": -0.5,
            "histogram_turn_positive": 0.5,
            "histogram_turn_negative": -0.5,
            "histogram_expansion_bull": 0.5,
            "histogram_contraction_bear": -0.5,
            # 背离
            "top_divergence": -0.8,
            "bottom_divergence": 0.8,
            # 趋势/强度
            "trend_acceleration": 0.5,
            "trend_deceleration": -0.3,
            "bull_bear_transition": 0.6, # 与 zero_line_breakthrough 逻辑一致
            "overbought_signal": -0.4,
            "oversold_signal": 0.4,
            "extreme_reversal_sell": -0.9,
            "extreme_reversal_buy": 0.9,
            "convergence": 0.1, # 粘合形态 (突破前信号)
            "divergence_ppo": -0.1, # 发散形态 (趋势延续，但可能不稳定)
            "stagnation": 0.1, # 钝化形态 (趋势减弱，中性)
            # 复杂形态（双顶底等）
            "double_bottom": 0.7,
            "double_top": -0.7,
            "triple_bottom": 0.9,
            "triple_top": -0.9,
            "head_shoulders_bottom": 0.8,
            "head_shoulders_top": -0.8,
            # 辅助信号
            "volume_surge": 0.1,
            "histogram_expansion_bear": -0.4,
            "histogram_contraction_bull": 0.4,
            # 楔形/三角形/通道等（原代码定义模糊，赋予中性/低强度）
            "rising_wedge": 0.1,
            "falling_wedge": -0.1,
            "triangle_convergence": 0.1,
            "triangle_divergence": -0.1,
            "channel_breakthrough": 0.2,
            "channel_pullback": 0.1,
            "cycle_resonance": 0.2,
            "cycle_divergence": -0.2,
        }

        self.all_signals = list(self.signal_strength.keys())

    def get_ppo_components(self, close_prices, volume, fast_period=12, slow_period=26, signal_period=9):
        """向量化计算PPO核心组件（PPO线、信号线、柱状图）"""
        
        # 1. 计算EMA
        fast_ema = close_prices.ewm(span=fast_period, adjust=False).mean()
        slow_ema = close_prices.ewm(span=slow_period, adjust=False).mean()
        
        # 2. PPO Line
        # 避免除以零
        ppo_line = ((fast_ema - slow_ema) / (slow_ema + 1e-6)) * 100
        
        # 3. Signal Line
        signal_line = ppo_line.ewm(span=signal_period, adjust=False).mean()
        
        # 4. Histogram
        histogram = ppo_line - signal_line
        
        # 5. 成交量指标 (使用20周期MA)
        volume_ma = volume.rolling(window=20, min_periods=1).mean()
        volume_ratio = volume / volume_ma
        
        return ppo_line, signal_line, histogram, fast_ema, slow_ema, volume_ratio

    def single_bar_signals(self, ppo_line, signal_line, histogram):
        """向量化检测基于单根/连续两根K线的PPO信号"""
        signals = {}
        ppo_line_prev = ppo_line.shift(1)
        signal_line_prev = signal_line.shift(1)
        histogram_prev = histogram.shift(1)
        
        # 辅助变量
        above_zero = ppo_line > 0
        below_zero = ppo_line < 0
        
        # 1. PPO金叉/死叉 (PPO线 vs Signal线)
        golden_cross = ((ppo_line_prev <= signal_line_prev) & (ppo_line > signal_line)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((ppo_line_prev >= signal_line_prev) & (ppo_line < signal_line)).astype(float) * self.signal_strength["death_cross"]
        
        # 2. PPO零轴上方金叉 / 零轴下方死叉 (复合信号)
        signals["above_zero_golden_cross"] = (golden_cross.abs() > 0) & above_zero.astype(float) * self.signal_strength["above_zero_golden_cross"]
        signals["below_zero_death_cross"] = (death_cross.abs() > 0) & below_zero.astype(float) * self.signal_strength["below_zero_death_cross"]

        # 3. PPO零轴突破 / 零轴回踩
        signals["zero_line_breakthrough"] = ((ppo_line_prev <= 0) & above_zero).astype(float) * self.signal_strength["zero_line_breakthrough"]
        signals["zero_line_pullback"] = ((ppo_line_prev > 0) & (ppo_line <= 0)).astype(float) * self.signal_strength["zero_line_pullback"]
        signals["bull_bear_transition"] = signals["zero_line_breakthrough"].copy() * self.signal_strength["bull_bear_transition"]

        # 4. PPO柱状图转正 / 转负 (零轴穿越)
        signals["histogram_turn_positive"] = ((histogram_prev <= 0) & (histogram > 0)).astype(float) * self.signal_strength["histogram_turn_positive"]
        signals["histogram_turn_negative"] = ((histogram_prev >= 0) & (histogram < 0)).astype(float) * self.signal_strength["histogram_turn_negative"]

        # 5. PPO柱状图放大 / 缩小 (动量加速/减速)
        hist_abs = histogram.abs()
        hist_prev_abs = histogram_prev.abs()
        
        # 放大 (扩张)
        is_expansion = (hist_abs > hist_prev_abs * 1.2)
        signals["histogram_expansion_bull"] = is_expansion.where(histogram > 0, 0).astype(float) * self.signal_strength["histogram_expansion_bull"]
        signals["histogram_expansion_bear"] = is_expansion.where(histogram < 0, 0).astype(float) * self.signal_strength["histogram_expansion_bear"]

        # 缩小 (收缩)
        is_contraction = (hist_abs < hist_prev_abs * 0.8)
        signals["histogram_contraction_bull"] = is_contraction.where(histogram > 0, 0).astype(float) * self.signal_strength["histogram_contraction_bull"]
        signals["histogram_contraction_bear"] = is_contraction.where(histogram < 0, 0).astype(float) * self.signal_strength["histogram_contraction_bear"]

        # 6. PPO超买 / 超卖信号 (固定百分比阈值: +/- 5 for PPO, +/- 2 for Hist)
        is_overbought = (ppo_line > 5) & (histogram > 2)
        is_oversold = (ppo_line < -5) & (histogram < -2)
        signals["overbought_signal"] = is_overbought.astype(float) * self.signal_strength["overbought_signal"]
        signals["oversold_signal"] = is_oversold.astype(float) * self.signal_strength["oversold_signal"]

        # 7. PPO粘合形态 / 钝化形态
        is_convergence = (ppo_line_prev.abs() < 0.5) & (ppo_line.abs() < 0.5) # PPO线接近零轴
        is_stagnation = (ppo_line - ppo_line_prev).abs() < 0.05 # PPO线变化极小 (钝化)
        signals["convergence"] = is_convergence.astype(float) * self.signal_strength["convergence"]
        signals["stagnation"] = is_stagnation.astype(float) * self.signal_strength["stagnation"]

        # 8. PPO发散形态 (PPO线持续在零轴附近波动) - 简化为 PPO线在小区间内震荡
        is_divergence_ppo = (ppo_line.abs() > 2) & (ppo_line_prev.abs() > 2) & ((ppo_line - ppo_line_prev).abs() > 0.5)
        signals["divergence_ppo"] = is_divergence_ppo.astype(float) * self.signal_strength["divergence_ppo"]
        
        # 9. 基础金叉/死叉 (整合入结果)
        signals["golden_cross"] = golden_cross
        signals["death_cross"] = death_cross
        
        return signals

    def multi_bar_signals(self, ppo_line, divergence_threshold=0.02):
        """向量化检测基于3-4根K线的形态（双/三重顶底, 头肩顶底, 极值反转）"""
        signals = {}
        
        # N周期前的值
        ppo_curr = ppo_line
        ppo_prev1 = ppo_line.shift(1)
        ppo_prev2 = ppo_line.shift(2)
        ppo_prev3 = ppo_line.shift(3)
        
        # ****************************
        # 简单形态：双底/双顶 (需要3个点)
        # ****************************
        # 双底: V-A-V (V1, A, V2), V1/V2相似, A为峰值 < 0
        is_double_bottom = (ppo_prev2 < ppo_prev1) & \
                           (ppo_curr < ppo_prev1) & \
                           (np.abs(ppo_prev2 - ppo_curr) < divergence_threshold * 100) & \
                           (ppo_prev1 < 0)
        signals["double_bottom"] = is_double_bottom.astype(float) * self.signal_strength["double_bottom"]

        # 双顶: A-V-A (A1, V, A2), A1/A2相似, V为谷值 > 0
        is_double_top = (ppo_prev2 > ppo_prev1) & \
                        (ppo_curr > ppo_prev1) & \
                        (np.abs(ppo_prev2 - ppo_curr) < divergence_threshold * 100) & \
                        (ppo_prev1 > 0)
        signals["double_top"] = is_double_top.astype(float) * self.signal_strength["double_top"]

        # ****************************
        # 复杂形态：三重底/顶 (需要4个点)
        # ****************************
        # 三重底: V1-A1-V2-A2 (V1, A1, V2, A2), V1, V2, V3 (V3=curr) 相似, A1/A2为峰值 < 0
        is_triple_bottom = (ppo_prev3 < ppo_prev2) & (ppo_prev1 < ppo_prev2) & (ppo_curr < ppo_prev2) & \
                           (np.abs(ppo_prev3 - ppo_prev1) < divergence_threshold * 100) & \
                           (np.abs(ppo_prev1 - ppo_curr) < divergence_threshold * 100) & \
                           (ppo_prev2 < 0)
        signals["triple_bottom"] = is_triple_bottom.astype(float) * self.signal_strength["triple_bottom"]

        # 三重顶
        is_triple_top = (ppo_prev3 > ppo_prev2) & (ppo_prev1 > ppo_prev2) & (ppo_curr > ppo_prev2) & \
                        (np.abs(ppo_prev3 - ppo_prev1) < divergence_threshold * 100) & \
                        (np.abs(ppo_prev1 - ppo_curr) < divergence_threshold * 100) & \
                        (ppo_prev2 > 0)
        signals["triple_top"] = is_triple_top.astype(float) * self.signal_strength["triple_top"]

        # ****************************
        # 复杂形态：头肩底/顶 (需要4个点)
        # ****************************
        # 头肩底: S1-H-S2, S1/S2高, H低 (原代码的简化逻辑)
        is_hsb = (ppo_prev3 > ppo_prev1) & (ppo_prev2 < ppo_prev3) & \
                 (ppo_prev2 < ppo_curr) & (ppo_curr > ppo_prev1) & (ppo_prev2 < 0)
        signals["head_shoulders_bottom"] = is_hsb.astype(float) * self.signal_strength["head_shoulders_bottom"]

        # 头肩顶: S1-H-S2, S1/S2低, H高
        is_hst = (ppo_prev3 < ppo_prev1) & (ppo_prev2 > ppo_prev3) & \
                 (ppo_prev2 > ppo_curr) & (ppo_curr < ppo_prev1) & (ppo_prev2 > 0)
        signals["head_shoulders_top"] = is_hst.astype(float) * self.signal_strength["head_shoulders_top"]
        
        # PPO 极值反转 (简化为 PPO 突破 +/- 10 后反向)
        is_extreme_reversal_buy = (ppo_line.shift(1) < -10) & (ppo_line > ppo_line.shift(1))
        is_extreme_reversal_sell = (ppo_line.shift(1) > 10) & (ppo_line < ppo_line.shift(1))
        signals["extreme_reversal_buy"] = is_extreme_reversal_buy.astype(float) * self.signal_strength["extreme_reversal_buy"]
        signals["extreme_reversal_sell"] = is_extreme_reversal_sell.astype(float) * self.signal_strength["extreme_reversal_sell"]

        return signals


    def divergence_signals(self, ppo_line, close_prices, lookback_period=10):
        """向量化检测顶底背离形态（价格和PPO的比较）"""
        signals = {}
        
        # 使用N周期滚动最大/最小值 (N=10)
        close_high = close_prices.rolling(window=lookback_period, min_periods=5).max()
        close_low = close_prices.rolling(window=lookback_period, min_periods=5).min()
        ppo_high = ppo_line.rolling(window=lookback_period, min_periods=5).max()
        ppo_low = ppo_line.rolling(window=lookback_period, min_periods=5).min()

        # 1. PPO顶背离（价格创新高但PPO未创新高） - 比较当前（i）和 i-5 的高点
        is_top_divergence = (close_prices > close_high.shift(5)) & \
                            (ppo_line < ppo_high.shift(5)) & \
                            (ppo_line > 0)
        signals["top_divergence"] = is_top_divergence.astype(float) * self.signal_strength["top_divergence"]

        # 2. PPO底背离（价格创新低但PPO未创新低） - 比较当前（i）和 i-5 的低点
        is_bottom_divergence = (close_prices < close_low.shift(5)) & \
                               (ppo_line > ppo_low.shift(5)) & \
                               (ppo_line < 0)
        signals["bottom_divergence"] = is_bottom_divergence.astype(float) * self.signal_strength["bottom_divergence"]

        return signals

    def trend_and_pattern_signals(self, ppo_line, close_prices, window=5):
        """向量化检测趋势加速/减速/楔形/通道等形态"""
        signals = {}
        
        ppo_prev1 = ppo_line.shift(1)
        ppo_prev2 = ppo_line.shift(2)
        
        # 5日滚动数据
        ppo_roll = ppo_line.rolling(window=window)
        price_roll = close_prices.rolling(window=window)
        
        ppo_max = ppo_roll.max()
        ppo_min = ppo_roll.min()
        
        # ****************************
        # 趋势加速/减速/多空转换 (基于原代码的简化逻辑)
        # ****************************
        # PPO趋势加速: PPO连续上升且 > 0
        is_accel = (ppo_line > ppo_prev1) & (ppo_prev1 > ppo_prev2) & (ppo_line > 0)
        # PPO趋势减速: PPO连续下降且 < 0 (原代码逻辑)
        is_decel = (ppo_line < ppo_prev1) & (ppo_prev1 < ppo_prev2) & (ppo_line < 0)
        
        signals["trend_acceleration"] = is_accel.astype(float) * self.signal_strength["trend_acceleration"]
        signals["trend_deceleration"] = is_decel.astype(float) * self.signal_strength["trend_deceleration"]

        # PPO多空转换: 与 zero_line_breakthrough 逻辑一致 (PPO_{i-3}, PPO_{i-2} < 0, PPO_i > 0)
        is_bull_bear_transition = (ppo_prev2 < 0) & (ppo_prev1 < 0) & (ppo_line > 0)
        signals["bull_bear_transition"] = is_bull_bear_transition.astype(float) * self.signal_strength["bull_bear_transition"]

        # ****************************
        # 楔形/通道等形态 (基于原代码的简化逻辑)
        # ****************************
        ppo_diff = ppo_line - ppo_line.shift(4)
        price_diff = close_prices - close_prices.shift(4)

        # 楔形上升/下降
        is_rising_wedge = (ppo_diff > 0) & (price_diff > 0)
        is_falling_wedge = (ppo_diff < 0) & (price_diff < 0)
        signals["rising_wedge"] = is_rising_wedge.astype(float) * self.signal_strength["rising_wedge"]
        signals["falling_wedge"] = is_falling_wedge.astype(float) * self.signal_strength["falling_wedge"]

        # 三角形收敛/发散 (基于PPO极差变化)
        ppo_range = ppo_max - ppo_min
        ppo_range_prev = ppo_line.shift(2).rolling(window=3).max() - ppo_line.shift(2).rolling(window=3).min()
        
        is_convergence = ppo_range < ppo_range_prev
        is_divergence = ppo_range > ppo_range_prev
        signals["triangle_convergence"] = is_convergence.astype(float) * self.signal_strength["triangle_convergence"]
        signals["triangle_divergence"] = is_divergence.astype(float) * self.signal_strength["triangle_divergence"]

        # 通道突破/回踩
        is_channel_breakthrough = (ppo_line > ppo_max.shift(1) * 1.05) | (ppo_line < ppo_min.shift(1) * 1.05)
        is_channel_pullback = (ppo_line <= ppo_max.shift(1) * 0.95) & (ppo_line >= ppo_min.shift(1) * 0.95)
        signals["channel_breakthrough"] = is_channel_breakthrough.astype(float) * self.signal_strength["channel_breakthrough"]
        signals["channel_pullback"] = is_channel_pullback.astype(float) * self.signal_strength["channel_pullback"]
        
        # 周期共振/背离 (假设 PPO 自身的高低点与价格趋势一致/不一致)
        is_cycle_resonance = (ppo_line > 0) & (ppo_line > ppo_prev1) # PPO 上升 > 0
        is_cycle_divergence = (ppo_line > 0) & (ppo_line < ppo_prev1) # PPO 下降 > 0
        signals["cycle_resonance"] = is_cycle_resonance.astype(float) * self.signal_strength["cycle_resonance"]
        signals["cycle_divergence"] = is_cycle_divergence.astype(float) * self.signal_strength["cycle_divergence"]

        return signals
    
    def volume_surge_signal(self, volume_ratio, volume_surge_threshold=1.5):
        """向量化检测放量信号"""
        is_volume_surge = (volume_ratio > volume_surge_threshold).astype(float) * self.signal_strength["volume_surge"]
        return {"volume_surge": is_volume_surge}


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume,
                                fast_period=12, slow_period=26, signal_period=9, 
                                divergence_threshold=0.02, volume_surge_threshold=1.5, enabled_signals=None):
        """
        整合启用的信号，生成最终的PPO信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            ... (PPO参数)
            enabled_signals: list，指定启用的信号名称

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（>0买入，<0卖出）
        """
        
        if enabled_signals is None:
            enabled_signals = list(self.signal_strength.keys())
        
        # 1. 计算PPO核心组件（只使用Close_data, Volume）
        ppo_line, signal_line, histogram, _, _, volume_ratio = self.get_ppo_components(
            Close_data, Volume, fast_period, slow_period, signal_period
        )

        # 2. 获取所有信号矩阵
        single_bar = self.single_bar_signals(ppo_line, signal_line, histogram)
        multi_bar = self.multi_bar_signals(ppo_line, divergence_threshold)
        divergence = self.divergence_signals(ppo_line, Close_data)
        patterns = self.trend_and_pattern_signals(ppo_line, Close_data)
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
        
        # 清除最初的慢速周期信号
        sum_buy[:slow_period] = 0.0
        sum_sell[:slow_period] = 0.0

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
                                       fast_period=12, slow_period=26, signal_period=9, 
                                       divergence_threshold=0.02, volume_surge_threshold=1.5):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息
        """
        
        # 1. 计算PPO核心组件（只使用Close_data, Volume）
        ppo_line, signal_line, histogram, _, _, volume_ratio = self.get_ppo_components(
            Close_data, Volume, fast_period, slow_period, signal_period
        )
        
        # 2. 获取所有信号矩阵
        single_bar = self.single_bar_signals(ppo_line, signal_line, histogram)
        multi_bar = self.multi_bar_signals(ppo_line, divergence_threshold)
        divergence = self.divergence_signals(ppo_line, Close_data)
        patterns = self.trend_and_pattern_signals(ppo_line, Close_data)
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
                                      fast_period=12, slow_period=26, signal_period=9, 
                                      divergence_threshold=0.02, volume_surge_threshold=1.5, enabled_signals=None):
        """【新增方法】生成Multi-index格式的信号矩阵"""
        
        # 1. 计算PPO核心组件
        ppo_line, signal_line, histogram, _, _, volume_ratio = self.get_ppo_components(
            Close_data, Volume, fast_period, slow_period, signal_period
        )
        
        # 2. 获取各类信号
        single_bar = self.single_bar_signals(ppo_line, signal_line, histogram)
        multi_bar = self.multi_bar_signals(ppo_line, divergence_threshold)
        divergence = self.divergence_signals(ppo_line, Close_data)
        patterns = self.trend_and_pattern_signals(ppo_line, Close_data)
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
            
            if len(Close_data) > slow_period:
                valid_start_date = Close_data.index[slow_period]
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
    

    def get_factor_matrices(self, Close_data, Volume, fast_period=12, slow_period=26, signal_period=9,
                            divergence_threshold=0.02, volume_surge_threshold=1.5):
        """
        拆分PPO的所有原子信号（逐信号矩阵）。
        返回 {signal_name: DataFrame(Date x Contract)}
        """
        ppo_line, signal_line, histogram, _, _, volume_ratio = self.get_ppo_components(
            Close_data, Volume, fast_period, slow_period, signal_period
        )

        single_bar = self.single_bar_signals(ppo_line, signal_line, histogram)
        multi_bar = self.multi_bar_signals(ppo_line, divergence_threshold)
        divergence = self.divergence_signals(ppo_line, Close_data)
        patterns = self.trend_and_pattern_signals(ppo_line, Close_data)
        vol_surge = self.volume_surge_signal(volume_ratio, volume_surge_threshold)

        all_factors = {**single_bar, **multi_bar, **divergence, **patterns, **vol_surge}
        min_period = max(fast_period, slow_period)
        for name, df in all_factors.items():
            if df is not None:
                df = df.reindex_like(Close_data).fillna(0.0)
                df.iloc[:min_period * 2] = 0.0
                all_factors[name] = df
            else:
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        return all_factors