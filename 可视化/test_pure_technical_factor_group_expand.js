const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
    path.join(__dirname, "量化因子/board_quant.js"),
    "utf8",
);

assert.match(
    source,
    /function\s+isFactorGroupWithoutCore\s*\(/,
    "应明确识别没有核心因子的目录组",
);

assert.match(
    source,
    /function\s+toggleFactorSnapshotGroup\s*\(/,
    "组头和展开按钮应复用同一展开切换逻辑",
);

assert.match(
    source,
    /const\s+groupHeader\s*=\s*event\.target\.closest\("\.factor-group-header"\)/,
    "点击组头应能展开或收起因子组",
);

assert.match(
    source,
    /const\s+keepAsDirectoryEntry\s*=\s*isFactorGroupWithoutCore\(group\)/,
    "核心快照没有该组值时，纯技术组仍应保留为目录入口",
);

assert.match(
    source,
    /isDirectoryOnlyGroup[\s\S]{0,800}factor-group-title[\s\S]{0,800}:\s*\([\s\S]{0,400}factor-snapshot-value/,
    "无核心因子组应只渲染组名，有核心因子组才渲染摘要值",
);

console.log("纯技术因子组展开测试通过");
