/* 量化因子专属逻辑，在 chart_board_core.js + chart_board_backtest.js 之后加载 */

function loadSignalSlotBindings() {
    const defaults = Object.fromEntries(SIGNAL_TYPE_TOGGLE_SPECS.map((item) => [item.key, ""]));
    try {
        const raw = JSON.parse(localStorage.getItem(SIGNAL_SLOT_BINDINGS_KEY) || "{}");
        if (!raw || typeof raw !== "object") {
            signalSlotBindings = defaults;
            return;
        }
        signalSlotBindings = { ...defaults };
        for (const spec of SIGNAL_TYPE_TOGGLE_SPECS) {
            const value = String(raw[spec.key] || "").trim();
            if (value) {
                signalSlotBindings[spec.key] = value;
            }
        }
    } catch {
        signalSlotBindings = defaults;
    }
}

function saveSignalSlotBindings() {
    try {
        localStorage.setItem(SIGNAL_SLOT_BINDINGS_KEY, JSON.stringify(signalSlotBindings));
    } catch {
        /* ignore */
    }
}

function applySignalSlotBindingUi() {
    if (!signalTypeTogglesWrap) {
        return;
    }
    signalTypeTogglesWrap.querySelectorAll(".signal-type-toggle[data-signal-type]").forEach((btnEl) => {
        const slotKey = String(btnEl.dataset.signalType || "");
        const factorName = String(signalSlotBindings[slotKey] || "").trim();
        btnEl.classList.toggle("signal-type-toggle-bound-active", Boolean(factorName));
        btnEl.classList.toggle("signal-type-toggle-empty", !factorName);
        const boundEl = btnEl.querySelector(".signal-type-toggle-bound");
        if (boundEl) {
            boundEl.textContent = factorName
                ? (getDisplayLabelForFactorColumn(factorName) || factorName)
                : "";
            boundEl.title = factorName || "";
        }
        const slotLabel = SIGNAL_TYPE_TOGGLE_SPECS.find((item) => item.key === slotKey)?.label || slotKey;
        btnEl.title = factorName
            ? (slotLabel + ": " + (getDisplayLabelForFactorColumn(factorName) || factorName) + "，拖拽可覆盖绑定，点击切换显示")
            : (slotLabel + ": 拖拽因子到此处绑定，点击切换显示");
    });
}

function getSignalSlotSeriesColor(slotKey) {
    return SIGNAL_SLOT_SERIES_COLORS[slotKey] || SIGNAL_SERIES_COLORS[0];
}

function getVisibleSignalSlots() {
    return SIGNAL_TYPE_TOGGLE_SPECS.filter((spec) => {
        return Boolean(signalTypeToggleState[spec.key]) && String(signalSlotBindings[spec.key] || "").trim();
    });
}

function getBoundSignalSlotFactorNames() {
    return new Set(
        SIGNAL_TYPE_TOGGLE_SPECS
            .map((spec) => String(signalSlotBindings[spec.key] || "").trim())
            .filter(Boolean)
    );
}

function getAdHocActiveFactorNames() {
    const slotBound = getBoundSignalSlotFactorNames();
    return activeFactorNames.filter((name) => name && !slotBound.has(name));
}

/** 右侧列表 / 副图统一：槽位绑定因子看槽位开关，其余看 activeFactorNames */
function isFactorSnapshotActive(factorName) {
    const name = String(factorName || "").trim();
    if (!name) {
        return false;
    }
    const slotKey = getSlotKeyForBoundFactor(name);
    if (slotKey) {
        return Boolean(signalTypeToggleState[slotKey]);
    }
    return activeFactorNames.includes(name);
}

function getVisibleQuantFactorNames() {
    const names = [];
    const seen = new Set();
    for (const spec of getVisibleSignalSlots()) {
        const factor = String(signalSlotBindings[spec.key] || "").trim();
        if (factor && !seen.has(factor)) {
            seen.add(factor);
            names.push(factor);
        }
    }
    for (const factor of getAdHocActiveFactorNames()) {
        if (!seen.has(factor)) {
            seen.add(factor);
            names.push(factor);
        }
    }
    return names;
}

function purgeSlotBoundFromActiveFactorNames() {
    const slotBound = getBoundSignalSlotFactorNames();
    if (!slotBound.size) {
        return;
    }
    const removedPrimary = selectedFactorName && slotBound.has(selectedFactorName);
    activeFactorNames = activeFactorNames.filter((name) => !slotBound.has(name));
    if (removedPrimary) {
        selectedFactorName = activeFactorNames[0] || "";
        signalPoints = selectedFactorName ? getFactorPoints(selectedFactorName) : [];
        lastSignalTime = selectedFactorName ? getFactorLastSeenTime(selectedFactorName) : null;
        if (factorSelect) {
            factorSelect.value = selectedFactorName;
        }
        persistFactorState();
    }
}

function normalizeSeriesColorKey(colorText) {
    return String(colorText || "").trim().toLowerCase();
}

function getSlotKeyForBoundFactor(factorName) {
    const name = String(factorName || "").trim();
    if (!name) {
        return "";
    }
    for (const spec of SIGNAL_TYPE_TOGGLE_SPECS) {
        if (String(signalSlotBindings[spec.key] || "").trim() === name) {
            return spec.key;
        }
    }
    return "";
}

function getOccupiedSlotColorSet() {
    const used = new Set();
    for (const spec of SIGNAL_TYPE_TOGGLE_SPECS) {
        const factor = String(signalSlotBindings[spec.key] || "").trim();
        if (factor) {
            used.add(normalizeSeriesColorKey(getSignalSlotSeriesColor(spec.key)));
        }
    }
    return used;
}

function getAvailableAdHocSeriesColors() {
    const occupied = getOccupiedSlotColorSet();
    const available = AD_HOC_SIGNAL_SERIES_COLORS.filter(
        (color) => !occupied.has(normalizeSeriesColorKey(color))
    );
    return available.length ? available : AD_HOC_SIGNAL_SERIES_COLORS.slice();
}

function getAdHocFactorSeriesColor(factorName) {
    const adHocFactors = getAdHocActiveFactorNames();
    const idx = Math.max(0, adHocFactors.indexOf(factorName));
    const palette = getAvailableAdHocSeriesColors();
    return palette[idx % palette.length];
}

function getFactorDisplayColor(factorName) {
    const slotKey = getSlotKeyForBoundFactor(factorName);
    if (slotKey && isFactorSnapshotActive(factorName)) {
        return getSignalSlotSeriesColor(slotKey);
    }
    if (getAdHocActiveFactorNames().includes(factorName)) {
        return getAdHocFactorSeriesColor(factorName);
    }
    return "";
}

function buildFactorColorStyleAttr(color) {
    if (!color) {
        return "";
    }
    const glow = colorWithAlpha(color, 0.35);
    return " style=\"--factor-active-color:" + escapeHtml(color) + ";--factor-active-glow:" + escapeHtml(glow) + ";\"";
}

function getSlotSignalPoints(slotKey) {
    return slotSignalPointsByKey.get(String(slotKey || "")) || [];
}

function clearSlotSignalSeries(slotKey) {
    const series = slotSignalSeriesByKey.get(slotKey);
    if (series) {
        signalChart.removeSeries(series);
        slotSignalSeriesByKey.delete(slotKey);
    }
}

function ensureSlotSignalSeries(slotKey) {
    if (slotSignalSeriesByKey.has(slotKey)) {
        return slotSignalSeriesByKey.get(slotKey);
    }
    const series = signalChart.addSeries(LightweightCharts.LineSeries, {
        priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
        priceScaleId: "right",
        color: getSignalSlotSeriesColor(slotKey),
        lineWidth: 2,
        crosshairMarkerVisible: false
    });
    slotSignalSeriesByKey.set(slotKey, series);
    return series;
}

function getPrimaryQuantSignalPoints() {
    const visibleSlots = getVisibleSignalSlots();
    if (visibleSlots.length) {
        return getSlotSignalPoints(visibleSlots[0].key);
    }
    const adHoc = getAdHocActiveFactorNames();
    if (!adHoc.length) {
        return [];
    }
    const primary = adHoc[0];
    return primary === selectedFactorName
        ? signalPoints
        : (extraSignalPointsByFactor.get(primary) || []);
}

function renderQuantSignalData() {
    const visibleSlots = getVisibleSignalSlots();
    const visibleSlotKeys = new Set(visibleSlots.map((spec) => spec.key));
    for (const slotKey of Array.from(slotSignalSeriesByKey.keys())) {
        if (!visibleSlotKeys.has(slotKey)) {
            clearSlotSignalSeries(slotKey);
        }
    }

    const adHocFactors = getAdHocActiveFactorNames();
    const primaryAdHocFactor = adHocFactors[0] || "";
    const primaryPoints = primaryAdHocFactor ? getFactorPoints(primaryAdHocFactor) : [];
    signalSeries.setData(buildSignalSeriesData(primaryPoints));
    signalSeries.applyOptions({
        color: primaryAdHocFactor ? getAdHocFactorSeriesColor(primaryAdHocFactor) : "#3b82f6",
        lineWidth: 2,
        crosshairMarkerVisible: Boolean(primaryAdHocFactor)
    });

    const visibleAdHoc = new Set(adHocFactors.slice(1));
    for (const factorName of Array.from(extraSignalSeriesByFactor.keys())) {
        if (!visibleAdHoc.has(factorName)) {
            clearExtraSignalSeries(factorName);
        }
    }
    for (const factorName of adHocFactors.slice(1)) {
        const series = ensureExtraSignalSeries(factorName);
        series.applyOptions({
            color: getAdHocFactorSeriesColor(factorName),
            lineWidth: 2,
            crosshairMarkerVisible: false
        });
        series.setData(buildSignalSeriesData(getFactorPoints(factorName)));
    }

    for (const spec of visibleSlots) {
        const series = ensureSlotSignalSeries(spec.key);
        series.setData(buildSignalSeriesData(getSlotSignalPoints(spec.key)));
    }

    updateCoupledSignalOverlay();
    signalChart.priceScale("right").applyOptions({ autoScale: true });
    syncSignalChartViewportFromMain();
}

