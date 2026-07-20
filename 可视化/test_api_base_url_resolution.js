const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const files = [
    "shared/chart_board_core.js",
    "shared/chart_board_info_core.js",
];

function loadResolver(relativePath) {
    const source = fs.readFileSync(path.join(__dirname, relativePath), "utf8");
    const start = source.indexOf("function resolveApiBaseUrl()");
    const nextSection = source.indexOf("\n\n", source.indexOf("\n}", start) + 2);
    assert.notEqual(start, -1, `${relativePath} 缺少 resolveApiBaseUrl`);
    assert.notEqual(nextSection, -1, `${relativePath} 无法定位 resolveApiBaseUrl 结尾`);

    const context = {
        URL,
        URLSearchParams,
        localStorage: { getItem: () => null },
        window: {
            location: {
                protocol: "https:",
                hostname: "bowenquant.yishida.online",
                origin: "https://bowenquant.yishida.online",
                search: "",
            },
        },
    };
    vm.runInNewContext(`${source.slice(start, nextSection)}\nresult = resolveApiBaseUrl();`, context);
    return context.result;
}

for (const file of files) {
    assert.equal(
        loadResolver(file),
        "https://bowenquant.yishida.online",
        `${file} 在 HTTPS 下必须使用同域 API`,
    );
}

console.log("API 地址解析测试通过");
