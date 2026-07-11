from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from models.configurable_signal_rules import runner as configurable_runner
from models.zxw_init_10pct_snapshot import runner as pct10_runner
from models.zxw_factor_check_only import runner as zxw_factor_check_runner
from models.zxw_factor_check_profit_threshold_dual_assumption import (
    runner as zxw_factor_check_profit_threshold_dual_assumption_runner,
)
from models.zxw_factor_check_sell_signal_step_position import (
    runner as zxw_factor_check_sell_signal_step_position_runner,
)
from models.zxw_factor_check_sell_signal_profit20_step_position import (
    runner as zxw_factor_check_sell_signal_profit20_step_position_runner,
)
from models.zxw_factor_check_base_threshold import runner as zxw_factor_check_base_threshold_runner

ProgressCallback = Callable[[str, int, str], None]

DEFAULT_MODEL_ID = "configurable_signal_rules"


@dataclass(frozen=True)
class ModelEntry:
    id: str
    title: str
    description_html: str
    web_runnable: bool
    uses_frontend_buy_sell_rules: bool
    run: Callable[..., dict[str, Any]] | None


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


def _doc_zxw_factor_check_profit_threshold_dual_assumption() -> str:
    return (
        "<p><strong>ZXW 组合规则（只为了检验因子策略）（双假设 + 卖出阈值）</strong>"
        "（<code>FactorCheckProfitThresholdDualAssumptionZxwStrategy</code>）。"
        "在双假设模型基础上增加基于平均持仓成本的卖出阈值，并保留前端买入/卖出因子合成。</p>"
        "<p><strong>卖出阈值</strong>：当前收盘价 &gt; 平均持仓成本×<strong>200%</strong> 时清仓；"
        "当前收盘价 &gt; 平均持仓成本×<strong>150%</strong> 且 &lt; 平均持仓成本×<strong>200%</strong> 时卖出约一半，且每轮持仓只执行一次。</p>"
        "<p><strong>买入锁定</strong>：半仓卖出后，只要该标的仍有持仓，就禁止强买与现金等额补仓；"
        "等该标的清仓后重置状态，后续重新出现买入信号时才允许再买。</p>"
        "<p><strong>其余</strong>：去前视；单日 <code>|收盘/昨收−1| &gt; 9.8%</code> 当天不可买卖；"
        "<code>strong_buy_signal≥1</code> 尽量买到 2%；<code>strong_sell_signal≥1</code> 无条件清仓；不做子集穷举。</p>"
        "<p><strong>前端</strong>：须同时配置买入因子与卖出因子（各至少 1 个）。</p>"
    )


def _doc_zxw_factor_check_sell_signal_step_position() -> str:
    return (
        "<p><strong>ZXW 组合规则（只为了检验因子策略）（卖出信号阶梯减仓）</strong>"
        "（<code>zxw_factor_check_sell_signal_step_position</code>）。"
        "基于双假设因子检验模型复制而来，前端卖出因子参与交易。</p>"
        "<p><strong>卖出</strong>：持仓且 <code>strong_sell_signal≥1</code> 时，"
        "以本轮最大持股数作为总仓位基准。低于 <strong>50%</strong> 涨幅时，"
        "每次卖出基准股数的 <strong>10%</strong>，累计最多 <strong>30%</strong>；"
        "高于 <strong>50%</strong> 且低于 <strong>100%</strong> 涨幅时，累计最多 <strong>80%</strong>；"
        "超过 <strong>100%</strong> 涨幅时累计先补到 <strong>80%</strong>，"
        "之后继续出现卖出信号，则再次每次卖出基准股数的 10%。</p>"
        "<p><strong>总仓位基准</strong>：按初始 2% 买入后、本轮未完全清仓前达到的最大持股数记录；"
        "除非完全清仓，否则该基准不随后续部分卖出变化。</p>"
        "<p><strong>其余</strong>：保留去前视、单日涨跌幅不可交易、强买尽量买到 2%、"
        "现金等额补仓等原模型规则；部分卖出后未清仓前禁止强买与现金等额补仓。</p>"
    )


