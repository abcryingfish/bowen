"""Incremental orchestration for the style monitor ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from .config import INITIAL_CASH, INITIAL_DATE, LOT_SIZE, MIN_FACTOR_COVERAGE, STYLE_MONITOR_DB_PATH, MODEL_DEFINITIONS, build_config_hash, is_rebalance_day
from .data import StyleDataSource
from .portfolio import PortfolioState, build_target_shares, mark_to_market, rebalance_at_close, select_style_legs
from .repository import LegDayPayload, ModelDayPayload, StyleMonitorRepository


class StyleMonitorPaused(RuntimeError):
    pass


def _definition_map():
    return {item.model_id: item for item in MODEL_DEFINITIONS}


def run_incremental_update(*, model_ids=None, through_date: date | None = None, progress: Callable[[str, int, str], None] | None = None, database_path=None, data_source=None, repository=None) -> dict[str, Any]:
    source = data_source or StyleDataSource()
    repo = repository or StyleMonitorRepository(database_path or STYLE_MONITOR_DB_PATH)
    repo.initialize_schema()
    definitions = _definition_map()
    selected = [definitions[item] for item in (model_ids or list(definitions))]
    latest_dates = {item.model_id: source.latest_common_date(item.factor_name) for item in selected}
    upper = through_date or max((value for value in latest_dates.values() if value), default=None)
    if upper is None:
        return {"completed_models": [], "paused_models": [], "failed_models": [], "latest_dates": {}, "processed_days": {}}

    model_meta = {}
    tasks = []
    for definition in selected:
        version = repo.ensure_model_version(definition, build_config_hash(definition))
        state = repo.get_run_state(version)
        start = (state.last_success_date + timedelta(days=1)) if state.last_success_date else source.first_usable_date(definition.factor_name, INITIAL_DATE, MIN_FACTOR_COVERAGE)
        model_upper = min(upper, latest_dates[definition.model_id]) if latest_dates[definition.model_id] else None
        if start is None or model_upper is None or start > model_upper:
            continue
        dates = source.available_market_dates(start, model_upper)
        model_meta[definition.model_id] = {"definition": definition, "version": version, "run_state": state, "dates": dates}
        tasks.extend((trade_date, definition.model_id) for trade_date in dates)
    tasks.sort(key=lambda item: (item[0], list(definitions).index(item[1])))
    total = len(tasks)
    completed = 0
    results = {"completed_models": [], "paused_models": [], "failed_models": [], "latest_dates": {}, "processed_days": {}}
    states: dict[tuple[str, str], PortfolioState] = {}
    navs: dict[tuple[str, str], float] = {}
    rebalance_dates: dict[str, date | None] = {model_id: meta["run_state"].last_rebalance_date for model_id, meta in model_meta.items()}
    for meta in model_meta.values():
        for leg in ("high", "low"):
            restored_state, restored_nav = repo.load_portfolio_state(meta["version"], leg)
            states[(meta["version"], leg)] = restored_state
            if restored_nav is not None:
                navs[(meta["version"], leg)] = restored_nav
    blocked: set[str] = set()
    for trade_date, model_id in tasks:
        completed += 1
        meta = model_meta[model_id]
        if model_id in blocked:
            continue
        definition = meta["definition"]
        version = meta["version"]
        calendar = meta["dates"]
        try:
            due = is_rebalance_day(trade_date, rebalance_dates[model_id], definition.rebalance_frequency, calendar)
            snapshot = source.build_eligible_snapshot(trade_date, definition.factor_name) if due else None
            if due and float(snapshot.attrs.get("factor_coverage", 0.0)) < MIN_FACTOR_COVERAGE:
                message = f"因子覆盖率 {float(snapshot.attrs.get('factor_coverage', 0.0)):.2%} 低于 80.00%"
                blocked.add(model_id)
                results["paused_models"].append({"model_id": model_id, "date": trade_date.isoformat(), "message": message})
                if not meta["run_state"].last_success_date:
                    raise StyleMonitorPaused(message)
                continue
            legs = {}
            selections = select_style_legs(snapshot, 0.20, 200) if due else {"high": [], "low": []}
            for leg in ("high", "low"):
                state = states.setdefault((version, leg), PortfolioState(INITIAL_CASH, {}, {}))
                if due:
                    codes = [item.code for item in selections[leg]]
                    prices = {str(row.htsc_code): float(row.close) for row in snapshot.itertuples() if str(row.htsc_code) in codes and float(row.close) > 0}
                    target = build_target_shares(codes, prices, mark_to_market(state, prices).total_asset, 0.0003, LOT_SIZE)
                    execution = rebalance_at_close(state, target, prices, 0.0003)
                    state = execution.state
                    rebalance_dates[model_id] = trade_date
                else:
                    prices = source.close_prices(trade_date, list(state.positions))
                    execution = type("Execution", (), {"trades": [], "total_commission": 0.0, "turnover": 0.0})()
                valuation = mark_to_market(state, prices)
                state = PortfolioState(state.cash, dict(state.positions), {**state.last_prices, **valuation.prices})
                previous_nav = navs.get((version, leg), 100.0)
                current_nav = valuation.total_asset / INITIAL_CASH * 100.0
                positions = [{"htsc_code": code, "score": next((item.score for item in selections[leg] if item.code == code), None), "rank": next((item.rank for item in selections[leg] if item.code == code), None), "target_weight": 1.0 / len(state.positions) if state.positions else 0.0, "actual_weight": shares * valuation.prices.get(code, 0.0) / valuation.total_asset if valuation.total_asset else 0.0, "shares": shares, "price": valuation.prices.get(code, 0.0), "market_value": shares * valuation.prices.get(code, 0.0), "stale_price": code in valuation.stale_codes} for code, shares in state.positions.items()]
                trade_rows = [{"htsc_code": trade.code, "side": trade.side, "shares": trade.shares, "price": trade.price, "trade_value": trade.trade_value, "commission": trade.commission} for trade in getattr(execution, "trades", [])]
                legs[leg] = LegDayPayload(valuation.total_asset - valuation.market_value, valuation.market_value, valuation.total_asset, current_nav, current_nav / previous_nav - 1.0 if previous_nav else None, current_nav / 100.0 - 1.0, getattr(execution, "turnover", 0.0), getattr(execution, "total_commission", 0.0), due, float(snapshot.attrs.get("factor_coverage")) if due else None, len(valuation.stale_codes), "ok", "", positions, trade_rows)
                states[(version, leg)] = state
                navs[(version, leg)] = current_nav
            repo.write_model_day(ModelDayPayload(version, model_id, build_config_hash(definition), trade_date, rebalance_dates[model_id], legs))
            results["processed_days"][model_id] = results["processed_days"].get(model_id, 0) + 1
            results["latest_dates"][model_id] = trade_date.isoformat()
            if model_id not in results["completed_models"]:
                results["completed_models"].append(model_id)
        except StyleMonitorPaused:
            raise
        except Exception as exc:  # noqa: BLE001
            blocked.add(model_id)
            results["failed_models"].append({"model_id": model_id, "date": trade_date.isoformat(), "message": str(exc)})
        if progress:
            progress("增量更新", int(completed / total * 100) if total else 100, f"{model_id} {trade_date.isoformat()}")
    return results
