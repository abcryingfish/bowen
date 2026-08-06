# 风格组合增量监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将“模型有效性”页面的演示曲线替换为 10 个真实股票风格组合的可恢复、幂等、手动增量监控账本。

**Architecture:** 在 `backtrader/models/style_portfolio_monitor/` 建立独立领域模块，分别负责模型配置、Parquet 数据读取、组合计算、DuckDB 账本和增量编排；不注册为现有网页回测模型，也不修改现有回测 runner。`可视化/style_monitor_job_service.py` 只负责任务生命周期，`可视化/api_server.py` 提供只读查询和手动更新接口，模型有效性页面按 API 返回的模型定义动态渲染。

**Tech Stack:** Python 3.10、pandas、DuckDB、PyArrow/Parquet、pytest、Python 标准库 HTTP 服务、原生 JavaScript、Lightweight Charts、Node.js 契约测试、UTF-8。

---

## 文件结构与固定接口

新增后端目录中的职责必须保持如下边界，避免把账本、数据读取和页面 API 混在一个大文件中：

- `backtrader/models/style_portfolio_monitor/config.py`：不可变模型定义、全局口径、配置哈希和调仓周期判断。
- `backtrader/models/style_portfolio_monitor/data.py`：读取日行情和单因子长表，生成可交易截面，绝不写数据库。
- `backtrader/models/style_portfolio_monitor/portfolio.py`：纯函数选股、整手目标仓位、卖出优先的理论收盘成交、估值和净值计算。
- `backtrader/models/style_portfolio_monitor/repository.py`：DuckDB schema、模型版本、事务写入和页面查询。
- `backtrader/models/style_portfolio_monitor/service.py`：初始化和断点增量编排，每模型每日一个事务。
- `可视化/style_monitor_service.py`：面向 HTTP 的只读查询门面，负责创建仓储实例和参数类型转换。
- `可视化/style_monitor_job_service.py`：单工作线程、进程内任务锁、任务快照。
- `可视化/api_server.py`：HTTP 参数解析与错误映射，不承载组合业务逻辑。
- `可视化/模型有效性/model_validity.js`：API 客户端、状态、动态图表、排名、抽屉和更新轮询。

固定领域类型和接口如下，后续任务不得改名：

```python
@dataclass(frozen=True)
class StyleModelDefinition:
    model_id: str
    title: str
    factor_name: str       # signal_daily 的中文 factor 目录名
    factor_key: str        # DuckDB/API 使用的稳定英文键
    rebalance_frequency: Literal["weekly", "monthly", "quarterly"]
    selection_side: Literal["both"] = "both"

@dataclass(frozen=True)
class PortfolioState:
    cash: float
    positions: dict[str, int]
    last_prices: dict[str, float]

def run_incremental_update(
    *,
    model_ids: Sequence[str] | None = None,
    through_date: date | None = None,
    progress: Callable[[str, int, str], None] | None = None,
    database_path: Path = STYLE_MONITOR_DB_PATH,
) -> dict[str, Any]:
    """函数体在 Task 5 按本计划给出的固定流程实现。"""
    raise NotImplementedError
```

账本采用两个独立多头腿 `high` 和 `low`。`relative_nav = high_nav / low_nav * 100` 只在查询时计算；不创建真实空头仓位。

### Task 1: 锁定模型配置与调仓规则

**Files:**
- Create: `backtrader/models/style_portfolio_monitor/__init__.py`
- Create: `backtrader/models/style_portfolio_monitor/config.py`
- Create: `backtrader/tests/style_portfolio_monitor/test_config.py`

- [ ] **Step 1: 写 10 个模型和配置哈希的失败测试**

```python
from datetime import date

from models.style_portfolio_monitor.config import (
    MODEL_DEFINITIONS,
    build_config_hash,
    is_rebalance_day,
)


def test_model_definitions_use_exact_factor_names_and_frequencies():
    actual = [(m.model_id, m.factor_name, m.factor_key, m.rebalance_frequency) for m in MODEL_DEFINITIONS]
    assert actual == [
        ("large_cap_raw", "大市值风格评分（纯市值）", "large_cap_style_score_pure", "weekly"),
        ("small_cap_raw", "小市值风格评分（纯市值）", "small_cap_style_score_pure", "weekly"),
        ("value_raw", "价值模型综合评分", "value_model_composite_score", "monthly"),
        ("value_industry_neutral", "价值模型综合评分(行业标准化)", "value_model_composite_score_industry_normalized", "monthly"),
        ("growth_raw", "成长风格评分", "growth_style_score", "monthly"),
        ("growth_industry_neutral", "成长风格综合评分(行业标准化)", "growth_style_composite_score_industry_normalized", "monthly"),
        ("momentum_raw", "动量风格评分", "momentum_style_score", "weekly"),
        ("low_volatility_raw", "低波风格评分", "low_volatility_style_score", "monthly"),
        ("dividend_raw", "红利基础百分位", "dividend_base_percentile", "quarterly"),
        ("liquidity_raw", "流动性综合评分", "liquidity_composite_score", "weekly"),
    ]


def test_config_hash_is_stable_and_changes_with_business_parameters():
    first = build_config_hash(MODEL_DEFINITIONS[0])
    second = build_config_hash(MODEL_DEFINITIONS[0])
    assert first == second
    assert len(first) == 64


def test_rebalance_day_uses_first_available_trading_day_of_period():
    calendar = [date(2026, 1, 30), date(2026, 2, 2), date(2026, 2, 3), date(2026, 4, 1)]
    assert is_rebalance_day(date(2026, 2, 2), None, "weekly", calendar)
    assert is_rebalance_day(date(2026, 2, 2), date(2026, 1, 30), "monthly", calendar)
    assert not is_rebalance_day(date(2026, 2, 3), date(2026, 2, 2), "monthly", calendar)
    assert is_rebalance_day(date(2026, 4, 1), date(2026, 2, 2), "quarterly", calendar)
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_config.py -q`

