import pandas as pd
import numpy as np

from itertools import chain

# ==========================================
# STOCH 随机指标技术面分析类
# ==========================================

'''
from strategys.技术面.STOCH import STOCH_Analyzer
trans = STOCH_Analyzer()
# 这里分别得到不同的买入卖出信号矩阵
signal_apo_buy,signal_apo_sell = trans.get_total_signal_matrix(Open_data,High_data,Low_data,Close_data,Volume)
signals_apo_search = trans.get_detailed_signals_dataframe(High_data,Low_data,Close_data)'''

class STOCH:
    """
    STOCH随机指标技术面综合分析类
    用于对多合约OHLCV数据进行向量化的STOCH指标计算和形态检测。
    """
    def __init__(self):
        # 信号强度定义（可以根据策略进行调整）
        self.signal_strength = {
            # 交叉信号
            "golden_cross": 0.5,             # 金叉：看涨
            "death_cross": -0.5,             # 死叉：看跌
            "overbought_golden_cross": 0.3,  # 超买区金叉：警惕但短期强势
            "oversold_death_cross": -0.3,    # 超卖区死叉：警惕但短期弱势
            
            # 区域突破与回踩
            "overbought_breakthrough": 0.6,  # 超买突破：趋势转换/加速
            "oversold_breakthrough": -0.6,   # 超卖突破：趋势转换/加速
            "overbought_pullback": -0.4,     # 超买回踩：趋势确认（短期回调）
            "oversold_pullback": 0.4,        # 超卖回踩：趋势确认（短期反弹）

            # 中轴信号
            "k_turn_positive": 0.4,          # %K上穿50：看涨
            "k_turn_negative": -0.4,         # %K下穿50：看跌
            # 新增 %D 线的 50 轴穿越信号强度
            "d_turn_positive": 0.45,         # %D上穿50：看涨 (D线较K线更平滑，信号强度可略高)
            "d_turn_negative": -0.45,        # %D下穿50：看跌
            
            # 背离与形态
            "bottom_divergence": 0.7,        # 底背离：强烈看涨反转
            "top_divergence": -0.7,          # 顶背离：强烈看跌反转
            "double_bottom": 0.5,            # 双底形态：底部反转
            "double_top": -0.5,              # 双顶形态：顶部反转
            
            # 其它信号
            "extreme_reversal_bull": 0.55,   # 极值反转（从低位向上）：看涨
            "extreme_reversal_bear": -0.55,  # 极值反转（从高位向下）：看跌
            "k_expansion": 0.3,              # %K放大：趋势加速
            "k_contraction": -0.3,           # %K缩小：趋势减弱
            "bull_bear_transition": 0.6,     # 多空转换（K线穿50）：趋势确认
        }

        self.continuous_signal_names = [
            "normalized_value",
            "kd_spread",
            "range_position",
        ]
        # 所有信号名称列表
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names

    def get_stoch_components(self, high_prices, low_prices, close_prices, 
                             k_period=14, d_period=3, smooth_k=3, smooth_d=3, **kwargs):
        """计算STOCH核心组件（%K, %D）"""
        
        # 1. 计算最高价和最低价的滚动窗口
        # LLV: Lowest Low in k_period
        llv = low_prices.rolling(window=k_period).min()  
        # HHV: Highest High in k_period
        hhv = high_prices.rolling(window=k_period).max()    
        
        # 2. 计算原始%K值 (R.S.V)
        # 避免除零错误，用 .replace([np.inf, -np.inf], np.nan) 替换，然后用 .fillna(0)
        range_diff = hhv - llv
        stoch_k_raw = 100 * (close_prices - llv) / range_diff
        stoch_k_raw = stoch_k_raw.replace([np.inf, -np.inf], np.nan).fillna(50.0)
        
        # 3. 计算原始%D值（%K的移动平均）
        stoch_d_raw = stoch_k_raw.rolling(window=d_period).mean()
        
        # 4. 计算平滑后的%K和%D
        stoch_k = stoch_k_raw.rolling(window=smooth_k).mean()  # 平滑%K
        stoch_d = stoch_d_raw.rolling(window=smooth_d).mean()  # 平滑%D
        
        # 填充NaN值：由于rolling计算会产生NaN，此处选择保留NaN，让后续信号计算决定是否填充，
        # 或者在信号计算时用fillna(0)转换为无信号。这里暂不填充。
        
        return stoch_k, stoch_d

    def cross_signals_detailed(self, stoch_k, stoch_d, overbought_level=80, oversold_level=20):
        """生成金叉/死叉及衍生信号的详细矩阵 (向量化)"""
        
        k_prev = stoch_k.shift(1)
        d_prev = stoch_d.shift(1)
        
        # 1. 基础金叉（K上穿D）和死叉（K下穿D）
        golden_cross = ((k_prev <= d_prev) & (stoch_k > stoch_d)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((k_prev >= d_prev) & (stoch_k < stoch_d)).astype(float) * self.signal_strength["death_cross"]
        
        # 2. 超买区金叉
        above_ob = (stoch_k > overbought_level)
        overbought_golden_cross = golden_cross.where(above_ob, 0) * (self.signal_strength["overbought_golden_cross"] / self.signal_strength["golden_cross"])

        # 3. 超卖区死叉
        below_os = (stoch_k < oversold_level)
        oversold_death_cross = death_cross.where(below_os, 0) * (self.signal_strength["oversold_death_cross"] / self.signal_strength["death_cross"])
        
        # 4. 极值反转
        extreme_reversal_bull = ((stoch_k < 5) & (stoch_k > k_prev)).astype(float) * self.signal_strength["extreme_reversal_bull"]
        extreme_reversal_bear = ((stoch_k > 95) & (stoch_k < k_prev)).astype(float) * self.signal_strength["extreme_reversal_bear"]

        # 最终信号矩阵中的NaN值用0填充
        return {
            "golden_cross": golden_cross.fillna(0),
            "death_cross": death_cross.fillna(0),
            "overbought_golden_cross": overbought_golden_cross.fillna(0),
            "oversold_death_cross": oversold_death_cross.fillna(0),
            "extreme_reversal_bull": extreme_reversal_bull.fillna(0),
            "extreme_reversal_bear": extreme_reversal_bear.fillna(0),
        }

    def breakthrough_pullback_signals(self, stoch_k, overbought_level=80, oversold_level=20):
        """生成超买/超卖突破和回踩信号 (向量化)"""

        k_prev = stoch_k.shift(1)
        
        # 1. 超买突破
        ob_breakthrough = ((k_prev <= overbought_level) & (stoch_k > overbought_level)).astype(float) * self.signal_strength["overbought_breakthrough"]
        
        # 2. 超卖突破 (下穿)
        os_breakthrough = ((k_prev >= oversold_level) & (stoch_k < oversold_level)).astype(float) * self.signal_strength["oversold_breakthrough"]
        
        # 3. 超买回踩 (从超买区回落到超买线以下)
        ob_pullback = ((k_prev > overbought_level) & (stoch_k <= overbought_level)).astype(float) * self.signal_strength["overbought_pullback"]
        
        # 4. 超卖回踩 (从超卖区回升到超卖线以上)
        os_pullback = ((k_prev < oversold_level) & (stoch_k >= oversold_level)).astype(float) * self.signal_strength["oversold_pullback"]
        
        return {
            "overbought_breakthrough": ob_breakthrough.fillna(0),
            "oversold_breakthrough": os_breakthrough.fillna(0),
            "overbought_pullback": ob_pullback.fillna(0),
            "oversold_pullback": os_pullback.fillna(0),
        }

    def midline_turn_signals(self, stoch_k, stoch_d):
        """生成中轴(50)转正/转负信号 (向量化)"""
        
        k_prev = stoch_k.shift(1)
        d_prev = stoch_d.shift(1)
        
        # 1. %K转正 (上穿50)
        k_turn_positive = ((k_prev <= 50) & (stoch_k > 50)).astype(float) * self.signal_strength["k_turn_positive"]
        
        # 2. %K转负 (下穿50)
        k_turn_negative = ((k_prev >= 50) & (stoch_k < 50)).astype(float) * self.signal_strength["k_turn_negative"]

        # 3. %D转正 (上穿50)
        d_turn_positive = ((d_prev <= 50) & (stoch_d > 50)).astype(float) * self.signal_strength["d_turn_positive"]
        
        # 4. %D转负 (下穿50)
        d_turn_negative = ((d_prev >= 50) & (stoch_d < 50)).astype(float) * self.signal_strength["d_turn_negative"]

        return {
            "k_turn_positive": k_turn_positive.fillna(0),
            "k_turn_negative": k_turn_negative.fillna(0),
            "d_turn_positive": d_turn_positive.fillna(0),
            "d_turn_negative": d_turn_negative.fillna(0),
        }

    def trend_signals_detailed(self, stoch_k):
        """生成趋势相关信号（扩张、收缩、转换）(向量化)"""
        
        k_prev1 = stoch_k.shift(1)
        k_prev2 = stoch_k.shift(2)
        
        # 1. %K放大 (偏离中轴50的幅度增加 1.2 倍)
        k_expansion = (np.abs(stoch_k - 50) > np.abs(k_prev1 - 50) * 1.2).astype(float) * self.signal_strength.get("k_expansion", 0)

        # 2. %K缩小 (偏离中轴50的幅度减小 0.8 倍)
        k_contraction = (np.abs(stoch_k - 50) < np.abs(k_prev1 - 50) * 0.8).astype(float) * self.signal_strength.get("k_contraction", 0)

        # 3. 简化多空转换 (从50下方连续2日后第3日上穿50)
        bull_bear_transition = ((k_prev2 < 50) & (k_prev1 < 50) & (stoch_k > 50)).astype(float) * self.signal_strength.get("bull_bear_transition", 0)
        
        return {
            "k_expansion": k_expansion.fillna(0),
            "k_contraction": k_contraction.fillna(0),
            "bull_bear_transition": bull_bear_transition.fillna(0),
        }


    def pattern_signals_detailed(self, stoch_k, overbought_level=80, oversold_level=20):
        """生成简化的形态信号（双顶/双底）(向量化)"""
        
        k_prev1 = stoch_k.shift(1)
        k_prev2 = stoch_k.shift(2)

        # 1. 简化双底形态 (3周期反转：谷-峰-谷, 且在超卖区)
        # 这是一个简化的3周期反转，不是严格的双底，但可向量化实现
        double_bottom = ((k_prev1 > k_prev2) & (k_prev1 > stoch_k) & 
                         (k_prev1 < oversold_level)).astype(float) * self.signal_strength.get("double_bottom", 0)

        # 2. 简化双顶形态 (3周期反转：峰-谷-峰, 且在超买区)
        double_top = ((k_prev1 < k_prev2) & (k_prev1 < stoch_k) & 
                      (k_prev1 > overbought_level)).astype(float) * self.signal_strength.get("double_top", 0)

        return {
            "double_bottom": double_bottom.fillna(0),
            "double_top": double_top.fillna(0),
        }
        
    def divergence_signals_detailed(self, stoch_k, close_prices, window=10, divergence_threshold=5):
        """生成简化的背离信号（10周期）(向量化)"""
        
        # 1. 计算价格和STOCH的近10周期最大值/最小值
        price_high = close_prices.rolling(window=window).max()
        price_low = close_prices.rolling(window=window).min()
        stoch_high = stoch_k.rolling(window=window).max()
        stoch_low = stoch_k.rolling(window=window).min()

        # 2. 简化的顶背离：当前价格在近期高点附近，但STOCH远离近期高点
        # 价格创新高 (当前价接近10日高点) 且 STOCH未创新高 (当前STOCH远低于10日高点)
        # 用当前价格与当前STOCH的相对位置进行判断
        
        # 顶背离: 价格升势，STOCH降势
        # 简化逻辑：当前价格 > 5天前的价格 AND 当前STOCH < 5天前的STOCH AND 当前STOCH > OB level
        price_prev5 = close_prices.shift(5)
        stoch_prev5 = stoch_k.shift(5)
        
        # 顶背离: 价格新高/平高, STOCH新低/平低 (与MACD.py中的简化逻辑类似)
        top_divergence = ((close_prices > price_prev5) & (stoch_k < stoch_prev5) & 
                          (stoch_k > 80)).astype(float) * self.signal_strength.get("top_divergence", 0)

        # 底背离: 价格新低/平低, STOCH新高/平高
        bottom_divergence = ((close_prices < price_prev5) & (stoch_k > stoch_prev5) & 
                             (stoch_k < 20)).astype(float) * self.signal_strength.get("bottom_divergence", 0)

        return {
            "top_divergence": top_divergence.fillna(0),
            "bottom_divergence": bottom_divergence.fillna(0),
        }

    def continuous_signals(self, stoch_k, stoch_d, lookback_period=20):
        """返回可用于排序/回归的连续随机指标特征。"""
        normalized_value = ((stoch_k - 50.0) / 50.0).clip(
            lower=-1.0, upper=1.0
        ).fillna(0.0)
        kd_spread = ((stoch_k - stoch_d) / 50.0).clip(
            lower=-1.0, upper=1.0
        ).fillna(0.0)

        stoch_min = stoch_k.rolling(window=lookback_period, min_periods=1).min()
        stoch_max = stoch_k.rolling(window=lookback_period, min_periods=1).max()
        stoch_range = (stoch_max - stoch_min).replace(0.0, np.nan)
        range_position = (
            (2.0 * (stoch_k - stoch_min) / stoch_range) - 1.0
        ).clip(lower=-1.0, upper=1.0).fillna(0.0)

        return {
            "normalized_value": normalized_value,
            "kd_spread": kd_spread,
            "range_position": range_position,
        }


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                enabled_signals=None, k_period=14, d_period=3, smooth_k=3, smooth_d=3):
        """
        整合启用的信号，生成最终的STOCH信号强度矩阵
        
        参数:
            high_prices, low_prices, close_prices: pd.DataFrame, OHLC价格矩阵
            volume: pd.DataFrame, 成交量矩阵 (未在STOCH中使用)
            enabled_signals: list, 指定启用的信号名称
        
        返回:
            sum_buy, sum_sell: pd.DataFrame, 同输入维度，值为信号强度（-1.0至1.0）
        """
        # 1. 如果没有指定启用的信号，使用所有信号
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 2. 初始化累加矩阵
        # 使用 close_prices 的索引和列名来初始化结果 DataFrame
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 3. 计算STOCH核心组件
        stoch_k, stoch_d = self.get_stoch_components(High_data, Low_data, Close_data, k_period, d_period, smooth_k, smooth_d)

        # 4. 获取所有信号矩阵
        cross_sigs = self.cross_signals_detailed(stoch_k, stoch_d)
        breakthrough_sigs = self.breakthrough_pullback_signals(stoch_k)
        midline_sigs = self.midline_turn_signals(stoch_k, stoch_d)
        trend_sigs = self.trend_signals_detailed(stoch_k)
        pattern_sigs = self.pattern_signals_detailed(stoch_k)
        divergence_sigs = self.divergence_signals_detailed(stoch_k, Close_data)

        # 合并所有信号字典
        all_signals_dict = {
            **cross_sigs, **breakthrough_sigs, **midline_sigs, 
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

        # 6. 移除由于滚动窗口导致的早期NaN行 (与原模板保持一致)
        # 这里设置为0，而不是填充，因为早期数据不足以形成信号
        sum_buy.iloc[:k_period + smooth_k + smooth_d] = 0.0
        sum_sell.iloc[:k_period + smooth_k + smooth_d] = 0.0
        
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
                                     k_period=14, d_period=3, smooth_k=3, smooth_d=3):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 1. 计算STOCH核心组件
        stoch_k, stoch_d = self.get_stoch_components(High_data, Low_data, Close_data, k_period, d_period, smooth_k, smooth_d)
        
        # 2. 定义信号处理器及其分类
        # 注意: _convert_signal_matrix_to_records 仅接受 signal_matrix 和 signal_name
        signal_processors = [
            self.cross_signals_detailed(stoch_k, stoch_d),
            self.breakthrough_pullback_signals(stoch_k),
            self.midline_turn_signals(stoch_k, stoch_d),
            self.trend_signals_detailed(stoch_k),
            self.pattern_signals_detailed(stoch_k),
            self.divergence_signals_detailed(stoch_k, Close_data)
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
                                      k_period=14, d_period=3, smooth_k=3, smooth_d=3, enabled_signals=None):
        """【新增方法】生成Multi-index格式的信号矩阵"""
        
        stoch_k, stoch_d = self.get_stoch_components(High_data, Low_data, Close_data, k_period, d_period, smooth_k, smooth_d)
        
        signal_processors = [
            self.cross_signals_detailed(stoch_k, stoch_d),
            self.breakthrough_pullback_signals(stoch_k),
            self.midline_turn_signals(stoch_k, stoch_d),
            self.trend_signals_detailed(stoch_k),
            self.pattern_signals_detailed(stoch_k),
            self.divergence_signals_detailed(stoch_k, Close_data)
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
            
            if len(Close_data) > k_period:
                valid_start_date = Close_data.index[k_period]
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
    
    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, k_period=14, d_period=3, smooth_k=3, smooth_d=3):
        """
        拆分 STOCH 的所有原子信号矩阵。
        """
        # 1. 计算核心组件 (注意参数要对应)
        k_line, d_line = self.get_stoch_components(High_data, Low_data, Close_data, k_period, d_period, smooth_k, smooth_d)
        
        # 2. 获取信号字典 (调用类中真实存在的方法)
        cross = self.cross_signals_detailed(k_line, d_line)
        breakthrough = self.breakthrough_pullback_signals(k_line)
        midline = self.midline_turn_signals(k_line, d_line)
        trend = self.trend_signals_detailed(k_line)
        pattern = self.pattern_signals_detailed(k_line)
        div = self.divergence_signals_detailed(k_line, Close_data)
        continuous = self.continuous_signals(k_line, d_line)

        # 3. 合并所有字典
        all_factors = {
            **cross,
            **breakthrough,
            **midline,
            **trend,
            **pattern,
            **div,
            **continuous,
        }
        
        # 4. 清洗数据
        # STOCH 需要 K周期 + 平滑周期
        skip_rows = k_period + smooth_k + smooth_d
        
        for name, df in all_factors.items():
            if df is not None:
                df = df.reindex_like(Close_data).fillna(0.0)
                if len(df) > skip_rows:
                    df.iloc[:skip_rows] = 0.0
                all_factors[name] = df
            else:
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
                
        return all_factors
