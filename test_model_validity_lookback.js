const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const root = __dirname;
const visualDir = String.fromCodePoint(0x53ef, 0x89c6, 0x5316);
const validityDir = String.fromCodePoint(0x6a21, 0x578b, 0x6709, 0x6548, 0x6027);
const script = fs.readFileSync(path.join(root, visualDir, validityDir, "model_validity.js"), "utf8");
const context = {
    window: { STYLE_MONITOR_API_BASE: "http://127.0.0.1:8000", addEventListener() {} },
    document: { readyState: "loading", addEventListener() {} },
    fetch() {},
};

vm.runInNewContext(script, context);
const calculateLookbackStart = context.window.ModelValidity.calculateLookbackStart;

assert.strictEqual(calculateLookbackStart("2026-08-03", 1), "2026-08-03");
assert.strictEqual(calculateLookbackStart("2026-08-03", 10), "2026-07-25");
assert.strictEqual(calculateLookbackStart("2026-08-03", 0), null);
assert.strictEqual(calculateLookbackStart("2026-08-03", 20001), null);
assert.strictEqual(calculateLookbackStart("", 10), null);

console.log("模型有效性回看天数测试通过");