Expected: FAIL，包含 `ModuleNotFoundError: No module named 'models.style_portfolio_monitor'`。

- [ ] **Step 3: 实现不可变配置和基于真实交易日的周期切换**

在 `config.py` 定义上述 `StyleModelDefinition`，并固定：

```python
STYLE_MONITOR_DB_PATH = Path(r"D:\database\style_portfolio_monitor\style_monitor.duckdb")
INITIAL_DATE = date(2015, 1, 1)
INITIAL_CASH = 10_000_000.0
COMMISSION_RATE = 0.0003
LOT_SIZE = 100
MIN_HISTORY_DAYS = 120
LIQUIDITY_LOOKBACK_DAYS = 20
MIN_AVERAGE_TURNOVER = 20_000_000.0
SELECTION_RATIO = 0.20
MAX_SELECTION_COUNT = 200
MIN_FACTOR_COVERAGE = 0.80
```

`build_config_hash()` 使用 `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 后做 SHA-256，输入 `payload` 必须包含模型字段和以上全部业务常量。`is_rebalance_day()` 比较当前日与 `last_rebalance_date` 所属 ISO 周、自然月或自然季度；首次有数据时返回 `True`，不能用自然周一/月初日历日判断。

- [ ] **Step 4: 运行配置测试**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_config.py -q`

Expected: `3 passed`。

- [ ] **Step 5: 提交配置任务**

```powershell
git add -- 'backtrader/models/style_portfolio_monitor/__init__.py' 'backtrader/models/style_portfolio_monitor/config.py' 'backtrader/tests/style_portfolio_monitor/test_config.py'
git commit -m "feat: define style portfolio monitor models"
```

### Task 2: 行情、因子与可交易股票池读取

**Files:**
- Create: `backtrader/models/style_portfolio_monitor/data.py`
- Create: `backtrader/tests/style_portfolio_monitor/test_data.py`

- [ ] **Step 1: 写最新分区覆盖、历史天数、成交额和因子覆盖率测试**

测试用 `tmp_path` 写两个小型 Parquet 数据根。行情列固定为 `time, htsc_code, close, volume, value`，其中 `value` 是成交额：

```python
def test_build_eligible_snapshot_filters_market_history_liquidity_and_missing_values(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path)
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)
    snapshot = source.build_eligible_snapshot(date(2026, 1, 30), "成长风格评分")
    assert snapshot["htsc_code"].tolist() == ["600000.SH"]
    assert snapshot.iloc[0]["average_turnover_20d"] >= 20_000_000
    assert snapshot.iloc[0]["history_days"] >= 120


def test_factor_part_file_overrides_merged_for_same_date_and_code(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path, merged_score=40.0, part_score=80.0)
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)
    snapshot = source.build_eligible_snapshot(date(2026, 1, 30), "成长风格评分")
    assert snapshot.set_index("htsc_code").loc["600000.SH", "score"] == 80.0


def test_factor_coverage_uses_tradable_universe_before_score_filter(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path, missing_score_code="000001.SZ")
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)
    snapshot = source.build_eligible_snapshot(date(2026, 1, 30), "成长风格评分")
    assert snapshot.attrs["tradable_count"] == 2
    assert snapshot.attrs["factor_valid_count"] == 1
    assert snapshot.attrs["factor_coverage"] == 0.5
```

`write_fixture_partitions()` 必须生成至少 120 个工作日，使 `600000.SH` 通过、`.BJ` 和非股票代码被排除、一个沪深代码因 20 日平均 `value` 低于阈值被排除、一个代码因当日 `close`/`volume` 无效被排除。

- [ ] **Step 2: 运行测试并确认失败**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_data.py -q`

Expected: FAIL，包含 `ImportError: cannot import name 'StyleDataSource'`。

- [ ] **Step 3: 实现分区读取和截面构造**

实现：

```python
class StyleDataSource:
    def __init__(self, market_root=Path(r"D:\database\stock_basic_data_daily"), signal_root=Path(r"D:\database\signal_daily")):
        """保存路径并初始化受限的月分区缓存。"""
        raise NotImplementedError
    def available_market_dates(self, start: date, end: date | None = None) -> list[date]:
        raise NotImplementedError
    def latest_common_date(self, factor_name: str) -> date | None:
        raise NotImplementedError
    def first_usable_date(self, factor_name: str, start: date, minimum_coverage: float) -> date | None:
        raise NotImplementedError
    def build_eligible_snapshot(self, trade_date: date, factor_name: str) -> pd.DataFrame:
        raise NotImplementedError
    def close_prices(self, trade_date: date, codes: Sequence[str]) -> dict[str, float]:
        raise NotImplementedError