async function refreshSingleSlotFactorData(slotKey, isInitialLoad = false) {
    const key = String(slotKey || "").trim();
    const factor = String(signalSlotBindings[key] || "").trim();
    if (!key || !factor || currentInterval !== "1day" || isYkrsCode()) {
        slotSignalPointsByKey.delete(key);
        slotLastSignalTimeByKey.delete(key);
        return;
    }
    const missingKey = buildMissingFactorKey(currentCode, factor, currentInterval);
    if (missingFactorKeys.has(missingKey)) {
        slotSignalPointsByKey.delete(key);
        slotLastSignalTimeByKey.delete(key);
        return;
    }
    const { fromTs: rangeFromTs, toTs: rangeToTs } = computeSignalRangeFromBars();
    const lastSeen = slotLastSignalTimeByKey.get(key) ?? null;
    const fromTs = (!isInitialLoad && lastSeen !== null) ? Number(lastSeen) : rangeFromTs;
    try {
        const payload = await fetchFactorSignals(
            currentCode,
            factor,
            fromTs,
            rangeToTs,
            isInitialLoad ? null : lastSeen,
            isInitialLoad ? computeSignalInitialLimit() : FACTOR_FETCH_LIMIT_INCREMENTAL
        );
        const isNoFactor = Boolean(payload && payload.meta && payload.meta.no_factor === true);
        if (isNoFactor) {
            missingFactorKeys.add(missingKey);
            slotSignalPointsByKey.delete(key);
            slotLastSignalTimeByKey.delete(key);
            return;
        }
        const incoming = Array.isArray(payload.signals) ? payload.signals : [];
        const existing = isInitialLoad ? [] : getSlotSignalPoints(key);
        const merged = mergeFactorPoints(existing, incoming);
        const mergedLastTime = merged.length > 0 ? Number(merged[merged.length - 1].time) : null;
        slotSignalPointsByKey.set(key, merged);
        slotLastSignalTimeByKey.set(key, mergedLastTime);
    } catch {
        slotSignalPointsByKey.delete(key);
        slotLastSignalTimeByKey.delete(key);
    }
}

async function refreshSlotBoundSignalData(isInitialLoad = false) {
    const boundKeys = SIGNAL_TYPE_TOGGLE_SPECS
        .map((spec) => spec.key)
        .filter((key) => String(signalSlotBindings[key] || "").trim());
    if (!boundKeys.length || currentInterval !== "1day" || isYkrsCode()) {
        renderSignalData();
        updateSignalCaptionTitle();
        return;
    }
    await Promise.all(boundKeys.map((key) => refreshSingleSlotFactorData(key, isInitialLoad)));
    renderSignalData();
    updateSignalCaptionTitle();
}

async function bindFactorToSignalSlot(slotKey, factorName) {
    const key = String(slotKey || "").trim();
    const factor = String(factorName || "").trim();
    if (!key || !factor || !(key in signalSlotBindings)) {
        return;
    }
    for (const spec of SIGNAL_TYPE_TOGGLE_SPECS) {
        if (spec.key !== key && String(signalSlotBindings[spec.key] || "").trim() === factor) {
            signalSlotBindings[spec.key] = "";
            slotSignalPointsByKey.delete(spec.key);
            slotLastSignalTimeByKey.delete(spec.key);
            clearSlotSignalSeries(spec.key);
        }
    }
    signalSlotBindings[key] = factor;
    saveSignalSlotBindings();
    slotSignalPointsByKey.delete(key);
    slotLastSignalTimeByKey.delete(key);
    if (activeFactorNames.includes(factor)) {
        activeFactorNames = activeFactorNames.filter((name) => name !== factor);
        extraSignalPointsByFactor.delete(factor);
        extraLastSignalTimeByFactor.delete(factor);
        clearExtraSignalSeries(factor);
        if (selectedFactorName === factor) {
            selectedFactorName = activeFactorNames[0] || "";
            signalPoints = selectedFactorName ? getFactorPoints(selectedFactorName) : [];
            lastSignalTime = selectedFactorName ? getFactorLastSeenTime(selectedFactorName) : null;
            if (factorSelect) {
                factorSelect.value = selectedFactorName;
            }
            persistFactorState();
        }
    }
    signalTypeToggleState[key] = true;
    applySignalTypeToggleUi();
    applySignalSlotBindingUi();
    if (currentInterval === "1day" && !isYkrsCode() && barsCache.length > 0) {
        await refreshSingleSlotFactorData(key, true);
    }
    renderSignalData();
    updateSignalCaptionTitle();
    setFactorHint("status updated");
    if (currentRightTabName === "量化因子") {
        scheduleFactorSnapshotForRightPanel(
            Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
            true
        );
    }
    applySignalSlotBindingUi();
    applySignalTypeToggleUi();
}

function findSignalSlotAtPoint(clientX, clientY) {
    const elements = typeof document.elementsFromPoint === "function"
        ? document.elementsFromPoint(clientX, clientY)
        : [document.elementFromPoint(clientX, clientY)];
    for (const el of elements) {
        if (el instanceof Element) {
            const slotBtn = el.closest(".signal-type-toggle[data-signal-type]");
            if (slotBtn) {
                return slotBtn;
            }
        }
    }
    if (signalTypeTogglesWrap) {
        const slotButtons = signalTypeTogglesWrap.querySelectorAll(".signal-type-toggle[data-signal-type]");
        for (const slotBtn of slotButtons) {
            const rect = slotBtn.getBoundingClientRect();
            if (
                clientX >= rect.left &&
                clientX <= rect.right &&
                clientY >= rect.top &&
                clientY <= rect.bottom
            ) {
                return slotBtn;
            }
        }
    }
    return null;
}

function clearSignalSlotDropTargets() {
    document.querySelectorAll(".signal-type-toggle.drop-target").forEach((el) => {
        el.classList.remove("drop-target");
    });
}

loadSignalSlotBindings();

function getFactorSnapshotPanelElements() {
    return {
        headExtraEl: document.getElementById("factor-snapshot-head-extra"),
        listEl: document.getElementById("factor-snapshot-list")
    };
}

let factorSnapshotListClickBound = false;
function bindFactorSnapshotListInteractions() {
    const { listEl } = getFactorSnapshotPanelElements();
    if (!listEl || factorSnapshotListClickBound) {
        return;
    }
    factorSnapshotListClickBound = true;
    listEl.addEventListener("click", async (event) => {
        if (!(event.target instanceof Element)) {
            return;
        }
        if (Date.now() < suppressFactorSnapshotClickUntil) {
            return;
        }
        const toggleBtn = event.target.closest(".factor-group-toggle");
        if (toggleBtn) {
            event.preventDefault();
            event.stopPropagation();
            const groupId = String(toggleBtn.getAttribute("data-group-id") || "").trim();
            if (!groupId) {
                return;
            }
            if (expandedFactorGroupIds.has(groupId)) {
                expandedFactorGroupIds.delete(groupId);
            } else {
                expandedFactorGroupIds.add(groupId);
            }
            persistExpandedFactorGroups();
            scheduleFactorSnapshotForRightPanel(
                Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
                true
            );
            return;
        }
        const itemEl = event.target.closest(".factor-snapshot-item[data-factor-name]");
        if (!itemEl) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        const factorName = String(itemEl.getAttribute("data-factor-name") || "").trim();
        if (!factorName) {
            return;
        }
        if (event.metaKey || event.ctrlKey || isFactorSnapshotActive(factorName)) {
            await toggleFactorActiveState(factorName);
            return;
        }
        await selectFactorAndRefresh(factorName);
    });
}

function renderFactorSnapshotStatus(text) {
    const { headExtraEl, listEl } = getFactorSnapshotPanelElements();
    if (!headExtraEl || !listEl) {
        return;
    }
    headExtraEl.textContent = text;

    // 只有当明确知道当前时间点无数据或获取失败时，才清空列表，避免“正在加载...”状态下右侧面板闪烁跳动。
    if (text.includes("no factor") || text.includes("failed")) {
        currentFactorSnapshotPayload = null;
        listEl.innerHTML = "";
        updateExportFactorOptions();
    }
}

function formatFactorSnapshotValue(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
        return "0";
    }
    return n.toFixed(4);
}

function factorItemFilterText(name) {
    const raw = String(name ?? "").trim();
    const disp = String(getDisplayLabelForFactorColumn(raw) || raw).trim();
    return (raw + " " + disp).toLowerCase();
}

function buildCatalogGroupSearchBlob(group, summaryDisplay, summaryCol, childNames) {
    const parts = [
        String(group && group.group_id != null ? group.group_id : ""),
        String(group && group.group_name != null ? group.group_name : ""),
        String(summaryDisplay || ""),
        String(summaryCol || ""),
    ];
    const names = Array.isArray(childNames) ? childNames : [];
    for (const nm of names) {
        const key = String(nm ?? "").trim();
        if (!key) {
            continue;
        }
        parts.push(key);
        parts.push(String(getDisplayLabelForFactorColumn(key) || key).trim());
    }
    return parts.filter(Boolean).join(" ").toLowerCase();
}

function closeFactorSnapshotFilterPopover() {
    const pop = document.getElementById("factor-snapshot-filter-popover");
    const btn = document.getElementById("factor-snapshot-filter-btn");
    if (!pop) {
        return;
    }
    pop.hidden = true;
    pop.classList.remove("is-fixed-open");
    pop.style.top = "";
    pop.style.left = "";
    btn?.classList.remove("active");
}

function positionFactorSnapshotFilterPopover() {
    const btn = document.getElementById("factor-snapshot-filter-btn");
    const pop = document.getElementById("factor-snapshot-filter-popover");
    if (!btn || !pop || pop.hidden) {
        return;
    }
    const rect = btn.getBoundingClientRect();
    pop.classList.add("is-fixed-open");
    pop.style.left = (rect.left + rect.width / 2) + "px";
    pop.style.top = Math.max(4, rect.top - 4) + "px";
}

let factorSnapshotFilterPopoverListenersBound = false;
function bindFactorSnapshotFilterPopoverListeners() {
    if (factorSnapshotFilterPopoverListenersBound) {
        return;
    }
    factorSnapshotFilterPopoverListenersBound = true;
    window.addEventListener("resize", () => positionFactorSnapshotFilterPopover());
    window.addEventListener("scroll", () => positionFactorSnapshotFilterPopover(), true);
}

function setFactorSnapshotFilterUiVisible(visible) {
    const tools = document.getElementById("factor-snapshot-tools");
    if (!tools) {
        return;
    }
    tools.style.display = visible ? "" : "none";
    if (!visible) {
        const input = document.getElementById("factor-snapshot-filter-input");
        closeFactorSnapshotFilterPopover();
        if (input) {
            input.value = "";
        }
        applyFactorSnapshotFilter();
    }
}

function applyFactorSnapshotFilter() {
    const listEl = document.getElementById("factor-snapshot-list");
    if (!listEl) {
        return;
    }
    const q = getFactorSnapshotFilterQuery();
    const pinned = listEl.querySelector(".factor-pinned-wrap");
    if (pinned) {
        pinned.classList.remove("factor-filter-hidden");
        pinned.querySelectorAll(".factor-snapshot-item").forEach((el) => {
            const blob = String(el.getAttribute("data-factor-filter-text") || "").toLowerCase();
            const name = String(el.getAttribute("data-factor-name") || "").toLowerCase();
            const hit = !q || blob.includes(q) || name.includes(q);
            el.classList.toggle("factor-filter-hidden", !hit);
        });
        const anyVisible =
            !q ||
            Array.from(pinned.querySelectorAll(".factor-snapshot-item")).some((row) => !row.classList.contains("factor-filter-hidden"));
        pinned.classList.toggle("factor-filter-hidden", !anyVisible);
    }
    listEl.querySelectorAll(".factor-group-block").forEach((block) => {
        const blob = String(block.getAttribute("data-group-filter-text") || "").toLowerCase();
        const hit = !q || blob.includes(q);
        block.classList.toggle("factor-filter-hidden", !hit);
    });
}

