const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "形态面/board_morph.js"), "utf8");

function extractFunction(name) {
    const start = source.indexOf(`function ${name}(`);
    assert(start >= 0, `找不到函数: ${name}`);
    const braceStart = source.indexOf("{", start);
    let depth = 0;
    for (let idx = braceStart; idx < source.length; idx += 1) {
        if (source[idx] === "{") depth += 1;
        if (source[idx] === "}") depth -= 1;
        if (depth === 0) return source.slice(start, idx + 1);
    }
    throw new Error(`函数未闭合: ${name}`);
}

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.value = "";
        this.textContent = "";
        this.disabled = false;
    }

    appendChild(child) {
        this.children.push(child);
    }

    replaceChildren() {
        this.children = [];
    }
}

const selectEl = new FakeElement("select");
const context = {
    console,
    morphPatternPointsByName: new Map(),
    morphPatternDisplayNames: new Map([
        ["engulfing", "吞没形态"],
        ["piercing", "刺透形态"],
    ]),
    selectedMorphPatternName: "engulfing",
    document: {
        getElementById: (id) => id === "morph-pattern-filter-select" ? selectEl : null,
        createElement: (tagName) => new FakeElement(tagName),
    },
};
vm.createContext(context);
vm.runInContext([
    extractFunction("getMorphPatternDisplayName"),
    extractFunction("getVisibleMorphPatternNames"),
    extractFunction("syncMorphPatternFilterOptions"),
].join("\n"), context);

context.morphPatternPointsByName.set("engulfing", [{ time: 1, value: 1 }]);
context.morphPatternPointsByName.set("piercing", [{ time: 2, value: 1 }]);
context.syncMorphPatternFilterOptions();
assert.strictEqual(selectEl.value, "engulfing");
assert.deepStrictEqual(Array.from(context.getVisibleMorphPatternNames()), ["engulfing"]);

context.morphPatternPointsByName.clear();
context.morphPatternPointsByName.set("piercing", [{ time: 3, value: 1 }]);
context.syncMorphPatternFilterOptions();
assert.strictEqual(context.selectedMorphPatternName, "engulfing");
assert.strictEqual(selectEl.value, "engulfing");
assert.strictEqual(selectEl.disabled, false);
assert(selectEl.children.some((item) => item.textContent === "吞没形态（当前股票无信号）"));
assert.deepStrictEqual(Array.from(context.getVisibleMorphPatternNames()), []);

console.log("形态筛选跨股票保持测试通过");
