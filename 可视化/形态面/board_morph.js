/* 形态面专属逻辑 — 在 chart_board_core.js + chart_board_backtest.js 之后加载 */

/** 形态面与量化面共用 K 线缓存与左拖历史加载，不再使用 250 根滑动窗口 */
function shouldUseMorphBarWindow() {
    return false;
}

function getMorphActiveLevelKeys() {
    return ["level1", "level2", "level3"].filter((key) => morphPanelState[key]);
}

function isMorphWindowEdgeCheckSuppressed() {
    return morphWindowShiftInFlight
        || Date.now() < morphWindowEdgeCheckSuppressedUntil;
}

function suppressMorphWindowEdgeCheck(ms = MORPH_WINDOW_EDGE_SUPPRESS_MS) {
    morphWindowEdgeCheckSuppressedUntil = Date.now() + ms;
}

function cancelMorphWindowEdgeCheckTimer() {
    if (morphWindowEdgeCheckTimer) {
        clearTimeout(morphWindowEdgeCheckTimer);
        morphWindowEdgeCheckTimer = null;
    }
}

function isMorphWindowLogicalAtLeftShiftEdge(logicalRange) {
    return Boolean(logicalRange && Number(logicalRange.from) <= 0.5);
}

function isMorphWindowLogicalAtRightShiftEdge(logicalRange, maxIndex) {
    return Boolean(
        logicalRange
        && maxIndex >= 0
        && Number(logicalRange.to) >= maxIndex - 0.5,
    );
}

function shouldDeferMorphWindowShift(logicalRange) {
    if (morphWindowShiftInFlight) {
        return true;
    }
    if (!morphWindowChartInteracting) {
        return false;
    }
    return Boolean(logicalRange && !isMorphWindowLogicalAtLeftShiftEdge(logicalRange));
}

function getMorphWindowVisibleSpan(logicalRange, fallback = 100) {
    if (!logicalRange) {
        return fallback;
    }
    return Math.min(
        getMorphWindowMaxVisibleSpan(barsCache.length, logicalRange),
        Math.max(10, logicalRange.to - logicalRange.from),
    );
}

function trimMorphShiftBatchOlder(bars) {
    const normalized = normalizeBarsArray(bars);
    if (!normalized.length || normalized.length <= MORPH_WINDOW_SHIFT_BATCH_BARS) {
        return normalized;
    }
    return normalized.slice(-MORPH_WINDOW_SHIFT_BATCH_BARS);
}

function trimMorphShiftBatchNewer(bars) {
    const normalized = normalizeBarsArray(bars);
    if (!normalized.length || normalized.length <= MORPH_WINDOW_SHIFT_BATCH_BARS) {
        return normalized;
    }
    return normalized.slice(0, MORPH_WINDOW_SHIFT_BATCH_BARS);
}

function updateMorphTimeScaleZoomLimits() {
    if (!chart || !shouldUseMorphBarWindow()) {
        return;
    }
    const width = Math.max(200, container ? container.clientWidth : 800);
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    const maxVisible = getMorphWindowMaxVisibleSpan(barsCache.length, logicalRange);
    const minBarSpacing = Math.max(0.5, width / maxVisible);
    chart.timeScale().applyOptions({ minBarSpacing });
}

function syncMorphViewportLogicalRangeClamp() {
    if (!shouldUseMorphBarWindow() || !chart) {
        return false;
    }
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (!logicalRange) {
        return false;
    }
    const clamped = clampVisibleLogicalRangeToDataBounds(logicalRange);
    if (!clamped) {
        return false;
    }
    const changed = Math.abs(clamped.from - logicalRange.from) > 0.01
        || Math.abs(clamped.to - logicalRange.to) > 0.01;
    if (changed) {
        suppressMorphWindowEdgeCheck();
        chart.timeScale().setVisibleLogicalRange(clamped);
        syncSignalChartViewportFromMain();
    }
    return changed;
}

function clampMorphWindowToLeftEdge(span) {
    const maxIndex = barsCache.length - 1;
    if (maxIndex < 0) {
        return;
    }
    const safeSpan = Math.min(
        getMorphWindowVisibleSpan({ from: -0.5, to: -0.5 + span }, span),
        maxIndex + 1,
    );
    suppressMorphWindowEdgeCheck();
    setMainChartVisibleLogicalRange({
        from: -0.5,
        to: Math.min(maxIndex + 0.5, -0.5 + safeSpan),
    });
}

function clampMorphWindowPastRightEdge(logicalRange, span) {
    const maxIndex = barsCache.length - 1;
    if (maxIndex < 0 || !logicalRange) {
        return false;
    }
    const maxTo = maxIndex + 0.5;
    if (Number(logicalRange.to) <= maxTo + 0.01) {
        return false;
    }
    const safeSpan = getMorphWindowVisibleSpan(logicalRange, span);
    suppressMorphWindowEdgeCheck();
    setMainChartVisibleLogicalRange({
        from: Math.max(-0.5, maxTo - safeSpan),
        to: maxTo,
    });
    return true;
}

function setMorphWindowVisibleRangeAfterShiftOlder(span) {
    const maxIndex = barsCache.length - 1;
    if (maxIndex < 0) {
        return;
    }
    const cushion = MORPH_WINDOW_SHIFT_EDGE_CUSHION;
    const to = Math.max(cushion, maxIndex - cushion);
    const from = Math.max(-0.5, to - span);
    suppressMorphWindowEdgeCheck();
    setMainChartVisibleLogicalRange({ from, to });
}

function setMorphWindowVisibleRangeAfterShiftNewer(span) {
    const maxIndex = barsCache.length - 1;
    if (maxIndex < 0) {
        return;
    }
    const cushion = MORPH_WINDOW_SHIFT_EDGE_CUSHION;
    const from = Math.min(maxIndex - 10, -0.5 + cushion);
    const to = Math.min(maxIndex + 0.5, from + span);
    suppressMorphWindowEdgeCheck();
    setMainChartVisibleLogicalRange({ from, to });
}

function filterMorphBarsStrictlyBefore(bars, beforeTime) {
    const cutoff = Number(beforeTime);
    if (!Number.isFinite(cutoff)) {
        return [];
    }
    return normalizeBarsArray(bars).filter((bar) => Number(bar.time) < cutoff);
}

function mergeMorphWindowOlderIncoming(incoming, beforeTime) {
    const older = filterMorphBarsStrictlyBefore(incoming, beforeTime);
    if (!older.length) {
        return null;
    }
    const merged = normalizeBarsArray([...older, ...barsCache]);
    if (merged.length <= MORPH_WINDOW_MAX_BARS) {
        return merged;
    }
    return merged.slice(0, MORPH_WINDOW_MAX_BARS);
}

