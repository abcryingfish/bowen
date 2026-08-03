import pandas as pd
import numpy as np


# 缩写解释和公式说明
'''AMA相关参数及公式说明

AMA: Adaptive Adaptive Moving Average (自适应移动平均)
ER: Efficiency Ratio (效率比) - 衡量价格趋势的有效性
SC: Smoothing Constant (平滑常数) - 控制AMA对价格变化的敏感度
AMA线: 随趋势强度动态调整的移动平均线

效率比(ER)计算公式:
ER = 价格变动净距离 / 价格变动变动总距离
价格变动净距离 = |当前价格 - N期前价格|
价格变动总距离 = N期内每日价格变动绝对值之和

平滑常数(SC)计算公式:
SC = [ER × (fast_SC - slow_SC) + slow_SC]²
其中: fast_SC = 2/(fast_period + 1), slow_SC = 2/(slow_period + 1)

AMA线计算公式:
AMAₜ = AMAₜ₋₁ + SCₜ × (价格ₜ - AMAₜ₋₁)
初始值AMAₙ = 第N期价格 (N为计算周期)

AMA斜率: 当前AMA值与前一期AMA值的差值
AMA动量: 当前AMA值相对前一期的变化百分比
AMA波动率: 一定周期内AMA动量的标准差

优点: 能自动适应趋势强度，趋势强时更敏感，震荡时更平滑，减少滞后性
缺点: 极端行情下可能过度敏感，参数设置对结果影响较大
'''


