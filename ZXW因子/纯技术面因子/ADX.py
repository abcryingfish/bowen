from ast import Return
import pandas as pd
import numpy as np


# 引用方式示例
'''
from strategys.技术面.ADX import ADX
adx_analyzer = ADX()
signal_adx_buy, signal_adx_sell = adx_analyzer.get_total_signal_matrix(
    High_data, Low_data, Close_data, Close_data,
    adx_period=14, divergence_threshold=0.02
)
signals_adx_search = adx_analyzer.get_detailed_signals_dataframe(
    High_data, Low_data, Close_data, Close_data
)
)
'''


# 指标缩写解释及公式
'''ADX相关参数及计算公式

ADX：Average Directional Index（平均趋向指数）
用于衡量趋势强度，不指示方向，值越高趋势越强（通常>25为强趋势，<20为弱趋势）

TR：True Range（真实波幅）
TR = max(最高价-最低价, |最高价-前收盘价|, |最低价-前收盘价|)

+DM：Positive Directional Movement（正趋向变动）
当当前最高价-前最高价 > 前最低价-当前最低价 且 为正时，+DM=当前最高价-前最高价，否则为0

-DM：Negative Directional Movement（负趋向变动）
当前最低价-前最低价 > 前最高价-当前最高价 且 为正时，-DM=前最低价-当前最低价，否则为0

+DI：Positive Directional Indicator（正趋向指标）
+DI = 100 * (+DM的N期平滑和 / TR的N期平滑和)

-DI：Negative Directional Indicator（负趋向指标）
-DI = 100 * (-DM的N期平滑和 / TR的N期平滑和)

DX：Directional Index（趋向指数）
DX = 100 * (|+DI - -DI| / (+DI + -DI))

ADX：Average Directional Index（平均趋向指数）
ADX = DX的N期移动平均

优点：能有效识别趋势强度，适合趋势跟踪，过滤无趋势震荡行情
缺点：滞后性明显，在剧烈反转行情反应迟缓，单独使用无法判断趋势方向
'''


