const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
    path.join(__dirname, "shared/chart_board_backtest.js"),
    "utf8",
);

assert.match(source, /筛选类型/, "规则项应显示筛选类型");
assert.match(source, /因子值/, "应提供因子值模式");
assert.match(source, /横截面排名/, "应提供横截面排名模式");
assert.match(source, /位于分位区间/, "排名模式应支持分位区间");
assert.match(source, /mode:\s*"cross_section_percentile"/, "请求应包含横截面排名模式");
assert.match(source, /scope:\s*"selected_stock_pool"/, "排名范围应固定为当前股票池");
assert.match(source, /frequency:\s*"daily"/, "排名频率应固定为每日截面");
assert.match(source, /backtest-rule-filter-mode/, "应绑定筛选类型控件");
assert.match(source, /backtest-rule-value-operator/, "应绑定因子值比较方式控件");
assert.match(source, /backtest-rule-rank-direction/, "应绑定横截面排名方向控件");
assert.match(source, /backtest-rule-rank-unit/, "应提供横截面排名单位控件");
assert.match(source, /rank_unit/, "请求应能够区分排名单位");
assert.match(source, /backtest-rule-rank-count/, "应提供具体名次输入控件");
assert.match(source, /min_rank/, "请求应支持名次区间字段");
assert.match(source, /Number\.isInteger\(rank\)/, "具体名次应校验为整数");

console.log("回测因子筛选模式测试通过");
