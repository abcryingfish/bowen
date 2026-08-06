import pandas as pd
import numpy as np
from itertools import chain




'''from strategys.技术面.DEMA import DEMA
# 实例化APO类
trans = DEMA()

# 1. 获取汇总的买卖信号强度矩阵
# 使用默认参数 fast_period=12, slow_period=26
signal_apo_buy, signal_apo_sell = trans.get_total_signal_matrix(
    Close_data
)

# 2. 获取详细的信号DataFrame（包含信号名称、方向和强度）
signals_apo_detailed = trans.get_detailed_signals_dataframe(Close_data

)


get_multi_index_signal_matrix
'''


# 这里是对DEMA指标的解释和公式的撰写，方便阅读
'''DEMA的参数，对应优缺点

DEMA：Double Exponential Moving Average (双重指数移动平均线)
定义：DEMA是一种旨在减少传统EMA滞后性的移动平均线。它通过将单重EMA的滞后部分移除，使得其反应速度更快，更紧密地跟随价格。

计算公式：
周期： N (默认为20)
指数平滑系数： $\alpha = 2 / (N + 1)$

1. 单重EMA (EMA):
   $EMA(N) = \text{EMA}(Price, N)$

2. EMA的EMA (EMA\_of\_EMA):
   $EMA\_of\_EMA(N) = \text{EMA}(EMA(N), N)$

3. DEMA 线 (DEMA Line): 
   $DEMA(N) = 2 \times EMA(N) - EMA\_of\_EMA(N)$

优点：
1. **低滞后性**：DEMA显著减少了传统EMA的滞后性，能更快地响应价格变化，提供更及时的信号。
2. **平滑性**：在保持快速反应的同时，仍具有移动平均线的平滑特性，过滤掉部分噪音。
3. **趋势追踪**：在强趋势市场中能提供清晰的支撑和阻力线。

缺点：
1. **过度拟合**：由于滞后性极低，DEMA在震荡或盘整市场中可能过于敏感，产生频繁的假信号。
2. **计算要求高**：需要计算两次EMA，对数据量和计算性能要求略高。
3. **缺乏超买超卖界限**：DEMA本身是价格的平滑线，不像震荡指标那样有明确的超买/超卖阈值，判断超买超卖需要依赖与价格或EMA的相对偏离。
'''


