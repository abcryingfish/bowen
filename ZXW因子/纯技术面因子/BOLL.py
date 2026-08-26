import pandas as pd
import numpy as np
from itertools import chain



'''from strategys.技术面.BOLL import BOLL
# 实例化APO类
trans = BOLL()

# 1. 获取汇总的买卖信号强度矩阵
# 使用默认参数 fast_period=12, slow_period=26
signal_apo_buy, signal_apo_sell = trans.get_total_signal_matrix(Close_data,
    High_data, 
    Low_data, 
    Volume
)

# 2. 获取详细的信号DataFrame（包含信号名称、方向和强度）
signals_apo_detailed = trans.get_detailed_signals_dataframe(Close_data,
    High_data, 
    Low_data

)'''

# 这里是对BOLL指标的解释和公式的撰写，方便阅读
'''BOLL的参数，对应优缺点

BOLL：Bollinger Bands (布林带)
定义：布林带是一种根据统计学原理（正态分布）构建的通道指标，用于衡量价格波动范围和超买超卖状态。它由三条线组成：中轨（Middle Band）、上轨（Upper Band）和下轨（Lower Band）。

计算公式：
周期： N (默认为20)
标准差倍数： K (默认为2)

1. 中轨（Middle Band, MB）：N周期简单移动平均线（SMA）。
   $MB = SMA(Price, N)$

2. 上轨（Upper Band, UP）：中轨加上 K 倍 N周期标准差。
   $UP = MB + K \times StdDev(Price, N)$

3. 下轨（Lower Band, DN）：中轨减去 K 倍 N周期标准差。
   $DN = MB - K \times StdDev(Price, N)$

4. 布林带宽（BandWidth）：衡量布林带的收窄或扩张，即波动率。
   $BandWidth = UP - DN$

优点：
1. **波动率自适应**：通道会随着市场波动率的增减而自动扩张或收缩，避免使用固定的超买超卖阈值。
2. **趋势和震荡适用**：在趋势行情中，价格沿上轨或下轨运行；在震荡行情中，价格在中轨附近震荡。
3. **超买超卖**：价格突破上下轨通常被视为极端的超买或超卖信号。

缺点：
1. **滞后性**：基于移动平均线和标准差计算，对价格的快速变化会有一定的滞后反应。
2. **突破陷阱**：价格突破上下轨后，可能继续沿着通道外运行（趋势延续），而非立即反转。
3. **参数敏感**：N和K的取值对指标的敏感度和信号的可靠性有显著影响。
'''


