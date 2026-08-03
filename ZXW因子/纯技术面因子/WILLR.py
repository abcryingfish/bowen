import pandas as pd
import numpy as np
from itertools import chain



'''
from strategys.技术面.WILLR import WILLR
trans = WILLR()
# 这里分别得到不同的买入卖出信号矩阵
signal_apo_buy,signal_apo_sell = trans.get_total_signal_matrix(Open_data,High_data,Low_data,Close_data,Volume)
signals_apo_search = trans.get_detailed_signals_dataframe(High_data,Low_data,Close_data)'''


# =============================================================================
# WILLR：Williams %R（威廉指标）
# WILLR = (Highest High - Close) / (Highest High - Lowest Low) * (-100)
#
# 原理：测量收盘价相对于周期内最高价和最低价范围的位置，反映市场超买/超卖状态。
#
# WILLR区间：
#   -20 以上：超买区（Overbought Zone），可能出现顶部反转。
#   -80 以下：超卖区（Oversold Zone），可能出现底部反转。
#   -50：中轴线，通常被视为多空分界线。
#
# 优点：对市场转折点的反应灵敏，能有效指示超买超卖状态。
# 缺点：在震荡行情中容易发出频繁的假信号；信号具有滞后性，通常在价格形成顶/底后才确认。
# =============================================================================


