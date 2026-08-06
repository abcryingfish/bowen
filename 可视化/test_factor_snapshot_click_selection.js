const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
    path.join(__dirname, "量化因子/board_quant.js"),
    "utf8",
);

const dragEndStart = source.indexOf("function endFactorSnapshotDrag(event)");
const nextFunctionStart = source.indexOf("function removeFactorGroupDragGhost()", dragEndStart);
assert.notEqual(dragEndStart, -1, "应存在因子拖拽结束处理函数");
assert.notEqual(nextFunctionStart, -1, "应能定位因子拖拽结束处理函数边界");

const dragEndSource = source.slice(dragEndStart, nextFunctionStart);
assert.doesNotMatch(
    dragEndSource,
    /selectFactorAndRefresh|toggleFactorActiveState/,
    "普通点击应只由 click 处理器选择因子，pointerup 不应重复选择或取消",
);

assert.match(
    source,
    /listEl\.addEventListener\("click",[\s\S]{0,1800}selectFactorAndRefresh\(factorName\)/,
    "因子列表 click 处理器应保留唯一的选择入口",
);

console.log("因子快照单次点击选择测试通过");