let factorSnapshotFilterOutsideBound = false;
function installFactorSnapshotFilterUi() {
    const tools = document.getElementById("factor-snapshot-tools");
    const wrap = document.getElementById("factor-snapshot-filter-wrap");
    const btn = document.getElementById("factor-snapshot-filter-btn");
    const pop = document.getElementById("factor-snapshot-filter-popover");
    const input = document.getElementById("factor-snapshot-filter-input");
    if (!tools || !wrap || !btn || !pop || !input) {
        return;
    }
    bindFactorSnapshotListInteractions();
    if (tools.dataset.filterUiBound === "1") {
        return;
    }
    tools.dataset.filterUiBound = "1";
    bindFactorSnapshotFilterPopoverListeners();
    btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const open = pop.hidden;
        pop.hidden = !open;
        btn.classList.toggle("active", open);
        if (open) {
            positionFactorSnapshotFilterPopover();
            requestAnimationFrame(() => input.focus());
        } else {
            closeFactorSnapshotFilterPopover();
        }
    });
    input.addEventListener("input", () => {
        applyFactorSnapshotFilter();
        if (currentRightTabName === "量化因子") {
            scheduleFactorSnapshotForRightPanel(
                Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
                true
            );
        }
    });
    input.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeFactorSnapshotFilterPopover();
        }
    });
    if (!factorSnapshotFilterOutsideBound) {
        factorSnapshotFilterOutsideBound = true;
        document.addEventListener("mousedown", (e) => {
            const tools = document.getElementById("factor-snapshot-tools");
            const p = document.getElementById("factor-snapshot-filter-popover");
            if (!tools || !p || p.hidden) {
                return;
            }
            if (e.target instanceof Node && tools.contains(e.target)) {
                return;
            }
            closeFactorSnapshotFilterPopover();
        });
    }
}

function renderFactorNameWithBar(name, value, maxAbs) {
    const safeName = escapeHtml(name);
    const n = Number(value);
    if (!Number.isFinite(n)) {
        return "<span class=\"factor-snapshot-name\"><span class=\"factor-snapshot-name-text\">" + safeName + "</span></span>";
    }
    const width = "50";
    let fill = "";
    if (n > 0) {
        fill = "<span class=\"factor-snapshot-name-fill pos\" style=\"width:" + width + "%;\"></span>";
    } else if (n < 0) {
        fill = "<span class=\"factor-snapshot-name-fill neg\" style=\"width:" + width + "%;\"></span>";
    }
    return (
        "<span class=\"factor-snapshot-name\">" +
        fill +
        "<span class=\"factor-snapshot-name-text\">" + safeName + "</span>" +
        "</span>"
    );
}

function getFactorSnapshotFilterQuery() {
    const input = document.getElementById("factor-snapshot-filter-input");
    return input ? String(input.value || "").trim().toLowerCase() : "";
}

function getSnapshotRequestMode() {
    return getSnapshotRequestedGroupIds().length > 0 ? "union" : "core";
}

function normalizeSnapshotGroupId(groupId) {
    const normalized = String(groupId || "").trim();
    if (!normalized) {
        return "";
    }
    if (normalized === "__ungrouped__") {
        return "ungrouped";
    }
    return normalized;
}

function getExpandedSnapshotGroupIds() {
    const validGroupIds = new Set(
        Array.isArray(factorGroups)
            ? factorGroups
                .map((group) => normalizeSnapshotGroupId(group && group.group_id))
                .filter(Boolean)
            : []
    );
    return Array.from(
        new Set(
            Array.from(expandedFactorGroupIds)
                .map((groupId) => normalizeSnapshotGroupId(groupId))
                .filter((groupId) => groupId && validGroupIds.has(groupId))
        )
    )
        .sort();
}

function getSearchMatchedSnapshotGroupIds() {
    const q = getFactorSnapshotFilterQuery();
    if (!q) {
        return [];
    }
    const matched = [];
    for (const group of Array.isArray(factorGroups) ? factorGroups : []) {
        const groupId = normalizeSnapshotGroupId(group && group.group_id);
        if (!groupId) {
            continue;
        }
        const childNames = Array.isArray(group && group.children) ? group.children : [];
        const summaryCol = Array.isArray(group && group.core_factors) && group.core_factors.length
            ? String(group.core_factors[0] || "").trim()
            : (childNames.length ? String(childNames[0] || "").trim() : "");
        const summaryDisplay = getCatalogGroupFactorDisplayLabel(group, summaryCol) || summaryCol;
        const blob = buildCatalogGroupSearchBlob(group, summaryDisplay, summaryCol, childNames);
        if (blob.includes(q)) {
            matched.push(groupId);
        }
    }
    return Array.from(new Set(matched)).sort();
}

function getSnapshotRequestedGroupIds() {
    const expanded = getExpandedSnapshotGroupIds();
    const matched = getSearchMatchedSnapshotGroupIds();
    if (!matched.length) {
        return expanded;
    }
    return Array.from(new Set([...expanded, ...matched])).sort();
}

function getSnapshotRequestSignature() {
    const mode = getSnapshotRequestMode();
    const groupIds = mode === "union" ? getSnapshotRequestedGroupIds() : [];
    return {
        mode,
        groupIds,
        cacheToken: groupIds.length ? (mode + ":" + groupIds.join(",")) : mode,
    };
}

function sortFactorNamesByCustomOrder(groupId, names) {
    const source = Array.isArray(names) ? names : [];
    const gid = String(groupId || "").trim();
    const custom = factorOrderByGroup && typeof factorOrderByGroup === "object"
        ? factorOrderByGroup[gid]
        : null;
    if (!Array.isArray(custom) || !custom.length || !source.length) {
        return [...source];
    }
    const rankMap = new Map();
    custom.forEach((name, idx) => {
        const key = String(name || "").trim();
        if (key && !rankMap.has(key)) {
            rankMap.set(key, idx);
        }
    });
    return source
        .map((name, idx) => ({ name, idx, rank: rankMap.has(name) ? rankMap.get(name) : Number.MAX_SAFE_INTEGER }))
        .sort((a, b) => {
            if (a.rank !== b.rank) {
                return a.rank - b.rank;
            }
            return a.idx - b.idx;
        })
        .map((item) => item.name);
}

function sortGroupsByCustomOrder(groups) {
    const source = Array.isArray(groups) ? groups : [];
    if (!Array.isArray(factorGroupOrder) || !factorGroupOrder.length || !source.length) {
        return [...source];
    }
    const rankMap = new Map();
    factorGroupOrder.forEach((groupId, idx) => {
        const key = String(groupId || "").trim();
        if (key && !rankMap.has(key)) {
            rankMap.set(key, idx);
        }
    });
    return source
        .map((group, idx) => {
            const groupId = String(group && group.group_id ? group.group_id : "").trim();
            return { group, idx, rank: rankMap.has(groupId) ? rankMap.get(groupId) : Number.MAX_SAFE_INTEGER };
        })
        .sort((a, b) => {
            if (a.rank !== b.rank) {
                return a.rank - b.rank;
            }
            return a.idx - b.idx;
        })
        .map((item) => item.group);
}

function buildCatalogSnapshotGroups(valueByName) {
    const catalogGroups = [];
    const usedNames = new Set();
    if (Array.isArray(factorGroups) && factorGroups.length > 0) {
        for (const group of factorGroups) {
            const groupId = String(group && group.group_id ? group.group_id : "").trim();
            if (!groupId) {
                continue;
            }
            const children = Array.isArray(group.children) ? group.children : [];
            const filteredChildren = [];
            for (const name of children) {
                const factorName = String(name || "").trim();
                if (!factorName || !valueByName.has(factorName) || filteredChildren.includes(factorName)) {
                    continue;
                }
                filteredChildren.push(factorName);
                usedNames.add(factorName);
            }
            if (!filteredChildren.length) {
                continue;
            }
            const coreFactorsRaw = Array.isArray(group.core_factors) ? group.core_factors : [];
            const coreLabelsRaw = Array.isArray(group.core_factor_labels) ? group.core_factor_labels : [];
            const coreFactors = [];
            const coreFactorLabels = [];
            for (let i = 0; i < coreFactorsRaw.length; i += 1) {
                const cf = String(coreFactorsRaw[i] || "").trim();
                if (!cf || !valueByName.has(cf) || coreFactors.includes(cf)) {
                    continue;
                }
                coreFactors.push(cf);
                const lb = i < coreLabelsRaw.length ? String(coreLabelsRaw[i] || "").trim() : "";
                coreFactorLabels.push(lb || cf);
            }
            catalogGroups.push({
                group_id: groupId,
                group_name: String(group.group_name || groupId),
                core_factors: coreFactors,
                core_factor_labels: coreFactorLabels,
                children: filteredChildren
            });
        }
    }

    const ungrouped = [];
    for (const name of valueByName.keys()) {
        if (!usedNames.has(name)) {
            ungrouped.push(name);
        }
    }
    ungrouped.sort((a, b) => String(a).localeCompare(String(b)));
    const displayGroups = [...catalogGroups];
    if (ungrouped.length) {
        displayGroups.push({
            group_id: "__ungrouped__",
            group_name: "未分组",
            core_factors: [],
            core_factor_labels: [],
            children: ungrouped
        });
    }
    return displayGroups;
}

function renderFactorItemHtml(name, value, maxAbs) {
    const displayName = getDisplayLabelForFactorColumn(name) || name;
    const filterAttr = escapeHtml(factorItemFilterText(name));
    const slotKey = getSlotKeyForBoundFactor(name);
    const isActive = isFactorSnapshotActive(name);
    const itemClasses = [
        "factor-snapshot-item",
        slotKey ? "factor-slot-bound" : "",
        isActive ? "active" : "",
    ].filter(Boolean).join(" ");
    return (
        "<div class=\"" + itemClasses + "\" data-factor-name=\"" + escapeHtml(name) + "\" data-factor-filter-text=\"" + filterAttr + "\"" + buildFactorColorStyleAttr(getFactorDisplayColor(name)) + ">" +
        renderFactorNameWithBar(displayName, value, maxAbs) +
        "<span class=\"factor-snapshot-value\">" + formatFactorSnapshotValue(value) + "</span>" +
        "</div>"
    );
}

function getFactorActiveStyleAttr(factorName) {
    return buildFactorColorStyleAttr(getFactorDisplayColor(factorName));
}

/** 分组标题：优先用目录 JSON 的 core_factor_labels，否则用 core_factors 列名，再回退 group_name。 */
function getFactorGroupDisplayTitle(group) {
    const labels = Array.isArray(group.core_factor_labels)
        ? group.core_factor_labels.map((x) => String(x || "").trim()).filter(Boolean)
        : [];
    if (labels.length) {
        return labels.join(" / ");
    }
    const cores = Array.isArray(group.core_factors)
        ? group.core_factors.map((x) => String(x || "").trim()).filter(Boolean)
        : [];
    if (cores.length) {
        return cores.join(" / ");
    }
    const name = String(group.group_name || "").trim();
    if (name) {
        return name;
    }
    return String(group.group_id || "").trim() || "--";
}