class ADX:
    def __init__(self):
        self.signal_strength = {
            # 交叉信号
            "golden_cross": 0.5,          # +DI上穿-DI（金叉）：中等看涨
            "death_cross": -0.5,          # +DI下穿-DI（死叉）：中等看跌
            # 趋势强度信号
            "strong_breakthrough": 0.6,   # ADX上穿25（进入强趋势）：趋势强化
            "weak_breakthrough": -0.6,    # ADX下穿25（进入弱趋势）：趋势减弱
            # 趋势确认信号
            "trend_confirmation": 0.5,    # ADX>25且上升：趋势确认
            "trend_weakening": -0.5,      # ADX>25且下降：趋势减弱
            # 背离信号
            "top_divergence": -0.7,       # 顶背离：强看跌
            "bottom_divergence": 0.7,     # 底背离：强看涨
            # 形态信号
            "double_bottom": 0.6,         # 双底形态：看涨
            "double_top": -0.6,           # 双顶形态：看跌
            "triple_bottom": 0.7,         # 三重底：强看涨
            "triple_top": -0.7,           # 三重顶：强看跌
        }

        # 所有信号名称列表
        self.all_signals = list(self.signal_strength.keys())

    def get_adx_components(self, high, low, close, adx_period=14):
        """计算ADX核心组件（TR、+DM、-DM、+DI、-DI、DX、ADX）"""
        # 计算真实波幅TR
        hl = high - low
        hc = abs(high - close.shift(1))
        lc = abs(low - close.shift(1))
        tr = pd.DataFrame(np.max([hl, hc, lc], axis=0), index=high.index, columns=high.columns)
        
        # 计算趋向变动+DM、-DM
        plus_dm_raw = high - high.shift(1)
        minus_dm_raw = low.shift(1) - low
        plus_dm = np.where((plus_dm_raw > minus_dm_raw) & (plus_dm_raw > 0), plus_dm_raw, 0)
        minus_dm = np.where((minus_dm_raw > plus_dm_raw) & (minus_dm_raw > 0), minus_dm_raw, 0)
        
        # 计算平滑的TR、+DM、-DM
        tr_smooth = tr.rolling(window=adx_period, min_periods=1).sum()
        plus_dm_smooth = pd.DataFrame(plus_dm, index=high.index, columns=high.columns).rolling(window=adx_period, min_periods=1).sum()
        minus_dm_smooth = pd.DataFrame(minus_dm, index=high.index, columns=high.columns).rolling(window=adx_period, min_periods=1).sum()
        
        # 计算+DI、-DI
        plus_di = 100 * (plus_dm_smooth / tr_smooth)
        minus_di = 100 * (minus_dm_smooth / tr_smooth)
        
        # 计算DX和ADX
        di_sum = plus_di + minus_di
        di_diff = abs(plus_di - minus_di)
        dx = np.where(di_sum != 0, 100 * (di_diff / di_sum), 0)
        adx_line = pd.DataFrame(dx, index=high.index, columns=high.columns).rolling(window=adx_period, min_periods=1).mean()
        
        # 计算ADX斜率（趋势方向）
        adx_slope = adx_line - adx_line.shift(1)
        
        return {
            'tr': tr,
            'plus_dm': plus_dm,
            'minus_dm': minus_dm,
            'plus_di': plus_di,
            'minus_di': minus_di,
            'dx': dx,
            'adx_line': adx_line,
            'adx_slope': adx_slope
        }

    def cross_signals(self, plus_di, minus_di):
        """生成金叉/死叉信号"""
        # 金叉：+DI上穿-DI
        golden_cross = ((plus_di.shift(1) <= minus_di.shift(1)) & 
                       (plus_di > minus_di)).astype(float) * self.signal_strength["golden_cross"]
        
        # 死叉：+DI下穿-DI
        death_cross = ((plus_di.shift(1) >= minus_di.shift(1)) & 
                      (plus_di < minus_di)).astype(float) * self.signal_strength["death_cross"]
        
        return {
            "golden_cross": golden_cross,
            "death_cross": death_cross
        }

    def trend_strength_signals(self, adx_line, adx_slope):
        """生成趋势强度相关信号"""
        # ADX上穿25（进入强趋势）
        strong_breakthrough = ((adx_line.shift(1) <= 25) & 
                              (adx_line > 25)).astype(float) * self.signal_strength["strong_breakthrough"]
        
        # ADX下穿25（进入弱趋势）
        weak_breakthrough = ((adx_line.shift(1) >= 25) & 
                            (adx_line < 25)).astype(float) * self.signal_strength["weak_breakthrough"]
        
        # 趋势确认（ADX>25且上升）
        trend_confirmation = ((adx_line > 25) & 
                             (adx_slope > 0)).astype(float) * self.signal_strength["trend_confirmation"]
        
        # 趋势减弱（ADX>25且下降）
        trend_weakening = ((adx_line > 25) & 
                          (adx_slope < 0)).astype(float) * self.signal_strength["trend_weakening"]
        
        return {
            "strong_breakthrough": strong_breakthrough,
            "weak_breakthrough": weak_breakthrough,
            "trend_confirmation": trend_confirmation,
            "trend_weakening": trend_weakening
        }

    def divergence_signals(self, adx_line, close, divergence_threshold=0.02):
        """生成背离信号（顶背离/底背离）"""
        # 顶背离：价格创新高，ADX未创新高
        price_high = close.rolling(window=10).max()
        adx_high = adx_line.rolling(window=10).max()
        top_divergence = ((close > price_high.shift(1) * (1 + divergence_threshold)) & 
                         (adx_line < adx_high.shift(1) * (1 - divergence_threshold)) & 
                         (adx_line > 25)).astype(float) * self.signal_strength["top_divergence"]
        
        # 底背离：价格创新低，ADX未创新低
        price_low = close.rolling(window=10).min()
        adx_low = adx_line.rolling(window=10).min()
        bottom_divergence = ((close < price_low.shift(1) * (1 - divergence_threshold)) & 
                           (adx_line > adx_low.shift(1) * (1 + divergence_threshold)) & 
                           (adx_line < 25)).astype(float) * self.signal_strength["bottom_divergence"]
        
        return {
            "top_divergence": top_divergence,
            "bottom_divergence": bottom_divergence
        }

    def pattern_signals(self, adx_line):
        """生成形态信号（双底/双顶、三重底/三重顶）"""
        # 双底形态
        double_bottom = ((adx_line.shift(2) < adx_line.shift(1)) & 
                        (adx_line < adx_line.shift(1)) & 
                        (abs(adx_line.shift(2) - adx_line) < 5) & 
                        (adx_line.shift(1) < 30)).astype(float) * self.signal_strength["double_bottom"]
        
        # 双顶形态
        double_top = ((adx_line.shift(2) > adx_line.shift(1)) & 
                     (adx_line > adx_line.shift(1)) & 
                     (abs(adx_line.shift(2) - adx_line) < 5) & 
                     (adx_line.shift(1) > 30)).astype(float) * self.signal_strength["double_top"]
        
        # 三重底形态
        triple_bottom = ((adx_line.shift(3) < adx_line.shift(2)) & 
                        (adx_line.shift(1) < adx_line.shift(2)) & 
                        (adx_line < adx_line.shift(2)) & 
                        (abs(adx_line.shift(3) - adx_line.shift(1)) < 5) & 
                        (abs(adx_line.shift(1) - adx_line) < 5) & 
                        (adx_line.shift(2) < 30)).astype(float) * self.signal_strength["triple_bottom"]
        
        # 三重顶形态
        triple_top = ((adx_line.shift(3) > adx_line.shift(2)) & 
                     (adx_line.shift(1) > adx_line.shift(2)) & 
                     (adx_line > adx_line.shift(2)) & 
                     (abs(adx_line.shift(3) - adx_line.shift(1)) < 5) & 
                     (abs(adx_line.shift(1) - adx_line) < 5) & 
                     (adx_line.shift(2) > 30)).astype(float) * self.signal_strength["triple_top"]
        
        return {
            "double_bottom": double_bottom,
            "double_top": double_top,
            "triple_bottom": triple_bottom,
            "triple_top": triple_top
        }

    def get_total_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, adx_period=14, divergence_threshold=0.02, enabled_signals=None):
        """
        整合所有ADX信号，生成买卖信号强度矩阵
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，行=时间，列=标的
            adx_period: int，ADX计算周期
            divergence_threshold: float，背离判断阈值
            enabled_signals: list，指定启用的信号名称
        
        返回:
            sum_buy, sum_sell: pd.DataFrame，买卖信号强度矩阵
        """
        # 1. 处理启用信号
        if enabled_signals is None:
            enabled_signals = self.all_signals
        
        # 2. 初始化信号矩阵（只使用High_data, Low_data, Close_data）
        sum_buy = pd.DataFrame(0, index=Close_data.index, columns=Close_data.columns)
        sum_sell = pd.DataFrame(0, index=Close_data.index, columns=Close_data.columns)
        
        # 3. 计算ADX核心组件
        adx_components = self.get_adx_components(High_data, Low_data, Close_data, adx_period)
        
        # 4. 获取各类信号
        cross_sigs = self.cross_signals(adx_components['plus_di'], adx_components['minus_di'])
        trend_strength_sigs = self.trend_strength_signals(adx_components['adx_line'], adx_components['adx_slope'])
        divergence_sigs = self.divergence_signals(adx_components['adx_line'], Close_data, divergence_threshold)
        pattern_sigs = self.pattern_signals(adx_components['adx_line'])
        
        # 5. 合并所有信号
        all_signals_dict = {**cross_sigs, **trend_strength_sigs, **divergence_sigs, **pattern_sigs}
        
        # 6. 累加信号强度
        for signal_name, signal_matrix in all_signals_dict.items():
            if signal_name in enabled_signals and signal_matrix is not None:
                buy_mask = signal_matrix > 0
                sell_mask = signal_matrix < 0
                sum_buy += signal_matrix.where(buy_mask, 0)
                sum_sell += signal_matrix.where(sell_mask, 0)
        
        # 7. 前N期数据置零（避免计算初期信号不稳定）
        sum_buy.iloc[:adx_period*2] = 0
        sum_sell.iloc[:adx_period*2] = 0
        
        return sum_buy, sum_sell

    def _convert_signal_matrix_to_records(self, signal_matrix, signal_name, date_index, stock_columns):
        """将信号矩阵转换为记录列表"""
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

    def get_detailed_signals_dataframe(self, Open_data, High_data, Low_data, Close_data, Volume, adx_period=14, divergence_threshold=0.02):
        """
        获取详细的ADX信号DataFrame
        
        返回:
            signals_df: DataFrame，包含 Date, Contract, direction, signal_name, strength
        """
        # 1. 计算ADX核心组件（只使用High_data, Low_data, Close_data）
        adx_components = self.get_adx_components(High_data, Low_data, Close_data, adx_period)
        
        # 2. 获取各类信号
        cross_sigs = self.cross_signals(adx_components['plus_di'], adx_components['minus_di'])
        trend_strength_sigs = self.trend_strength_signals(adx_components['adx_line'], adx_components['adx_slope'])
        divergence_sigs = self.divergence_signals(adx_components['adx_line'], Close_data, divergence_threshold)
        pattern_sigs = self.pattern_signals(adx_components['adx_line'])
        
        # 3. 转换为记录列表
        from itertools import chain
        signal_processors = [
            (cross_sigs, "交叉信号"),
            (trend_strength_sigs, "趋势强度信号"),
            (divergence_sigs, "背离信号"),
            (pattern_sigs, "形态信号")
        ]
        
        all_records = list(chain.from_iterable(
            self._convert_signal_matrix_to_records(signal_matrix, signal_name, High_data.index, High_data.columns)
            for processor, category in signal_processors
            for signal_name, signal_matrix in processor.items()
        ))
        
        # 4. 创建并返回DataFrame
        if all_records:
            signals_df = pd.DataFrame(all_records)
            signals_df = signals_df.sort_values(['Date', 'Contract']).reset_index(drop=True)
        else:
            signals_df = pd.DataFrame(columns=['Date', 'Contract', 'direction', 'signal_name', 'strength'])
        
        return signals_df

    def get_multi_index_signal_matrix(self, Open_data, High_data, Low_data, Close_data, Volume, 
                                      adx_period=14, divergence_threshold=0.02, enabled_signals=None):
        """
        【新增方法】生成Multi-index格式的信号矩阵
        
        这是一个通用方法，可以被其他类似的技术指标类复用。
        
        参数:
            Open_data, High_data, Low_data, Close_data, Volume: pd.DataFrame，OHLC数据
            adx_period: int，ADX计算周期，默认14
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
            df = adx_analyzer.get_multi_index_signal_matrix(
                Open_data, High_data, Low_data, Close_data, Volume
            )
            
            # 获取特定信号
            df = adx_analyzer.get_multi_index_signal_matrix(
                Open_data, High_data, Low_data, Close_data, Volume,
                enabled_signals=['golden_cross', 'death_cross', 'top_divergence']
            )
            
            # 查询特定日期和合约的信号
            df.loc[(20240101, 'AAPL'), :]
            
            # 查询特定信号的所有记录（非零）
            df[df['golden_cross'] != 0]['golden_cross']
        """
        
        # 1. 计算ADX核心组件
        adx_components = self.get_adx_components(High_data, Low_data, Close_data, adx_period)
        
        # 2. 获取各类信号
        cross_sigs = self.cross_signals(adx_components['plus_di'], adx_components['minus_di'])
        trend_strength_sigs = self.trend_strength_signals(adx_components['adx_line'], adx_components['adx_slope'])
        divergence_sigs = self.divergence_signals(adx_components['adx_line'], Close_data, divergence_threshold)
        pattern_sigs = self.pattern_signals(adx_components['adx_line'])
        
        # 3. 合并所有信号字典
        all_signals_dict = {**cross_sigs, **trend_strength_sigs, **divergence_sigs, **pattern_sigs}
        
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
            
            # 7. 屏蔽初始无效行（前 adx_period*2 行）
            min_valid_rows = adx_period * 2
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

    # def get_factor_matrices(self, High_data, Low_data, Close_data, adx_period=14, divergence_threshold=0.02):
    #         """
    #         直接生成多个因子矩阵，每个因子对应一个 DataFrame。
    #         返回格式: { 'factor_name': pd.DataFrame, ... }
    #         """
    #         # 1. 计算基础组件
    #         comp = self.get_adx_components(High_data, Low_data, Close_data, adx_period)
            
    #         # 2. 获取原始信号字典
    #         cross = self.cross_signals(comp['plus_di'], comp['minus_di'])
    #         strength = self.trend_strength_signals(comp['adx_line'], comp['adx_slope'])
    #         divergence = self.divergence_signals(comp['adx_line'], Close_data, divergence_threshold)
    #         patterns = self.pattern_signals(comp['adx_line'])

    #         # 3. 封装为独立的因子矩阵
    #         # 我们可以选择合并同类型的细分信号，使矩阵更具代表性
    #         factors = {
    #             # 交叉类因子：合并金叉和死叉
    #             "factor_adx_cross": cross["golden_cross"] + cross["death_cross"],
                
    #             # 突破类因子：合并强弱突破
    #             "factor_adx_breakout": strength["strong_breakthrough"] + strength["weak_breakthrough"],
                
    #             # 趋势持续因子：合并确认和减弱
    #             "factor_adx_persistence": strength["trend_confirmation"] + strength["trend_weakening"],
                
    #             # 背离因子：合并顶背离和底背离
    #             "factor_adx_divergence": divergence["top_divergence"] + divergence["bottom_divergence"],
                
    #             # 形态因子：合并所有形态信号
    #             "factor_adx_pattern": (patterns["double_bottom"] + patterns["triple_bottom"] + 
    #                                 patterns["double_top"] + patterns["triple_top"])
    #         }

    #         # 4. 统一处理：去除计算初期的不稳定数据
    #         for name in factors:
    #             factors[name].iloc[:adx_period * 2] = 0
                
    #         return factors
    

    def get_factor_matrices(self, High_data, Low_data, Close_data, adx_period=14, divergence_threshold=0.02):
        """
        将所有原子信号拆分为独立的因子矩阵。
        返回格式: { 'signal_name': pd.DataFrame(Date x Contract), ... }
        """
        # 1. 计算 ADX 核心组件
        comp = self.get_adx_components(High_data, Low_data, Close_data, adx_period)
        
        # 2. 获取各类信号字典（这些字典内部已经是独立的 DataFrame 了）
        cross_sigs = self.cross_signals(comp['plus_di'], comp['minus_di'])
        trend_strength_sigs = self.trend_strength_signals(comp['adx_line'], comp['adx_slope'])
        divergence_sigs = self.divergence_signals(comp['adx_line'], Close_data, divergence_threshold)
        pattern_sigs = self.pattern_signals(comp['adx_line'])

        # 3. 合并所有信号到一个大字典中
        # 使用 ** 语法合并多个字典
        all_factors = {
            **cross_sigs,
            **trend_strength_sigs,
            **divergence_sigs,
            **pattern_sigs
        }

        # 4. 统一处理：去除计算初期的不稳定数据
        for name, df in all_factors.items():
            if df is not None:
                # 前 adx_period*2 行置 0，避免冷启动噪音
                df.iloc[:adx_period * 2] = 0.0
            else:
                # 理论上不会走到这里，防御性代码
                all_factors[name] = pd.DataFrame(0.0, index=Close_data.index, columns=Close_data.columns)

        return all_factors