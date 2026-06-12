from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from models.configurable_signal_rules import runner as configurable_runner
from models.hong_ziming_avg_position import runner as hong_runner
from models.zxw_init_10pct_snapshot import runner as pct10_runner
from models.zxw_rule_backtest import runner as zxw_rule_runner
from models.zxw_strong_adjusted_only import runner as zxw_strong_adjusted_runner
from models.zxw_factor_check_only import runner as zxw_factor_check_runner
from models.zxw_factor_check_no_lookahead import runner as zxw_factor_check_no_lookahead_runner
from models.zxw_factor_check_dual_assumption import runner as zxw_factor_check_dual_assumption_runner

ProgressCallback = Callable[[str, int, str], None]

DEFAULT_MODEL_ID = "hong_ziming_avg_position"


@dataclass(frozen=True)
class ModelEntry:
    id: str
    title: str
    description_html: str
    web_runnable: bool
    uses_frontend_buy_sell_rules: bool
    run: Callable[..., dict[str, Any]] | None


def _doc_hong_ziming() -> str:
    return (
        "<p><strong>洪梓铭平均仓位模型</strong>（网页默认，<code>HongZimingAvgPositionStrategy</code>）。"
        "宽表信号列：<code>total_buy_signal</code>、<code>sell_combo_signal</code>、<code>rsi_sell_combo</code>。"
        "数据管线与 <code>models.zxw_rule_backtest.zxw_view_results_full</code> 一致。</p>"
        "<p><strong>每个交易日、每只股票的处理顺序</strong>：先止损与卖点逻辑，再买点（卖点与买点独立）。</p>"
        "<p><strong>卖出 / 减仓</strong></p><ul>"
        "<li><strong>硬止损</strong>：有仓且收盘价 <strong>&lt;</strong> 持仓均价 × <strong>0.8</strong>（约低于成本 20%）→ 该股<strong>清仓</strong>；"
        "并清除该标的卖点连续计数与买点冷静期记录。</li>"
        "<li><strong>组合卖点「连续」两日</strong>：若 <code>sell_combo_signal ≥ 1</code> <strong>或</strong> "
        "<code>rsi_sell_combo ≥ 1</code> 记为当日有卖点。有仓时：<strong>第 1 个连续卖点日</strong>卖出约 "
        "<strong>50%</strong> 持仓（至少 1 股）；<strong>第 2 个连续卖点日</strong>再触发则<strong>清仓</strong>。"
        "若当日<strong>不为</strong>卖点日（两路组合卖点皆未触发），则连续计数清零。</li>"
        "</ul>"
        "<p><strong>买入</strong></p><ul>"
        "<li>起始可视为空仓；仅当 <code>total_buy_signal ≥ 1</code> 才允许买入。</li>"
        "<li><strong>冷静期</strong>：同一标的在上一次买点<strong>成交</strong>的 bar 记为 <code>last</code>，"
        "当前 bar 索引为 <code>bar_ix</code>；若 <code>bar_ix − last ≤ 2</code> 则<strong>禁止</strong>再买（至少再隔 2 根 K 线）。</li>"
        "<li><strong>单票市值上限</strong> = 当日组合总市值 ÷ <strong>50</strong>（与池子股票数量无关）。</li>"
        "<li><strong>单次加仓预算</strong> = min(总市值÷<strong>100</strong>, 距上限的剩余空间, 可用现金/(1+手续费))；"
        "按收盘价折算为<strong>整数股</strong>买入，且加仓后市值不得超过上限。</li>"
        "<li>买点成交后：更新冷静期锚点，并把该标的卖点<strong>连续计数清零</strong>。</li>"
        "</ul>"
        "<p><strong>前端因子</strong>：买卖规则可传，但<strong>不参与</strong>本模型。</p>"
    )