async function fetchMorphWindowOlderIncoming(beforeTime) {
    const firstBarTime = Number(beforeTime);
    if (!Number.isFinite(firstBarTime)) {
        return { incoming: [], toTs: null, fromTs: null, invalidBoundary: true };
    }
    const toTs = alignToCurrentInterval(firstBarTime - getIntervalConfig().alignStepSeconds);
    if (!Number.isFinite(toTs) || toTs <= 0) {
        return { incoming: [], toTs, fromTs: null, invalidBoundary: true };
    }
    const fromTs = alignToCurrentInterval(toTs - getIntervalConfig().historicalBackfillWindowSeconds);
    const payload = await fetchMorphWindowBarsByTimeRange(fromTs, toTs);
    return {
        incoming: filterMorphBarsStrictlyBefore(payload, firstBarTime),
        toTs,
        fromTs,
        invalidBoundary: false,
    };
}

function buildMorphWindowBarsByPrepend(olderBars, anchorTime) {
    return mergeMorphWindowOlderIncoming(olderBars, anchorTime);
}

function buildMorphWindowBarsByAppend(newerBars) {
    const newer = normalizeBarsArray(newerBars);
    if (!newer.length) {
        return null;
    }
    const merged = [...barsCache, ...newer];
    if (merged.length <= MORPH_WINDOW_MAX_BARS) {
        return merged;
    }
    return merged.slice(-MORPH_WINDOW_MAX_BARS);
}

function preserveMorphViewportAfterBarShift(anchorTime, anchorIndexBefore, visibleBefore) {
    if (!visibleBefore || !Number.isFinite(anchorTime) || !Number.isFinite(anchorIndexBefore)) {
        return false;
    }
    ensureBarsDayIndexMap();
    const anchorKey = alignToCurrentInterval(Number(anchorTime));
    const newIdx = barsDayIndexMap.get(anchorKey);
    if (newIdx === undefined) {
        return false;
    }
    const delta = newIdx - anchorIndexBefore;
    suppressMorphWindowEdgeCheck();
    setMainChartVisibleLogicalRange({
        from: visibleBefore.from + delta,
        to: visibleBefore.to + delta,
    });
    return true;
}

function resetMorphWindowState() {
    morphWindowAtLatest = true;
    morphWindowShiftInFlight = false;
    morphWindowPreloadedBars = null;
    morphWindowPreloadDirection = "";
    morphWindowEdgeCheckSuppressedUntil = 0;
    morphWindowChartInteracting = false;
    morphWindowLastShiftAt = 0;
    cancelMorphWindowEdgeCheckTimer();
    historyExhausted = false;
    lastHistoryRequestTo = null;
}

function normalizeBarsArray(rawBars) {
    const byTime = new Map();
    for (const bar of (Array.isArray(rawBars) ? rawBars : [])) {
        const ts = Number(bar && bar.time);
        if (Number.isFinite(ts)) {
            byTime.set(ts, bar);
        }
    }
    return Array.from(byTime.values()).sort((a, b) => Number(a.time) - Number(b.time));
}

function trimBarsToMorphWindow(rawBars, maxBars = MORPH_WINDOW_MAX_BARS) {
    const sorted = normalizeBarsArray(rawBars);
    if (sorted.length <= maxBars) {
        return sorted;
    }
    return sorted.slice(sorted.length - maxBars);
}

function replaceMorphBarsWindow(rawBars) {
    barsCache = trimBarsToMorphWindow(rawBars, MORPH_WINDOW_MAX_BARS);
    lastBarTime = barsCache.length > 0 ? Number(barsCache[barsCache.length - 1].time) : null;
    rebuildBarsDayIndexMap();
    const nowTs = alignToCurrentInterval(Math.floor(Date.now() / 1000));
    if (!Number.isFinite(lastBarTime)) {
        morphWindowAtLatest = true;
        applyMorphMainChartTimeScaleOptions();
        return;
    }
    morphWindowAtLatest = Math.abs(lastBarTime - nowTs) <= 86400 * 3;
    applyMorphMainChartTimeScaleOptions();
    syncMorphViewportLogicalRangeClamp();
}

function applyMorphMainChartTimeScaleOptions() {
    if (!chart || !shouldUseMorphBarWindow()) {
        return;
    }
    updateMorphTimeScaleZoomLimits();
    chart.timeScale().applyOptions({
        fixLeftEdge: false,
        fixRightEdge: false,
    });
}

function syncMorphWindowAtLatestFromViewport() {
    if (!shouldUseMorphBarWindow() || !chart) {
        return;
    }
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (!logicalRange) {
        return;
    }
    const nearLatest = isNearNewestVisibleBar(logicalRange)
        && Number(logicalRange.from) >= getMorphLatestWindowMinFrom() - 1;
    if (nearLatest === morphWindowAtLatest) {
        return;
    }
    morphWindowAtLatest = nearLatest;
    updateMorphTimeScaleZoomLimits();
    chart.timeScale().applyOptions({
        fixLeftEdge: false,
        fixRightEdge: false,
    });
}

function getMorphWindowRangeTimestamps() {
    if (!barsCache.length) {
        return null;
    }
    return {
        fromTs: Number(barsCache[0].time),
        toTs: Number(barsCache[barsCache.length - 1].time),
    };
}

async function fetchMorphWindowBarsByTimeRange(fromTs, toTs) {
    const payload = await fetchBars(
        currentCode,
        alignToCurrentInterval(fromTs),
        alignToCurrentInterval(toTs),
        null,
        { allowNotFound: true },
    );
    return normalizeBarsArray(Array.isArray(payload.bars) ? payload.bars : []);
}

function rebuildMorphSummaryPointsCache() {
    const countByDay = new Map();
    for (const [dayKey, events] of morphEventsByDay) {
        const count = Array.isArray(events) ? events.length : 0;
        if (count > 0) {
            countByDay.set(Number(dayKey), count);
        }
    }
    morphSummaryPointsCache = Array.from(countByDay.entries())
        .map(([time, value]) => ({ time: Number(time), value: Number(value) }))
        .sort((a, b) => a.time - b.time);
}

function getMorphSummaryPoints() {
    return morphSummaryPointsCache;
}

async function loadMorphWindowSignals(replace = true) {
    if (!shouldUseMorphBarWindow()) {
        return;
    }
    const levelKey = getMorphPrimarySignalKey();
    if (!levelKey || !["level1", "level2", "level3"].includes(levelKey)) {
        return;
    }
    const range = getMorphWindowRangeTimestamps();
    if (!range) {
        return;
    }
    try {
        const payload = await fetchMorphCandlestick(
            currentCode,
            levelKey,
            range.fromTs,
            range.toTs,
            MORPH_WINDOW_MAX_BARS,
        );
        applyMorphCandlestickPayload(payload, levelKey, { merge: !replace });
    } catch (err) {
        if (replace) {
            morphPatternPointsByName.clear();
            morphEventsByDay.clear();
            morphLoadedLevelKey = levelKey;
            morphSummaryPointsCache = [];
        }
    }
}

