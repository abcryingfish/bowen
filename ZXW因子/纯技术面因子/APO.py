import pandas as pd
import numpy as np
from itertools import chain


'''from strategys.技术面.APO import APO
# 实例化APO类
APO_Calculator = APO()

# 1. 获取汇总的买卖信号强度矩阵
# 使用默认参数 fast_period=12, slow_period=26
signal_apo_buy, signal_apo_sell = APO_Calculator.get_total_signal_matrix(
    close_prices_matrix=Close_data, 
    fast_period=12, 
    slow_period=26
)

# 2. 获取详细的信号DataFrame（包含信号名称、方向和强度）
signals_apo_detailed = APO_Calculator.get_detailed_signals_dataframe(
    close_prices_matrix=Close_data
)'''

# 这里是对APO指标的解释和公式的撰写，方便阅读
'''APO的参数，对应优缺点

APO：Absolute Price Oscillator (绝对价格振荡器)
定义：APO是快速期指数移动平均线（EMA）与慢速期EMA之间的差值。它衡量的是短期动量相对于长期动量的绝对差异。

EMA： Exponential Moving Average
APO： Absolute Price Oscillator
α = 2 / (周期 + 1)
EMA 当前值 = (当前价格 × α) + (前一期 EMA 值 × (1 - α))

APO 公式:
APO = EMA(Price, fast\_period) - EMA(Price, slow\_period)

优点：
1. 绝对差值：与MACD不同（MACD是DIF的EMA），APO是两条EMA的直接差值，对价格变动的反应更直接、更快。
2. 趋势强度：APO值的大小直接反映了短期与长期动量的绝对强度差异，可用于判断趋势的加速或减速。
3. 波动率适应性：在某些策略中，与价格相关的绝对值指标可能更稳定。

缺点：
1. 缺乏平滑：由于APO线没有信号线（如MACD的DEA），其波动性高于MACD柱状图，可能产生更多噪音。
2. 信号敏感：对周期参数的选择更敏感，在震荡市中可能产生频繁的零轴穿越。
'''