def _doc_zxw_rule() -> str:
    return (
        "<p><strong>ZXW 组合规则</strong>（<code>ZxwRuleBacktestStrategy</code>，<code>zxw_view_results_full</code> 宽表）。"
        "关键列含 <code>total_sell_signal</code>、<code>sell_combo_signal</code>、<code>rsi_sell_combo</code>、"
        "<code>total_buy_signal</code>、<code>bottom_fishing_score</code>、<code>mac_total</code>、"
        "<code>block_halving_future_buy</code> 等。</p>"
        "<p><strong>首日</strong>：对全部有效标的按可用现金等权目标市值<strong>一次建满</strong>（<code>INITIAL_EQUAL_WEIGHT_FULL_POSITION</code>）。</p>"
        "<p><strong>有仓时卖出 / 减仓（单标的循环内，按代码顺序匹配到一条即 continue）</strong></p><ul>"
        "<li><strong>止损</strong>：浮动盈亏 ≤ <strong>−15%</strong>（收盘相对持仓均价）→ <strong>清仓</strong>。</li>"
        "<li><strong>弱卖清仓</strong>：<code>total_sell_signal ≥ 1</code> 且该标的市值权重 <strong>&lt; 1%</strong> → <strong>清仓</strong>。</li>"
        "<li><strong>分档止盈（二选一组合卖点）</strong>：记 <code>either_combo</code> = "
        "(<code>sell_combo_signal≥1</code> 或 <code>rsi_sell_combo≥1</code>)。"
        "若盈利 <strong>&gt; 100%</strong> 且 <code>either_combo</code> 且本档未做过 → 卖出约 <strong>75%</strong> 持仓并记录档位；"
        "否则若盈利 <strong>&gt; 50%</strong> 且 <code>either_combo</code> 且一档未做过 → 卖出约 <strong>50%</strong> 并记录。</li>"
        "<li><strong>分档后回撤加仓</strong>：若已做过 50% 减仓档，从该档后最高价回撤 ≥ <strong>20%</strong> → "
        "加仓现金约 = 组合总市值 × <code>drawdown_add_weight</code>（默认 2.5%），每档仅一次。</li>"
        "<li>若已做过 75% 减仓档，从该档后最高价回撤 ≥ <strong>30%</strong> → 同上规则加仓一次。</li>"
        "</ul>"
        "<p><strong>买入（无仓或加至目标市值）</strong></p><ul>"
        "<li><strong>次买（弱买）</strong>：若 <code>block_halving_future_buy &lt; 1</code>，且 "
        "<code>bottom_fishing_score &gt; 0</code> 且 <code>mac_total &gt; 0</code>，且上一日收盘后"
        "仓位占比门控 <strong>&lt; 80%</strong>（用 <code>notify_cashvalue</code> 写入的上一日仓位比），"
        "且当前市值 &lt; 总市值×<code>max_weight</code>（默认 <strong>5%</strong>）→ 目标市值调至 5%。</li>"
        "<li><strong>强买</strong>：若 <code>block_halving_future_buy &lt; 1</code> 且 <code>total_buy_signal ≥ 1</code>，"
        "且当前市值 &lt; 总市值×5% → 同样目标市值调至 5%。</li>"
        "</ul>"
        "<p><strong>前端因子</strong>：可传，<strong>不参与</strong>上述信号合并。</p>"
    )


