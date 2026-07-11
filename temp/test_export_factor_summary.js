const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sourcePath = path.resolve(__dirname, "../可视化/量化因子/board_quant.js");
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

const sandbox = {
    factorGroups: [
        {
            group_id: "volume",
            group_name: "量能组",
            children: ["volume_score", "break_volume", "pullback_volume"],
        },
    ],
    getDisplayLabelForFactorColumn(name) {
        const labels = {
            volume_score: "量能总分",
            break_volume: "放量突破",
            pullback_volume: "缩量回踩",
        };
        return labels[name] || name;
    },
};
vm.createContext(sandbox);
vm.runInContext(`
${extractFunction("formatExportSelectedFactorSummaryText")}
${extractFunction("getExportSummaryFactorNamesForGroup")}
${extractFunction("buildExportFactorOptionsForGroup")}
`, sandbox);

function assertEqual(actual, expected, message) {
    if (actual !== expected) {
        throw new Error(`${message}: expected ${expected}, got ${actual}`);
    }
}

assertEqual(
    sandbox.formatExportSelectedFactorSummaryText({
        label: "量能组 / 放量突破 (break_volume)",
    }),
    "Selected: 量能组 / 放量突破 (break_volume)",
    "summary should show the selected concrete factor, not expand the group name"
);

assertEqual(
    sandbox.getExportSummaryFactorNamesForGroup({
        group_id: "volume",
        children: ["volume_score"],
    }).join(","),
    "volume_score,break_volume,pullback_volume",
    "summary factor list should come from catalog children even when snapshot only has core factors"
);

const options = sandbox.buildExportFactorOptionsForGroup({
    group_id: "volume",
    group_name: "量能组",
    children: ["volume_score"],
});
assertEqual(
    options.map((item) => item.value).join(","),
    "volume_score,break_volume,pullback_volume",
    "export select should expose every factor as its own option"
);
assertEqual(
    options[1].label,
    "量能组 / 放量突破 (break_volume)",
    "export option label should identify the group and the concrete factor"
);

console.log("export factor summary tests passed");
