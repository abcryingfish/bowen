const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sourcePath = path.resolve(__dirname, "../可视化/shared/chart_board_core.js");
const source = fs.readFileSync(sourcePath, "utf8");

function extractFunction(name) {
    const marker = `function ${name}`;
    const start = source.indexOf(marker);
    if (start < 0) {
        throw new Error(`${name} not found`);
    }
    const braceStart = source.indexOf("{", start);
    let depth = 0;
    for (let i = braceStart; i < source.length; i += 1) {
        const ch = source[i];
        if (ch === "{") {
            depth += 1;
        } else if (ch === "}") {
            depth -= 1;
            if (depth === 0) {
                return source.slice(start, i + 1);
            }
        }
    }
    throw new Error(`${name} body not closed`);
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(`
function normalizeCodeValue(codeValue) {
    return String(codeValue || "").trim().toUpperCase();
}
${extractFunction("resolveKeyboardStockNavigationPool")}
${extractFunction("normalizeKeyboardStockCodeList")}
${extractFunction("resolveKeyboardStockNavigationTarget")}
${extractFunction("shouldBlockKeyboardStockNavigationForActiveElement")}
`, sandbox);

function assertEqual(actual, expected, message) {
    if (actual !== expected) {
        throw new Error(`${message}: expected ${expected}, got ${actual}`);
    }
}

function assertDeepEqual(actual, expected, message) {
    const actualJson = JSON.stringify(actual);
    const expectedJson = JSON.stringify(expected);
    if (actualJson !== expectedJson) {
        throw new Error(`${message}: expected ${expectedJson}, got ${actualJson}`);
    }
}

assertDeepEqual(
    sandbox.resolveKeyboardStockNavigationPool(
        "000950.SZ",
        ["002588.SZ", "000950.SZ", "002555.SZ"],
        ["000001.SZ", "000002.SZ", "000950.SZ"]
    ),
    ["002588.SZ", "000950.SZ", "002555.SZ"],
    "current watchlist code should use watchlist pool"
);

assertDeepEqual(
    sandbox.resolveKeyboardStockNavigationPool(
        "000002.SZ",
        ["002588.SZ", "000950.SZ", "002555.SZ"],
        ["000001.SZ", "000002.SZ", "000003.SZ"]
    ),
    ["000001.SZ", "000002.SZ", "000003.SZ"],
    "non-watchlist current code should use market pool"
);

assertEqual(
    sandbox.resolveKeyboardStockNavigationTarget("002555.SZ", ["002588.SZ", "000950.SZ", "002555.SZ"], 1),
    "002588.SZ",
    "next should wrap to first item"
);

assertEqual(
    sandbox.resolveKeyboardStockNavigationTarget("002588.SZ", ["002588.SZ", "000950.SZ", "002555.SZ"], -1),
    "002555.SZ",
    "previous should wrap to last item"
);

assertEqual(
    sandbox.shouldBlockKeyboardStockNavigationForActiveElement("INPUT", "code-input", false),
    false,
    "code input focus should still allow numpad stock navigation"
);

assertEqual(
    sandbox.shouldBlockKeyboardStockNavigationForActiveElement("INPUT", "factor-snapshot-filter-input", false),
    true,
    "other input focus should block stock navigation"
);

console.log("keyboard stock navigation tests passed");