def _doc_zxw_rule_profit30() -> str:
    return (
        "<p><strong>ZXW 组合规则（30%盈利分档）</strong>：与「ZXW 组合规则（看结果脚本）」相同管线（"
        "<code>ZxwRuleBacktestStrategy</code> + <code>zxw_view_results_full</code>），"
        "通过 <code>profit_tier_mode=&quot;profit30&quot;</code> 启用下列<strong>分档止盈</strong>；其余（首日满仓、−15% 止损、弱卖、次买/强买、"
        "<code>block_halving_future_buy</code> 等）与默认 ZXW 模型一致。</p>"
        "<p><strong>首日</strong>：对全部有效标的按可用现金等权目标市值<strong>一次建满</strong>。</p>"
        "<p><strong>有仓时卖出 / 减仓（单标的循环内，按代码顺序匹配到一条即 continue）</strong></p><ul>"
        "<li><strong>止损</strong>：浮动盈亏 ≤ <strong>−15%</strong> → <strong>清仓</strong>。</li>"
        "<li><strong>弱卖清仓</strong>：<code>total_sell_signal ≥ 1</code> 且市值权重 <strong>&lt; 1%</strong> → <strong>清仓</strong>。</li>"
        "<li><strong>分档止盈（either_combo）</strong>："
        "<code>either_combo</code> = (<code>sell_combo_signal≥1</code> 或 <code>rsi_sell_combo≥1</code>)。"
        "按 <strong>if / elif</strong> 从高盈利到低（同一日只命中一档）："
        "若盈利 <strong>&gt; 100%</strong> 且 <code>either_combo</code> → <strong>清仓</strong>；"
        "否则若盈利 <strong>&gt; 50%</strong> 且 <code>either_combo</code> 且本档未执行过 → 卖出约 <strong>75%</strong> 持仓；"
        "否则若盈利 <strong>&gt; 30%</strong> 且 <code>either_combo</code> 且本档未执行过 → 卖出约 <strong>50%</strong> 持仓。</li>"
        "<li><strong>分档后回撤加仓</strong>：对「&gt;30% 盈利时已减半」档，从该次减仓后最高价回撤 ≥ <strong>20%</strong> → "
        "加仓约 总市值×2.5%（每档一次）；对「&gt;50% 盈利时已卖约 75%」档，从该次减仓后最高价回撤 ≥ <strong>30%</strong> → 同上加仓一次。</li>"
        "</ul>"
        "<p><strong>买入</strong>：与默认 ZXW 相同（弱买 bottom+mac、强买 total_buy_signal；80% 仓位门控；单票目标 5%）。</p>"
        "<p><strong>前端因子</strong>：可传，<strong>不参与</strong>上述信号合并。</p>"
    )


def _doc_10pct() -> str:
    return (
        "<p><strong>4-28 初始 10% 硬仓位（命名快照）</strong>：与「原版 MAC/KDJ/OBV/抄底」使用<strong>同一策略类</strong> "
        "<code>MacKdjBottomScoreBuyAndHoldStrategy</code>（<code>max_weight=10%</code>）与 <code>zxw_view_results_legacy</code> 数据合并；"
        "「登记次日卖 / 次日买、目标市值 10%、卖后现金再均分回补（100 股一手）」等规则与 <strong>原版 MAC/KDJ</strong> 模型<strong>逐条相同</strong>。</p>"
        "<p>差异仅为运行入口的实验命名（<code>variant_label</code> / snapshot 注记），便于对齐历史 notebook。</p>"
        "<p><strong>前端因子</strong>：可传，<strong>不参与</strong>。</p>"
    )


