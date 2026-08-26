import pandas as pd
import numpy as np
from itertools import chain



'''from strategys.技术面.CCI import CCI
# 实例化APO类
trans = CCI()

# 1. 获取汇总的买卖信号强度矩阵
# 使用默认参数 fast_period=12, slow_period=26
signal_apo_buy, signal_apo_sell = trans.get_total_signal_matrix(High_data,
    Low_data, 
    Close_data
)

# 2. 获取详细的信号DataFrame（包含信号名称、方向和强度）
signals_apo_detailed = trans.get_detailed_signals_dataframe(High_data,
    Low_data, 
    Close_data

)
'''

# 这里是对CCI指标的解释和公式的撰写，方便阅读
'''CCI的参数，对应优缺点

CCI：Commodity Channel Index (商品通道指标)
定义：CCI是一种衡量价格偏离其统计平均水平的超买超卖指标。它类似于布林带，但其计算基于平均绝对偏差而非标准差，使其对价格的极端变动更为敏感。

计算公式：
周期： N (默认为20)

1. 典型价格 (Typical Price, TP): 
   $TP = (High + Low + Close) / 3$

2. TP的简单移动平均 (SMA\_TP):
   $SMA\_TP = SMA(TP, N)$

3. 平均绝对偏差 (Mean Deviation, MD): N周期内，TP与SMA\_TP的绝对差值的平均值。
   $MD = \frac{1}{N} \sum_{i=1}^{N} |TP_i - SMA\_TP|$

4. CCI 线 (CCI Line):
   $CCI = \frac{TP - SMA\_TP}{0.015 \times MD}$ 
   (注：0.015是常数，用于将80%的CCI值限制在-100到+100之间)

优点：
1. **超前性**：由于其计算方式，CCI对价格变动非常敏感，常被认为比其他滞后指标更具超前性。
2. **超买超卖**：±100是判断超买超卖的常用界线，±200以上则为极端超买超卖。
3. **趋势启动**：CCI从-100下方突破-100被认为是趋势启动的信号。

缺点：
1. **波动性高**：对价格变化反应过于灵敏，在震荡市中信号噪音较大，容易产生“假突破”。
2. **依赖参数**：N周期的选择对指标的平滑度和信号准确性有较大影响。
3. **金叉/死叉意义不同**：CCI的金叉/死叉通常指穿越零轴，而非像MACD那样两条线交叉。
'''


