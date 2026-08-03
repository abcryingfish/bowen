import pandas as pd
import numpy as np
from itertools import chain

# =============================================================================
# WMA：Weighted Moving Average（加权移动平均线）
#
# 原理：WMA给予越近期的价格数据越高的权重，因此比SMA（简单移动平均）对价格变化更敏感，
#      但平滑度低于EMA（指数移动平均）。常用于判断短期和中期趋势。
#
# WMA公式（周期n）：
#   WMA = (n*Price_t + (n-1)*Price_{t-1} + ... + 1*Price_{t-n+1}) / (n + (n-1) + ... + 1)
#
# 优点：对最新价格反应灵敏，更贴近当前市场动能。
# 缺点：在震荡市中容易产生比EMA更多的假信号。
# =============================================================================


'''from strategys.技术面.WMA import WMA
trans = WMA()
# 这里分别得到不同的买入卖出信号矩阵
signal_apo_buy,signal_apo_sell = trans.get_total_signal_matrix(Open_data,High_data,Low_data,Close_data,Volume)
signals_apo_search = trans.get_detailed_signals_dataframe(Close_data)'''


class WMA:
    def __init__(self):
        # 定义所有信号的强度和方向（正值看涨，负值看跌）
        self.signal_strength = {
            # 基础交叉与排列 (WMA Short vs WMA Long)
            "golden_cross": 0.6,             # 短期WMA上穿长期WMA
            "death_cross": -0.6,             # 短期WMA下穿长期WMA
            "bullish_alignment": 0.8,        # WMA多头排列（S > M > L > T）
            "bearish_alignment": -0.8,       # WMA空头排列（S < M < L < T）

            # 价格与WMA互动
            "price_breakthrough": 0.7,       # 价格向上突破WMA Short
            "price_pullback": -0.7,          # 价格向下回踩WMA Short
            "support_confirmation": 0.5,     # 价格在WMA Short上方且WMA Short上升
            "resistance_confirmation": -0.5, # 价格在WMA Short下方且WMA Short下降

            # 趋势动量与斜率
            "turn_positive": 0.4,            # WMA斜率转正
            "turn_negative": -0.4,           # WMA斜率转负
            "trend_acceleration": 0.5,       # WMA短期加速上涨
            "trend_deceleration": -0.5,      # WMA短期加速下跌
            "bull_bear_transition": 0.7,     # 趋势反转（短期WMA上穿中期WMA）
            
            # 背离与极值
            "top_divergence": -0.9,          # 顶背离：价格新高，WMA未新高
            "bottom_divergence": 0.9,        # 底背离：价格新低，WMA未新低
            "extreme_reversal": 0.6,         # 价格距离短期WMA过远后的反转

            # 聚合与形态 (简化)
            "wma_divergence": 0.5,           # WMA发散（S/L距离增大）
            "wma_convergence": -0.5,         # WMA收敛/粘合（S/L距离减小）
            "wma_double_bottom": 0.75,       # WMA短期线形成双底
            "wma_double_top": -0.75,         # WMA短期线形成双顶
            # 将"周期共振"、"周期背离"等模糊信号并入上述更具体的信号中。
        }

        self.all_signals = list(self.signal_strength.keys())

    def _calculate_wma(self, prices, period):
        """计算WMA的辅助函数（向量化）"""
        # 注意：pandas没有内置WMA，需要自定义apply或使用ta-lib/talib的实现。
        # 此处使用numpy.average with weights，效率低于纯向量化，但比迭代快得多。
        def wma_func(x):
            weights = np.arange(1, len(x) + 1)
            return np.average(x, weights=weights)

        # rolling(raw=False) 强制转换为 Series/DataFrame
        return prices.rolling(window=period).apply(wma_func, raw=False)


    def get_wma_components(self, Close_data, wma_short=5, wma_medium=10, wma_long=20, wma_trend=50):
        """计算WMA核心组件（S, M, L, T周期）"""
        
        wma_s = self._calculate_wma(Close_data, wma_short)
        wma_m = self._calculate_wma(Close_data, wma_medium)
        wma_l = self._calculate_wma(Close_data, wma_long)
        wma_t = self._calculate_wma(Close_data, wma_trend)
        
        return wma_s, wma_m, wma_l, wma_t

    def get_cross_and_alignment_signals(self, wma_s, wma_m, wma_l, wma_t):
        """生成交叉和多空排列信号（向量化）"""
        signals = {}
        prev_wma_s = wma_s.shift(1)
        prev_wma_l = wma_l.shift(1)
        
        # 基础金叉/死叉 (S vs L)
        golden_cross = (prev_wma_s <= prev_wma_l) & (wma_s > wma_l)
        death_cross = (prev_wma_s >= prev_wma_l) & (wma_s < wma_l)
        signals["golden_cross"] = golden_cross.astype(float) * self.signal_strength["golden_cross"]
        signals["death_cross"] = death_cross.astype(float) * self.signal_strength["death_cross"]

        # 多头排列 (S > M > L > T)
        bullish_alignment = (wma_s > wma_m) & (wma_m > wma_l) & (wma_l > wma_t)
        signals["bullish_alignment"] = bullish_alignment.astype(float) * self.signal_strength["bullish_alignment"]

        # 空头排列 (S < M < L < T)
        bearish_alignment = (wma_s < wma_m) & (wma_m < wma_l) & (wma_l < wma_t)
        signals["bearish_alignment"] = bearish_alignment.astype(float) * self.signal_strength["bearish_alignment"]

        return signals

    def get_price_wma_signals(self, close_prices, wma_s, wma_l, wma_m):
        """生成价格与WMA互动、粘合发散信号（向量化）"""
        signals = {}
        prev_price = close_prices.shift(1)
        prev_wma_s = wma_s.shift(1)
        prev_wma_l = wma_l.shift(1)
        
        # 价格突破WMA Short
        price_breakthrough = (prev_price <= prev_wma_s) & (close_prices > wma_s)
        signals["price_breakthrough"] = price_breakthrough.astype(float) * self.signal_strength["price_breakthrough"]

        # 价格回踩WMA Short (价格从上方跌破)
        price_pullback = (prev_price > prev_wma_s) & (close_prices <= wma_s)
        signals["price_pullback"] = price_pullback.astype(float) * self.signal_strength["price_pullback"]

        # 支撑确认 (价格在WMA上方且WMA上行)
        support_confirmation = (close_prices > wma_s) & (wma_s > prev_wma_s)
        signals["support_confirmation"] = support_confirmation.astype(float) * self.signal_strength["support_confirmation"]

        # 阻力确认 (价格在WMA下方且WMA下行)
        resistance_confirmation = (close_prices < wma_s) & (wma_s < prev_wma_s)
        signals["resistance_confirmation"] = resistance_confirmation.astype(float) * self.signal_strength["resistance_confirmation"]

        # 粘合/发散 (WMA S vs WMA L)
        wma_diff = np.abs(wma_s - wma_l) / wma_l.replace(0, 1) # 百分比差异
        prev_wma_diff = wma_diff.shift(1)
        
        # 发散 (差异增大)
        wma_divergence = (wma_diff > prev_wma_diff * 1.2)
        signals["wma_divergence"] = wma_divergence.astype(float) * self.signal_strength["wma_divergence"]

        # 收敛 (差异减小)
        wma_convergence = (wma_diff < prev_wma_diff * 0.8)
        signals["wma_convergence"] = wma_convergence.astype(float) * self.signal_strength["wma_convergence"]

        # 极值反转（价格与WMA距离过远后的反转）
        # 价格与WMA Short的距离（百分比）
        wma_distance_perc = (close_prices - wma_s) / wma_s.replace(0, 1)
        prev_wma_distance_perc = wma_distance_perc.shift(1)

        # 极值反转：距离超过0.05（5%）后，距离开始收缩
        extreme_reversal = ((wma_distance_perc > 0.05) & (wma_distance_perc < prev_wma_distance_perc)) | \
                           ((wma_distance_perc < -0.05) & (wma_distance_perc > prev_wma_distance_perc))
        signals["extreme_reversal"] = extreme_reversal.astype(float) * self.signal_strength["extreme_reversal"]

        # WMA斜率转正/负
        wma_slope = wma_s - prev_wma_s
        turn_positive = (wma_slope.shift(1) <= 0) & (wma_slope > 0)
        turn_negative = (wma_slope.shift(1) >= 0) & (wma_slope < 0)
        signals["turn_positive"] = turn_positive.astype(float) * self.signal_strength["turn_positive"]
        signals["turn_negative"] = turn_negative.astype(float) * self.signal_strength["turn_negative"]

        # 趋势加速/减速 (短期WMA的连续斜率)
        wma_accel_bull = (wma_s > wma_s.shift(1)) & (wma_s.shift(1) > wma_s.shift(2)) & (wma_s.shift(2) > wma_s.shift(3))
        wma_decel_bear = (wma_s < wma_s.shift(1)) & (wma_s.shift(1) < wma_s.shift(2)) & (wma_s.shift(2) < wma_s.shift(3))
        signals["trend_acceleration"] = wma_accel_bull.astype(float) * self.signal_strength["trend_acceleration"]
        signals["trend_deceleration"] = wma_decel_bear.astype(float) * self.signal_strength["trend_deceleration"]
        
        # 多空转换（短期WMA上穿中期WMA）
        bull_bear_transition = (wma_s.shift(1) <= wma_m.shift(1)) & (wma_s > wma_m)
        signals["bull_bear_transition"] = bull_bear_transition.astype(float) * self.signal_strength["bull_bear_transition"]
        
        # 双底/双顶（简化）：SMA短期线在低位/高位形成V/A形
        wma_s_rise = (wma_s > wma_s.shift(1))
        wma_s_fall = (wma_s < wma_s.shift(1))
        
        # 双底（W形）：跌 -> 涨 -> 跌 -> 涨
        double_bottom = wma_s_fall.shift(3) & wma_s_rise.shift(2) & wma_s_fall.shift(1) & wma_s_rise
        signals["wma_double_bottom"] = double_bottom.astype(float) * self.signal_strength["wma_double_bottom"]
        
        # 双顶（M形）：涨 -> 跌 -> 涨 -> 跌
        double_top = wma_s_rise.shift(3) & wma_s_fall.shift(2) & wma_s_rise.shift(1) & wma_s_fall
        signals["wma_double_top"] = double_top.astype(float) * self.signal_strength["wma_double_top"]

        return signals


    def get_divergence_signals(self, close_prices, wma_s, lookback_period=10):
        """生成顶底背离信号（简化向量化实现）"""
        signals = {}
        
        # 价格和WMA的N日内最高点和最低点
        price_high = close_prices.rolling(window=lookback_period).max()
        price_low = close_prices.rolling(window=lookback_period).min()
        wma_high = wma_s.rolling(window=lookback_period).max()
        wma_low = wma_s.rolling(window=lookback_period).min()
        
        # 顶背离: 价格当前高于前一个高点(5日前)，但WMA当前低于前一个高点
        price_new_high = close_prices > price_high.shift(5)
        wma_no_new_high = wma_s < wma_high.shift(5)
        top_divergence = price_new_high & wma_no_new_high
        signals["top_divergence"] = top_divergence.astype(float) * self.signal_strength["top_divergence"]
        
        # 底背离: 价格当前低于前一个低点(5日前)，但WMA当前高于前一个低点
        price_new_low = close_prices < price_low.shift(5)
        wma_no_new_low = wma_s > wma_low.shift(5)
        bottom_divergence = price_new_low & wma_no_new_low
        signals["bottom_divergence"] = bottom_divergence.astype(float) * self.signal_strength["bottom_divergence"]

        return signals

    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, enabled_signals=None, wma_short=5, wma_medium=10, wma_long=20, wma_trend=50):
        """
        整合启用的信号，生成最终的WMA信号强度矩阵
        
        参数:
            open_prices, high_prices, low_prices, close_prices, volume: pd.DataFrame，行=时间，列=标的
            enabled_signals: list，指定启用的信号名称
        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
    
        # 1. 如果没有指定启用的信号，使用所有信号
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 2. 计算WMA核心组件
        wma_s, wma_m, wma_l, wma_t = self.get_wma_components(Close_data, wma_short, wma_medium, wma_long, wma_trend)

        # 3. 获取所有信号矩阵
        cross_and_align_sigs = self.get_cross_and_alignment_signals(wma_s, wma_m, wma_l, wma_t)
        price_wma_sigs = self.get_price_wma_signals(Close_data, wma_s, wma_l, wma_m)
        divergence_sigs = self.get_divergence_signals(Close_data, wma_s)

        # 4. 合并所有信号字典
        all_signals_dict = {
            **cross_and_align_sigs, 
            **price_wma_sigs, 
            **divergence_sigs, 
        }

        # 5. 初始化并累加信号矩阵
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        for signal_name, signal_matrix in all_signals_dict.items():
            # 只处理启用的信号
            if signal_name in enabled_signals and signal_matrix is not None:
                buy_mask = signal_matrix > 0
                sell_mask = signal_matrix < 0
                
                # 累加信号的强度值
                sum_buy = sum_buy + signal_matrix.where(buy_mask, 0)
                sum_sell = sum_sell + signal_matrix.where(sell_mask, 0)

        # 6. 处理初始NaN行（将前N行置为0）
        # WMA计算需要最长wma_trend周期的数据
        skip_rows = wma_trend
        
        if len(sum_buy) > skip_rows:
             sum_buy.iloc[:skip_rows] = 0
             sum_sell.iloc[:skip_rows] = 0

        '''这里得到的分别是买和卖的矩阵，index是日期，column是标的，value是对应的强度值'''
        return sum_buy, sum_sell


    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name, date_index, stock_columns):
        """将信号矩阵转换为详细的记录列表"""
        
        stacked = signal_matrix.stack()
        # 过滤掉强度为 0 的信号
        non_zero_signals = stacked[stacked != 0]
        
        if len(non_zero_signals) == 0:
            return []
        
        # 直接构建DataFrame
        dates, stocks = zip(*non_zero_signals.index)
        
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


    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, wma_short=5, wma_medium=10, wma_long=20, wma_trend=50):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 计算WMA核心组件
        wma_s, wma_m, wma_l, wma_t = self.get_wma_components(Close_data, wma_short, wma_medium, wma_long, wma_trend)
        
        # 获取日期索引和股票列名
        date_index = Close_data.index
        stock_columns = Close_data.columns
        
        # 获取所有信号字典
        cross_and_align_sigs = self.get_cross_and_alignment_signals(wma_s, wma_m, wma_l, wma_t)
        price_wma_sigs = self.get_price_wma_signals(Close_data, wma_s, wma_l, wma_m)
        divergence_sigs = self.get_divergence_signals(Close_data, wma_s)

        signal_processors = [
            cross_and_align_sigs, 
            price_wma_sigs, 
            divergence_sigs, 
        ]
        
        # 统一处理所有信号记录
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name, date_index, stock_columns)
            for signal_dict in signal_processors
            for signal_name, signal_matrix in signal_dict.items()
        ))
        
        # 创建并返回排序后的DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      wma_short=5, wma_medium=10, wma_long=20, wma_trend=50, enabled_signals=None):
        """【新增方法】生成Multi-index格式的信号矩阵"""
        
        wma_s, wma_m, wma_l, wma_t = self.get_wma_components(Close_data, wma_short, wma_medium, wma_long, wma_trend)
        
        cross_and_align_sigs = self.get_cross_and_alignment_signals(wma_s, wma_m, wma_l, wma_t)
        price_wma_sigs = self.get_price_wma_signals(Close_data, wma_s, wma_l, wma_m)
        divergence_sigs = self.get_divergence_signals(Close_data, wma_s)
        
        all_signals_dict = {**cross_and_align_sigs, **price_wma_sigs, **divergence_sigs}
        
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
            
            if len(Close_data) > wma_trend:
                valid_start_date = Close_data.index[wma_trend]
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
    

    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume,
                            wma_short=5, wma_medium=10, wma_long=20, wma_trend=50,
                            wma_period=None):
        """
        将WMA的所有子信号拆分为独立的因子矩阵（每个信号一个矩阵）。
        兼容旧参数 wma_period：如果传入则统一覆盖 wma_short/medium/long/trend。
        """
        # 兼容旧调用：如果提供了 wma_period，则用它覆盖四个周期参数
        if wma_period is not None:
            wma_short = wma_medium = wma_long = wma_trend = wma_period
        
        # 1. 计算核心组件（返回4个WMA）
        wma_s, wma_m, wma_l, wma_t = self.get_wma_components(
            Close_data, wma_short, wma_medium, wma_long, wma_trend
        )
        
        # 2. 获取各类原子信号字典
        cross_and_align = self.get_cross_and_alignment_signals(wma_s, wma_m, wma_l, wma_t)
        price_wma = self.get_price_wma_signals(Close_data, wma_s, wma_l, wma_m)
        divergence = self.get_divergence_signals(Close_data, wma_s)

        # 3. 合并所有信号并处理初期不稳定数据 (2 * 最长周期)
        all_factors = {**cross_and_align, **price_wma, **divergence}
        min_valid = wma_trend * 2
        
        for name, df in all_factors.items():
            if df is not None:
                df = df.reindex_like(Close_data).fillna(0.0)
                df.iloc[:min_valid] = 0.0
                all_factors[name] = df
            else:
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
                
        return all_factors