function getDisplayLabelForFactorColumn(col) {
    const c = String(col || "").trim();
    if (!c) {
        return "";
    }
    if (factorLabelMap && typeof factorLabelMap === "object") {
        const mapped = String(factorLabelMap[c] || "").trim();
        if (mapped) {
            return mapped;
        }
    }
    const idx = factorCoreNames.indexOf(c);
    if (idx >= 0 && factorCoreLabels[idx]) {
        const lb = String(factorCoreLabels[idx]).trim();
        if (lb) {
            return lb;
        }
    }
    return c;
}

function getUngroupedPrimaryColumn(ungroupedList) {
    if (!Array.isArray(ungroupedList) || !ungroupedList.length) {
        return "";
    }
    for (const col of factorCoreNames) {
        if (ungroupedList.includes(col)) {
            return col;
        }
    }
    return String(ungroupedList[0] || "").trim();
}

function getCatalogGroupSummaryColumn(group, valueByName) {
    const coreList = Array.isArray(group.core_factors) ? group.core_factors : [];
    const coreChildren = coreList.filter((name) => valueByName.has(name));
    if (coreChildren.length) {
        return coreChildren[0];
    }
    const ch = Array.isArray(group.children) ? group.children : [];
    for (const name of ch) {
        const n = String(name || "").trim();
        if (n && valueByName.has(n)) {
            return n;
        }
    }
    return ch.length ? String(ch[0] || "").trim() : "";
}

function getCatalogGroupFactorDisplayLabel(group, col) {
    const c = String(col || "").trim();
    if (!c) {
        return "";
    }
    const cfs = Array.isArray(group.core_factors) ? group.core_factors : [];
    const labels = Array.isArray(group.core_factor_labels) ? group.core_factor_labels : [];
    const idx = cfs.indexOf(c);
    if (idx >= 0 && labels[idx]) {
        const lb = String(labels[idx]).trim();
        if (lb) {
            return lb;
        }
    }
    return getDisplayLabelForFactorColumn(c);
}

function buildExportSummaryFactorOptions(snapshotPayload) {
    const snapshot = snapshotPayload && typeof snapshotPayload === "object" ? snapshotPayload : null;
    if (!snapshot || !snapshot.factors || typeof snapshot.factors !== "object") {
        return [];
    }
    const entries = Object.entries(snapshot.factors);
    if (!entries.length) {
        return [];
    }
    const valueByName = new Map(entries.map(([name, value]) => [String(name), value]));
    const displayGroups = buildCatalogSnapshotGroups(valueByName);
    const options = [];
    for (const group of displayGroups) {
        const groupId = String(group.group_id || "").trim();
        let summaryCol = "";
        let summaryLabel = "";
        if (groupId === "__ungrouped__" || groupId === "ungrouped") {
            summaryCol = getUngroupedPrimaryColumn(group.children);
            summaryLabel = String(group.group_name || "未分组").trim() || "未分组";
        } else {
            summaryCol = getCatalogGroupSummaryColumn(group, valueByName);
            summaryLabel = getCatalogGroupFactorDisplayLabel(group, summaryCol) || summaryCol;
        }
        summaryCol = String(summaryCol || "").trim();
        if (!summaryCol || options.some((item) => item.value === summaryCol)) {
            continue;
        }
        options.push({
            value: summaryCol,
            label: summaryLabel === summaryCol ? summaryLabel : (summaryLabel + " (" + summaryCol + ")"),
        });
    }
    return options;
}

function updateExportFactorOptions() {
    if (!exportFactorSelect || !exportFactorSummary || !exportSymbolsBtn) {
        return;
    }
    const options = buildExportSummaryFactorOptions(currentFactorSnapshotPayload);
    const previous = String(exportFactorSelect.value || "").trim();
    exportFactorSelect.innerHTML = options
        .map((item) => "<option value=\"" + escapeHtml(item.value) + "\">" + escapeHtml(item.label) + "</option>")
        .join("");
    if (options.length) {
        const nextValue = options.some((item) => item.value === previous) ? previous : options[0].value;
        exportFactorSelect.value = nextValue;
        const selectedText = options.find((item) => item.value === nextValue)?.label || nextValue;
        exportFactorSummary.textContent = "Selected: " + selectedText;
    } else {
        exportFactorSummary.textContent = "No available primary factor";
    }
    exportSymbolsBtn.disabled = !(options.length && currentInterval === "1day");
}

function renderFactorSnapshotToRightPanel(snapshot, targetTs) {
    const { headExtraEl, listEl } = getFactorSnapshotPanelElements();
    if (!headExtraEl || !listEl) {
        return;
    }
    const showTs = Number.isFinite(Number(targetTs)) ? Number(targetTs) : Number(snapshot && snapshot.time);
    currentFactorSnapshotTime = Number.isFinite(showTs) ? showTs : null;
    currentFactorSnapshotPayload = snapshot && typeof snapshot === "object" ? snapshot : null;
    lastRenderedSnapshotKey = currentCode + "|" + (Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : "na") + "|factor|" + getSnapshotRequestSignature().cacheToken;

    const factorsObj = snapshot && snapshot.factors && typeof snapshot.factors === "object" ? snapshot.factors : {};
    const entries = Object.entries(factorsObj);
    entries.sort((a, b) => String(a[0]).localeCompare(String(b[0])));
    let maxAbs = 0;
    for (const [, value] of entries) {
        const n = Math.abs(Number(value));
        if (Number.isFinite(n) && n > maxAbs) {
            maxAbs = n;
        }
    }

    if (!entries.length) {
        headExtraEl.textContent = "0";
        listEl.innerHTML = "";
        setFactorSnapshotFilterUiVisible(true);
        applyFactorSnapshotFilter();
        updateExportFactorOptions();
        return;
    }

    const valueByName = new Map(entries.map(([name, value]) => [String(name), value]));
    const filterQuery = getFactorSnapshotFilterQuery();
    const displayGroups = sortGroupsByCustomOrder(buildCatalogSnapshotGroups(valueByName)).filter((group) => {
        if (!filterQuery) {
            return true;
        }
        const isUngrouped = group.group_id === "__ungrouped__" || group.group_id === "ungrouped";
        const summaryCol = String(
            isUngrouped
                ? getUngroupedPrimaryColumn(group.children)
                : getCatalogGroupSummaryColumn(group, valueByName)
        ).trim();
        const summaryDisplay = isUngrouped
            ? (String(group.group_name || "Ungrouped").trim() || "Ungrouped")
            : String(getCatalogGroupFactorDisplayLabel(group, summaryCol) || summaryCol).trim();
        return buildCatalogGroupSearchBlob(group, summaryDisplay, summaryCol, group.children || []).includes(filterQuery);
    });
    headExtraEl.textContent = String(entries.length);

    const htmlParts = [];
    const pinnedFactors = activeFactorNames
        .filter((name, idx, arr) => arr.indexOf(name) === idx)
        .filter((name) => valueByName.has(name));
    if (pinnedFactors.length) {
        const pinnedItemsHtml = pinnedFactors
            .map((name) => (
                "<div class=\"factor-snapshot-item pinned-copy active\" data-factor-name=\"" + escapeHtml(name) + "\" data-factor-filter-text=\"" + escapeHtml(factorItemFilterText(name)) + "\"" + getFactorActiveStyleAttr(name) + ">" +
                renderFactorNameWithBar(getDisplayLabelForFactorColumn(name) || name, valueByName.get(name), maxAbs) +
                "<span class=\"factor-snapshot-value\">" + formatFactorSnapshotValue(valueByName.get(name)) + "</span>" +
                "</div>"
            ))
            .join("");
        htmlParts.push(
            "<div class=\"factor-pinned-wrap\">" +
            "<div class=\"factor-pinned-title\">已选因子</div>" +
            pinnedItemsHtml +
            "</div>"
        );
    }

    for (const group of displayGroups) {
        const groupId = String(group.group_id || "").trim();
        const expanded = Boolean(filterQuery) || expandedFactorGroupIds.has(groupId);
        const isUngrouped = groupId === "__ungrouped__" || groupId === "ungrouped";
        const summaryCol = isUngrouped
            ? getUngroupedPrimaryColumn(group.children)
            : getCatalogGroupSummaryColumn(group, valueByName);
        const summaryDisplay = isUngrouped
            ? (String(group.group_name || "Ungrouped").trim() || "Ungrouped")
            : (getCatalogGroupFactorDisplayLabel(group, summaryCol) || summaryCol);
        const summaryVal = valueByName.get(summaryCol);
        const summaryActive = isFactorSnapshotActive(summaryCol) ? " active" : "";
        const toggleBtn = (
            "<button type=\"button\" class=\"factor-group-toggle\" data-group-id=\"" + escapeHtml(groupId) + "\">" +
            (expanded ? "收起" : "展开") +
            "</button>"
        );
        const childNames = isUngrouped ? group.children : group.children.filter((c) => c !== summaryCol);
        const expandedCols = expanded
            ? sortFactorNamesByCustomOrder(groupId, childNames).filter((name) => {
                if (!filterQuery) {
                    return true;
                }
                return factorItemFilterText(name).includes(filterQuery);
            })
            : [];
        const itemsHtml = expandedCols
            .map((name) => renderFactorItemHtml(name, valueByName.get(name), maxAbs))
            .join("");
        const groupBlob = escapeHtml(buildCatalogGroupSearchBlob(group, summaryDisplay, summaryCol, group.children || []));
        htmlParts.push(
            "<div class=\"factor-group-block\" data-factor-group=\"" + escapeHtml(groupId) + "\" data-group-filter-text=\"" + groupBlob + "\">" +
            "<div class=\"factor-group-header\">" +
            "<div class=\"factor-group-head-main\">" +
            "<div class=\"factor-group-summary-wrap\">" +
            "<div class=\"factor-group-summary-row factor-snapshot-item factor-snapshot-item--header-summary" + summaryActive + "\" data-factor-name=\"" + escapeHtml(summaryCol) + "\"" + getFactorActiveStyleAttr(summaryCol) + ">" +
            renderFactorNameWithBar(summaryDisplay, summaryVal, maxAbs) +
            "<span class=\"factor-snapshot-value\">" + formatFactorSnapshotValue(summaryVal) + "</span>" +
            "</div>" +
            "</div>" +
            "</div>" +
            toggleBtn +
            "</div>" +
            (itemsHtml ? ("<div class=\"factor-group-items\">" + itemsHtml + "</div>") : "") +
            "</div>"
        );
    }
    listEl.innerHTML = htmlParts.join("");
    setFactorSnapshotFilterUiVisible(true);
    applyFactorSnapshotFilter();
    updateExportFactorOptions();
}