```

查询约束：

- 只读命中的年月分区，不扫描整个历史；为 120 日历史和 20 日成交额读取当前日前足够的交易日窗口。
- 同一 `time + htsc_code` 按文件顺序 `merged.parquet` 先、`part_*.parquet` 后，最后文件覆盖旧值。
- 代码使用正则 `^[036]\d{5}\.(SH|SZ)$`，排除 `.BJ`、`.THS`、ETF/指数等不符合沪深 A 股证券代码的记录。
- 当日 `close > 0`、`volume > 0`；最近 20 个有效交易日的 `value` 平均值不低于 2,000 万；历史有效收盘数至少 120。
- 因子目录按中文 `factor_name` 拼接，仅读 `time, htsc_code, value`，结果列重命名为 `score`。
- `factor_coverage = factor_valid_count / tradable_count`；先构造行情可交易池再剔除缺分股票，禁止用最终有分股票数作分母。
- 行情月分区使用最多 8 个月的 LRU 缓存，因子月分区使用最多 20 个“因子名+年月”的 LRU 缓存；缓存内仍按 `time + htsc_code` 去重。历史回填按日期推进时，10 个模型复用同一行情窗口，不能为每个模型重新读取相同 Parquet。
- `first_usable_date()` 从因子首个日期开始按真实交易日检查，返回第一个 `factor_coverage >= minimum_coverage` 的日期；这只用于新 `model_version` 寻找起点，避免行业中性因子在早期零星数据日永久暂停。
- 找不到月份、列或有效交易日时抛出 `StyleDataError`，错误消息包含路径、因子名和日期。

- [ ] **Step 4: 运行数据层测试**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_data.py -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交数据层任务**

```powershell
git add -- 'backtrader/models/style_portfolio_monitor/data.py' 'backtrader/tests/style_portfolio_monitor/test_data.py'
git commit -m "feat: load style monitor market and factor snapshots"
```

### Task 3: 选股、整手调仓和理论收盘记账

**Files:**
- Create: `backtrader/models/style_portfolio_monitor/portfolio.py`
- Create: `backtrader/tests/style_portfolio_monitor/test_portfolio.py`

- [ ] **Step 1: 写纯函数组合算法失败测试**

```python
def test_select_high_and_low_uses_ceil_twenty_percent_caps_200_and_is_deterministic():
    snapshot = make_snapshot(503)
    selected = select_style_legs(snapshot, ratio=0.20, max_count=200)
    assert len(selected["high"]) == 101
    assert len(selected["low"]) == 101
    assert selected["high"][0].code == "000503.SZ"
    assert selected["low"][0].code == "000001.SZ"


def test_equal_weight_targets_round_down_to_board_lots_and_keep_cash_non_negative():
    targets = build_target_shares(
        codes=["600000.SH", "000001.SZ"],
        prices={"600000.SH": 10.0, "000001.SZ": 20.0},
        portfolio_value=10_000.0,
        commission_rate=0.0003,
        lot_size=100,
    )
    assert targets == {"600000.SH": 400, "000001.SZ": 200}


def test_rebalance_sells_before_buys_and_charges_each_trade():
    state = PortfolioState(cash=0.0, positions={"600000.SH": 1000}, last_prices={"600000.SH": 10.0})
    result = rebalance_at_close(
        state,
        target_shares={"600000.SH": 0, "000001.SZ": 400},
        prices={"600000.SH": 10.0, "000001.SZ": 20.0},
        commission_rate=0.0003,
    )
    assert [trade.side for trade in result.trades] == ["SELL", "BUY"]
    assert result.state.cash >= 0
    assert result.total_commission == pytest.approx((10_000 + 8_000) * 0.0003)


def test_mark_to_market_uses_last_price_and_marks_stale_position():
    result = mark_to_market(
        PortfolioState(cash=1000, positions={"600000.SH": 100}, last_prices={"600000.SH": 9.8}),
        prices={},
    )
    assert result.total_asset == pytest.approx(1980)
    assert result.stale_codes == ["600000.SH"]


def test_relative_nav_is_ratio_not_return_difference():
    assert calculate_relative_nav(110.0, 100.0) == pytest.approx(110.0)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_portfolio.py -q`

Expected: FAIL，包含 `ModuleNotFoundError` 或未定义函数错误。

- [ ] **Step 3: 实现确定性的两腿组合算法**

实现 `SelectedStock`、`Trade`、`RebalanceResult`、`ValuationResult` 数据类及以下函数：

```python
def select_style_legs(snapshot: pd.DataFrame, ratio: float, max_count: int) -> dict[str, list[SelectedStock]]:
    raise NotImplementedError
def build_target_shares(codes, prices, portfolio_value, commission_rate, lot_size) -> dict[str, int]:
    raise NotImplementedError
def rebalance_at_close(state, target_shares, prices, commission_rate) -> RebalanceResult:
    raise NotImplementedError
def mark_to_market(state, prices) -> ValuationResult:
    raise NotImplementedError
def calculate_relative_nav(high_nav: float, low_nav: float) -> float | None:
    raise NotImplementedError
```

算法固定为：有效样本数 `n` 的单腿数量 `min(ceil(n * 0.20), 200)`；高分按 `score DESC, htsc_code ASC`，低分按 `score ASC, htsc_code ASC`。目标资金先预留目标买入额的手续费，再逐股向下取 100 股整数手；卖单全部完成后才计算可用现金和买单，若舍入误差仍导致现金不足，则按代码逆序逐手缩减买单直到现金非负。换手率使用 `sum(abs(trade_value)) / pre_trade_total_asset`，首次建仓也计换手。新入选股票缺当日有效价格时不买；原持仓缺价时用 `last_prices` 估值并输出 `stale_codes`。

- [ ] **Step 4: 运行组合算法测试**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_portfolio.py -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交组合算法任务**

```powershell
git add -- 'backtrader/models/style_portfolio_monitor/portfolio.py' 'backtrader/tests/style_portfolio_monitor/test_portfolio.py'
git commit -m "feat: add theoretical style portfolio accounting"
```

### Task 4: DuckDB schema、版本和事务幂等

**Files:**
- Create: `backtrader/models/style_portfolio_monitor/repository.py`
- Create: `backtrader/tests/style_portfolio_monitor/test_repository.py`

- [ ] **Step 1: 写 schema、版本、事务回滚和幂等测试**

```python
def test_schema_contains_required_tables_and_two_leg_primary_keys(tmp_path):
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    tables = repo.list_tables()
    assert {"model_definition", "nav_daily", "position_daily", "trade_log", "run_state", "update_run"} <= tables
    assert repo.primary_key_columns("nav_daily") == ["model_version", "leg", "trade_date"]


