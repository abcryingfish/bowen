import pandas as pd
import numpy as np
from itertools import chain

class MOM:
    """
    MOM (Momentum) 动量指标技术面综合分析类。
    实现核心MOM指标计算和多种MOM形态的向量化检测。
    """

    def __init__(self):
        # MOM信号强度定义 (正值: 买入/看涨, 负值: 卖出/看跌)
        self.signal_strength = {
            # 基础金叉死叉
            "golden_cross": 0.5,
            "death_cross": -0.5,
            # 零轴/正负值突破
            "positive_breakthrough": 0.6,
            "negative_breakthrough": -0.6,
            "zero_line_breakthrough": 0.7,
            "zero_line_pullback": -0.4, # 零轴回踩（空头确认）
            "bull_bear_transition": 0.7, # 与 zero_line_breakthrough 逻辑相同，但作为单独信号
            # 背离
            "top_divergence": -0.8,
            "bottom_divergence": 0.8,
            # 趋势/强度
            "trend_acceleration": 0.5, # 动量加速
            "trend_deceleration": -0.3, # 动量减速（顶部减速，视为看跌减速）
            "strong_zone": 0.3,
            "weak_zone": -0.3,
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
            "momentum_rate",
            "momentum_strength",
            "volume_ratio",
        ]
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names

    def get_mom_components(self, close_prices, volume, mom_period=10):
        """向量化计算MOM核心组件"""
        
        # 1. MOM Line (MOM线)
        mom_line = close_prices - close_prices.shift(mom_period)
        
        # 2. MOM Rate (MOM变化率)
        mom_rate = (mom_line / close_prices.shift(mom_period)) * 100
        
        # 3. MOM SMA (MOM线信号线，采用原代码的5周期)
        mom_sma = mom_line.rolling(window=5, min_periods=1).mean()
        
        # 4. 辅助指标
        mom_slope = mom_line - mom_line.shift(1)
        mom_momentum = mom_slope - mom_slope.shift(1)
        mom_volatility = mom_line.rolling(window=10).std()
        
        # 5. 成交量指标 (使用20周期MA)
        volume_ma = volume.rolling(window=20, min_periods=1).mean()
        volume_ratio = volume / volume_ma
        
        return mom_line, mom_sma, mom_slope, mom_momentum, mom_volatility, volume_ratio

    def single_bar_signals(self, mom_line, mom_sma, mom_slope, mom_volatility):
        """向量化检测基于单根/连续两根K线的MOM信号"""
        signals = {}
        mom_line_prev = mom_line.shift(1)
        mom_sma_prev = mom_sma.shift(1)
        
        # 辅助变量
        above_zero = mom_line > 0
        below_zero = mom_line < 0
        mom_slope_prev = mom_slope.shift(1)
        
        # 1. MOM金叉/死叉 (MOM线 vs MOM SMA)
        golden_cross = ((mom_line_prev <= mom_sma_prev) & (mom_line > mom_sma)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((mom_line_prev >= mom_sma_prev) & (mom_line < mom_sma)).astype(float) * self.signal_strength["death_cross"]
        
        # 2. 正值/负值突破 (实际上就是零轴突破，原代码有冗余，此处修正为零轴突破和零轴回踩)
        # MOM零轴突破 (与 Bull Bear Transition 逻辑一致)
        signals["zero_line_breakthrough"] = ((mom_line_prev <= 0) & above_zero).astype(float) * self.signal_strength["zero_line_breakthrough"]
        signals["positive_breakthrough"] = signals["zero_line_breakthrough"].copy() * self.signal_strength["positive_breakthrough"]
        signals["bull_bear_transition"] = signals["zero_line_breakthrough"].copy() * self.signal_strength["bull_bear_transition"]

        # MOM零轴回踩
        signals["zero_line_pullback"] = ((mom_line_prev > 0) & (mom_line <= 0)).astype(float) * self.signal_strength["zero_line_pullback"]
        signals["negative_breakthrough"] = signals["zero_line_pullback"].copy() * self.signal_strength["negative_breakthrough"] # 下穿零轴视为负值突破

        # 3. MOM趋势加速/减速
        # 加速: 斜率增加且为正
        is_accel = (mom_slope > mom_slope_prev) & (mom_line > 0)
        # 减速: 斜率减小且为负 (原代码的减速逻辑)
        is_decel = (mom_slope < mom_slope_prev) & (mom_line < 0)
        signals["trend_acceleration"] = is_accel.astype(float) * self.signal_strength["trend_acceleration"]
        signals["trend_deceleration"] = is_decel.astype(float) * self.signal_strength["trend_deceleration"]

        # 4. MOM超买/超卖信号 (动态阈值：+/- 2倍波动率)
        vol_2x = mom_volatility * 2
        vol_2x_neg = vol_2x * -1
        
        is_overbought = (mom_line > vol_2x)
        is_oversold = (mom_line < vol_2x_neg)
        signals["overbought_signal"] = is_overbought.astype(float) * self.signal_strength["overbought_signal"]
        signals["oversold_signal"] = is_oversold.astype(float) * self.signal_strength["oversold_signal"]

        # 5. MOM极值反转 (极值+斜率反转)
        vol_2_5x = mom_volatility * 2.5
        is_extreme_reversal_sell = (mom_line > vol_2_5x) & (mom_slope < 0)
        is_extreme_reversal_buy = (mom_line < vol_2_5x * -1) & (mom_slope > 0)
        signals["extreme_reversal_sell"] = is_extreme_reversal_sell.astype(float) * self.signal_strength["extreme_reversal_sell"]
        signals["extreme_reversal_buy"] = is_extreme_reversal_buy.astype(float) * self.signal_strength["extreme_reversal_buy"]
        
        # 6. MOM强势/弱势区间 (动态阈值：+/- 1倍波动率)
        is_strong_zone = (mom_line > mom_volatility)
        is_weak_zone = (mom_line < mom_volatility * -1)
        signals["strong_zone"] = is_strong_zone.astype(float) * self.signal_strength["strong_zone"]
        signals["weak_zone"] = is_weak_zone.astype(float) * self.signal_strength["weak_zone"]

        # 7. 基础金叉/死叉 (整合入结果)
        signals["golden_cross"] = golden_cross
        signals["death_cross"] = death_cross
        
        return signals

    def multi_bar_signals(self, mom_line, divergence_threshold=0.02):
        """向量化检测基于3-4根K线的形态（双/三重顶底, 头肩顶底）"""
        signals = {}
        
        # N周期前的值
        mom_curr = mom_line
        mom_prev1 = mom_line.shift(1)
        mom_prev2 = mom_line.shift(2)
        mom_prev3 = mom_line.shift(3)
        
        # ****************************
        # 简单形态：双底/双顶 (需要3个点)
        # ****************************
        # 双底: V-A-V (V1, A, V2), V1/V2相似, A为峰值 < 0
        is_double_bottom = (mom_prev2 < mom_prev1) & \
                           (mom_curr < mom_prev1) & \
                           (np.abs(mom_prev2 - mom_curr) < divergence_threshold * np.abs(mom_prev1)) & \
                           (mom_prev1 < 0)
        signals["double_bottom"] = is_double_bottom.astype(float) * self.signal_strength["double_bottom"]

        # 双顶: A-V-A (A1, V, A2), A1/A2相似, V为谷值 > 0
        is_double_top = (mom_prev2 > mom_prev1) & \
                        (mom_curr > mom_prev1) & \
                        (np.abs(mom_prev2 - mom_curr) < divergence_threshold * np.abs(mom_prev1)) & \
                        (mom_prev1 > 0)
        signals["double_top"] = is_double_top.astype(float) * self.signal_strength["double_top"]

        # ****************************
        # 复杂形态：三重底/顶 (需要4个点)
        # ****************************
        # 三重底: V1-A1-V2-A2 (V1, A1, V2, A2), V1, V2, V3 (V3=curr) 相似, A1/A2为峰值 < 0
        is_triple_bottom = (mom_prev3 < mom_prev2) & (mom_prev1 < mom_prev2) & (mom_curr < mom_prev2) & \
                           (np.abs(mom_prev3 - mom_prev1) < divergence_threshold * np.abs(mom_prev2)) & \
                           (np.abs(mom_prev1 - mom_curr) < divergence_threshold * np.abs(mom_prev2)) & \
                           (mom_prev2 < 0)
        signals["triple_bottom"] = is_triple_bottom.astype(float) * self.signal_strength["triple_bottom"]

        # 三重顶
        is_triple_top = (mom_prev3 > mom_prev2) & (mom_prev1 > mom_prev2) & (mom_curr > mom_prev2) & \
                        (np.abs(mom_prev3 - mom_prev1) < divergence_threshold * np.abs(mom_prev2)) & \
                        (np.abs(mom_prev1 - mom_curr) < divergence_threshold * np.abs(mom_prev2)) & \
                        (mom_prev2 > 0)
        signals["triple_top"] = is_triple_top.astype(float) * self.signal_strength["triple_top"]

        # ****************************
        # 复杂形态：头肩底/顶 (需要4个点)
        # ****************************
        # 头肩底: S1-H-S2, S1/S2高, H低 (原代码的简化逻辑)
        is_hsb = (mom_prev3 > mom_prev1) & (mom_prev2 < mom_prev3) & \
                 (mom_prev2 < mom_curr) & (mom_curr > mom_prev1) & (mom_prev2 < 0)
        signals["head_shoulders_bottom"] = is_hsb.astype(float) * self.signal_strength["head_shoulders_bottom"]

        # 头肩顶: S1-H-S2, S1/S2低, H高
        is_hst = (mom_prev3 < mom_prev1) & (mom_prev2 > mom_prev3) & \
                 (mom_prev2 > mom_curr) & (mom_curr < mom_prev1) & (mom_prev2 > 0)
        signals["head_shoulders_top"] = is_hst.astype(float) * self.signal_strength["head_shoulders_top"]

        return signals


    def divergence_signals(self, mom_line, close_prices, lookback_period=10):
        """向量化检测顶底背离形态（价格和MOM的比较）"""
        signals = {}
        
        # 使用N周期滚动最大/最小值 (N=10)
        close_high = close_prices.rolling(window=lookback_period, min_periods=5).max()
        close_low = close_prices.rolling(window=lookback_period, min_periods=5).min()
        mom_high = mom_line.rolling(window=lookback_period, min_periods=5).max()
        mom_low = mom_line.rolling(window=lookback_period, min_periods=5).min()

        # 1. MOM顶背离（价格创新高但MOM未创新高）
        is_top_divergence = (close_prices > close_high.shift(5)) & \
                            (mom_line < mom_high.shift(5)) & \
                            (mom_line > 0)
        signals["top_divergence"] = is_top_divergence.astype(float) * self.signal_strength["top_divergence"]

        # 2. MOM底背离（价格创新低但MOM未创新低）
        is_bottom_divergence = (close_prices < close_low.shift(5)) & \
                               (mom_line > mom_low.shift(5)) & \
                               (mom_line < 0)
        signals["bottom_divergence"] = is_bottom_divergence.astype(float) * self.signal_strength["bottom_divergence"]

        return signals

    def pattern_signals(self, mom_line, close_prices, window=5):
        """向量化检测楔形/三角形/通道等形态 (基于原代码的简化逻辑)"""
        signals = {}
        
        # 5日滚动数据
        mom_roll = mom_line.rolling(window=window)
        price_roll = close_prices.rolling(window=window)
        
        mom_min = mom_roll.min()
        mom_max = mom_roll.max()
        price_max = price_roll.max()
        
        mom_diff = mom_line - mom_line.shift(4)
        price_diff = close_prices - close_prices.shift(4)

        # 1. 楔形上升/下降 (MOM和价格同向移动)
        is_rising_wedge = (mom_diff > 0) & (price_diff > 0)
        is_falling_wedge = (mom_diff < 0) & (price_diff < 0)
        signals["rising_wedge"] = is_rising_wedge.astype(float) * self.signal_strength["rising_wedge"]
        signals["falling_wedge"] = is_falling_wedge.astype(float) * self.signal_strength["falling_wedge"]

        # 2. 三角形收敛/发散 (基于MOM极差的变化)
        mom_range = mom_max - mom_min
        mom_range_prev = mom_line.shift(2).rolling(window=3).max() - mom_line.shift(2).rolling(window=3).min()
        
        is_convergence = mom_range < mom_range_prev # 当前波动小于历史波动
        is_divergence = mom_range > mom_range_prev
        signals["triangle_convergence"] = is_convergence.astype(float) * self.signal_strength["triangle_convergence"]
        signals["triangle_divergence"] = is_divergence.astype(float) * self.signal_strength["triangle_divergence"]

        # 3. 通道突破/回踩 (基于MOM的极值突破)
        is_channel_breakthrough = (mom_line > mom_max.shift(1) * 1.1) | (mom_line < mom_min.shift(1) * 1.1)
        is_channel_pullback = (mom_line <= mom_max.shift(1) * 0.9) & (mom_line >= mom_min.shift(1) * 0.9)
        signals["channel_breakthrough"] = is_channel_breakthrough.astype(float) * self.signal_strength["channel_breakthrough"]
        signals["channel_pullback"] = is_channel_pullback.astype(float) * self.signal_strength["channel_pullback"]

        # 4. 突破/回调确认
        is_breakthrough_confirmation = (mom_line > mom_max.shift(1)) & (close_prices > price_max.shift(1))
        is_pullback_confirmation = (mom_line < mom_max.shift(1) * 0.9) & (close_prices < price_max.shift(1) * 0.98)
        signals["breakthrough_confirmation"] = is_breakthrough_confirmation.astype(float) * self.signal_strength["breakthrough_confirmation"]
        signals["pullback_confirmation"] = is_pullback_confirmation.astype(float) * self.signal_strength["pullback_confirmation"]

        # 复杂形态（头肩顶/底、楔形、三角形、通道等）在原代码中缺乏明确的向量化定义，故不实现。

        return signals

    def continuous_signals(self, mom_line, mom_rate, mom_volatility, volume_ratio):
        """返回可直接用于排序/回归的连续 MOM 特征。"""
        momentum_rate_value = (mom_rate / 100.0).clip(lower=-1.0, upper=1.0).fillna(0.0)
        volatility_denominator = mom_volatility.replace(0.0, np.nan)
        momentum_strength = (mom_line / volatility_denominator).clip(lower=-1.0, upper=1.0).fillna(0.0)
        volume_ratio_value = (volume_ratio - 1.0).clip(lower=-1.0, upper=1.0).fillna(0.0)
        return {
            "momentum_rate": momentum_rate_value,
            "momentum_strength": momentum_strength,
            "volume_ratio": volume_ratio_value,
        }
    
    def volume_surge_signal(self, volume_ratio, volume_surge_threshold=1.5):
        """向量化检测放量信号"""
        is_volume_surge = (volume_ratio > volume_surge_threshold).astype(float) * self.signal_strength["volume_surge"]
        return {"volume_surge": is_volume_surge}


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume,
                                mom_period=10, divergence_threshold=0.02, volume_surge_threshold=1.5, enabled_signals=None):
        """
        整合启用的信号，生成最终的MOM信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            ... (MOM参数)
            enabled_signals: list，指定启用的信号名称

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（>0买入，<0卖出）
        """
        
        if enabled_signals is None:
            enabled_signals = list(self.signal_strength.keys())
        
        # 1. 计算MOM核心组件（只使用Close_data, Volume）
        mom_line, mom_sma, mom_slope, mom_momentum, mom_volatility, volume_ratio = self.get_mom_components(
            Close_data, Volume, mom_period
        )

        # 2. 获取所有信号矩阵
        single_bar = self.single_bar_signals(mom_line, mom_sma, mom_slope, mom_volatility)
        multi_bar = self.multi_bar_signals(mom_line, divergence_threshold)
        divergence = self.divergence_signals(mom_line, Close_data)
        patterns = self.pattern_signals(mom_line, Close_data)
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
        
        # 清除前 mom_period 个周期的信号（MOM线本身未计算）
        sum_buy[:mom_period] = 0.0
        sum_sell[:mom_period] = 0.0

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
                                       mom_period=10, divergence_threshold=0.02, volume_surge_threshold=1.5):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息
        """
        
        # 1. 计算MOM核心组件（只使用Close_data, Volume）
        mom_line, mom_sma, mom_slope, mom_momentum, mom_volatility, volume_ratio = self.get_mom_components(
            Close_data, Volume, mom_period
        )
        
        # 2. 获取所有信号矩阵
        single_bar = self.single_bar_signals(mom_line, mom_sma, mom_slope, mom_volatility)
        multi_bar = self.multi_bar_signals(mom_line, divergence_threshold)
        divergence = self.divergence_signals(mom_line, Close_data)
        patterns = self.pattern_signals(mom_line, Close_data)
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
                                      mom_period=10, divergence_threshold=0.02, volume_surge_threshold=1.5, 
                                      enabled_signals=None):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，OHLC数据
            mom_period: int，MOM计算周期，默认10
            divergence_threshold: float，背离判断阈值，默认0.02
            volume_surge_threshold: float，放量阈值，默认1.5
            enabled_signals: list，指定启用的信号名称，默认None表示使用所有信号
        
        返回:
            signals_multi_index: pd.DataFrame
                - Index: MultiIndex (Date, Contract)
                - Columns: 各个信号名称
                - Values: float32格式
        """
        
        # 1. 计算MOM核心组件
        mom_line, mom_sma, mom_slope, mom_momentum, mom_volatility, volume_ratio = self.get_mom_components(
            Close_data, Volume, mom_period
        )
        
        # 2. 获取各类信号
        single_bar = self.single_bar_signals(mom_line, mom_sma, mom_slope, mom_volatility)
        multi_bar = self.multi_bar_signals(mom_line, divergence_threshold)
        divergence = self.divergence_signals(mom_line, Close_data)
        patterns = self.pattern_signals(mom_line, Close_data)
        vol_surge = self.volume_surge_signal(volume_ratio, volume_surge_threshold)
        
        # 3. 合并所有信号字典
        all_signals_dict = {**single_bar, **multi_bar, **divergence, **patterns, **vol_surge}
        
        # 4. 过滤信号
        if enabled_signals is not None:
            all_signals_dict = {k: v for k, v in all_signals_dict.items() if k in enabled_signals}
        
        # 5. 转换为Multi-index Series
        signal_series_list = []
        signal_names = []
        
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_matrix is not None:
                signal_matrix = signal_matrix.reindex_like(Close_data).fillna(0.0)
                stacked_series = signal_matrix.stack()
                signal_series_list.append(stacked_series)
                signal_names.append(signal_name)
        
        # 6. 合并为DataFrame
        if signal_series_list:
            signals_multi_index = pd.concat(signal_series_list, axis=1, keys=signal_names)
            signals_multi_index = signals_multi_index.fillna(0)
            
            # 7. 屏蔽初始无效行
            if len(Close_data) > mom_period:
                valid_start_date = Close_data.index[mom_period]
                signals_multi_index = signals_multi_index[
                    signals_multi_index.index.get_level_values(0) >= valid_start_date
                ]
            
            # 8. 转换数据类型
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
    

    def get_factor_matrices(self, Close_data, Volume, mom_period=10, divergence_threshold=0.02, volume_surge_threshold=1.5):
        """
        拆分MOM的所有动量信号矩阵（每个信号一个矩阵）。
        返回 {signal_name: DataFrame(Date x Contract)}
        """
        mom_line, mom_sma, mom_slope, mom_momentum, mom_volatility, volume_ratio = self.get_mom_components(
            Close_data, Volume, mom_period
        )

        single_bar = self.single_bar_signals(mom_line, mom_sma, mom_slope, mom_volatility)
        multi_bar = self.multi_bar_signals(mom_line, divergence_threshold)
        divergence = self.divergence_signals(mom_line, Close_data)
        patterns = self.pattern_signals(mom_line, Close_data)
        vol_surge = self.volume_surge_signal(volume_ratio, volume_surge_threshold)
        mom_rate = (mom_line / Close_data.shift(mom_period).replace(0.0, np.nan)) * 100.0
        continuous = self.continuous_signals(mom_line, mom_rate, mom_volatility, volume_ratio)

        all_factors = {**single_bar, **multi_bar, **divergence, **patterns, **vol_surge, **continuous}

        for name, df in all_factors.items():
            if df is not None:
                df = df.reindex_like(Close_data).fillna(0.0)
                df.iloc[:mom_period * 2] = 0.0
                all_factors[name] = df
            else:
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        return all_factors