def _doc_configurable() -> str:
    return (
        "<p><strong>可配置因子买卖规则</strong>（<code>ConfigurableSignalStrategy</code>）。"
        "前端规则经因子引擎生成 <code>buy_signal</code> / <code>sell_signal</code> 写入 feed；"
        "另有固定列 <code>mac_total</code> 等参与「加仓至目标市值」通道（代码变量名 <code>adjusted_buy_signal</code> 实际绑定 "
        "<code>mac_total</code>）。默认 <code>max_weight=5%</code>、<code>drawdown_add_weight=2.5%</code>、100 股一手。</p>"
        "<p><strong>买入</strong></p><ul>"
        "<li><strong>首日</strong>：全部有效标的<strong>等权用尽现金</strong>建仓（<code>INIT_EQUAL_WEIGHT_100PCT</code>）。</li>"
        "<li><strong>回撤加仓（有仓；各档位每标的仅一次）</strong>：已持仓且 <code>buy_signal &gt; 0</code>："
        "若相对成本回撤 ≤ <strong>−30%</strong> → 加仓约 总市值×2.5% 后当日不再处理该标的其它仓内逻辑；"
        "否则若回撤 ≤ <strong>−20%</strong> → 同样加仓一次（与 −30% 档独立计数）。</li>"
        "<li><strong>目标市值通道</strong>：若 <code>mac_total &gt; 0</code> 且未被「满一年腰斩」规则拉黑，"
        "且当前市值 &lt; 总市值×<code>max_weight</code>（5%）→ <code>order_target_value</code> 调至该目标市值。</li>"
        "<li><strong>一年腰斩禁买</strong>：自首次建仓起满 365 日且收盘 ≤ 首次参考价×50% → 该标的不再走上述 <code>mac_total</code> 加仓通道。</li>"
        "</ul>"
        "<p><strong>卖出</strong></p><ul>"
        "<li>已持仓且 <code>sell_signal &gt; 0</code> 且浮动盈亏 <strong>&gt; 50%</strong> → <strong>清仓</strong>。</li>"
        "<li>已持仓且 <code>sell_signal &gt; 0</code> 且浮动盈亏 <strong>&gt; 30%</strong> → 卖出约 <strong>50%</strong> 持仓。</li>"
        "</ul>"
        "<p><strong>前端因子</strong>：<strong>必须</strong>配置买卖规则；未选因子时 <code>buy_signal</code>/<code>sell_signal</code> 多为 0，策略几乎无主动卖信号。</p>"
    )


def _doc_zxw_factor_check() -> str:
    return (
        "<p><strong>ZXW 组合规则（只为了检验因子策略）</strong>（<code>FactorCheckZxwStrategy</code>）。"
        "强买/强卖均严格按前端所选因子及<strong>各自</strong> AND/OR 合成 "
        "<code>strong_buy_signal</code> / <code>strong_sell_signal</code>；"
        "<strong>不做</strong>买入×卖出子集穷举。</p>"
        "<p><strong>首日</strong>：回溯建仓（<code>strong_buy_signal</code>，"
        "信号日至起点前无 <code>strong_sell_signal</code>），单票 <strong>2%</strong>。</p>"
        "<p><strong>买入</strong>：<code>strong_buy_signal≥1</code> 尽量买到 2%；"
        "卖完且强买处理完后现金仍≥10% 时，剩余现金<strong>等额</strong>分给持仓（可突破 2%，仅整股/佣金限制）；"
        "无持仓则保持空仓；<code>block_halving_future_buy</code> 禁买。</p>"
        "<p><strong>卖出</strong>：<code>strong_sell_signal≥1</code> → <strong>无条件清仓</strong>；"
        "无成本止损、无分档止盈。</p>"
        "<p><strong>前端</strong>：须同时配置买入因子与卖出因子（各至少 1 个）。</p>"
    )


def _doc_zxw_factor_check_no_lookahead() -> str:
    return (
        "<p><strong>ZXW 组合规则（只为了检验因子策略）（去前视）</strong>（<code>FactorCheckZxwStrategy</code>）。"
        "与「只为了检验因子策略」相同：强买/强卖按前端因子及各自 AND/OR 合成；"
        "<strong>不做</strong>买入×卖出子集穷举。</p>"
        "<p><strong>差异</strong>：关闭 <code>block_halving_future_buy</code>（无「当年第5日→次年第5日腰斩」前视禁买）；"
        "行情不再向后扩展 14 个月。</p>"
        "<p><strong>首日</strong>：回溯建仓（<code>strong_buy_signal</code>，"
        "信号日至起点前无 <code>strong_sell_signal</code>），单票 <strong>2%</strong>。</p>"
        "<p><strong>买入</strong>：<code>strong_buy_signal≥1</code> 尽量买到 2%；"
        "卖完且强买处理完后现金仍≥10% 时，剩余现金<strong>等额</strong>分给持仓（可突破 2%，仅整股/佣金限制）；"
        "无持仓则保持空仓。</p>"
        "<p><strong>卖出</strong>：<code>strong_sell_signal≥1</code> → <strong>无条件清仓</strong>。</p>"
        "<p><strong>前端</strong>：须同时配置买入因子与卖出因子（各至少 1 个）。</p>"
    )


