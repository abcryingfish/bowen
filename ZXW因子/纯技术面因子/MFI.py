import pandas as pd
import numpy as np
from itertools import chain

class MFI:
    """
    MFI (Money Flow Index)资金流量指标技术面综合分析类。
    实现核心MFI指标计算和多种MFI形态的向量化检测。
    """

    def __init__(self):
        # MFI信号强度定义
        self.signal_strength = {
            # 看涨信号
            "golden_cross": 0.5,
            "overbought_golden_cross": 0.7,
            "oversold_breakthrough": 0.6,
            "oversold_pullback": 0.5,
            "bottom_divergence": 0.8,
            "turn_positive": 0.4,
            "expansion_bull": 0.4,
            "double_bottom": 0.7,
            "triple_bottom": 0.9,
            "extreme_reversal_buy": 0.8,
            "trend_acceleration_bull": 0.5,
            "bull_bear_transition": 0.6,
            "money_flow_in": 0.4,
            
            # 看跌信号
            "death_cross": -0.5,
            "oversold_death_cross": -0.7,
            "overbought_breakthrough": -0.6,
            "overbought_pullback": -0.5,
            "top_divergence": -0.8,
            "turn_negative": -0.4,
            "contraction_bear": -0.4,
            "double_top": -0.7,
            "triple_top": -0.9,
            "extreme_reversal_sell": -0.8,
            "trend_acceleration_bear": -0.5,
            "money_flow_out": -0.4,
            
            # 中性/趋势减弱信号
            "stagnation": 0.1,  
            "contraction_bull": 0.2,
            "expansion_bear": -0.2,
            "convergence": 0.1,
            "divergence_mfi": 0.1,
            "trend_deceleration_bull": 0.3, 
            "trend_deceleration_bear": -0.3, 
            "volume_surge": 0.1, 
        }

        self.continuous_signal_names = [
            "normalized_value",
            "money_flow_bias",
            "volume_ratio",
        ]
        self.all_signals = list(self.signal_strength.keys()) + self.continuous_signal_names

    def get_mfi_components(self, high_prices, low_prices, close_prices, volume, mfi_period=14):
        """向量化计算MFI核心组件"""
        # 确保索引对齐
        df = pd.concat([high_prices, low_prices, close_prices, volume], axis=1, keys=['high', 'low', 'close', 'volume'])
        
        # 1. 典型价格 (TP)
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        # 2. 原始资金流量 (RMF)
        raw_money_flow = typical_price * df['volume']
        
        # 3. 价格上涨/下跌判断
        price_up = typical_price > typical_price.shift(1)
        price_down = typical_price < typical_price.shift(1)
        
        # 4. 正负资金流量
        positive_money_flow = raw_money_flow.where(price_up, 0)
        negative_money_flow = raw_money_flow.where(price_down, 0)
        
        # 5. 周期内正负资金流量总和
        pos_flow_sum = positive_money_flow.rolling(window=mfi_period, min_periods=mfi_period).sum()
        neg_flow_sum = negative_money_flow.rolling(window=mfi_period, min_periods=mfi_period).sum()
        
        # 6. 资金流量比率 (MR)
        money_flow_ratio = pos_flow_sum / (neg_flow_sum + 1e-6) 
        
        # 7. MFI指标
        mfi = 100 - (100 / (1 + money_flow_ratio))
        
        # 8. 成交量均线
        volume_ma = df['volume'].rolling(window=20, min_periods=1).mean()
        volume_ratio = df['volume'] / volume_ma
        
        return mfi, typical_price, raw_money_flow, positive_money_flow, negative_money_flow, pos_flow_sum, neg_flow_sum, money_flow_ratio, volume_ratio

    def single_bar_signals(self, mfi, pos_flow, neg_flow, overbought_level=80, oversold_level=20):
        """向量化检测基于单个/连续两根K线的MFI信号"""
        signals = {}
        mfi_prev = mfi.shift(1)
        
        # 辅助变量
        above_50 = mfi > 50
        below_50 = mfi < 50
        
        # 1. MFI金叉/死叉
        golden_cross = ((mfi_prev <= 50) & above_50).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((mfi_prev >= 50) & below_50).astype(float) * self.signal_strength["death_cross"]
        
        # 2. 复合信号
        overbought_golden = (golden_cross.abs() > 0) & (mfi > overbought_level)
        oversold_death = (death_cross.abs() > 0) & (mfi < oversold_level)
        signals["overbought_golden_cross"] = overbought_golden.astype(float) * self.signal_strength["overbought_golden_cross"]
        signals["oversold_death_cross"] = oversold_death.astype(float) * self.signal_strength["oversold_death_cross"]

        # 3. 突破/回踩
        signals["overbought_breakthrough"] = ((mfi_prev <= overbought_level) & (mfi > overbought_level)).astype(float) * self.signal_strength["overbought_breakthrough"]
        signals["oversold_breakthrough"] = ((mfi_prev >= oversold_level) & (mfi < oversold_level)).astype(float) * self.signal_strength["oversold_breakthrough"]
        signals["overbought_pullback"] = ((mfi_prev > overbought_level) & (mfi <= overbought_level)).astype(float) * self.signal_strength["overbought_pullback"]
        signals["oversold_pullback"] = ((mfi_prev < oversold_level) & (mfi >= oversold_level)).astype(float) * self.signal_strength["oversold_pullback"]
        
        # 4. 转正/转负
        signals["turn_positive"] = golden_cross.abs() * self.signal_strength["turn_positive"]
        signals["turn_negative"] = death_cross.abs() * self.signal_strength["turn_negative"]

        # 5. 放大/缩小
        mfi_diff_abs = (mfi - 50).abs()
        mfi_prev_diff_abs = (mfi_prev - 50).abs()
        mfi_expansion = (mfi_diff_abs > mfi_prev_diff_abs * 1.2)
        mfi_contraction = (mfi_diff_abs < mfi_prev_diff_abs * 0.8)
        signals["expansion_bull"] = mfi_expansion.where(mfi > 50, 0).astype(float) * self.signal_strength["expansion_bull"]
        signals["expansion_bear"] = mfi_expansion.where(mfi < 50, 0).astype(float) * self.signal_strength["expansion_bear"]
        signals["contraction_bull"] = mfi_contraction.where(mfi > 50, 0).astype(float) * self.signal_strength["contraction_bull"]
        signals["contraction_bear"] = mfi_contraction.where(mfi < 50, 0).astype(float) * self.signal_strength["contraction_bear"]
        
        # 6. 极值反转
        is_high_extreme_reversal = (mfi > 95) & (mfi < mfi_prev)
        is_low_extreme_reversal = (mfi < 5) & (mfi > mfi_prev)
        signals["extreme_reversal_buy"] = is_low_extreme_reversal.astype(float) * self.signal_strength["extreme_reversal_buy"]
        signals["extreme_reversal_sell"] = is_high_extreme_reversal.astype(float) * self.signal_strength["extreme_reversal_sell"]

        # 7. 形态
        signals["convergence"] = ((mfi_diff_abs < 5) & ((mfi_prev - 50).abs() < 5)).astype(float) * self.signal_strength["convergence"]
        signals["divergence_mfi"] = ((mfi_diff_abs > 30) & ((mfi_prev - 50).abs() > 30)).astype(float) * self.signal_strength["divergence_mfi"]
        signals["stagnation"] = ((mfi - mfi_prev).abs() < 1).astype(float) * self.signal_strength["stagnation"]

        # 8. 资金流向
        signals["money_flow_in"] = (above_50 & (pos_flow > neg_flow)).astype(float) * self.signal_strength["money_flow_in"]
        signals["money_flow_out"] = (below_50 & (neg_flow > pos_flow)).astype(float) * self.signal_strength["money_flow_out"]
        
        all_signals = {
            "golden_cross": golden_cross,
            "death_cross": death_cross,
            **signals
        }
        return all_signals

    def multi_bar_signals(self, mfi, overbought_level=80, oversold_level=20, divergence_threshold=5):
        """向量化检测基于3-4根K线的形态（双/三重顶底）"""
        signals = {}
        mfi_curr = mfi
        mfi_prev1 = mfi.shift(1)
        mfi_prev2 = mfi.shift(2)
        mfi_prev3 = mfi.shift(3)
        
        # 双底
        is_double_bottom = (mfi_prev2 < mfi_prev1) & (mfi_curr < mfi_prev1) & \
                           (np.abs(mfi_prev2 - mfi_curr) < divergence_threshold) & (mfi_prev1 < oversold_level)
        signals["double_bottom"] = is_double_bottom.astype(float) * self.signal_strength["double_bottom"]

        # 双顶
        is_double_top = (mfi_prev2 > mfi_prev1) & (mfi_curr > mfi_prev1) & \
                        (np.abs(mfi_prev2 - mfi_curr) < divergence_threshold) & (mfi_prev1 > overbought_level)
        signals["double_top"] = is_double_top.astype(float) * self.signal_strength["double_top"]

        # 三重底
        is_triple_bottom = (mfi_prev3 < mfi_prev2) & (mfi_prev1 < mfi_prev2) & (mfi_curr < mfi_prev2) & \
                           (np.abs(mfi_prev3 - mfi_prev1) < divergence_threshold) & \
                           (np.abs(mfi_prev1 - mfi_curr) < divergence_threshold) & (mfi_prev2 < oversold_level)
        signals["triple_bottom"] = is_triple_bottom.astype(float) * self.signal_strength["triple_bottom"]

        # 三重顶
        is_triple_top = (mfi_prev3 > mfi_prev2) & (mfi_prev1 > mfi_prev2) & (mfi_curr > mfi_prev2) & \
                        (np.abs(mfi_prev3 - mfi_prev1) < divergence_threshold) & \
                        (np.abs(mfi_prev1 - mfi_curr) < divergence_threshold) & (mfi_prev2 > overbought_level)
        signals["triple_top"] = is_triple_top.astype(float) * self.signal_strength["triple_top"]

        return signals

    def divergence_signals(self, mfi, close_prices, overbought_level=80, oversold_level=20, lookback_period=10):
        """向量化检测顶底背离形态（价格和MFI的比较）"""
        signals = {}
        
        # 【关键修复】确保只使用与 MFI 对齐的数值列，避免 Timestamp 与 int 比较报错
        # 1. 筛选数值列
        valid_columns = mfi.columns
        # 确保 close_prices 包含 mfi 的列 (取交集)
        target_cols = valid_columns.intersection(close_prices.columns)
        
        if len(target_cols) == 0:
            # 如果没有匹配的列，说明列名对不上，返回空信号
            return {}
            
        # 使用过滤后的价格数据进行计算
        prices_calc = close_prices[target_cols]
        mfi_calc = mfi[target_cols]

        # 2. 计算滚动最大/最小值
        close_high = prices_calc.rolling(window=lookback_period, min_periods=5).max()
        close_low = prices_calc.rolling(window=lookback_period, min_periods=5).min()
        mfi_high = mfi_calc.rolling(window=lookback_period, min_periods=5).max()
        mfi_low = mfi_calc.rolling(window=lookback_period, min_periods=5).min()

        # 3. MFI顶背离（价格创新高但MFI未创新高）
        is_top_divergence = (prices_calc > close_high.shift(5)) & \
                            (mfi_calc < mfi_high.shift(5)) & \
                            (mfi_calc > overbought_level)
        signals["top_divergence"] = is_top_divergence.astype(float) * self.signal_strength["top_divergence"]

        # 4. MFI底背离（价格创新低但MFI未创新低）
        is_bottom_divergence = (prices_calc < close_low.shift(5)) & \
                               (mfi_calc > mfi_low.shift(5)) & \
                               (mfi_calc < oversold_level)
        signals["bottom_divergence"] = is_bottom_divergence.astype(float) * self.signal_strength["bottom_divergence"]

        return signals

    def trend_signals(self, mfi):
        """向量化检测趋势加速/减速/多空转换"""
        signals = {}
        mfi_prev1 = mfi.shift(1)
        mfi_prev2 = mfi.shift(2)
        
        # 趋势加速
        is_accel_bull = (mfi > mfi_prev1) & (mfi_prev1 > mfi_prev2) & (mfi > 50)
        is_accel_bear = (mfi < mfi_prev1) & (mfi_prev1 < mfi_prev2) & (mfi < 50)
        signals["trend_acceleration_bull"] = is_accel_bull.astype(float) * self.signal_strength["trend_acceleration_bull"]
        signals["trend_acceleration_bear"] = is_accel_bear.astype(float) * self.signal_strength["trend_acceleration_bear"]

        # 趋势减速
        is_decel_bull = (mfi < mfi_prev1) & (mfi_prev1 < mfi_prev2) & (mfi > 50)
        is_decel_bear = (mfi > mfi_prev1) & (mfi_prev1 > mfi_prev2) & (mfi < 50)
        signals["trend_deceleration_bull"] = is_decel_bull.astype(float) * self.signal_strength["trend_deceleration_bull"]
        signals["trend_deceleration_bear"] = is_decel_bear.astype(float) * self.signal_strength["trend_deceleration_bear"]

        # 多空转换
        is_bull_bear_transition = (mfi_prev2 < 50) & (mfi_prev1 < 50) & (mfi > 50)
        signals["bull_bear_transition"] = is_bull_bear_transition.astype(float) * self.signal_strength["bull_bear_transition"]

        return signals
    
    def volume_surge_signal(self, volume_ratio, volume_surge_threshold=1.5):
        """向量化检测放量信号"""
        is_volume_surge = (volume_ratio > volume_surge_threshold).astype(float) * self.signal_strength["volume_surge"]
        return {"volume_surge": is_volume_surge}

    def continuous_signals(self, mfi, pos_flow, neg_flow, volume_ratio):
        """返回可直接用于排序/回归的连续 MFI 特征。"""
        normalized_value = ((mfi - 50.0) / 50.0).clip(lower=-1.0, upper=1.0).fillna(0.0)
        flow_total = (pos_flow + neg_flow).replace(0.0, np.nan)
        money_flow_bias = ((pos_flow - neg_flow) / flow_total).clip(lower=-1.0, upper=1.0).fillna(0.0)
        volume_ratio_value = (volume_ratio - 1.0).clip(lower=-1.0, upper=1.0).fillna(0.0)
        return {
            "normalized_value": normalized_value,
            "money_flow_bias": money_flow_bias,
            "volume_ratio": volume_ratio_value,
        }

    # ==========================================
    # 修复后的 get_factor_matrices
    # ==========================================
    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, mfi_period=14):
        """
        拆分MFI的所有原子信号矩阵。
        """
        # 1. 计算组件
        mfi, _, _, pos, neg, _, _, _, vol_ratio = self.get_mfi_components(High_data, Low_data, Close_data, Volume, mfi_period)
        
        # 2. 获取信号字典
        single = self.single_bar_signals(mfi, pos, neg)
        multi = self.multi_bar_signals(mfi)
        div = self.divergence_signals(mfi, Close_data)
        trend = self.trend_signals(mfi)
        vol_surge = self.volume_surge_signal(vol_ratio)
        continuous = self.continuous_signals(mfi, pos, neg, vol_ratio)

        # 3. 合并所有字典
        all_factors = {**single, **multi, **div, **trend, **vol_surge, **continuous}
        
        # 4. 清洗数据 (reindex_like, fillna, 去除冷启动期)
        skip_rows = mfi_period * 2
        
        for name, df in all_factors.items():
            if df is not None:
                # 确保索引完全对齐并填充NaN
                df = df.reindex_like(Close_data).fillna(0.0)
                # 清除指标计算初期的不稳定数据
                if len(df) > skip_rows:
                    df.iloc[:skip_rows] = 0.0
                all_factors[name] = df
            else:
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
                
        return all_factors

    # 保留原有的辅助方法 (以防被调用)
    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name):
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
    
    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, enabled_signals=None):
         # 此处仅为保留原有接口，具体逻辑在 get_factor_matrices 中已实现拆分
         return self.get_factor_matrices(Open_data, High_data, Low_data, Close_data, Volume)
