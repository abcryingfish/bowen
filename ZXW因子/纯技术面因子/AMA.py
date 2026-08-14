import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np


AMA_STATE_ALGORITHM_VERSION = "ama_recursive_v1"
AMA_STATE_TAIL_ROWS = 20
DEFAULT_AMA_STATE_CACHE_PATH = Path(
    r"D:\database\signal_daily\_state\ama_latest_state.parquet"
)
_AMA_STATE_LOCK = threading.RLock()
_AMA_PENDING_STATES: dict[str, dict[str, dict[str, Any]]] = {}


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


def _encode_float_array(values: np.ndarray) -> bytes:
    return np.ascontiguousarray(values, dtype=np.float64).tobytes()


def _decode_float_array(raw: object) -> np.ndarray:
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    return np.frombuffer(raw, dtype=np.float64).copy()


def _encode_datetime_array(values: pd.DatetimeIndex) -> bytes:
    return np.ascontiguousarray(values.asi8, dtype=np.int64).tobytes()


def _decode_datetime_array(raw: object) -> pd.DatetimeIndex:
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    return pd.to_datetime(np.frombuffer(raw, dtype=np.int64).copy())


def load_ama_state_cache(
    path: str | Path = DEFAULT_AMA_STATE_CACHE_PATH,
) -> dict[str, dict[str, Any]]:
    cache_path = Path(path)
    if not cache_path.is_file():
        return {}
    try:
        with _AMA_STATE_LOCK:
            frame = pd.read_parquet(cache_path)
    except Exception:
        return {}
    required = {
        "htsc_code",
        "last_dt",
        "tail_dates_bytes",
        "close_tail_bytes",
        "ama_tail_bytes",
        "period",
        "fast_sc",
        "slow_sc",
        "algorithm_version",
    }
    if not required.issubset(frame.columns):
        return {}

    states: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        try:
            tail_dates = _decode_datetime_array(row["tail_dates_bytes"])
            close_tail = _decode_float_array(row["close_tail_bytes"])
            ama_tail = _decode_float_array(row["ama_tail_bytes"])
            if not (len(tail_dates) == len(close_tail) == len(ama_tail)):
                continue
            code = str(row["htsc_code"]).strip().upper()
            states[code] = {
                "htsc_code": code,
                "last_dt": pd.Timestamp(row["last_dt"]).floor("D"),
                "tail_dates": tail_dates,
                "close_tail": close_tail,
                "ama_tail": ama_tail,
                "period": int(row["period"]),
                "fast_sc": int(row["fast_sc"]),
                "slow_sc": int(row["slow_sc"]),
                "algorithm_version": str(row["algorithm_version"]),
            }
        except Exception:
            continue
    return states


def _ama_state_usable(
    state: dict[str, Any] | None,
    *,
    period: int,
    fast_sc: int,
    slow_sc: int,
) -> bool:
    if not state:
        return False
    return (
        _ama_state_params_match(
            state,
            period=period,
            fast_sc=fast_sc,
            slow_sc=slow_sc,
        )
        and len(state.get("tail_dates", ())) >= period + 1
        and len(state.get("close_tail", ())) == len(state.get("ama_tail", ()))
    )


def _ama_state_params_match(
    state: dict[str, Any] | None,
    *,
    period: int,
    fast_sc: int,
    slow_sc: int,
) -> bool:
    return bool(state) and (
        state.get("algorithm_version") == AMA_STATE_ALGORITHM_VERSION
        and int(state.get("period", -1)) == int(period)
        and int(state.get("fast_sc", -1)) == int(fast_sc)
        and int(state.get("slow_sc", -1)) == int(slow_sc)
    )


def ama_state_cache_covers(
    path: str | Path,
    codes: list[str] | set[str] | tuple[str, ...],
    *,
    period: int = 10,
    fast_sc: int = 2,
    slow_sc: int = 30,
) -> bool:
    states = load_ama_state_cache(path)
    normalized_codes = {
        str(code).strip().upper() for code in codes if str(code).strip()
    }
    return bool(normalized_codes) and all(
        _ama_state_params_match(
            states.get(code),
            period=period,
            fast_sc=fast_sc,
            slow_sc=slow_sc,
        )
        for code in normalized_codes
    )