def _doc_zxw_factor_check_sell_signal_profit20_step_position() -> str:
    return (
        "<p><strong>ZXW 组合规则（20%盈利门槛 + 卖出信号阶梯减仓）</strong>"
        "（<code>zxw_factor_check_sell_signal_profit20_step_position</code>）。"
        "基于卖出信号阶梯减仓模型复制而来，前端卖出因子参与交易，但卖出信号需当前盈利超过20%才有效。</p>"
        "<p><strong>卖出</strong>：持仓、<code>strong_sell_signal≥1</code> 且当前收盘价 &gt; 持仓均价×<strong>120%</strong> 时，"
        "以本轮最大持股数作为总仓位基准。低于 <strong>50%</strong> 涨幅时，"
        "每次卖出基准股数的 <strong>10%</strong>，累计最多 <strong>30%</strong>；"
        "高于 <strong>50%</strong> 且低于 <strong>100%</strong> 涨幅时，累计最多 <strong>80%</strong>；"
        "超过 <strong>100%</strong> 涨幅时累计先补到 <strong>80%</strong>，"
        "之后继续出现卖出信号，则再次每次卖出基准股数的 10%。</p>"
        "<p><strong>总仓位基准</strong>：按初始 2% 买入后、本轮未完全清仓前达到的最大持股数记录；"
        "除非完全清仓，否则该基准不随后续部分卖出变化。</p>"
    )


def _doc_zxw_factor_check_base_threshold() -> str:
    return (
        "<p><strong>ZXW 组合规则（因子检验 + 基本面阈值）</strong>"
        "（<code>zxw_factor_check_base_threshold</code>）。"
        "在「双假设 + 卖出阈值」模型基础上，增加买入端基本面硬过滤。</p>"
        "<p><strong>买入过滤</strong>：前端买入因子合成 <code>strong_buy_signal≥1</code> 后，"
        "仅保留同时满足 <code>PE&lt;50</code>、<code>PB&lt;6</code>、<code>ROE&gt;10</code>、"
        "<code>营业收入同比&gt;10</code> 的标的信号。</p>"
        "<p><strong>数据匹配</strong>：基本面读取 QMT 派生表 "
        "<code>D:\\database\\qmt_company_data\\table=factor_fundamental_valuation</code>；"
        "PE 使用 <code>pe_ttm</code>，PB 使用 <code>pb</code>，ROE 使用 <code>roe</code>，"
        "营业收入同比由同表 <code>revenue</code> 按报告期同比计算；均按信号日前最近日频数据匹配。</p>"
        "<p><strong>其余</strong>：保留原模型卖出阈值、单日涨跌幅不可交易、首日回溯建仓与现金补仓规则；不做子集穷举。</p>"
        "<p><strong>前端</strong>：须同时配置买入因子与卖出因子（各至少 1 个）。</p>"
    )


REGISTRY: dict[str, ModelEntry] = {
    "zxw_factor_check_only": ModelEntry(
        id="zxw_factor_check_only",
        title="ZXW 组合规则（只为了检验因子策略）",
        description_html=_doc_zxw_factor_check(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_factor_check_runner.run,
    ),
    "zxw_factor_check_profit_threshold_dual_assumption": ModelEntry(
        id="zxw_factor_check_profit_threshold_dual_assumption",
        title="ZXW组合规则(只为了检验因子策略（双假设）+卖出阈值)",
        description_html=_doc_zxw_factor_check_profit_threshold_dual_assumption(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_factor_check_profit_threshold_dual_assumption_runner.run,
    ),
    "zxw_factor_check_sell_signal_step_position": ModelEntry(
        id="zxw_factor_check_sell_signal_step_position",
        title="ZXW组合规则(卖出信号阶梯减仓)",
        description_html=_doc_zxw_factor_check_sell_signal_step_position(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_factor_check_sell_signal_step_position_runner.run,
    ),
    "zxw_factor_check_sell_signal_profit20_step_position": ModelEntry(
        id="zxw_factor_check_sell_signal_profit20_step_position",
        title="ZXW组合规则(20%盈利门槛+卖出信号阶梯减仓)",
        description_html=_doc_zxw_factor_check_sell_signal_profit20_step_position(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_factor_check_sell_signal_profit20_step_position_runner.run,
    ),
    "zxw_factor_check_base_threshold": ModelEntry(
        id="zxw_factor_check_base_threshold",
        title="ZXW组合规则(基本面叠加：双假设+卖出阈值)",
        description_html=_doc_zxw_factor_check_base_threshold(),
        web_runnable=True,
        uses_frontend_buy_sell_rules=True,
        run=zxw_factor_check_base_threshold_runner.run,
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
        "zxw_factor_check_only",
        "zxw_factor_check_profit_threshold_dual_assumption",
        "zxw_factor_check_sell_signal_step_position",
        "zxw_factor_check_sell_signal_profit20_step_position",
        "zxw_factor_check_base_threshold",
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