class APO:
    def __init__(self):
        # 定义信号强度 (可根据回测结果调整)
        self.signal_strength = {
            # 基础趋势信号
            "golden_cross": 0.5,             # APO上穿零轴（趋势转多）
            "death_cross": -0.5,             # APO下穿零轴（趋势转空）
            "uptrend_confirmation": 0.3,     # APO持续为正（确认上升趋势）
            "downtrend_confirmation": -0.3,  # APO持续为负（确认下降趋势）
            # 反转信号
            "bottom_divergence": 0.8,        # 底部背离（强看涨反转）
            "top_divergence": -0.8,          # 顶部背离（强看跌反转）
            # 动量/超买超卖信号
            "trend_acceleration_bull": 0.6,  # 趋势加速（看涨）
            "trend_acceleration_bear": -0.6, # 趋势加速（看跌）
            "overbought_signal": -0.4,       # 超买（弱看跌警告）
            "oversold_signal": 0.4,          # 超卖（弱看涨机会）
        }

        # 所有信号名称列表；连续特征保留归一化后的幅度，便于排序/回归。
        self.continuous_signal_names = [
            "relative_value",
            "slope_rate",
            "range_position",
        ]
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names

    def get_apo_components(self, close_prices_matrix, fast_period=12, slow_period=26):
        """计算APO核心组件 (fast_ema, slow_ema, apo_line)"""
        # 使用adjust=False进行标准EMA计算，以匹配常用技术指标软件
        ema_fast = close_prices_matrix.ewm(span=fast_period, adjust=False).mean()
        ema_slow = close_prices_matrix.ewm(span=slow_period, adjust=False).mean()
        
        # APO线 (绝对价格振荡器)
        apo_line = ema_fast - ema_slow
        
        # 填充NaN值，通常由e.g. slow_period-1个初始值产生
        apo_line = apo_line.ffill().fillna(0) # 用前一个有效值填充，开头仍为NaN的设为0
        
        return ema_fast, ema_slow, apo_line

    def zero_cross_signals(self, apo_line):
        """APO零轴穿越信号（金叉/死叉）"""
        
        # 零轴穿越 (APO金叉/死叉)
        prev_apo = apo_line.shift(1)
        
        # 金叉: APO上穿零轴 (prev_apo <= 0 且 apo_line > 0)
        golden_cross = ((prev_apo <= 0) & (apo_line > 0)).astype(float) * self.signal_strength["golden_cross"]
        
        # 死叉: APO下穿零轴 (prev_apo >= 0 且 apo_line < 0)
        death_cross = ((prev_apo >= 0) & (apo_line < 0)).astype(float) * self.signal_strength["death_cross"]
        
        return {
            "golden_cross": golden_cross.fillna(0),
            "death_cross": death_cross.fillna(0)
        }
    
    def trend_confirmation_signals(self, apo_line):
        """APO趋势确认信号"""
        
        # 上升趋势确认: APO持续在零轴上方
        uptrend_confirmation = (apo_line > 0).astype(float) * self.signal_strength["uptrend_confirmation"]
        
        # 下降趋势确认: APO持续在零轴下方
        downtrend_confirmation = (apo_line < 0).astype(float) * self.signal_strength["downtrend_confirmation"]
        
        return {
            "uptrend_confirmation": uptrend_confirmation.fillna(0),
            "downtrend_confirmation": downtrend_confirmation.fillna(0)
        }

    def divergence_signals(self, apo_line, close_prices_matrix, lookback_period=20, divergence_threshold=0.02):
        """APO顶底背离信号 (使用向量化简化实现)"""
        
        # 最近 lookback_period 内的最高价/最低价和APO的最大值/最小值
        price_high = close_prices_matrix.rolling(lookback_period).max()
        price_low = close_prices_matrix.rolling(lookback_period).min()
        apo_max = apo_line.rolling(lookback_period).max()
        apo_min = apo_line.rolling(lookback_period).min()

        # 计算背离: 比较当前值与lookback_period内的极值
        current_price = close_prices_matrix
        current_apo = apo_line
        
        # 1. 顶背离 (Top Divergence): 价格创新高，APO未创新高
        # 价格创新高 (当前价 > 0.98 * 历史最高价) 且 APO未创新高 (当前APO < 历史最高APO * (1 - threshold))
        price_peak = (current_price > price_high.shift(1) * (1 - divergence_threshold))
        apo_not_peak = (current_apo < apo_max.shift(1) * (1 - divergence_threshold))
        is_top_divergence = (price_peak & apo_not_peak & (apo_line > 0)).astype(float) * self.signal_strength["top_divergence"]
        
        # 2. 底背离 (Bottom Divergence): 价格创新低，APO未创新低
        # 价格创新低 (当前价 < 1.02 * 历史最低价) 且 APO未创新低 (当前APO > 历史最低APO * (1 + threshold))
        price_trough = (current_price < price_low.shift(1) * (1 + divergence_threshold))
        apo_not_trough = (current_apo > apo_min.shift(1) * (1 + divergence_threshold))
        is_bottom_divergence = (price_trough & apo_not_trough & (apo_line < 0)).astype(float) * self.signal_strength["bottom_divergence"]
        
        return {
            "top_divergence": is_top_divergence.fillna(0),
            "bottom_divergence": is_bottom_divergence.fillna(0)
        }

    def momentum_signals(self, apo_line, lookback_period=10):
        """APO趋势加速/超买超卖信号"""
        
        # APO斜率 (动量)
        apo_slope = apo_line.diff()
        prev_slope = apo_slope.shift(1)
        
        # 1. 趋势加速/减速 (基于APO斜率的变化)
        # 加速 (斜率绝对值增加)
        is_acceleration = (apo_slope.abs() > prev_slope.abs() * 1.5)
        trend_acceleration_bull = (is_acceleration & (apo_line > 0)).astype(float) * self.signal_strength["trend_acceleration_bull"]
        trend_acceleration_bear = (is_acceleration & (apo_line < 0)).astype(float) * self.signal_strength["trend_acceleration_bear"]
        
        # 2. 超买超卖 (基于近期的APO极值)
        apo_max = apo_line.rolling(lookback_period).max()
        apo_min = apo_line.rolling(lookback_period).min()
        apo_range = apo_max - apo_min
        
        # 归一化APO位置 [0, 1]
        apo_position = (apo_line - apo_min) / apo_range
        
        is_overbought = (apo_position > 0.8).astype(float) * self.signal_strength["overbought_signal"]
        is_oversold = (apo_position < 0.2).astype(float) * self.signal_strength["oversold_signal"]

        return {
            "trend_acceleration_bull": trend_acceleration_bull.fillna(0),
            "trend_acceleration_bear": trend_acceleration_bear.fillna(0),
            "overbought_signal": is_overbought.fillna(0),
            "oversold_signal": is_oversold.fillna(0)
        }

    def continuous_signals(self, close_prices_matrix, apo_line, lookback_period=10):
        """返回不依赖价格绝对单位的连续 APO 特征。"""
        close_abs = close_prices_matrix.abs().replace(0.0, np.nan)
        relative_value = (apo_line / close_abs).clip(lower=-1.0, upper=1.0).fillna(0.0)
        slope_rate = (apo_line.diff() / close_abs).clip(lower=-1.0, upper=1.0).fillna(0.0)
        apo_max = apo_line.rolling(lookback_period, min_periods=lookback_period).max()
        apo_min = apo_line.rolling(lookback_period, min_periods=lookback_period).min()
        apo_range = (apo_max - apo_min).replace(0.0, np.nan)
        range_position = (2.0 * (apo_line - apo_min) / apo_range - 1.0).clip(
            lower=-1.0, upper=1.0
        ).fillna(0.0)
        return {
            "relative_value": relative_value,
            "slope_rate": slope_rate,
            "range_position": range_position,
        }

    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, fast_period=12, slow_period=26, enabled_signals=None):
        """
        整合启用的信号，生成最终的APO信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            fast_period: int, 快速EMA周期
            slow_period: int, 慢速EMA周期
            enabled_signals: list，指定启用的信号名称

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
        
        # 1. 如果没有指定启用的信号，使用所有信号
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 2. 初始化累加矩阵（只使用Close_data）
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 3. 计算APO核心组件
        _, _, apo_line = self.get_apo_components(Close_data, fast_period, slow_period)

        # 4. 获取所有信号矩阵
        zero_cross = self.zero_cross_signals(apo_line)
        trend_conf = self.trend_confirmation_signals(apo_line)
        divergence = self.divergence_signals(apo_line, Close_data)
        momentum = self.momentum_signals(apo_line)
        continuous = self.continuous_signals(Close_data, apo_line)

        # 合并所有信号字典
        all_signals_dict = {**zero_cross, **trend_conf, **divergence, **momentum, **continuous}

        # 5. 累加启用的信号强度
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_name in enabled_signals and signal_matrix is not None:
                # 信号强度可能为0，但不会是None
                
                # 累加买入信号 (强度 > 0)
                buy_mask = signal_matrix > 0
                sum_buy = sum_buy + signal_matrix.where(buy_mask, 0)
                
                # 累加卖出信号 (强度 < 0)
                sell_mask = signal_matrix < 0
                sum_sell = sum_sell + signal_matrix.where(sell_mask, 0)

        # 6. 处理初始NaN值 (由于EMA和Rolling计算)
        # 用0填充初始计算不足导致的前几个NaN行
        sum_buy = sum_buy.fillna(0)
        sum_sell = sum_sell.fillna(0)
        
        # 根据slow_period屏蔽初始行
        # 默认 fast_period=12, slow_period=26，至少有26个数据才能较好的计算EMA
        min_valid_rows = max(fast_period, slow_period) 
        if len(sum_buy) > min_valid_rows:
            sum_buy.iloc[:min_valid_rows] = 0.0
            sum_sell.iloc[:min_valid_rows] = 0.0
            
        '''这里得到的分别是买和卖的矩阵，index是日期，column是标的，value是对应的强度值'''
        return sum_buy, sum_sell

    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name, date_index, stock_columns):
        """将单个信号矩阵转换为记录列表"""
        
        # 堆叠矩阵，找出非零信号
        stacked = signal_matrix.stack()
        non_zero_signals = stacked[stacked != 0]
        
        if len(non_zero_signals) == 0:
            return []
        
        # 直接从MultiIndex中解包日期和合约
        dates, stocks = zip(*non_zero_signals.index)
        
        # 构建DataFrame
        result_df = pd.DataFrame({
            'Date': dates,
            'Contract': stocks,
            'direction': np.where(non_zero_signals.values > 0, "buy", "sell"),
            'signal_name': signal_name,
            'strength': np.abs(non_zero_signals.values)
        })
        
        # 转换为记录列表
        records = result_df.to_dict('records')
        
        return records

    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, fast_period=12, slow_period=26):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 计算APO核心组件（只使用Close_data）
        _, _, apo_line = self.get_apo_components(Close_data, fast_period, slow_period)
        
        # 获取日期索引和股票列名
        date_index = Close_data.index
        stock_columns = Close_data.columns
        
        # 信号处理器列表
        signal_processors = [
            self.zero_cross_signals(apo_line),
            self.trend_confirmation_signals(apo_line),
            self.divergence_signals(apo_line, Close_data),
            self.momentum_signals(apo_line),
            self.continuous_signals(Close_data, apo_line),
        ]
        
        # 统一处理所有信号记录
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name, date_index, stock_columns)
            for processor in signal_processors
            for signal_name, signal_matrix in processor.items()
        ))
        
        # 创建并返回排序后的DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
            
            # 同样屏蔽初始无效行
            min_valid_rows = max(fast_period, slow_period)
            if len(Close_data) > min_valid_rows:
                 # 过滤掉日期早于有效期的信号
                signals_df = signals_df[signals_df['Date'] >= Close_data.index[min_valid_rows]]
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      fast_period=12, slow_period=26, enabled_signals=None):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        这是一个通用方法，可以被其他类似的技术指标类复用。
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，OHLC数据
            fast_period: int，快速EMA周期，默认12
            slow_period: int，慢速EMA周期，默认26
            enabled_signals: list，指定启用的信号名称，默认None表示使用所有信号
        
        返回:
            signals_multi_index: pd.DataFrame
                - Index: MultiIndex (Date, Contract)
                    - Date: int32格式（如 20240101）
                    - Contract: string格式
                - Columns: 各个信号名称
                - Values: float32格式，对应信号的强度值（保留正负和0）
        
        使用示例:
            # 获取所有信号
            df = apo_analyzer.get_multi_index_signal_matrix(
                Open_data, High_data, Low_data, Close_data, Volume
            )
            
            # 获取特定信号
            df = apo_analyzer.get_multi_index_signal_matrix(
                Open_data, High_data, Low_data, Close_data, Volume,
                enabled_signals=['golden_cross', 'death_cross', 'top_divergence']
            )
        """
        
        # 1. 计算APO核心组件
        _, _, apo_line = self.get_apo_components(Close_data, fast_period, slow_period)
        
        # 2. 获取各类信号
        zero_cross = self.zero_cross_signals(apo_line)
        trend_conf = self.trend_confirmation_signals(apo_line)
        divergence = self.divergence_signals(apo_line, Close_data)
        momentum = self.momentum_signals(apo_line)
        continuous = self.continuous_signals(Close_data, apo_line)

        # 3. 合并所有信号字典
        all_signals_dict = {**zero_cross, **trend_conf, **divergence, **momentum, **continuous}
        
        # 4. 过滤信号
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
            
            # 7. 屏蔽初始无效行（前 max(fast_period, slow_period) 行）
            min_valid_rows = max(fast_period, slow_period)
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
    
    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, fast_period=12, slow_period=26):
        """
        拆分APO的所有子信号。
        """
        _, _, apo_line = self.get_apo_components(Close_data, fast_period, slow_period)
        
        zero = self.zero_cross_signals(apo_line)
        conf = self.trend_confirmation_signals(apo_line)
        div = self.divergence_signals(apo_line, Close_data)
        mom = self.momentum_signals(apo_line)
        continuous = self.continuous_signals(Close_data, apo_line)

        all_factors = {**zero, **conf, **div, **mom, **continuous}
        
        min_period = max(fast_period, slow_period)
        for name in all_factors:
            all_factors[name].iloc[:min_period * 2] = 0.0
                
        return all_factors