def _ama_signal_frames(
    analyzer: AMA,
    close_prices: pd.DataFrame,
    components: dict[str, pd.DataFrame],
    *,
    period: int,
) -> dict[str, pd.DataFrame]:
    factors = {
        **analyzer.cross_signals(close_prices, components["ama_line"]),
        **analyzer.trend_signals(components["ama_slope"]),
        **analyzer.divergence_signals(close_prices, components["ama_line"]),
        **analyzer.efficiency_signals(components["efficiency_ratio"]),
        **analyzer.momentum_signals(components["ama_momentum"]),
        **analyzer.band_signals(
            close_prices,
            components["ama_line"],
            components["ama_volatility"],
        ),
    }
    for frame in factors.values():
        frame.iloc[: period * 2] = 0.0
    return factors


def _seeded_ama_components(
    close_series: pd.Series,
    ama_seed: pd.Series,
    *,
    period: int,
    fast_sc: int,
    slow_sc: int,
) -> dict[str, pd.DataFrame]:
    close = close_series.astype(float)
    direction = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(window=period).sum()
    efficiency = (direction / volatility).where(volatility != 0, 0.0)
    fastest = 2.0 / (fast_sc + 1)
    slowest = 2.0 / (slow_sc + 1)
    smoothing = (efficiency * (fastest - slowest) + slowest) ** 2

    ama = ama_seed.reindex(close.index).astype(float)
    seeded = np.flatnonzero(ama.notna().to_numpy())
    if seeded.size == 0:
        raise ValueError("AMA 状态缺少可用递归种子")
    last_seed_pos = int(seeded[-1])
    for position in range(last_seed_pos + 1, len(close)):
        previous = ama.iloc[position - 1]
        current_close = close.iloc[position]
        current_smoothing = smoothing.iloc[position]
        ama.iloc[position] = previous + current_smoothing * (current_close - previous)

    ama_slope = ama.diff().ffill().fillna(0.0)
    ama_momentum = ama.pct_change(fill_method=None).ffill().fillna(0.0)
    ama_volatility = ama_momentum.rolling(window=10).std().ffill().fillna(0.0)
    column = str(close_series.name)
    to_frame = lambda series: series.to_frame(name=column)
    return {
        "ama_line": to_frame(ama.ffill().fillna(0.0)),
        "efficiency_ratio": to_frame(efficiency),
        "smoothing_constant": to_frame(smoothing),
        "ama_slope": to_frame(ama_slope),
        "ama_momentum": to_frame(ama_momentum),
        "ama_volatility": to_frame(ama_volatility),
    }


def _bootstrap_ama_components(
    close_prices: pd.DataFrame,
    *,
    period: int,
    fast_sc: int,
    slow_sc: int,
) -> dict[str, pd.DataFrame]:
    """首次 bootstrap 使用 NumPy 递归，避免 DataFrame.iloc 逐行写入。"""
    direction = (close_prices - close_prices.shift(period)).abs()
    volatility = close_prices.diff().abs().rolling(window=period).sum()
    efficiency = pd.DataFrame(
        np.where(volatility != 0, direction / volatility, 0.0),
        index=close_prices.index,
        columns=close_prices.columns,
    )
    fastest = 2.0 / (fast_sc + 1)
    slowest = 2.0 / (slow_sc + 1)
    smoothing = (efficiency * (fastest - slowest) + slowest) ** 2
    close_np = close_prices.to_numpy(dtype=float)
    smoothing_np = smoothing.to_numpy(dtype=float)
    ama_np = np.full(close_np.shape, np.nan, dtype=float)
    if len(close_np) > period:
        ama_np[period] = close_np[period]
        for position in range(period + 1, len(close_np)):
            ama_np[position] = ama_np[position - 1] + smoothing_np[position] * (
                close_np[position] - ama_np[position - 1]
            )
    ama_line = pd.DataFrame(ama_np, index=close_prices.index, columns=close_prices.columns)
    ama_slope = ama_line.diff()
    ama_momentum = ama_line.pct_change()
    ama_volatility = ama_momentum.rolling(window=10).std()
    return {
        "ama_line": ama_line.ffill().fillna(0.0),
        "efficiency_ratio": efficiency,
        "smoothing_constant": smoothing,
        "ama_slope": ama_slope.ffill().fillna(0.0),
        "ama_momentum": ama_momentum.ffill().fillna(0.0),
        "ama_volatility": ama_volatility.ffill().fillna(0.0),
    }


