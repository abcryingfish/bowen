import pandas as pd
import numpy as np
from itertools import chain


'''from strategys.技术面.AROON import AROON
# 实例化APO类
trans = AROON()

# 1. 获取汇总的买卖信号强度矩阵
# 使用默认参数 fast_period=12, slow_period=26
signal_apo_buy, signal_apo_sell = trans.get_total_signal_matrix(
    High_data, 
    Low_data, 
    Close_data
)

# 2. 获取详细的信号DataFrame（包含信号名称、方向和强度）
signals_apo_detailed = trans.get_detailed_signals_dataframe(
    High_data, 
    Low_data, 
    Close_data



total_matrix_1 = trans.get_multi_index_signal_matrix(Open_data,High_data,Low_data,Close_data,Volume,enabled_signals=None, aroon_period=14)

)'''

# 这里是对AROON指标的解释和公式的撰写，方便阅读
'''AROON的参数，对应优缺点

AROON：Aroon Indicator (阿隆指标)
定义：Aroon指标用于衡量价格趋势的强度和趋势持续性。它由两条线组成：Aroon Up（上升线）和 Aroon Down（下降线），以及一个震荡器（Aroon Oscillator）。

计算公式：
周期： N (默认为14)

1. Aroon Up（上升线）：衡量在N周期内，最近一次最高价出现到当前的期间长度。
   Aroon Up = [ (N - 距离最近最高价出现的天数) / N ] * 100

2. Aroon Down（下降线）：衡量在N周期内，最近一次最低价出现到当前的期间长度。
   Aroon Down = [ (N - 距离最近最低价出现的天数) / N ] * 100

3. Aroon Oscillator（震荡器）：衡量多空力量的绝对差异。
   Aroon Oscillator = Aroon Up - Aroon Down

优点：
1. **趋势识别快**：Aroon Up或Aroon Down快速达到100或接近100时，能快速确认趋势的启动。
2. **趋势持续性**：能直观地显示当前趋势的“新鲜度”，即最近的极值是否发生在近期。
3. **适用于震荡市**：当两条线均低于50时，常被视为盘整或震荡区间的信号。

缺点：
1. **滞后性**：作为趋势指标，它基于历史最高价和最低价的位置，仍有一定的滞后性。
2. **高频波动**：在震荡行情中，Aroon线可能会频繁交叉，产生大量噪音信号。
3. **计算复杂**：计算涉及找到周期内的极值位置，难以完全依赖简单的移动平均进行平滑。
'''


