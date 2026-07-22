# Morph Candlestick Chinese Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every candlestick pattern name appear in Chinese on both the morphology dashboard and factor-validation dashboard while retaining English technical keys for storage and queries.

**Architecture:** `形态趋势通道因子/morph_candlestick_meta.py` becomes the single naming source and writes `display_name` into the UTF-8 manifest. Both backend services expose labels from that manifest; both frontends render labels but keep English keys in state, request parameters, SQL filters, and deduplication keys. Missing labels fall back to the English key.

**Tech Stack:** Python 3.10, JSON/UTF-8, DuckDB, unittest/pytest, vanilla JavaScript, existing browser dashboard.

---

## File Map

- Modify `形态趋势通道因子/morph_candlestick_meta.py`: own the complete English-to-Chinese mapping and add labels to manifest entries.
- Modify `test_candlestick_one_pattern_one_signal.py`: enforce complete, unique mappings and UTF-8 manifest behavior.
- Modify `可视化/market_data_service.py`: expose display labels with morphology pattern/event responses.
- Create `test_market_data_service_morph_display_names.py`: test label response and English fallback without live data.
- Modify `可视化/shared/chart_board_core.js`: remove the incomplete duplicated static mapping and hold response-driven labels.
- Modify `可视化/形态面/board_morph.js`: consume response labels for chart overlays.
- Modify `可视化/量化因子有效性检验/factor_validation_service.py`: expose factor labels while preserving factor IDs.
- Modify `可视化/量化因子有效性检验/test_factor_validation_jobs.py`: cover Chinese labels and old-manifest fallback.
- Modify `可视化/量化因子有效性检验/factor_validation.js`: display/search/select/restore records with Chinese labels while submitting English IDs.
- Create `可视化/量化因子有效性检验/test_factor_validation_labels.js`: source-level Node contract test that extracts and executes the label helper without a browser DOM.

### Task 1: Complete the canonical Chinese name metadata

**Files:**
- Modify: `test_candlestick_one_pattern_one_signal.py`
- Modify: `形态趋势通道因子/morph_candlestick_meta.py`

- [ ] **Step 1: Write failing metadata tests**

Add tests that require every signal to have one non-empty, unique Chinese display name and verify representative names:

```python
def test_pattern_names_have_complete_unique_chinese_display_names():
    pattern_module = _load_module("candlestick_patterns_display", PATTERN_FILE)
    meta_module = _load_module("candlestick_metadata_display", META_FILE)
    signal_names = set(pattern_module.Pattern().signal_strength)

    assert set(meta_module.SIGNAL_DISPLAY_NAME_ZH) == signal_names
    labels = list(meta_module.SIGNAL_DISPLAY_NAME_ZH.values())
    assert all(label.strip() for label in labels)
    assert len(labels) == len(set(labels))
    assert meta_module.SIGNAL_DISPLAY_NAME_ZH["engulfing_bullish"] == "看涨吞没"
    assert meta_module.SIGNAL_DISPLAY_NAME_ZH["three_crows"] == "三只乌鸦"


def test_manifest_contains_utf8_display_names(tmp_path):
    meta_module = _load_module("candlestick_metadata_manifest_display", META_FILE)
    manifest = meta_module.build_pattern_manifest({"piercing": 0.7})
    path = meta_module.write_manifest(manifest, tmp_path)

    assert manifest["patterns"]["piercing"]["display_name"] == "刺透形态"
    assert "刺透形态" in path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest test_candlestick_one_pattern_one_signal.py -q
```

Expected: FAIL because `SIGNAL_DISPLAY_NAME_ZH` and manifest `display_name` do not exist.

- [ ] **Step 3: Add the complete mapping and manifest field**

Define `SIGNAL_DISPLAY_NAME_ZH: dict[str, str]` for every key in `SIGNAL_BAR_SPAN`. Preserve the approved existing names including “看涨孕线、看跌孕线、十字晨星、锤子线、上吊线、看涨吞没、看跌吞没、乌云盖顶、刺透形态、启明星、黄昏星、十字暮星、看涨弃婴、看跌弃婴、看涨十字孕线、看跌十字孕线、平头顶部、平头底部、看涨捉腰带线、看跌捉腰带线、看涨反击线、看跌反击线、两只乌鸦、三只乌鸦、红三兵、上升三法、下降三法”；give every remaining technical key one unique conventional Chinese name. In `build_pattern_manifest`, add:

```python
"display_name": SIGNAL_DISPLAY_NAME_ZH.get(name, name),
```

Keep `ensure_ascii=False` and `encoding="utf-8"` unchanged.

- [ ] **Step 4: Run the focused tests and confirm pass**

Run the Step 2 command. Expected: all tests in the file PASS.

- [ ] **Step 5: Commit the metadata slice**

```powershell
git add -- '形态趋势通道因子/morph_candlestick_meta.py' 'test_candlestick_one_pattern_one_signal.py'
git commit -m "feat: add Chinese candlestick display names"
```

### Task 2: Return Chinese labels from the morphology market-data API