def _state_from_series(
    code: str,
    close_series: pd.Series,
    ama_series: pd.Series,
    *,
    period: int,
    fast_sc: int,
    slow_sc: int,
) -> dict[str, Any]:
    valid = close_series.notna() & ama_series.notna()
    close_tail = close_series.loc[valid].iloc[-AMA_STATE_TAIL_ROWS:]
    ama_tail = ama_series.reindex(close_tail.index)
    return {
        "htsc_code": str(code).strip().upper(),
        "last_dt": pd.Timestamp(close_tail.index[-1]).floor("D"),
        "tail_dates": pd.DatetimeIndex(close_tail.index).floor("D"),
        "close_tail": close_tail.to_numpy(dtype=np.float64),
        "ama_tail": ama_tail.to_numpy(dtype=np.float64),
        "period": int(period),
        "fast_sc": int(fast_sc),
        "slow_sc": int(slow_sc),
        "algorithm_version": AMA_STATE_ALGORITHM_VERSION,
    }


def _queue_ama_states(path: str | Path, states: dict[str, dict[str, Any]]) -> None:
    if not states:
        return
    key = str(Path(path).resolve())
    with _AMA_STATE_LOCK:
        _AMA_PENDING_STATES.setdefault(key, {}).update(states)


def discard_pending_ama_states(path: str | Path) -> None:
    key = str(Path(path).resolve())
    with _AMA_STATE_LOCK:
        _AMA_PENDING_STATES.pop(key, None)


def commit_ama_state_cache(path: str | Path) -> Path:
    cache_path = Path(path)
    key = str(cache_path.resolve())
    with _AMA_STATE_LOCK:
        pending = dict(_AMA_PENDING_STATES.get(key, {}))
        if not pending:
            return cache_path
        merged = load_ama_state_cache(cache_path)
        merged.update(pending)
        rows: list[dict[str, Any]] = []
        updated_at = pd.Timestamp.now()
        for code, state in sorted(merged.items()):
            rows.append(
                {
                    "htsc_code": code,
                    "last_dt": pd.Timestamp(state["last_dt"]).floor("D"),
                    "tail_dates_bytes": _encode_datetime_array(
                        pd.DatetimeIndex(state["tail_dates"])
                    ),
                    "close_tail_bytes": _encode_float_array(state["close_tail"]),
                    "ama_tail_bytes": _encode_float_array(state["ama_tail"]),
                    "period": int(state["period"]),
                    "fast_sc": int(state["fast_sc"]),
                    "slow_sc": int(state["slow_sc"]),
                    "algorithm_version": AMA_STATE_ALGORITHM_VERSION,
                    "updated_at": updated_at,
                }
            )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_name(
            f"{cache_path.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp.parquet"
        )
        try:
            pd.DataFrame(rows).to_parquet(temp_path, index=False)
            last_error: OSError | None = None
            for attempt in range(20):
                try:
                    os.replace(temp_path, cache_path)
                    last_error = None
                    break
                except OSError as exc:
                    last_error = exc
                    time.sleep(0.1 * (attempt + 1))
            if last_error is not None:
                raise last_error
            _AMA_PENDING_STATES.pop(key, None)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    return cache_path


