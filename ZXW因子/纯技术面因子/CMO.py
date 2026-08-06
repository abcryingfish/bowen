import pandas as pd
import numpy as np
from itertools import chain




'''from strategys.技术面.CMO import CMO
# 实例化APO类
trans = CMO()

# 1. 获取汇总的买卖信号强度矩阵
# 使用默认参数 fast_period=12, slow_period=26
signal_apo_buy, signal_apo_sell = trans.get_total_signal_matrix(
    Close_data
)

# 2. 获取详细的信号DataFrame（包含信号名称、方向和强度）
signals_apo_detailed = trans.get_detailed_signals_dataframe(Close_data

)'''

# 这里是对CMO指标的解释和公式的撰写，方便阅读
'''CMO的参数，对应优缺点

CMO：Chande Momentum Oscillator (钱德动量震荡指标)
定义：CMO是一种动量指标，衡量在指定周期内，上涨动量与下跌动量的净差额占总动量的百分比。CMO值的范围在-100到+100之间。

计算公式：
周期： N (默认为14)

1. 价格变化：
   $Change = Price_t - Price_{t-1}$

2. 上涨总和 (Up Sum, SU): N周期内所有上涨日价格变化的绝对值之和。
   $SU = \sum_{i=1}^{N} \max(0, Change_i)$

3. 下跌总和 (Down Sum, SD): N周期内所有下跌日价格变化的绝对值之和。
   $SD = \sum_{i=1}^{N} \max(0, -Change_i)$

4. CMO 线 (CMO Line):
   $CMO = 100 \times \frac{SU - SD}{SU + SD}$

优点：
1. **纯粹动量**：CMO仅关注上涨和下跌的绝对动量，能清晰显示多空力量的对比。
2. **归一化**：数值始终在-100到+100之间，易于判断超买（+50以上）和超卖（-50以下）。
3. **趋势力度**：CMO越接近100或-100，表示当前的趋势力度越强。

缺点：
1. **波动性**：作为动量指标，波动性较大，容易在超买超卖区产生频繁信号。
2. **滞后性**：基于N期价格累计，对于短线交易仍有一定的滞后。
3. **金叉/死叉不唯一**：除了零轴穿越，通常还会引入CMO自身的移动平均线（CMO SMA）来产生交叉信号。
'''


