const fs = require("fs");
const path = require("path");
const assert = require("assert");

const root = __dirname;
const pagePath = path.join(root, "可视化", "模型有效性", "index.html");
const navPath = path.join(root, "可视化", "shared", "edge_float_nav.js");
const livePagePath = path.join(root, "可视化", "实盘面", "index.html");
const liveCssPath = path.join(root, "可视化", "实盘面", "live_board.css");
const webStartPath = path.join(root, "可视化", "start_web_server.bat");
const rootWrapperPath = path.join(root, "可视化", "模型有效性.html");
const page = fs.readFileSync(pagePath, "utf8");
const nav = fs.readFileSync(navPath, "utf8");
const livePage = fs.readFileSync(livePagePath, "utf8");
const liveCss = fs.readFileSync(liveCssPath, "utf8");
const webStart = fs.readFileSync(webStartPath, "utf8");
const rootWrapper = fs.readFileSync(rootWrapperPath, "utf8");
const pageCss = fs.readFileSync(path.join(root, "可视化", "模型有效性", "model_validity.css"), "utf8");
const pageJs = fs.readFileSync(path.join(root, "可视化", "模型有效性", "model_validity.js"), "utf8");

assert.match(page, /<title>模型有效性<\/title>/);
assert.match(page, /window\.PAGE_VIEW\s*=\s*["']model-validity["']/);
assert.strictEqual((page.match(/class=["'][^"']*model-chart-card/g) || []).length, 6);
assert.match(page, /edge-float-hud/);
assert.match(page, /lightweight-charts\.standalone\.production\.js/);
assert.match(page, /href="\.\.\/实盘面\/index\.html"/);
assert.match(nav, /model-validity/);
assert.match(livePage, /模型有效性\/index\.html/);
assert.match(liveCss, /live-model-link/);
assert.match(webStart, /模型有效性\/index\.html/);
assert.match(rootWrapper, /模型有效性\/index\.html/);

assert.match(page, /model-validity-zoom-content/);
assert.match(page, /model-validity-zoom-controls/);
assert.match(page, /model-validity-zoom-decrease/);
assert.match(page, /model-validity-zoom-reset/);
assert.match(page, /model-validity-zoom-increase/);
assert.match(pageCss, /--model-validity-zoom/);
assert.match(pageCss, /body\.page-model-validity[\s\S]*?margin:\s*0/);
assert.match(pageCss, /\.model-validity-shell[\s\S]*?box-sizing:\s*border-box/);
assert.match(pageJs, /DEFAULT_ZOOM\s*=\s*1\.25/);
assert.match(pageJs, /localStorage/);
assert.match(pageJs, /model-validity-zoom-decrease/);
assert.match(pageJs, /model-validity-zoom-increase/);

console.log("模型有效性页面契约通过");
