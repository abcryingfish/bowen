const fs = require("fs");
const path = require("path");
const assert = require("assert");

const root = __dirname;
const hud = fs.readFileSync(path.join(root, "可视化", "shared", "edge_float_hud.js"), "utf8");
const nav = fs.readFileSync(path.join(root, "可视化", "shared", "edge_float_nav.js"), "utf8");
const multiPage = fs.readFileSync(path.join(root, "可视化", "多维度分析", "index.html"), "utf8");
const hudPages = [
    ["量化因子", "index.html"],
    ["量化因子有效性检验", "dashboard.html"],
    ["结果展示", "index.html"],
    ["组合结果", "index.html"],
    ["实盘面", "index.html", "live_board.js"],
    ["多维度分析", "index.html"],
    ["模型有效性", "index.html"],
    ["板块轮动", "index.html"],
    ["形态面", "index.html"],
    ["舆情面", "index.html"],
    ["基本面", "index.html"],
];

assert.match(hud, /__edgeFloatHudInitialized/);
assert.match(hud, /PAGE_VIEW/);
const navContext = { window: {}, globalThis: {} };
require("vm").runInNewContext(nav, navContext);
const modelPage = navContext.window.EdgeFloatNav.PAGES.find((item) => item.id === "model-validity");
assert.ok(modelPage);
const resolvedPath = decodeURIComponent(new URL(modelPage.file, "http://127.0.0.1:8086/量化因子有效性检验/dashboard.html").pathname);
assert.match(resolvedPath, /模型有效性\/index\.html$/);
const sectorPage = navContext.window.EdgeFloatNav.PAGES.find((item) => item.id === "sector-rotation");
assert.ok(sectorPage);
assert.strictEqual(sectorPage.label, "板块轮动");
const sectorPath = decodeURIComponent(new URL(sectorPage.file, "http://127.0.0.1:8086/量化因子/index.html").pathname);
assert.match(sectorPath, /板块轮动\/index\.html$/);
assert.match(multiPage, /edge-float-hud/);
assert.match(multiPage, /shared\/edge_float\.css/);
assert.match(multiPage, /PAGE_VIEW\s*=\s*["']multi-dimensional-analysis["']/);

for (const parts of hudPages) {
    const [directory, htmlFile, initFile] = parts;
    const label = `${directory}/${htmlFile}`;
    const page = fs.readFileSync(path.join(root, "可视化", directory, htmlFile), "utf8");
    const initSource = initFile ? fs.readFileSync(path.join(root, "可视化", directory, initFile), "utf8") : page;
    assert.match(page, /id="edge-float-hud"/, `${label} 缺少 edge-float-hud`);
    assert.match(page, /edge_float_nav\.js/, `${label} 未加载公共悬浮导航`);
    assert.match(page, /edge_float_hud\.js/, `${label} 未加载 HUD 控制脚本`);
    assert.match(initSource, /PAGE_VIEW\s*=|initEdgeFloatHud\s*\(\s*\{\s*pageId:/, `${label} 缺少 HUD 页面标识`);
}

console.log("悬浮球导航兜底契约通过");
