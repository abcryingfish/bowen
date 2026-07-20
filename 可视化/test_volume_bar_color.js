const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
    path.join(__dirname, "shared/chart_board_core.js"),
    "utf8",
);

function extractDeclaration(name) {
    const match = source.match(new RegExp(`const ${name} = [^;]+;`));
    assert.ok(match, `缺少 ${name}`);
    return match[0];
}

function extractFunction(name) {
    const start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `缺少 ${name}`);
    const end = source.indexOf("\n}\n", start);
    assert.notEqual(end, -1, `无法定位 ${name} 结尾`);
    return source.slice(start, end + 2);
}

const context = {};
vm.runInNewContext(`
${extractDeclaration("A_SHARE_UP_COLOR")}
${extractDeclaration("A_SHARE_DOWN_COLOR")}
${extractDeclaration("A_SHARE_FLAT_VOLUME_COLOR")}
${extractFunction("getAShareBarColor")}
${extractFunction("getAShareVolumeColor")}
result = [
    getAShareVolumeColor({ open: 10, close: 11 }),
    getAShareVolumeColor({ open: 10, close: 9 }),
    getAShareVolumeColor({ open: 10, close: 10 }),
    getAShareVolumeColor({ open: 9, close: 10 }, { close: 10 }),
    getAShareVolumeColor({ open: 12, close: 11 }, { close: 10 }),
    getAShareBarColor({ open: 10, close: 10 }),
];
`, context);

assert.deepEqual(
    Array.from(context.result),
    ["#ef5350", "#26a69a", "#ffffff", "#ffffff", "#ef5350", "#ef5350"],
);

const modalVolumeStart = source.indexOf("tvDayMinuteVolumeSeries.setData(");
assert.notEqual(modalVolumeStart, -1, "缺少日频双击弹窗成交量数据映射");
const modalVolumeEnd = source.indexOf(")));", modalVolumeStart);
assert.notEqual(modalVolumeEnd, -1, "无法定位日频双击弹窗成交量数据映射结尾");
assert.match(
    source.slice(modalVolumeStart, modalVolumeEnd + 3),
    /bars\.map\(\(item,\s*index\)[\s\S]*color:\s*getAShareVolumeColor\(\s*item,\s*index > 0 \? bars\[index - 1\] : openingPreviousBar\s*\)/,
    "日频双击弹窗成交量必须比较上一分钟收盘价",
);
assert.match(
    source,
    /const openingPreviousBar = Number\.isFinite\(prevClosePrice\)[\s\S]*\{ close: prevClosePrice \}[\s\S]*: null;/,
    "日频双击弹窗第一分钟必须使用前收盘价",
);

console.log("成交量颜色测试通过");