def build_ama_factor_matrices_with_state(
    close_data: pd.DataFrame,
    *,
    state_cache_path: str | Path,
    period: int = 10,
    fast_sc: int = 2,
    slow_sc: int = 30,
    state_only: bool = False,
) -> dict[str, pd.DataFrame]:
    """使用耐久状态续算 AMA；缓存缺失的代码按当前输入完整计算。"""
    if not isinstance(close_data.index, pd.DatetimeIndex):
        raise TypeError("AMA 状态续算要求 DatetimeIndex")
    close_data = close_data.copy()
    close_data.index = pd.DatetimeIndex(close_data.index).floor("D")
    analyzer = AMA()
    result = {
        name: pd.DataFrame(np.nan, index=close_data.index, columns=close_data.columns)
        for name in analyzer.all_signals
    }
    cached_states = load_ama_state_cache(state_cache_path)
    new_states: dict[str, dict[str, Any]] = {}
    bootstrap_columns: list[str] = []

    for raw_code in close_data.columns:
        code = str(raw_code).strip().upper()
        state = cached_states.get(code)
        valid_close = close_data[raw_code].dropna().astype(float)
        if valid_close.empty or not _ama_state_usable(
            state,
            period=period,
            fast_sc=fast_sc,
            slow_sc=slow_sc,
        ):
            if not valid_close.empty:
                bootstrap_columns.append(raw_code)
            continue

        last_dt = pd.Timestamp(state["last_dt"]).floor("D")
        if last_dt not in valid_close.index:
            bootstrap_columns.append(raw_code)
            continue
        cached_close = float(np.asarray(state["close_tail"], dtype=float)[-1])
        current_anchor = float(valid_close.loc[last_dt])
        scale = current_anchor / cached_close if cached_close != 0 else np.nan
        if not np.isfinite(scale) or scale <= 0:
            bootstrap_columns.append(raw_code)
            continue

        tail_dates = pd.DatetimeIndex(state["tail_dates"]).floor("D")
        tail_close = pd.Series(
            np.asarray(state["close_tail"], dtype=float) * scale,
            index=tail_dates,
            name=code,
        )
        tail_ama = pd.Series(
            np.asarray(state["ama_tail"], dtype=float) * scale,
            index=tail_dates,
            name=code,
        )
        new_close = valid_close.loc[valid_close.index > last_dt].rename(code)
        if new_close.empty:
            continue
        combined_close = pd.concat([tail_close, new_close])
        combined_close = combined_close[~combined_close.index.duplicated(keep="last")]
        ama_seed = tail_ama.reindex(combined_close.index)
        components = _seeded_ama_components(
            combined_close,
            ama_seed,
            period=period,
            fast_sc=fast_sc,
            slow_sc=slow_sc,
        )
        if not state_only:
            factors = _ama_signal_frames(
                analyzer,
                combined_close.to_frame(name=code),
                components,
                period=period,
            )
            for name, frame in factors.items():
                result[name].loc[new_close.index, raw_code] = frame.loc[new_close.index, code]
        new_states[code] = _state_from_series(
            code,
            combined_close,
            components["ama_line"][code],
            period=period,
            fast_sc=fast_sc,
            slow_sc=slow_sc,
        )

    if bootstrap_columns:
        valid_series = {
            raw_code: close_data[raw_code].dropna().astype(float)
            for raw_code in bootstrap_columns
        }
        max_rows = max((len(series) for series in valid_series.values()), default=0)
        compact = pd.DataFrame(
            np.nan,
            index=pd.RangeIndex(max_rows),
            columns=bootstrap_columns,
        )
        for raw_code, series in valid_series.items():
            compact.loc[: len(series) - 1, raw_code] = series.to_numpy(dtype=float)
        components = _bootstrap_ama_components(
            compact,
            period=period,
            fast_sc=fast_sc,
            slow_sc=slow_sc,
        )
        factors = (
            {}
            if state_only
            else _ama_signal_frames(analyzer, compact, components, period=period)
        )
        for raw_code, series in valid_series.items():
            row_count = len(series)
            if not state_only:
                for name, frame in factors.items():
                    result[name].loc[series.index, raw_code] = frame[raw_code].iloc[:row_count].to_numpy()
            ama_series = pd.Series(
                components["ama_line"][raw_code].iloc[:row_count].to_numpy(dtype=float),
                index=series.index,
                name=str(raw_code).strip().upper(),
            )
            code = str(raw_code).strip().upper()
            new_states[code] = _state_from_series(
                code,
                series.rename(code),
                ama_series,
                period=period,
                fast_sc=fast_sc,
                slow_sc=slow_sc,
            )

    _queue_ama_states(state_cache_path, new_states)
    return result