async function refreshSingleFactorData(factorName, isInitialLoad = false) {
    const factor = String(factorName || "").trim();
    if (!factor || currentInterval !== "1day" || isYkrsCode()) {
        return;
    }
    const missingKey = buildMissingFactorKey(currentCode, factor, currentInterval);
    if (missingFactorKeys.has(missingKey)) {
        return;
    }
    const { fromTs: rangeFromTs, toTs: rangeToTs } = computeSignalRangeFromBars();
    const lastSeen = getFactorLastSeenTime(factor);
    const fromTs = (!isInitialLoad && lastSeen !== null) ? Number(lastSeen) : rangeFromTs;
    try {
        const payload = await fetchFactorSignals(
            currentCode,
            factor,
            fromTs,
            rangeToTs,
            isInitialLoad ? null : lastSeen,
            isInitialLoad ? computeSignalInitialLimit() : FACTOR_FETCH_LIMIT_INCREMENTAL
        );
        const isNoFactor = Boolean(payload && payload.meta && payload.meta.no_factor === true);
        if (isNoFactor) {
            missingFactorKeys.add(missingKey);
            return;
        }
        const incoming = Array.isArray(payload.signals) ? payload.signals : [];
        const existing = isInitialLoad ? [] : getFactorPoints(factor);
        const merged = mergeFactorPoints(existing, incoming);
        const mergedLastTime = merged.length > 0 ? Number(merged[merged.length - 1].time) : null;
        if (factor === selectedFactorName) {
            signalPoints = merged;
            lastSignalTime = mergedLastTime;
        } else {
            extraSignalPointsByFactor.set(factor, merged);
            extraLastSignalTimeByFactor.set(factor, mergedLastTime);
        }
    } catch (err) {
        if (factor === selectedFactorName) {
            signalPoints = [];
            lastSignalTime = null;
        } else {
            extraSignalPointsByFactor.delete(factor);
            extraLastSignalTimeByFactor.delete(factor);
        }
    }
}
async function selectFactorAndRefresh(nextFactorName) {
    const factorName = String(nextFactorName || "").trim();
    if (!factorName) {
        return;
    }
    if (factorNames.length > 0 && !factorNames.includes(factorName)) {
        return;
    }
    const slotKey = getSlotKeyForBoundFactor(factorName);
    if (slotKey) {
        await setSignalSlotToggle(slotKey, true);
        countdownValue = AUTO_REFRESH_SECONDS;
        return;
    }
    if (!activeFactorNames.includes(factorName)) {
        activeFactorNames.push(factorName);
    }
    promoteFactorToPrimary(factorName);
    // 鍏堝悓姝ュ埛鏂板彸渚у洜瀛愬垪琛ㄩ珮浜紝閬垮厤绛?refreshSignalData 缃戠粶杩斿洖鍚庢墠鍑虹幇 .active
    if (
        currentRightTabName === "量化因子" &&
        currentFactorSnapshotPayload &&
        !shouldUseBacktestPositionSnapshotPanel()
    ) {
        renderFactorSnapshotToRightPanel(
            currentFactorSnapshotPayload,
            Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime
        );
    }
    const needsInitialLoad = getFactorPoints(factorName).length === 0;
    await refreshSignalData(needsInitialLoad);
    if (currentRightTabName === "量化因子") {
        scheduleFactorSnapshotForRightPanel(
            Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
            true
        );
    }
    countdownValue = AUTO_REFRESH_SECONDS;
}

async function toggleFactorActiveState(factorName) {
    const target = String(factorName || "").trim();
    if (!target) {
        return;
    }
    const slotKey = getSlotKeyForBoundFactor(target);
    if (slotKey) {
        purgeSlotBoundFromActiveFactorNames();
        await toggleSignalSlotByKey(slotKey);
        const visibleCount = getVisibleQuantFactorNames().length;
        setFactorHint("status updated");
        if (
            currentRightTabName === "量化因子" &&
            currentFactorSnapshotPayload &&
            !shouldUseBacktestPositionSnapshotPanel()
        ) {
            renderFactorSnapshotToRightPanel(
                currentFactorSnapshotPayload,
                Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime
            );
        }
        if (currentRightTabName === "量化因子") {
            scheduleFactorSnapshotForRightPanel(
                Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
                true
            );
        }
        return;
    }
    if (!activeFactorNames.includes(target)) {
        activeFactorNames.push(target);
        if (!selectedFactorName) {
            promoteFactorToPrimary(target);
        }
        const needsInitialLoad = getFactorPoints(target).length === 0;
        await refreshSingleFactorData(target, needsInitialLoad);
        renderSignalData();
        updateSignalCaptionTitle();
        setFactorHint("status updated");
        if (
            currentRightTabName === "量化因子" &&
            currentFactorSnapshotPayload &&
            !shouldUseBacktestPositionSnapshotPanel()
        ) {
            renderFactorSnapshotToRightPanel(
                currentFactorSnapshotPayload,
                Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime
            );
        }
        if (currentRightTabName === "量化因子") {
            scheduleFactorSnapshotForRightPanel(
                Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
                true
            );
        }
        return;
    }
    if (target !== selectedFactorName) {
        activeFactorNames = activeFactorNames.filter((name) => name !== target);
        extraSignalPointsByFactor.delete(target);
        extraLastSignalTimeByFactor.delete(target);
        clearExtraSignalSeries(target);
        renderSignalData();
        updateSignalCaptionTitle();
        setFactorHint("status updated");
        if (currentRightTabName === "量化因子") {
            scheduleFactorSnapshotForRightPanel(
                Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
                true
            );
        }
        return;
    }

    const remaining = activeFactorNames.filter((name) => name !== target);
    activeFactorNames = remaining;
    if (remaining.length > 0) {
        promoteFactorToPrimary(remaining[0]);
        signalPoints = getFactorPoints(selectedFactorName);
        lastSignalTime = getFactorLastSeenTime(selectedFactorName);
    } else {
        selectedFactorName = "";
        signalPoints = [];
        lastSignalTime = null;
        if (factorSelect) {
            factorSelect.value = "";
        }
        persistFactorState();
    }
    renderSignalData();
    updateSignalCaptionTitle();
    setFactorHint("status updated");
    if (currentRightTabName === "量化因子") {
        scheduleFactorSnapshotForRightPanel(
            Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
            true
        );
    }
}

async function clearExtraActiveFactors() {
    if (!selectedFactorName && !activeFactorNames.length) {
        return;
    }
    activeFactorNames = [];
    selectedFactorName = "";
    signalPoints = [];
    lastSignalTime = null;
    extraSignalPointsByFactor.clear();
    extraLastSignalTimeByFactor.clear();
    for (const factorName of Array.from(extraSignalSeriesByFactor.keys())) {
        clearExtraSignalSeries(factorName);
    }
    if (factorSelect) {
        factorSelect.value = "";
    }
    persistFactorState();
    renderSignalData();
    updateSignalCaptionTitle();
    setFactorHint("status updated");
    if (currentRightTabName === "量化因子") {
        scheduleFactorSnapshotForRightPanel(
            Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
            true
        );
    }
}

function scheduleFactorSnapshotForRightPanel(timeValue, immediate = false) {
    if (currentRightTabName !== "量化因子") {
        return;
    }
    if (currentInterval !== "1day") {
        if (shouldUseBacktestPositionSnapshotPanel()) {
            renderBacktestPositionSnapshotStatus("组合持仓快照仅在 1day 周期显示");
        } else {
            renderFactorSnapshotStatus("量化因子列表仅在 1day 周期展示");
        }
        return;
    }
    const normalizedTs = normalizeTimeToSeconds(timeValue !== undefined && timeValue !== null ? timeValue : lastBarTime);
    if (!Number.isFinite(normalizedTs)) {
        if (shouldUseBacktestPositionSnapshotPanel()) {
            renderBacktestPositionSnapshotStatus("");
        } else {
            renderFactorSnapshotStatus("");
        }
        return;
    }

    if (shouldUseBacktestPositionSnapshotPanel()) {
        const renderedKey = currentCode + "|" + normalizedTs + "|position";
        if (renderedKey === lastRenderedSnapshotKey) {
            return;
        }
        const cacheKey = "position|" + currentCode + "|" + normalizedTs;
        const cached = rightPanelSnapshotCache.get(cacheKey);
        if (cached) {
            if (cached && cached.no_data) {
                currentFactorSnapshotTime = normalizedTs;
                renderBacktestPositionSnapshotStatus("status updated");
                return;
            }
            renderBacktestPositionSnapshotToRightPanel(cached, normalizedTs);
            return;
        }
        if (isRightPanelSnapshotRequestPaused()) {
            return;
        }
        const run = async () => {
            if (!getSelectedRunTag()) {
                renderBacktestPositionSnapshotStatus("");
                return;
            }
            const reqSeq = ++snapshotRequestSeq;
            renderBacktestPositionSnapshotStatus("");
            try {
                const payload = await fetchBacktestPositionSnapshot(currentCode, normalizedTs);
                if (reqSeq !== snapshotRequestSeq) {
                    return;
                }
                if (payload && payload.no_data) {
                    rightPanelSnapshotCache.set(cacheKey, payload);
                    pauseRightPanelSnapshotRequestsForInteraction();
                    renderBacktestPositionSnapshotStatus("status updated");
                    return;
                }
                rightPanelSnapshotCache.set(cacheKey, payload);
                renderBacktestPositionSnapshotToRightPanel(payload, normalizedTs);
            } catch (err) {
                if (reqSeq !== snapshotRequestSeq) {
                    return;
                }
                const message = err instanceof Error ? err.message : "组合持仓快照获取失败";
                renderBacktestPositionSnapshotStatus("status updated");
            }
        };

        if (snapshotDebounceTimer) {
            clearTimeout(snapshotDebounceTimer);
            snapshotDebounceTimer = null;
        }
        if (immediate) {
            void run();
            return;
        }
        snapshotDebounceTimer = setTimeout(() => {
            snapshotDebounceTimer = null;
            void run();
        }, RIGHT_PANEL_SNAPSHOT_DEBOUNCE_MS);
        return;
    }

    const snapshotRequest = getSnapshotRequestSignature();
    const snapshotMode = snapshotRequest.mode;
    const renderedKey = currentCode + "|" + normalizedTs + "|factor|" + snapshotRequest.cacheToken;
    // 仅对非 immediate 请求去重；immediate 常用于展开/多选高亮等，数据 key 未变化但 DOM 需要重绘。
    if (!immediate && renderedKey === lastRenderedSnapshotKey) {
        return;
    }
    const cacheKey = currentCode + "|" + normalizedTs + "|" + snapshotRequest.cacheToken;
    const cached = rightPanelSnapshotCache.get(cacheKey);
    if (cached) {
        if (cached && cached.no_data) {
            currentFactorSnapshotTime = normalizedTs;
            renderFactorSnapshotStatus("status updated");
            return;
        }
        renderFactorSnapshotToRightPanel(cached, normalizedTs);
        return;
    }
    if (isRightPanelSnapshotRequestPaused()) {
        return;
    }

    const run = async () => {
        const reqSeq = ++snapshotRequestSeq;
        renderFactorSnapshotStatus("");
        try {
            const payload = await fetchFactorSnapshot(
                currentCode,
                normalizedTs,
                snapshotMode,
                snapshotRequest.groupIds.join(",")
            );
            if (reqSeq !== snapshotRequestSeq) {
                return;
            }
            if (payload && payload.no_data) {
                rightPanelSnapshotCache.set(cacheKey, payload);
                pauseRightPanelSnapshotRequestsForInteraction();
                renderFactorSnapshotStatus("status updated");
                return;
            }
            rightPanelSnapshotCache.set(cacheKey, payload);
            renderFactorSnapshotToRightPanel(payload, normalizedTs);
        } catch (err) {
            if (reqSeq !== snapshotRequestSeq) {
                return;
            }
            const message = err instanceof Error ? err.message : "因子快照获取失败";
            renderFactorSnapshotStatus("status updated");
        }
    };

    if (snapshotDebounceTimer) {
        clearTimeout(snapshotDebounceTimer);
        snapshotDebounceTimer = null;
    }
    if (immediate) {
        void run();
        return;
    }
    snapshotDebounceTimer = setTimeout(() => {
        snapshotDebounceTimer = null;
        void run();
    }, RIGHT_PANEL_SNAPSHOT_DEBOUNCE_MS);
}