class AMA:
    def __init__(self):
        # 信号强度字典，与原文件保持一致
        self.signal_strength = {
            # 交叉信号
            "golden_cross": 0.5,          # 金叉：中等看涨
            "death_cross": -0.5,          # 死叉：中等看跌
            # 趋势信号
            "uptrend_strengthen": 0.4,    # 上升趋势增强
            "downtrend_strengthen": -0.4, # 下降趋势增强
            # 背离信号
            "bottom_divergence": 0.6,     # 底背离：强看涨
            "top_divergence": -0.6,       # 顶背离：强看跌
            # 效率比信号
            "high_efficiency": 0.3,       # 高效率比：趋势强劲
            "low_efficiency": -0.3,       # 低效率比：震荡市场
            # 突破信号
            "upper_breakthrough": 0.5,    # 突破上轨：看涨
            "lower_breakdown": -0.5,      # 跌破下轨：看跌
            # 动量信号
            "momentum_acceleration": 0.4, # 动量加速
            "momentum_deceleration": -0.4 # 动量减速
        }

        # 所有信号名称列表
        self.all_signals = list(self.signal_strength.keys())

    def get_ama_components(self, close_prices, period=10, fast_sc=2, slow_sc=30):
        """
        计算AMA核心组件
        
        参数:
            close_prices: pd.DataFrame，行=时间，列=标的，值=收盘价
        
        返回:
            dict: 包含 ama_line, efficiency_ratio, smoothing_constant 等核心组件
        """
        
        # 1. 计算效率比(ER) - 向量化
        # 价格变动净距离 = |当前价格 - N期前价格|
        direction = (close_prices - close_prices.shift(period)).abs()
        # 价格变动总距离 = N期内每日价格变动绝对值之和
        volatility = close_prices.diff().abs().rolling(window=period).sum()
        # ER = 净距离 / 总距离
        efficiency_ratio = np.where(volatility != 0, direction / volatility, 0)
        # 转换为DataFrame以保持结构
        efficiency_ratio = pd.DataFrame(efficiency_ratio, index=close_prices.index, columns=close_prices.columns)
        
        # 2. 计算平滑常数(SC) - 向量化
        fastest_sc = 2.0 / (fast_sc + 1)
        slowest_sc = 2.0 / (slow_sc + 1)
        # SC = [ER × (fast_SC - slow_SC) + slow_SC]²
        smoothing_constant = (efficiency_ratio * (fastest_sc - slowest_sc) + slowest_sc) ** 2
        
        # 3. 计算AMA线 - 迭代（由于AMA的递归特性，难以完全向量化）
        ama_line = pd.DataFrame(index=close_prices.index, columns=close_prices.columns, dtype='float64')
        
        # 初始值设置: AMAₙ = 第N期价格
        ama_line.iloc[period] = close_prices.iloc[period]
        
        # 逐行迭代计算AMA（必须使用循环）
        # 注意: Python的循环在多列DataFrame上效率相对较高
        for i in range(period + 1, len(ama_line)):
            # AMAₜ = AMAₜ₋₁ + SCₜ × (价格ₜ - AMAₜ₋₁)
            ama_line.iloc[i] = ama_line.iloc[i-1] + smoothing_constant.iloc[i] * (close_prices.iloc[i] - ama_line.iloc[i-1])

        # 4. 计算衍生指标 - 向量化
        # AMA斜率: 当前AMA值与前一期AMA值的差值
        ama_slope = ama_line.diff()
        # AMA动量: 当前AMA值相对前一期的变化百分比
        ama_momentum = ama_line.pct_change()
        # AMA波动率: 一定周期内AMA动量的标准差
        ama_volatility = ama_momentum.rolling(window=10).std()
        
        # NaN处理：用最近的有效值向前填充（只对AMA本身及其衍生指标进行填充，ER和SC的NaN是滞后期的计算结果，不应填充）
        ama_line = ama_line.ffill().fillna(0)
        ama_slope = ama_slope.ffill().fillna(0)
        ama_momentum = ama_momentum.ffill().fillna(0)
        ama_volatility = ama_volatility.ffill().fillna(0)
        
        return {
            'ama_line': ama_line,
            'efficiency_ratio': efficiency_ratio,
            'smoothing_constant': smoothing_constant,
            'ama_slope': ama_slope,
            'ama_momentum': ama_momentum,
            'ama_volatility': ama_volatility
        }

    # 交叉信号 (价格与AMA线)
    def cross_signals(self, close_prices, ama_line):
        """生成金叉/死叉信号"""
        # 金叉：价格上穿AMA线
        golden_cross = ((close_prices.shift(1) <= ama_line.shift(1)) & 
                        (close_prices > ama_line)).astype(float) * self.signal_strength["golden_cross"]
        
        # 死叉：价格下穿AMA线
        death_cross = ((close_prices.shift(1) >= ama_line.shift(1)) & 
                       (close_prices < ama_line)).astype(float) * self.signal_strength["death_cross"]
        
        return {
            "golden_cross": golden_cross,
            "death_cross": death_cross
        }

    # 趋势信号 (AMA斜率)
    def trend_signals(self, ama_slope, window=3):
        """生成趋势强弱信号"""
        # 上升趋势增强：斜率为正且绝对值增大
        slope_abs = ama_slope.abs()
        uptrend = ama_slope > 0
        uptrend_strengthen = (uptrend & 
                             (slope_abs > slope_abs.shift(1)) & 
                             (slope_abs.rolling(window).mean() > slope_abs.shift(window).rolling(window).mean())
                            ).astype(float) * self.signal_strength["uptrend_strengthen"]
        
        # 下降趋势增强：斜率为负且绝对值增大
        downtrend = ama_slope < 0
        downtrend_strengthen = (downtrend & 
                               (slope_abs > slope_abs.shift(1)) & 
                               (slope_abs.rolling(window).mean() > slope_abs.shift(window).rolling(window).mean())
                              ).astype(float) * self.signal_strength["downtrend_strengthen"]
        
        return {
            "uptrend_strengthen": uptrend_strengthen,
            "downtrend_strengthen": downtrend_strengthen
        }

    # 背离信号 (价格与AMA线)
    def divergence_signals(self, close_prices, ama_line, threshold=0.02):
        """生成背离信号"""
        # 底背离：价格创新低，AMA未创新低
        price_lows = close_prices.rolling(window=5).min()
        ama_lows = ama_line.rolling(window=5).min()
        bottom_divergence = ((close_prices == price_lows) & 
                            (ama_line > ama_lows) & 
                            ((close_prices - ama_line) / ama_line < -threshold)
                           ).astype(float) * self.signal_strength["bottom_divergence"]
        
        # 顶背离：价格创新高，AMA未创新高
        price_highs = close_prices.rolling(window=5).max()
        ama_highs = ama_line.rolling(window=5).max()
        top_divergence = ((close_prices == price_highs) & 
                         (ama_line < ama_highs) & 
                         ((close_prices - ama_line) / ama_line > threshold)
                        ).astype(float) * self.signal_strength["top_divergence"]
        
        return {
            "bottom_divergence": bottom_divergence,
            "top_divergence": top_divergence
        }

    # 效率比信号
    def efficiency_signals(self, efficiency_ratio):
        """生成效率比信号"""
        # 高效率比：趋势强劲
        high_efficiency = (efficiency_ratio > 0.7).astype(float) * self.signal_strength["high_efficiency"]
        
        # 低效率比：震荡市场
        low_efficiency = (efficiency_ratio < 0.3).astype(float) * self.signal_strength["low_efficiency"]
        
        return {
            "high_efficiency": high_efficiency,
            "low_efficiency": low_efficiency
        }

    # 动量信号 (AMA动量)
    def momentum_signals(self, ama_momentum, window=5):
        """生成动量信号"""
        # 动量加速：近期动量大于前期动量
        recent_momentum = ama_momentum.rolling(window).mean()
        prev_momentum = ama_momentum.shift(window).rolling(window).mean()
        
        momentum_acceleration = (recent_momentum > prev_momentum * 1.2).astype(float) * self.signal_strength["momentum_acceleration"]
        momentum_deceleration = (recent_momentum < prev_momentum * 0.8).astype(float) * self.signal_strength["momentum_deceleration"]
        
        return {
            "momentum_acceleration": momentum_acceleration,
            "momentum_deceleration": momentum_deceleration
        }

    # 轨道突破信号 (AMA线 +/- 波动率 * 乘数)
    def band_signals(self, close_prices, ama_line, ama_volatility, multiplier=2):
        """生成轨道突破信号"""
        # 计算上下轨 (AMA线 +/- 乘数 * AMA波动率 * AMA线)
        upper_band = ama_line + multiplier * ama_volatility * ama_line
        lower_band = ama_line - multiplier * ama_volatility * ama_line
        
        # 突破上轨
        upper_breakthrough = ((close_prices.shift(1) <= upper_band.shift(1)) & 
                             (close_prices > upper_band)).astype(float) * self.signal_strength["upper_breakthrough"]
        
        # 跌破下轨
        lower_breakdown = ((close_prices.shift(1) >= lower_band.shift(1)) & 
                          (close_prices < lower_band)).astype(float) * self.signal_strength["lower_breakdown"]
        
        return {
            "upper_breakthrough": upper_breakthrough,
            "lower_breakdown": lower_breakdown
        }

    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, period=10, fast_sc=2, slow_sc=30, 
                               divergence_threshold=0.02, enabled_signals=None):
        """
        整合所有信号，生成最终的买卖信号矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            period: AMA计算周期
            enabled_signals: 启用的信号列表，None表示使用所有信号
        
        返回:
            sum_buy, sum_sell: pd.DataFrame，买卖信号强度矩阵
        """
        # 1. 确定启用的信号
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 2. 计算AMA核心组件（只使用Close_data）
        components = self.get_ama_components(Close_data, period, fast_sc, slow_sc)
        
        # 3. 计算各类信号
        signal_generators = [
            self.cross_signals(Close_data, components['ama_line']),
            self.trend_signals(components['ama_slope']),
            self.divergence_signals(Close_data, components['ama_line'], divergence_threshold),
            self.efficiency_signals(components['efficiency_ratio']),
            self.momentum_signals(components['ama_momentum']),
            self.band_signals(Close_data, components['ama_line'], components['ama_volatility'])
        ]
        
        # 4. 合并所有信号
        all_signals = {}
        for sig_dict in signal_generators:
            all_signals.update(sig_dict)
        
        # 5. 计算买卖信号总和
        sum_buy = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)
        
        for signal_name, signal_matrix in all_signals.items():
            if signal_name in enabled_signals:
                # 累加正信号到买入
                sum_buy += signal_matrix.where(signal_matrix > 0, 0)
                # 累加负信号的绝对值到卖出
                sum_sell += signal_matrix.where(signal_matrix < 0, 0)
        
        # 6. 初期数据置零（避免计算不稳定，使用 2*period 作为安全期）
        sum_buy.iloc[:period*2] = 0
        sum_sell.iloc[:period*2] = 0
        
        return sum_buy, sum_sell

    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name, date_index, Contract_columns):
        """将信号矩阵转换为记录列表 (Helper function)"""
        stacked = signal_matrix.stack()
        non_zero = stacked[stacked != 0]
        
        if non_zero.empty:
            return []
        
        dates, Contract = zip(*non_zero.index)
        
        return pd.DataFrame({
            'Date': dates,
            'Contract': Contract,
            'direction': np.where(non_zero.values > 0, 'buy', 'sell'),
            'signal_name': signal_name,
            'strength': np.abs(non_zero.values)
        }).to_dict('records')

    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, period=10, 
                                      fast_sc=2, slow_sc=30, divergence_threshold=0.02):
        """获取详细的信号DataFrame"""
        
        # 计算核心组件（只使用Close_data）
        components = self.get_ama_components(Close_data, period, fast_sc, slow_sc)
        
        # 生成所有信号
        signal_generators = [
            (self.cross_signals(Close_data, components['ama_line']), "交叉信号"),
            (self.trend_signals(components['ama_slope']), "趋势信号"),
            (self.divergence_signals(Close_data, components['ama_line'], divergence_threshold), "背离信号"),
            (self.efficiency_signals(components['efficiency_ratio']), "效率比信号"),
            (self.momentum_signals(components['ama_momentum']), "动量信号"),
            (self.band_signals(Close_data, components['ama_line'], components['ama_volatility']), "轨道信号")
        ]
        
        # 转换为记录并合并
        from itertools import chain
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(sig_matrix, sig_name, Close_data.index, Close_data.columns)
            for sig_dict, _ in signal_generators
            for sig_name, sig_matrix in sig_dict.items()
        ))
        
        # 转换为DataFrame
        if all_records:
            return pd.DataFrame(all_records).sort_values(['Date', 'Contract']).reset_index(drop=True)
        else:
            return pd.DataFrame(columns=['Date', 'Contract', 'direction', 'signal_name', 'strength'])

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      period=10, fast_sc=2, slow_sc=30, divergence_threshold=0.02, 
                                      enabled_signals=None):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        这是一个通用方法，可以被其他类似的技术指标类复用。
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，OHLC数据
            period: int，AMA计算周期，默认10
            fast_sc: int，快速平滑常数周期，默认2
            slow_sc: int，慢速平滑常数周期，默认30
            divergence_threshold: float，背离判断阈值，默认0.02
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
            df = ama_analyzer.get_multi_index_signal_matrix(
                Open_data, High_data, Low_data, Close_data, Volume
            )
            
            # 获取特定信号
            df = ama_analyzer.get_multi_index_signal_matrix(
                Open_data, High_data, Low_data, Close_data, Volume,
                enabled_signals=['golden_cross', 'death_cross', 'bottom_divergence']
            )
            
            # 查询特定日期和合约的信号
            df.loc[(20240101, 'AAPL'), :]
            
            # 查询特定信号的所有记录（非零）
            df[df['golden_cross'] != 0]['golden_cross']
        """
        
        # 1. 计算AMA核心组件
        components = self.get_ama_components(Close_data, period, fast_sc, slow_sc)
        
        # 2. 获取各类信号
        cross_sigs = self.cross_signals(Close_data, components['ama_line'])
        trend_sigs = self.trend_signals(components['ama_slope'])
        divergence_sigs = self.divergence_signals(Close_data, components['ama_line'], divergence_threshold)
        efficiency_sigs = self.efficiency_signals(components['efficiency_ratio'])
        momentum_sigs = self.momentum_signals(components['ama_momentum'])
        band_sigs = self.band_signals(Close_data, components['ama_line'], components['ama_volatility'])
        
        # 3. 合并所有信号字典
        all_signals_dict = {
            **cross_sigs, 
            **trend_sigs, 
            **divergence_sigs, 
            **efficiency_sigs, 
            **momentum_sigs, 
            **band_sigs
        }
        
        # 4. 过滤信号
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
            
            # 7. 屏蔽初始无效行（前 period*2 行）
            min_valid_rows = period * 2
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
            
            # Values转换为float32类型
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

    def get_factor_matrices(self, Close_data, period=10):
        """
        将 AMA 的所有原子信号拆分为独立矩阵，每个信号一个 DataFrame。
        返回格式: {signal_name: DataFrame(Date x Contract), ...}
        """
        comp = self.get_ama_components(Close_data, period)
        
        cross = self.cross_signals(Close_data, comp['ama_line'])
        trend = self.trend_signals(comp['ama_slope'])
        div = self.divergence_signals(Close_data, comp['ama_line'])
        eff = self.efficiency_signals(comp['efficiency_ratio'])
        mom = self.momentum_signals(comp['ama_momentum'])
        band = self.band_signals(Close_data, comp['ama_line'], comp['ama_volatility'])

        all_factors = {**cross, **trend, **div, **eff, **mom, **band}

        for name, df in all_factors.items():
            if df is not None:
                df.iloc[:period * 2] = 0.0  # 冷启动期置零
            else:
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        return all_factors



# 引用方式示例 (作为注释，遵循您的格式要求)
# '''
# # 引用方式
# # 假设 Close_data 是一个 pd.DataFrame, index=日期, columns=标的, values=收盘价

# from strategys.技术面.ADX import ADX
# adx_analyzer = ADX()
# signal_adx_buy, signal_adx_sell = adx_analyzer.get_total_signal_matrix(
#     High_data, Low_data, Close_data, Close_data,
#     adx_period=14, divergence_threshold=0.02
# )
# signals_adx_search = adx_analyzer.get_detailed_signals_dataframe(
#     High_data, Low_data, Close_data, Close_data
# )
# '''

    def get_factor_matrices(self, Open_data, High_data, Low_data, Close_data, Volume, period=10, fast_sc=2, slow_sc=30):
            """
            完全拆分AMA的交叉、趋势增强、效率比等信号。
            """
            comp = self.get_ama_components(Close_data, period, fast_sc, slow_sc)
            
            cross = self.cross_signals(Close_data, comp['ama_line'])
            trend = self.trend_signals(comp['ama_slope'])
            div = self.divergence_signals(Close_data, comp['ama_line'])
            eff = self.efficiency_signals(comp['efficiency_ratio'])
            mom = self.momentum_signals(comp['ama_momentum'])
            band = self.band_signals(Close_data, comp['ama_line'], comp['ama_volatility'])

            all_factors = {**cross, **trend, **div, **eff, **mom, **band}
            
            for name in all_factors:
                all_factors[name].iloc[:period * 2] = 0.0
                    
            return all_factors