async function applyMorphWindowBarsAndSignals(rawBars, options = {}) {
    const { replaceSignals = true, skipViewportReset = false } = options;
    replaceMorphBarsWindow(rawBars);
    if (replaceSignals) {
        await loadMorphWindowSignals(true);
    }
    await refreshChartOverlays();
    renderChartData();
    renderMorphSignalData();
    await refreshBacktestOrderMarkers();
    updateSignalCaptionTitle();
    if (skipViewportReset) {
        clearMorphPatternOverlay(false);
        redrawMorphPatternOverlayAtCachedTime();
        return;
    }
    const maxIndex = barsCache.length - 1;
    if (maxIndex < 0) {
        return;
    }
    const span = Math.min(100, MORPH_WINDOW_MAX_VISIBLE_BARS, maxIndex + 1);
    suppressMorphWindowEdgeCheck();
    setMainChartVisibleLogicalRange({
        from: Math.max(-0.5, maxIndex - span * 0.8),
        to: maxIndex + span * 0.2,
    });
    clearMorphPatternOverlay(false);
    redrawMorphPatternOverlayAtCachedTime();
}

async function preloadMorphWindowOlder() {
    if (!shouldUseMorphBarWindow() || historyExhausted || morphWindowShiftInFlight || isRequesting) {
        return;
    }
    if (morphWindowPreloadDirection === "older" && morphWindowPreloadedBars) {
        return;
    }
    const firstTime = getFirstBarTime();
    if (firstTime === null) {
        return;
    }
    const toTs = alignToCurrentInterval(firstTime - getIntervalConfig().alignStepSeconds);
    if (lastHistoryRequestTo !== null && toTs >= lastHistoryRequestTo) {
        return;
    }
    try {
        const fetched = await fetchMorphWindowOlderIncoming(firstTime);
        if (!fetched.incoming.length) {
            return;
        }
        morphWindowPreloadedBars = fetched.incoming;
        morphWindowPreloadDirection = "older";
    } catch (err) {
        // ignore preload errors
    }
}

async function preloadMorphWindowNewer() {
    if (!shouldUseMorphBarWindow() || morphWindowAtLatest || morphWindowShiftInFlight) {
        return;
    }
    if (morphWindowPreloadDirection === "newer" && morphWindowPreloadedBars) {
        return;
    }
    if (!barsCache.length) {
        return;
    }
    const lastTime = Number(barsCache[barsCache.length - 1].time);
    const fromTs = alignToCurrentInterval(lastTime + getIntervalConfig().alignStepSeconds);
    const nowTs = alignToCurrentInterval(Math.floor(Date.now() / 1000));
    if (fromTs >= nowTs) {
        morphWindowAtLatest = true;
        return;
    }
    try {
        const incoming = await fetchMorphWindowBarsByTimeRange(fromTs, nowTs);
        if (!incoming.length) {
            return;
        }
        morphWindowPreloadedBars = trimMorphShiftBatchNewer(incoming);
        morphWindowPreloadDirection = "newer";
    } catch (err) {
        // ignore preload errors
    }
}

async function shiftMorphWindowOlder() {
    if (!shouldUseMorphBarWindow() || morphWindowShiftInFlight || historyExhausted || isRequesting) {
        return;
    }
    const firstBarTime = getFirstBarTime();
    if (firstBarTime === null) {
        return;
    }
    const toTs = alignToCurrentInterval(firstBarTime - getIntervalConfig().alignStepSeconds);
    if (!Number.isFinite(toTs) || toTs <= 0) {
        historyExhausted = true;
        setFactorHint("形态窗口：已无更早日线");
        applyMorphMainChartTimeScaleOptions();
        return;
    }
    if (lastHistoryRequestTo !== null && toTs >= lastHistoryRequestTo) {
        return;
    }

    morphWindowShiftInFlight = true;
    lastHistoryRequestTo = toTs;
    const visibleBefore = chart.timeScale().getVisibleLogicalRange();
    const anchorTime = firstBarTime;
    const anchorIndexBefore = 0;
    let rangeFromTs = null;
    let rangeToTs = null;
    try {
        let incoming = [];
        if (morphWindowPreloadDirection === "older" && Array.isArray(morphWindowPreloadedBars)) {
            incoming = filterMorphBarsStrictlyBefore(morphWindowPreloadedBars, firstBarTime);
        } else {
            const fetched = await fetchMorphWindowOlderIncoming(firstBarTime);
            if (fetched.invalidBoundary) {
                historyExhausted = true;
                setFactorHint("形态窗口：已无更早日线");
                applyMorphMainChartTimeScaleOptions();
                return;
            }
            incoming = fetched.incoming;
            rangeFromTs = fetched.fromTs;
            rangeToTs = fetched.toTs;
        }
        morphWindowPreloadedBars = null;
        morphWindowPreloadDirection = "";

        if (!incoming.length) {
            historyExhausted = true;
            setFactorHint("形态窗口：已无更早日线");
            applyMorphMainChartTimeScaleOptions();
            return;
        }

        const nextBars = mergeMorphWindowOlderIncoming(incoming, firstBarTime);
        if (!nextBars || Number(nextBars[0].time) >= Number(firstBarTime)) {
            lastHistoryRequestTo = null;
            logUiHint("形态窗口：未能向前扩展，请稍后再试");
            return;
        }

        historyExhausted = false;
        morphWindowAtLatest = false;
        morphWindowLastShiftAt = Date.now();
        setFactorHint("形态窗口加载更早历史...");
        await applyMorphWindowBarsAndSignals(nextBars, {
            replaceSignals: true,
            skipViewportReset: true,
        });
        if (!preserveMorphViewportAfterBarShift(anchorTime, anchorIndexBefore, visibleBefore)) {
            setMorphWindowVisibleRangeAfterShiftOlder(getMorphWindowVisibleSpan(visibleBefore));
        }
        if (rangeFromTs !== null && rangeToTs !== null) {
            void backfillMorphSignalsForRange(rangeFromTs, rangeToTs);
        }
    } catch (err) {
        lastHistoryRequestTo = null;
        const message = err instanceof Error ? err.message : "历史加载失败";
        logUiHint(`形态窗口: ${message}`);
    } finally {
        morphWindowShiftInFlight = false;
    }
}

async function shiftMorphWindowNewer() {
    if (!shouldUseMorphBarWindow() || morphWindowShiftInFlight || morphWindowAtLatest) {
        return;
    }
    morphWindowShiftInFlight = true;
    const visibleBefore = chart.timeScale().getVisibleLogicalRange();
    const anchorTime = lastBarTime;
    const anchorIndexBefore = barsCache.length > 0 ? barsCache.length - 1 : 0;
    try {
        let newerBars = null;
        if (morphWindowPreloadDirection === "newer" && Array.isArray(morphWindowPreloadedBars)) {
            newerBars = morphWindowPreloadedBars;
        } else if (barsCache.length) {
            const lastTime = Number(barsCache[barsCache.length - 1].time);
            const fromTs = alignToCurrentInterval(lastTime + getIntervalConfig().alignStepSeconds);
            const nowTs = alignToCurrentInterval(Math.floor(Date.now() / 1000));
            newerBars = trimMorphShiftBatchNewer(
                await fetchMorphWindowBarsByTimeRange(fromTs, nowTs),
            );
        }
        morphWindowPreloadedBars = null;
        morphWindowPreloadDirection = "";
        const nextBars = buildMorphWindowBarsByAppend(newerBars);
        if (!nextBars) {
            morphWindowAtLatest = true;
            return;
        }
        const oldLastTime = anchorTime;
        if (!Number.isFinite(oldLastTime) || Number(nextBars[nextBars.length - 1].time) <= Number(oldLastTime)) {
            morphWindowAtLatest = true;
            return;
        }
        morphWindowLastShiftAt = Date.now();
        setFactorHint("形态窗口加载更新历史...");
        await applyMorphWindowBarsAndSignals(nextBars, {
            replaceSignals: true,
            skipViewportReset: true,
        });
        if (!preserveMorphViewportAfterBarShift(anchorTime, anchorIndexBefore, visibleBefore)) {
            setMorphWindowVisibleRangeAfterShiftNewer(getMorphWindowVisibleSpan(visibleBefore));
        }
    } finally {
        morphWindowShiftInFlight = false;
    }
}