function persistQuantFactorUi() {
    if (PAGE_VIEW !== "quant") {
        return;
    }
    try {
        localStorage.setItem(
            QUANT_FACTOR_UI_STORAGE_KEY,
            JSON.stringify({
                activeFactorNames: Array.isArray(activeFactorNames) ? activeFactorNames.slice() : [],
                signalTypeToggleState: { ...signalTypeToggleState },
            })
        );
    } catch (_) {
        /* ignore */
    }
}

function restoreQuantFactorUi() {
    if (PAGE_VIEW !== "quant") {
        return;
    }
    try {
        const raw = localStorage.getItem(QUANT_FACTOR_UI_STORAGE_KEY);
        if (!raw) {
            return;
        }
        const parsed = JSON.parse(raw);
        if (parsed && Array.isArray(parsed.activeFactorNames)) {
            activeFactorNames = parsed.activeFactorNames.filter((n) => String(n || "").trim());
        }
        if (parsed && parsed.signalTypeToggleState && typeof parsed.signalTypeToggleState === "object") {
            for (const spec of SIGNAL_TYPE_TOGGLE_SPECS) {
                const key = spec.key;
                if (key in parsed.signalTypeToggleState) {
                    signalTypeToggleState[key] = Boolean(parsed.signalTypeToggleState[key]);
                }
            }
        }
    } catch (_) {
        /* ignore */
    }
}

async function runFactorCoupleFromUi() {
    const coupleCtl = document.getElementById("factor-snapshot-couple-btn");
    if (coupledSignalPoints.length > 0) {
        clearCoupledSignalLayer();
        updateCoupledSignalOverlay();
        renderSignalData();
        setFactorHint("status updated");
        return;
    }
    const selectedFactors = Array.isArray(activeFactorNames)
        ? activeFactorNames.map((name) => String(name || "").trim()).filter(Boolean)
        : [];
    const uniqueSelectedFactors = Array.from(new Set(selectedFactors));
    if (uniqueSelectedFactors.length < 1) {
        setFactorHint("status updated");
        return;
    }
    if (currentInterval !== "1day") {
        setFactorHint("status updated");
        return;
    }
    if (isYkrsCode()) {
        setFactorHint("status updated");
        return;
    }
    const code = normalizeCodeValue(currentCode);
    if (!code) {
        setFactorHint("status updated");
        return;
    }
    setFactorHint("status updated");
    try {
        const body = await fetchFactorCoupleSeries(code, uniqueSelectedFactors);
        const series = Array.isArray(body.series) ? body.series : [];
        if (!series.length) {
            coupledSignalPoints = [];
            updateCoupledSignalOverlay();
            coupleCtl?.classList.remove("active");
            setFactorHint("status updated");
            return;
        }
        coupledSignalPoints = series;
        updateCoupledSignalOverlay();
        coupleCtl?.classList.add("active");
        const meta = body && body.meta && typeof body.meta === "object" ? body.meta : {};
        const n = Number(meta.row_count);
        setFactorHint("status updated");
    } catch (err) {
        const message = err instanceof Error ? err.message : "因子耦合失败";
        coupleCtl?.classList.remove("active");
        setFactorHint("status updated");
        logUiHint(message);
    }
}

async function exportFactorRankCsv(timeTs, factor) {
    const params = new URLSearchParams({
        time: String(timeTs),
        factor: String(factor || "").trim(),
    });
    const url = API_BASE_URL + "/api/market/factor-export-rank?" + params.toString();
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        const message = body && body.error && body.error.message ? body.error.message : "导出失败";
        throw new Error(message);
    }
    return body;
}

async function backfillSignalsForRange(fromTs, toTs) {
    if (currentInterval !== "1day" || isYkrsCode()) {
        return;
    }
    if (!Number.isFinite(fromTs) || !Number.isFinite(toTs) || fromTs > toTs) {
        return;
    }
    const adHocFactors = getAdHocActiveFactorNames();
    const boundSlotKeys = SIGNAL_TYPE_TOGGLE_SPECS
        .map((spec) => spec.key)
        .filter((key) => String(signalSlotBindings[key] || "").trim());
    if (!adHocFactors.length && !boundSlotKeys.length) {
        return;
    }
    const fetchLimit = Math.min(
        FACTOR_FETCH_LIMIT_MAX,
        Math.max(300, barsCache.length)
    );
    const adHocTasks = adHocFactors.map(async (factorName) => {
        const missingKey = buildMissingFactorKey(currentCode, factorName, currentInterval);
        if (missingFactorKeys.has(missingKey)) {
            return;
        }
        try {
            const payload = await fetchFactorSignals(
                currentCode,
                factorName,
                fromTs,
                toTs,
                null,
                fetchLimit
            );
            const isNoFactor = Boolean(payload && payload.meta && payload.meta.no_factor === true);
            if (isNoFactor) {
                missingFactorKeys.add(missingKey);
                return;
            }
            const incoming = Array.isArray(payload.signals) ? payload.signals : [];
            const merged = mergeFactorPoints(getFactorPoints(factorName), incoming);
            const mergedLastTime = merged.length > 0 ? Number(merged[merged.length - 1].time) : null;
            if (factorName === selectedFactorName) {
                signalPoints = merged;
                lastSignalTime = mergedLastTime;
            } else {
                extraSignalPointsByFactor.set(factorName, merged);
                extraLastSignalTimeByFactor.set(factorName, mergedLastTime);
            }
        } catch (err) {
            // 区间补数失败不打断主图历史加载
        }
    });
    const slotTasks = boundSlotKeys.map(async (slotKey) => {
        const factorName = String(signalSlotBindings[slotKey] || "").trim();
        if (!factorName) {
            return;
        }
        const missingKey = buildMissingFactorKey(currentCode, factorName, currentInterval);
        if (missingFactorKeys.has(missingKey)) {
            return;
        }
        try {
            const payload = await fetchFactorSignals(
                currentCode,
                factorName,
                fromTs,
                toTs,
                null,
                fetchLimit
            );
            const isNoFactor = Boolean(payload && payload.meta && payload.meta.no_factor === true);
            if (isNoFactor) {
                missingFactorKeys.add(missingKey);
                return;
            }
            const incoming = Array.isArray(payload.signals) ? payload.signals : [];
            const merged = mergeFactorPoints(getSlotSignalPoints(slotKey), incoming);
            const mergedLastTime = merged.length > 0 ? Number(merged[merged.length - 1].time) : null;
            slotSignalPointsByKey.set(slotKey, merged);
            slotLastSignalTimeByKey.set(slotKey, mergedLastTime);
        } catch (err) {
            // 区间补数失败不打断主图历史加载
        }
    });
    await Promise.all([...adHocTasks, ...slotTasks]);
    renderSignalData();
    syncSignalChartViewportFromMain();
}

async function loadFactorOptions() {
    try {
        setFactorHint("status updated");
        installFactorSnapshotFilterUi();
        const catalogPayload = await fetchFactorNames();
        factorNames = Array.isArray(catalogPayload.factors) ? catalogPayload.factors : [];
        factorGroups = Array.isArray(catalogPayload.groups) ? catalogPayload.groups : [];
        factorCoreNames = Array.isArray(catalogPayload.core_factors) ? catalogPayload.core_factors : [];
        factorCoreLabels = Array.isArray(catalogPayload.core_factor_labels) ? catalogPayload.core_factor_labels : [];
        factorLabelMap = catalogPayload.factor_labels && typeof catalogPayload.factor_labels === "object"
            ? catalogPayload.factor_labels
            : {};
        const savedFactor = restoreFactorState();
        if (savedFactor && factorNames.includes(savedFactor)) {
            selectedFactorName = savedFactor;
        } else if (factorCoreNames.length > 0) {
            const firstCore = factorCoreNames.find((name) => factorNames.includes(name));
            selectedFactorName = firstCore || "";
        } else if (factorNames.length > 0) {
            selectedFactorName = factorNames[0];
        } else {
            selectedFactorName = "";
        }
        const restoredActiveNames = [];
        const seenActiveNames = new Set();
        for (const name of Array.isArray(activeFactorNames) ? activeFactorNames : []) {
            const factorName = String(name || "").trim();
            if (factorName && factorNames.includes(factorName) && !seenActiveNames.has(factorName)) {
                restoredActiveNames.push(factorName);
                seenActiveNames.add(factorName);
            }
        }
        if (savedFactor && selectedFactorName && factorNames.includes(selectedFactorName) && !seenActiveNames.has(selectedFactorName)) {
            restoredActiveNames.unshift(selectedFactorName);
            seenActiveNames.add(selectedFactorName);
        }
        activeFactorNames = restoredActiveNames;
        purgeSlotBoundFromActiveFactorNames();
        renderFactorOptions();
        applySignalSlotBindingUi();
        setFactorHint(factorNames.length ? ("Available factors: " + factorNames.length) : "No factors found");


        if (barsCache.length > 0) {
            await refreshSlotBoundSignalData(true);
            if (activeFactorNames.length) {
                await refreshSignalData(true);
            }
        }
        updateExportFactorOptions();
    } catch (err) {
        factorNames = [];
        factorGroups = [];
        factorCoreNames = [];
        factorCoreLabels = [];
        factorLabelMap = {};
        selectedFactorName = "";
        renderFactorOptions();
        const message = err instanceof Error ? err.message : "因子列表加载失败";
        setFactorHint("status updated");
        logUiHint(message);
        updateExportFactorOptions();
    }
}