def _doc_zxw_factor_check_dual_assumption() -> str:
    return (
        "<p><strong>ZXW 组合规则（只为了检验因子策略）（双假设）</strong>（<code>FactorCheckDualAssumptionZxwStrategy</code>）。"
        "在去前视因子检验基础上，增加：当日 <code>|收盘/昨收−1| &gt; 9.8%</code> 时该标的<strong>当天不可买卖</strong>。</p>"
        "<p><strong>其余</strong>：关闭 <code>block_halving_future_buy</code>；首日回溯建仓单票 2%；"
        "<code>strong_buy_signal≥1</code> 尽量买到 2%；"
        "<code>strong_sell_signal≥1</code> 无条件清仓；现金≥10% 时等额补仓；不做子集穷举。</p>"
        "<p><strong>前端</strong>：须同时配置买入因子与卖出因子（各至少 1 个）。</p>"
    )


def _doc_zxw_strong_adjusted() -> str:
    return (
        "<p><strong>ZXW 组合规则（只采用强点交易策略）</strong>（<code>StrongAdjustedZxwStrategy</code>）。"
        "宽表与 <code>zxw_view_results_full</code> 一致，需列 <code>total_buy_signal</code>（前端「总买入信号」）。"
        "强买由前端<strong>买入因子</strong>合成（<code>strong_buy_signal</code>）；"
        "止盈由前端<strong>卖出因子</strong>合成（<code>strong_sell_signal</code>，遍历子集只影响止盈）；"
        "止损仍用宽表 <code>total_sell_signal</code>（不随卖出子集变化）。"
        "网页「参数遍历」走 <code>optuna_strong_adjusted_study</code>："
        "<strong>穷举全部</strong>非空买入子集 × 非空卖出子集；命名含 <code>_买…</code> 与 <code>_卖…</code>。</p>"
        "<p><strong>首日</strong>：<code>start_date</code> 前按日历倒序扫 <code>strong_buy_signal≥1</code>（买入因子合成），"
        "且从信号日（含）到 <code>start_date</code>（不含）无 <code>total_sell_signal</code>；最多 50 只、每只 5%。</p>"
        "<p><strong>止损</strong>：收盘 &lt; 均价×0.8 预挂；<code>total_sell_signal≥1</code> 时清仓。</p>"
        "<p><strong>止盈</strong>（写死）：浮盈 &gt;30% / &gt;60% / &gt;100% 预挂；<code>total_sell_signal≥1</code> 时卖原仓 60% / 85% / 清仓。</p>"
        "<p><strong>强买</strong>：<code>strong_buy_signal≥1</code>；单票上限 5%（<code>max_weight</code>）；仓位&lt;80% 时补买与余款等分（均不超过 5%）。</p>"
        "<p><strong>前端</strong>：需配置<strong>买入因子</strong>与<strong>卖出因子</strong>（参数遍历时各至少 1 个）。</p>"
    )