function isNearNewestVisibleBar(logicalRangeOverride) {
    if (lastBarTime === null || !barsCache.length) {
        return false;
    }
    if (logicalRangeOverride) {
        return isMorphLogicalRangeNearLatest(logicalRangeOverride);
    }
    const timeRange = chart.timeScale().getVisibleRange();
    if (timeRange && timeRange.to !== undefined) {
        const rightVisibleTime = Number(timeRange.to);
        if (Number.isFinite(rightVisibleTime)) {
            const threshold = getIntervalConfig().leftEdgePreloadThresholdSeconds;
            return Number(lastBarTime) - rightVisibleTime <= threshold;
        }
    }
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (!logicalRange) {
        return false;
    }
    return isMorphLogicalRangeNearLatest(logicalRange);
}

function isMorphWindowAtHardLeftEdge() {
    const firstBarTime = getFirstBarTime();
    if (firstBarTime === null) {
        return false;
    }
    const timeRange = chart.timeScale().getVisibleRange();
    if (!timeRange || timeRange.from === undefined) {
        return false;
    }
    const leftVisibleTime = Number(timeRange.from);
    if (!Number.isFinite(leftVisibleTime)) {
        return false;
    }
    return leftVisibleTime <= Number(firstBarTime) + getIntervalConfig().alignStepSeconds;
}

function isMorphWindowAtHardRightEdge() {
    if (lastBarTime === null) {
        return false;
    }
    const timeRange = chart.timeScale().getVisibleRange();
    if (!timeRange || timeRange.to === undefined) {
        return false;
    }
    const rightVisibleTime = Number(timeRange.to);
    if (!Number.isFinite(rightVisibleTime)) {
        return false;
    }
    return rightVisibleTime >= Number(lastBarTime) - getIntervalConfig().alignStepSeconds;
}

async function handleMorphWindowEdgeFromViewport() {
    if (!shouldUseMorphBarWindow() || isMorphWindowEdgeCheckSuppressed() || !barsCache.length) {
        return;
    }
    if (Date.now() - morphWindowLastShiftAt < MORPH_WINDOW_EDGE_SUPPRESS_MS) {
        return;
    }
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (!logicalRange) {
        return;
    }
    const span = getMorphWindowVisibleSpan(logicalRange);

    const maxIndex = barsCache.length - 1;

    if (historyExhausted && logicalRange.from < -0.5) {
        clampMorphWindowToLeftEdge(span);
        return;
    }

    const atLeftShiftEdge = isMorphWindowLogicalAtLeftShiftEdge(logicalRange);
    const atRightShiftEdge = isMorphWindowLogicalAtRightShiftEdge(logicalRange, maxIndex);

    if (!historyExhausted && atLeftShiftEdge) {
        if (shouldDeferMorphWindowShift(logicalRange)) {
            void preloadMorphWindowOlder();
            return;
        }
        await shiftMorphWindowOlder();
        return;
    }
    if (!historyExhausted && logicalRange.from <= MORPH_WINDOW_PRELOAD_EDGE_BARS) {
        void preloadMorphWindowOlder();
    }

    if (isNearNewestVisibleBar(logicalRange)) {
        if (clampMorphWindowPastRightEdge(logicalRange, span)) {
            return;
        }
    } else if (atRightShiftEdge) {
        if (shouldDeferMorphWindowShift(logicalRange)) {
            void preloadMorphWindowNewer();
            return;
        }
        await shiftMorphWindowNewer();
        return;
    } else if (logicalRange.to >= maxIndex - MORPH_WINDOW_PRELOAD_EDGE_BARS) {
        void preloadMorphWindowNewer();
    }
}

function scheduleMorphWindowEdgeCheck() {
    if (!shouldUseMorphBarWindow() || isMorphWindowEdgeCheckSuppressed()) {
        return;
    }
    cancelMorphWindowEdgeCheckTimer();
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    const maxIndex = barsCache.length - 1;
    const atShiftEdge = Boolean(
        logicalRange && (
            (historyExhausted && logicalRange.from < -0.5)
            || (!historyExhausted && isMorphWindowLogicalAtLeftShiftEdge(logicalRange))
            || (!isNearNewestVisibleBar(logicalRange) && isMorphWindowLogicalAtRightShiftEdge(logicalRange, maxIndex))
        ),
    );
    const delay = atShiftEdge ? 60 : MORPH_WINDOW_EDGE_CHECK_SETTLE_MS;
    morphWindowEdgeCheckTimer = setTimeout(() => {
        morphWindowEdgeCheckTimer = null;
        void handleMorphWindowEdgeFromViewport();
    }, delay);
}

function bindMorphWindowChartInteractionGuard() {
    if (!container || container.dataset.morphWindowGuardBound === "1") {
        return;
    }
    container.dataset.morphWindowGuardBound = "1";
    container.addEventListener("pointerdown", () => {
        if (!shouldUseMorphBarWindow()) {
            return;
        }
        morphWindowChartInteracting = true;
        cancelMorphWindowEdgeCheckTimer();
    });
    const onPointerEnd = () => {
        if (!shouldUseMorphBarWindow()) {
            return;
        }
        morphWindowChartInteracting = false;
        syncMorphWindowAtLatestFromViewport();
        syncMorphViewportLogicalRangeClamp();
        scheduleMorphWindowEdgeCheck();
    };
    container.addEventListener("pointerup", onPointerEnd);
    container.addEventListener("pointercancel", onPointerEnd);
    window.addEventListener("pointerup", onPointerEnd);
    window.addEventListener("pointercancel", onPointerEnd);
}

function getActiveMorphSignalKeys() {
    return MORPH_PANEL_OPTION_KEYS.filter((key) => morphPanelState[key]);
}

function getMorphSignalLabel(key) {
    return MORPH_SIGNAL_LABELS[key] || String(key || "");
}

function getMorphPrimarySignalKey(activeKeys = getMorphActiveLevelKeys()) {
    if (!activeKeys.length) {
        return "";
    }
    return activeKeys.slice().sort().join("+");
}

function getMorphSignalPoints(key) {
    return morphSignalPointsByKey.get(String(key || "")) || [];
}

function getMorphPatternSeriesColor(name, patternNames = []) {
    const names = patternNames.length ? patternNames : Array.from(morphPatternPointsByName.keys());
    const idx = Math.max(0, names.indexOf(name));
    return SIGNAL_SERIES_COLORS[idx % SIGNAL_SERIES_COLORS.length];
}