def test_ensure_model_version_reuses_same_hash_and_creates_new_version_for_changed_hash(tmp_path):
    repo = ready_repository(tmp_path)
    first = repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-a")
    assert repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-a") == first
    second = repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-b")
    assert second != first


def test_write_model_day_is_idempotent(tmp_path):
    repo = ready_repository(tmp_path)
    payload = make_model_day_payload()
    repo.write_model_day(payload)
    repo.write_model_day(payload)
    assert repo.count_rows("nav_daily") == 2
    assert repo.count_rows("trade_log") == len(payload.trades)


def test_failed_day_rolls_back_all_rows_and_does_not_advance_watermark(tmp_path, monkeypatch):
    repo = ready_repository(tmp_path)
    monkeypatch.setattr(repo, "_insert_positions", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        repo.write_model_day(make_model_day_payload())
    assert repo.count_rows("nav_daily") == 0
    assert repo.get_run_state("large_cap_raw-v1").last_success_date is None
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_repository.py -q`

Expected: FAIL，包含 `ImportError: cannot import name 'StyleMonitorRepository'`。

- [ ] **Step 3: 实现 schema 和单日原子写入**

`initialize_schema()` 必须创建：

```sql
CREATE TABLE IF NOT EXISTS model_definition (
  model_version VARCHAR PRIMARY KEY, model_id VARCHAR NOT NULL, title VARCHAR NOT NULL,
  factor_name VARCHAR NOT NULL, factor_key VARCHAR NOT NULL, rebalance_frequency VARCHAR NOT NULL,
  config_hash VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
  UNIQUE(model_id, config_hash)
);
CREATE TABLE IF NOT EXISTS nav_daily (
  model_version VARCHAR NOT NULL, leg VARCHAR NOT NULL, trade_date DATE NOT NULL,
  cash DOUBLE NOT NULL, market_value DOUBLE NOT NULL, total_asset DOUBLE NOT NULL,
  nav DOUBLE NOT NULL, daily_return DOUBLE, cumulative_return DOUBLE NOT NULL,
  turnover DOUBLE NOT NULL, commission DOUBLE NOT NULL, rebalanced BOOLEAN NOT NULL,
  factor_coverage DOUBLE, stale_price_count INTEGER NOT NULL, status VARCHAR NOT NULL,
  status_message VARCHAR NOT NULL, PRIMARY KEY(model_version, leg, trade_date)
);
CREATE TABLE IF NOT EXISTS position_daily (
  model_version VARCHAR NOT NULL, leg VARCHAR NOT NULL, trade_date DATE NOT NULL,
  htsc_code VARCHAR NOT NULL, score DOUBLE, rank INTEGER, target_weight DOUBLE,
  actual_weight DOUBLE NOT NULL, shares BIGINT NOT NULL, price DOUBLE NOT NULL,
  market_value DOUBLE NOT NULL, stale_price BOOLEAN NOT NULL,
  PRIMARY KEY(model_version, leg, trade_date, htsc_code)
);
CREATE TABLE IF NOT EXISTS trade_log (
  trade_id VARCHAR PRIMARY KEY, model_version VARCHAR NOT NULL, leg VARCHAR NOT NULL,
  trade_date DATE NOT NULL, htsc_code VARCHAR NOT NULL, side VARCHAR NOT NULL,
  shares BIGINT NOT NULL, price DOUBLE NOT NULL, trade_value DOUBLE NOT NULL,
  commission DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS run_state (
  model_version VARCHAR PRIMARY KEY, last_success_date DATE, last_rebalance_date DATE,
  config_hash VARCHAR NOT NULL, updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS update_run (
  run_id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL,
  started_at TIMESTAMP, finished_at TIMESTAMP, through_date DATE,
  total_steps INTEGER NOT NULL, completed_steps INTEGER NOT NULL,
  current_model_id VARCHAR, current_date DATE, failed_model_id VARCHAR,
  failed_date DATE, message VARCHAR NOT NULL, error VARCHAR NOT NULL
);
```

`trade_id` 使用 `sha256(model_version|leg|trade_date|htsc_code|side)`，禁止随机 UUID 造成重复交易。`write_model_day()` 在同一个 `BEGIN TRANSACTION` 中先按主键删除该模型腿当日旧 positions/trades/nav，再插入两腿完整结果，最后更新 `run_state`；异常执行 `ROLLBACK`。DuckDB 连接每个公开方法内部创建并关闭，避免跨线程共享连接。

- [ ] **Step 4: 运行仓储测试**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_repository.py -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交仓储任务**

```powershell
git add -- 'backtrader/models/style_portfolio_monitor/repository.py' 'backtrader/tests/style_portfolio_monitor/test_repository.py'
git commit -m "feat: persist versioned style monitor ledger"
```

### Task 5: 初始化和断点增量编排

**Files:**
- Create: `backtrader/models/style_portfolio_monitor/service.py`
- Create: `backtrader/tests/style_portfolio_monitor/test_service.py`

- [ ] **Step 1: 写初始化、补缺、覆盖率暂停和缺价测试**

```python
def test_first_run_starts_at_2015_or_factor_first_usable_date(tmp_path):
    source = FakeSource(market_dates=[date(2015, 1, 5), date(2015, 1, 6)], factor_first_usable_date=date(2015, 1, 6))
    result = run_incremental_update(data_source=source, repository=ready_repository(tmp_path))
    assert source.requested_dates["growth_industry_neutral"][0] == date(2015, 1, 6)


def test_incremental_run_processes_every_missing_market_date_after_watermark(tmp_path):
    repo = ready_repository(tmp_path, last_success_date=date(2026, 1, 28))
    source = FakeSource(market_dates=[date(2026, 1, 29), date(2026, 1, 30)])
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    assert repo.written_dates("growth_raw") == [date(2026, 1, 29), date(2026, 1, 30)]


def test_low_factor_coverage_pauses_on_rebalance_day_without_advancing_watermark(tmp_path):
    repo = ready_repository(tmp_path)
    source = FakeSource(factor_coverage=0.79)
    with pytest.raises(StyleMonitorPaused, match="79.00%"):
        run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    assert repo.get_run_state_for_model("growth_raw").last_success_date is None


def test_non_rebalance_day_values_existing_positions_without_reselecting(tmp_path):
    repo = ready_repository_with_positions(tmp_path)
    source = FakeSource(close_prices={})
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    row = repo.latest_nav("growth_raw", "high")
    assert row.stale_price_count == 1
    assert source.snapshot_calls == 0


def test_repeated_update_produces_no_duplicate_nav_or_trades(tmp_path):
    repo = ready_repository(tmp_path)
    source = FakeSource()
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    counts = repo.table_counts()
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    assert repo.table_counts() == counts
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_service.py -q`

Expected: FAIL，包含 `ImportError: cannot import name 'run_incremental_update'`。

- [ ] **Step 3: 实现逐模型、逐交易日增量服务**

`run_incremental_update()` 的固定流程：

1. `initialize_schema()`，为选中模型按 `config_hash` 获取当前 `model_version`。
2. 取模型因子和行情的共同最新日期；`through_date` 只能缩短上界，不能越过共同最新日。
3. 起点为 `last_success_date` 后一个真实交易日；新版本无水位时调用 `first_usable_date()`，取不早于 `2015-01-01` 且因子覆盖率首次达到 80% 的交易日。
4. 非调仓日读取前一日两腿状态，只做持仓估值和日收益，不读取因子截面。
5. 调仓日读取可交易截面；覆盖率 `< 0.80` 抛 `StyleMonitorPaused`，保留 `update_run` 错误信息且不推进该模型水位。
6. 高低腿各自以 1,000 万初始资金独立记账；T 日分数、T 日收盘理论成交；交易卖出优先。
7. 每模型每日调用一次 `write_model_day()`；只有两腿都成功才推进水位和最近调仓日。
8. 先汇总全部模型的缺失日期，再按 `trade_date ASC, MODEL_DEFINITIONS 顺序` 执行，复用数据层月缓存；单模型失败后跳过该模型更晚日期，但其他模型继续。
9. 最终返回 `completed_models`、`paused_models`、`failed_models`、`latest_dates` 和各模型处理天数；同一次任务不得在内存中长期保留全市场全历史明细。

进度回调固定为 `progress(stage, percent, message)`，percent 由“全部模型缺失日期步数”计算，不能按模型数粗略跳变。

- [ ] **Step 4: 运行编排测试和前四个任务回归**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交增量服务任务**

```powershell
git add -- 'backtrader/models/style_portfolio_monitor/service.py' 'backtrader/tests/style_portfolio_monitor/test_service.py'
git commit -m "feat: orchestrate resumable style monitor updates"
```

### Task 6: 页面查询服务与相对强弱排名

**Files:**
- Modify: `backtrader/models/style_portfolio_monitor/repository.py`
- Create: `可视化/style_monitor_service.py`
- Create: `backtrader/tests/style_portfolio_monitor/test_queries.py`

- [ ] **Step 1: 写 summary、curves、positions、trades 查询测试**

```python
def test_summary_ranks_relative_leg_returns_over_1_5_20_days(tmp_path):
    repo = seeded_query_repository(tmp_path)
    payload = repo.query_summary()
    assert len(payload["models"]) == 10
    assert payload["rankings"]["1d"][0]["model_id"] == "momentum_raw"
    assert payload["models"][0]["latest_date"] is not None


def test_curves_rebases_selected_window_and_keeps_ratio_formula(tmp_path):
    repo = seeded_query_repository(tmp_path)
    payload = repo.query_curves("growth_raw", range_key="20d")
    assert payload["series"]["high"][0]["value"] == pytest.approx(100.0)
    assert payload["series"]["low"][0]["value"] == pytest.approx(100.0)
    for high, low, relative in zip(payload["series"]["high"], payload["series"]["low"], payload["series"]["relative"]):
        assert relative["value"] == pytest.approx(high["value"] / low["value"] * 100)


def test_positions_and_trades_validate_model_leg_date_and_limit(tmp_path):
    repo = seeded_query_repository(tmp_path)
    assert repo.query_positions("growth_raw", "high", None)["items"]
    assert len(repo.query_trades("growth_raw", "high", limit=1)["items"]) == 1
    with pytest.raises(StyleMonitorValidationError):
        repo.query_curves("missing", "60d")
```

- [ ] **Step 2: 运行查询测试并确认方法不存在**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_queries.py -q`

Expected: FAIL，包含 `AttributeError` 或查询函数导入失败。

- [ ] **Step 3: 实现只读查询 DTO**

`query_summary()` 返回：

```json
{
  "as_of": "2026-08-05",
  "models": [{"model_id":"growth_raw","model_version":"growth_raw-v1","title":"成长原始版","factor_name":"成长风格评分","frequency":"monthly","latest_date":"2026-08-05","last_rebalance_date":"2026-08-03","high_nav":101.2,"low_nav":99.8,"relative_nav":101.4028,"holding_count_high":200,"holding_count_low":200,"status":"ok","status_message":""}],
  "rankings": {"1d":[],"5d":[],"20d":[]},
  "latest_update": {"run_id":"run-20260805-001","status":"done","message":"更新完成"}
}
```

排名值为区间末相对净值/区间起相对净值-1；不足 N+1 个共同点时返回 `value: null` 并排在末尾。`query_curves()` 支持 `20d|60d|ytd|all`，每条点为 `{"time":"YYYY-MM-DD","value":100.0}`，窗口内三条线共同以首个高低腿齐全日期重基到 100。`query_positions()` 默认各模型自身最新日期，包含 score、rank、target_weight、actual_weight、shares、price、market_value、stale_price；非调仓日沿用最近调仓日的 score、rank、target_weight，actual_weight 按当日市值重算。`query_trades()` 按日期倒序并限制 `1..1000`。

在 `可视化/style_monitor_service.py` 定义 `query_style_monitor_summary()`、`query_style_monitor_curves(model_id, range_key)`、`query_style_monitor_positions(model_id, leg, trade_date)` 和 `query_style_monitor_trades(model_id, leg, limit)`；每次调用创建 `StyleMonitorRepository(STYLE_MONITOR_DB_PATH)` 并返回纯 `dict/list/str/int/float/bool/None`，不把 DuckDB date、Decimal 或 pandas 类型交给 `json.dumps()`。

- [ ] **Step 4: 运行查询测试**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_queries.py -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交查询任务**

```powershell
git add -- 'backtrader/models/style_portfolio_monitor/repository.py' '可视化/style_monitor_service.py' 'backtrader/tests/style_portfolio_monitor/test_queries.py'
git commit -m "feat: query style monitor curves and rankings"
```

### Task 7: 异步手动更新任务服务

**Files:**
- Create: `可视化/style_monitor_job_service.py`
- Create: `可视化/test_style_monitor_job_service.py`

- [ ] **Step 1: 写单任务锁、状态和失败传播测试**

```python
def test_create_job_runs_update_and_reports_progress(monkeypatch):
    monkeypatch.setattr(service, "run_incremental_update", fake_successful_update)
    job = service.create_style_monitor_job({"through_date": "2026-08-05"})
    final = wait_for_terminal(job["job_id"])
    assert final["status"] == "done"
    assert final["progress"] == 100
    assert final["result"]["completed_models"]


def test_second_job_is_rejected_while_first_is_running(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(service, "run_incremental_update", blocking_update(release))
    first = service.create_style_monitor_job({})
    with pytest.raises(StyleMonitorJobBusyError, match="已有风格组合更新任务"):
        service.create_style_monitor_job({})
    release.set()
    wait_for_terminal(first["job_id"])


def test_failed_update_exposes_short_error_without_trace_log_spam(monkeypatch):
    monkeypatch.setattr(service, "run_incremental_update", raising_update("测试失败"))
    final = wait_for_terminal(service.create_style_monitor_job({})["job_id"])
    assert final["status"] == "failed"
    assert final["error"] == "RuntimeError: 测试失败"
    assert len(final["log_tail"]) <= 80
```

- [ ] **Step 2: 运行任务服务测试并确认失败**

Run: `$env:PYTHONPATH='可视化;backtrader'; .\.venv\Scripts\python.exe -m pytest '可视化/test_style_monitor_job_service.py' -q`

Expected: FAIL，包含 `ModuleNotFoundError: No module named 'style_monitor_job_service'`。

- [ ] **Step 3: 实现单工作线程任务服务**

复制 `backtest_job_service.py` 的任务快照模式后针对本功能独立修改，不抽公共文件。定义 `StyleMonitorJob`、`create_style_monitor_job(payload)`、`get_style_monitor_job(job_id)`、`StyleMonitorJobBusyError`。固定 `MAX_STYLE_MONITOR_WORKERS = 1`，在 `_active_job_id` 尚未终态时拒绝第二个任务；payload 只接受可选 `through_date` 和 `model_ids`。不输出逐股票 TRACE 日志，`log_tail` 最多保留 80 行。

- [ ] **Step 4: 运行任务服务测试**

Run: `$env:PYTHONPATH='可视化;backtrader'; .\.venv\Scripts\python.exe -m pytest '可视化/test_style_monitor_job_service.py' -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交任务服务**

```powershell
git add -- '可视化/style_monitor_job_service.py' '可视化/test_style_monitor_job_service.py'
git commit -m "feat: run style monitor updates asynchronously"
```

### Task 8: 风格监控 HTTP API

**Files:**
- Modify: `可视化/api_server.py`
- Create: `可视化/test_style_monitor_api.py`

- [ ] **Step 1: 写路由、UTF-8、参数错误和任务状态测试**

测试启动 `ReuseThreadingHTTPServer(("127.0.0.1", 0), ApiRequestHandler)`，monkeypatch API 模块导入的查询函数：

```python
def test_summary_and_curves_routes_return_utf8_json(api_client, monkeypatch):
    monkeypatch.setattr(api_server, "query_style_monitor_summary", lambda: {"models": [{"title": "成长原始版"}]})
    status, headers, payload = api_client.get("/api/style-monitor/summary")
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert payload["models"][0]["title"] == "成长原始版"


def test_positions_rejects_invalid_leg(api_client):
    status, _, payload = api_client.get("/api/style-monitor/positions?model_id=growth_raw&leg=short")
    assert status == 400
    assert payload["error"]["code"] == "INVALID_ARGUMENT"


def test_update_returns_202_and_job_lookup_returns_snapshot(api_client, monkeypatch):
    monkeypatch.setattr(api_server, "create_style_monitor_job", lambda payload: {"job_id": "job-1", "status": "queued"})
    monkeypatch.setattr(api_server, "get_style_monitor_job", lambda job_id: {"job_id": job_id, "status": "done"})
    assert api_client.post("/api/style-monitor/update", {})[0] == 202
    assert api_client.get("/api/style-monitor/update/jobs/job-1")[2]["status"] == "done"
```

- [ ] **Step 2: 运行 API 测试并确认 404/失败**

Run: `$env:PYTHONPATH='可视化;backtrader'; .\.venv\Scripts\python.exe -m pytest '可视化/test_style_monitor_api.py' -q`

Expected: FAIL，GET 返回 404 或相关 handler 未定义。

- [ ] **Step 3: 增加六个路由和一致的错误映射**

在 `api_server.py` 仅追加以下路由：

```text
GET  /api/style-monitor/summary
GET  /api/style-monitor/curves?model_id=growth_raw&range=20d|60d|ytd|all
GET  /api/style-monitor/positions?model_id=growth_raw&leg=high|low&date=2026-08-05
GET  /api/style-monitor/trades?model_id=growth_raw&leg=high|low&limit=200
POST /api/style-monitor/update
GET  /api/style-monitor/update/jobs/{job_id}
```

模块顶部从 `style_monitor_job_service` 导入任务函数，从 `style_monitor_service` 导入四个只读查询函数。两个服务模块都沿用现有规则向 `sys.path` 末尾 append `backtrader` 路径，禁止 `insert(0)` 遮蔽第三方 `backtrader` 包。`StyleMonitorValidationError`/`ValueError` 映射 400，未知模型或任务 `KeyError` 映射 404，任务冲突映射 409，DuckDB/数据异常映射 500。POST 成功返回 202。`_read_json_body()` 继续按 UTF-8 解析。

- [ ] **Step 4: 运行 API 和现有 API 回归测试**

Run: `$env:PYTHONPATH='可视化;backtrader'; .\.venv\Scripts\python.exe -m pytest '可视化/test_style_monitor_api.py' '可视化/test_market_data_service_index_search.py' -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交 API 任务**

```powershell
git add -- '可视化/api_server.py' '可视化/test_style_monitor_api.py'
git commit -m "feat: expose style monitor api"
```

### Task 9: 模型有效性页面真实数据与交互

**Files:**
- Modify: `可视化/模型有效性/index.html`
- Modify: `可视化/模型有效性/model_validity.js`
- Modify: `可视化/模型有效性/model_validity.css`
- Modify: `test_model_validity_page.js`

- [ ] **Step 1: 把页面契约测试改成真实监控契约并确认失败**

将原先“恰好 6 个静态 `.model-chart-card`”断言替换为：

```javascript
assert.doesNotMatch(pageJs, /buildDemoSeries/);
assert.doesNotMatch(page, /data-chart-index=/);
assert.match(page, /id="style-summary-rankings"/);
assert.match(page, /id="style-chart-grid"/);
assert.match(page, /id="style-monitor-update"/);
assert.match(page, /理论监控/);
assert.match(page, /data-range="20d"/);
assert.match(page, /data-range="60d"/);
assert.match(page, /data-range="ytd"/);
assert.match(page, /data-range="all"/);
assert.match(page, /id="style-detail-drawer"/);
assert.match(pageJs, /\/api\/style-monitor\/summary/);
assert.match(pageJs, /\/api\/style-monitor\/curves/);
assert.match(pageJs, /\/api\/style-monitor\/update/);
assert.match(pageJs, /createModelCard/);
assert.match(pageJs, /renderRankings/);
assert.match(pageJs, /renderPositions/);
assert.match(pageJs, /renderTrades/);
```

- [ ] **Step 2: 运行页面契约并确认失败**

Run: `node .\test_model_validity_page.js`

Expected: FAIL，首先报告仍包含 `buildDemoSeries` 或缺少 `style-summary-rankings`。

- [ ] **Step 3: 修改 HTML 为总览、动态网格和明细抽屉**

保留现有页头、缩放、时钟和侧边导航。主区改为：状态条（账本日期、最近更新状态、手动更新图标按钮）、1/5/20 日三列排名、全局 `20D/60D/YTD/全部` 分段控制、空的 `#style-chart-grid`、加载/空/错误状态，以及 `#style-detail-drawer`。更新按钮使用现有图标库不可用时采用熟悉的 Unicode 刷新符号 `↻` 并带 `title="手动更新"`；页面显示固定说明“理论监控：T 日收盘信号与 T 日收盘理论成交，不代表可实盘成交”。

- [ ] **Step 4: 重写 JS 为 API 状态机和三线动态图表**

固定状态：

```javascript
const state = {
    range: "60d",
    summary: null,
    charts: new Map(),
    selectedModelId: null,
    updateJobId: null,
};
```

实现并导出到 `window.ModelValidity` 供测试：`apiFetch`、`createModelCard`、`renderRankings`、`renderModelCharts`、`loadCurve`、`openModelDetail`、`renderPositions`、`renderTrades`、`startManualUpdate`、`pollUpdateJob`、`formatPercent`。每张图使用三条 LineSeries：高分多头青色、低分多头琥珀色、相对曲线蓝色；图例按钮可独立显隐三条曲线且不销毁数据。曲线数据不足时在卡片内显示明确空状态。range 切换后只重新请求已显示模型的 curves。页面加载只 GET summary/curves，不 POST。点击更新后 POST 一次并每 1 秒轮询；终态停止轮询、刷新 summary 和所有曲线。所有插入文本使用 `textContent`，不把后端错误拼进 `innerHTML`。

- [ ] **Step 5: 修改 CSS 并验证桌面/移动端无重叠**

总览采用紧凑的全宽 band，不嵌套卡片；模型图卡继续使用 6px 圆角。桌面 3 列，1200px 以下 2 列，720px 以下 1 列；图表挂载区固定 `min-height: 220px`，排名列和按钮允许中文换行。抽屉在桌面右侧固定宽 `min(720px, 92vw)`，移动端占满宽度，持仓表横向滚动。保留非单一色调：高分青、低分琥珀、相对蓝、错误红。

- [ ] **Step 6: 运行前端静态检查和契约测试**

Run: `node --check '可视化/模型有效性/model_validity.js'; node .\test_model_validity_page.js`

Expected: JavaScript 语法检查退出 0，随后输出 `模型有效性页面契约通过`。

- [ ] **Step 7: 提交页面任务**

```powershell
git add -- '可视化/模型有效性/index.html' '可视化/模型有效性/model_validity.js' '可视化/模型有效性/model_validity.css' 'test_model_validity_page.js'
git commit -m "feat: display live style portfolio monitoring"
```

### Task 10: 全链路验证、真实数据冒烟与 TRACE 写盘审计

**Files:**
- Create: `backtrader/models/style_portfolio_monitor/smoke_check.py`
- Create: `backtrader/tests/style_portfolio_monitor/test_smoke_contract.py`
- Verify: `D:\database\style_portfolio_monitor\style_monitor.duckdb`
- Verify: `codex/logs_2.sqlite`（仅当实际存在）

- [ ] **Step 1: 写真实数据冒烟脚本契约测试**

```python
def test_smoke_script_is_read_only_by_default_and_requires_explicit_write_flag():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.write is False
    assert args.model_ids == []


def test_smoke_validation_requires_two_legs_and_balanced_accounting():
    report = validate_smoke_result(make_valid_result())
    assert report["ok"] is True
    broken = make_valid_result(high_cash=-1.0)
    assert validate_smoke_result(broken)["ok"] is False
```

- [ ] **Step 2: 运行测试并确认脚本不存在**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor/test_smoke_contract.py -q`

Expected: FAIL，包含 `ModuleNotFoundError`。

- [ ] **Step 3: 实现显式写入的单日冒烟检查器**

`smoke_check.py` 默认只检查 10 个因子目录、行情 schema 和共同最新日；只有 `--write` 时调用 `run_incremental_update()`。支持 `--model-id` 重复参数和 `--through-date`。写入后验证每个实际运行模型：高低腿各有一条 nav、现金非负、`cash + market_value == total_asset`（误差 0.01 元）、持仓股数为 100 整数倍、relative 公式正确、trade commission 等于 trade_value × 0.0003、run_state 与最新 nav 日期一致。

- [ ] **Step 4: 运行全部自动化测试**

Run: `$env:PYTHONPATH='可视化;backtrader'; .\.venv\Scripts\python.exe -m pytest backtrader/tests/style_portfolio_monitor '可视化/test_style_monitor_job_service.py' '可视化/test_style_monitor_api.py' -q`

Expected: 全部 PASS。

Run: `node --check '可视化/模型有效性/model_validity.js'; node .\test_model_validity_page.js`

Expected: 两条命令均退出 0，契约测试输出 `模型有效性页面契约通过`。

- [ ] **Step 5: 用真实数据先只读检查，再小范围写入冒烟**

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m models.style_portfolio_monitor.smoke_check`

Expected: 输出 10 个模型的因子目录、共同最新日期和 `只读检查通过`，不创建/修改 DuckDB。

Run: `$env:PYTHONPATH='backtrader'; .\.venv\Scripts\python.exe -m models.style_portfolio_monitor.smoke_check --write --model-id growth_raw --through-date 2015-01-05`

Expected: 输出 `growth_raw` 的高低腿账本核对通过；重复执行一次后 `nav_daily`、`trade_log` 行数不增长。

- [ ] **Step 6: 启动现有服务并做浏览器检查**

Run: `Start-Process -FilePath '可视化\start_all.bat' -WindowStyle Hidden`

访问 `http://127.0.0.1:8086/模型有效性/index.html`，检查：初始页面只读；模型卡数量来自 summary 且为 10；20D/60D/YTD/全部切换不重排布局；高/低/相对三线可显隐；持仓和交易抽屉可打开；手动更新显示进度并在终态停止轮询；宽度 1440、1024、390 像素下无文字或控件重叠；中文无乱码。

- [ ] **Step 7: 审计 UTF-8、diff 和 TRACE 高频写盘**

Run: `git diff --check -- 'backtrader/models/style_portfolio_monitor' 'backtrader/tests/style_portfolio_monitor' '可视化/style_monitor_job_service.py' '可视化/test_style_monitor_job_service.py' '可视化/test_style_monitor_api.py' '可视化/api_server.py' '可视化/模型有效性' 'test_model_validity_page.js'`

Expected: 无输出，退出 0。

Run: `rg --files -g 'logs_2.sqlite' -g '!outputs/**/node_modules/**'`

Expected: 当前仓库无输出。若部署环境找到 `codex/logs_2.sqlite`，先记录 `SELECT COALESCE(MAX(id),0) FROM logs;`、WAL 文件大小和 TRACE 行数；等待一次完整增量更新后再次读取。若 TRACE 的 `MAX(id)` 或 WAL 持续增长，则创建 `BEFORE INSERT ON logs WHEN lower(NEW.level)='trace' BEGIN SELECT RAISE(IGNORE); END` trigger，再重复更新并确认三个指标不增长。不得删除历史日志或 WAL 文件。

- [ ] **Step 8: 提交冒烟工具并记录验证结果**

```powershell
git add -- 'backtrader/models/style_portfolio_monitor/smoke_check.py' 'backtrader/tests/style_portfolio_monitor/test_smoke_contract.py'
git commit -m "test: verify style monitor end to end"
```

最终实施交付必须说明：实际共同最新日期、10 个模型各自起始/最新日期、被暂停模型及原因、真实冒烟的账本核对结果、浏览器检查分辨率，以及 `logs_2.sqlite` 是否存在和 TRACE 审计结果。