class CCI:
    def __init__(self):
        # 定义信号强度 (根据信号的可靠性设定初始权重)
        self.signal_strength = {
            # 核心趋势和零轴信号
            "zero_line_breakthrough": 0.5,                      # CCI上穿零轴（趋势转多）
            "zero_line_pullback": -0.5,                         # CCI下穿零轴（趋势转空）
            "overbought_breakthrough": 0.7,                     # CCI上破+100（强势趋势启动）
            "oversold_breakthrough": -0.7,                      # CCI下破-100（弱势趋势启动）
            # 反转/极值信号
            "top_divergence": -0.8,                             # 顶背离 (强看跌反转)
            "bottom_divergence": 0.8,                           # 底背离 (强看涨反转)
            "extreme_reversal_top": -0.6,                       # 极值反转 (超买区反转)
            "extreme_reversal_bottom": 0.6,                     # 极值反转 (超卖区反转)
            "trend_acceleration_bull": 0.4,                     # 趋势加速（看涨）
            "trend_acceleration_bear": -0.4,                    # 趋势加速（看跌）
            "overbought_signal": -0.3,                          # 超买警告
            "oversold_signal": 0.3,                             # 超卖机会
            "strong_zone": 0.4,                                 # 强势区间 (+100以上)
            "weak_zone": -0.4,                                  # 弱势区间 (-100以下)
            # 形态信号 (仅保留名称，实际计算需要更复杂的逻辑，未在函数中实现)
            "double_bottom": 0.7,
            "double_top": -0.7,
            "triple_bottom": 0.8,
            "triple_top": -0.8,
            "head_shoulders_bottom": 0.9,
            "head_shoulders_top": -0.9,
            "rising_wedge": -0.6,
            "falling_wedge": 0.6,
            "triangle_convergence": 0.3,
            "triangle_divergence": 0.2,
            "channel_breakthrough": 0.5,
            "channel_pullback": 0.3,
            "breakthrough_confirmation": 0.5,
            "pullback_confirmation": 0.4,
            "bull_bear_transition": 0.5,
        }

        # 连续特征保留 CCI 幅度、变化速度和历史区间位置。
        self.continuous_signal_names = ["normalized_value", "slope_rate", "range_position"]
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names
        
        # 复杂形态信号列表（未在主要函数中实现，仅用于内部管理）
        self.complex_patterns = [
            'golden_cross', 'death_cross', # CCI的金叉死叉通常就是零轴穿越，为了避免重复定义，仅保留零轴穿越
            'double_bottom', 'double_top', 'triple_bottom', 'triple_top', 
            'head_shoulders_bottom', 'head_shoulders_top', 'rising_wedge', 'falling_wedge', 
            'triangle_convergence', 'triangle_divergence', 'channel_breakthrough', 
            'channel_pullback', 'breakthrough_confirmation', 'pullback_confirmation',
        ]

    def get_cci_components(self, high_prices_matrix, low_prices_matrix, close_prices_matrix, cci_period=20, cci_constant=0.015):
        """计算CCI核心组件 (典型价格, SMA_TP, CCI线)"""
        
        # 1. 典型价格 (TP)
        typical_price = (high_prices_matrix + low_prices_matrix + close_prices_matrix) / 3
        
        # 2. SMA_TP
        sma_tp = typical_price.rolling(window=cci_period).mean()
        
        # 3. 平均绝对偏差 (MD) - 需要滚动计算
        # 使用 rolling().apply() 配合 lambda 函数实现向量化
        tp_minus_sma = typical_price - sma_tp
        mean_deviation = tp_minus_sma.abs().rolling(window=cci_period).mean()

        # 4. CCI 线
        # 避免除以零
        divisor = cci_constant * mean_deviation.replace(0, np.nan) 
        cci_line = (typical_price - sma_tp) / divisor
        
        # 填充初始NaN值 (由于rolling计算)
        cci_line = cci_line.ffill().fillna(0)
        
        return cci_line

    def zero_cross_signals(self, cci_line):
        """CCI零轴穿越信号（金叉/死叉）"""
        
        prev_cci = cci_line.shift(1)
        
        # 1. 零轴突破（上穿）
        zero_break_up = ((prev_cci <= 0) & (cci_line > 0)).astype(float) * self.signal_strength["zero_line_breakthrough"]
        
        # 2. 零轴回踩（下穿）
        zero_break_down = ((prev_cci >= 0) & (cci_line < 0)).astype(float) * self.signal_strength["zero_line_pullback"]
        
        # CCI多空转换 (与零轴突破相似，此处简化为零轴突破)
        bull_bear_transition = zero_break_up * self.signal_strength["bull_bear_transition"] - zero_break_down * self.signal_strength["bull_bear_transition"]
        bull_bear_transition = bull_bear_transition.abs()
        
        return {
            "zero_line_breakthrough": zero_break_up.fillna(0),
            "zero_line_pullback": zero_break_down.fillna(0),
            "bull_bear_transition": bull_bear_transition.fillna(0)
        }
    
    def extreme_signals(self, cci_line):
        """超买超卖和区间信号"""
        
        prev_cci = cci_line.shift(1)
        
        # 1. 超买突破 (上破+100)
        overbought_breakthrough = ((prev_cci <= 100) & (cci_line > 100)).astype(float) * self.signal_strength["overbought_breakthrough"]
        
        # 2. 超卖突破 (下破-100)
        oversold_breakthrough = ((prev_cci >= -100) & (cci_line < -100)).astype(float) * self.signal_strength["oversold_breakthrough"]
        
        # 3. 超买信号 (+100以上)
        overbought_signal = (cci_line > 100).astype(float) * self.signal_strength["overbought_signal"]

        # 4. 超卖信号 (-100以下)
        oversold_signal = (cci_line < -100).astype(float) * self.signal_strength["oversold_signal"]

        # 5. 强势区间 (+100以上)
        strong_zone = (cci_line > 100).astype(float) * self.signal_strength["strong_zone"]

        # 6. 弱势区间 (-100以下)
        weak_zone = (cci_line < -100).astype(float) * self.signal_strength["weak_zone"]

        return {
            "overbought_breakthrough": overbought_breakthrough.fillna(0),
            "oversold_breakthrough": oversold_breakthrough.fillna(0),
            "overbought_signal": overbought_signal.fillna(0),
            "oversold_signal": oversold_signal.fillna(0),
            "strong_zone": strong_zone.fillna(0),
            "weak_zone": weak_zone.fillna(0)
        }

    def momentum_reversal_signals(self, cci_line, lookback_period=10):
        """趋势加速/减速和极值反转信号"""
        
        cci_slope = cci_line.diff()
        cci_slope_prev = cci_slope.shift(1)
        cci_prev = cci_line.shift(1)
        
        # 1. 趋势加速（CCI斜率增加，且在趋势方向上）
        is_acceleration = (cci_slope.abs() > cci_slope_prev.abs())
        trend_acceleration_bull = (is_acceleration & (cci_line > 0)).astype(float) * self.signal_strength["trend_acceleration_bull"]
        trend_acceleration_bear = (is_acceleration & (cci_line < 0)).astype(float) * self.signal_strength["trend_acceleration_bear"]

        # 2. 极值反转（从极端值区域开始反向移动）
        # 顶极值反转：CCI > 200 且开始下降
        extreme_reversal_top = ((cci_prev > 200) & (cci_line < cci_prev)).astype(float) * self.signal_strength["extreme_reversal_top"]
        # 底极值反转：CCI < -200 且开始上升
        extreme_reversal_bottom = ((cci_prev < -200) & (cci_line > cci_prev)).astype(float) * self.signal_strength["extreme_reversal_bottom"]

        return {
            "trend_acceleration_bull": trend_acceleration_bull.fillna(0),
            "trend_acceleration_bear": trend_acceleration_bear.fillna(0),
            "extreme_reversal_top": extreme_reversal_top.fillna(0),
            "extreme_reversal_bottom": extreme_reversal_bottom.fillna(0)
        }


    def divergence_signals(self, cci_line, close_prices_matrix, lookback_period=10, divergence_threshold=0.02):
        """CCI顶底背离信号 (价格与CCI线)"""
        
        # 最近 lookback_period 内的最高价/最低价和CCI的最大值/最小值
        price_high = close_prices_matrix.rolling(lookback_period).max()
        price_low = close_prices_matrix.rolling(lookback_period).min()
        cci_max = cci_line.rolling(lookback_period).max()
        cci_min = cci_line.rolling(lookback_period).min()

        current_price = close_prices_matrix
        current_cci = cci_line
        
        # 1. 顶背离 (Top Divergence): 价格创新高，CCI未创新高 (且在正值区)
        price_peak = (current_price > price_high.shift(1))
        cci_not_peak = (current_cci < cci_max.shift(1) * (1 - divergence_threshold))
        is_top_divergence = (price_peak & cci_not_peak & (current_cci > 0)).astype(float) * self.signal_strength["top_divergence"]
        
        # 2. 底背离 (Bottom Divergence): 价格创新低，CCI未创新低 (且在负值区)
        price_trough = (current_price < price_low.shift(1))
        cci_not_trough = (current_cci > cci_min.shift(1) * (1 + divergence_threshold))
        is_bottom_divergence = (price_trough & cci_not_trough & (current_cci < 0)).astype(float) * self.signal_strength["bottom_divergence"]
        
        return {
            "top_divergence": is_top_divergence.fillna(0),
            "bottom_divergence": is_bottom_divergence.fillna(0)
        }

    def continuous_signals(self, cci_line, lookback_period=20):
        """返回可直接用于排序/回归的连续 CCI 特征。"""
        normalized_value = (cci_line / 200.0).clip(lower=-1.0, upper=1.0).fillna(0.0)
        slope_rate = (cci_line.diff() / 100.0).clip(lower=-1.0, upper=1.0).fillna(0.0)
        rolling_min = cci_line.rolling(lookback_period, min_periods=lookback_period).min()
        rolling_max = cci_line.rolling(lookback_period, min_periods=lookback_period).max()
        span = (rolling_max - rolling_min).replace(0.0, np.nan)
        range_position = (2.0 * (cci_line - rolling_min) / span - 1.0).clip(
            lower=-1.0, upper=1.0
        ).fillna(0.0)
        return {
            "normalized_value": normalized_value,
            "slope_rate": slope_rate,
            "range_position": range_position,
        }

    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, enabled_signals=None, cci_period=20):
        """
        整合启用的信号，生成最终的CCI信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            enabled_signals: list，指定启用的信号名称
            cci_period: int, CCI计算周期

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
        
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 只使用High_data, Low_data, Close_data
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 1. 计算CCI核心组件
        cci_line = self.get_cci_components(High_data, Low_data, Close_data, cci_period)

        # 2. 获取所有信号矩阵
        zero_cross = self.zero_cross_signals(cci_line)
        extreme = self.extreme_signals(cci_line)
        momentum_rev = self.momentum_reversal_signals(cci_line)
        divergence = self.divergence_signals(cci_line, Close_data)
        continuous = self.continuous_signals(cci_line, cci_period)

        # 合并所有信号字典
        all_signals_dict = {**zero_cross, **extreme, **momentum_rev, **divergence, **continuous}

        # 3. 累加启用的信号强度
        for signal_name, signal_matrix in all_signals_dict.items():
            # 排除复杂形态，只累加核心信号
            if signal_name in enabled_signals and signal_name not in self.complex_patterns and signal_matrix is not None:
                
                buy_mask = signal_matrix > 0
                sum_buy = sum_buy + signal_matrix.where(buy_mask, 0)
                
                sell_mask = signal_matrix < 0
                sum_sell = sum_sell + signal_matrix.where(sell_mask, 0)

        # 4. 处理初始NaN值
        sum_buy = sum_buy.fillna(0)
        sum_sell = sum_sell.fillna(0)
        
        # 屏蔽初始无效行
        min_valid_rows = cci_period
        if len(sum_buy) > min_valid_rows:
            sum_buy.iloc[:min_valid_rows] = 0.0
            sum_sell.iloc[:min_valid_rows] = 0.0
            
        '''这里得到的分别是买和卖的矩阵，index是日期，column是标的，value是对应的强度值'''
        return sum_buy, sum_sell

    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name, date_index, stock_columns):
        """将单个信号矩阵转换为记录列表"""
        
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
        
        records = result_df.to_dict('records')
        
        return records

    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, cci_period=20):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 1. 计算CCI核心组件（只使用High_data, Low_data, Close_data）
        cci_line = self.get_cci_components(High_data, Low_data, Close_data, cci_period)
        
        # 获取日期索引和股票列名
        date_index = Close_data.index
        stock_columns = Close_data.columns
        
        # 2. 信号处理器列表
        signal_processors = [
            self.zero_cross_signals(cci_line),
            self.extreme_signals(cci_line),
            self.momentum_reversal_signals(cci_line),
            self.divergence_signals(cci_line, Close_data),
            self.continuous_signals(cci_line, cci_period),
        ]
        
        # 3. 统一处理所有信号记录
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name, date_index, stock_columns)
            for processor in signal_processors
            for signal_name, signal_matrix in processor.items()
            if signal_name not in self.complex_patterns # 过滤掉未实现的复杂形态
        ))
        
        # 4. 创建并返回排序后的DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
            
            # 同样屏蔽初始无效行
            min_valid_rows = cci_period
            if len(Close_data) > min_valid_rows:
                 # 过滤掉日期早于有效期的信号
                signals_df = signals_df[signals_df['Date'] >= Close_data.index[min_valid_rows]]
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      cci_period=20, enabled_signals=None, exclude_complex_patterns=True):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，OHLC数据
            cci_period: int，CCI计算周期，默认20
            enabled_signals: list，指定启用的信号名称，默认None表示使用所有信号
            exclude_complex_patterns: bool，是否排除复杂形态信号（未实现的），默认True
        
        返回:
            signals_multi_index: pd.DataFrame
                - Index: MultiIndex (Date, Contract)
                    - Date: int32格式（如 20240101）
                    - Contract: string格式
                - Columns: 各个信号名称
                - Values: float32格式，对应信号的强度值（保留正负和0）
        """
        
        # 1. 计算CCI核心组件
        cci_line = self.get_cci_components(High_data, Low_data, Close_data, cci_period)
        
        # 2. 获取各类信号
        zero_cross = self.zero_cross_signals(cci_line)
        extreme = self.extreme_signals(cci_line)
        momentum_rev = self.momentum_reversal_signals(cci_line)
        divergence = self.divergence_signals(cci_line, Close_data)
        continuous = self.continuous_signals(cci_line, cci_period)
        
        # 3. 合并所有信号字典
        all_signals_dict = {**zero_cross, **extreme, **momentum_rev, **divergence, **continuous}
        
        # 4. 过滤信号
        if exclude_complex_patterns:
            # 排除未实现的复杂形态信号
            all_signals_dict = {
                k: v for k, v in all_signals_dict.items() 
                if k not in self.complex_patterns
            }
        
        if enabled_signals is not None:
            # 只保留启用的信号
            all_signals_dict = {
                k: v for k, v in all_signals_dict.items() 
                if k in enabled_signals
            }
        
        # 5. 将每个信号矩阵(Date × Contract)转换为Multi-index Series
        signal_series_list = []
        signal_names = []
        
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_matrix is not None:
                stacked_series = signal_matrix.stack()
                signal_series_list.append(stacked_series)
                signal_names.append(signal_name)
        
        # 6. 合并所有Series为DataFrame
        if signal_series_list:
            signals_multi_index = pd.concat(
                signal_series_list, 
                axis=1, 
                keys=signal_names
            )
            
            signals_multi_index = signals_multi_index.fillna(0)
            
            # 7. 屏蔽初始无效行
            min_valid_rows = cci_period
            if len(Close_data) > min_valid_rows:
                valid_start_date = Close_data.index[min_valid_rows]
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
            
            new_index = pd.MultiIndex.from_arrays(
                [date_int32, contract_str],
                names=['Date', 'Contract']
            )
            signals_multi_index.index = new_index
            signals_multi_index = signals_multi_index.astype('float32')
            
        else:
            signals_multi_index = pd.DataFrame(
                columns=signal_names if signal_names else [],
                index=pd.MultiIndex.from_tuples([], names=['Date', 'Contract'])
            )
            
        return signals_multi_index
    
    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, cci_period=20):
        """
        拆分CCI的所有原子信号矩阵。
        """
        cci_line = self.get_cci_components(High_data, Low_data, Close_data, cci_period)
        
        zero = self.zero_cross_signals(cci_line)
        extreme = self.extreme_signals(cci_line)
        mom = self.momentum_reversal_signals(cci_line)
        div = self.divergence_signals(cci_line, Close_data)
        continuous = self.continuous_signals(cci_line, cci_period)

        all_factors = {**zero, **extreme, **mom, **div, **continuous}
        
        for name in all_factors:
            all_factors[name].iloc[:cci_period * 2] = 0.0
                
        return all_factors
    

    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, cci_period=20):
        """
        拆分CCI的所有原子信号矩阵，取消合并逻辑。
        """
        cci_line = self.get_cci_components(High_data, Low_data, Close_data, cci_period)
        
        zero = self.zero_cross_signals(cci_line)
        extreme = self.extreme_signals(cci_line)
        mom = self.momentum_reversal_signals(cci_line)
        div = self.divergence_signals(cci_line, Close_data)
        continuous = self.continuous_signals(cci_line, cci_period)

        # 字典解包合并，确保每个Key（如 zero_line_breakthrough）都是独立矩阵
        all_factors = {**zero, **extreme, **mom, **div, **continuous}
        
        for name in all_factors:
            all_factors[name].iloc[:cci_period * 2] = 0.0
                
        return all_factors