class AROON:
    def __init__(self):
        # 定义信号强度 (根据信号的可靠性设定初始权重)
        self.signal_strength = {
            # 核心趋势信号 (已实现)
            "golden_cross": 0.5,                                # AROON Up上穿 AROON Down
            "death_cross": -0.5,                                # AROON Up下穿 AROON Down
            "oscillator_zero_breakthrough": 0.6,                # 震荡器上穿零轴
            "oscillator_zero_pullback": -0.6,                   # 震荡器下穿零轴（根据文件，此为趋势转换信号，此处强度为负，代表趋势减弱或反转）
            "up_breakthrough": 0.7,                             # AROON Up突破高位区 (如70)
            "down_breakthrough": -0.7,                          # AROON Down突破高位区 (如70)
            # 反转/极值信号 (已实现)
            "top_divergence": -0.8,                             # 顶背离 (强看跌反转)
            "bottom_divergence": 0.8,                           # 底背离 (强看涨反转)
            "overbought_signal": -0.4,                          # 超买警告 (看跌)
            "oversold_signal": 0.4,                             # 超卖机会 (看涨)
            "extreme_reversal": 0.5,                            # 极值反转 (趋势减弱或反转)
            "bull_bear_transition": 0.6,                        # 多空转换
            "strong_zone": 0.4,                                 # 强势趋势区间
            "weak_zone": -0.3,                                  # 弱势震荡区间
            # 形态信号 (仅保留名称，实际计算需要更复杂的逻辑，未在函数中实现)
            "double_bottom": 0.7,                               # 震荡器双底 (底部反转)
            "double_top": -0.7,                                 # 震荡器双顶 (顶部反转)
            "triple_bottom": 0.8,                               # 强烈底部反转
            "triple_top": -0.8,                                 # 强烈顶部反转
            "head_shoulders_bottom": 0.9,                       # 底部反转
            "head_shoulders_top": -0.9,                         # 顶部反转
            "rising_wedge": -0.6,                               # 楔形上升
            "falling_wedge": 0.6,                               # 楔形下降
            "triangle_convergence": 0.3,                        # 三角形收敛
            "triangle_divergence": 0.2,                         # 三角形发散
            "channel_breakthrough": 0.5,                        # 通道突破
            "channel_pullback": 0.3,                            # 通道回踩
            "breakthrough_confirmation": 0.5,                   # 突破确认
            "pullback_confirmation": 0.4,                       # 回调确认
            "trend_strengthening": 0.4,                         # 趋势强化
            "trend_weakening": -0.4,                            # 趋势弱化
        }

        # 所有信号名称列表；连续特征保留归一化后的 Aroon 线幅度。
        self.continuous_signal_names = [
            "up_strength",
            "down_strength",
            "oscillator_value",
        ]
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names
        
        # 复杂形态信号列表（未在主要函数中实现，仅用于内部管理）
        self.complex_patterns = [
            'triple_bottom', 'triple_top', 'head_shoulders_bottom', 'head_shoulders_top',
            'rising_wedge', 'falling_wedge', 'triangle_convergence', 'triangle_divergence',
            'channel_breakthrough', 'channel_pullback', 'breakthrough_confirmation', 'pullback_confirmation',
        ]

    def get_aroon_components(self, high_prices_matrix, low_prices_matrix, aroon_period=14):
        """
        计算AROON核心组件（Aroon Up, Aroon Down, Aroon Oscillator）。
        采用向量化计算，使用rolling.apply结合numpy.argmax/argmin来高效获取极值位置。
        """
        
        # Aroon Up: 最近 period 周期内最高价距离当前的天数
        # np.argmax(x) 返回窗口内最高价的相对位置（0到period-1）
        aroon_up = high_prices_matrix.rolling(aroon_period).apply(
            lambda x: 100 * (aroon_period - np.argmax(x)) / aroon_period, raw=True
        )
        
        # Aroon Down: 最近 period 周期内最低价距离当前的天数
        # np.argmin(x) 返回窗口内最低价的相对位置
        aroon_down = low_prices_matrix.rolling(aroon_period).apply(
            lambda x: 100 * (aroon_period - np.argmin(x)) / aroon_period, raw=True
        )

        # Aroon Oscillator
        aroon_oscillator = aroon_up - aroon_down
        
        # 填充初始NaN值（通常由周期不足引起）
        aroon_up = aroon_up.ffill().fillna(0)
        aroon_down = aroon_down.ffill().fillna(0)
        aroon_oscillator = aroon_oscillator.ffill().fillna(0)
        
        return aroon_up, aroon_down, aroon_oscillator

    def trend_signals(self, aroon_up, aroon_down, aroon_oscillator):
        """生成趋势转换和突破信号 (金叉/死叉, 零轴突破, 极值突破)"""
        
        prev_up = aroon_up.shift(1)
        prev_down = aroon_down.shift(1)
        prev_osc = aroon_oscillator.shift(1)
        
        # 1. AROON金叉 (Up上穿Down)
        golden_cross = ((prev_up <= prev_down) & (aroon_up > aroon_down)).astype(float) * self.signal_strength["golden_cross"]
        
        # 2. AROON死叉 (Up下穿Down)
        death_cross = ((prev_up >= prev_down) & (aroon_up < aroon_down)).astype(float) * self.signal_strength["death_cross"]
        
        # 3. 震荡器零轴突破 (上穿)
        osc_zero_break_up = ((prev_osc <= 0) & (aroon_oscillator > 0)).astype(float) * self.signal_strength["oscillator_zero_breakthrough"]
        
        # 4. 震荡器零轴回踩 (下穿) - 根据文件描述，也视为趋势转换信号
        osc_zero_break_down = ((prev_osc >= 0) & (aroon_oscillator < 0)).astype(float) * self.signal_strength["oscillator_zero_pullback"]

        # 5. AROON上升突破 (Up突破70)
        up_breakthrough = ((prev_up <= 70) & (aroon_up > 70)).astype(float) * self.signal_strength["up_breakthrough"]

        # 6. AROON下降突破 (Down突破70)
        down_breakthrough = ((prev_down <= 70) & (aroon_down > 70)).astype(float) * self.signal_strength["down_breakthrough"]

        return {
            "golden_cross": golden_cross.fillna(0),
            "death_cross": death_cross.fillna(0),
            "oscillator_zero_breakthrough": osc_zero_break_up.fillna(0),
            "oscillator_zero_pullback": osc_zero_break_down.fillna(0),
            "up_breakthrough": up_breakthrough.fillna(0),
            "down_breakthrough": down_breakthrough.fillna(0)
        }
        
    def extreme_zone_signals(self, aroon_up, aroon_down):
        """超买超卖和强势/弱势区间信号"""
        
        # 1. 超买信号 (Up高位, Down低位)
        overbought = ((aroon_up > 90) & (aroon_down < 10)).astype(float) * self.signal_strength["overbought_signal"]

        # 2. 超卖信号 (Up低位, Down高位)
        oversold = ((aroon_up < 10) & (aroon_down > 90)).astype(float) * self.signal_strength["oversold_signal"]

        # 3. 强势区间 (Up高位, Down低位 - 较宽松)
        strong_zone = ((aroon_up > 70) & (aroon_down < 30)).astype(float) * self.signal_strength["strong_zone"]

        # 4. 弱势区间/震荡 (Up, Down均在50以下)
        weak_zone = ((aroon_up < 50) & (aroon_down < 50)).astype(float) * self.signal_strength["weak_zone"]

        # 5. 多空转换 (与金叉/死叉接近，但更关注趋势线本身的反转)
        bull_bear_transition = (((aroon_up.shift(1) < aroon_down.shift(1)) & (aroon_up > aroon_down)) | 
                                ((aroon_up.shift(1) > aroon_down.shift(1)) & (aroon_up < aroon_down))).astype(float) * self.signal_strength["bull_bear_transition"]
        
        return {
            "overbought_signal": overbought.fillna(0),
            "oversold_signal": oversold.fillna(0),
            "strong_zone": strong_zone.fillna(0),
            "weak_zone": weak_zone.fillna(0),
            "bull_bear_transition": bull_bear_transition.fillna(0)
        }

    def pattern_signals(self, aroon_oscillator, window=5):
        """简单形态信号 (双顶/双底)"""
        
        # 简化双底/双顶检测 (基于震荡器的极值)
        # 寻找极低点：current_osc < prev_osc and current_osc < next_osc (使用shift实现)
        
        # 双底：近期低点形成后，反弹，再次形成低点
        # 假设：当前震荡器低于前一根，且前一根低于再前一根（形成 V 形底）
        is_low = (aroon_oscillator < aroon_oscillator.shift(1))
        
        # 简化的双底：寻找在负值区间内的两个相对低谷，且第二个低谷与第一个低谷接近
        is_double_bottom = ((aroon_oscillator.shift(1) < aroon_oscillator.shift(2)) & 
                            (aroon_oscillator.shift(3) < aroon_oscillator.shift(2)) &
                            (aroon_oscillator.shift(1) < -20) & 
                            (aroon_oscillator.shift(3) < -20) &
                            (abs(aroon_oscillator.shift(1) - aroon_oscillator.shift(3)) < 10)
                           ).astype(float) * self.signal_strength["double_bottom"]

        # 简化的双顶：寻找在正值区间内的两个相对高峰，且第二个高峰与第一个高峰接近
        is_double_top = ((aroon_oscillator.shift(1) > aroon_oscillator.shift(2)) & 
                         (aroon_oscillator.shift(3) > aroon_oscillator.shift(2)) &
                         (aroon_oscillator.shift(1) > 20) & 
                         (aroon_oscillator.shift(3) > 20) &
                         (abs(aroon_oscillator.shift(1) - aroon_oscillator.shift(3)) < 10)
                        ).astype(float) * self.signal_strength["double_top"]
        
        return {
            "double_bottom": is_double_bottom.fillna(0),
            "double_top": is_double_top.fillna(0)
        }

    def divergence_signals(self, aroon_up, aroon_down, close_prices_matrix, lookback_period=20, divergence_threshold=0.02):
        """AROON 顶底背离信号，只使用当前及历史 Aroon 数据。"""

        # 正确使用 Aroon Up/Down 的差值；不再通过 shift(-1) 读取未来数据。
        aroon_osc = aroon_up - aroon_down
        
        # 最近 lookback_period 内的最高价/最低价和AROON的最大值/最小值
        price_high = close_prices_matrix.rolling(lookback_period).max()
        price_low = close_prices_matrix.rolling(lookback_period).min()
        osc_max = aroon_osc.rolling(lookback_period).max()
        osc_min = aroon_osc.rolling(lookback_period).min()

        current_price = close_prices_matrix
        current_osc = aroon_osc
        
        # 1. 顶背离 (Top Divergence): 价格创新高，震荡器未创新高 (且在正值区)
        price_peak = (current_price > price_high.shift(1))
        osc_not_peak = (current_osc < osc_max.shift(1) - 100.0 * divergence_threshold)
        is_top_divergence = (price_peak & osc_not_peak & (current_osc > 0)).astype(float) * self.signal_strength["top_divergence"]
        
        # 2. 底背离 (Bottom Divergence): 价格创新低，震荡器未创新低 (且在负值区)
        price_trough = (current_price < price_low.shift(1))
        osc_not_trough = (current_osc > osc_min.shift(1) + 100.0 * divergence_threshold)
        is_bottom_divergence = (price_trough & osc_not_trough & (current_osc < 0)).astype(float) * self.signal_strength["bottom_divergence"]
        
        return {
            "top_divergence": is_top_divergence.fillna(0),
            "bottom_divergence": is_bottom_divergence.fillna(0)
        }

    def continuous_signals(self, aroon_up, aroon_down, aroon_oscillator):
        """返回 [0,1]/[-1,1] 的连续 Aroon 特征。"""
        return {
            "up_strength": (aroon_up / 100.0).clip(lower=0.0, upper=1.0).fillna(0.0),
            "down_strength": (aroon_down / 100.0).clip(lower=0.0, upper=1.0).fillna(0.0),
            "oscillator_value": (aroon_oscillator / 100.0).clip(lower=-1.0, upper=1.0).fillna(0.0),
        }


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, enabled_signals=None, aroon_period=14):
        """
        整合启用的信号，生成最终的AROON信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            enabled_signals: list，指定启用的信号名称
            aroon_period: int, AROON计算周期

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
        
        # 1. 如果没有指定启用的信号，使用所有信号
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 2. 初始化累加矩阵（只使用High_data, Low_data, Close_data）
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 3. 计算AROON核心组件
        aroon_up, aroon_down, aroon_oscillator = self.get_aroon_components(
            High_data, Low_data, aroon_period
        )

        # 4. 获取所有信号矩阵
        trend = self.trend_signals(aroon_up, aroon_down, aroon_oscillator)
        extreme = self.extreme_zone_signals(aroon_up, aroon_down)
        patterns = self.pattern_signals(aroon_oscillator)
        # 注意: 此处使用 aroon_oscillator 作为 aroon_line 传入背离函数进行简化计算
        divergence = self.divergence_signals(aroon_up, aroon_down, Close_data)
        continuous = self.continuous_signals(aroon_up, aroon_down, aroon_oscillator)

        # 合并所有信号字典
        all_signals_dict = {**trend, **extreme, **patterns, **divergence, **continuous}

        # 5. 累加启用的信号强度
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_name in enabled_signals and signal_matrix is not None:
                
                # 累加买入信号 (强度 > 0)
                buy_mask = signal_matrix > 0
                sum_buy = sum_buy + signal_matrix.where(buy_mask, 0)
                
                # 累加卖出信号 (强度 < 0)
                sell_mask = signal_matrix < 0
                sum_sell = sum_sell + signal_matrix.where(sell_mask, 0)

        # 6. 处理初始NaN值
        sum_buy = sum_buy.fillna(0)
        sum_sell = sum_sell.fillna(0)
        
        # 屏蔽初始无效行
        min_valid_rows = aroon_period
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

    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, aroon_period=14):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 计算AROON核心组件（只使用High_data, Low_data, Close_data）
        aroon_up, aroon_down, aroon_oscillator = self.get_aroon_components(
            High_data, Low_data, aroon_period
        )
        
        # 获取日期索引和股票列名
        date_index = Close_data.index
        stock_columns = Close_data.columns
        
        # 信号处理器列表
        signal_processors = [
            self.trend_signals(aroon_up, aroon_down, aroon_oscillator),
            self.extreme_zone_signals(aroon_up, aroon_down),
            self.pattern_signals(aroon_oscillator),
            self.divergence_signals(aroon_up, aroon_down, Close_data),
            self.continuous_signals(aroon_up, aroon_down, aroon_oscillator),
        ]
        
        # 统一处理所有信号记录
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name, date_index, stock_columns)
            for processor in signal_processors
            for signal_name, signal_matrix in processor.items()
            if signal_name not in self.complex_patterns  # 过滤掉未实现的复杂形态
        ))
        
        # 创建并返回排序后的DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
            
            # 同样屏蔽初始无效行
            min_valid_rows = aroon_period
            if len(Close_data) > min_valid_rows:
                 # 过滤掉日期早于有效期的信号
                signals_df = signals_df[signals_df['Date'] >= Close_data.index[min_valid_rows]]
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    # -----------------------------------------------------------------
    # 【【【【【【【【【【【【 新 增 函 数 】】】】】】】】】】】】
    # -----------------------------------------------------------------
            
    def get_multi_index_signal_matrix(self, open_prices, high_prices, low_prices, close_prices, Volume, 
                                    enabled_signals=None, aroon_period=14):
        """
        【修改后方法】生成Multi-index格式的信号矩阵。
        
        该版本不再将同一信号组内的子信号强度相加，而是将所有子信号单独作为一列输出。
        
        参数:
            open_prices, high_prices, low_prices, close_prices: pd.DataFrame，OHLC数据
            Volume: pd.DataFrame，成交量数据
            enabled_signals: list，指定启用的信号组名称 (对应信号组)
                - None: 启用所有信号组
                - list: 自定义信号组列表 (例如 ['trend_signals', 'divergence_signals'])
            aroon_period: int, AROON计算周期
        
        返回:
            signals_multi_index: pd.DataFrame
                - Index: MultiIndex (Date, Contract)
                - Columns: 各个子信号名称 (例如 'golden_cross', 'death_cross', 'extreme_bullish')
                - Values: float32格式，对应子信号的强度值（保留正负和0）
        """
        
        # 1. 计算核心组件（AROON特定）
        # 注意：AROON不使用 open_prices 和 Volume, 但参数保持一致性
        aroon_up, aroon_down, aroon_oscillator = self.get_aroon_components(
            high_prices, low_prices, aroon_period
        )
        
        # 2. 建立信号名称到计算函数的映射（lambda延迟执行）
        signal_mapping = {
            'trend_signals': lambda: self.trend_signals(aroon_up, aroon_down, aroon_oscillator),
            'extreme_zone_signals': lambda: self.extreme_zone_signals(aroon_up, aroon_down),
            'pattern_signals': lambda: self.pattern_signals(aroon_oscillator),
            # 注意: divergence_signals 需要 close_prices
            'divergence_signals': lambda: self.divergence_signals(aroon_up, aroon_down, close_prices),
            'continuous_signals': lambda: self.continuous_signals(aroon_up, aroon_down, aroon_oscillator),
        }
        
        # 3. 如果没有指定启用的信号，使用所有信号组合
        if enabled_signals is None:
            enabled_signals = list(signal_mapping.keys())
        
        # 4. 【关键修改点】计算所有启用的子信号矩阵，并收集它们
        # 策略：收集所有信号组返回字典中的所有 {子信号名: 矩阵} 对
        
        all_sub_signal_matrices = {}
        
        for signal_group_name in enabled_signals:
            if signal_group_name not in signal_mapping:
                print(f"警告: 未知的信号名称 '{signal_group_name}'，已忽略")
                continue
            
            # 调用计算函数，返回的是字典 {子信号名: 矩阵}
            result_dict = signal_mapping[signal_group_name]()
            
            # 将子信号矩阵添加到总集合中
            # result_dict 的键（子信号名）将成为最终 DataFrame 的列名
            for sub_signal_name, sub_signal_matrix in result_dict.items():
                if sub_signal_matrix is not None:
                    all_sub_signal_matrices[sub_signal_name] = sub_signal_matrix.fillna(0) # 填充0以防止stack后出现NaN
                
        # 5. 将每个子信号矩阵(Date × Contract)转换为Multi-index Series
        # 然后合并成一个DataFrame
        signal_series_list = []
        signal_names = []
        
        for sub_signal_name, sub_signal_matrix in all_sub_signal_matrices.items():
            # 将矩阵stack成Multi-index Series
            # stack()会自动创建MultiIndex (Date, Contract)
            stacked_series = sub_signal_matrix.stack()
            signal_series_list.append(stacked_series)
            signal_names.append(sub_signal_name) # 使用子信号名作为最终的列名
        
        # 6. 合并所有Series为DataFrame
        if signal_series_list:
            # 使用concat按列合并，keys参数指定列名
            signals_multi_index = pd.concat(
                signal_series_list, 
                axis=1, 
                keys=signal_names
            )
            
            # 填充NaN为0（如果 stack 后仍有缺失值，例如数据在某些日期/合约上缺失）
            # 考虑到上一步已经对原始矩阵 fillna(0) 理论上这里不会有太多 NaN
            signals_multi_index = signals_multi_index.fillna(0)
            
            # 7. 转换数据类型和索引格式
            
            # Date索引转换为int32格式（如果原始是datetime，转换为YYYYMMDD格式）
            current_dates = signals_multi_index.index.get_level_values(0)
            
            if pd.api.types.is_datetime64_any_dtype(current_dates):
                # datetime转int32 (YYYYMMDD格式)
                date_int32 = current_dates.strftime('%Y%m%d').astype('int32')
            elif pd.api.types.is_integer_dtype(current_dates):
                # 已经是整数，直接转换为int32
                date_int32 = current_dates.astype('int32')
            else:
                # 其他类型，尝试转换
                try:
                    date_int32 = pd.to_datetime(current_dates).strftime('%Y%m%d').astype('int32')
                except Exception:
                    # 转换失败，保持原样（但可能不符合int32要求）
                    print("警告：日期索引转换失败，保持原始格式")
                    date_int32 = current_dates
            
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
            
            # 8. 屏蔽初始无效行 (基于aroon_period)
            # 找到第一个有效日期
            if len(close_prices.index) > aroon_period:
                first_valid_date = close_prices.index[aroon_period - 1] # AROON需要N周期，所以第一个有效日期的索引是 N-1
            elif len(close_prices.index) > 0:
                # 如果数据不够，取最后一个有效索引
                first_valid_date = close_prices.index[-1]
            else:
                # 没有数据，直接返回空DataFrame
                return pd.DataFrame(columns=signal_names, index=pd.MultiIndex.from_tuples([], names=['Date', 'Contract'])).astype('float32')

            # 检查 close_prices.index 的类型并转换 first_valid_date_int
            if pd.api.types.is_datetime64_any_dtype(close_prices.index):
                first_valid_date_int = int(first_valid_date.strftime('%Y%m%d'))
            else:
                first_valid_date_int = int(first_valid_date)
                    
            # 过滤掉索引中早于 first_valid_date_int 的日期
            signals_multi_index = signals_multi_index[
                signals_multi_index.index.get_level_values(0) >= first_valid_date_int
            ]
                
        else:
            # 如果没有信号，创建空DataFrame
            signals_multi_index = pd.DataFrame(
                columns=signal_names if signal_names else [],
                index=pd.MultiIndex.from_tuples([], names=['Date', 'Contract'])
            ).astype('float32')
            
            # 确保空 DataFrame 的 MultiIndex Level type 正确
            if len(signals_multi_index.index.levels) > 0:
                signals_multi_index.index = signals_multi_index.index.set_levels(
                    signals_multi_index.index.levels[0].astype('int32'), level=0
                )
                signals_multi_index.index = signals_multi_index.index.set_levels(
                    signals_multi_index.index.levels[1].astype('string'), level=1
                )
                
        return signals_multi_index
    

    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, aroon_period=14):
        """
        拆分AROON的所有子信号矩阵。
        """
        up, down, osc = self.get_aroon_components(High_data, Low_data, aroon_period)
        
        trend = self.trend_signals(up, down, osc)
        extreme = self.extreme_zone_signals(up, down)
        patterns = self.pattern_signals(osc)
        div = self.divergence_signals(up, down, Close_data)
        continuous = self.continuous_signals(up, down, osc)

        all_factors = {**trend, **extreme, **patterns, **div, **continuous}
        
        for name in all_factors:
            all_factors[name].iloc[:aroon_period * 2] = 0.0
                
        return all_factors