function getMorphPatternDisplayName(signalName) {
    const key = String(signalName || "").trim();
    if (!key) {
        return "";
    }
    return MORPH_PATTERN_NAME_ZH[key] || key;
}

function redrawMorphPatternOverlayAtCachedTime() {
    if (!isMorphSignalTab()) {
        return;
    }
    const cachedTime = morphOverlayLastChartTime;
    if (cachedTime === undefined || cachedTime === null) {
        return;
    }
    morphOverlayLastChartTime = null;
    drawMorphPatternOverlayForDay(cachedTime);
}

function cancelMorphOverlayViewportRedraw() {
    if (morphOverlayViewportRafId) {
        cancelAnimationFrame(morphOverlayViewportRafId);
        morphOverlayViewportRafId = 0;
    }
}

function scheduleMorphOverlayViewportRedraw() {
    if (!isMorphSignalTab() || morphOverlayViewportRafId) {
        return;
    }
    morphOverlayViewportRafId = requestAnimationFrame(() => {
        morphOverlayViewportRafId = 0;
        redrawMorphPatternOverlayAtCachedTime();
    });
}

function scheduleMorphSignalRenderAfterBackfill() {
    if (morphBackfillRenderTimer) {
        clearTimeout(morphBackfillRenderTimer);
    }
    morphBackfillRenderTimer = setTimeout(() => {
        morphBackfillRenderTimer = null;
        renderMorphSignalData();
        updateSignalCaptionTitle();
        clearMorphPatternOverlay(false);
        redrawMorphPatternOverlayAtCachedTime();
        if (morphBackfillInFlight <= 0) {
            const label = getMorphActiveLevelKeys().map((key) => getMorphSignalLabel(key)).join(" / ");
            setFactorHint(`形态面 ${label} 历史区间已更新`);
        }
    }, MORPH_BACKFILL_RENDER_COALESCE_MS);
}

function clearMorphPatternLineSeries(name) {
    const series = morphPatternLineSeriesByName.get(name);
    if (series) {
        signalChart.removeSeries(series);
        morphPatternLineSeriesByName.delete(name);
    }
}

function ensureMorphPatternLineSeries(name) {
    if (morphPatternLineSeriesByName.has(name)) {
        return morphPatternLineSeriesByName.get(name);
    }
    const series = signalChart.addSeries(LightweightCharts.LineSeries, {
        priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
        priceScaleId: "right",
        color: getMorphPatternSeriesColor(name),
        lineWidth: 2,
        crosshairMarkerVisible: false
    });
    morphPatternLineSeriesByName.set(name, series);
    return series;
}

function clearAllMorphPatternLineSeries() {
    for (const name of Array.from(morphPatternLineSeriesByName.keys())) {
        clearMorphPatternLineSeries(name);
    }
}

function morphEventDedupeKey(event) {
    const timeKey = alignToCurrentInterval(Number(event && event.time));
    const startKey = alignToCurrentInterval(Number(event && event.start_time || event && event.time));
    return `${timeKey}|${String(event && event.signal_name || "")}|${startKey}`;
}

function mergeMorphEventsIntoByDay(incomingEvents) {
    for (const event of incomingEvents) {
        const dayKey = alignToCurrentInterval(Number(event && event.time));
        if (!Number.isFinite(dayKey)) {
            continue;
        }
        if (!morphEventsByDay.has(dayKey)) {
            morphEventsByDay.set(dayKey, []);
        }
        const list = morphEventsByDay.get(dayKey);
        const dedupeKey = morphEventDedupeKey(event);
        if (list.some((item) => morphEventDedupeKey(item) === dedupeKey)) {
            continue;
        }
        list.push(event);
    }
}

function applyMorphCandlestickPayload(payload, levelKey, options = {}) {
    const merge = Boolean(options && options.merge);
    const patterns = payload && typeof payload.patterns === "object" ? payload.patterns : {};
    const events = Array.isArray(payload && payload.events) ? payload.events : [];
    if (merge) {
        for (const [name, points] of Object.entries(patterns)) {
            if (!Array.isArray(points) || !points.length) {
                continue;
            }
            const key = String(name);
            const existing = morphPatternPointsByName.get(key) || [];
            morphPatternPointsByName.set(key, mergeFactorPoints(existing, points));
        }
        mergeMorphEventsIntoByDay(events);
        morphLoadedLevelKey = String(levelKey || morphLoadedLevelKey);
        rebuildMorphSummaryPointsCache();
        return;
    }
    morphPatternPointsByName.clear();
    for (const [name, points] of Object.entries(patterns)) {
        morphPatternPointsByName.set(String(name), Array.isArray(points) ? points : []);
    }
    morphEventsByDay.clear();
    for (const event of events) {
        const dayKey = alignToCurrentInterval(Number(event && event.time));
        if (!Number.isFinite(dayKey)) {
            continue;
        }
        if (!morphEventsByDay.has(dayKey)) {
            morphEventsByDay.set(dayKey, []);
        }
        morphEventsByDay.get(dayKey).push(event);
    }
    morphLoadedLevelKey = String(levelKey || "");
    rebuildMorphSummaryPointsCache();
}

function ensureMorphPatternOverlayCanvas() {
    if (!isMorphSignalTab() || !container) {
        return null;
    }
    if (!morphOverlayCanvas) {
        morphOverlayCanvas = document.createElement("canvas");
        morphOverlayCanvas.id = "morph-pattern-overlay";
        morphOverlayCanvas.className = "morph-pattern-overlay";
        morphOverlayCanvas.style.position = "absolute";
        morphOverlayCanvas.style.left = "0";
        morphOverlayCanvas.style.top = "0";
        morphOverlayCanvas.style.width = "100%";
        morphOverlayCanvas.style.height = "100%";
        morphOverlayCanvas.style.pointerEvents = "none";
        morphOverlayCanvas.style.zIndex = "4";
        if (!container.style.position) {
            container.style.position = "relative";
        }
        container.appendChild(morphOverlayCanvas);
        morphOverlayCtx = morphOverlayCanvas.getContext("2d");
    }
    resizeMorphPatternOverlayCanvas();
    return morphOverlayCanvas;
}

function resizeMorphPatternOverlayCanvas() {
    if (!morphOverlayCanvas || !container) {
        return;
    }
    const width = Math.max(1, container.clientWidth);
    const height = Math.max(1, container.clientHeight);
    morphOverlayCanvas.width = width;
    morphOverlayCanvas.height = height;
    morphOverlayCanvas.style.width = `${width}px`;
    morphOverlayCanvas.style.height = `${height}px`;
}

function clearMorphPatternOverlay(resetLast = true) {
    if (resetLast) {
        morphOverlayLastChartTime = null;
    }
    if (!morphOverlayCtx || !morphOverlayCanvas) {
        return;
    }
    morphOverlayCtx.clearRect(0, 0, morphOverlayCanvas.width, morphOverlayCanvas.height);
}

function findBarIndexByUnixTime(unixSec) {
    const aligned = alignToCurrentInterval(Number(unixSec));
    if (!Number.isFinite(aligned)) {
        return -1;
    }
    ensureBarsDayIndexMap();
    const idx = barsDayIndexMap.get(aligned);
    return idx === undefined ? -1 : idx;
}