class CMO:
    def __init__(self):
        # 定义信号强度 (根据信号的可靠性设定初始权重)
        self.signal_strength = {
            # 核心趋势和交叉信号
            "golden_cross": 0.5,                                # CMO上穿CMO SMA（趋势转强）
            "death_cross": -0.5,                                # CMO下穿CMO SMA（趋势转弱）
            "zero_line_breakthrough": 0.6,                      # CMO上穿零轴（动量转多）
            "zero_line_pullback": -0.6,                         # CMO下穿零轴（动量转空）
            "overbought_breakthrough": 0.7,                     # CMO上破+50（强势超买启动）
            "oversold_breakthrough": -0.7,                      # CMO下破-50（强势超卖启动）
            # 反转/极值信号
            "top_divergence": -0.8,                             # 顶背离 (强看跌反转)
            "bottom_divergence": 0.8,                           # 底背离 (强看涨反转)
            "extreme_reversal_top": -0.6,                       # 极值反转 (超买区反转)
            "extreme_reversal_bottom": 0.6,                     # 极值反转 (超卖区反转)
            "trend_acceleration": 0.5,                          # 趋势加速（CMO斜率增强）
            "trend_deceleration": -0.5,                         # 趋势减速（CMO斜率减弱）
            "overbought_signal": -0.3,                          # 超买警告 (+50以上)
            "oversold_signal": 0.3,                             # 超卖机会 (-50以下)
            "strong_zone": 0.4,                                 # 强势区间 (+25以上)
            "weak_zone": -0.4,                                  # 弱势区间 (-25以下)
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

        # 所有信号名称列表
        self.all_signals = list(self.signal_strength.keys())

    def get_cmo_components(self, price_matrix, cmo_period=14, sma_period=5):
        """计算CMO核心组件 (上涨总和, 下跌总和, CMO线, CMO SMA)"""
        
        # 1. 价格变化
        price_change = price_matrix.diff()
        
        # 2. 上涨和下跌
        up_change = price_change.where(price_change > 0, 0)
        down_change = -price_change.where(price_change < 0, 0) # 绝对值

        # 3. 滚动总和 (Rolling Sum)
        up_sum = up_change.rolling(window=cmo_period).sum()
        down_sum = down_change.rolling(window=cmo_period).sum()
        
        # 4. CMO 线
        total_movement = up_sum + down_sum
        # 避免除以零，在 total_movement != 0 的地方计算CMO，否则为0
        cmo_line = 100 * (up_sum - down_sum) / total_movement
        
        # 5. CMO SMA (CMO的平滑线，通常用于交叉信号)
        cmo_sma = cmo_line.rolling(window=sma_period).mean()

        # 填充初始NaN值 (由于rolling计算)
        cmo_line = cmo_line.fillna(method='ffill').fillna(0)
        cmo_sma = cmo_sma.fillna(method='ffill').fillna(0)

        return cmo_line, cmo_sma

    def cross_signals(self, cmo_line, cmo_sma):
        """CMO线与CMO SMA的交叉信号"""
        
        cmo_prev = cmo_line.shift(1)
        sma_prev = cmo_sma.shift(1)
        
        # 1. 金叉: CMO上穿CMO SMA
        golden_cross = ((cmo_prev <= sma_prev) & (cmo_line > cmo_sma)).astype(float) * self.signal_strength["golden_cross"]
        
        # 2. 死叉: CMO下穿CMO SMA
        death_cross = ((cmo_prev >= sma_prev) & (cmo_line < cmo_sma)).astype(float) * self.signal_strength["death_cross"]
        
        return {
            "golden_cross": golden_cross.fillna(0),
            "death_cross": death_cross.fillna(0)
        }

    def extreme_signals(self, cmo_line):
        """零轴、超买超卖和区间信号"""
        
        cmo_prev = cmo_line.shift(1)
        
        # 1. 零轴突破（上穿）
        zero_break_up = ((cmo_prev <= 0) & (cmo_line > 0)).astype(float) * self.signal_strength["zero_line_breakthrough"]
        
        # 2. 零轴回踩（下穿）
        zero_break_down = ((cmo_prev >= 0) & (cmo_line < 0)).astype(float) * self.signal_strength["zero_line_pullback"]

        # 3. 超买突破 (上破+50)
        overbought_breakthrough = ((cmo_prev <= 50) & (cmo_line > 50)).astype(float) * self.signal_strength["overbought_breakthrough"]
        
        # 4. 超卖突破 (下破-50)
        oversold_breakthrough = ((cmo_prev >= -50) & (cmo_line < -50)).astype(float) * self.signal_strength["oversold_breakthrough"]
        
        # 5. 超买信号 (+50以上)
        overbought_signal = (cmo_line > 50).astype(float) * self.signal_strength["overbought_signal"]

        # 6. 超卖信号 (-50以下)
        oversold_signal = (cmo_line < -50).astype(float) * self.signal_strength["oversold_signal"]

        # 7. 强势区间 (+25以上)
        strong_zone = (cmo_line > 25).astype(float) * self.signal_strength["strong_zone"]

        # 8. 弱势区间 (-25以下)
        weak_zone = (cmo_line < -25).astype(float) * self.signal_strength["weak_zone"]

        return {
            "zero_line_breakthrough": zero_break_up.fillna(0),
            "zero_line_pullback": zero_break_down.fillna(0),
            "overbought_breakthrough": overbought_breakthrough.fillna(0),
            "oversold_breakthrough": oversold_breakthrough.fillna(0),
            "overbought_signal": overbought_signal.fillna(0),
            "oversold_signal": oversold_signal.fillna(0),
            "strong_zone": strong_zone.fillna(0),
            "weak_zone": weak_zone.fillna(0)
        }

    def momentum_reversal_signals(self, cmo_line):
        """趋势加速/减速和极值反转信号"""
        
        cmo_slope = cmo_line.diff()
        cmo_slope_prev = cmo_slope.shift(1)
        cmo_prev = cmo_line.shift(1)
        
        # 1. 趋势加速/减速（CMO斜率变化）
        is_acceleration_bull = (cmo_slope > cmo_slope_prev) & (cmo_line > 0)
        trend_acceleration = is_acceleration_bull.astype(float) * self.signal_strength["trend_acceleration"]
        
        is_deceleration_bear = (cmo_slope < cmo_slope_prev) & (cmo_line < 0)
        trend_deceleration = is_deceleration_bear.astype(float) * self.signal_strength["trend_deceleration"]

        # 2. 极值反转（从极端值区域开始反向移动）
        # 顶极值反转：CMO > 75 且开始下降
        extreme_reversal_top = ((cmo_prev > 75) & (cmo_line < cmo_prev)).astype(float) * self.signal_strength["extreme_reversal_top"]
        # 底极值反转：CMO < -75 且开始上升
        extreme_reversal_bottom = ((cmo_prev < -75) & (cmo_line > cmo_prev)).astype(float) * self.signal_strength["extreme_reversal_bottom"]

        return {
            "trend_acceleration": trend_acceleration.fillna(0),
            "trend_deceleration": trend_deceleration.fillna(0),
            "extreme_reversal_top": extreme_reversal_top.fillna(0),
            "extreme_reversal_bottom": extreme_reversal_bottom.fillna(0)
        }


    def divergence_signals(self, cmo_line, close_prices_matrix, lookback_period=10):
        """CMO顶底背离信号 (价格与CMO线)"""
        
        # 最近 lookback_period 内的最高价/最低价和CMO的最大值/最小值
        price_high = close_prices_matrix.rolling(lookback_period).max()
        price_low = close_prices_matrix.rolling(lookback_period).min()
        cmo_max = cmo_line.rolling(lookback_period).max()
        cmo_min = cmo_line.rolling(lookback_period).min()

        current_price = close_prices_matrix
        current_cmo = cmo_line
        
        # 1. 顶背离 (Top Divergence): 价格创新高，CMO未创新高 (且在正值区)
        price_peak = (current_price > price_high.shift(1))
        cmo_not_peak = (current_cmo < cmo_max.shift(1) * 0.98) # 价格创新高，CMO未达到前高
        is_top_divergence = (price_peak & cmo_not_peak & (current_cmo > 0)).astype(float) * self.signal_strength["top_divergence"]
        
        # 2. 底背离 (Bottom Divergence): 价格创新低，CMO未创新低 (且在负值区)
        price_trough = (current_price < price_low.shift(1))
        cmo_not_trough = (current_cmo > cmo_min.shift(1) * 0.98) # 价格创新低，CMO未达到前低
        is_bottom_divergence = (price_trough & cmo_not_trough & (current_cmo < 0)).astype(float) * self.signal_strength["bottom_divergence"]
        
        return {
            "top_divergence": is_top_divergence.fillna(0),
            "bottom_divergence": is_bottom_divergence.fillna(0)
        }

    def double_pattern_signals(self, cmo_line, lookback=20):
        """双顶和双底形态识别"""
        
        # 使用滚动窗口寻找局部极值
        local_max = cmo_line.rolling(5, center=True).max()
        local_min = cmo_line.rolling(5, center=True).min()
        
        # 是否为局部高点/低点
        is_peak = (cmo_line == local_max)
        is_trough = (cmo_line == local_min)
        
        # 双底：两个相近的低点（误差<5%），且都在超卖区（<-40）
        cmo_prev_low = cmo_line.shift(lookback)
        double_bottom_cond = (
            is_trough & 
            is_trough.shift(lookback) &
            (abs(cmo_line - cmo_prev_low) / (abs(cmo_prev_low) + 1e-8) < 0.05) &
            (cmo_line < -40) &
            (cmo_line > cmo_line.rolling(lookback*2).min().shift(1))  # 开始反弹
        )
        double_bottom = double_bottom_cond.astype(float) * self.signal_strength["double_bottom"]
        
        # 双顶：两个相近的高点（误差<5%），且都在超买区（>40）
        cmo_prev_high = cmo_line.shift(lookback)
        double_top_cond = (
            is_peak & 
            is_peak.shift(lookback) &
            (abs(cmo_line - cmo_prev_high) / (abs(cmo_prev_high) + 1e-8) < 0.05) &
            (cmo_line > 40) &
            (cmo_line < cmo_line.rolling(lookback*2).max().shift(1))  # 开始回落
        )
        double_top = double_top_cond.astype(float) * self.signal_strength["double_top"]
        
        return {
            "double_bottom": double_bottom.fillna(0),
            "double_top": double_top.fillna(0)
        }

    def triple_pattern_signals(self, cmo_line, lookback=15):
        """三重顶和三重底形态识别"""
        
        # 使用滚动窗口寻找局部极值
        local_max = cmo_line.rolling(5, center=True).max()
        local_min = cmo_line.rolling(5, center=True).min()
        
        is_peak = (cmo_line == local_max)
        is_trough = (cmo_line == local_min)
        
        # 三重底：三个相近的低点
        low1 = cmo_line.shift(lookback*2)
        low2 = cmo_line.shift(lookback)
        low3 = cmo_line
        
        triple_bottom_cond = (
            is_trough & 
            is_trough.shift(lookback) & 
            is_trough.shift(lookback*2) &
            (abs(low1 - low2) / (abs(low2) + 1e-8) < 0.05) &
            (abs(low2 - low3) / (abs(low3) + 1e-8) < 0.05) &
            (low3 < -35) &
            (low3 > cmo_line.rolling(lookback*3).min().shift(1))  # 开始反弹
        )
        triple_bottom = triple_bottom_cond.astype(float) * self.signal_strength["triple_bottom"]
        
        # 三重顶：三个相近的高点
        high1 = cmo_line.shift(lookback*2)
        high2 = cmo_line.shift(lookback)
        high3 = cmo_line
        
        triple_top_cond = (
            is_peak & 
            is_peak.shift(lookback) & 
            is_peak.shift(lookback*2) &
            (abs(high1 - high2) / (abs(high2) + 1e-8) < 0.05) &
            (abs(high2 - high3) / (abs(high3) + 1e-8) < 0.05) &
            (high3 > 35) &
            (high3 < cmo_line.rolling(lookback*3).max().shift(1))  # 开始回落
        )
        triple_top = triple_top_cond.astype(float) * self.signal_strength["triple_top"]
        
        return {
            "triple_bottom": triple_bottom.fillna(0),
            "triple_top": triple_top.fillna(0)
        }

    def head_shoulders_signals(self, cmo_line, lookback=20):
        """头肩顶和头肩底形态识别"""
        
        local_max = cmo_line.rolling(5, center=True).max()
        local_min = cmo_line.rolling(5, center=True).min()
        
        is_peak = (cmo_line == local_max)
        is_trough = (cmo_line == local_min)
        
        # 头肩底：左肩(低) - 头部(更低) - 右肩(低)
        left_shoulder = cmo_line.shift(lookback*2)
        head = cmo_line.shift(lookback)
        right_shoulder = cmo_line
        
        head_shoulders_bottom_cond = (
            is_trough & 
            is_trough.shift(lookback) & 
            is_trough.shift(lookback*2) &
            (head < left_shoulder) &  # 头部最低
            (head < right_shoulder) &
            (abs(left_shoulder - right_shoulder) / (abs(left_shoulder) + 1e-8) < 0.1) &  # 两肩相近
            (head < -40) &
            (right_shoulder > head)  # 右肩开始抬升
        )
        head_shoulders_bottom = head_shoulders_bottom_cond.astype(float) * self.signal_strength["head_shoulders_bottom"]
        
        # 头肩顶：左肩(高) - 头部(更高) - 右肩(高)
        head_shoulders_top_cond = (
            is_peak & 
            is_peak.shift(lookback) & 
            is_peak.shift(lookback*2) &
            (head > left_shoulder) &  # 头部最高
            (head > right_shoulder) &
            (abs(left_shoulder - right_shoulder) / (abs(left_shoulder) + 1e-8) < 0.1) &  # 两肩相近
            (head > 40) &
            (right_shoulder < head)  # 右肩开始下降
        )
        head_shoulders_top = head_shoulders_top_cond.astype(float) * self.signal_strength["head_shoulders_top"]
        
        return {
            "head_shoulders_bottom": head_shoulders_bottom.fillna(0),
            "head_shoulders_top": head_shoulders_top.fillna(0)
        }

    def wedge_signals(self, cmo_line, lookback=20):
        """楔形形态识别（上升楔形和下降楔形）"""
        
        # 计算CMO的局部高点和低点趋势
        highs = cmo_line.rolling(5).max()
        lows = cmo_line.rolling(5).min()
        
        # 高点趋势和低点趋势（使用线性回归斜率）
        high_slope = highs.diff(lookback) / lookback
        low_slope = lows.diff(lookback) / lookback
        
        # 上升楔形：高点和低点都上升，但高点斜率 < 低点斜率（收敛）
        rising_wedge_cond = (
            (high_slope > 0) & 
            (low_slope > 0) &
            (high_slope < low_slope * 0.8) &  # 收敛特征
            (cmo_line > 30)  # 在超买区
        )
        rising_wedge = rising_wedge_cond.astype(float) * self.signal_strength["rising_wedge"]
        
        # 下降楔形：高点和低点都下降，但高点斜率 > 低点斜率（收敛）
        falling_wedge_cond = (
            (high_slope < 0) & 
            (low_slope < 0) &
            (abs(high_slope) < abs(low_slope) * 0.8) &  # 收敛特征
            (cmo_line < -30)  # 在超卖区
        )
        falling_wedge = falling_wedge_cond.astype(float) * self.signal_strength["falling_wedge"]
        
        return {
            "rising_wedge": rising_wedge.fillna(0),
            "falling_wedge": falling_wedge.fillna(0)
        }

    def triangle_signals(self, cmo_line, lookback=20):
        """三角形态识别（收敛和发散）"""
        
        # 计算波动范围
        highs = cmo_line.rolling(5).max()
        lows = cmo_line.rolling(5).min()
        volatility = highs - lows
        
        # 收敛：波动范围逐渐缩小
        vol_trend = volatility.diff(lookback)
        
        triangle_convergence_cond = (
            (vol_trend < -1) &  # 波动范围明显缩小
            (volatility < volatility.shift(lookback) * 0.7) &
            (abs(cmo_line) < 40)  # 在中间区域
        )
        triangle_convergence = triangle_convergence_cond.astype(float) * self.signal_strength["triangle_convergence"]
        
        # 发散：波动范围逐渐扩大
        triangle_divergence_cond = (
            (vol_trend > 1) &  # 波动范围明显扩大
            (volatility > volatility.shift(lookback) * 1.3) &
            (abs(cmo_line) > 30)  # 离开中间区域
        )
        triangle_divergence = triangle_divergence_cond.astype(float) * self.signal_strength["triangle_divergence"]
        
        return {
            "triangle_convergence": triangle_convergence.fillna(0),
            "triangle_divergence": triangle_divergence.fillna(0)
        }

    def channel_signals(self, cmo_line, lookback=20):
        """通道突破和回撤信号"""
        
        # 使用移动平均和标准差构建通道
        ma = cmo_line.rolling(lookback).mean()
        std = cmo_line.rolling(lookback).std()
        
        upper_channel = ma + 1.5 * std
        lower_channel = ma - 1.5 * std
        
        cmo_prev = cmo_line.shift(1)
        
        # 向上突破通道
        channel_breakthrough_cond = (
            (cmo_prev <= upper_channel.shift(1)) &
            (cmo_line > upper_channel) &
            (cmo_line > 0)
        )
        channel_breakthrough = channel_breakthrough_cond.astype(float) * self.signal_strength["channel_breakthrough"]
        
        # 回撤到通道内（从突破位置回落）
        channel_pullback_cond = (
            (cmo_prev >= upper_channel.shift(1)) &
            (cmo_line < upper_channel) &
            (cmo_line > ma)  # 但仍在中轴上方
        )
        channel_pullback = channel_pullback_cond.astype(float) * self.signal_strength["channel_pullback"]
        
        return {
            "channel_breakthrough": channel_breakthrough.fillna(0),
            "channel_pullback": channel_pullback.fillna(0)
        }

    def confirmation_signals(self, cmo_line, close_prices, lookback=5):
        """突破和回撤确认信号"""
        
        # 价格突破关键位置后的确认
        price_high = close_prices.rolling(lookback*2).max().shift(lookback)
        price_low = close_prices.rolling(lookback*2).min().shift(lookback)
        
        cmo_prev = cmo_line.shift(lookback)
        
        # 突破确认：价格创新高且CMO也在上升
        breakthrough_confirmation_cond = (
            (close_prices > price_high) &
            (cmo_line > cmo_prev) &
            (cmo_line > 20)
        )
        breakthrough_confirmation = breakthrough_confirmation_cond.astype(float) * self.signal_strength["breakthrough_confirmation"]
        
        # 回撤确认：价格回调但CMO保持强势
        pullback_confirmation_cond = (
            (close_prices < close_prices.shift(3)) &  # 短期回调
            (close_prices > price_low * 1.02) &  # 但未跌破支撑
            (cmo_line > 0) &  # CMO仍为正
            (cmo_line > cmo_line.shift(lookback) * 0.8)  # CMO保持相对强势
        )
        pullback_confirmation = pullback_confirmation_cond.astype(float) * self.signal_strength["pullback_confirmation"]
        
        return {
            "breakthrough_confirmation": breakthrough_confirmation.fillna(0),
            "pullback_confirmation": pullback_confirmation.fillna(0)
        }

    def transition_signals(self, cmo_line, lookback=30):
        """牛熊转换信号"""
        
        # 长期趋势判断
        long_ma = cmo_line.rolling(lookback).mean()
        short_ma = cmo_line.rolling(lookback//3).mean()
        
        # 牛熊转换：短期均线上穿长期均线，且从负值区进入正值区
        bull_bear_transition_cond = (
            (short_ma.shift(1) <= long_ma.shift(1)) &
            (short_ma > long_ma) &
            (cmo_line > 0) &
            (cmo_line.shift(lookback) < -20)  # 之前处于弱势
        )
        bull_bear_transition = bull_bear_transition_cond.astype(float) * self.signal_strength["bull_bear_transition"]
        
        return {
            "bull_bear_transition": bull_bear_transition.fillna(0)
        }

    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, enabled_signals=None, cmo_period=14, sma_period=5):
        """
        整合启用的信号，生成最终的CMO信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            enabled_signals: list，指定启用的信号名称。如果为None则启用所有信号
            cmo_period: int, CMO计算周期
            sma_period: int, CMO SMA计算周期

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
        
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 只使用Close_data
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 1. 计算CMO核心组件
        cmo_line, cmo_sma = self.get_cmo_components(Close_data, cmo_period, sma_period)

        # 2. 获取所有信号矩阵（包括新实现的复杂形态）
        cross = self.cross_signals(cmo_line, cmo_sma)
        extreme = self.extreme_signals(cmo_line)
        momentum_rev = self.momentum_reversal_signals(cmo_line)
        divergence = self.divergence_signals(cmo_line, Close_data)
        double_patterns = self.double_pattern_signals(cmo_line)
        triple_patterns = self.triple_pattern_signals(cmo_line)
        head_shoulders = self.head_shoulders_signals(cmo_line)
        wedge = self.wedge_signals(cmo_line)
        triangle = self.triangle_signals(cmo_line)
        channel = self.channel_signals(cmo_line)
        confirmation = self.confirmation_signals(cmo_line, Close_data)
        transition = self.transition_signals(cmo_line)

        # 合并所有信号字典
        all_signals_dict = {
            **cross, **extreme, **momentum_rev, **divergence,
            **double_patterns, **triple_patterns, **head_shoulders,
            **wedge, **triangle, **channel, **confirmation, **transition
        }

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
        min_valid_rows = cmo_period
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

    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, cmo_period=14, sma_period=5):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 1. 计算CMO核心组件（只使用Close_data）
        cmo_line, cmo_sma = self.get_cmo_components(Close_data, cmo_period, sma_period)
        
        # 获取日期索引和股票列名
        date_index = Close_data.index
        stock_columns = Close_data.columns
        
        # 2. 信号处理器列表（包括所有新实现的信号）
        signal_processors = [
            self.cross_signals(cmo_line, cmo_sma),
            self.extreme_signals(cmo_line),
            self.momentum_reversal_signals(cmo_line),
            self.divergence_signals(cmo_line, Close_data),
            self.double_pattern_signals(cmo_line),
            self.triple_pattern_signals(cmo_line),
            self.head_shoulders_signals(cmo_line),
            self.wedge_signals(cmo_line),
            self.triangle_signals(cmo_line),
            self.channel_signals(cmo_line),
            self.confirmation_signals(cmo_line, Close_data),
            self.transition_signals(cmo_line)
        ]
        
        # 3. 统一处理所有信号记录
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name, date_index, stock_columns)
            for processor in signal_processors
            for signal_name, signal_matrix in processor.items()
        ))
        
        # 4. 创建并返回排序后的DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
            
            # 同样屏蔽初始无效行
            min_valid_rows = cmo_period
            if len(Close_data) > min_valid_rows:
                 # 过滤掉日期早于有效期的信号
                signals_df = signals_df[signals_df['Date'] >= Close_data.index[min_valid_rows]]
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      enabled_signals=None, cmo_period=14, sma_period=5, 
                                      exclude_complex_patterns=False):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        这是一个通用方法，可以被其他类似的技术指标类复用。
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，OHLC数据
            enabled_signals: list，指定启用的信号名称，默认None表示使用所有已实现的信号
            cmo_period: int, CMO计算周期
            sma_period: int, CMO SMA计算周期
            exclude_complex_patterns: bool, 是否排除复杂形态信号，默认False（包含所有信号）
        
        返回:
            signals_multi_index: pd.DataFrame
                - Index: MultiIndex (Date, Contract)
                    - Date: int32格式（如 20240101）
                    - Contract: string格式
                - Columns: 各个信号名称
                - Values: float32格式，对应信号的强度值（保留正负和0）
        
        使用示例:
            # 获取所有信号
            df = trans.get_multi_index_signal_matrix(
                Open_data, High_data, Low_data, Close_data, Volume
            )
            
            # 获取特定信号
            df = trans.get_multi_index_signal_matrix(
                Open_data, High_data, Low_data, Close_data, Volume,
                enabled_signals=['golden_cross', 'death_cross', 'top_divergence']
            )
            
            # 查询特定日期和合约的信号
            df.loc[(20240101, 'AAPL'), :]
            
            # 查询特定信号的所有记录（非零）
            df[df['golden_cross'] != 0]['golden_cross']
        """
        
        # 1. 计算CMO核心组件
        cmo_line, cmo_sma = self.get_cmo_components(Close_data, cmo_period, sma_period)
        
        # 2. 获取所有信号矩阵（包括新实现的复杂形态）
        cross = self.cross_signals(cmo_line, cmo_sma)
        extreme = self.extreme_signals(cmo_line)
        momentum_rev = self.momentum_reversal_signals(cmo_line)
        divergence = self.divergence_signals(cmo_line, Close_data)
        double_patterns = self.double_pattern_signals(cmo_line)
        triple_patterns = self.triple_pattern_signals(cmo_line)
        head_shoulders = self.head_shoulders_signals(cmo_line)
        wedge = self.wedge_signals(cmo_line)
        triangle = self.triangle_signals(cmo_line)
        channel = self.channel_signals(cmo_line)
        confirmation = self.confirmation_signals(cmo_line, Close_data)
        transition = self.transition_signals(cmo_line)
        
        # 3. 合并所有信号字典
        all_signals_dict = {
            **cross, **extreme, **momentum_rev, **divergence,
            **double_patterns, **triple_patterns, **head_shoulders,
            **wedge, **triangle, **channel, **confirmation, **transition
        }
        
        # 4. 过滤信号
        # 定义复杂形态信号列表（用于可选过滤）
        complex_pattern_names = [
            'double_bottom', 'double_top', 'triple_bottom', 'triple_top', 
            'head_shoulders_bottom', 'head_shoulders_top', 'rising_wedge', 'falling_wedge', 
            'triangle_convergence', 'triangle_divergence', 'channel_breakthrough', 
            'channel_pullback', 'breakthrough_confirmation', 'pullback_confirmation',
            'bull_bear_transition'
        ]
        
        if exclude_complex_patterns:
            # 排除复杂形态（如果需要的话）
            all_signals_dict = {
                k: v for k, v in all_signals_dict.items() 
                if k not in complex_pattern_names
            }
        
        if enabled_signals is not None:
            # 只保留启用的信号
            all_signals_dict = {
                k: v for k, v in all_signals_dict.items() 
                if k in enabled_signals
            }
        
        # 5. 将每个信号矩阵(Date × Contract)转换为Multi-index Series
        # 然后合并成一个DataFrame
        signal_series_list = []
        signal_names = []
        
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_matrix is not None:
                # 将矩阵stack成Multi-index Series
                # stack()会自动创建MultiIndex (Date, Contract)
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
            
            # 填充NaN为0（某些信号可能在某些(Date, Contract)组合上为空）
            signals_multi_index = signals_multi_index.fillna(0)
            
            # 7. 屏蔽初始无效行
            min_valid_rows = cmo_period
            if len(Close_data) > min_valid_rows:
                # 获取有效的起始日期
                valid_start_date = Close_data.index[min_valid_rows]
                # 过滤掉早于有效日期的数据
                signals_multi_index = signals_multi_index[
                    signals_multi_index.index.get_level_values(0) >= valid_start_date
                ]
            
            # 8. 转换数据类型
            # Date索引转换为int32格式（如果原始是datetime，转换为YYYYMMDD格式）
            current_dates = signals_multi_index.index.get_level_values(0)
            
            # 检查日期类型并转换
            if pd.api.types.is_datetime64_any_dtype(current_dates):
                # datetime转int32 (YYYYMMDD格式)
                date_int32 = current_dates.strftime('%Y%m%d').astype('int32')
            elif pd.api.types.is_integer_dtype(current_dates):
                # 已经是整数，直接转换为int32
                date_int32 = current_dates.astype('int32')
            else:
                # 其他类型，尝试转换
                date_int32 = pd.to_datetime(current_dates).strftime('%Y%m%d').astype('int32')
            
            # Contract索引转换为string格式
            contract_str = signals_multi_index.index.get_level_values(1).astype('string')
            
            # 重建索引
            new_index = pd.MultiIndex.from_arrays(
                [date_int32, contract_str],
                names=['Date', 'Contract']
            )
            signals_multi_index.index = new_index
            
            # 9. 设置Index名称，增强可读性
            signals_multi_index.index.names = ['Date', 'Contract']
            
            # Values转换为float类型
            signals_multi_index = signals_multi_index.astype('float32')
            
        else:
            # 如果没有信号，创建空DataFrame
            signals_multi_index = pd.DataFrame(
                columns=signal_names if signal_names else [],
                index=pd.MultiIndex.from_tuples([], names=['Date', 'Contract'])
            )
            # 设置正确的数据类型
            signals_multi_index.index = signals_multi_index.index.set_levels(
                signals_multi_index.index.levels[0].astype('int32'), level=0
            ) if len(signals_multi_index.index.levels) > 0 else signals_multi_index.index
            
        return signals_multi_index
    


    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, cmo_period=14, sma_period=5):
        """
        完全拆分CMO的头肩顶、楔形、三角形等所有形态信号。
        """
        line, sma = self.get_cmo_components(Close_data, cmo_period, sma_period)
        
        cross = self.cross_signals(line, sma)
        extreme = self.extreme_signals(line)
        mom_rev = self.momentum_reversal_signals(line)
        div = self.divergence_signals(line, Close_data)
        double_p = self.double_pattern_signals(line)
        triple_p = self.triple_pattern_signals(line)
        hs = self.head_shoulders_signals(line)
        wedge = self.wedge_signals(line)
        triangle = self.triangle_signals(line)
        channel = self.channel_signals(line)
        conf = self.confirmation_signals(line, Close_data)
        trans = self.transition_signals(line)

        all_factors = {**cross, **extreme, **mom_rev, **div, **double_p, **triple_p, 
                       **hs, **wedge, **triangle, **channel, **conf, **trans}
        
        for name in all_factors:
            all_factors[name].iloc[:cmo_period * 2] = 0.0
                
        return all_factors