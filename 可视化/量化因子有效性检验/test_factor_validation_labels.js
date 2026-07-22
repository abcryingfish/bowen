const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "factor_validation.js"), "utf8");

function extractFunction(name) {
    const start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `缺少 ${name}`);
    const end = source.indexOf(" }", start);
    assert.notEqual(end, -1, `无法定位 ${name} 结尾`);
    return source.slice(start, end + 2);
}

const stateMatch = source.match(/const state = \{[^;]+\};/);
assert.ok(stateMatch, "缺少 state 声明");

const context = {};
vm.runInNewContext(`
${stateMatch[0]}
${extractFunction("factorLabel")}
state.factorLabels = {
    "morph/level3/piercing": "三级形态 / 刺透形态",
};
result = [
    factorLabel("morph/level3/piercing"),
    factorLabel("普通因子"),
];
`, context);

assert.deepEqual(Array.from(context.result), ["三级形态 / 刺透形态", "普通因子"]);
assert.match(source, /factor:\s*state\.selectedFactor/, "请求必须继续提交英文技术键");
assert.match(source, /const label = factorLabel\(name\)/, "因子列表必须使用中文标签");
assert.match(source, /factorLabel\(record\.factor\)/, "历史记录必须使用中文标签");

console.log("有效性检验中文显示名测试通过");