function getBarRangeEnvelope(startIdx, endIdx) {
    const from = Math.min(startIdx, endIdx);
    const to = Math.max(startIdx, endIdx);
    let high = -Infinity;
    let low = Infinity;
    for (let i = from; i <= to; i += 1) {
        const bar = barsCache[i];
        if (!bar) {
            continue;
        }
        high = Math.max(high, Number(bar.high));
        low = Math.min(low, Number(bar.low));
    }
    if (!Number.isFinite(high) || !Number.isFinite(low)) {
        return null;
    }
    return { high, low };
}

const MORPH_OVERLAY_NEAR_DAY_RADIUS = 5;
const MORPH_OVERLAY_MAX_LABELS_PER_DAY = 8;
const MORPH_OVERLAY_MIN_BOX_WIDTH_FOR_LABEL = 16;
const MORPH_OVERLAY_LABEL_FONT_PX = 22;

function getBarPixelHalfWidth(barIndex) {
    const timeScale = chart.timeScale();
    const x = timeScale.timeToCoordinate(toChartTime(barsCache[barIndex].time));
    if (!Number.isFinite(x)) {
        return 4;
    }
    let half = 4;
    if (barIndex + 1 < barsCache.length) {
        const xNext = timeScale.timeToCoordinate(toChartTime(barsCache[barIndex + 1].time));
        if (Number.isFinite(xNext)) {
            half = Math.max(half, Math.abs(xNext - x) * 0.5);
        }
    }
    if (barIndex > 0) {
        const xPrev = timeScale.timeToCoordinate(toChartTime(barsCache[barIndex - 1].time));
        if (Number.isFinite(xPrev)) {
            half = Math.max(half, Math.abs(x - xPrev) * 0.5);
        }
    }
    return half;
}

function getMorphBoxHorizontalSpan(startIdx, endIdx, timeScale) {
    const fromIdx = Math.min(startIdx, endIdx);
    const toIdx = Math.max(startIdx, endIdx);
    const xStart = timeScale.timeToCoordinate(toChartTime(barsCache[fromIdx].time));
    const xEnd = timeScale.timeToCoordinate(toChartTime(barsCache[toIdx].time));
    if (!Number.isFinite(xStart) || !Number.isFinite(xEnd)) {
        return null;
    }
    return {
        left: xStart - getBarPixelHalfWidth(fromIdx),
        right: xEnd + getBarPixelHalfWidth(toIdx),
    };
}

function getMorphOverlayOpacityByBarOffset(barOffset) {
    const d = Math.abs(Math.round(Number(barOffset)));
    if (!Number.isFinite(d) || d >= MORPH_OVERLAY_NEAR_DAY_RADIUS) {
        return 0;
    }
    return 0.5 - d * 0.1;
}

function collectMorphOverlayItems(crossBarIndex) {
    const items = [];
    const from = Math.max(0, crossBarIndex - MORPH_OVERLAY_NEAR_DAY_RADIUS);
    const to = Math.min(barsCache.length - 1, crossBarIndex + MORPH_OVERLAY_NEAR_DAY_RADIUS);
    for (let barIdx = from; barIdx <= to; barIdx += 1) {
        const dayKey = alignToCurrentInterval(Number(barsCache[barIdx].time));
        const events = morphEventsByDay.get(dayKey) || [];
        for (const event of events) {
            const eventBarIndex = findBarIndexByUnixTime(event.time);
            const startIdx = findBarIndexByUnixTime(event.start_time || event.time);
            if (eventBarIndex < 0 || startIdx < 0) {
                continue;
            }
            const offset = Math.abs(eventBarIndex - crossBarIndex);
            const opacity = getMorphOverlayOpacityByBarOffset(offset);
            if (opacity <= 0) {
                continue;
            }
            items.push({ event, opacity, barOffset: offset, eventBarIndex });
        }
    }
    items.sort((a, b) => b.barOffset - a.barOffset);
    return items;
}

function drawMorphPatternOverlayLabel(ctx, text, centerX, topY, color, opacity) {
    const label = getMorphPatternDisplayName(text);
    if (!label || !Number.isFinite(centerX) || !Number.isFinite(topY)) {
        return;
    }
    const fontSize = MORPH_OVERLAY_LABEL_FONT_PX;
    ctx.font = `${fontSize}px sans-serif`;
    ctx.textBaseline = "bottom";
    const paddingX = 8;
    const paddingY = 4;
    const textWidth = ctx.measureText(label).width;
    const boxWidth = textWidth + paddingX * 2;
    const boxHeight = fontSize + paddingY * 2;
    const left = centerX - boxWidth / 2;
    const bottom = topY;
    const top = bottom - boxHeight;
    ctx.fillStyle = colorWithAlpha("#0f172a", opacity * 0.82);
    ctx.strokeStyle = colorWithAlpha(color, Math.min(1, opacity + 0.1));
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(left, top, boxWidth, boxHeight, 4);
    } else {
        ctx.rect(left, top, boxWidth, boxHeight);
    }
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = colorWithAlpha(color, Math.min(1, opacity + 0.2));
    ctx.fillText(label, left + paddingX, bottom - paddingY);
}

function drawMorphPatternOverlayForDay(chartTime) {
    if (!isMorphSignalTab()) {
        clearMorphPatternOverlay();
        return;
    }
    if (chartTime === undefined || chartTime === null) {
        clearMorphPatternOverlay();
        return;
    }
    if (morphOverlayLastChartTime === chartTime) {
        return;
    }
    ensureMorphPatternOverlayCanvas();
    clearMorphPatternOverlay(false);
    morphOverlayLastChartTime = chartTime;
    if (!morphOverlayCtx || !barsCache.length) {
        return;
    }
    const crossBarIndex = findBarIndexByChartTime(chartTime);
    if (crossBarIndex < 0) {
        return;
    }
    const levelKey = getMorphPrimarySignalKey();
    const patternNames = levelKey && morphLoadedLevelKey === levelKey
        ? Array.from(morphPatternPointsByName.keys()).sort()
        : [];
    const overlayItems = collectMorphOverlayItems(crossBarIndex);
    if (!overlayItems.length) {
        return;
    }
    const timeScale = chart.timeScale();
    const labelCountByDay = new Map();
    overlayItems.forEach((item, idx) => {
        const { event, opacity } = item;
        const endIdx = findBarIndexByUnixTime(event.time);
        const startIdx = findBarIndexByUnixTime(event.start_time || event.time);
        if (endIdx < 0 || startIdx < 0) {
            return;
        }
        const envelope = getBarRangeEnvelope(startIdx, endIdx);
        if (!envelope) {
            return;
        }
        const signalName = String(event.signal_name || "");
        const color = getMorphPatternSeriesColor(signalName, patternNames);
        const span = getMorphBoxHorizontalSpan(startIdx, endIdx, timeScale);
        if (!span) {
            return;
        }
        const yHigh = candlestickSeries.priceToCoordinate(envelope.high);
        const yLow = candlestickSeries.priceToCoordinate(envelope.low);
        if (!Number.isFinite(yHigh) || !Number.isFinite(yLow)) {
            return;
        }
        const stackShift = idx % 3;
        const left = Math.min(span.left, span.right) - stackShift;
        const right = Math.max(span.left, span.right) + stackShift;
        const top = Math.min(yHigh, yLow) - 2;
        const bottom = Math.max(yHigh, yLow) + 2;
        const boxWidth = Math.max(2, right - left);
        const boxHeight = Math.max(2, bottom - top);
        morphOverlayCtx.lineWidth = 1;
        morphOverlayCtx.strokeStyle = colorWithAlpha(color, Math.min(1, opacity + 0.12));
        morphOverlayCtx.fillStyle = colorWithAlpha(color, opacity);
        morphOverlayCtx.fillRect(left, top, boxWidth, boxHeight);
        morphOverlayCtx.strokeRect(left, top, boxWidth, boxHeight);

        const dayKey = alignToCurrentInterval(Number(event.time));
        const labelCount = labelCountByDay.get(dayKey) || 0;
        if (
            boxWidth >= MORPH_OVERLAY_MIN_BOX_WIDTH_FOR_LABEL
            && labelCount < MORPH_OVERLAY_MAX_LABELS_PER_DAY
        ) {
            labelCountByDay.set(dayKey, labelCount + 1);
            const labelY = top - 6 - labelCount * 30;
            drawMorphPatternOverlayLabel(
                morphOverlayCtx,
                signalName,
                (left + right) / 2,
                labelY,
                color,
                opacity,
            );
        }
    });
}

