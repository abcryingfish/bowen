const fs = require("fs");
const path = require("path");
const assert = require("assert");

const root = __dirname;
const hud = fs.readFileSync(path.join(root, "可视化", "shared", "edge_float_hud.js"), "utf8");
const nav = fs.readFileSync(path.join(root, "可视化", "shared", "edge_float_nav.js"), "utf8");
const multiPage = fs.readFileSync(path.join(root, "可视化", "多维度分析", "index.html"), "utf8");

assert.match(hud, /__edgeFloatHudInitialized/);
assert.match(hud, /PAGE_VIEW/);
const navContext = { window: {}, globalThis: {} };
require("vm").runInNewContext(nav, navContext);
const modelPage = navContext.window.EdgeFloatNav.PAGES.find((item) => item.id === "model-validity");
assert.ok(modelPage);
const resolvedPath = decodeURIComponent(new URL(modelPage.file, "http://127.0.0.1:8086/量化因子有效性检验/dashboard.html").pathname);
assert.match(resolvedPath, /模型有效性\/index\.html$/);
assert.match(multiPage, /edge-float-hud/);
assert.match(multiPage, /shared\/edge_float\.css/);
assert.match(multiPage, /PAGE_VIEW\s*=\s*["']multi-dimensional-analysis["']/);

console.log("悬浮球导航兜底契约通过");