REGISTRY: dict[str, ModelEntry] = {
    "hong_ziming_avg_position": ModelEntry(
        id="hong_ziming_avg_position",
        title="洪梓铭平均仓位模型",
        description_html=_doc_hong_ziming(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=False,
        run=hong_runner.run,
    ),
    "zxw_rule_backtest": ModelEntry(
        id="zxw_rule_backtest",
        title="ZXW 组合规则（看结果脚本）",
        description_html=_doc_zxw_rule(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=False,
        run=zxw_rule_runner.run,
    ),
    "zxw_rule_backtest_profit30": ModelEntry(
        id="zxw_rule_backtest_profit30",
        title="ZXW 组合规则（30%盈利分档）",
        description_html=_doc_zxw_rule_profit30(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=False,
        run=zxw_rule_runner.run_profit30_tier,
    ),
    "zxw_strong_adjusted_only": ModelEntry(
        id="zxw_strong_adjusted_only",
        title="ZXW 组合规则（只采用强点交易策略）",
        description_html=_doc_zxw_strong_adjusted(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_strong_adjusted_runner.run,
    ),
    "zxw_factor_check_only": ModelEntry(
        id="zxw_factor_check_only",
        title="ZXW 组合规则（只为了检验因子策略）",
        description_html=_doc_zxw_factor_check(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_factor_check_runner.run,
    ),
    "zxw_factor_check_no_lookahead": ModelEntry(
        id="zxw_factor_check_no_lookahead",
        title="ZXW 组合规则（只为了检验因子策略）（去前视）",
        description_html=_doc_zxw_factor_check_no_lookahead(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_factor_check_no_lookahead_runner.run,
    ),
    "zxw_factor_check_dual_assumption": ModelEntry(
        id="zxw_factor_check_dual_assumption",
        title="ZXW 组合规则（只为了检验因子策略）（双假设）",
        description_html=_doc_zxw_factor_check_dual_assumption(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_factor_check_dual_assumption_runner.run,
    ),
    "zxw_init_10pct_snapshot": ModelEntry(
        id="zxw_init_10pct_snapshot",
        title="4-28 初始10%硬仓位（命名快照）",
        description_html=_doc_10pct(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=False,
        run=pct10_runner.run,
    ),
    "configurable_signal_rules": ModelEntry(
        id="configurable_signal_rules",
        title="可配置因子买卖规则",
        description_html=_doc_configurable(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=configurable_runner.run,
    ),
}


def list_models_public() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for e in REGISTRY.values():
        rows.append(
            {
                "id": e.id,
                "title": e.title,
                "description_html": e.description_html,
                "web_runnable": e.web_runnable,
                "uses_frontend_buy_sell_rules": e.uses_frontend_buy_sell_rules,
            }
        )
    order = [
        "hong_ziming_avg_position",
        "zxw_rule_backtest",
        "zxw_rule_backtest_profit30",
        "zxw_strong_adjusted_only",
        "zxw_factor_check_only",
        "zxw_factor_check_no_lookahead",
        "zxw_factor_check_dual_assumption",
        "zxw_init_10pct_snapshot",
        "configurable_signal_rules",
    ]
    rank = {k: i for i, k in enumerate(order)}
    rows.sort(key=lambda r: rank.get(str(r.get("id")), 99))
    return rows


def resolve_model_id(raw: Any) -> str:
    mid = str(raw or "").strip()
    return mid if mid else DEFAULT_MODEL_ID


def run_registered_model(
    *,
    model_id: str,
    codes: list[str],
    start_date: str,
    end_date: str,
    run_name: str,
    frontend_buy_rules: Any,
    frontend_sell_rules: Any,
    frontend_buy_operator: str,
    frontend_sell_operator: str,
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    entry = REGISTRY.get(model_id)
    if entry is None:
        known = ", ".join(sorted(REGISTRY.keys()))
        raise ValueError(f"未知的 adopt_model={model_id!r}。可选: {known}")
    if not entry.web_runnable or entry.run is None:
        raise ValueError(
            f"模型 {model_id!r} 不支持网页回测任务；请改用 web_runnable 为 true 的 adopt_model。"
        )
    return entry.run(
        codes=codes,
        start_date=start_date,
        end_date=end_date,
        run_name=run_name,
        frontend_buy_rules=frontend_buy_rules,
        frontend_sell_rules=frontend_sell_rules,
        frontend_buy_operator=frontend_buy_operator,
        frontend_sell_operator=frontend_sell_operator,
        progress=progress,
    )