async function backfillMorphSignalsForRange(fromTs, toTs) {
    if (currentInterval !== "1day" || isYkrsCode() || !isMorphSignalTab()) {
        return;
    }
    const levelKeys = getMorphActiveLevelKeys();
    if (!levelKeys.length) {
        return;
    }
    if (!Number.isFinite(fromTs) || !Number.isFinite(toTs) || fromTs > toTs) {
        return;
    }
    const daySpan = Math.ceil((Number(toTs) - Number(fromTs)) / 86400) + 5;
    const fetchLimit = Math.min(
        FACTOR_FETCH_LIMIT_MAX,
        Math.max(300, daySpan),
    );
    morphBackfillInFlight += 1;
    if (morphBackfillInFlight === 1) {
        setFactorHint("形态历史数据加载中...");
    }
    try {
        for (const levelKey of levelKeys) {
            const payload = await fetchMorphCandlestick(
                currentCode,
                levelKey,
                fromTs,
                toTs,
                fetchLimit,
            );
            applyMorphCandlestickPayload(payload, getMorphPrimarySignalKey(), { merge: true });
        }
        scheduleMorphSignalRenderAfterBackfill();
    } catch (err) {
        // 区间补数失败不打断主图历史加载
    } finally {
        morphBackfillInFlight = Math.max(0, morphBackfillInFlight - 1);
    }
}

async function fetchMorphCandlestick(code, level, fromTs, toTs, limitValue = FACTOR_FETCH_LIMIT_INITIAL, options = {}) {
    const params = new URLSearchParams({
        code: String(code || "").trim(),
        level: String(level || "").trim(),
        from: String(fromTs),
        to: String(toTs),
        limit: String(limitValue),
    });
    const fields = options && options.fields ? String(options.fields).trim() : "";
    if (fields) {
        params.set("fields", fields);
    }
    const url = `${API_BASE_URL}/api/market/morph-candlestick?${params.toString()}`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        if (isNoDataErrorResponse(resp.status, body)) {
            return { patterns: {}, events: [], meta: { row_count: 0, pattern_count: 0, event_count: 0 } };
        }
        const message = body && body.error && body.error.message ? body.error.message : "形态信号获取失败";
        throw new Error(message);
    }
    return body;
}

async function refreshMorphSignalData(isInitialLoad = false) {
    if (!isMorphSignalTab()) {
        return;
    }
    if (morphBackfillRenderTimer) {
        clearTimeout(morphBackfillRenderTimer);
        morphBackfillRenderTimer = null;
    }
    morphBackfillInFlight = 0;
    if (isYkrsCode() || currentInterval !== "1day") {
        morphPatternPointsByName.clear();
        morphEventsByDay.clear();
        morphLoadedLevelKey = "";
        renderMorphSignalData();
        updateSignalCaptionTitle();
        setFactorHint(currentInterval !== "1day" ? "形态面仅在日线周期可用" : "YKRS 标的不请求形态信号");
        return;
    }
    const levelKeys = getMorphActiveLevelKeys();
    const compoundKey = getMorphPrimarySignalKey(levelKeys);
    if (!compoundKey) {
        morphPatternPointsByName.clear();
        morphEventsByDay.clear();
        morphLoadedLevelKey = "";
        morphSummaryPointsCache = [];
        renderMorphSignalData();
        updateSignalCaptionTitle();
        return;
    }
    if (compoundKey !== morphLoadedLevelKey) {
        morphPatternPointsByName.clear();
        morphEventsByDay.clear();
        morphSummaryPointsCache = [];
        clearMorphPatternOverlay(true);
    }
    const { fromTs, toTs } = computeSignalRangeFromBars();
    try {
        if (!isInitialLoad) {
            setFactorHint("形态数据加载中...");
        }
        for (let i = 0; i < levelKeys.length; i += 1) {
            const levelKey = levelKeys[i];
            const payload = await fetchMorphCandlestick(
                currentCode,
                levelKey,
                fromTs,
                toTs,
                computeSignalInitialLimit(),
            );
            applyMorphCandlestickPayload(payload, compoundKey, { merge: i > 0 });
        }
        morphLoadedLevelKey = compoundKey;
        renderMorphSignalData();
        updateSignalCaptionTitle();
        clearMorphPatternOverlay(false);
        redrawMorphPatternOverlayAtCachedTime();
        const label = levelKeys.map((key) => getMorphSignalLabel(key)).join(" / ");
        setFactorHint(`形态面 ${label} | 窗口 ${barsCache.length} 日`);
    } catch (err) {
        morphPatternPointsByName.clear();
        morphEventsByDay.clear();
        morphLoadedLevelKey = "";
        renderMorphSignalData();
        updateSignalCaptionTitle();
        const message = err instanceof Error ? err.message : "形态信号刷新失败";
        setFactorHint(`形态信号刷新失败: ${message}`);
        logUiHint(message);
    }
}

function getMorphSignalSeriesColor(key, activeKeys = getActiveMorphSignalKeys()) {
    const idx = Math.max(0, activeKeys.indexOf(key));
    return SIGNAL_SERIES_COLORS[idx % SIGNAL_SERIES_COLORS.length];
}

function clearExtraMorphSignalSeries(key) {
    const series = extraMorphSignalSeriesByKey.get(key);
    if (series) {
        signalChart.removeSeries(series);
        extraMorphSignalSeriesByKey.delete(key);
    }
}

function ensureExtraMorphSignalSeries(key) {
    if (extraMorphSignalSeriesByKey.has(key)) {
        return extraMorphSignalSeriesByKey.get(key);
    }
    const series = signalChart.addSeries(LightweightCharts.LineSeries, {
        priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
        priceScaleId: "right",
        color: getMorphSignalSeriesColor(key),
        lineWidth: 2,
        crosshairMarkerVisible: false
    });
    extraMorphSignalSeriesByKey.set(key, series);
    return series;
}