**Files:**
- Create: `test_market_data_service_morph_display_names.py`
- Modify: `可视化/market_data_service.py`

- [ ] **Step 1: Write failing service tests**

Load `market_data_service.py` with this fixed project-path import and test a manifest containing `display_name` and an old manifest without it:

```python
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVICE_FILE = ROOT / "可视化" / "market_data_service.py"
spec = importlib.util.spec_from_file_location("market_data_service_morph_labels", SERVICE_FILE)
assert spec and spec.loader
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
```

Then test the mapping helper:

```python
def test_morph_pattern_display_names_use_manifest_and_fallback():
    manifest = {
        "patterns": {
            "piercing": {"level": "level3", "display_name": "刺透形态"},
            "unknown_pattern": {"level": "level3"},
        }
    }
    assert service._morph_pattern_display_names(manifest, ["piercing", "unknown_pattern"]) == {
        "piercing": "刺透形态",
        "unknown_pattern": "unknown_pattern",
    }
```

Add a service helper assertion that `service._morph_event_display_name(manifest, "piercing") == "刺透形态"` and `service._morph_event_display_name(manifest, "unknown_pattern") == "unknown_pattern"`. The implementation step wires this helper into every returned event and puts the complete mapping in `meta.pattern_display_names`.

- [ ] **Step 2: Run the new test and confirm failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest test_market_data_service_morph_display_names.py -q
```

Expected: FAIL because `_morph_pattern_display_names` and response labels do not exist.

- [ ] **Step 3: Implement response labels without changing keys**

Add a helper:

```python
def _morph_pattern_display_names(manifest: dict[str, Any], pattern_names: list[str]) -> dict[str, str]:
    patterns = manifest.get("patterns") or {}
    return {
        name: str((patterns.get(name) or {}).get("display_name") or name)
        for name in pattern_names
    }
```

Use it to add `display_name` to each event and `pattern_display_names` to both normal and empty `meta` responses. Do not change the keys of the `patterns` object.

- [ ] **Step 4: Run the new and existing market-data tests**

```powershell
& .\.venv\Scripts\python.exe -m pytest test_market_data_service_morph_display_names.py 可视化/test_market_data_service_index_search.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the market API slice**

```powershell
git add -- '可视化/market_data_service.py' 'test_market_data_service_morph_display_names.py'
git commit -m "feat: expose Chinese morph labels in market API"
```

### Task 3: Render API-provided labels on the morphology dashboard

**Files:**
- Modify: `可视化/shared/chart_board_core.js`
- Modify: `可视化/形态面/board_morph.js`
- Create: `可视化/test_morph_pattern_display_names.js`

- [ ] **Step 1: Add a failing JavaScript contract test**

Create a Node test using the same `fs` + `vm` extraction pattern as `可视化/test_volume_bar_color.js`. Extract `morphPatternDisplayNames`, `getMorphPatternDisplayName`, and the new `applyMorphPatternDisplayNames` helper, then evaluate:

```javascript
assert.equal(getMorphPatternDisplayName("piercing"), "刺透形态");
assert.equal(getMorphPatternDisplayName("new_pattern"), "new_pattern");
```

The fixture must first apply `{ meta: { pattern_display_names: { piercing: "刺透形态" } } }` and must assert the internal pattern key remains `piercing`.

- [ ] **Step 2: Run the JavaScript test and confirm failure**

```powershell
node 可视化\test_morph_pattern_display_names.js
```

Expected: FAIL because the existing static mapping cannot consume response labels and is incomplete.

- [ ] **Step 3: Replace the static partial map with response-driven state**

In shared core, replace `MORPH_PATTERN_NAME_ZH` with:

```javascript
const morphPatternDisplayNames = new Map();
```

In `applyMorphCandlestickPayload`, merge `payload.meta.pattern_display_names` into the map. Update `getMorphPatternDisplayName` to use the map and fall back to the English key:

```javascript
return morphPatternDisplayNames.get(key) || key;
```

Continue using English names for `morphPatternPointsByName`, colors, event deduplication, and request parameters.

- [ ] **Step 4: Run JavaScript tests**

```powershell
node 可视化\test_morph_pattern_display_names.js
node 可视化\test_volume_bar_color.js
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit the morphology frontend slice**

```powershell
git add -- '可视化/shared/chart_board_core.js' '可视化/形态面/board_morph.js' '可视化/test_morph_pattern_display_names.js'
git commit -m "feat: render Chinese morph labels on chart"
```

### Task 4: Expose stable IDs and Chinese labels to factor validation

**Files:**
- Modify: `可视化/量化因子有效性检验/test_factor_validation_jobs.py`
- Modify: `可视化/量化因子有效性检验/factor_validation_service.py`

- [ ] **Step 1: Update tests to use English IDs and Chinese labels**

Replace the Chinese IDs in the morphology fixtures with `engulfing_bullish` and `piercing`. Require this response contract:

```python
self.assertEqual(
    morph_group["children"],
    ["morph/level1/engulfing_bullish", "morph/level2/piercing"],
)
self.assertEqual(
    payload["factor_labels"],
    {
        "morph/level1/engulfing_bullish": "一级形态 / 看涨吞没",
        "morph/level2/piercing": "二级形态 / 刺透形态",
    },
)
```

Add a legacy manifest assertion that a missing `display_name` falls back to the English signal key.

- [ ] **Step 2: Run the focused test and confirm failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest '可视化/量化因子有效性检验/test_factor_validation_jobs.py' -q
```

