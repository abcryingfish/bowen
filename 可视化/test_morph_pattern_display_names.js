const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const coreSource = fs.readFileSync(
    path.join(__dirname, "shared/chart_board_core.js"),
    "utf8",
);
const morphSource = fs.readFileSync(
    path.join(__dirname, "形态面/board_morph.js"),
    "utf8",
);

function extractDeclaration(source, name) {
    const match = source.match(new RegExp(`const ${name} = [^;]+;`));
    assert.ok(match, `缺少 ${name}`);
    return match[0];
}

function extractFunction(source, name) {
    const start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `缺少 ${name}`);
    const end = source.indexOf("\n}\n", start);
    assert.notEqual(end, -1, `无法定位 ${name} 结尾`);
    return source.slice(start, end + 2);
}

const context = {};
vm.runInNewContext(`
${extractDeclaration(coreSource, "morphPatternDisplayNames")}
${extractFunction(morphSource, "applyMorphPatternDisplayNames")}
${extractFunction(morphSource, "getMorphPatternDisplayName")}
applyMorphPatternDisplayNames({
    meta: { pattern_display_names: { piercing: "刺透形态" } },
});
result = [
    getMorphPatternDisplayName("piercing"),
    getMorphPatternDisplayName("unknown_pattern"),
];
`, context);

assert.deepEqual(Array.from(context.result), ["刺透形态", "unknown_pattern"]);
assert.match(
    morphSource,
    /applyMorphPatternDisplayNames\(payload\);[\s\S]*const patterns = payload/,
    "形态响应写入数据前必须先应用中文显示名",
);

console.log("形态中文显示名测试通过");