function normalizeMorphPanelState(raw) {
    const next = { ...MORPH_PANEL_DEFAULT_STATE };
    if (!raw || typeof raw !== "object") {
        return next;
    }
    for (const key of MORPH_PANEL_OPTION_KEYS) {
        if (typeof raw[key] === "boolean") {
            next[key] = raw[key];
        }
    }
    const levelKeys = ["level1", "level2", "level3"];
    if (!levelKeys.some((key) => next[key])) {
        next.level3 = true;
    }
    return next;
}

function loadMorphPanelState() {
    try {
        const raw = localStorage.getItem(MORPH_PANEL_STORAGE_KEY);
        if (!raw) {
            return { ...MORPH_PANEL_DEFAULT_STATE };
        }
        return normalizeMorphPanelState(JSON.parse(raw));
    } catch {
        return { ...MORPH_PANEL_DEFAULT_STATE };
    }
}

function saveMorphPanelState() {
    try {
        localStorage.setItem(MORPH_PANEL_STORAGE_KEY, JSON.stringify(morphPanelState));
    } catch {
        /* ignore */
    }
}

function getMorphPanelState() {
    return { ...morphPanelState };
}

function applyMorphPanelStateToDom() {
    const listEl = document.getElementById("morph-panel-list");
    if (!listEl) {
        return;
    }
    listEl.querySelectorAll(".morph-panel-item[data-morph-key]").forEach((itemEl) => {
        const key = String(itemEl.dataset.morphKey || "");
        const active = Boolean(morphPanelState[key]);
        itemEl.classList.toggle("active", active);
        itemEl.setAttribute("aria-pressed", active ? "true" : "false");
    });
}

function toggleMorphPanelOption(key) {
    if (!MORPH_PANEL_OPTION_KEYS.includes(key)) {
        return;
    }
    const itemEl = document.querySelector(`.morph-panel-item[data-morph-key="${key}"]`);
    const group = itemEl ? String(itemEl.dataset.morphGroup || "") : "";
    const nextActive = !morphPanelState[key];
    if (group === MORPH_PANEL_LEVEL_GROUP) {
        morphPanelState[key] = nextActive;
        const levelKeys = ["level1", "level2", "level3"];
        if (nextActive === false && !levelKeys.some((levelKey) => morphPanelState[levelKey])) {
            morphPanelState.level3 = true;
        }
    } else {
        morphPanelState[key] = nextActive;
    }
    saveMorphPanelState();
    applyMorphPanelStateToDom();
    if (key === "channel" || key === "trend") {
        if (morphPanelState[key]) {
            logUiHint("通道 / 趋势线暂未接入");
        }
    }
    if (isMorphSignalTab()) {
        if (["level1", "level2", "level3"].includes(key)) {
            morphPatternPointsByName.clear();
            morphEventsByDay.clear();
            morphLoadedLevelKey = "";
            morphSummaryPointsCache = [];
            clearMorphPatternOverlay(true);
            clearAllMorphPatternLineSeries();
            void refreshMorphSignalData(true);
        } else {
            renderSignalData();
        }
        updateSignalCaptionTitle();
    }
}

function installMorphPanelUi() {
    morphPanelState = loadMorphPanelState();
    applyMorphPanelStateToDom();
    if (morphPanelUiBound || !rightPanelBody) {
        return;
    }
    rightPanelBody.addEventListener("click", (event) => {
        if (currentRightTabName !== "形态面") {
            return;
        }
        const itemEl = event.target instanceof Element ? event.target.closest(".morph-panel-item[data-morph-key]") : null;
        if (!itemEl || !rightPanelBody.contains(itemEl)) {
            return;
        }
        toggleMorphPanelOption(String(itemEl.dataset.morphKey || ""));
    });
    morphPanelUiBound = true;
}

window.getMorphPanelState = getMorphPanelState;
window.getMorphSignalPointsByKey = () => new Map(morphSignalPointsByKey);
window.setMorphSignalPoints = (key, points) => {
    const normalizedKey = String(key || "").trim();
    if (!normalizedKey) {
        return;
    }
    morphSignalPointsByKey.set(
        normalizedKey,
        Array.isArray(points) ? points : []
    );
    if (isMorphSignalTab()) {
        renderSignalData();
        updateSignalCaptionTitle();
    }
};

uiHintToastTimer = null;

function renderMorphSignalData() {
    for (const factorName of Array.from(extraSignalSeriesByFactor.keys())) {
        clearExtraSignalSeries(factorName);
    }
    for (const slotKey of Array.from(slotSignalSeriesByKey.keys())) {
        clearSlotSignalSeries(slotKey);
    }
    if (coupledSignalSeries) {
        coupledSignalSeries.setData([]);
    }

    for (const key of Array.from(extraMorphSignalSeriesByKey.keys())) {
        clearExtraMorphSignalSeries(key);
    }

    const levelKeys = getMorphActiveLevelKeys();
    const compoundKey = getMorphPrimarySignalKey(levelKeys);
    if (!compoundKey || morphLoadedLevelKey !== compoundKey) {
        clearAllMorphPatternLineSeries();
        signalSeries.setData([]);
        signalChart.priceScale("right").applyOptions({ autoScale: true });
        syncSignalChartViewportFromMain();
        return;
    }

    const patternNames = Array.from(morphPatternPointsByName.keys()).sort();
    if (!patternNames.length) {
        clearAllMorphPatternLineSeries();
        const summaryPoints = getMorphSummaryPoints();
        if (!summaryPoints.length) {
            signalSeries.setData([]);
            signalChart.priceScale("right").applyOptions({ autoScale: true });
            syncSignalChartViewportFromMain();
            return;
        }
        signalSeries.applyOptions({
            color: "#38bdf8",
            crosshairMarkerVisible: true,
        });
        signalSeries.setData(buildSignalSeriesData(summaryPoints));
        signalChart.priceScale("right").applyOptions({ autoScale: true });
        syncSignalChartViewportFromMain();
        return;
    }

    const primaryName = patternNames[0];
    signalSeries.applyOptions({
        color: getMorphPatternSeriesColor(primaryName, patternNames),
        crosshairMarkerVisible: true,
    });
    signalSeries.setData(buildSignalSeriesData(morphPatternPointsByName.get(primaryName) || []));

    for (const name of Array.from(morphPatternLineSeriesByName.keys())) {
        if (!patternNames.includes(name) || name === primaryName) {
            clearMorphPatternLineSeries(name);
        }
    }
    for (let i = 1; i < patternNames.length; i += 1) {
        const name = patternNames[i];
        const series = ensureMorphPatternLineSeries(name);
        series.applyOptions({
            color: getMorphPatternSeriesColor(name, patternNames),
            crosshairMarkerVisible: false,
        });
        series.setData(buildSignalSeriesData(morphPatternPointsByName.get(name) || []));
    }

    signalChart.priceScale("right").applyOptions({ autoScale: true });
    syncSignalChartViewportFromMain();
}

window.ChartBoardView = { id: "morph", label: "形态面" };