Expected: FAIL because `factor_labels` is absent.

- [ ] **Step 3: Implement factor label construction**

Add level labels and a helper that parses `morph/<level>/<signal_name>`, reads `display_name` from the manifest, and returns:

```python
MORPH_LEVEL_LABELS = {
    "level1": "一级形态",
    "level2": "二级形态",
    "level3": "三级形态",
}
```

Return `factor_labels` from `list_factor_validation_factors`. Ordinary factors map to themselves. Keep `factors`, group `children`, `_parse_morph_factor_name`, SQL filters, and result `meta.factor` unchanged.

- [ ] **Step 4: Run the focused test and confirm pass**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit the validation API slice**

```powershell
git add -- '可视化/量化因子有效性检验/factor_validation_service.py' '可视化/量化因子有效性检验/test_factor_validation_jobs.py'
git commit -m "feat: expose Chinese factor validation labels"
```

### Task 5: Render Chinese labels in factor validation without changing requests

**Files:**
- Modify: `可视化/量化因子有效性检验/factor_validation.js`
- Create: `可视化/量化因子有效性检验/test_factor_validation_labels.js`

- [ ] **Step 1: Write failing label behavior tests**

Create a Node `fs` + `vm` source-level test. Extract the `state` declaration and `factorLabel` helper from `factor_validation.js`, assign `state.factorLabels`, and assert:

```javascript
assert.equal(factorLabel("morph/level3/piercing"), "三级形态 / 刺透形态");
assert.equal(factorLabel("普通因子"), "普通因子");
assert.equal(requestPayload().factor, "morph/level3/piercing");
```

Also require search matching by both Chinese label and English technical key.

- [ ] **Step 2: Run the new test and confirm failure**

```powershell
node '可视化\量化因子有效性检验\test_factor_validation_labels.js'
```

Expected: FAIL because the page has no `factorLabels` state or `factorLabel` helper.

- [ ] **Step 3: Implement display-only label use**

Add `factorLabels` to state and populate it from `payload.factor_labels`. Add:

```javascript
function factorLabel(name) {
    const key = String(name || "").trim();
    return state.factorLabels[key] || key;
}
```

Use this helper in factor list text/search, selected-factor text, status messages, saved/restored record titles, and record cards. Retain the English technical key in `data-factor`, `state.selectedFactor`, request payloads, and saved `factor` fields.

- [ ] **Step 4: Run JavaScript and Python validation tests**

```powershell
node '可视化\量化因子有效性检验\test_factor_validation_labels.js'
& .\.venv\Scripts\python.exe -m pytest '可视化/量化因子有效性检验/test_factor_validation_jobs.py' -q
```

Expected: PASS.

- [ ] **Step 5: Commit the validation frontend slice**

```powershell
git add -- '可视化/量化因子有效性检验/factor_validation.js' '可视化/量化因子有效性检验/test_factor_validation_labels.js'
git commit -m "feat: show Chinese labels in factor validation"
```

### Task 6: Refresh manifest and verify end to end

**Files:**
- Generated external data: `D:\database\signal_daily_形态\candlestick_no_vol\morph_candlestick_manifest.json`

- [ ] **Step 1: Run the full focused regression suite**

```powershell
& .\.venv\Scripts\python.exe -m pytest test_candlestick_one_pattern_one_signal.py test_morph_candlestick_signal_generation.py test_market_data_service_morph_display_names.py '可视化/量化因子有效性检验/test_factor_validation_jobs.py' -q
node 可视化\test_morph_pattern_display_names.js
node '可视化\量化因子有效性检验\test_factor_validation_labels.js'
```

Expected: all tests PASS and both Node commands exit 0.

- [ ] **Step 2: Regenerate only the manifest from current algorithm metadata**

Use the project virtual environment to load `Pattern().signal_strength`, call `build_pattern_manifest`, and call `write_manifest` for the existing morphology data root. Do not run parquet generation and do not rewrite factor/event partitions.

- [ ] **Step 3: Validate the generated UTF-8 manifest**

Confirm all pattern entries contain unique `display_name` values, `engulfing_bullish` remains the JSON key, and the raw UTF-8 file contains `看涨吞没` without `\u` escaping.

- [ ] **Step 4: Start the existing web/API servers and inspect both pages**

Open:

```text
http://127.0.0.1:8086/形态面/index.html
http://127.0.0.1:8086/量化因子有效性检验/dashboard.html
```

Verify the morphology overlay displays Chinese, factor validation lists/searches/selects Chinese labels, requests still contain English `morph/level*/...` identifiers, and no label overlaps or mojibake appear at desktop and mobile widths.

- [ ] **Step 5: Review the final diff**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files plus pre-existing unrelated user changes are present.