async function refreshSignalData(isInitialLoad = false) {
    if (isYkrsCode()) {
        signalPoints = [];
        lastSignalTime = null;
        extraSignalPointsByFactor.clear();
        extraLastSignalTimeByFactor.clear();
        renderSignalData();
        setFactorHint("status updated");
        updateSignalCaptionTitle();
        return;
    }
    if (currentInterval !== "1day") {
        signalPoints = [];
        lastSignalTime = null;
        extraSignalPointsByFactor.clear();
        extraLastSignalTimeByFactor.clear();
        renderSignalData();
        setFactorHint("status updated");
        updateSignalCaptionTitle();
        return;
    }
    const adHocFactors = getAdHocActiveFactorNames();
    if (!adHocFactors.length) {
        renderSignalData();
        updateSignalCaptionTitle();
        return;
    }
    if (adHocFactors.includes(selectedFactorName)) {
        promoteFactorToPrimary(selectedFactorName);
    } else if (selectedFactorName && !adHocFactors.includes(selectedFactorName)) {
        selectedFactorName = adHocFactors[0];
        if (factorSelect) {
            factorSelect.value = selectedFactorName;
        }
    }
    try {
        await Promise.all(adHocFactors.map((factorName) => refreshSingleFactorData(factorName, isInitialLoad)));
        renderSignalData();
        updateSignalCaptionTitle();
        setFactorHint("status updated");
    } catch (err) {
        const message = err instanceof Error ? err.message : "因子数据刷新失败";
        signalPoints = [];
        lastSignalTime = null;
        extraSignalPointsByFactor.clear();
        extraLastSignalTimeByFactor.clear();
        renderSignalData();
        updateSignalCaptionTitle();
        setFactorHint("status updated");
        logUiHint(message);
    }
}

function removeFactorSnapshotDragGhost() {
    if (!factorSnapshotDragState) {
        return;
    }
    const { ghostEl, sourceItem, dropTargetItem } = factorSnapshotDragState;
    if (ghostEl && ghostEl.parentNode) {
        ghostEl.parentNode.removeChild(ghostEl);
    }
    if (sourceItem) {
        sourceItem.classList.remove("drag-origin");
    }
    if (dropTargetItem) {
        dropTargetItem.classList.remove("drop-before", "drop-after");
    }
    const dropRuleZone = document.querySelector(".backtest-rule-drop-zone.drag-over");
    if (dropRuleZone) {
        dropRuleZone.classList.remove("drag-over");
    }
    clearSignalSlotDropTargets();
    document.body.classList.remove("factor-snapshot-dragging");
    factorSnapshotDragState = null;
}

function beginFactorSnapshotDrag(event) {
    if (
        event.button !== 0 ||
        !(event.target instanceof Element) ||
        currentRightTabName !== "量化因子"
    ) {
        return;
    }
    if (event.target.closest(".factor-group-toggle")) {
        return;
    }
    const sourceItem = event.target.closest(".factor-snapshot-item[data-factor-name]");
    const sourceFactorName = sourceItem ? String(sourceItem.getAttribute("data-factor-name") || "").trim() : "";
    const sourceContainer = sourceItem ? sourceItem.closest(".factor-group-items") : null;
    const sourceGroup = sourceItem ? sourceItem.closest(".factor-group-block") : null;
    const sourceGroupId = sourceGroup ? String(sourceGroup.getAttribute("data-factor-group") || "").trim() : "";
    const isPinned = Boolean(sourceItem && sourceItem.closest(".factor-pinned-wrap"));
    const isSummary = Boolean(sourceItem && sourceItem.classList.contains("factor-snapshot-item--header-summary"));
    if (!sourceItem || !sourceFactorName) {
        return;
    }
    if (!sourceContainer && !isPinned && !isSummary) {
        return;
    }
    if (!sourceGroupId && !isPinned) {
        return;
    }
    event.preventDefault();
    try {
        if (typeof sourceItem.setPointerCapture === "function") {
            sourceItem.setPointerCapture(event.pointerId);
        }
    } catch {
        /* ignore */
    }
    const sourceRect = sourceItem.getBoundingClientRect();
    const offsetX = event.clientX - sourceRect.left;
    const offsetY = event.clientY - sourceRect.top;
    factorSnapshotDragState = {
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        offsetX,
        offsetY,
        sourceItem,
        sourceContainer,
        sourceGroupId: isPinned ? "__pinned__" : sourceGroupId,
        sourceFactorName,
        ghostEl: null,
        hasDragged: false,
        dropTargetItem: null,
        dropPosition: "",
        dropRuleSide: "",
        dropSignalSlotKey: ""
    };
}

function moveFactorSnapshotDrag(event) {
    if (!factorSnapshotDragState || event.pointerId !== factorSnapshotDragState.pointerId) {
        return;
    }
    event.preventDefault();
    const moveX = event.clientX - factorSnapshotDragState.startClientX;
    const moveY = event.clientY - factorSnapshotDragState.startClientY;
    if (!factorSnapshotDragState.hasDragged) {
        const movedEnough = (Math.abs(moveX) + Math.abs(moveY)) >= 4;
        if (!movedEnough) {
            return;
        }
        factorSnapshotDragState.hasDragged = true;
        const ghostEl = factorSnapshotDragState.sourceItem.cloneNode(true);
        ghostEl.classList.add("factor-snapshot-drag-ghost");
        ghostEl.classList.remove("active", "drag-origin");
        ghostEl.style.setProperty("--ghost-width", factorSnapshotDragState.sourceItem.getBoundingClientRect().width + "px");
        factorSnapshotDragState.ghostEl = ghostEl;
        factorSnapshotDragState.sourceItem.classList.add("drag-origin");
        document.body.classList.add("factor-snapshot-dragging");
        document.body.appendChild(ghostEl);
    }
    if (!factorSnapshotDragState.ghostEl) {
        return;
    }
    const left = event.clientX - factorSnapshotDragState.offsetX;
    const top = event.clientY - factorSnapshotDragState.offsetY;
    factorSnapshotDragState.ghostEl.style.left = left + "px";
    factorSnapshotDragState.ghostEl.style.top = top + "px";

    if (factorSnapshotDragState.dropTargetItem) {
        factorSnapshotDragState.dropTargetItem.classList.remove("drop-before", "drop-after");
        factorSnapshotDragState.dropTargetItem = null;
        factorSnapshotDragState.dropPosition = "";
    }
    const previousRuleZone = document.querySelector(".backtest-rule-drop-zone.drag-over");
    if (previousRuleZone) {
        previousRuleZone.classList.remove("drag-over");
    }
    factorSnapshotDragState.dropRuleSide = "";
    clearSignalSlotDropTargets();
    const slotBtn = findSignalSlotAtPoint(event.clientX, event.clientY);
    if (slotBtn) {
        slotBtn.classList.add("drop-target");
        factorSnapshotDragState.dropSignalSlotKey = String(slotBtn.dataset.signalType || "");
        return;
    }
    factorSnapshotDragState.dropSignalSlotKey = "";
    const pointedEl = document.elementFromPoint(event.clientX, event.clientY);
    const ruleZone =
        (pointedEl instanceof Element ? pointedEl.closest(".backtest-rule-drop-zone") : null) ||
        findBacktestRuleDropZoneAtPoint(event.clientX, event.clientY);
    if (ruleZone) {
        const side = String(ruleZone.getAttribute("data-backtest-rule-side") || "").trim();
        if (side === "buy" || side === "sell") {
            ruleZone.classList.add("drag-over");
            factorSnapshotDragState.dropRuleSide = side;
            return;
        }
    }
    const pointedItem = pointedEl instanceof Element ? pointedEl.closest(".factor-group-items .factor-snapshot-item") : null;
    if (!pointedItem || pointedItem === factorSnapshotDragState.sourceItem) {
        return;
    }
    const pointedContainer = pointedItem.closest(".factor-group-items");
    if (pointedContainer !== factorSnapshotDragState.sourceContainer) {
        return;
    }
    const rect = pointedItem.getBoundingClientRect();
    const dropBefore = event.clientY < rect.top + (rect.height / 2);
    factorSnapshotDragState.dropTargetItem = pointedItem;
    factorSnapshotDragState.dropPosition = dropBefore ? "before" : "after";
    pointedItem.classList.add(dropBefore ? "drop-before" : "drop-after");
}

function endFactorSnapshotDrag(event) {
    if (!factorSnapshotDragState || event.pointerId !== factorSnapshotDragState.pointerId) {
        return;
    }
    if (factorSnapshotDragState.hasDragged) {
        suppressFactorSnapshotClickUntil = Date.now() + 300;
        const {
            sourceItem,
            sourceContainer,
            sourceGroupId,
            dropTargetItem,
            dropPosition,
            dropRuleSide,
            dropSignalSlotKey,
            sourceFactorName
        } = factorSnapshotDragState;
        let effectiveSlotKey = String(dropSignalSlotKey || "");
        if (!effectiveSlotKey) {
            const slotBtn = findSignalSlotAtPoint(event.clientX, event.clientY);
            if (slotBtn) {
                effectiveSlotKey = String(slotBtn.dataset.signalType || "");
            }
        }
        if (effectiveSlotKey) {
            suppressSignalSlotClickUntil = Date.now() + 320;
            void bindFactorToSignalSlot(effectiveSlotKey, sourceFactorName);
        } else if (dropRuleSide === "buy" || dropRuleSide === "sell") {
            addBacktestRule(dropRuleSide, sourceFactorName);
        } else if (dropTargetItem && sourceItem && sourceContainer) {
            if (dropPosition === "before") {
                sourceContainer.insertBefore(sourceItem, dropTargetItem);
            } else if (dropPosition === "after") {
                sourceContainer.insertBefore(sourceItem, dropTargetItem.nextSibling);
            }
            const order = Array.from(
                sourceContainer.querySelectorAll(".factor-snapshot-item[data-factor-name]")
            )
                .map((el) => String(el.getAttribute("data-factor-name") || "").trim())
                .filter(Boolean);
            if (order.length) {
                factorOrderByGroup[sourceGroupId] = order;
            }
        }
    } else {
        const { sourceFactorName } = factorSnapshotDragState;
        if (sourceFactorName && Date.now() >= suppressFactorSnapshotClickUntil) {
            if (event.metaKey || event.ctrlKey || isFactorSnapshotActive(sourceFactorName)) {
                void toggleFactorActiveState(sourceFactorName);
            } else {
                void selectFactorAndRefresh(sourceFactorName);
            }
        }
    }
    removeFactorSnapshotDragGhost();
}

function removeFactorGroupDragGhost() {
    if (!factorGroupDragState) {
        return;
    }
    const { ghostEl, sourceBlock, dropTargetBlock } = factorGroupDragState;
    if (ghostEl && ghostEl.parentNode) {
        ghostEl.parentNode.removeChild(ghostEl);
    }
    if (sourceBlock) {
        sourceBlock.classList.remove("drag-origin");
    }
    if (dropTargetBlock) {
        dropTargetBlock.classList.remove("drop-before", "drop-after");
    }
    const dropRuleZone = document.querySelector(".backtest-rule-drop-zone.drag-over");
    if (dropRuleZone) {
        dropRuleZone.classList.remove("drag-over");
    }
    document.body.classList.remove("factor-snapshot-dragging");
    factorGroupDragState = null;
}