class WILLR:
    def __init__(self):
        # 定义所有信号的强度和方向（正值看涨，负值看跌）
        self.signal_strength = {
            # 基础信号 (强度中等)
            "golden_cross": 0.5,           # WILLR上穿-50中轴
            "death_cross": -0.5,           # WILLR下穿-50中轴
            "overbought_zone": -0.3,       # 持续超买（警告）
            "oversold_zone": 0.3,          # 持续超卖（机会）
            "turn_positive": 0.4,          # WILLR斜率转正
            "turn_negative": -0.4,         # WILLR斜率转负
            "extreme_reversal": 0.7,       # 极值反转（-90以下反弹 或 -10以上回落）

            # 突破与回踩 (强度较高)
            "overbought_breakthrough": -0.6, # 跌破-20线（卖出信号）
            "oversold_breakthrough": 0.6,    # 突破-80线（买入信号）
            "overbought_pullback": -0.5,     # 回踩-20线（空头确认）
            "oversold_pullback": 0.5,        # 回踩-80线（多头确认）

            # 背离信号 (强度最高)
            "top_divergence": -0.9,        # 顶背离：价格新高，WILLR未新高
            "bottom_divergence": 0.9,      # 底背离：价格新低，WILLR未新低
            
            # 趋势与形态 (强度中高)
            "willr_divergence": 0.5,       # WILLR趋势发散（趋势加速）
            "willr_convergence": -0.5,     # WILLR趋势收敛（趋势减弱）
            "trend_acceleration_bull": 0.5, # 趋势加速（多头）
            "trend_deceleration_bear": -0.5, # 趋势减速（空头）
            "bull_bear_transition": 0.7,    # 多空转换（从熊转牛）
            
            # 形态（此处仅实现向量化相对容易的）
            # 注意：复杂的形态如头肩顶/底、楔形等难以完全向量化，需简化或使用专门的形态识别库。
            # 这里简化为基于WILLR的极值形态
            "willr_double_bottom": 0.8,
            "willr_double_top": -0.8,
            # 将原文件中的"粘合"、"发散"等重复/模糊信号简化为上述已定义的信号，避免重复定义。
        }

        self.all_signals = list(self.signal_strength.keys())

    def get_willr_components(self, High_data, Low_data, Close_data, willr_period=14, willr_smooth=3):
        """计算WILLR核心组件（willr_raw, willr_smooth）"""
        
        # 计算周期内最高价和最低价（向量化）
        highest_high = High_data.rolling(window=willr_period).max()
        lowest_low = Low_data.rolling(window=willr_period).min()
        
        # WILLR = (Highest High - Close) / (Highest High - Lowest Low) * (-100)
        range_diff = highest_high - lowest_low
        # 避免除以零，将分母为零的地方替换为1（此时分子也为0，WILLR结果为0）
        range_diff_safe = range_diff.replace(0, 1) 
        
        willr_raw = ((highest_high - Close_data) / range_diff_safe) * (-100)
        
        # 计算平滑WILLR值
        willr_smooth = willr_raw.rolling(window=willr_smooth).mean()
        
        return willr_raw, willr_smooth

    def get_cross_and_zone_signals(self, willr_smooth):
        """生成交叉、超买超卖、突破、回踩等信号（向量化）"""
        signals = {}
        prev_willr = willr_smooth.shift(1)
        
        # 基础金叉/死叉 (中轴-50)
        golden_cross = (prev_willr <= -50) & (willr_smooth > -50)
        death_cross = (prev_willr >= -50) & (willr_smooth < -50)
        signals["golden_cross"] = golden_cross.astype(float) * self.signal_strength["golden_cross"]
        signals["death_cross"] = death_cross.astype(float) * self.signal_strength["death_cross"]

        # 超买/超卖区域 (-20 / -80)
        signals["overbought_zone"] = (willr_smooth > -20).astype(float) * self.signal_strength["overbought_zone"]
        signals["oversold_zone"] = (willr_smooth < -80).astype(float) * self.signal_strength["oversold_zone"]

        # 超买突破（跌破-20）/ 超卖突破（突破-80）
        overbought_breakthrough = (prev_willr >= -20) & (willr_smooth < -20)
        oversold_breakthrough = (prev_willr <= -80) & (willr_smooth > -80)
        signals["overbought_breakthrough"] = overbought_breakthrough.astype(float) * self.signal_strength["overbought_breakthrough"]
        signals["oversold_breakthrough"] = oversold_breakthrough.astype(float) * self.signal_strength["oversold_breakthrough"]
        
        # 超买回踩（反弹至-20）/ 超卖回踩（回落至-80）
        overbought_pullback = (prev_willr < -20) & (willr_smooth >= -20)
        oversold_pullback = (prev_willr > -80) & (willr_smooth <= -80)
        signals["overbought_pullback"] = overbought_pullback.astype(float) * self.signal_strength["overbought_pullback"]
        signals["oversold_pullback"] = oversold_pullback.astype(float) * self.signal_strength["oversold_pullback"]

        # 趋势转正/转负 (斜率变化)
        willr_slope = willr_smooth - prev_willr
        turn_positive = (willr_slope.shift(1) <= 0) & (willr_slope > 0)
        turn_negative = (willr_slope.shift(1) >= 0) & (willr_slope < 0)
        signals["turn_positive"] = turn_positive.astype(float) * self.signal_strength["turn_positive"]
        signals["turn_negative"] = turn_negative.astype(float) * self.signal_strength["turn_negative"]
        
        # 极值反转 (-10以上向下 或 -90以下向上)
        extreme_reversal = ((willr_smooth > -10) & (willr_smooth < prev_willr)) | \
                           ((willr_smooth < -90) & (willr_smooth > prev_willr))
        signals["extreme_reversal"] = extreme_reversal.astype(float) * self.signal_strength["extreme_reversal"]

        return signals

    def get_divergence_signals(self, close_prices, willr_smooth, lookback_period=10):
        """生成顶底背离信号（简化向量化实现）"""
        signals = {}
        
        # 简化版背离：价格N日内创新高/低，WILLR N日内未创新高/低
        
        # 价格和WILLR的N日内最高点和最低点
        price_high = close_prices.rolling(window=lookback_period).max()
        price_low = close_prices.rolling(window=lookback_period).min()
        willr_high = willr_smooth.rolling(window=lookback_period).max()
        willr_low = willr_smooth.rolling(window=lookback_period).min()
        
        # 顶背离: 价格当前高于前一个高点(5日前)，但WILLR当前低于前一个高点
        # 价格创新高 (与N日前相比)
        price_new_high = close_prices > price_high.shift(5)
        # WILLR未创新高 (与N日前相比)
        willr_no_new_high = willr_smooth < willr_high.shift(5)
        
        top_divergence = price_new_high & willr_no_new_high & (willr_smooth > -50) # 发生在看涨区域更可靠
        signals["top_divergence"] = top_divergence.astype(float) * self.signal_strength["top_divergence"]
        
        # 底背离: 价格当前低于前一个低点(5日前)，但WILLR当前高于前一个低点
        # 价格创新低
        price_new_low = close_prices < price_low.shift(5)
        # WILLR未创新低
        willr_no_new_low = willr_smooth > willr_low.shift(5)
        
        bottom_divergence = price_new_low & willr_no_new_low & (willr_smooth < -50) # 发生在看跌区域更可靠
        signals["bottom_divergence"] = bottom_divergence.astype(float) * self.signal_strength["bottom_divergence"]

        return signals

    def get_trend_and_form_signals(self, willr_smooth):
        """生成趋势加速/减速/形态信号（向量化）"""
        signals = {}
        
        # WILLR与中轴(-50)的距离
        willr_distance = np.abs(willr_smooth + 50)
        prev_distance = willr_distance.shift(1)
        
        # WILLR趋势发散（趋势加速）- 距离中轴越来越远
        willr_divergence = (willr_distance > prev_distance * 1.2) 
        signals["willr_divergence"] = willr_divergence.astype(float) * self.signal_strength["willr_divergence"]
        
        # WILLR趋势收敛（趋势减弱）- 距离中轴越来越近
        willr_convergence = (willr_distance < prev_distance * 0.8)
        signals["willr_convergence"] = willr_convergence.astype(float) * self.signal_strength["willr_convergence"]
        
        # 趋势加速（多头）：WILLR连续上升（3天），且在-50以上
        willr_rise = (willr_smooth > willr_smooth.shift(1))
        trend_acceleration_bull = willr_rise & willr_rise.shift(1) & (willr_smooth > -50)
        signals["trend_acceleration_bull"] = trend_acceleration_bull.astype(float) * self.signal_strength["trend_acceleration_bull"]
        
        # 趋势减速（空头）：WILLR连续下降（3天），且在-50以下
        willr_fall = (willr_smooth < willr_smooth.shift(1))
        trend_deceleration_bear = willr_fall & willr_fall.shift(1) & (willr_smooth < -50)
        signals["trend_deceleration_bear"] = trend_deceleration_bear.astype(float) * self.signal_strength["trend_deceleration_bear"]
        
        # 多空转换（熊转牛）：WILLR从-50以下突破-50
        bull_bear_transition = (willr_smooth.shift(2) < -50) & (willr_smooth.shift(1) < -50) & (willr_smooth > -50)
        signals["bull_bear_transition"] = bull_bear_transition.astype(float) * self.signal_strength["bull_bear_transition"]
        
        # 双底/双顶（简化）：最近5日内WILLR出现两个低点/高点，且第二个点更接近中轴
        # 寻找WILLR的局部极值（需要更精确的峰谷检测，此处仅为示例）
        # 简化为：在超卖区(-80)附近形成W形反转
        is_w_bottom = (willr_smooth.shift(3) < -80) & (willr_smooth.shift(2) > -80) & \
                      (willr_smooth.shift(1) < willr_smooth.shift(3)) & (willr_smooth > willr_smooth.shift(1))
        signals["willr_double_bottom"] = is_w_bottom.astype(float) * self.signal_strength["willr_double_bottom"]
        
        # 简化为：在超买区(-20)附近形成M形反转
        is_m_top = (willr_smooth.shift(3) > -20) & (willr_smooth.shift(2) < -20) & \
                   (willr_smooth.shift(1) > willr_smooth.shift(3)) & (willr_smooth < willr_smooth.shift(1))
        signals["willr_double_top"] = is_m_top.astype(float) * self.signal_strength["willr_double_top"]

        return signals


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, enabled_signals=None, willr_period=14, willr_smooth=3):
        """
        整合启用的信号，生成最终的WILLR信号强度矩阵
        
        参数:
            open_prices, high_prices, low_prices, close_prices, volume: pd.DataFrame，行=时间，列=标的
            enabled_signals: list，指定启用的信号名称
        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
    
        # 1. 如果没有指定启用的信号，使用所有信号
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 2. 计算WILLR核心组件
        willr_raw, willr_smooth = self.get_willr_components(High_data, Low_data, Close_data, willr_period, willr_smooth)

        # 3. 获取所有信号矩阵
        cross_and_zone_sigs = self.get_cross_and_zone_signals(willr_smooth)
        divergence_sigs = self.get_divergence_signals(Close_data, willr_smooth)
        trend_and_form_sigs = self.get_trend_and_form_signals(willr_smooth)

        # 4. 合并所有信号字典
        all_signals_dict = {
            **cross_and_zone_sigs, 
            **divergence_sigs, 
            **trend_and_form_sigs
        }

        # 5. 初始化并累加信号矩阵
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        for signal_name, signal_matrix in all_signals_dict.items():
            # 只处理启用的信号
            if signal_name in enabled_signals and signal_matrix is not None:
                # 信号强度 > 0 为买入信号
                buy_mask = signal_matrix > 0
                # 信号强度 < 0 为卖出信号
                sell_mask = signal_matrix < 0
                
                # 累加信号的强度值（正值累加给买入，负值累加给卖出）
                sum_buy = sum_buy + signal_matrix.where(buy_mask, 0)
                sum_sell = sum_sell + signal_matrix.where(sell_mask, 0)

        # 6. 处理初始NaN行（将前N行置为0）
        # WILLR计算需要 willr_period + willr_smooth 左右的周期，这里保守设置为30行
        skip_rows = max(willr_period, 30)
        
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


    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, willr_period=14, willr_smooth=3):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 计算WILLR核心组件
        willr_raw, willr_smooth = self.get_willr_components(High_data, Low_data, Close_data, willr_period, willr_smooth)
        
        # 获取日期索引和股票列名
        date_index = Close_data.index
        stock_columns = Close_data.columns
        
        # 获取所有信号字典
        cross_and_zone_sigs = self.get_cross_and_zone_signals(willr_smooth)
        divergence_sigs = self.get_divergence_signals(Close_data, willr_smooth)
        trend_and_form_sigs = self.get_trend_and_form_signals(willr_smooth)

        signal_processors = [
            cross_and_zone_sigs, 
            divergence_sigs, 
            trend_and_form_sigs
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
                                      willr_period=14, willr_smooth=3, enabled_signals=None):
        """【新增方法】生成Multi-index格式的信号矩阵"""
        
        willr_raw, willr_smooth_line = self.get_willr_components(High_data, Low_data, Close_data, willr_period, willr_smooth)
        
        cross_and_zone_sigs = self.get_cross_and_zone_signals(willr_smooth_line)
        divergence_sigs = self.get_divergence_signals(Close_data, willr_smooth_line)
        trend_and_form_sigs = self.get_trend_and_form_signals(willr_smooth_line)
        
        all_signals_dict = {**cross_and_zone_sigs, **divergence_sigs, **trend_and_form_sigs}
        
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
            
            if len(Close_data) > willr_period:
                valid_start_date = Close_data.index[willr_period]
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
    

    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, willr_period=14, willr_smooth=3):
            """
            拆分 WILLR 的所有原子信号矩阵。
            """
            # 1. 计算组件
            _, willr_smooth_line = self.get_willr_components(High_data, Low_data, Close_data, willr_period, willr_smooth)
            
            # 2. 获取信号字典 (调用类中真实存在的方法)
            cross_zone = self.get_cross_and_zone_signals(willr_smooth_line)
            div = self.get_divergence_signals(Close_data, willr_smooth_line)
            trend = self.get_trend_and_form_signals(willr_smooth_line)

            # 3. 合并所有字典
            all_factors = {**cross_zone, **div, **trend}
            
            # 4. 清洗数据 (去除前N个无效数据, fillna)
            # 计算需要跳过的行数 (保守估计)
            skip_rows = willr_period + willr_smooth
            
            for name, df in all_factors.items():
                if df is not None:
                    # 确保索引对齐并填充 NaN
                    df = df.reindex_like(Close_data).fillna(0.0)
                    # 清除指标计算初期的不稳定数据
                    if len(df) > skip_rows:
                        df.iloc[:skip_rows] = 0.0
                    all_factors[name] = df
                else:
                    all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
                    
            return all_factors