class DEMA:
    def __init__(self):
        # 定义信号强度 (根据信号的可靠性设定初始权重)
        self.signal_strength = {
            # 核心趋势和交叉信号
            "golden_cross": 0.6,                                # DEMA上穿零轴（趋势转多）
            "death_cross": -0.6,                                # DEMA下穿零轴（趋势转空）
            "trend_reversal": 0.7,                              # DEMA斜率发生转折
            "trend_acceleration": 0.5,                          # DEMA斜率加速（趋势加强）
            "trend_deceleration": -0.5,                         # DEMA斜率减速（趋势减弱）
            "extreme_reversal_top": -0.6,                       # DEMA远离EMA后反转（顶部警告）
            "extreme_reversal_bottom": 0.6,                     # DEMA远离EMA后反转（底部机会）
            "top_divergence": -0.8,                             # 顶背离 (强看跌反转)
            "bottom_divergence": 0.8,                           # 底背离 (强看涨反转)
            "support_breakthrough": -0.7,                       # 价格跌破DEMA支撑线
            "resistance_breakthrough": 0.7,                     # 价格突破DEMA阻力线
            "momentum_exhaustion": -0.5,                        # 动能衰竭（二阶动量反转）
            "momentum_recovery": 0.5,                           # 动能恢复
            # 复杂形态信号
            "zero_line_breakthrough": 0.5,                      # 零轴突破
            "zero_line_pullback": -0.5,                         # 零轴回调
            "double_bottom": 0.7,                               # 双底形态
            "double_top": -0.7,                                 # 双顶形态
            "triple_bottom": 0.8,                               # 三底形态
            "triple_top": -0.8,                                 # 三顶形态
            "rising_wedge": -0.6,                               # 上升楔形（看跌）
            "falling_wedge": 0.6,                               # 下降楔形（看涨）
            "triangle_convergence": 0.3,                        # 三角形收敛
            "triangle_divergence": 0.2,                         # 三角形发散
            "channel_breakthrough": 0.5,                        # 通道突破
            "channel_pullback": 0.3,                            # 通道回调
            "overbought_signal": -0.3,                          # 超买信号
            "oversold_signal": 0.3,                             # 超卖信号
            "bull_bear_transition": 0.5,                        # 多空转换
            "oscillating_range": 0.2,                           # 震荡区间
            "breakthrough_confirmation": 0.5,                   # 突破确认
            "pullback_confirmation": 0.4,                       # 回调确认
        }

        # 所有信号名称列表
        self.all_signals = list(self.signal_strength.keys())
        
        # 复杂形态信号列表（已完整实现，可通过exclude_complex_patterns参数选择是否启用）
        self.complex_patterns = [
            'zero_line_breakthrough', 'zero_line_pullback', 'double_bottom', 'double_top', 
            'triple_bottom', 'triple_top', 'rising_wedge', 'falling_wedge', 
            'triangle_convergence', 'triangle_divergence', 'channel_breakthrough', 
            'channel_pullback', 'bull_bear_transition', 'oscillating_range', 
            'breakthrough_confirmation', 'pullback_confirmation'
        ]

    def get_dema_components(self, price_matrix, dema_period=20):
        """计算DEMA核心组件 (EMA, EMA_of_EMA, DEMA线, 斜率, 动量)"""
        
        # 1. 单重EMA (EMA)
        ema = price_matrix.ewm(span=dema_period, adjust=False).mean()
        
        # 2. EMA的EMA (EMA_of_EMA)
        ema_of_ema = ema.ewm(span=dema_period, adjust=False).mean()
        
        # 3. DEMA 线
        dema_line = 2 * ema - ema_of_ema

        # 4. DEMA斜率 (Slope)
        dema_slope = dema_line.diff()
        
        # 5. DEMA动量 (Momentum - 二阶变化)
        dema_momentum = dema_slope.diff()

        # 填充初始NaN值 (由于EMA计算)
        dema_line = dema_line.fillna(method='ffill').fillna(price_matrix)
        ema = ema.fillna(method='ffill').fillna(price_matrix)
        dema_slope = dema_slope.fillna(0)
        dema_momentum = dema_momentum.fillna(0)
        
        return dema_line, ema, dema_slope, dema_momentum

    def trend_reversal_signals(self, dema_line, dema_slope):
        """趋势转折信号（DEMA自身方向变化）"""
        
        # 1. 趋势转折（斜率穿越零轴）
        slope_prev = dema_slope.shift(1)
        
        trend_reversal_up = ((slope_prev <= 0) & (dema_slope > 0)).astype(float) * self.signal_strength["trend_reversal"]
        trend_reversal_down = ((slope_prev >= 0) & (dema_slope < 0)).astype(float) * self.signal_strength["trend_reversal"] * (-1)
        
        # 2. 动能加速/减速（斜率变化）
        slope_prev_abs = dema_slope.shift(1).abs()
        
        # 加速：斜率绝对值增加，且斜率方向为正
        acceleration = ((dema_slope.abs() > slope_prev_abs) & (dema_slope > 0)).astype(float) * self.signal_strength["trend_acceleration"]
        
        # 减速：斜率绝对值减小，且斜率方向为负
        deceleration = ((dema_slope.abs() < slope_prev_abs) & (dema_slope < 0)).astype(float) * self.signal_strength["trend_deceleration"]

        return {
            "trend_reversal_up": trend_reversal_up.fillna(0),
            "trend_reversal_down": trend_reversal_down.fillna(0),
            "trend_acceleration": acceleration.fillna(0),
            "trend_deceleration": deceleration.fillna(0)
        }

    def momentum_exhaustion_signals(self, dema_momentum):
        """动能衰竭与恢复信号（基于二阶动量反转）"""
        
        momentum_prev = dema_momentum.shift(1)
        
        # 1. 动能衰竭：动量由正转负，且负动量增大
        is_exhaustion = ((momentum_prev > 0) & (dema_momentum < 0) & 
                         (dema_momentum.abs() > momentum_prev.abs())).astype(float) * self.signal_strength["momentum_exhaustion"]
        
        # 2. 动能恢复：动量由负转正，且正动量增大
        is_recovery = ((momentum_prev < 0) & (dema_momentum > 0) & 
                       (dema_momentum.abs() > momentum_prev.abs())).astype(float) * self.signal_strength["momentum_recovery"]

        return {
            "momentum_exhaustion": is_exhaustion.fillna(0),
            "momentum_recovery": is_recovery.fillna(0)
        }
        
    def extreme_crossover_signals(self, price_matrix, dema_line, ema):
        """DEMA与价格或EMA的相对关系信号"""
        
        # DEMA线自身即为价格的支撑/阻力线，此处使用DEMA与单EMA线的关系来判断极值偏离。
        # DEMA远离EMA（意味着动量强）
        dema_diff = dema_line - ema
        dema_diff_prev = dema_diff.shift(1)
        
        # 1. 超买信号（DEMA远高于EMA）
        # 使用 DEMA > EMA * 1.05 作为超买
        is_overbought = (dema_line > ema * 1.05).astype(float) * self.signal_strength["overbought_signal"]

        # 2. 超卖信号（DEMA远低于EMA）
        # 使用 DEMA < EMA * 0.95 作为超卖
        is_oversold = (dema_line < ema * 0.95).astype(float) * self.signal_strength["oversold_signal"]

        # 3. 极值反转 (DEMA达到极端偏离后开始向EMA回归)
        # 顶部反转：DEMA在远高于EMA后开始下降（即 dema_diff 达到高点后开始减小）
        reversal_top = ((dema_line > ema * 1.1) & (dema_diff < dema_diff_prev)).astype(float) * self.signal_strength["extreme_reversal_top"]
        
        # 底部反转：DEMA在远低于EMA后开始上升（即 dema_diff 达到低点后开始增大）
        reversal_bottom = ((dema_line < ema * 0.9) & (dema_diff > dema_diff_prev)).astype(float) * self.signal_strength["extreme_reversal_bottom"]

        # 4. 支撑/阻力突破 (价格突破DEMA线)
        price_prev = price_matrix.shift(1)
        
        # 支撑突破 (DEMA为支撑，价格跌破DEMA线)
        support_break = ((price_prev >= dema_line.shift(1)) & (price_matrix < dema_line)).astype(float) * self.signal_strength["support_breakthrough"]
        
        # 阻力突破 (DEMA为阻力，价格突破DEMA线)
        resistance_break = ((price_prev <= dema_line.shift(1)) & (price_matrix > dema_line)).astype(float) * self.signal_strength["resistance_breakthrough"]

        return {
            "overbought_signal": is_overbought.fillna(0),
            "oversold_signal": is_oversold.fillna(0),
            "extreme_reversal_top": reversal_top.fillna(0),
            "extreme_reversal_bottom": reversal_bottom.fillna(0),
            "support_breakthrough": support_break.fillna(0),
            "resistance_breakthrough": resistance_break.fillna(0)
        }


    def divergence_signals(self, dema_line, price_matrix, lookback_period=10):
        """DEMA顶底背离信号 (价格与DEMA线)"""
        
        # 最近 lookback_period 内的最高价/最低价和DEMA的最大值/最小值
        price_high = price_matrix.rolling(lookback_period).max()
        price_low = price_matrix.rolling(lookback_period).min()
        dema_max = dema_line.rolling(lookback_period).max()
        dema_min = dema_line.rolling(lookback_period).min()

        current_price = price_matrix
        current_dema = dema_line
        
        # 1. 顶背离 (Top Divergence): 价格创新高，DEMA未创新高 (且在正值区)
        price_peak = (current_price > price_high.shift(1))
        dema_not_peak = (current_dema < dema_max.shift(1) * 0.99)
        is_top_divergence = (price_peak & dema_not_peak & (current_dema > 0)).astype(float) * self.signal_strength["top_divergence"]
        
        # 2. 底背离 (Bottom Divergence): 价格创新低，DEMA未创新低 (且在负值区)
        price_trough = (current_price < price_low.shift(1))
        dema_not_trough = (current_dema > dema_min.shift(1) * 0.99)
        is_bottom_divergence = (price_trough & dema_not_trough & (current_dema < 0)).astype(float) * self.signal_strength["bottom_divergence"]
        
        return {
            "top_divergence": is_top_divergence.fillna(0),
            "bottom_divergence": is_bottom_divergence.fillna(0)
        }

    def complex_pattern_signals(self, price_matrix, dema_line, ema, dema_slope, lookback_period=20):
        """复杂形态信号 (零轴突破/回调、双底/双顶、三底/三顶、楔形、三角形、通道等)"""
        
        # ============ 1. 零轴突破和回调 ============
        # 零轴突破：DEMA从下方突破零轴后持续上涨
        dema_prev = dema_line.shift(1)
        zero_line_breakthrough = (
            (dema_prev < 0) & (dema_line > 0) & (dema_slope > 0)
        ).astype(float) * self.signal_strength["zero_line_breakthrough"]
        
        # 零轴回调：DEMA从上方回调至零轴后继续下跌
        zero_line_pullback = (
            (dema_prev > 0) & (dema_line < 0) & (dema_slope < 0)
        ).astype(float) * self.signal_strength["zero_line_pullback"]
        
        # ============ 2. 双底和双顶形态 ============
        # 双底：在lookback_period内出现两个相近的低点，第二个低点后价格上涨
        rolling_min = dema_line.rolling(lookback_period).min()
        rolling_min_prev = rolling_min.shift(lookback_period // 2)
        
        # 判断是否形成双底：当前值接近历史低点，且之前也有类似低点
        is_near_min = (dema_line < rolling_min * 1.02)
        is_near_min_prev = (rolling_min_prev < rolling_min * 1.02)
        double_bottom = (
            is_near_min & is_near_min_prev & (dema_slope > 0) & (dema_line < ema)
        ).astype(float) * self.signal_strength["double_bottom"]
        
        # 双顶：在lookback_period内出现两个相近的高点，第二个高点后价格下跌
        rolling_max = dema_line.rolling(lookback_period).max()
        rolling_max_prev = rolling_max.shift(lookback_period // 2)
        
        is_near_max = (dema_line > rolling_max * 0.98)
        is_near_max_prev = (rolling_max_prev > rolling_max * 0.98)
        double_top = (
            is_near_max & is_near_max_prev & (dema_slope < 0) & (dema_line > ema)
        ).astype(float) * self.signal_strength["double_top"]
        
        # ============ 3. 三底和三顶形态 ============
        # 三底：更严格的底部形态，需要三个低点
        rolling_min_1 = rolling_min.shift(lookback_period // 3)
        rolling_min_2 = rolling_min.shift(lookback_period * 2 // 3)
        
        is_triple_bottom = (
            is_near_min & 
            (rolling_min_1 < rolling_min * 1.02) & 
            (rolling_min_2 < rolling_min * 1.02) &
            (dema_slope > 0) & 
            (dema_line < ema * 0.95)
        ).astype(float) * self.signal_strength["triple_bottom"]
        
        # 三顶：更严格的顶部形态，需要三个高点
        rolling_max_1 = rolling_max.shift(lookback_period // 3)
        rolling_max_2 = rolling_max.shift(lookback_period * 2 // 3)
        
        is_triple_top = (
            is_near_max & 
            (rolling_max_1 > rolling_max * 0.98) & 
            (rolling_max_2 > rolling_max * 0.98) &
            (dema_slope < 0) & 
            (dema_line > ema * 1.05)
        ).astype(float) * self.signal_strength["triple_top"]
        
        # ============ 4. 楔形形态 ============
        # 上升楔形（看跌）：价格在上升通道中，但上升动能减弱
        slope_ma = dema_slope.rolling(lookback_period // 2).mean()
        slope_std = dema_slope.rolling(lookback_period // 2).std()
        
        # 上升楔形：斜率为正但递减，且波动率收窄
        rising_wedge = (
            (slope_ma > 0) & 
            (slope_ma < slope_ma.shift(5)) & 
            (slope_std < slope_std.shift(5)) &
            (dema_line > ema)
        ).astype(float) * self.signal_strength["rising_wedge"]
        
        # 下降楔形（看涨）：价格在下降通道中，但下降动能减弱
        falling_wedge = (
            (slope_ma < 0) & 
            (slope_ma > slope_ma.shift(5)) & 
            (slope_std < slope_std.shift(5)) &
            (dema_line < ema)
        ).astype(float) * self.signal_strength["falling_wedge"]
        
        # ============ 5. 三角形收敛和发散 ============
        # 计算DEMA的波动幅度
        dema_range = rolling_max - rolling_min
        dema_range_prev = dema_range.shift(lookback_period // 2)
        
        # 三角形收敛：波动幅度逐渐缩小
        triangle_convergence = (
            (dema_range < dema_range_prev * 0.7) &
            (dema_range > 0) &
            (slope_std < slope_std.shift(5))
        ).astype(float) * self.signal_strength["triangle_convergence"]
        
        # 三角形发散：波动幅度突然放大（突破信号）
        triangle_divergence = (
            (dema_range > dema_range_prev * 1.5) &
            (slope_std > slope_std.shift(5))
        ).astype(float) * self.signal_strength["triangle_divergence"]
        
        # ============ 6. 通道突破和回调 ============
        # 使用标准差构建通道
        dema_mean = dema_line.rolling(lookback_period).mean()
        dema_std = dema_line.rolling(lookback_period).std()
        
        upper_band = dema_mean + 2 * dema_std
        lower_band = dema_mean - 2 * dema_std
        
        # 通道突破：DEMA突破上轨
        channel_breakthrough = (
            (dema_prev < upper_band.shift(1)) & 
            (dema_line > upper_band) &
            (dema_slope > 0)
        ).astype(float) * self.signal_strength["channel_breakthrough"]
        
        # 通道回调：DEMA回到通道内
        channel_pullback = (
            (dema_prev > upper_band.shift(1)) & 
            (dema_line < upper_band) &
            (dema_line > dema_mean)
        ).astype(float) * self.signal_strength["channel_pullback"]
        
        # ============ 7. 多空转换 ============
        # 多空转换：DEMA穿越EMA，且方向明确
        dema_ema_diff = dema_line - ema
        dema_ema_diff_prev = dema_ema_diff.shift(1)
        
        bull_bear_transition = (
            (dema_ema_diff_prev * dema_ema_diff < 0) &  # 穿越零轴
            (dema_slope.abs() > slope_std)  # 动能足够强
        ).astype(float) * self.signal_strength["bull_bear_transition"] * np.sign(dema_slope)
        
        # ============ 8. 震荡区间 ============
        # 震荡区间：DEMA在一个窄幅范围内波动
        oscillating_range = (
            (dema_range < dema_mean.abs() * 0.1) &
            (slope_std < slope_std.rolling(lookback_period).mean() * 0.5)
        ).astype(float) * self.signal_strength["oscillating_range"]
        
        # ============ 9. 突破确认 ============
        # 突破确认：价格突破DEMA后持续走强
        price_prev = price_matrix.shift(1)
        breakthrough_confirmation = (
            (price_prev < dema_prev) & 
            (price_matrix > dema_line) &
            (price_matrix > price_prev) &
            (dema_slope > 0)
        ).astype(float) * self.signal_strength["breakthrough_confirmation"]
        
        # ============ 10. 回调确认 ============
        # 回调确认：价格回调到DEMA附近后反弹
        is_near_dema = (price_matrix > dema_line * 0.98) & (price_matrix < dema_line * 1.02)
        pullback_confirmation = (
            is_near_dema &
            (price_matrix > price_prev) &
            (dema_slope > 0) &
            (price_matrix.shift(2) > dema_line.shift(2))  # 之前在DEMA上方
        ).astype(float) * self.signal_strength["pullback_confirmation"]
        
        return {
            "zero_line_breakthrough": zero_line_breakthrough.fillna(0),
            "zero_line_pullback": zero_line_pullback.fillna(0),
            "double_bottom": double_bottom.fillna(0),
            "double_top": double_top.fillna(0),
            "triple_bottom": is_triple_bottom.fillna(0),
            "triple_top": is_triple_top.fillna(0),
            "rising_wedge": rising_wedge.fillna(0),
            "falling_wedge": falling_wedge.fillna(0),
            "triangle_convergence": triangle_convergence.fillna(0),
            "triangle_divergence": triangle_divergence.fillna(0),
            "channel_breakthrough": channel_breakthrough.fillna(0),
            "channel_pullback": channel_pullback.fillna(0),
            "bull_bear_transition": bull_bear_transition.fillna(0),
            "oscillating_range": oscillating_range.fillna(0),
            "breakthrough_confirmation": breakthrough_confirmation.fillna(0),
            "pullback_confirmation": pullback_confirmation.fillna(0)
        }


    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, enabled_signals=None, dema_period=20):
        """
        整合启用的信号，生成最终的DEMA信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            enabled_signals: list，指定启用的信号名称
            dema_period: int, DEMA计算周期

        返回:
            sum_buy, sum_sell: pd.DataFrame，同输入维度，值为信号强度（-1.0至1.0）
        """
        
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 只使用Close_data
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        # 1. 计算DEMA核心组件
        dema_line, ema, dema_slope, dema_momentum = self.get_dema_components(Close_data, dema_period)

        # 2. 获取所有信号矩阵
        trend_rev = self.trend_reversal_signals(dema_line, dema_slope)
        momentum_exh = self.momentum_exhaustion_signals(dema_momentum)
        extreme_cross = self.extreme_crossover_signals(Close_data, dema_line, ema)
        divergence = self.divergence_signals(dema_line, Close_data)
        complex_patterns = self.complex_pattern_signals(Close_data, dema_line, ema, dema_slope)

        # 3. 零轴穿越信号 (DEMA穿越零轴)
        dema_prev = dema_line.shift(1)
        golden_cross = ((dema_prev <= 0) & (dema_line > 0)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((dema_prev >= 0) & (dema_line < 0)).astype(float) * self.signal_strength["death_cross"] * (-1)
        
        # 合并所有信号字典
        all_signals_dict = {
            "golden_cross": golden_cross.fillna(0),
            "death_cross": death_cross.fillna(0),
            **trend_rev, 
            **momentum_exh, 
            **extreme_cross, 
            **divergence,
            **complex_patterns
        }

        # 4. 累加启用的信号强度
        for signal_name, signal_matrix in all_signals_dict.items():
            # 包含所有信号（包括复杂形态）
            if signal_name in enabled_signals and signal_matrix is not None:
                
                buy_mask = signal_matrix > 0
                sum_buy = sum_buy + signal_matrix.where(buy_mask, 0)
                
                sell_mask = signal_matrix < 0
                sum_sell = sum_sell + signal_matrix.where(sell_mask, 0)

        # 5. 处理初始NaN值
        sum_buy = sum_buy.fillna(0)
        sum_sell = sum_sell.fillna(0)
        
        # 屏蔽初始无效行
        min_valid_rows = dema_period * 2  # DEMA计算需要两轮EMA，所以至少需要 2*N 才能稳定
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

    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, dema_period=20):
        """
        获取详细的信号DataFrame，包含每个信号的明细信息

        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 1. 计算DEMA核心组件（只使用Close_data）
        dema_line, ema, dema_slope, dema_momentum = self.get_dema_components(Close_data, dema_period)
        
        # 获取日期索引和股票列名
        date_index = Close_data.index
        stock_columns = Close_data.columns
        
        # 2. 信号处理器列表
        trend_rev = self.trend_reversal_signals(dema_line, dema_slope)
        momentum_exh = self.momentum_exhaustion_signals(dema_momentum)
        extreme_cross = self.extreme_crossover_signals(Close_data, dema_line, ema)
        divergence = self.divergence_signals(dema_line, Close_data)
        complex_patterns = self.complex_pattern_signals(Close_data, dema_line, ema, dema_slope)

        # 零轴穿越信号
        dema_prev = dema_line.shift(1)
        golden_cross = ((dema_prev <= 0) & (dema_line > 0)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((dema_prev >= 0) & (dema_line < 0)).astype(float) * self.signal_strength["death_cross"] * (-1)
        
        signal_processors = [
            {"golden_cross": golden_cross, "death_cross": death_cross * (-1)}, # 负号转回正信号
            trend_rev, 
            momentum_exh, 
            extreme_cross, 
            divergence,
            complex_patterns
        ]
        
        # 3. 统一处理所有信号记录（包含复杂形态）
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
            min_valid_rows = dema_period * 2
            if len(Close_data) > min_valid_rows:
                 # 过滤掉日期早于有效期的信号
                signals_df = signals_df[signals_df['Date'] >= Close_data.index[min_valid_rows]]
        else:
            signals_df = pd.DataFrame(columns=[
                'Date', 'Contract', 'direction', 'signal_name', 'strength'
            ])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      dema_period=20, enabled_signals=None, exclude_complex_patterns=True):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，OHLC数据
            dema_period: int，DEMA计算周期，默认20
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
        
        # 1. 计算DEMA核心组件
        dema_line, ema, dema_slope, dema_momentum = self.get_dema_components(Close_data, dema_period)
        
        # 2. 获取各类信号
        trend_rev = self.trend_reversal_signals(dema_line, dema_slope)
        momentum_exh = self.momentum_exhaustion_signals(dema_momentum)
        extreme_cross = self.extreme_crossover_signals(Close_data, dema_line, ema)
        divergence = self.divergence_signals(dema_line, Close_data)
        complex_patterns = self.complex_pattern_signals(Close_data, dema_line, ema, dema_slope)
        
        # 零轴穿越信号
        dema_prev = dema_line.shift(1)
        golden_cross = ((dema_prev <= 0) & (dema_line > 0)).astype(float) * self.signal_strength["golden_cross"]
        death_cross = ((dema_prev >= 0) & (dema_line < 0)).astype(float) * self.signal_strength["death_cross"] * (-1)
        
        # 3. 合并所有信号字典
        all_signals_dict = {
            "golden_cross": golden_cross.fillna(0),
            "death_cross": death_cross.fillna(0),
            **trend_rev, 
            **momentum_exh, 
            **extreme_cross, 
            **divergence,
            **complex_patterns
        }
        
        # 4. 过滤信号
        if exclude_complex_patterns:
            all_signals_dict = {
                k: v for k, v in all_signals_dict.items() 
                if k not in self.complex_patterns
            }
        
        if enabled_signals is not None:
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
            
            # 7. 屏蔽初始无效行（前 dema_period*2 行）
            min_valid_rows = dema_period * 2
            if len(Close_data) > min_valid_rows:
                valid_start_date = Close_data.index[min_valid_rows]

                print(valid_start_date)
                print(type(valid_start_date))
                print(signals_multi_index.index.get_level_values(0))
                print(type(signals_multi_index.index.get_level_values(0)))



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
    



    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, dema_period=20):
        """
        拆分DEMA的趋势转折、动能衰竭及复杂形态信号。
        """
        line, ema, slope, mom = self.get_dema_components(Close_data, dema_period)
        
        trend = self.trend_reversal_signals(line, slope)
        exhaustion = self.momentum_exhaustion_signals(mom)
        extreme = self.extreme_crossover_signals(Close_data, line, ema)
        div = self.divergence_signals(line, Close_data)
        complex_p = self.complex_pattern_signals(Close_data, line, ema, slope)

        # 处理特殊的零轴穿越（在 get_total_signal_matrix 中单独定义的逻辑）
        dema_prev = line.shift(1)
        golden = ((dema_prev <= 0) & (line > 0)).astype(float) * self.signal_strength["golden_cross"]
        death = ((dema_prev >= 0) & (line < 0)).astype(float) * self.signal_strength["death_cross"]

        all_factors = {
            "golden_cross": golden, 
            "death_cross": death,
            **trend, **exhaustion, **extreme, **div, **complex_p
        }
        
        for name in all_factors:
            all_factors[name].iloc[:dema_period * 2] = 0.0
                
        return all_factors