class BOLL:
    def __init__(self):
        # 定义信号强度 (根据信号的可靠性设定初始权重)
        self.signal_strength = {
            # 核心趋势和通道信号
            "golden_cross": 0.5,                                # 价格上穿中轨
            "death_cross": -0.5,                                # 价格下穿中轨
            "upper_breakthrough": 1.0,                          # 价格接近/突破上轨的连续强度
            "lower_breakthrough": -1.0,                         # 价格接近/跌破下轨的连续强度
            "upper_pullback": -0.6,                             # 价格回踩上轨（趋势终结，看跌反转）
            "lower_pullback": 0.6,                              # 价格回踩下轨（趋势终结，看涨反转）
            "middle_support": 0.4,                              # 中轨支撑有效（趋势确认）
            "middle_resistance": -0.4,                          # 中轨阻力有效（趋势确认）
            # 波动率/反转信号
            "squeeze": 0.8,                                     # 布林带收窄（突破前信号，强）
            "expansion": 0.7,                                   # 布林带扩张（趋势加速信号）
            "extreme_reversal_top": -0.7,                       # 极值反转（上轨附近反转）
            "extreme_reversal_bottom": 0.7,                     # 极值反转（下轨附近反转）
            "top_divergence": -0.8,                             # 顶背离 (强看跌反转)
            "bottom_divergence": 0.8,                           # 底背离 (强看涨反转)
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
            "trend_acceleration": 0.5,
            "trend_deceleration": -0.5,
            "bull_bear_transition": 0.6,
            "stagnation": -0.3,                                 # 钝化形态
        }

        # 所有信号名称列表；连续特征保留布林带位置、宽度和中轨偏离。
        self.continuous_signal_names = [
            "band_position",
            "band_width_ratio",
            "middle_bias",
        ]
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names
        
        # 复杂形态信号列表（未在主要函数中实现，仅用于内部管理）
        self.complex_patterns = [
            'double_bottom', 'double_top', 'triple_bottom', 'triple_top', 
            'head_shoulders_bottom', 'head_shoulders_top', 'rising_wedge', 'falling_wedge', 
            'triangle_convergence', 'triangle_divergence', 'channel_breakthrough', 
            'channel_pullback', 'bull_bear_transition'
        ]


    def get_boll_components(self, price_matrix, boll_period=20, boll_std=2):
        """计算布林带核心组件 (上轨、中轨、下轨、带宽)"""
        
        # 1. 计算中轨 (Middle Band, MB): N周期简单移动平均线
        boll_middle = price_matrix.rolling(window=boll_period).mean()
        
        # 2. 计算 N周期标准差
        boll_std_value = price_matrix.rolling(window=boll_period).std()
        
        # 3. 计算上轨和下轨
        boll_upper = boll_middle + (boll_std_value * boll_std)
        boll_lower = boll_middle - (boll_std_value * boll_std)
        
        # 4. 计算布林带宽度 (BandWidth)
        boll_width = boll_upper - boll_lower
        
        # 5. 计算价格在布林带中的位置 (%B)
        boll_position = (price_matrix - boll_lower) / boll_width
        
        # 填充初始NaN值
        boll_middle = boll_middle.ffill().fillna(price_matrix)
        boll_upper = boll_upper.ffill().fillna(price_matrix)
        boll_lower = boll_lower.ffill().fillna(price_matrix)
        boll_width = boll_width.fillna(0)
        boll_position = boll_position.fillna(0.5)

        return boll_upper, boll_middle, boll_lower, boll_width, boll_position

    @staticmethod
    def _continuous_boundary_score(
        directional_gap,
        scale,
        touch_weight=0.25,
        pre_width=0.5,
        post_width=0.75,
    ):
        """将边界距离映射为单调连续分数，负侧预热、正侧突破后饱和。"""
        safe_scale = scale.abs().replace(0.0, np.nan)
        normalized_gap = directional_gap / safe_scale
        pre_score = touch_weight * np.exp(
            -0.5 * (normalized_gap / pre_width) ** 2
        )
        post_score = touch_weight + (1.0 - touch_weight) * (
            1.0 - np.exp(-normalized_gap.clip(lower=0.0) / post_width)
        )
        score = pre_score.where(normalized_gap < 0.0, post_score)
        return score.clip(lower=0.0, upper=1.0).fillna(0.0)

    def trend_cross_signals(self, price_matrix, boll_upper, boll_middle, boll_lower):
        """价格与布林带三轨的交叉和突破信号"""
        
        price_prev = price_matrix.shift(1)
        
        # 1. 金叉: 价格上穿中轨
        golden_cross = ((price_prev <= boll_middle.shift(1)) & (price_matrix > boll_middle)).astype(float) * self.signal_strength["golden_cross"]
        
        # 2. 死叉: 价格下穿中轨
        death_cross = ((price_prev >= boll_middle.shift(1)) & (price_matrix < boll_middle)).astype(float) * self.signal_strength["death_cross"]
        
        # 3-4. 上下轨突破改为连续边界强度。布林带宽度在默认参数下为 4 倍
        # 滚动标准差，因此 width / 4 可作为不依赖价格量级的波动尺度。
        boundary_scale = (boll_upper - boll_lower).abs() / 4.0
        upper_breakthrough = self._continuous_boundary_score(
            price_matrix - boll_upper,
            boundary_scale,
        )
        lower_breakthrough = -self._continuous_boundary_score(
            boll_lower - price_matrix,
            boundary_scale,
        )
        
        # 5. 上轨回踩 (Upper Band Pullback): 价格从上轨外回到上轨内
        upper_pullback = ((price_prev > boll_upper.shift(1)) & (price_matrix <= boll_upper)).astype(float) * self.signal_strength["upper_pullback"]
        
        # 6. 下轨回踩 (Lower Band Pullback): 价格从下轨外回到下轨内
        lower_pullback = ((price_prev < boll_lower.shift(1)) & (price_matrix >= boll_lower)).astype(float) * self.signal_strength["lower_pullback"]

        return {
            "golden_cross": golden_cross.fillna(0),
            "death_cross": death_cross.fillna(0),
            "upper_breakthrough": upper_breakthrough.fillna(0),
            "lower_breakthrough": lower_breakthrough.fillna(0),
            "upper_pullback": upper_pullback.fillna(0),
            "lower_pullback": lower_pullback.fillna(0)
        }
        
    def support_resistance_signals(self, price_matrix, boll_middle):
        """中轨支撑与阻力信号"""
        
        price_prev = price_matrix.shift(1)
        middle_prev = boll_middle.shift(1)
        
        # 1. 中轨支撑 (价格触及中轨并反弹向上，且中轨向上倾斜)
        middle_support = ((price_prev < boll_middle.shift(1)) & 
                          (price_matrix >= boll_middle) & 
                          (boll_middle > middle_prev)).astype(float) * self.signal_strength["middle_support"]
        
        # 2. 中轨阻力 (价格触及中轨并反弹向下，且中轨向下倾斜)
        middle_resistance = ((price_prev > boll_middle.shift(1)) & 
                             (price_matrix <= boll_middle) & 
                             (boll_middle < middle_prev)).astype(float) * self.signal_strength["middle_resistance"]
        
        return {
            "middle_support": middle_support.fillna(0),
            "middle_resistance": middle_resistance.fillna(0)
        }

    def volatility_signals(self, boll_width, boll_middle, boll_period=20, squeeze_ratio=0.8, expansion_ratio=1.2, stagnation_period=5):
        """布林带宽度和波动率相关信号"""
        
        boll_width_prev = boll_width.shift(1)
        boll_width_rolling_min = boll_width.rolling(window=boll_period).min()
        
        # 1. Squeeze (收窄): 当前宽度远低于历史平均，或低于前一个周期的低点
        # 简化版：当前宽度比前一个周期显著缩小
        is_squeeze = (boll_width < boll_width_rolling_min * (1 + 0.1)).astype(float) * self.signal_strength["squeeze"]
        
        # 2. Expansion (扩张): 当前宽度比前一个周期显著放大
        is_expansion = (boll_width > boll_width_prev * expansion_ratio).astype(float) * self.signal_strength["expansion"]

        # 3. Extreme Reversal (极值反转 - 基于宽度变化): 收窄后立即扩张 (未完全实现，用极值位置反转代替)
        
        # 4. 粘合/收敛形态 (Convergence - 波动率低): 宽度/中轨比率低
        width_to_middle_ratio = boll_width / boll_middle.abs()
        is_convergence = (width_to_middle_ratio < 0.05).astype(float) * self.signal_strength["squeeze"] # 复用 squeeze 信号强度

        # 5. 发散/扩张形态 (Divergence - 波动率高): 宽度/中轨比率高
        is_divergence = (width_to_middle_ratio > 0.15).astype(float) * self.signal_strength["expansion"] # 复用 expansion 信号强度
        
        # 6. 钝化形态 (Stagnation): 中轨斜率绝对值显著减小
        boll_slope = boll_middle.diff()
        boll_slope_prev = boll_slope.shift(1)
        is_stagnation = (boll_slope.abs() < boll_slope_prev.abs() * 0.5).astype(float) * self.signal_strength["stagnation"]

        return {
            "squeeze": is_squeeze.fillna(0),
            "expansion": is_expansion.fillna(0),
            "convergence": is_convergence.fillna(0),
            "divergence": is_divergence.fillna(0),
            "stagnation": is_stagnation.fillna(0)
        }
        
    def divergence_signals(self, price_matrix, boll_position, lookback_period=10):
        """布林带顶底背离信号 (价格与 %B)"""
        
        # 1. 顶背离 (Top Divergence): 价格创新高，%B未创新高
        price_high = price_matrix.rolling(lookback_period).max()
        boll_pos_max = boll_position.rolling(lookback_period).max()

        price_peak = (price_matrix > price_high.shift(1))
        pos_not_peak = (boll_position < boll_pos_max.shift(1))
        
        # 顶背离发生在价格在高位区域时
        is_top_divergence = (price_peak & pos_not_peak & (boll_position > 0.7)).astype(float) * self.signal_strength["top_divergence"]
        
        # 2. 底背离 (Bottom Divergence): 价格创新低，%B未创新低
        price_low = price_matrix.rolling(lookback_period).min()
        boll_pos_min = boll_position.rolling(lookback_period).min()
        
        price_trough = (price_matrix < price_low.shift(1))
        pos_not_trough = (boll_position > boll_pos_min.shift(1))
        
        # 底背离发生在价格在低位区域时
        is_bottom_divergence = (price_trough & pos_not_trough & (boll_position < 0.3)).astype(float) * self.signal_strength["bottom_divergence"]
        
        return {
            "top_divergence": is_top_divergence.fillna(0),
            "bottom_divergence": is_bottom_divergence.fillna(0)
        }
        
    def extreme_reversal_signals(self, boll_position):
        """极值反转信号 (价格在通道边缘后立即反向移动)"""
        
        pos_prev = boll_position.shift(1)
        
        # 1. 上轨极值反转 (价格达到上轨或超上轨，然后位置下降)
        is_top_reversal = ((boll_position > 0.9) & (boll_position < pos_prev)).astype(float) * self.signal_strength["extreme_reversal_top"]
        
        # 2. 下轨极值反转 (价格达到下轨或超下轨，然后位置上升)
        is_bottom_reversal = ((boll_position < 0.1) & (boll_position > pos_prev)).astype(float) * self.signal_strength["extreme_reversal_bottom"]

        return {
            "extreme_reversal_top": is_top_reversal.fillna(0),
            "extreme_reversal_bottom": is_bottom_reversal.fillna(0)
        }

    def continuous_signals(self, price_matrix, boll_middle, boll_width, boll_position):
        """返回可直接用于排序/回归的连续布林带特征。"""
        middle_abs = boll_middle.abs().replace(0.0, np.nan)
        return {
            "band_position": boll_position.clip(lower=0.0, upper=1.0).fillna(0.5),
            "band_width_ratio": (boll_width / middle_abs).clip(lower=0.0, upper=1.0).fillna(0.0),
            "middle_bias": ((price_matrix - boll_middle) / middle_abs).clip(lower=-1.0, upper=1.0).fillna(0.0),
        }


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, enabled_signals=None, boll_period=20, boll_std=2):
        """
        整合启用的信号，生成最终的BOLL信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            enabled_signals: list，指定启用的信号名称
            boll_period: int, 布林带计算周期
            boll_std: float, 布林带标准差倍数

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
        
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 只使用Close_data
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 1. 计算BOLL核心组件
        boll_upper, boll_middle, boll_lower, boll_width, boll_position = self.get_boll_components(
            Close_data, boll_period, boll_std
        )

        # 2. 获取所有信号矩阵
        trend_cross = self.trend_cross_signals(Close_data, boll_upper, boll_middle, boll_lower)
        support_res = self.support_resistance_signals(Close_data, boll_middle)
        volatility = self.volatility_signals(boll_width, boll_middle, boll_period)
        divergence = self.divergence_signals(Close_data, boll_position)
        reversal = self.extreme_reversal_signals(boll_position)
        continuous = self.continuous_signals(Close_data, boll_middle, boll_width, boll_position)
        
        # 简单形态信号 (此处未实现，仅占位)
        simple_patterns = {} # self.simple_pattern_signals(boll_position) 

        # 合并所有信号字典
        all_signals_dict = {**trend_cross, **support_res, **volatility, **divergence, **reversal, **continuous, **simple_patterns}

        # 3. 累加启用的信号强度
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_name in enabled_signals and signal_matrix is not None:
                
                buy_mask = signal_matrix > 0
                sum_buy = sum_buy + signal_matrix.where(buy_mask, 0)
                
                sell_mask = signal_matrix < 0
                sum_sell = sum_sell + signal_matrix.where(sell_mask, 0)

        # 4. 处理初始NaN值
        sum_buy = sum_buy.fillna(0)
        sum_sell = sum_sell.fillna(0)
        
        # 屏蔽初始无效行
        min_valid_rows = boll_period
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

    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, boll_period=20, boll_std=2):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 1. 计算BOLL核心组件（只使用Close_data）
        boll_upper, boll_middle, boll_lower, boll_width, boll_position = self.get_boll_components(
            Close_data, boll_period, boll_std
        )
        
        # 获取日期索引和股票列名
        date_index = Close_data.index
        stock_columns = Close_data.columns
        
        # 2. 信号处理器列表
        signal_processors = [
            self.trend_cross_signals(Close_data, boll_upper, boll_middle, boll_lower),
            self.support_resistance_signals(Close_data, boll_middle),
            self.volatility_signals(boll_width, boll_middle, boll_period),
            self.divergence_signals(Close_data, boll_position),
            self.extreme_reversal_signals(boll_position),
            self.continuous_signals(Close_data, boll_middle, boll_width, boll_position),
            # 简单形态信号 (此处未实现，不包含在处理器中)
        ]
        
        # 3. 统一处理所有信号记录
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name, date_index, stock_columns)
            for processor in signal_processors
            for signal_name, signal_matrix in processor.items()
            if signal_name not in self.complex_patterns  # 过滤掉复杂形态
        ))
        
        # 4. 创建并返回排序后的DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
            
            # 同样屏蔽初始无效行
            min_valid_rows = boll_period
            if len(Close_data) > min_valid_rows:
                 # 过滤掉日期早于有效期的信号
                signals_df = signals_df[signals_df['Date'] >= Close_data.index[min_valid_rows]]
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      boll_period=20, boll_std=2, enabled_signals=None, 
                                      exclude_complex_patterns=True):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，OHLC数据
            boll_period: int，布林带计算周期，默认20
            boll_std: float，布林带标准差倍数，默认2
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
        
        # 1. 计算BOLL核心组件
        boll_upper, boll_middle, boll_lower, boll_width, boll_position = self.get_boll_components(
            Close_data, boll_period, boll_std
        )
        
        # 2. 获取各类信号
        trend_cross = self.trend_cross_signals(Close_data, boll_upper, boll_middle, boll_lower)
        support_res = self.support_resistance_signals(Close_data, boll_middle)
        volatility = self.volatility_signals(boll_width, boll_middle, boll_period)
        divergence = self.divergence_signals(Close_data, boll_position)
        reversal = self.extreme_reversal_signals(boll_position)
        continuous = self.continuous_signals(Close_data, boll_middle, boll_width, boll_position)
        
        # 3. 合并所有信号字典
        all_signals_dict = {**trend_cross, **support_res, **volatility, **divergence, **reversal, **continuous}
        
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
                # 将矩阵stack成Multi-index Series
                stacked_series = signal_matrix.stack()
                signal_series_list.append(stacked_series)
                signal_names.append(signal_name)
        
        # 6. 合并所有Series为DataFrame
        if signal_series_list:
            # 使用concat按列合并，keys参数指定列名
            signals_multi_index = pd.concat(
                signal_series_list, 
                axis=1, 
                keys=signal_names
            )
            
            # 填充NaN为0
            signals_multi_index = signals_multi_index.fillna(0)
            
            # 7. 屏蔽初始无效行（前 boll_period 行）
            min_valid_rows = boll_period
            if len(Close_data) > min_valid_rows:
                # 获取有效的起始日期
                valid_start_date = Close_data.index[min_valid_rows]
                # 过滤掉早于有效日期的数据
                signals_multi_index = signals_multi_index[
                    signals_multi_index.index.get_level_values(0) >= valid_start_date
                ]
            
            # 8. 转换数据类型
            current_dates = signals_multi_index.index.get_level_values(0)
            
            # 检查日期类型并转换
            if pd.api.types.is_datetime64_any_dtype(current_dates):
                date_int32 = current_dates.strftime('%Y%m%d').astype('int32')
            elif pd.api.types.is_integer_dtype(current_dates):
                date_int32 = current_dates.astype('int32')
            else:
                date_int32 = pd.to_datetime(current_dates).strftime('%Y%m%d').astype('int32')
            
            # Contract索引转换为string格式
            contract_str = signals_multi_index.index.get_level_values(1).astype('string')
            
            # 重建索引
            new_index = pd.MultiIndex.from_arrays(
                [date_int32, contract_str],
                names=['Date', 'Contract']
            )
            signals_multi_index.index = new_index
            
            # Values转换为float32类型
            signals_multi_index = signals_multi_index.astype('float32')
            
        else:
            # 如果没有信号，创建空DataFrame
            signals_multi_index = pd.DataFrame(
                columns=signal_names if signal_names else [],
                index=pd.MultiIndex.from_tuples([], names=['Date', 'Contract'])
            )
            
        return signals_multi_index
    
    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, boll_period=20, boll_std=2):
        """
        将BOLL的所有子信号拆分为独立的因子矩阵。
        """
        # 1. 计算核心组件
        upper, middle, lower, width, pos = self.get_boll_components(Close_data, boll_period, boll_std)
        
        # 2. 获取各类原子信号字典
        trend = self.trend_cross_signals(Close_data, upper, middle, lower)
        supp_res = self.support_resistance_signals(Close_data, middle)
        vol = self.volatility_signals(width, middle, boll_period)
        div = self.divergence_signals(Close_data, pos)
        rev = self.extreme_reversal_signals(pos)
        continuous = self.continuous_signals(Close_data, middle, width, pos)

        # 3. 合并所有信号并处理初期不稳定数据
        all_factors = {**trend, **supp_res, **vol, **div, **rev, **continuous}
        
        for name in all_factors:
            all_factors[name].iloc[:boll_period * 2] = 0.0
                
        return all_factors
