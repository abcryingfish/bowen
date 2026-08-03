const fs = require("fs");
const path = require("path");
const assert = require("assert");

const root = __dirname;
const factorDir = path.join(root, "ZXW\u56e0\u5b50");
const generatorPath = path.join(factorDir, "ZXW\u7b56\u7565\u6280\u672f\u56e0\u5b50\u751f\u6210.py");
const pureBundlePath = path.join(factorDir, "\u7eaf\u6280\u672f\u9762\u56e0\u5b50_bundle.py");
const notebookPath = path.join(factorDir, "ZXW\u7b56\u7565\u6280\u672f\u56e0\u5b50\u751f\u6210.ipynb");

const generator = fs.readFileSync(generatorPath, "utf8");
const pureBundle = fs.readFileSync(pureBundlePath, "utf8");

assert.strictEqual(fs.existsSync(notebookPath), false, "旧版 ZXW 因子 notebook 应已删除");
assert.match(generator, /from \u7eaf\u6280\u672f\u9762\u56e0\u5b50_bundle import/);
assert.match(generator, /get_pure_technical_lookback_config/);
assert.match(generator, /iter_pure_technical_factor_bundles/);
assert.match(generator, /["']pure_technical["']/);
assert.match(pureBundle, /BUNDLE_ID\s*=\s*["']pure_technical["']/);
assert.match(pureBundle, /selected_factors/);

console.log("ZXW 因子生成入口契约通过");
