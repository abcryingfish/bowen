const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
    path.join(__dirname, "shared/chart_board_backtest.js"),
    "utf8",
);

assert.match(source, /ths_monthly_threshold/, "前端应识别THS月度阈值模型");
assert.match(source, /isThsMonthlyThreshold/, "应使用独立的模型判断避免影响其它模型");
assert.match(source, /\.endsWith\("\.THS"\)/, "模型应校验输入代码为.THS");
assert.match(source, /sell_rules:\s*isThsMonthlyThreshold\(\)\s*\?\s*\[\]/, "THS模型不应提交卖出因子");
assert.match(source, /cross_section_percentile/, "THS模型应保留截面排名/比例模式");

console.log("THS板块月度阈值模型前端测试通过");