function beginFactorGroupDrag(event) {
    if (
        event.button !== 0 ||
        !(event.target instanceof Element) ||
        currentRightTabName !== "量化因子" ||
        shouldUseBacktestPositionSnapshotPanel()
    ) {
        return;
    }
    const handleEl = event.target.closest(".factor-group-header");
    const toggleBtn = event.target.closest(".factor-group-toggle");
    if (event.target.closest(".factor-snapshot-item[data-factor-name]")) {
        return;
    }
    const sourceBlock = event.target.closest(".factor-group-block");
    const sourceGroupId = sourceBlock ? String(sourceBlock.getAttribute("data-factor-group") || "").trim() : "";
    const listEl = document.getElementById("factor-snapshot-list");
    if (!handleEl || toggleBtn || !sourceBlock || !sourceGroupId || !listEl) {
        return;
    }
    event.preventDefault();
    const sourceRect = sourceBlock.getBoundingClientRect();
    factorGroupDragState = {
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        offsetX: event.clientX - sourceRect.left,
        offsetY: event.clientY - sourceRect.top,
        sourceBlock,
        sourceGroupId,
        listEl,
        ghostEl: null,
        hasDragged: false,
        dropTargetBlock: null,
        dropPosition: "",
        dropRuleSide: ""
    };
}

function moveFactorGroupDrag(event) {
    if (!factorGroupDragState || event.pointerId !== factorGroupDragState.pointerId) {
        return;
    }
    event.preventDefault();
    const moveX = event.clientX - factorGroupDragState.startClientX;
    const moveY = event.clientY - factorGroupDragState.startClientY;
    if (!factorGroupDragState.hasDragged) {
        const movedEnough = (Math.abs(moveX) + Math.abs(moveY)) >= 4;
        if (!movedEnough) {
            return;
        }
        factorGroupDragState.hasDragged = true;
        const ghostEl = factorGroupDragState.sourceBlock.cloneNode(true);
        ghostEl.classList.add("factor-group-drag-ghost");
        ghostEl.classList.remove("drag-origin");
        ghostEl.style.setProperty("--ghost-width", factorGroupDragState.sourceBlock.getBoundingClientRect().width + "px");
        factorGroupDragState.ghostEl = ghostEl;
        factorGroupDragState.sourceBlock.classList.add("drag-origin");
        document.body.classList.add("factor-snapshot-dragging");
        document.body.appendChild(ghostEl);
    }
    if (!factorGroupDragState.ghostEl) {
        return;
    }
    factorGroupDragState.ghostEl.style.left = (event.clientX - factorGroupDragState.offsetX) + "px";
    factorGroupDragState.ghostEl.style.top = (event.clientY - factorGroupDragState.offsetY) + "px";
    if (factorGroupDragState.dropTargetBlock) {
        factorGroupDragState.dropTargetBlock.classList.remove("drop-before", "drop-after");
        factorGroupDragState.dropTargetBlock = null;
        factorGroupDragState.dropPosition = "";
    }
    const previousRuleZone = document.querySelector(".backtest-rule-drop-zone.drag-over");
    if (previousRuleZone) {
        previousRuleZone.classList.remove("drag-over");
    }
    factorGroupDragState.dropRuleSide = "";
    const pointedEl = document.elementFromPoint(event.clientX, event.clientY);
    const ruleZone =
        (pointedEl instanceof Element ? pointedEl.closest(".backtest-rule-drop-zone") : null) ||
        findBacktestRuleDropZoneAtPoint(event.clientX, event.clientY);
    if (ruleZone) {
        const side = String(ruleZone.getAttribute("data-backtest-rule-side") || "").trim();
        if (side === "buy" || side === "sell") {
            ruleZone.classList.add("drag-over");
            factorGroupDragState.dropRuleSide = side;
            return;
        }
    }
    const targetBlock = pointedEl instanceof Element ? pointedEl.closest(".factor-group-block") : null;
    if (!targetBlock || targetBlock === factorGroupDragState.sourceBlock) {
        return;
    }
    const rect = targetBlock.getBoundingClientRect();
    const dropBefore = event.clientY < rect.top + (rect.height / 2);
    factorGroupDragState.dropTargetBlock = targetBlock;
    factorGroupDragState.dropPosition = dropBefore ? "before" : "after";
    targetBlock.classList.add(dropBefore ? "drop-before" : "drop-after");
}

function endFactorGroupDrag(event) {
    if (!factorGroupDragState || event.pointerId !== factorGroupDragState.pointerId) {
        return;
    }
    if (factorGroupDragState.hasDragged) {
        suppressFactorSnapshotClickUntil = Date.now() + 300;
        const { sourceBlock, dropTargetBlock, dropPosition, listEl, dropRuleSide } = factorGroupDragState;
        if (sourceBlock && (dropRuleSide === "buy" || dropRuleSide === "sell")) {
            const summaryFactorEl = sourceBlock.querySelector(".factor-group-summary-row[data-factor-name]");
            const summaryFactorName = summaryFactorEl
                ? String(summaryFactorEl.getAttribute("data-factor-name") || "").trim()
                : "";
            if (summaryFactorName) {
                addBacktestRule(dropRuleSide, summaryFactorName);
            }
        } else if (sourceBlock && dropTargetBlock && listEl) {
            if (dropPosition === "before") {
                listEl.insertBefore(sourceBlock, dropTargetBlock);
            } else if (dropPosition === "after") {
                listEl.insertBefore(sourceBlock, dropTargetBlock.nextSibling);
            }
            factorGroupOrder = Array.from(listEl.querySelectorAll(".factor-group-block[data-factor-group]"))
                .map((el) => String(el.getAttribute("data-factor-group") || "").trim())
                .filter(Boolean);
        }
    }
    removeFactorGroupDragGhost();
}

intervalSelect.addEventListener("change", async () => {
    await switchIntervalAndReload();
    countdownValue = AUTO_REFRESH_SECONDS;
    updateExportFactorOptions();
});
if (adjustModeSelect) {
    adjustModeSelect.addEventListener("change", async () => {
        const nextMode = String(adjustModeSelect.value || "qfq").trim();
        currentAdjustMode = Object.prototype.hasOwnProperty.call(ADJUST_MODE_PARAM, nextMode)
            ? nextMode
            : "qfq";
        adjustModeSelect.value = currentAdjustMode;
        await switchIntervalAndReload();
        countdownValue = AUTO_REFRESH_SECONDS;
    });
}
if (factorSelect) {
    factorSelect.addEventListener("change", async () => {
        await selectFactorAndRefresh(factorSelect.value);
    });
}
if (exportFactorSelect && exportFactorSummary) {
    exportFactorSelect.addEventListener("change", () => {
        const selectedText = exportFactorSelect.options[exportFactorSelect.selectedIndex]
            ? exportFactorSelect.options[exportFactorSelect.selectedIndex].text
            : "未选择";
        exportFactorSummary.textContent = "Selected: " + selectedText;
    });
}
if (exportSymbolsBtn) {
    exportSymbolsBtn.addEventListener("click", async () => {
        if (currentInterval !== "1day") {
            logUiHint("仅支持在 1day 周期导出因子排名");
            return;
        }
        const factor = exportFactorSelect ? String(exportFactorSelect.value || "").trim() : "";
        if (!factor) {
            logUiHint("请先在筛选列表选择一个主因子");
            return;
        }
        const exportTime = Number.isFinite(currentFactorSnapshotTime) ? Number(currentFactorSnapshotTime) : Number(lastBarTime);
        if (!Number.isFinite(exportTime)) {
            logUiHint("当前没有可导出的时间点");
            return;
        }
        exportSymbolsBtn.disabled = true;
        const oldText = exportSymbolsBtn.textContent;
        exportSymbolsBtn.textContent = "导出中...";
        try {
            const payload = await exportFactorRankCsv(exportTime, factor);
            const filePath = payload && payload.file_path ? String(payload.file_path) : "";
            const rowCount = payload && payload.meta ? Number(payload.meta.row_count || 0) : 0;
            logUiHint("导出完成: " + rowCount + " rows");
            if (filePath) {
                alert("导出完成\n" + filePath);
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : "导出失败";
            logUiHint("导出失败: " + message);
            alert("导出失败\n" + message);
        } finally {
            exportSymbolsBtn.textContent = oldText;
            exportSymbolsBtn.disabled = false;
            updateExportFactorOptions();
            if (exportFactorDetails) {
                exportFactorDetails.open = false;
            }
        }
    });
}
if (paramTraverseToggle) {
    const applyParamTraverseToggleUi = () => {
        paramTraverseToggle.setAttribute("aria-pressed", paramTraverseSwitchOn ? "true" : "false");
        paramTraverseToggle.classList.toggle("param-traverse-toggle-on", paramTraverseSwitchOn);
    };
    applyParamTraverseToggleUi();
    paramTraverseToggle.addEventListener("click", () => {
        paramTraverseSwitchOn = !paramTraverseSwitchOn;
        applyParamTraverseToggleUi();
        refreshOptunaControlsVisibility();
        ensureAllRulesTraverseFields();
        renderBacktestRulePanels();
    });
}

function applySignalTypeToggleUi() {
    if (!signalTypeTogglesWrap) {
        return;
    }
    signalTypeTogglesWrap.querySelectorAll(".signal-type-toggle[data-signal-type]").forEach((btnEl) => {
        const key = String(btnEl.dataset.signalType || "");
        const active = Boolean(signalTypeToggleState[key]);
        btnEl.classList.toggle("param-traverse-toggle-on", active);
        btnEl.setAttribute("aria-pressed", active ? "true" : "false");
    });
}

async function setSignalSlotToggle(slotKey, nextOn, options = {}) {
    const key = String(slotKey || "").trim();
    if (!key || !(key in signalTypeToggleState)) {
        return;
    }
    const on = Boolean(nextOn);
    if (signalTypeToggleState[key] === on && !options.force) {
        if (options.render !== false) {
            renderSignalData();
            updateSignalCaptionTitle();
        }
        return;
    }
    signalTypeToggleState[key] = on;
    persistQuantFactorUi();
    applySignalTypeToggleUi();
    if (
        on &&
        String(signalSlotBindings[key] || "").trim() &&
        currentInterval === "1day" &&
        !isYkrsCode() &&
        barsCache.length > 0
    ) {
        const needsInitial = getSlotSignalPoints(key).length === 0;
        await refreshSingleSlotFactorData(key, needsInitial);
    }
    if (options.render !== false) {
        renderSignalData();
        updateSignalCaptionTitle();
    }
    if (options.refreshPanel !== false && currentRightTabName === "量化因子") {
        scheduleFactorSnapshotForRightPanel(
            Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime,
            true
        );
    }
}

async function toggleSignalSlotByKey(slotKey) {
    const key = String(slotKey || "").trim();
    if (!key || !(key in signalTypeToggleState)) {
        return;
    }
    await setSignalSlotToggle(key, !signalTypeToggleState[key]);
}

function getSignalTypeToggleState() {
    return { ...signalTypeToggleState };
}

window.getSignalTypeToggleState = getSignalTypeToggleState;
window.getSignalSlotBindings = () => ({ ...signalSlotBindings });
window.ChartBoardView = { id: "quant", label: "量化因子" };








