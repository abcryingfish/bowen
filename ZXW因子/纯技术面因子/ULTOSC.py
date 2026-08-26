import pandas as pd
import numpy as np

from itertools import chain

# ==========================================
# ULTOSC 终极震荡指标技术面分析类
# ==========================================

'''from strategys.技术面.ULTOSC import ULTOSC_Analyzer
trans = ULTOSC_Analyzer()
# 这里分别得到不同的买入卖出信号矩阵
signal_apo_buy,signal_apo_sell = trans.get_total_signal_matrix(Open_data,High_data,Low_data,Close_data,Volume)
signals_apo_search = trans.get_detailed_signals_dataframe(High_data,Low_data,Close_data)'''


class ULTOSC:
    """
    ULTOSC终极震荡指标技术面综合分析类
    用于对多合约OHLCV数据进行向量化的ULTOSC指标计算和形态检测。
    采用标准 ULTOSC 公式（基于BP/TR）。
    """
    def __init__(self):
        # 信号强度定义（ULTOSC通常没有信号线，主要基于中轴和超买超卖区）
        self.signal_strength = {
            # 中轴突破/穿越信号 (ULTOSC穿越50线)
            "turn_positive": 0.55,           # 上穿50（ULTOSC转正）：看涨
            "turn_negative": -0.55,          # 下穿50（ULTOSC转负）：看跌
            
            # 区域突破与回踩 (ULTOSC突破超买/超卖线)
            "overbought_breakthrough": 0.4,  # 超买突破：趋势转换/警示
            "oversold_breakthrough": -0.4,   # 超卖突破：趋势转换/警示
            "overbought_pullback": -0.6,     # 超买回踩：顶部确认（短期回调）
            "oversold_pullback": 0.6,        # 超卖回踩：底部确认（短期反弹）

            # 背离与形态
            "bottom_divergence": 0.8,        # 底背离：强烈看涨反转
            "top_divergence": -0.8,          # 顶背离：强烈看跌反转
            "double_bottom": 0.5,            # 双底形态（超卖区）：底部反转
            "double_top": -0.5,              # 双顶形态（超买区）：顶部反转
            
            # 其它信号
            "extreme_reversal_bull": 0.6,    # 极值反转（从低位向上）：看涨
            "extreme_reversal_bear": -0.6,   # 极值反转（从高位向下）：看跌
            "expansion": 0.3,                # 放大：趋势加速
            "contraction": -0.3,             # 缩小：趋势减弱
            "bull_bear_transition": 0.65,    # 多空转换（ULTOSC穿50）：趋势确认
        }

        self.continuous_signal_names = [
            "normalized_value",
            "slope_rate",
            "range_position",
        ]

        # 所有信号名称列表
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names

    def get_ultosc_components(self, high_prices, low_prices, close_prices, 
                             period1=7, period2=14, period3=28):
        """
        计算ULTOSC核心组件（ULTOSC）。
        采用标准公式：ULTOSC = 100 * [(4*Avg7 + 2*Avg14 + Avg28) / 7]
        """
        
        # 1. 计算 Buying Pressure (BP) 和 True Range (TR)
        prev_close = close_prices.shift(1)

        # BP = Close - min(Low, PrevClose)
        bp = close_prices - low_prices.combine(prev_close, np.minimum)
        
        # TR = max(High, PrevClose) - min(Low, PrevClose)
        true_high = high_prices.combine(prev_close, np.maximum)
        true_low = low_prices.combine(prev_close, np.minimum)
        tr = true_high - true_low
        
        # 2. 计算 Avg_n (n日BP总和 / n日TR总和)
        # 避免除零错误，用 .replace([np.inf, -np.inf], np.nan) 替换
        
        avg_7 = bp.rolling(window=period1).sum() / tr.rolling(window=period1).sum()
        avg_14 = bp.rolling(window=period2).sum() / tr.rolling(window=period2).sum()
        avg_28 = bp.rolling(window=period3).sum() / tr.rolling(window=period3).sum()
        
        # 3. 计算 ULTOSC (加权平均)
        ultosc = 100 * (4 * avg_7 + 2 * avg_14 + 1 * avg_28) / 7
        
        # 填充NaN值：由于滚动计算会产生NaN，最终结果中用 50.0 填充（中性值）
        ultosc = ultosc.replace([np.inf, -np.inf], np.nan).fillna(50.0)
        
        return ultosc

    def midline_turn_signals(self, ultosc):
        """生成中轴(50)转正/转负信号 (向量化)"""
        
        ultosc_prev = ultosc.shift(1)
        
        # 1. ULTOSC转正 (上穿50)
        turn_positive = ((ultosc_prev <= 50) & (ultosc > 50)).astype(float) * self.signal_strength["turn_positive"]
        
        # 2. ULTOSC转负 (下穿50)
        turn_negative = ((ultosc_prev >= 50) & (ultosc < 50)).astype(float) * self.signal_strength["turn_negative"]

        return {
            "turn_positive": turn_positive.fillna(0),
            "turn_negative": turn_negative.fillna(0),
        }

    def breakthrough_pullback_signals(self, ultosc, overbought_level=80, oversold_level=20):
        """生成超买/超卖突破和回踩信号 (向量化)"""

        ultosc_prev = ultosc.shift(1)
        
        # 1. 超买突破
        ob_breakthrough = ((ultosc_prev <= overbought_level) & (ultosc > overbought_level)).astype(float) * self.signal_strength["overbought_breakthrough"]
        
        # 2. 超卖突破 (下穿)
        os_breakthrough = ((ultosc_prev >= oversold_level) & (ultosc < oversold_level)).astype(float) * self.signal_strength["oversold_breakthrough"]
        
        # 3. 超买回踩 (从超买区回落到超买线以下)
        ob_pullback = ((ultosc_prev > overbought_level) & (ultosc <= overbought_level)).astype(float) * self.signal_strength["overbought_pullback"]
        
        # 4. 超卖回踩 (从超卖区回升到超卖线以上)
        os_pullback = ((ultosc_prev < oversold_level) & (ultosc >= oversold_level)).astype(float) * self.signal_strength["oversold_pullback"]
        
        # 5. 极值反转
        extreme_reversal_bull = ((ultosc < 5) & (ultosc > ultosc_prev)).astype(float) * self.signal_strength["extreme_reversal_bull"]
        extreme_reversal_bear = ((ultosc > 95) & (ultosc < ultosc_prev)).astype(float) * self.signal_strength["extreme_reversal_bear"]

        return {
            "overbought_breakthrough": ob_breakthrough.fillna(0),
            "oversold_breakthrough": os_breakthrough.fillna(0),
            "overbought_pullback": ob_pullback.fillna(0),
            "oversold_pullback": os_pullback.fillna(0),
            "extreme_reversal_bull": extreme_reversal_bull.fillna(0),
            "extreme_reversal_bear": extreme_reversal_bear.fillna(0),
        }

    def trend_signals_detailed(self, ultosc):
        """生成趋势相关信号（扩张、收缩、转换）(向量化)"""
        
        ultosc_prev1 = ultosc.shift(1)
        ultosc_prev2 = ultosc.shift(2)
        
        # 1. 放大 (偏离中轴50的幅度增加 1.2 倍)
        expansion = (np.abs(ultosc - 50) > np.abs(ultosc_prev1 - 50) * 1.2).astype(float) * self.signal_strength.get("expansion", 0)

        # 2. 缩小 (偏离中轴50的幅度减小 0.8 倍)
        contraction = (np.abs(ultosc - 50) < np.abs(ultosc_prev1 - 50) * 0.8).astype(float) * self.signal_strength.get("contraction", 0)

        # 3. 简化多空转换 (从50下方连续2日后第3日上穿50)
        bull_bear_transition = ((ultosc_prev2 < 50) & (ultosc_prev1 < 50) & (ultosc > 50)).astype(float) * self.signal_strength.get("bull_bear_transition", 0)
        
        return {
            "expansion": expansion.fillna(0),
            "contraction": contraction.fillna(0),
            "bull_bear_transition": bull_bear_transition.fillna(0),
        }

    def pattern_signals_detailed(self, ultosc, overbought_level=80, oversold_level=20):
        """生成简化的形态信号（双顶/双底）(向量化)"""
        
        ultosc_prev1 = ultosc.shift(1)
        ultosc_prev2 = ultosc.shift(2)

        # 1. 简化双底形态 (3周期反转：谷-峰-谷, 且峰值在超卖区以下)
        # 这是一个简化的3周期反转：当日UTOSC < 前日UTOSC > 前前日UTOSC，即形成“峰”
        double_bottom = ((ultosc_prev1 < ultosc_prev2) & (ultosc_prev1 < ultosc) & 
                         (ultosc_prev1 < oversold_level)).astype(float) * self.signal_strength.get("double_bottom", 0)

        # 2. 简化双顶形态 (3周期反转：峰-谷-峰, 且谷值在超买区以上)
        double_top = ((ultosc_prev1 > ultosc_prev2) & (ultosc_prev1 > ultosc) & 
                      (ultosc_prev1 > overbought_level)).astype(float) * self.signal_strength.get("double_top", 0)

        return {
            "double_bottom": double_bottom.fillna(0),
            "double_top": double_top.fillna(0),
        }
        
    def divergence_signals_detailed(self, ultosc, close_prices, window=10):
        """生成简化的背离信号（10周期）(向量化)"""
        
        # 简化逻辑：比较当前价格/ULTOSC与5个交易日前的数值
        price_prev5 = close_prices.shift(5)
        ultosc_prev5 = ultosc.shift(5)
        
        # 顶背离: 价格创新高/平高 AND ULTOSC未创新高/平高 (且在超买区)
        top_divergence = ((close_prices >= price_prev5) & (ultosc < ultosc_prev5) & 
                          (ultosc > 80)).astype(float) * self.signal_strength.get("top_divergence", 0)

        # 底背离: 价格创新低/平低 AND ULTOSC未创新低/平低 (且在超卖区)
        bottom_divergence = ((close_prices <= price_prev5) & (ultosc > ultosc_prev5) & 
                             (ultosc < 20)).astype(float) * self.signal_strength.get("bottom_divergence", 0)

        return {
            "top_divergence": top_divergence.fillna(0),
            "bottom_divergence": bottom_divergence.fillna(0),
        }

    def continuous_signals(self, ultosc, lookback_period=20):
        """返回可用于排序/回归的连续 ULTOSC 特征。"""
        normalized_value = ((ultosc - 50.0) / 50.0).clip(
            lower=-1.0, upper=1.0
        ).fillna(0.0)
        slope_rate = (ultosc.diff() / 50.0).clip(
            lower=-1.0, upper=1.0
        ).fillna(0.0)

        ultosc_min = ultosc.rolling(window=lookback_period, min_periods=1).min()
        ultosc_max = ultosc.rolling(window=lookback_period, min_periods=1).max()
        ultosc_range = (ultosc_max - ultosc_min).replace(0.0, np.nan)
        range_position = (
            (2.0 * (ultosc - ultosc_min) / ultosc_range) - 1.0
        ).clip(lower=-1.0, upper=1.0).fillna(0.0)

        return {
            "normalized_value": normalized_value,
            "slope_rate": slope_rate,
            "range_position": range_position,
        }


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                enabled_signals=None, period1=7, period2=14, period3=28):
        """
        整合启用的信号，生成最终的ULTOSC信号强度矩阵
        
        参数:
            high_prices, low_prices, close_prices: pd.DataFrame, OHLC价格矩阵
            volume: pd.DataFrame, 成交量矩阵 (未在ULTOSC中使用)
            enabled_signals: list, 指定启用的信号名称
        
        返回:
            sum_buy, sum_sell: pd.DataFrame, 同输入维度，值为信号强度（-1.0至1.0）
        """
        # 1. 如果没有指定启用的信号，使用所有信号
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 2. 初始化累加矩阵
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 3. 计算ULTOSC核心组件
        ultosc = self.get_ultosc_components(High_data, Low_data, Close_data, period1, period2, period3)

        # 4. 获取所有信号矩阵
        midline_sigs = self.midline_turn_signals(ultosc)
        breakthrough_sigs = self.breakthrough_pullback_signals(ultosc)
        trend_sigs = self.trend_signals_detailed(ultosc)
        pattern_sigs = self.pattern_signals_detailed(ultosc)
        divergence_sigs = self.divergence_signals_detailed(ultosc, Close_data)

        # 合并所有信号字典
        all_signals_dict = {
            **midline_sigs, **breakthrough_sigs, 
            **trend_sigs, **pattern_sigs, **divergence_sigs
        }

        # 5. 累加信号强度
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_matrix is not None and signal_name in enabled_signals:
                buy_mask = signal_matrix > 0
                sell_mask = signal_matrix < 0
                
                # 累加买入信号的绝对值（强度）
                sum_buy = sum_buy + np.abs(signal_matrix).where(buy_mask, 0)
                # 累加卖出信号的绝对值（强度）
                sum_sell = sum_sell + np.abs(signal_matrix).where(sell_mask, 0)

        # 6. 移除由于滚动窗口导致的早期NaN行
        max_period = max(period1, period2, period3)
        sum_buy.iloc[:max_period] = 0.0
        sum_sell.iloc[:max_period] = 0.0
        
        return sum_buy, sum_sell


    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name):
        """将单个信号矩阵转换为记录列表"""
        
        # 将 DataFrame 堆叠成 Series，索引为 (Date, Contract)
        stacked = signal_matrix.stack()
        # 过滤掉强度为0（无信号）的记录
        non_zero_signals = stacked[stacked != 0]
        
        if len(non_zero_signals) == 0:
            return []
        
        # 解包多重索引
        dates, stocks = zip(*non_zero_signals.index)
        
        # 直接构建结果 DataFrame
        result_df = pd.DataFrame({
            'Date': dates,
            'Contract': stocks,
            'direction': np.where(non_zero_signals.values > 0, "buy", "sell"),
            'signal_name': signal_name,
            'strength': np.abs(non_zero_signals.values)
        })
        
        # 转换为记录列表
        return result_df.to_dict('records')


    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                     period1=7, period2=14, period3=28):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 1. 计算ULTOSC核心组件
        ultosc = self.get_ultosc_components(High_data, Low_data, Close_data, period1, period2, period3)
        
        # 2. 定义信号处理器
        signal_processors = [
            self.midline_turn_signals(ultosc),
            self.breakthrough_pullback_signals(ultosc),
            self.trend_signals_detailed(ultosc),
            self.pattern_signals_detailed(ultosc),
            self.divergence_signals_detailed(ultosc, Close_data)
        ]
        
        # 3. 统一处理所有信号记录
        all_records = []
        for processor in signal_processors:
            for signal_name, signal_matrix in processor.items():
                all_records.extend(self._convert_signal_matrix_to_records(signal_matrix, signal_name))
        
        # 4. 创建并返回排序后的DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      period1=7, period2=14, period3=28, enabled_signals=None):
        """【新增方法】生成Multi-index格式的信号矩阵"""
        
        ultosc = self.get_ultosc_components(High_data, Low_data, Close_data, period1, period2, period3)
        
        signal_processors = [
            self.midline_turn_signals(ultosc),
            self.breakthrough_pullback_signals(ultosc),
            self.trend_signals_detailed(ultosc),
            self.pattern_signals_detailed(ultosc),
            self.divergence_signals_detailed(ultosc, Close_data)
        ]
        
        all_signals_dict = {}
        for processor in signal_processors:
            all_signals_dict.update(processor)
        
        if enabled_signals is not None:
            all_signals_dict = {k: v for k, v in all_signals_dict.items() if k in enabled_signals}
        
        signal_series_list = []
        signal_names = []
        
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_matrix is not None:
                stacked_series = signal_matrix.stack()
                signal_series_list.append(stacked_series)
                signal_names.append(signal_name)
        
        if signal_series_list:
            signals_multi_index = pd.concat(signal_series_list, axis=1, keys=signal_names)
            signals_multi_index = signals_multi_index.fillna(0)
            
            if len(Close_data) > period3:
                valid_start_date = Close_data.index[period3]
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
    

    def get_factor_matrices(self, High_data, Low_data, Close_data, Volume, 
                           period1=7, period2=14, period3=28):
        """
        拆分 ULTOSC 的所有子信号矩阵。
        """
        # 1. 计算组件
        ultosc_line = self.get_ultosc_components(High_data, Low_data, Close_data, period1, period2, period3)
        
        # 2. 获取信号字典 (调用类中真实存在的方法)
        midline = self.midline_turn_signals(ultosc_line)
        breakthrough = self.breakthrough_pullback_signals(ultosc_line)
        trend = self.trend_signals_detailed(ultosc_line)
        pattern = self.pattern_signals_detailed(ultosc_line)
        div = self.divergence_signals_detailed(ultosc_line, Close_data)
        continuous = self.continuous_signals(ultosc_line)

        # 3. 合并所有字典
        all_factors = {
            **midline,
            **breakthrough,
            **trend,
            **pattern,
            **div,
            **continuous,
        }
        
        # 4. 清洗数据
        # ULTOSC 至少需要 period3 才能稳定
        skip_rows = period3 * 2
        
        for name, df in all_factors.items():
            if df is not None:
                df = df.reindex_like(Close_data).fillna(0.0)
                if len(df) > skip_rows:
                    df.iloc[:skip_rows] = 0.0
                all_factors[name] = df
            else:
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
                
        return all_factors
