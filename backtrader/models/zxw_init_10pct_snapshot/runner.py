from __future__ import annotations

from typing import Any, Callable

from models.zxw_legacy_mac_kdj_bottom.runner import run as legacy_run

ProgressCallback = Callable[[str, int, str], None]


def run(
    *,
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
    out = legacy_run(
        codes=codes,
        start_date=start_date,
        end_date=end_date,
        run_name=run_name,
        frontend_buy_rules=frontend_buy_rules,
        frontend_sell_rules=frontend_sell_rules,
        frontend_buy_operator=frontend_buy_operator,
        frontend_sell_operator=frontend_sell_operator,
        progress=progress,
        variant_label="zxw_init_10pct_snapshot",
    )
    cfg = out.get("config")
    if isinstance(cfg, dict):
        cfg["snapshot_note"] = (
            "命名对应历史上 4-28 初始10%硬仓位 notebook 实验；引擎与 zxw_legacy_mac_kdj_bottom 相同（MacKdjBottomScoreBuyAndHoldStrategy，max_weight=10%）。"
        )
    summ = out.get("summary")
    if isinstance(summ, dict):
        summ["模型说明快照"] = cfg.get("snapshot_note") if isinstance(cfg, dict) else ""
    return out
