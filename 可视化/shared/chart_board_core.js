/* 看板核心：K 线、API、自选股、布局（不含回测面板） */
/* 看板公共逻辑：K 线、API、自选股、回测、布局 */
function resolveApiBaseUrl() {
    try {
        const sp = new URLSearchParams(window.location.search);
        for (const key of ["api", "api_base"]) {
            const raw = (sp.get(key) || "").trim();
            if (!raw) {
                continue;
            }
            const normalized = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
            const u = new URL(normalized.endsWith("/") ? normalized : `${normalized}/`);
            if (u.protocol === "http:" || u.protocol === "https:") {
                return u.origin;
            }
        }
    } catch {
        /* ignore */
    }
    try {
        const ls = (localStorage.getItem("RESULTS_API_BASE") || localStorage.getItem("API_BASE_URL") || "").trim();
        if (ls) {
            const normalized = /^https?:\/\//i.test(ls) ? ls : `http://${ls}`;
            const u = new URL(normalized.endsWith("/") ? normalized : `${normalized}/`);
            if (u.protocol === "http:" || u.protocol === "https:") {
                return u.origin;
            }
        }
    } catch {
        /* ignore */
    }
    try {
        if (window.location.protocol === "http:" || window.location.protocol === "https:") {
            return `http://${window.location.hostname}:8000`;
        }
    } catch {
        /* ignore */
    }
    return "http://127.0.0.1:8000";
}


const PAGE_VIEW = String(window.PAGE_VIEW || "quant").trim().toLowerCase();
const PAGE_VIEW_LABELS = {
    quant: "量化因子",
    morph: "形态面",
    sentiment: "舆情面",
    fundamental: "基本面",
};
const PAGE_VIEW_TO_FILE = {
    quant: "../量化因子/index.html",
    morph: "../形态面/index.html",
    sentiment: "../舆情面/index.html",
    fundamental: "../基本面/index.html",
};
function getPageViewLabel() {
    return PAGE_VIEW_LABELS[PAGE_VIEW] || PAGE_VIEW;
}
function isMainBoardPage() {
    return Boolean(PAGE_VIEW_TO_FILE[PAGE_VIEW]);
}
function isFundamentalBoardPage() {
    return PAGE_VIEW === "fundamental";
}
function isSentimentBoardPage() {
    return PAGE_VIEW === "sentiment";
}
function isInfoBoardPage() {
    return isFundamentalBoardPage() || isSentimentBoardPage();
}
function isEmbedOnlyIndexSurface() {
    return !isMainBoardPage();
}
function getPrimaryRightTabLabel(codeValue) {
    const code = normalizeCodeValue(codeValue || (typeof currentCode !== "undefined" ? currentCode : ""));
    return code.endsWith(".YKRS") ? "组合详情" : "量化因子";
}
function shouldHideSignalChartPanel() {
    return isInfoBoardPage() || (PAGE_BOOT.allowYkrsCurve && typeof currentCode !== "undefined" && isMainChartLineMode());
}
function isYkrsCode(codeValue = "") {
    if (!codeValue && typeof currentCode !== "undefined") {
        codeValue = currentCode;
    }
    return normalizeCodeValue(codeValue).endsWith(".YKRS");
}
function isYkrsCurveDeniedOnThisSurface(codeValue = "") {
    if (!codeValue && typeof currentCode !== "undefined") {
        codeValue = currentCode;
    }
    return isYkrsCode(codeValue) && !PAGE_BOOT.allowYkrsCurve;
}
function renderRightPanelByTab(tabName) {
    const label = typeof getPrimaryRightTabLabel === "function" ? getPrimaryRightTabLabel() : "量化因子";
    currentRightTabName = String(tabName || label).trim();
    if (typeof rightPanelBody !== "undefined" && rightPanelBody && Object.prototype.hasOwnProperty.call(RIGHT_PANEL_TAB_CONTENT, currentRightTabName)) {
        rightPanelBody.innerHTML = RIGHT_PANEL_TAB_CONTENT[currentRightTabName];
    }
}
function applyPrimaryRightTabLabel() {
    if (typeof headerTabs === "undefined" || !headerTabs.length) {
        return;
    }
    const primary = headerTabs[0];
    if (primary) {
        primary.textContent = typeof getPrimaryRightTabLabel === "function" ? getPrimaryRightTabLabel() : "量化因子";
    }
}
function updateAdjustModeControlVisibility() {
    if (typeof adjustModeSelect !== "undefined" && adjustModeSelect) {
        adjustModeSelect.disabled = currentInterval === "1min";
        adjustModeSelect.hidden = currentInterval === "1min";
    }
}
function applyMorphMainChartTimeScaleOptions() {
    if (typeof chart !== "undefined" && chart) {
        chart.timeScale().applyOptions(TIME_SCALE_DATA_CLAMP);
    }
}
function updateMorphTimeScaleZoomLimits() { }
function syncMorphViewportLogicalRangeClamp() { }
function resizeMorphPatternOverlayCanvas() { }
function redrawMorphPatternOverlayAtCachedTime() { }
function clearAllMorphPatternLineSeries() { }
function syncMorphWindowAtLatestFromViewport() { }
function scheduleMorphWindowEdgeCheck() { }
function suppressMorphWindowEdgeCheck() { }
function isMorphWindowEdgeCheckSuppressed() { return false; }
function isMorphWindowLogicalAtLeftShiftEdge() { return false; }
async function preloadMorphWindowOlder() { }
async function preloadMorphWindowNewer() { }
function syncActiveRunFromUrl() { }
function installRightPanelModelOverlayHandlers() { }
function initViewForCurrentPage() {
    if (!isMainBoardPage()) {
        return Promise.resolve();
    }
    currentRightTabName = getPageViewLabel();
    if (PAGE_VIEW === "quant") {
        restoreQuantFactorUi();
        applySignalSlotBindingUi();
        applySignalTypeToggleUi();
        installFactorSnapshotFilterUi();
        setFactorSnapshotFilterUiVisible(!shouldUseBacktestPositionSnapshotPanel());
        scheduleFactorSnapshotForRightPanel(lastBarTime, true);
        return Promise.resolve();
    }
    if (PAGE_VIEW === "morph") {
        installMorphPanelUi();
        renderSignalData();
        updateSignalCaptionTitle();
        return Promise.resolve();
    }
    if (window.ChartBoardView && typeof window.ChartBoardView.onCodeChange === "function") {
        return window.ChartBoardView.onCodeChange(currentCode);
    }
    if (window.ChartBoardView && typeof window.ChartBoardView.init === "function") {
        return Promise.resolve(window.ChartBoardView.init());
    }
    renderSignalData();
    updateSignalCaptionTitle();
    return Promise.resolve();
}

function parsePortfolioBootOptions() {
    const sp = new URLSearchParams(window.location.search);
    const portfolioMode = sp.get("portfolio") === "1" || sp.get("result") === "1";
    const embedMode = sp.get("embed") === "1";
    /** 仅组合结果页内嵌 iframe 加载 .YKRS 组合曲线；主站一律禁止。 */
    const allowYkrsCurve = embedMode && portfolioMode && !isMainBoardPage();
    const codeFromUrl = (sp.get("code") || "").trim().toUpperCase();
    let code = codeFromUrl;
    if (!codeFromUrl && allowYkrsCurve) {
        code = "000000.YKRS";
    } else if (!codeFromUrl) {
        code = "";
    } else if (codeFromUrl.endsWith(".YKRS") && !allowYkrsCurve) {
        code = "";
    }
    const lockCode = portfolioMode || sp.get("lock_code") === "1";
    return {
        portfolioMode,
        embedMode,
        allowYkrsCurve,
        code,
        lockCode,
    };
}

const PAGE_BOOT = parsePortfolioBootOptions();

if (window.BacktestRunContext) {
    BacktestRunContext.syncActiveRunFromUrl(new URLSearchParams(window.location.search));
}

function getSelectedRunTag() {
    return window.BacktestRunContext ? BacktestRunContext.getActiveRunTag() : "";
}

function appendRunTagParam(params) {
    const tag = getSelectedRunTag();
    if (tag) {
        params.set("run_tag", tag);
    }
    return params;
}

function scrubDisallowedYkrsFromLocation() {
    if (PAGE_BOOT.allowYkrsCurve) {
        return;
    }
    try {
        const u = new URL(window.location.href);
        const c = (u.searchParams.get("code") || "").trim().toUpperCase();
        if (c.endsWith(".YKRS")) {
            u.searchParams.delete("code");
            const next = `${u.pathname}${u.search}${u.hash}`;
            window.history.replaceState({}, "", next);
        }
    } catch (_) {
        /* ignore */
    }
}
scrubDisallowedYkrsFromLocation();
if (PAGE_BOOT.portfolioMode || PAGE_BOOT.embedMode) {
    document.documentElement.classList.add("portfolio-result-page");
}
if (PAGE_BOOT.embedMode) {
    document.documentElement.classList.add("portfolio-result-page--embed");
}
if (PAGE_BOOT.lockCode) {
    document.documentElement.classList.add("portfolio-result-page--lock-code");
}
if (PAGE_BOOT.allowYkrsCurve) {
    document.documentElement.classList.add("portfolio-ykrs-curve-picker");
}

const API_BASE_URL = resolveApiBaseUrl();
const AUTO_REFRESH_SECONDS = 4;
/** 时间轴左右拖动不超出首末 K 线，中间无数据区间仍可见。 */
const TIME_SCALE_DATA_CLAMP = {
    fixLeftEdge: true,
    fixRightEdge: true
};
const INTERVAL_CONFIG = {
    "1min": {
        lookbackFallbacks: [
            3 * 24 * 60 * 60,
            30 * 24 * 60 * 60,
            180 * 24 * 60 * 60,
            730 * 24 * 60 * 60
        ],
        historicalBackfillWindowSeconds: 14 * 24 * 60 * 60,
        leftEdgePreloadThresholdSeconds: 6 * 60 * 60,
        jumpFetchWindows: [
            3 * 24 * 60 * 60,
            3 * 24 * 60 * 60,
            30 * 24 * 60 * 60,
            180 * 24 * 60 * 60
        ],
        alignStepSeconds: 60,
        latestPriceLookbackSeconds: 30 * 24 * 60 * 60,
        minimumVisibleSpanSeconds: 6 * 60 * 60
    },
    "1day": {
        lookbackFallbacks: [
            180 * 24 * 60 * 60,
            730 * 24 * 60 * 60,
            1825 * 24 * 60 * 60
        ],
        historicalBackfillWindowSeconds: 365 * 24 * 60 * 60,
        leftEdgePreloadThresholdSeconds: 30 * 24 * 60 * 60,
        jumpFetchWindows: [
            180 * 24 * 60 * 60,
            730 * 24 * 60 * 60,
            1825 * 24 * 60 * 60
        ],
        alignStepSeconds: 24 * 60 * 60,
        latestPriceLookbackSeconds: 730 * 24 * 60 * 60,
        minimumVisibleSpanSeconds: 180 * 24 * 60 * 60
    }
};
const CODE_SUGGESTION_LIMIT = 5;
const WATCHLIST_STORAGE_KEY = "quant_watchlist_v1";
const WATCHLIST_SYNC_DEBOUNCE_MS = 800;
const VIEW_STORAGE_KEY = "quant_last_view_v1";
const FACTOR_STORAGE_KEY = "quant_selected_factor_v1";
const FACTOR_GROUP_EXPAND_STORAGE_KEY = "quant_factor_group_expand_v1";
const QUANT_FACTOR_UI_STORAGE_KEY = "quant_factor_ui_v1";
const FACTOR_FETCH_LIMIT_INITIAL = 1200;
const FACTOR_FETCH_LIMIT_INCREMENTAL = 300;
const FACTOR_FETCH_LIMIT_MAX = 5000;
const MINUTE_OFFSCREEN_PRUNE_DELAY_MS = 1000;
const MINUTE_OFFSCREEN_PRUNE_BUFFER_BARS = 200;
const HISTORY_PREFETCH_DEBOUNCE_MS = 350;
const HISTORY_EMPTY_WINDOW_SKIP_ROUNDS = 3;
const HISTORY_PREFETCH_GESTURE_ROUNDS = 2;
/** 主图/副图左侧 Y 轴统一宽度。 */
const LEFT_PRICE_SCALE_MIN_WIDTH_PX = 0;
/** 主图/副图右侧 Y 轴统一宽度。 */
const RIGHT_PRICE_SCALE_MIN_WIDTH_PX = 72;

/** 中间列下方预留区初始高度，可拖拽调节。 */
const INITIAL_CENTER_BOTTOM_HEIGHT_PX = 180;
const CENTER_BOTTOM_HEIGHT_MIN_PX = 80;
const CENTER_BOTTOM_HEIGHT_MAX_PX = 520;

/** K 线与中间下区之间的副图（信号）初始高度。 */
const INITIAL_SIGNAL_PANE_HEIGHT_PX = 140;
const SIGNAL_PANE_MIN_PX = 72;
const SIGNAL_PANE_MAX_PX = 400;
/** 主 K 线区（含工具栏）允许的最小高度，用于计算副图与下区的可拖范围。 */
const MIN_CHART_STACK_PX = 140;

const codeInput = document.getElementById("code-input");
const ykrsCurveSelect = document.getElementById("ykrs-curve-select");
/** 组合结果页工具栏预留下拉，后续可绑定 change 等逻辑。 */
const portfolioExtraSelect = document.getElementById("portfolio-extra-select");
const portfolioExtraDayToggle = document.getElementById("portfolio-extra-day-toggle");
let portfolioExtraDayOn = false;

function setPortfolioExtraDayToggle(on) {
    portfolioExtraDayOn = Boolean(on);
    if (!portfolioExtraDayToggle) {
        return;
    }
    portfolioExtraDayToggle.classList.toggle("is-on", portfolioExtraDayOn);
    portfolioExtraDayToggle.setAttribute("aria-pressed", portfolioExtraDayOn ? "true" : "false");
}

const intervalSelect = document.getElementById("interval-select");
const adjustModeSelect = document.getElementById("adjust-mode-select");
const codeSuggestions = document.getElementById("code-suggestions");
const container = document.getElementById("chart-container");
const portfolioChartLegend = document.getElementById("portfolio-chart-legend");
const chartLegendStrategyLabel = document.getElementById("chart-legend-strategy-label");
const chartLegendBenchmarkLabel = document.getElementById("chart-legend-benchmark-label");
const chartLegendIndexLabel = document.getElementById("chart-legend-index-label");
const chartLegendBenchmarkItem = portfolioChartLegend
    ? portfolioChartLegend.querySelector('[data-legend-series="benchmark"]')
    : null;
const chartLegendIndexItem = portfolioChartLegend
    ? portfolioChartLegend.querySelector('[data-legend-series="index-overlay"]')
    : null;
const signalChartContainer = document.getElementById("signal-chart-container");
const signalChartWrap = document.getElementById("signal-chart-wrap");
const signalCaptionTitle = document.getElementById("signal-caption-title");
const signalCaptionOhlcv = document.getElementById("signal-caption-ohlcv");
const factorSelect = document.getElementById("factor-select");
const factorHint = document.getElementById("factor-hint");
const pageClock = document.getElementById("page-clock");
const addWatchCurrentBtn = document.getElementById("btn-add-watch-current");
const exportFactorDetails = document.getElementById("export-factor-details");
const exportFactorSummary = document.getElementById("export-factor-summary");
const exportFactorSelect = document.getElementById("export-factor-select");
const exportSymbolsBtn = document.getElementById("btn-export-symbols");
const paramTraverseToggle = document.getElementById("param-traverse-toggle");
let paramTraverseSwitchOn = false;
/** 档位定义顺序 = 副图叠层从低到高；强买最后绘制，因此在最上层。 */
const SIGNAL_TYPE_TOGGLE_SPECS = Object.freeze([
    { key: "fundamental_sell", label: "基本面卖点" },
    { key: "weak_sell", label: "弱卖" },
    { key: "fundamental_buy", label: "基本面买点" },
    { key: "weak_buy", label: "弱买" },
    { key: "strong_buy", label: "强买" },
]);
const signalTypeToggleState = Object.fromEntries(
    SIGNAL_TYPE_TOGGLE_SPECS.map((item) => [item.key, true])
);
const signalTypeTogglesWrap = document.getElementById("signal-type-toggles");
let uiHintToastTimer = null;
let tvDayMinuteChart = null;
let tvDayMinuteCandleSeries = null;
let tvDayMinutePercentSeries = null;
let tvDayMinuteVolumeSeries = null;
let tvDayMinuteRefreshTimer = null;
let tvDayMinuteRefreshToken = 0;
let tvDayMinuteActiveRequest = false;
let tvDayMinuteModalState = null;
let tvDayMinuteBarsCache = [];
let tvDayMinuteKeyboardIndex = -1;
let tvDayMinuteMouseIndex = -1;
let tvDayMinuteMouseVersion = 0;
let tvDayMinuteKeyboardMouseVersion = -1;
let tvDayMinuteApplyingKeyboardCrosshair = false;
const SIGNAL_SLOT_BINDINGS_KEY = "SIGNAL_SLOT_BINDINGS_V1";
const SIGNAL_SLOT_SERIES_COLORS = Object.freeze({
    strong_buy: "#ef5350",
    weak_buy: "#f59e0b",
    fundamental_buy: "#ec4899",
    weak_sell: "#4ade80",
    fundamental_sell: "#60a5fa",
});
const AD_HOC_SIGNAL_SERIES_COLORS = Object.freeze([
    "#3b82f6",
    "#a855f7",
    "#14b8a6",
    "#ec4899",
    "#c084fc",
    "#22d3ee",
    "#fb7185",
    "#84cc16",
    "#8b5cf6",
    "#2dd4bf",
]);
let signalSlotBindings = Object.fromEntries(
    SIGNAL_TYPE_TOGGLE_SPECS.map((item) => [item.key, ""])
);
const slotSignalPointsByKey = new Map();
const slotLastSignalTimeByKey = new Map();
const slotSignalSeriesByKey = new Map();
const watchlistCards = document.getElementById("watchlist-cards");
const mainLayout = document.getElementById("main-layout");
const leftPanel = document.getElementById("left-panel");
const rightPanel = document.getElementById("right-panel");
const rightPanelBody = document.getElementById("right-panel-body");
const centerColumn = document.getElementById("center-column");
const centerBottomPanel = document.getElementById("center-bottom-panel");
const splitterCenterV = document.getElementById("splitter-center-v");
const splitterSignal = document.getElementById("splitter-signal");
const chartWrap = document.querySelector("#center-column .chart-wrap");
const splitterLeft = document.getElementById("splitter-left");
const splitterRight = document.getElementById("splitter-right");
const headerTabsContainer = document.getElementById("header-tabs-container");
let headerTabs = Array.from(document.querySelectorAll(".header-tab"));
const PRIMARY_RIGHT_PANEL_TAB_KEY = "量化因子";
const COMBINED_HEADER_TAB_LABEL = "组合详情";
const DEFAULT_HEADER_TAB_LABELS = ["量化因子", "形态面", "舆情面", "基本面"];

const RIGHT_PANEL_TAB_CONTENT = {
    "量化因子": `
                <div class="factor-snapshot-header">
                    <h3 class="factor-snapshot-head">
                        <span id="factor-snapshot-head-title">因子</span>
                        <span id="factor-snapshot-head-extra" class="factor-snapshot-head-extra"></span>
                    </h3>
                    <div class="factor-snapshot-header-actions">
                        <div id="factor-snapshot-tools" class="factor-snapshot-tools">
                            <span id="factor-snapshot-filter-wrap" class="factor-snapshot-filter-wrap">
                                <button type="button" id="factor-snapshot-filter-btn" class="factor-snapshot-filter-btn" title="按关键词筛选组名或因子名" aria-label="筛选因子">筛</button>
                                <div id="factor-snapshot-filter-popover" class="factor-snapshot-filter-popover" hidden>
                                    <input type="search" id="factor-snapshot-filter-input" class="factor-snapshot-filter-input" placeholder="组名 / 因子名" autocomplete="off" />
                                </div>
                            </span>
                            <button type="button" id="factor-snapshot-couple-btn" class="factor-snapshot-couple-btn" title="因子耦合：当前标的全历史按日计算，所选右侧因子均 > 1 则为 1" aria-label="因子耦合">
                                <svg class="factor-snapshot-couple-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.35" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                    <path d="M10 13a5 5 0 0 1 0-7l.7-.7a5 5 0 1 1 7.1 7.1l-.7.7" />
                                    <path d="M14 11a5 5 0 0 1 0 7l-.7.7a5 5 0 1 1-7.1-7.1l.7-.7" />
                                </svg>
                            </button>
                        </div>
                        <button id="factor-clear-btn" class="factor-snapshot-clear-btn" type="button">清空</button>
                    </div>
                </div>
                <div id="factor-snapshot-list" class="factor-snapshot-list"></div>
            `,
    "形态面": `
                <h3 class="morph-panel-title">形态面</h3>
                <div id="morph-panel-list" class="morph-panel-list" role="group" aria-label="形态面选项">
                    <button type="button" class="morph-panel-item" data-morph-key="level1" data-morph-group="level" aria-pressed="false">
                        <span class="morph-panel-label">1级形态面</span>
                        <span class="morph-panel-check" aria-hidden="true"></span>
                    </button>
                    <button type="button" class="morph-panel-item" data-morph-key="level2" data-morph-group="level" aria-pressed="false">
                        <span class="morph-panel-label">2级形态面</span>
                        <span class="morph-panel-check" aria-hidden="true"></span>
                    </button>
                    <button type="button" class="morph-panel-item" data-morph-key="level3" data-morph-group="level" aria-pressed="false">
                        <span class="morph-panel-label">3级形态面</span>
                        <span class="morph-panel-check" aria-hidden="true"></span>
                    </button>
                    <button type="button" class="morph-panel-item" data-morph-key="channel" aria-pressed="false">
                        <span class="morph-panel-label">閫氶亾</span>
                        <span class="morph-panel-check" aria-hidden="true"></span>
                    </button>
                    <button type="button" class="morph-panel-item" data-morph-key="trend" aria-pressed="false">
                        <span class="morph-panel-label">趋势线</span>
                        <span class="morph-panel-check" aria-hidden="true"></span>
                    </button>
                </div>
            `,
    "舆情面": `
                <h3 style="margin: 0 0 8px 0; color: #d1d4dc;">舆情面</h3>
                <div>这里先放舆情面占位内容，后续可接新闻热度、情绪指标与事件摘要。</div>
            `,
    "基本面": `
                <h3 style="margin: 0 0 8px 0; color: #d1d4dc;">基本面</h3>
                <div>这里先放基本面占位内容，后续可接财务指标、估值区间与行业对比。</div>
            `
};

const RIGHT_PANEL_SNAPSHOT_DEBOUNCE_MS = 120;
const SIGNAL_SERIES_COLORS = ["#3b82f6", "#f59e0b", "#10b981", "#a855f7", "#ef4444", "#14b8a6", "#eab308", "#ec4899"];

const MORPH_PANEL_STORAGE_KEY = "MORPH_PANEL_STATE_V1";
const MORPH_PANEL_LEVEL_GROUP = "level";
const MORPH_PANEL_OPTION_KEYS = ["level1", "level2", "level3", "channel", "trend"];
const MORPH_PANEL_DEFAULT_STATE = Object.freeze({
    level1: false,
    level2: false,
    level3: true,
    channel: true,
    trend: true,
});
let morphPanelState = { ...MORPH_PANEL_DEFAULT_STATE };
let morphPanelUiBound = false;

const MORPH_SIGNAL_LABELS = Object.freeze({
    level1: "1级形态面",
    level2: "2级形态面",
    level3: "3级形态面",
    channel: "通道",
    trend: "趋势线",
});
const MORPH_PATTERN_NAME_ZH = Object.freeze({
    harami_bullish: "看涨孕线",
    harami_bearish: "看跌孕线",
    morning_star_doji: "十字晨星",
    hammer: "锤子线",
    hanging_man: "上吊线",
    engulfing_bullish: "看涨吞没",
    engulfing_bearish: "看跌吞没",
    dark_cloud_cover: "乌云盖顶",
    piercing: "刺透形态",
    morning_star: "启明星",
    evening_star: "黄昏星",
    evening_star_doji: "十字暮星",
    abandoned_baby_bullish: "看涨弃婴",
    abandoned_baby_bearish: "看跌弃婴",
    harami_doji_bullish: "看涨十字孕线",
    harami_doji_bearish: "看跌十字孕线",
    tweezers_top: "平头顶部",
    tweezers_bottom: "平头底部",
    belt_hold_bullish: "看涨捉腰带线",
    belt_hold_bearish: "看跌捉腰带线",
    counterattack_bullish: "看涨反击线",
    counterattack_bearish: "看跌反击线",
    two_crows: "两只乌鸦",
    three_black_crows: "三只乌鸦",
    three_white_soldiers: "红三兵",
    rising_three_methods: "上升三法",
    falling_three_methods: "下降三法"
});
const morphSignalPointsByKey = new Map();
const extraMorphSignalSeriesByKey = new Map();
const morphPatternPointsByName = new Map();
const morphPatternLineSeriesByName = new Map();
const morphEventsByDay = new Map();
let morphLoadedLevelKey = "";
let morphOverlayCanvas = null;
let morphOverlayCtx = null;
let morphOverlayLastChartTime = null;
let morphOverlayViewportRafId = 0;
let morphBackfillRenderTimer = null;
let morphBackfillInFlight = 0;
const MORPH_BACKFILL_RENDER_COALESCE_MS = 200;
const MORPH_WINDOW_MAX_BARS = 250;
const MORPH_WINDOW_MAX_VISIBLE_BARS = 250;
const MORPH_WINDOW_PRELOAD_EDGE_BARS = 30;
/** 只有当视口左边已经贴到第一个 bar 前，才向左平移，避免缓存内平移时误判。 */
const MORPH_WINDOW_SHIFT_TRIGGER_BARS = 1;
const MORPH_WINDOW_SHIFT_EDGE_CUSHION = 12;
const MORPH_WINDOW_EDGE_CHECK_SETTLE_MS = 150;
const MORPH_WINDOW_EDGE_SUPPRESS_MS = 450;
const MORPH_WINDOW_SHIFT_BATCH_BARS = 60;
/** 缂╁皬瑙嗗浘鏃朵繚鐣欑殑 pan 浣欓噺锛岄伩鍏嶈鍙ｉ摵婊＄紦瀛樺悗瀹屽叏鎷栦笉鍔?*/
const MORPH_WINDOW_PAN_SLACK_BARS = 40;
let morphSummaryPointsCache = [];
let morphWindowAtLatest = true;
let morphWindowShiftInFlight = false;
let morphWindowEdgeCheckTimer = null;
let morphWindowEdgeCheckSuppressedUntil = 0;
let morphWindowChartInteracting = false;
let morphWindowPreloadedBars = null;
let morphWindowPreloadDirection = "";
let morphWindowLastShiftAt = 0;

function getMorphSlackVisibleSpan(barCount = barsCache.length) {
    const count = Math.max(0, Number(barCount) || 0);
    if (!count) {
        return MORPH_WINDOW_MAX_VISIBLE_BARS;
    }
    const slack = MORPH_WINDOW_PAN_SLACK_BARS;
    if (count <= slack + 2) {
        return Math.max(2, count);
    }
    return Math.min(MORPH_WINDOW_MAX_VISIBLE_BARS, count - slack);
}

function getMorphLatestWindowMinFrom(barCount = barsCache.length) {
    const maxTo = Math.max(0, Number(barCount) || 0) - 0.5;
    return maxTo - getMorphSlackVisibleSpan(barCount);
}

function getMorphWindowMaxVisibleSpan(barCount = barsCache.length, range = null) {
    const count = Math.max(0, Number(barCount) || 0);
    if (!count) {
        return MORPH_WINDOW_MAX_VISIBLE_BARS;
    }
    const fullCap = Math.min(MORPH_WINDOW_MAX_VISIBLE_BARS, count);
    if (range && Number(range.from) < getMorphLatestWindowMinFrom(count) - 1) {
        return fullCap;
    }
    return getMorphSlackVisibleSpan(count);
}

function isMorphLogicalRangeNearLatest(range, barCount = barsCache.length) {
    const maxIndex = Math.max(0, (Number(barCount) || 0) - 1);
    if (!range || maxIndex < 0) {
        return false;
    }
    const from = Number(range.from);
    const to = Number(range.to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) {
        return false;
    }
    const span = Math.max(10, to - from);
    return to >= maxIndex - Math.max(3, span * 0.25);
}

function isMorphLogicalRangeNearOldest(range, barCount = barsCache.length) {
    const maxIndex = Math.max(0, (Number(barCount) || 0) - 1);
    if (!range || maxIndex < 0) {
        return false;
    }
    const from = Number(range.from);
    const to = Number(range.to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) {
        return false;
    }
    const span = Math.max(10, to - from);
    return from <= Math.max(3, span * 0.25);
}

function isQuantSignalTab() {
    return PAGE_VIEW === "quant" || (isEmbedOnlyIndexSurface() && currentRightTabName === PRIMARY_RIGHT_PANEL_TAB_KEY);
}

function isMorphSignalTab() {
    return PAGE_VIEW === "morph" || (isEmbedOnlyIndexSurface() && currentRightTabName === "形态面");
}

function clearAllSignalChartSeries() {
    signalSeries.setData([]);
    for (const factorName of Array.from(extraSignalSeriesByFactor.keys())) {
        clearExtraSignalSeries(factorName);
    }
    for (const key of Array.from(extraMorphSignalSeriesByKey.keys())) {
        clearExtraMorphSignalSeries(key);
    }
    clearAllMorphPatternLineSeries();
    for (const slotKey of Array.from(slotSignalSeriesByKey.keys())) {
        clearSlotSignalSeries(slotKey);
    }
}

function logUiHint(message) {
    const text = String(message || "").trim();
    if (!text) {
        return;
    }
    if (typeof console !== "undefined" && console.warn) {
        console.warn("[看板]", text);
    }
    let toast = document.getElementById("ui-hint-toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "ui-hint-toast";
        toast.className = "ui-hint-toast";
        toast.setAttribute("role", "status");
        toast.setAttribute("aria-live", "polite");
        document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.classList.add("visible");
    if (uiHintToastTimer) {
        clearTimeout(uiHintToastTimer);
    }
    uiHintToastTimer = setTimeout(() => {
        toast.classList.remove("visible");
    }, 5200);
}

function ensureTvDayModal() {
    let mask = document.getElementById("tv-day-modal-mask");
    if (mask) {
        return mask;
    }
    mask = document.createElement("div");
    mask.id = "tv-day-modal-mask";
    mask.className = "tv-day-modal-mask";
    mask.setAttribute("aria-hidden", "true");
    mask.innerHTML = `
        <div class="tv-day-modal" role="dialog" aria-modal="true" aria-labelledby="tv-day-modal-title">
            <div class="tv-day-modal-header">
                <span id="tv-day-modal-title">TradingView</span>
                <button id="tv-day-modal-close" class="tv-day-modal-close" type="button" aria-label="关闭">×</button>
            </div>
            <div class="tv-day-modal-body">
                <div id="tv-day-minute-status" class="tv-day-minute-status">加载分钟线...</div>
                <div id="tv-day-minute-chart" class="tv-day-minute-chart"></div>
            </div>
        </div>
    `;
    document.body.appendChild(mask);
    const closeBtn = document.getElementById("tv-day-modal-close");
    if (closeBtn) {
        closeBtn.addEventListener("click", () => closeTvDayModal());
    }
    mask.addEventListener("click", (event) => {
        if (event.target === mask) {
            closeTvDayModal();
        }
    });
    return mask;
}

function setTvDayMinuteStatus(message, visible = true) {
    const statusEl = document.getElementById("tv-day-minute-status");
    if (!statusEl) {
        return;
    }
    statusEl.textContent = message || "";
    statusEl.style.display = visible ? "flex" : "none";
}

function resetTvDayMinuteChart() {
    if (tvDayMinuteChart && typeof tvDayMinuteChart.remove === "function") {
        try {
            tvDayMinuteChart.remove();
        } catch (_) {
            /* ignore */
        }
    }
    tvDayMinuteChart = null;
    tvDayMinuteCandleSeries = null;
    tvDayMinutePercentSeries = null;
    tvDayMinuteVolumeSeries = null;
    tvDayMinuteBarsCache = [];
    tvDayMinuteKeyboardIndex = -1;
    tvDayMinuteMouseIndex = -1;
    tvDayMinuteMouseVersion = 0;
    tvDayMinuteKeyboardMouseVersion = -1;
    tvDayMinuteApplyingKeyboardCrosshair = false;
    const chartEl = document.getElementById("tv-day-minute-chart");
    if (chartEl) {
        chartEl.innerHTML = "";
    }
}

async function fetchTvDayMinuteBars(code, dayTs) {
    const fromTs = alignToCurrentInterval(dayTs);
    const toTs = fromTs + 24 * 60 * 60;
    const params = new URLSearchParams({
        code,
        interval: "1min",
        adjust: "none",
        from: String(fromTs),
        to: String(toTs),
        limit: "2000"
    });
    const url = `${API_BASE_URL}/api/market/bars?${params.toString()}`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        const message = body && body.error && body.error.message ? body.error.message : "分钟线请求失败";
        throw new Error(message);
    }
    return Array.isArray(body.bars) ? body.bars : [];
}

function formatTvDayTitleDate(dayTs) {
    const dt = new Date(Number(dayTs) * 1000);
    if (Number.isNaN(dt.getTime())) {
        return "";
    }
    const y = dt.getUTCFullYear();
    const m = String(dt.getUTCMonth() + 1).padStart(2, "0");
    const d = String(dt.getUTCDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function formatTvDayMinuteCrosshairTimeLabel(time) {
    let dt = null;
    if (typeof time === "number") {
        dt = new Date(time * 1000);
    } else if (time && typeof time === "object" && "timestamp" in time) {
        dt = new Date(Number(time.timestamp) * 1000);
    } else if (time && typeof time === "object" && "year" in time && "month" in time && "day" in time) {
        dt = new Date(Date.UTC(Number(time.year), Number(time.month) - 1, Number(time.day), 0, 0, 0));
    }
    if (!(dt instanceof Date) || Number.isNaN(dt.getTime())) {
        return "--";
    }
    const hour24 = dt.getUTCHours();
    const hh = String(hour24 % 12 || 12).padStart(2, "0");
    const mm = String(dt.getUTCMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
}

function renderTvDayMinuteChart(bars, prevClose = NaN) {
    const chartEl = document.getElementById("tv-day-minute-chart");
    if (!chartEl) {
        return;
    }
    resetTvDayMinuteChart();
    tvDayMinuteChart = LightweightCharts.createChart(chartEl, {
        layout: { background: { color: "#131722" }, textColor: "#d1d4dc", attributionLogo: false },
        grid: { vertLines: { color: "#2b2b2b" }, horzLines: { color: "#2b2b2b" } },
        leftPriceScale: { visible: true, borderColor: "#2b2b2b", minimumWidth: RIGHT_PRICE_SCALE_MIN_WIDTH_PX },
        rightPriceScale: { visible: true, borderColor: "#2b2b2b", minimumWidth: RIGHT_PRICE_SCALE_MIN_WIDTH_PX },
        localization: { timeFormatter: formatTvDayMinuteCrosshairTimeLabel },
        timeScale: { timeVisible: true, secondsVisible: true, borderColor: "#2b2b2b" },
        crosshair: {
            horzLine: { labelBackgroundColor: "#3b82f6" },
            vertLine: { labelBackgroundColor: "#3b82f6" }
        }
    });
    tvDayMinuteCandleSeries = tvDayMinuteChart.addSeries(LightweightCharts.LineSeries, {
        color: "#3b82f6",
        lineWidth: 2,
        lastValueVisible: false,
        priceLineVisible: false,
        priceScaleId: "left"
    });
    tvDayMinutePercentSeries = tvDayMinuteChart.addSeries(LightweightCharts.LineSeries, {
        color: "rgba(0,0,0,0)",
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        priceScaleId: "right",
        priceFormat: {
            type: "custom",
            minMove: 0.01,
            formatter: (value) => `${Number(value).toFixed(2)}%`
        }
    });
    tvDayMinuteVolumeSeries = tvDayMinuteChart.addSeries(LightweightCharts.HistogramSeries, {
        priceFormat: { type: "volume" },
        lastValueVisible: false,
        priceLineVisible: false,
        priceScaleId: "volume-scale"
    });
    tvDayMinuteChart.priceScale("left").applyOptions({
        autoScale: true,
        scaleMargins: { top: 0.08, bottom: 0.22 }
    });
    tvDayMinuteChart.priceScale("right").applyOptions({
        autoScale: true,
        scaleMargins: { top: 0.08, bottom: 0.22 }
    });
    tvDayMinuteChart.priceScale("volume-scale").applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
        visible: false
    });
    tvDayMinuteChart.subscribeCrosshairMove((param) => {
        if (tvDayMinuteApplyingKeyboardCrosshair) {
            return;
        }
        const index = findTvDayMinuteBarIndexByTime(param && param.time);
        if (index < 0) {
            return;
        }
        tvDayMinuteMouseIndex = index;
        tvDayMinuteMouseVersion += 1;
        tvDayMinuteKeyboardMouseVersion = -1;
    });
    chartEl.addEventListener("mousemove", (event) => {
        if (!tvDayMinuteChart || !tvDayMinuteBarsCache.length) {
            return;
        }
        const bounds = chartEl.getBoundingClientRect();
        const x = event.clientX - bounds.left;
        const timeValue = tvDayMinuteChart.timeScale().coordinateToTime(x);
        const index = findTvDayMinuteBarIndexByTime(timeValue);
        if (index < 0 || index === tvDayMinuteMouseIndex) {
            return;
        }
        tvDayMinuteMouseIndex = index;
        tvDayMinuteMouseVersion += 1;
        tvDayMinuteKeyboardMouseVersion = -1;
    });
    updateTvDayMinuteChartData(bars, prevClose, true);
}

function updateTvDayMinuteChartData(bars, prevClose = NaN, fitContent = false) {
    if (!tvDayMinuteChart || !tvDayMinuteCandleSeries || !tvDayMinutePercentSeries || !tvDayMinuteVolumeSeries) {
        renderTvDayMinuteChart(bars, prevClose);
        return;
    }
    const previousTime = tvDayMinuteKeyboardIndex >= 0 && tvDayMinuteKeyboardIndex < tvDayMinuteBarsCache.length
        ? Number(tvDayMinuteBarsCache[tvDayMinuteKeyboardIndex].time)
        : NaN;
    tvDayMinuteBarsCache = Array.isArray(bars) ? bars.slice() : [];
    const priceData = bars.map((item) => ({
        time: Number(item.time),
        value: Number(item.close)
    }));
    if (!priceData.length) {
        return;
    }
    const prevClosePrice = Number(prevClose);
    const basePrice = Number.isFinite(prevClosePrice) && prevClosePrice !== 0
        ? prevClosePrice
        : Number(priceData[0] && priceData[0].value);
    const toPercent = (value) => (
        Number.isFinite(basePrice) && basePrice !== 0 && Number.isFinite(value)
            ? ((value - basePrice) / basePrice) * 100
            : 0
    );
    const percentData = priceData.map((item) => ({
        time: item.time,
        value: toPercent(item.value)
    }));
    const maxAbsPct = Math.max(
        0.01,
        ...percentData.map((item) => Math.abs(Number(item.value))).filter(Number.isFinite)
    );
    const priceRangeMin = basePrice * (1 - maxAbsPct / 100);
    const priceRangeMax = basePrice * (1 + maxAbsPct / 100);
    tvDayMinuteCandleSeries.applyOptions({
        autoscaleInfoProvider: () => ({
            priceRange: { minValue: priceRangeMin, maxValue: priceRangeMax }
        })
    });
    tvDayMinutePercentSeries.applyOptions({
        autoscaleInfoProvider: () => ({
            priceRange: { minValue: -maxAbsPct, maxValue: maxAbsPct }
        })
    });
    tvDayMinuteCandleSeries.setData(priceData);
    tvDayMinutePercentSeries.setData(percentData);
    tvDayMinuteVolumeSeries.setData(bars.map((item) => ({
        time: Number(item.time),
        value: Number(item.volume || 0),
        color: getAShareBarColor(item)
    })));
    if (fitContent) {
        tvDayMinuteChart.timeScale().fitContent();
    }
    if (Number.isFinite(previousTime)) {
        const nextIndex = tvDayMinuteBarsCache.findIndex((item) => Number(item && item.time) === previousTime);
        tvDayMinuteKeyboardIndex = nextIndex >= 0 ? nextIndex : Math.min(tvDayMinuteKeyboardIndex, tvDayMinuteBarsCache.length - 1);
        applyTvDayMinuteKeyboardCrosshair();
    }
}

function isTvDayMinuteModalVisible() {
    const mask = document.getElementById("tv-day-modal-mask");
    return Boolean(mask && mask.classList.contains("visible"));
}

function findTvDayMinuteBarIndexByTime(timeValue) {
    if (!tvDayMinuteBarsCache.length) {
        return -1;
    }
    const target = normalizeTimeToSeconds(timeValue);
    if (!Number.isFinite(target)) {
        return -1;
    }
    let bestIndex = -1;
    let bestDistance = Infinity;
    for (let i = 0; i < tvDayMinuteBarsCache.length; i += 1) {
        const itemTime = Number(tvDayMinuteBarsCache[i] && tvDayMinuteBarsCache[i].time);
        if (!Number.isFinite(itemTime)) {
            continue;
        }
        const distance = Math.abs(itemTime - target);
        if (distance < bestDistance) {
            bestDistance = distance;
            bestIndex = i;
        }
    }
    return bestDistance <= 45 ? bestIndex : -1;
}

function applyTvDayMinuteKeyboardCrosshair() {
    if (!tvDayMinuteChart || !tvDayMinuteCandleSeries || !tvDayMinuteBarsCache.length) {
        return false;
    }
    if (tvDayMinuteKeyboardIndex < 0) {
        tvDayMinuteKeyboardIndex = tvDayMinuteBarsCache.length - 1;
    }
    tvDayMinuteKeyboardIndex = Math.min(
        Math.max(0, tvDayMinuteKeyboardIndex),
        tvDayMinuteBarsCache.length - 1
    );
    const bar = tvDayMinuteBarsCache[tvDayMinuteKeyboardIndex];
    const close = Number(bar && bar.close);
    const time = Number(bar && bar.time);
    if (!Number.isFinite(close) || !Number.isFinite(time) || typeof tvDayMinuteChart.setCrosshairPosition !== "function") {
        return false;
    }
    tvDayMinuteApplyingKeyboardCrosshair = true;
    try {
        tvDayMinuteChart.setCrosshairPosition(close, time, tvDayMinuteCandleSeries);
    } finally {
        setTimeout(() => {
            tvDayMinuteApplyingKeyboardCrosshair = false;
        }, 0);
    }
    return true;
}

function moveTvDayMinuteKeyboardCrosshair(offset) {
    if (!isTvDayMinuteModalVisible() || !tvDayMinuteBarsCache.length) {
        return false;
    }
    if (
        tvDayMinuteMouseIndex >= 0
        && tvDayMinuteMouseIndex < tvDayMinuteBarsCache.length
        && tvDayMinuteMouseVersion !== tvDayMinuteKeyboardMouseVersion
    ) {
        tvDayMinuteKeyboardIndex = tvDayMinuteMouseIndex + offset;
        tvDayMinuteKeyboardMouseVersion = tvDayMinuteMouseVersion;
    } else if (tvDayMinuteKeyboardIndex < 0) {
        tvDayMinuteKeyboardIndex = tvDayMinuteBarsCache.length - 1;
    } else {
        tvDayMinuteKeyboardIndex += offset;
    }
    return applyTvDayMinuteKeyboardCrosshair();
}

async function loadTvDayMinuteChart(code, dayTs, prevClose = NaN, options = {}) {
    const silent = options && options.silent === true;
    const token = tvDayMinuteRefreshToken;
    if (!silent) {
        setTvDayMinuteStatus("加载分钟线...");
        resetTvDayMinuteChart();
    }
    try {
        const bars = await fetchTvDayMinuteBars(code, dayTs);
        if (token !== tvDayMinuteRefreshToken) {
            return;
        }
        if (!bars.length) {
            if (!silent) {
                setTvDayMinuteStatus("当天暂无分钟线数据");
            }
            return;
        }
        setTvDayMinuteStatus("", false);
        if (silent) {
            updateTvDayMinuteChartData(bars, prevClose);
        } else {
            renderTvDayMinuteChart(bars, prevClose);
        }
    } catch (err) {
        if (token === tvDayMinuteRefreshToken) {
            setTvDayMinuteStatus(err && err.message ? err.message : "分钟线加载失败");
        }
    }
}

async function refreshTvDayMinuteModal() {
    if (!tvDayMinuteModalState || tvDayMinuteActiveRequest) {
        return;
    }
    const mask = document.getElementById("tv-day-modal-mask");
    if (!mask || !mask.classList.contains("visible")) {
        return;
    }
    tvDayMinuteActiveRequest = true;
    try {
        await loadTvDayMinuteChart(
            tvDayMinuteModalState.code,
            tvDayMinuteModalState.dayTs,
            tvDayMinuteModalState.prevClose,
            { silent: true }
        );
    } finally {
        tvDayMinuteActiveRequest = false;
    }
}

function stopTvDayMinuteAutoRefresh() {
    if (tvDayMinuteRefreshTimer) {
        clearInterval(tvDayMinuteRefreshTimer);
        tvDayMinuteRefreshTimer = null;
    }
    tvDayMinuteActiveRequest = false;
    tvDayMinuteModalState = null;
    tvDayMinuteRefreshToken += 1;
}

function startTvDayMinuteAutoRefresh(code, dayTs, prevClose = NaN) {
    stopTvDayMinuteAutoRefresh();
    tvDayMinuteModalState = { code, dayTs, prevClose };
    tvDayMinuteRefreshTimer = setInterval(refreshTvDayMinuteModal, AUTO_REFRESH_SECONDS * 1000);
}

function openTvDayModal(code, dayTs, prevClose = NaN) {
    const mask = ensureTvDayModal();
    const titleEl = document.getElementById("tv-day-modal-title");
    if (titleEl) {
        titleEl.textContent = `${String(code || "").trim()} ${formatTvDayTitleDate(dayTs)} 1鍒嗛挓`;
    }
    mask.classList.add("visible");
    mask.setAttribute("aria-hidden", "false");
    startTvDayMinuteAutoRefresh(code, dayTs, prevClose);
    void loadTvDayMinuteChart(code, dayTs, prevClose);
}

function openTvDayModalForBarIndex(barIndex) {
    if (currentInterval !== "1day" || isMainChartLineMode()) {
        return false;
    }
    if (!Number.isInteger(barIndex) || barIndex < 0 || barIndex >= barsCache.length) {
        return false;
    }
    const bar = barsCache[barIndex];
    const dayTs = alignToCurrentInterval(Number(bar && bar.time));
    if (!Number.isFinite(dayTs)) {
        return false;
    }
    const prevBar = barIndex > 0 ? barsCache[barIndex - 1] : null;
    const prevClose = prevBar ? Number(prevBar.close) : NaN;
    openTvDayModal(currentCode, dayTs, prevClose);
    return true;
}

function closeTvDayModal() {
    const mask = document.getElementById("tv-day-modal-mask");
    if (!mask) {
        return;
    }
    if (document.activeElement && mask.contains(document.activeElement)) {
        if (container && typeof container.focus === "function") {
            container.focus({ preventScroll: true });
        } else if (document.body && typeof document.body.focus === "function") {
            document.body.focus({ preventScroll: true });
        }
        if (document.activeElement && mask.contains(document.activeElement) && typeof document.activeElement.blur === "function") {
            document.activeElement.blur();
        }
    }
    mask.classList.remove("visible");
    mask.setAttribute("aria-hidden", "true");
    stopTvDayMinuteAutoRefresh();
    resetTvDayMinuteChart();
}

function bindDailyChartDoubleClickModal() {
    if (!container) {
        return;
    }
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeTvDayModal();
        }
    });
    container.addEventListener("dblclick", async (event) => {
        if (currentInterval !== "1day" || isMainChartLineMode()) {
            return;
        }
        const bounds = container.getBoundingClientRect();
        const x = event.clientX - bounds.left;
        const chartTime = chart.timeScale().coordinateToTime(x);
        const barIndex = findBarIndexByChartTime(chartTime);
        if (barIndex < 0) {
            return;
        }
        event.preventDefault();
        openTvDayModalForBarIndex(barIndex);
    });
}

const API_READY_MAX_ATTEMPTS = 1;
const API_READY_INTERVAL_MS = 0;

async function fetchApiHealthOnce(timeoutMs = 600) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const resp = await fetch(`${API_BASE_URL}/api/health`, {
            method: "GET",
            cache: "no-store",
            signal: controller.signal,
        });
        if (!resp.ok) {
            return false;
        }
        const body = await resp.json();
        return Boolean(body && body.ok !== false);
    } catch (_) {
        return false;
    } finally {
        clearTimeout(timer);
    }
}

async function waitForApiReady() {
    return true;
}

function runBackgroundTask(label, task) {
    Promise.resolve()
        .then(task)
        .catch((err) => {
            console.warn(label, err);
        });
}

function setPortfolioIndexOverlayStatus(_message, _isError = false) {
    /* 宸茬Щ闄ら〉闈㈢姸鎬佹潯锛涙垚鍔?鎻愮ず涓嶅啀杈撳嚭锛岄伩鍏嶆帶鍒跺彴骞叉壈 */
}

/** 回测模型说明：由 GET /api/backtest/models 填充；失败时保持空列表。 */
let BACKTEST_MODEL_CATALOG = [];
let BACKTEST_MODEL_DOC = {};

const BACKTEST_MODEL_FALLBACK = [];

const ADJUST_MODE_PARAM = {
    qfq: "forward",
    hfq: "backward",
    none: "none",
};
let currentCode = PAGE_BOOT.code || "301469.SZ";
let currentInterval = "1day";
let currentAdjustMode = "qfq";
const PORTFOLIO_MAIN_CURVE_CODE = "000000.YKRS";
const BENCHMARK_CURVE_CODE = "000001.YKRS";
const CURVE_LINE_CODES = new Set([PORTFOLIO_MAIN_CURVE_CODE, BENCHMARK_CURVE_CODE]);
const POSITION_SNAPSHOT_CODES = new Set([PORTFOLIO_MAIN_CURVE_CODE]);
let barsCache = [];
let benchmarkBarsCache = [];
let indexOverlayBarsCache = [];
let lastBarTime = null;
let firstAvailableBarTime = null;
let lastAvailableBarTime = null;
let isRequesting = false;
let isSwitchingCode = false;
let pendingSwitchCode = "";
let isLoadingHistory = false;
let historyExhausted = false;
let lastHistoryRequestTo = null;
let refreshTimer = null;
let countdownTimer = null;
let countdownValue = AUTO_REFRESH_SECONDS;
let selectedWatchCode = "";
let watchlistCodes = ["301469.SZ"];
let watchlistPriceMap = new Map();
let watchlistSyncTimer = null;
let factorNames = [];
let factorGroups = [];
let factorCoreNames = [];
let factorCoreLabels = [];
let factorLabelMap = {};
let expandedFactorGroupIds = new Set();
let selectedFactorName = "";
let activeFactorNames = [];
let signalPoints = [];
let lastSignalTime = null;
let missingFactorKeys = new Set();
let extraSignalPointsByFactor = new Map();
let extraLastSignalTimeByFactor = new Map();
let extraSignalSeriesByFactor = new Map();
let currentRightTabName = getPageViewLabel();
let currentFactorSnapshotTime = null;
let currentFactorSnapshotPayload = null;
let lastRenderedSnapshotKey = "";
let snapshotRequestSeq = 0;
let rightPanelSnapshotCache = new Map();
let currentBacktestPositionSnapshot = null;
let currentBacktestPositionHoverCode = "";
let backtestOrderItems = [];
let selectedPortfolioIndexCode = "";
let minuteOffscreenPruneTimer = null;
let historyPrefetchDebounceTimer = null;
let clearCodeInputOnNextEdit = false;
let codeSuggestTimer = null;
let codeSuggestItems = [];
let activeSuggestionIndex = -1;
async function loadBacktestModelsCatalog() { }
async function refreshBacktestOrderMarkers() { }
function applyBacktestOrderMarkers() { }
function renderBacktestPositionSnapshotToRightPanel(_snapshot, _targetTs) { }
function shouldUseBacktestPositionSnapshotPanel(codeValue = currentCode) {
    return POSITION_SNAPSHOT_CODES.has(normalizeCodeValue(codeValue));
}
async function fetchBacktestSummaryForActiveRun() { return null; }
function getBacktestRangeFromSummary(_summary) { return null; }
async function fetchBacktestOrders(_code, _fromTs, _toTs) { return []; }
function buildBacktestOrderMarkers(_items) { return []; }
function buildBacktestOrderMarkerText(_item) { return ""; }
async function fetchBacktestPositionSnapshot() { return null; }
function renderBacktestPositionSnapshotStatus(_text) { }
function refreshOptunaControlsVisibility() { }
/* --- view stubs (board_*.js 瑕嗙洊) --- */
async function backfillMorphSignalsForRange(_fromTs, _toTs) { }
function bindMorphWindowChartInteractionGuard() { }
function clearMorphPatternOverlay(_resetLast = true) { }
function drawMorphPatternOverlayForDay(_chartTime) { }
function getMorphPrimarySignalKey() { return ""; }
function getMorphSummaryPoints() { return []; }
function installMorphPanelUi() { }
async function refreshMorphSignalData(_isInitialLoad = false) { renderSignalData(); }
function renderMorphSignalData() { signalSeries.setData([]); syncSignalChartViewportFromMain(); }
function replaceMorphBarsWindow(rawBars) { mergeBars(rawBars); }
function resetMorphWindowState() { }
function scheduleMorphOverlayViewportRedraw() { }
function shouldUseMorphBarWindow() { return false; }
function applySignalSlotBindingUi() { }
async function clearExtraActiveFactors() { }
function getAdHocActiveFactorNames() { return []; }
function getBoundSignalSlotFactorNames() { return new Set(); }
function getSignalTypeToggleState() { return {}; }
function getVisibleSignalSlots() { return []; }
function installFactorSnapshotFilterUi() { }
async function loadFactorOptions() { }
async function refreshCenterBottomPanel() { }
function persistQuantFactorUi() { }
async function refreshSignalData(_isInitialLoad = false) { }
async function refreshSlotBoundSignalData(_isInitialLoad = false) { }
function renderQuantSignalData() { signalSeries.setData([]); syncSignalChartViewportFromMain(); }
function restoreQuantFactorUi() { }
function scheduleFactorSnapshotForRightPanel(_timeValue, _immediate = false) { }
function setFactorSnapshotFilterUiVisible(_visible) { }
async function toggleFactorActiveState(_factorName) { }
function updateExportFactorOptions() { }
function applySignalTypeToggleUi() { }
async function toggleSignalSlotByKey(_slotKey) { }
function beginFactorSnapshotDrag() { }
function moveFactorSnapshotDrag() { }
async function endFactorSnapshotDrag() { }
function beginFactorGroupDrag() { }
function moveFactorGroupDrag() { }
async function endFactorGroupDrag() { }
async function runFactorCoupleFromUi() { }
/* --- end view stubs --- */

const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#131722" }, textColor: "#d1d4dc", attributionLogo: false },
    grid: { vertLines: { color: "#2b2b2b" }, horzLines: { color: "#2b2b2b" } },
    leftPriceScale: {
        visible: false,
        borderColor: "#2b2b2b",
        minimumWidth: LEFT_PRICE_SCALE_MIN_WIDTH_PX
    },
    rightPriceScale: {
        autoScale: true,
        borderColor: "#2b2b2b",
        minimumWidth: RIGHT_PRICE_SCALE_MIN_WIDTH_PX
    },
    localization: {
        timeFormatter: formatXAxisTimeLabel
    },
    timeScale: {
        timeVisible: true,
        borderColor: "#2b2b2b",
        ...TIME_SCALE_DATA_CLAMP
    },
    crosshair: {
        horzLine: {
            labelBackgroundColor: "#3b82f6"
        },
        vertLine: {
            labelBackgroundColor: "#3b82f6"
        }
    }
});

const A_SHARE_UP_COLOR = "#ef5350";
const A_SHARE_DOWN_COLOR = "#26a69a";

function getAShareBarColor(bar) {
    return Number(bar && bar.close) >= Number(bar && bar.open) ? A_SHARE_UP_COLOR : A_SHARE_DOWN_COLOR;
}

const candlestickSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: A_SHARE_UP_COLOR,
    downColor: A_SHARE_DOWN_COLOR,
    borderVisible: false,
    wickUpColor: A_SHARE_UP_COLOR,
    wickDownColor: A_SHARE_DOWN_COLOR
});
const mainLineSeries = chart.addSeries(LightweightCharts.LineSeries, {
    color: "#3b82f6",
    lineWidth: 2,
    crosshairMarkerVisible: true,
    crosshairMarkerRadius: 3,
    priceFormat: { type: "price", precision: 4, minMove: 0.0001 }
});
const benchmarkLineSeries = chart.addSeries(LightweightCharts.LineSeries, {
    color: "#facc15",
    lineWidth: 2,
    crosshairMarkerVisible: false,
    priceFormat: { type: "price", precision: 4, minMove: 0.0001 }
});
const INDEX_OVERLAY_LINE_COLOR = "#22c55e";
const PORTFOLIO_INDEX_OVERLAY_STORAGE_KEY = "portfolio_index_overlay_code_v1";
const indexOverlayLineSeries = chart.addSeries(LightweightCharts.LineSeries, {
    color: INDEX_OVERLAY_LINE_COLOR,
    lineWidth: 3,
    crosshairMarkerVisible: true,
    crosshairMarkerRadius: 4,
    priceFormat: { type: "price", precision: 4, minMove: 0.0001 }
});
const volumeSeries = chart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: "volume" },
    priceScaleId: "volume-scale"
});
chart.priceScale("volume-scale").applyOptions({
    scaleMargins: { top: 0.88, bottom: 0.0 },
    visible: false
});
function normalizeCodeValue(codeValue) {
    return String(codeValue || "").trim().toUpperCase();
}

function formatPositionSnapshotCode(codeValue) {
    const raw = String(codeValue || "").trim();
    if (!raw) {
        return "";
    }
    const dotIdx = raw.indexOf(".");
    return dotIdx > 0 ? raw.slice(0, dotIdx) : raw;
}

function isCurveLineCode(codeValue) {
    return CURVE_LINE_CODES.has(normalizeCodeValue(codeValue));
}

function isMainChartLineMode() {
    return isCurveLineCode(currentCode);
}

function shouldShowBenchmarkOverlay() {
    return normalizeCodeValue(currentCode) === PORTFOLIO_MAIN_CURVE_CODE && currentInterval === "1day";
}

function getPortfolioChartLegendStrategyLabel() {
    if (normalizeCodeValue(currentCode) === PORTFOLIO_MAIN_CURVE_CODE) {
        return "策略曲线";
    }
    if (ykrsCurveSelect && ykrsCurveSelect.selectedOptions.length) {
        const text = String(ykrsCurveSelect.selectedOptions[0].textContent || "").trim();
        if (text) {
            return text;
        }
    }
    return "主曲线";
}

function getPortfolioChartLegendIndexLabel() {
    if (!portfolioExtraSelect || !portfolioExtraSelect.selectedOptions.length) {
        return "指数叠加";
    }
    const option = portfolioExtraSelect.selectedOptions[0];
    const dataName = String(option.dataset.indexName || "").trim();
    if (dataName) {
        return dataName;
    }
    const text = String(option.textContent || "").trim();
    const withoutCode = text.replace(/\s*\([^)]*\)\s*$/, "").trim();
    return withoutCode || "指数叠加";
}

function getBacktestRangeBars(barList) {
    if (!Array.isArray(barList) || !barList.length) {
        return [];
    }
    if (!barsCache.length) {
        return barList;
    }
    const fromTs = alignToCurrentInterval(Number(barsCache[0].time));
    const toTs = alignToCurrentInterval(Number(barsCache[barsCache.length - 1].time));
    if (!Number.isFinite(fromTs) || !Number.isFinite(toTs)) {
        return barList;
    }
    const filtered = barList.filter((bar) => {
        const t = alignToCurrentInterval(Number(bar.time));
        return Number.isFinite(t) && t >= fromTs && t <= toTs;
    });
    return filtered.length ? filtered : barList;
}

function computeTotalReturnPctFromBars(barList) {
    const scoped = getBacktestRangeBars(barList);
    if (!scoped.length) {
        return null;
    }
    const sorted = [...scoped].sort((a, b) => Number(a.time) - Number(b.time));
    const first = Number(sorted[0].close);
    const last = Number(sorted[sorted.length - 1].close);
    if (!Number.isFinite(first) || !Number.isFinite(last) || Math.abs(first) < 1e-12) {
        return null;
    }
    return ((last / first) - 1) * 100;
}

function formatPortfolioLegendReturnPct(pct) {
    if (pct == null || !Number.isFinite(pct)) {
        return "";
    }
    const sign = pct >= 0 ? "+" : "";
    return ` ${sign}${pct.toFixed(2)}%`;
}

function buildPortfolioLegendLabelText(baseLabel, barList) {
    const label = String(baseLabel || "").trim() || "--";
    const suffix = formatPortfolioLegendReturnPct(computeTotalReturnPctFromBars(barList));
    return suffix ? `${label}${suffix}` : label;
}

function updatePortfolioChartLegend() {
    if (!portfolioChartLegend) {
        return;
    }
    const showLegend = Boolean(PAGE_BOOT.allowYkrsCurve && isMainChartLineMode() && barsCache.length > 0);
    portfolioChartLegend.classList.toggle("is-visible", showLegend);
    portfolioChartLegend.hidden = !showLegend;
    if (!showLegend) {
        return;
    }
    if (chartLegendStrategyLabel) {
        chartLegendStrategyLabel.textContent = buildPortfolioLegendLabelText(
            getPortfolioChartLegendStrategyLabel(),
            barsCache
        );
    }
    const showBenchmark = shouldShowBenchmarkOverlay() && benchmarkBarsCache.length > 0;
    if (chartLegendBenchmarkItem) {
        chartLegendBenchmarkItem.hidden = !showBenchmark;
    }
    if (chartLegendBenchmarkLabel && showBenchmark) {
        chartLegendBenchmarkLabel.textContent = buildPortfolioLegendLabelText(
            "绛夐鎸佷粨",
            benchmarkBarsCache
        );
    }
    const indexLineData = buildRebasedIndexOverlayLineData();
    const showIndex = shouldShowIndexOverlay() && indexLineData.length > 0;
    if (chartLegendIndexItem) {
        chartLegendIndexItem.hidden = !showIndex;
    }
    if (chartLegendIndexLabel && showIndex) {
        chartLegendIndexLabel.textContent = buildPortfolioLegendLabelText(
            getPortfolioChartLegendIndexLabel(),
            indexOverlayBarsCache
        );
    }
}

async function refreshBenchmarkOverlay() {
    if (!shouldShowBenchmarkOverlay() || !barsCache.length) {
        benchmarkBarsCache = [];
        return;
    }
    const fromTs = Number(barsCache[0].time);
    const toTs = Number(barsCache[barsCache.length - 1].time);
    const payload = await fetchBars(BENCHMARK_CURVE_CODE, fromTs, toTs, null, { allowNotFound: true });
    benchmarkBarsCache = Array.isArray(payload.bars) ? payload.bars : [];
}

function shouldShowIndexOverlay() {
    return Boolean(
        PAGE_BOOT.allowYkrsCurve &&
        selectedPortfolioIndexCode &&
        currentInterval === "1day" &&
        barsCache.length > 0
    );
}

function getBarsCacheTimeRange() {
    if (!barsCache.length) {
        return null;
    }
    const fromTs = Number(barsCache[0].time);
    const toTs = Number(barsCache[barsCache.length - 1].time);
    if (!Number.isFinite(fromTs) || !Number.isFinite(toTs) || fromTs > toTs) {
        return null;
    }
    return { fromTs, toTs };
}

async function resolveIndexOverlayTimeRange() {
    try {
        const backtestRange = await resolveYkrsDailyBarWindow();
        if (
            backtestRange &&
            Number.isFinite(backtestRange.fromTs) &&
            Number.isFinite(backtestRange.toTs) &&
            backtestRange.fromTs <= backtestRange.toTs
        ) {
            return backtestRange;
        }
    } catch (err) {
        console.warn("resolveIndexOverlayTimeRange 回测窗口对齐失败", err);
    }
    return getBarsCacheTimeRange();
}

function chartVisibleTimeToUnixSeconds(chartTime) {
    if (chartTime == null || chartTime === undefined) {
        return NaN;
    }
    if (typeof chartTime === "number") {
        return alignToCurrentInterval(chartTime);
    }
    if (typeof chartTime === "object" && Number.isFinite(chartTime.year)) {
        const utcMs = Date.UTC(
            Number(chartTime.year),
            Number(chartTime.month) - 1,
            Number(chartTime.day)
        );
        return alignToCurrentInterval(Math.floor(utcMs / 1000));
    }
    return NaN;
}

/** 当前主图可见窗口左侧时间，用于指数曲线和蓝线左端对齐。 */
function getVisibleViewportLeftUnixTime() {
    const timeRange = chart.timeScale().getVisibleRange();
    if (timeRange && timeRange.from !== undefined) {
        const leftTs = chartVisibleTimeToUnixSeconds(timeRange.from);
        if (Number.isFinite(leftTs)) {
            return leftTs;
        }
    }
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (logicalRange && barsCache.length) {
        const idx = Math.max(0, Math.min(barsCache.length - 1, Math.floor(Number(logicalRange.from) + 0.5)));
        const bar = barsCache[idx];
        if (bar) {
            return alignToCurrentInterval(Number(bar.time));
        }
    }
    return barsCache.length ? alignToCurrentInterval(Number(barsCache[0].time)) : NaN;
}

function resolveIndexOverlayAnchor(portfolioByTime, indexByTime) {
    const leftTs = getVisibleViewportLeftUnixTime();
    let fallback = null;
    for (const bar of barsCache) {
        const t = alignToCurrentInterval(Number(bar.time));
        const portfolioClose = portfolioByTime.get(t);
        const indexClose = indexByTime.get(t);
        if (!Number.isFinite(portfolioClose) || !Number.isFinite(indexClose) || indexClose === 0) {
            continue;
        }
        const candidate = { time: t, portfolioClose, indexClose };
        if (!fallback) {
            fallback = candidate;
        }
        if (Number.isFinite(leftTs) && t >= leftTs) {
            return candidate;
        }
    }
    return fallback;
}

function buildRebasedIndexOverlayLineData() {
    if (!indexOverlayBarsCache.length || !barsCache.length) {
        return [];
    }
    const indexByTime = new Map();
    for (const bar of indexOverlayBarsCache) {
        const t = alignToCurrentInterval(Number(bar.time));
        const close = Number(bar.close);
        if (Number.isFinite(t) && Number.isFinite(close)) {
            indexByTime.set(t, close);
        }
    }
    const portfolioByTime = new Map();
    for (const bar of barsCache) {
        const t = alignToCurrentInterval(Number(bar.time));
        const close = Number(bar.close);
        if (Number.isFinite(t) && Number.isFinite(close)) {
            portfolioByTime.set(t, close);
        }
    }
    const anchor = resolveIndexOverlayAnchor(portfolioByTime, indexByTime);
    if (!anchor) {
        return [];
    }
    const paired = [];
    for (const bar of barsCache) {
        const t = alignToCurrentInterval(Number(bar.time));
        const indexClose = indexByTime.get(t);
        if (Number.isFinite(indexClose)) {
            paired.push({ time: t, indexClose });
        }
    }
    if (!paired.length) {
        return [];
    }
    const { portfolioClose: portfolioAnchor, indexClose: indexAnchor } = anchor;
    return paired.map((item) => ({
        time: toChartTime(item.time),
        value: portfolioAnchor * (item.indexClose / indexAnchor)
    }));
}

let indexOverlayViewportRefreshRaf = 0;
function scheduleIndexOverlayViewportRefresh() {
    if (!shouldShowIndexOverlay() || !indexOverlayBarsCache.length) {
        return;
    }
    if (indexOverlayViewportRefreshRaf) {
        cancelAnimationFrame(indexOverlayViewportRefreshRaf);
    }
    indexOverlayViewportRefreshRaf = requestAnimationFrame(() => {
        indexOverlayViewportRefreshRaf = 0;
        const indexLineData = buildRebasedIndexOverlayLineData();
        const showIndexOverlay = indexLineData.length > 0;
        indexOverlayLineSeries.setData(showIndexOverlay ? indexLineData : []);
        applyIndexOverlaySeriesVisibility();
    });
}

async function apiSupportsIndexOverlay() {
    try {
        const resp = await fetch(`${API_BASE_URL}/api/health`, { method: "GET", cache: "no-store" });
        const body = await resp.json();
        if (!resp.ok) {
            return false;
        }
        const features = Array.isArray(body.features) ? body.features : [];
        return features.includes("index_bars") && features.includes("index_codes");
    } catch (_) {
        return false;
    }
}

function isIndexRouteMissingResponse(status, body) {
    if (status !== 404) {
        return false;
    }
    const message = body && body.error && body.error.message ? String(body.error.message) : "";
    return message.includes("璇锋眰鐨勬帴鍙ｄ笉瀛樺湪");
}

async function fetchIndexOverlayBars(fromTs, toTs) {
    const code = selectedPortfolioIndexCode;
    if (!code) {
        return [];
    }
    const baseParams = {
        code,
        from: String(fromTs),
        to: String(toTs),
        limit: "5000"
    };
    const tryUrls = [
        `${API_BASE_URL}/api/market/index/bars?${new URLSearchParams(baseParams)}`,
        `${API_BASE_URL}/api/market/bars?${new URLSearchParams({ ...baseParams, interval: "1day" })}`
    ];
    for (const url of tryUrls) {
        try {
            const resp = await fetch(url, { method: "GET", cache: "no-store" });
            let body = {};
            try {
                body = await resp.json();
            } catch (_) {
                body = {};
            }
            if (resp.ok && Array.isArray(body.bars)) {
                return body.bars;
            }
            if (resp.status === 404 && (isNoDataErrorResponse(resp.status, body) || isIndexRouteMissingResponse(resp.status, body))) {
                continue;
            }
        } catch (err) {
            console.warn("fetchIndexOverlayBars", url, err);
        }
    }
    return [];
}

async function refreshIndexOverlay() {
    if (!shouldShowIndexOverlay() || !selectedPortfolioIndexCode) {
        indexOverlayBarsCache = [];
        return;
    }
    if (!(await apiSupportsIndexOverlay())) {
        indexOverlayBarsCache = [];
        return;
    }
    const cacheRange = getBarsCacheTimeRange();
    if (!cacheRange) {
        indexOverlayBarsCache = [];
        return;
    }
    let bars = await fetchIndexOverlayBars(cacheRange.fromTs, cacheRange.toTs);
    if (!bars.length) {
        const range = await resolveIndexOverlayTimeRange();
        if (range) {
            bars = await fetchIndexOverlayBars(range.fromTs, range.toTs);
        }
    }
    indexOverlayBarsCache = bars;
}

async function syncIndexOverlayAfterBarsRefresh() {
    if (!selectedPortfolioIndexCode) {
        return;
    }
    await applyPortfolioIndexOverlaySelection(false);
}

async function refreshChartOverlays() {
    await refreshBenchmarkOverlay();
    if (!selectedPortfolioIndexCode) {
        indexOverlayBarsCache = [];
        return;
    }
    try {
        await refreshIndexOverlay();
    } catch (err) {
        console.warn("refreshIndexOverlay", err);
        indexOverlayBarsCache = [];
    }
}

function applyIndexOverlaySeriesVisibility() {
    const lineData = buildRebasedIndexOverlayLineData();
    const visible = lineData.length > 0;
    try {
        indexOverlayLineSeries.applyOptions({
            visible,
            color: INDEX_OVERLAY_LINE_COLOR,
            lineWidth: 3
        });
    } catch (err) {
        console.warn("applyIndexOverlaySeriesVisibility", err);
    }
}

function getActiveMainSeries() {
    return isMainChartLineMode() ? mainLineSeries : candlestickSeries;
}

function applyMainChartSeriesMode() {
    chart.priceScale("right").applyOptions({
        scaleMargins: isMainChartLineMode()
            ? { top: 0.08, bottom: 0.08 }
            : { top: 0.08, bottom: 0.26 },
    });
}

applyMainChartSeriesMode();

const signalChart = LightweightCharts.createChart(signalChartContainer, {
    layout: { background: { color: "#131722" }, textColor: "#d1d4dc", attributionLogo: false },
    grid: { vertLines: { color: "#2b2b2b" }, horzLines: { color: "#2b2b2b" } },
    leftPriceScale: {
        visible: false,
        borderColor: "#2b2b2b",
        minimumWidth: LEFT_PRICE_SCALE_MIN_WIDTH_PX
    },
    rightPriceScale: {
        autoScale: true,
        borderColor: "#2b2b2b",
        minimumWidth: RIGHT_PRICE_SCALE_MIN_WIDTH_PX
    },
    localization: {
        timeFormatter: formatXAxisTimeLabel
    },
    crosshair: {
        horzLine: {
            labelBackgroundColor: "#ef5350"
        }
    },
    // 副图显示底部时间轴，并与主图保持同步。
    timeScale: {
        visible: true,
        timeVisible: true,
        borderColor: "#2b2b2b",
        ...TIME_SCALE_DATA_CLAMP
    },
    // 副图只跟随主图时间轴，避免双向联动导致视图抖动。
    handleScroll: false,
    handleScale: false
});
const signalSeries = signalChart.addSeries(LightweightCharts.LineSeries, {
    // 因子可能是离散信号，也可能是连续强度值；保留小数精度避免丢失细节。
    priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
    // 浣跨敤鍙充晶涓讳环鏍艰酱锛岀‘淇濆壇鍥炬渶鍙虫樉绀?Y 杞?
    priceScaleId: "right",
    color: "#3b82f6",
    lineWidth: 2,
    crosshairMarkerVisible: true,
    crosshairMarkerRadius: 3
});
signalChart.priceScale("right").applyOptions({
    visible: true,
    borderColor: "#2b2b2b",
    minimumWidth: RIGHT_PRICE_SCALE_MIN_WIDTH_PX,
    scaleMargins: { top: 0.1, bottom: 0.05 }
});

const PORTFOLIO_CHART_THEME_DARK = {
    layout: { background: { color: "#131722" }, textColor: "#d1d4dc", attributionLogo: false },
    grid: { vertLines: { color: "#2b2b2b" }, horzLines: { color: "#2b2b2b" } },
    rightPriceScale: { borderColor: "#2b2b2b" },
    leftPriceScale: { borderColor: "#2b2b2b" },
    timeScale: { borderColor: "#2b2b2b" },
    crosshair: {
        horzLine: { labelBackgroundColor: "#3b82f6" },
        vertLine: { labelBackgroundColor: "#3b82f6" },
    },
};
const PORTFOLIO_CHART_THEME_LIGHT = {
    layout: { background: { color: "#ffffff" }, textColor: "#1e293b", attributionLogo: false },
    grid: { vertLines: { color: "#e2e8f0" }, horzLines: { color: "#e2e8f0" } },
    rightPriceScale: { borderColor: "#cbd5e1" },
    leftPriceScale: { borderColor: "#cbd5e1" },
    timeScale: { borderColor: "#cbd5e1" },
    crosshair: {
        horzLine: { labelBackgroundColor: "#64748b" },
        vertLine: { labelBackgroundColor: "#64748b" },
    },
};

window.setPortfolioPrintLightCharts = function setPortfolioPrintLightCharts(on) {
    const light = Boolean(on);
    const theme = light ? PORTFOLIO_CHART_THEME_LIGHT : PORTFOLIO_CHART_THEME_DARK;
    chart.applyOptions(theme);
    signalChart.applyOptions({
        ...theme,
        crosshair: {
            horzLine: { labelBackgroundColor: light ? "#64748b" : "#ef5350" },
            vertLine: { labelBackgroundColor: light ? "#64748b" : "#ef5350" },
        },
    });
    mainLineSeries.applyOptions({ color: "#3b82f6" });
    benchmarkLineSeries.applyOptions({ color: "#facc15" });
    indexOverlayLineSeries.applyOptions({ color: INDEX_OVERLAY_LINE_COLOR });
    signalSeries.applyOptions({ color: "#3b82f6" });
};

const PORTFOLIO_PRINT_LIGHT_STORAGE_KEY = "result_print_light_v1";

function readPortfolioPrintLightSaved() {
    try {
        return sessionStorage.getItem(PORTFOLIO_PRINT_LIGHT_STORAGE_KEY) === "1";
    } catch (_) {
        return false;
    }
}

function savePortfolioPrintLightState(on) {
    try {
        if (on) {
            sessionStorage.setItem(PORTFOLIO_PRINT_LIGHT_STORAGE_KEY, "1");
        } else {
            sessionStorage.removeItem(PORTFOLIO_PRINT_LIGHT_STORAGE_KEY);
        }
    } catch (_) {
        /* ignore */
    }
}

function applyPortfolioPrintLight(on) {
    const light = Boolean(on);
    portfolioExtraDayOn = light;
    document.documentElement.classList.toggle("portfolio-print-light", light);
    setPortfolioExtraDayToggle(light);
    window.setPortfolioPrintLightCharts(light);
    savePortfolioPrintLightState(light);
}
window.applyPortfolioPrintLight = applyPortfolioPrintLight;

function initPortfolioPrintLightToggleOnce() {
    if (!PAGE_BOOT.allowYkrsCurve || !portfolioExtraDayToggle) {
        return;
    }
    if (portfolioExtraDayToggle.dataset.printLightBound === "1") {
        return;
    }
    portfolioExtraDayToggle.dataset.printLightBound = "1";
    portfolioExtraDayToggle.addEventListener("click", (event) => {
        event.preventDefault();
        applyPortfolioPrintLight(!portfolioExtraDayOn);
    });
    applyPortfolioPrintLight(readPortfolioPrintLightSaved());
}

let syncTimeScaleLock = false;
let syncCrosshairLock = false;
/** 十字线输入：mouse 跟随指针；keyboard 用方向键逐根移动，不跟随鼠标直到指针回到主图/副图。 */
let crosshairInputMode = "mouse";
let keyboardCrosshairBarIndex = -1;
let lastMouseCrosshairBarIndex = -1;
let isCrosshairLocked = false;
let reapplyingKeyboardCrosshair = false;
function syncLogicalRange(primary, secondary) {
    const range = primary.timeScale().getVisibleLogicalRange();
    if (!range) {
        return;
    }
    syncTimeScaleLock = true;
    try {
        secondary.timeScale().setVisibleLogicalRange(range);
    } finally {
        syncTimeScaleLock = false;
    }
}

function syncVisibleTimeRange(primary, secondary) {
    const range = primary.timeScale().getVisibleRange();
    if (!range) {
        return;
    }
    syncTimeScaleLock = true;
    try {
        secondary.timeScale().setVisibleRange(range);
    } finally {
        syncTimeScaleLock = false;
    }
}

function applyChartTimeScaleBounds() {
    if (shouldUseMorphBarWindow()) {
        applyMorphMainChartTimeScaleOptions();
    } else {
        chart.timeScale().applyOptions(TIME_SCALE_DATA_CLAMP);
    }
    if (!shouldHideSignalChartPanel()) {
        signalChart.timeScale().applyOptions(TIME_SCALE_DATA_CLAMP);
    }
}

function clampVisibleLogicalRangeToDataBounds(range) {
    if (!range || !barsCache.length) {
        return null;
    }
    const barCount = barsCache.length;
    const minFrom = -0.5;
    const maxTo = barCount - 0.5;
    const minSpan = 2;
    let from = Number(range.from);
    let to = Number(range.to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) {
        return null;
    }
    if (to - from < minSpan) {
        const center = (from + to) / 2;
        from = center - minSpan / 2;
        to = center + minSpan / 2;
    }
    if (from < minFrom) {
        to += minFrom - from;
        from = minFrom;
    }
    if (to > maxTo) {
        from -= to - maxTo;
        to = maxTo;
    }
    if (from < minFrom) {
        from = minFrom;
    }
    if (to > maxTo) {
        to = maxTo;
    }
    if (to - from < minSpan) {
        to = Math.min(maxTo, from + minSpan);
    }
    return { from, to };
}

function setMainChartVisibleLogicalRange(range) {
    const clamped = clampVisibleLogicalRangeToDataBounds(range);
    if (!clamped) {
        return;
    }
    chart.timeScale().setVisibleLogicalRange(clamped);
    syncSignalChartViewportFromMain();
}

/** 主图与因子副图按时间轴对齐；不要使用 logicalRange，因为两图 bar 数量常不一致。 */
function syncSignalChartViewportFromMain() {
    if (shouldHideSignalChartPanel()) {
        return;
    }
    const timeRange = chart.timeScale().getVisibleRange();
    if (!timeRange || timeRange.from === undefined || timeRange.to === undefined) {
        return;
    }
    syncTimeScaleLock = true;
    try {
        signalChart.timeScale().setVisibleRange(timeRange);
    } catch (err) {
        try {
            signalChart.timeScale().fitContent();
        } catch (_) {
            /* ignore */
        }
    } finally {
        syncTimeScaleLock = false;
    }
}

function shiftMainChartVisibleLogicalRange(offsetBars) {
    const offset = Number(offsetBars);
    if (!Number.isFinite(offset) || Math.abs(offset) < 0.001) {
        return;
    }
    const currentRange = chart.timeScale().getVisibleLogicalRange();
    if (!currentRange) {
        return;
    }
    setMainChartVisibleLogicalRange({
        from: Number(currentRange.from) + offset,
        to: Number(currentRange.to) + offset,
    });
}

function getVisibleLogicalRangeSafe() {
    const range = chart.timeScale().getVisibleLogicalRange();
    if (!range) {
        return null;
    }
    const from = Number(range.from);
    const to = Number(range.to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) {
        return null;
    }
    return { from, to };
}

function pruneMinuteOffscreenBars() {
    if (currentInterval !== "1min" || shouldUseMorphBarWindow() || !barsCache.length) {
        return;
    }
    const range = getVisibleLogicalRangeSafe();
    if (!range) {
        return;
    }
    const keepFrom = Math.max(0, Math.floor(range.from) - MINUTE_OFFSCREEN_PRUNE_BUFFER_BARS);
    const keepTo = Math.min(
        barsCache.length,
        Math.ceil(range.to) + 1 + MINUTE_OFFSCREEN_PRUNE_BUFFER_BARS
    );
    if (keepFrom <= 0 && keepTo >= barsCache.length) {
        return;
    }
    const removedLeft = keepFrom;
    barsCache = barsCache.slice(keepFrom, keepTo);
    lastBarTime = barsCache.length > 0 ? Number(barsCache[barsCache.length - 1].time) : null;
    rebuildBarsDayIndexMap();
    renderChartData();
    setMainChartVisibleLogicalRange({
        from: range.from - removedLeft,
        to: range.to - removedLeft,
    });
}

function scheduleMinuteOffscreenPrune() {
    if (minuteOffscreenPruneTimer) {
        clearTimeout(minuteOffscreenPruneTimer);
        minuteOffscreenPruneTimer = null;
    }
    if (currentInterval !== "1min" || shouldUseMorphBarWindow()) {
        return;
    }
    minuteOffscreenPruneTimer = setTimeout(() => {
        minuteOffscreenPruneTimer = null;
        pruneMinuteOffscreenBars();
    }, MINUTE_OFFSCREEN_PRUNE_DELAY_MS);
}

function formatCaptionPrice(value) {
    return Number.isFinite(value) ? value.toFixed(3) : "--";
}

function formatCaptionVolume(value) {
    if (!Number.isFinite(value)) {
        return "--";
    }
    const rounded = Math.round(value);
    return rounded.toLocaleString("en-US");
}

function formatCaptionPct(value) {
    if (!Number.isFinite(value)) {
        return "--";
    }
    const sign = value > 0 ? "+" : "";
    return `${sign}${value.toFixed(2)}%`;
}

function calcDailyChangePct(prevClose, close) {
    if (!Number.isFinite(prevClose) || !Number.isFinite(close) || prevClose === 0) {
        return NaN;
    }
    return ((close - prevClose) / prevClose) * 100;
}

function calcDailyChangePctByBarIndex(barIndex, close) {
    if (!Number.isInteger(barIndex) || barIndex <= 0 || barIndex >= barsCache.length) {
        return NaN;
    }
    const prevBar = barsCache[barIndex - 1];
    const prevClose = Number(prevBar && prevBar.close);
    return calcDailyChangePct(prevClose, close);
}

function calcDailyChangePctByChartTime(chartTime, close) {
    const barIndex = findBarIndexByChartTime(chartTime);
    return calcDailyChangePctByBarIndex(barIndex, close);
}

function updateSignalCaptionFromCrosshair(param) {
    if (!signalCaptionOhlcv) {
        return;
    }
    if (!param || param.time === undefined || !param.seriesData) {
        signalCaptionOhlcv.textContent = "O: -- H: -- L: -- C: -- V: -- 娑ㄨ穼骞? --";
        return;
    }
    const candle = param.seriesData.get(candlestickSeries);
    const linePoint = param.seriesData.get(mainLineSeries);
    const volume = param.seriesData.get(volumeSeries);
    if (linePoint && typeof linePoint === "object" && "value" in linePoint) {
        const close = Number(linePoint.value);
        signalCaptionOhlcv.textContent =
            `O: ${formatCaptionPrice(close)} ` +
            `H: ${formatCaptionPrice(close)} ` +
            `L: ${formatCaptionPrice(close)} ` +
            `C: ${formatCaptionPrice(close)} ` +
            "V: 0 " +
            "娑ㄨ穼骞? --";
        return;
    }
    if (!candle || typeof candle !== "object") {
        signalCaptionOhlcv.textContent = "O: -- H: -- L: -- C: -- V: -- 娑ㄨ穼骞? --";
        return;
    }
    const open = Number(candle.open);
    const high = Number(candle.high);
    const low = Number(candle.low);
    const close = Number(candle.close);
    const vol = volume && typeof volume === "object" ? Number(volume.value) : NaN;
    signalCaptionOhlcv.textContent =
        `O: ${formatCaptionPrice(open)} ` +
        `H: ${formatCaptionPrice(high)} ` +
        `L: ${formatCaptionPrice(low)} ` +
        `C: ${formatCaptionPrice(close)} ` +
        `V: ${formatCaptionVolume(vol)} ` +
        `娑ㄨ穼骞? ${formatCaptionPct(calcDailyChangePctByChartTime(param.time, close))}`;
}

function normalizeTimeToSeconds(timeValue) {
    if (typeof timeValue === "number") {
        return alignToCurrentInterval(timeValue);
    }
    if (
        timeValue &&
        typeof timeValue === "object" &&
        "year" in timeValue &&
        "month" in timeValue &&
        "day" in timeValue
    ) {
        const y = Number(timeValue.year);
        const m = Number(timeValue.month);
        const d = Number(timeValue.day);
        if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) {
            return NaN;
        }
        const ts = Math.floor(Date.UTC(y, m - 1, d, 0, 0, 0) / 1000);
        return alignToCurrentInterval(ts);
    }
    return NaN;
}

async function resolveYkrsDailyBarWindow() {
    const runTag = getSelectedRunTag();
    if (!runTag) {
        ykrsDailyBarWindowCached = null;
        ykrsDailyBarWindowCacheUntil = 0;
        ykrsDailyBarWindowCachedRunTag = "";
        return null;
    }
    const ttlMs = 12000;
    if (
        ykrsDailyBarWindowCached &&
        Date.now() < ykrsDailyBarWindowCacheUntil &&
        ykrsDailyBarWindowCachedRunTag === runTag
    ) {
        return ykrsDailyBarWindowCached;
    }
    try {
        const summary = await fetchBacktestSummaryForActiveRun();
        const br = getBacktestRangeFromSummary(summary);
        if (br && Number.isFinite(br.fromTs) && Number.isFinite(br.toTs)) {
            ykrsDailyBarWindowCached = br;
            ykrsDailyBarWindowCacheUntil = Date.now() + ttlMs;
            ykrsDailyBarWindowCachedRunTag = runTag;
            return br;
        }
    } catch (err) {
        console.warn("resolveYkrsDailyBarWindow 失败", err);
    }
    ykrsDailyBarWindowCached = null;
    ykrsDailyBarWindowCacheUntil = 0;
    ykrsDailyBarWindowCachedRunTag = "";
    return null;
}

function formatPositionSnapshotNumber(value, digits = 2) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
        return "---";
    }
    return n.toFixed(digits);
}

function formatPositionSnapshotPercent(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
        return "---";
    }
    return `${(n * 100).toFixed(2)}%`;
}

function beginRightPanelSnapshotInteraction() {
    rightPanelSnapshotInteractionId += 1;
    rightPanelSnapshotPausedInteractionId = -1;
}

function pauseRightPanelSnapshotRequestsForInteraction() {
    rightPanelSnapshotPausedInteractionId = rightPanelSnapshotInteractionId;
}

function isRightPanelSnapshotRequestPaused() {
    return rightPanelSnapshotPausedInteractionId === rightPanelSnapshotInteractionId;
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function colorWithAlpha(colorText, alpha) {
    const color = String(colorText || "").trim();
    const a = Number(alpha);
    const alphaValue = Number.isFinite(a) ? Math.max(0, Math.min(1, a)) : 1;

    const hex6 = color.match(/^#([0-9a-fA-F]{6})$/);
    if (hex6) {
        const h = hex6[1];
        const r = Number.parseInt(h.slice(0, 2), 16);
        const g = Number.parseInt(h.slice(2, 4), 16);
        const b = Number.parseInt(h.slice(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${alphaValue})`;
    }

    const hex3 = color.match(/^#([0-9a-fA-F]{3})$/);
    if (hex3) {
        const h = hex3[1];
        const r = Number.parseInt(h[0] + h[0], 16);
        const g = Number.parseInt(h[1] + h[1], 16);
        const b = Number.parseInt(h[2] + h[2], 16);
        return `rgba(${r}, ${g}, ${b}, ${alphaValue})`;
    }

    const rgb = color.match(/^rgba?\(([^)]+)\)$/i);
    if (rgb) {
        const parts = rgb[1].split(",").map((x) => x.trim());
        if (parts.length >= 3) {
            const r = Number(parts[0]);
            const g = Number(parts[1]);
            const b = Number(parts[2]);
            if (Number.isFinite(r) && Number.isFinite(g) && Number.isFinite(b)) {
                return `rgba(${r}, ${g}, ${b}, ${alphaValue})`;
            }
        }
    }

    return `rgba(107, 156, 255, ${alphaValue})`;
}

function getFactorSeriesColor(factorName) {
    const slotKey = getSlotKeyForBoundFactor(factorName);
    if (slotKey) {
        return getSignalSlotSeriesColor(slotKey);
    }
    return getAdHocFactorSeriesColor(factorName);
}

function getFactorPoints(factorName) {
    return factorName === selectedFactorName
        ? signalPoints
        : (extraSignalPointsByFactor.get(factorName) || []);
}

function getFactorLastSeenTime(factorName) {
    return factorName === selectedFactorName
        ? lastSignalTime
        : (extraLastSignalTimeByFactor.get(factorName) ?? null);
}

function clearExtraSignalSeries(factorName) {
    const series = extraSignalSeriesByFactor.get(factorName);
    if (series) {
        signalChart.removeSeries(series);
        extraSignalSeriesByFactor.delete(factorName);
    }
}

function clearCoupledSignalLayer() {
    coupledSignalPoints = [];
    if (coupledSignalSeries) {
        try {
            signalChart.removeSeries(coupledSignalSeries);
        } catch (err) {
            // ignore
        }
        coupledSignalSeries = null;
    }
    const coupleCtl = document.getElementById("factor-snapshot-couple-btn");
    if (coupleCtl) {
        coupleCtl.classList.remove("active");
    }
}

function ensureCoupledSignalSeries() {
    if (coupledSignalSeries) {
        return coupledSignalSeries;
    }
    coupledSignalSeries = signalChart.addSeries(LightweightCharts.LineSeries, {
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        priceScaleId: "right",
        color: COUPLED_SIGNAL_LINE_COLOR,
        lineWidth: 2,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 3
    });
    return coupledSignalSeries;
}

function updateCoupledSignalOverlay() {
    if (!isQuantSignalTab() || !coupledSignalPoints.length || shouldHideSignalChartPanel() || currentInterval !== "1day" || isYkrsCode()) {
        if (coupledSignalSeries) {
            coupledSignalSeries.setData([]);
        }
        return;
    }
    const series = ensureCoupledSignalSeries();
    series.setData(buildSignalSeriesData(coupledSignalPoints));
}

function buildSignalSeriesData(points) {
    // 日线下将信号按主图交易日补齐，缺失补 0，避免副图时间点缺失导致十字线联动报错。
    if (currentInterval === "1day" && Array.isArray(barsCache) && barsCache.length > 0) {
        const valueByDay = new Map();
        for (const item of (Array.isArray(points) ? points : [])) {
            const ts = Number(item && item.time);
            const rawValue = Number(item && item.value);
            if (!Number.isFinite(ts) || !Number.isFinite(rawValue)) {
                continue;
            }
            valueByDay.set(alignToCurrentInterval(ts), rawValue);
        }

        const byDay = new Map();
        for (const bar of barsCache) {
            const barTs = Number(bar && bar.time);
            if (!Number.isFinite(barTs)) {
                continue;
            }
            const dayTs = alignToCurrentInterval(barTs);
            const value = valueByDay.has(dayTs) ? Number(valueByDay.get(dayTs)) : 0;
            const chartTime = toChartTime(dayTs);
            const key = chartTime && typeof chartTime === "object"
                ? `${chartTime.year}-${chartTime.month}-${chartTime.day}`
                : String(chartTime);
            byDay.set(key, { time: chartTime, value });
        }
        return Array.from(byDay.values());
    }

    const byTime = new Map();
    for (const item of (Array.isArray(points) ? points : [])) {
        const rawValue = Number(item && item.value);
        if (!Number.isFinite(rawValue)) {
            continue;
        }
        const chartTime = toChartTime(item.time);
        // 1day 模式下避免同一天多个点导致 BusinessDay 重复，从而序列不显示。
        let key = "";
        if (currentInterval === "1day" && chartTime && typeof chartTime === "object") {
            key = `${chartTime.year}-${chartTime.month}-${chartTime.day}`;
        } else {
            key = String(chartTime);
        }
        byTime.set(key, { time: chartTime, value: rawValue });
    }
    return Array.from(byTime.values());
}

function ensureExtraSignalSeries(factorName) {
    if (extraSignalSeriesByFactor.has(factorName)) {
        return extraSignalSeriesByFactor.get(factorName);
    }
    const series = signalChart.addSeries(LightweightCharts.LineSeries, {
        priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
        priceScaleId: "right",
        color: getFactorSeriesColor(factorName),
        lineWidth: 2,
        crosshairMarkerVisible: false
    });
    extraSignalSeriesByFactor.set(factorName, series);
    return series;
}

function promoteFactorToPrimary(factorName) {
    const nextFactor = String(factorName || "").trim();
    if (!nextFactor) {
        return;
    }
    const oldPrimary = selectedFactorName;
    if (oldPrimary === nextFactor) {
        if (factorSelect && Array.from(factorSelect.options).some((option) => option.value === nextFactor)) {
            factorSelect.value = nextFactor;
        }
        updateSignalCaptionTitle();
        persistFactorState();
        return;
    }

    const previousPrimaryPoints = signalPoints;
    const previousPrimaryLastTime = lastSignalTime;

    if (oldPrimary && activeFactorNames.includes(oldPrimary)) {
        extraSignalPointsByFactor.set(oldPrimary, previousPrimaryPoints);
        extraLastSignalTimeByFactor.set(oldPrimary, previousPrimaryLastTime);
    }

    signalPoints = extraSignalPointsByFactor.get(nextFactor) || [];
    lastSignalTime = extraLastSignalTimeByFactor.get(nextFactor) ?? null;
    extraSignalPointsByFactor.delete(nextFactor);
    extraLastSignalTimeByFactor.delete(nextFactor);
    clearExtraSignalSeries(nextFactor);

    selectedFactorName = nextFactor;
    if (factorSelect && Array.from(factorSelect.options).some((option) => option.value === nextFactor)) {
        factorSelect.value = nextFactor;
    }
    updateSignalCaptionTitle();
    persistFactorState();
}

function renderSignalData() {
    if (shouldHideSignalChartPanel()) {
        clearAllSignalChartSeries();
        signalCaptionTitle.textContent = "淇″彿: --";
        signalCaptionOhlcv.textContent = "O: -- H: -- L: -- C: -- V: --";
        updateCoupledSignalOverlay();
        return;
    }
    if (isMorphSignalTab()) {
        renderMorphSignalData();
        return;
    }
    if (!isQuantSignalTab()) {
        clearAllSignalChartSeries();
        if (coupledSignalSeries) {
            coupledSignalSeries.setData([]);
        }
        signalChart.priceScale("right").applyOptions({ autoScale: true });
        syncSignalChartViewportFromMain();
        return;
    }
    renderQuantSignalData();
}

function mergeFactorPoints(existingPoints, newPoints) {
    const byTime = new Map();
    for (const point of existingPoints) {
        byTime.set(Number(point.time), point);
    }
    for (const point of newPoints) {
        byTime.set(Number(point.time), point);
    }
    return Array.from(byTime.values()).sort((a, b) => Number(a.time) - Number(b.time));
}

function getSignalValueByTime(timeValue) {
    if (shouldHideSignalChartPanel()) {
        return NaN;
    }
    const target = normalizeTimeToSeconds(timeValue);
    if (!Number.isFinite(target)) {
        return NaN;
    }
    const points = isMorphSignalTab()
        ? (() => {
            const levelKey = getMorphPrimarySignalKey();
            const patternNames = levelKey && morphLoadedLevelKey === levelKey
                ? Array.from(morphPatternPointsByName.keys()).sort()
                : [];
            const primaryName = patternNames[0];
            if (primaryName) {
                return morphPatternPointsByName.get(primaryName) || [];
            }
            return getMorphSummaryPoints();
        })()
        : getPrimaryQuantSignalPoints();
    for (const item of points) {
        if (alignToCurrentInterval(Number(item.time)) === target) {
            return Number(item.value);
        }
    }
    // 与副图渲染逻辑一致：主图存在该时间点但因子缺失时按 0 显示，保证副图十字线可见。
    if (currentInterval === "1day") {
        for (const bar of barsCache) {
            if (alignToCurrentInterval(Number(bar.time)) === target) {
                return 0;
            }
        }
    }
    return NaN;
}

function isChartNavigationKeyBlocked() {
    const el = document.activeElement;
    if (!el || !(el instanceof HTMLElement)) {
        return false;
    }
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        return true;
    }
    if (el.isContentEditable) {
        return true;
    }
    return false;
}

function findBarIndexByChartTime(chartTime) {
    if (!barsCache.length) {
        return -1;
    }
    const target = normalizeTimeToSeconds(chartTime);
    if (!Number.isFinite(target)) {
        return -1;
    }
    const alignedTarget = alignToCurrentInterval(target);
    ensureBarsDayIndexMap();
    const idx = barsDayIndexMap.get(alignedTarget);
    return idx === undefined ? -1 : idx;
}

function resolveInitialKeyboardBarIndex() {
    if (!barsCache.length) {
        return -1;
    }
    const t = Number.isFinite(currentFactorSnapshotTime)
        ? currentFactorSnapshotTime
        : lastBarTime;
    if (Number.isFinite(t)) {
        const al = alignToCurrentInterval(Number(t));
        for (let i = 0; i < barsCache.length; i += 1) {
            if (alignToCurrentInterval(Number(barsCache[i].time)) === al) {
                return i;
            }
        }
    }
    return barsCache.length - 1;
}

/** 空格锁定 / 方向键起点：优先键盘当前格，其次鼠标十字线所在 K 线，最后使用右侧快照时间。 */
function resolveCrosshairLockBarIndex() {
    if (!barsCache.length) {
        return -1;
    }
    if (keyboardCrosshairBarIndex >= 0 && keyboardCrosshairBarIndex < barsCache.length) {
        return keyboardCrosshairBarIndex;
    }
    if (lastMouseCrosshairBarIndex >= 0 && lastMouseCrosshairBarIndex < barsCache.length) {
        return lastMouseCrosshairBarIndex;
    }
    const fallback = resolveInitialKeyboardBarIndex();
    if (fallback >= 0) {
        return fallback;
    }
    return barsCache.length - 1;
}

function exitKeyboardCrosshairMode() {
    if (isCrosshairLocked) {
        return;
    }
    if (crosshairInputMode !== "keyboard") {
        return;
    }
    crosshairInputMode = "mouse";
    keyboardCrosshairBarIndex = -1;
}

function toggleCrosshairLock() {
    if (!barsCache.length) {
        return;
    }
    if (isCrosshairLocked) {
        if (keyboardCrosshairBarIndex >= 0) {
            lastMouseCrosshairBarIndex = keyboardCrosshairBarIndex;
        }
        isCrosshairLocked = false;
        crosshairInputMode = "mouse";
        keyboardCrosshairBarIndex = -1;
        return;
    }
    const nextIndex = resolveCrosshairLockBarIndex();
    if (nextIndex < 0) {
        return;
    }
    isCrosshairLocked = true;
    applyKeyboardCrosshairAtIndex(nextIndex, { immediateSnapshot: true });
}

function applyKeyboardCrosshairAtIndex(index, options = {}) {
    const immediateSnapshot = options.immediateSnapshot !== false;
    if (!barsCache.length || index < 0 || index >= barsCache.length) {
        return;
    }
    keyboardCrosshairBarIndex = index;
    crosshairInputMode = "keyboard";
    const bar = barsCache[index];
    const tChart = toChartTime(bar.time);
    const close = Number(bar.close);
    const open = Number(bar.open);
    const high = Number(bar.high);
    const low = Number(bar.low);
    const vol = Number(bar.volume || 0);
    if (signalCaptionOhlcv) {
        signalCaptionOhlcv.textContent =
            `O: ${formatCaptionPrice(open)} ` +
            `H: ${formatCaptionPrice(high)} ` +
            `L: ${formatCaptionPrice(low)} ` +
            `C: ${formatCaptionPrice(close)} ` +
            `V: ${formatCaptionVolume(vol)} ` +
            `娑ㄨ穼骞? ${formatCaptionPct(calcDailyChangePctByBarIndex(index, close))}`;
    }
    const sigVal = getSignalValueByTime(tChart);
    reapplyingKeyboardCrosshair = true;
    try {
        if (typeof chart.setCrosshairPosition === "function" && Number.isFinite(close)) {
            chart.setCrosshairPosition(close, tChart, getActiveMainSeries());
        }
        if (typeof signalChart.setCrosshairPosition === "function") {
            if (Number.isFinite(sigVal)) {
                signalChart.setCrosshairPosition(sigVal, tChart, signalSeries);
            } else if (typeof signalChart.clearCrosshairPosition === "function") {
                signalChart.clearCrosshairPosition();
            }
        }
    } finally {
        reapplyingKeyboardCrosshair = false;
    }
    scheduleFactorSnapshotForRightPanel(Number(bar.time), immediateSnapshot);
}

function zoomPrimaryLogicalRange(zoomIn) {
    const range = chart.timeScale().getVisibleLogicalRange();
    if (!range || !barsCache.length) {
        return;
    }
    const n = barsCache.length;
    const stretch = zoomIn ? 0.82 : 1.22;
    const centerIdx =
        keyboardCrosshairBarIndex >= 0 ? keyboardCrosshairBarIndex + 0.5 : (range.from + range.to) / 2;
    let halfWidth = ((range.to - range.from) / 2) * stretch;
    const minHalf = 2;
    const maxHalf = Math.max(minHalf, n / 2);
    halfWidth = Math.min(Math.max(halfWidth, minHalf), maxHalf);
    let from = centerIdx - halfWidth;
    let to = centerIdx + halfWidth;
    if (from < -0.5) {
        to += -from - 0.5;
        from = -0.5;
    }
    if (to > n - 0.5) {
        from -= to - (n - 0.5);
        to = n - 0.5;
    }
    if (from < -0.5) {
        from = -0.5;
    }
    if (to > n - 0.5) {
        to = n - 0.5;
    }
    setMainChartVisibleLogicalRange({ from, to });
    if (!zoomIn) {
        scheduleBehaviorHistoryPrefetch();
    }
}

function isGlobalCodeInputTypingKey(key) {
    return /^[0-9a-zA-Z]$/.test(String(key || ""));
}

function applyGlobalCodeInputTyping(key) {
    if (!codeInput) {
        return;
    }
    clearCodeInputOnNextEdit = false;
    codeInput.focus();
    codeInput.value = key;
    codeInput.setSelectionRange(1, 1);
    hideCodeSuggestions();
    codeInput.dispatchEvent(new Event("input", { bubbles: true }));
}

function consumePendingCodeInputClear() {
    if (!clearCodeInputOnNextEdit || !codeInput) {
        return false;
    }
    clearCodeInputOnNextEdit = false;
    codeInput.value = "";
    hideCodeSuggestions();
    codeInput.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
}

function onGlobalChartNavigationKeydown(event) {
    const key = event.key;
    if (
        isMainBoardPage()
        && isGlobalCodeInputTypingKey(key)
        && !event.ctrlKey
        && !event.metaKey
        && !event.altKey
        && !event.isComposing
        && !isChartNavigationKeyBlocked()
    ) {
        event.preventDefault();
        applyGlobalCodeInputTyping(key);
        return;
    }
    if (isChartNavigationKeyBlocked()) {
        return;
    }
    if (key === " " || key === "Spacebar" || event.code === "Space") {
        if (!barsCache.length) {
            return;
        }
        event.preventDefault();
        toggleCrosshairLock();
        return;
    }
    if (key === "Enter") {
        const mask = document.getElementById("tv-day-modal-mask");
        if (mask && mask.classList.contains("visible")) {
            return;
        }
        const barIndex = resolveCrosshairLockBarIndex();
        if (openTvDayModalForBarIndex(barIndex)) {
            event.preventDefault();
        }
        return;
    }
    if (key !== "ArrowLeft" && key !== "ArrowRight" && key !== "ArrowUp" && key !== "ArrowDown") {
        return;
    }
    if (!barsCache.length) {
        return;
    }
    event.preventDefault();
    beginRightPanelSnapshotInteraction();
    crosshairInputMode = "keyboard";
    if (keyboardCrosshairBarIndex < 0) {
        keyboardCrosshairBarIndex = resolveCrosshairLockBarIndex();
    }
    if (keyboardCrosshairBarIndex < 0) {
        keyboardCrosshairBarIndex = barsCache.length - 1;
    }
    if (key === "ArrowLeft") {
        keyboardCrosshairBarIndex = Math.max(0, keyboardCrosshairBarIndex - 1);
        applyKeyboardCrosshairAtIndex(keyboardCrosshairBarIndex);
        return;
    }
    if (key === "ArrowRight") {
        keyboardCrosshairBarIndex = Math.min(barsCache.length - 1, keyboardCrosshairBarIndex + 1);
        applyKeyboardCrosshairAtIndex(keyboardCrosshairBarIndex);
        return;
    }
    if (key === "ArrowUp") {
        zoomPrimaryLogicalRange(true);
        applyKeyboardCrosshairAtIndex(keyboardCrosshairBarIndex, { immediateSnapshot: false });
        return;
    }
    if (key === "ArrowDown") {
        zoomPrimaryLogicalRange(false);
        applyKeyboardCrosshairAtIndex(keyboardCrosshairBarIndex, { immediateSnapshot: false });
    }
}

function bindTimeScaleSync(primary, secondary) {
    // 主图 -> 因子副图：仅按时间范围同步，避免数据条数不同时副图空白。
    primary.timeScale().subscribeVisibleLogicalRangeChange(() => {
        if (secondary === signalChart) {
            if (shouldHideSignalChartPanel() || syncTimeScaleLock) {
                return;
            }
            syncSignalChartViewportFromMain();
            return;
        }
        if (syncTimeScaleLock) {
            return;
        }
        syncLogicalRange(primary, secondary);
    });
    primary.timeScale().subscribeVisibleTimeRangeChange(() => {
        if (secondary === signalChart) {
            if (shouldHideSignalChartPanel() || syncTimeScaleLock) {
                return;
            }
            syncSignalChartViewportFromMain();
            return;
        }
        if (syncTimeScaleLock) {
            return;
        }
        syncVisibleTimeRange(primary, secondary);
    });
}

function bindCrosshairSync(primaryChart, secondaryChart, primarySeries, secondarySeries) {
    primaryChart.subscribeCrosshairMove((param) => {
        if (reapplyingKeyboardCrosshair) {
            return;
        }
        if (isCrosshairLocked && keyboardCrosshairBarIndex >= 0) {
            applyKeyboardCrosshairAtIndex(keyboardCrosshairBarIndex, { immediateSnapshot: false });
            return;
        }
        if (crosshairInputMode === "keyboard" && keyboardCrosshairBarIndex >= 0) {
            applyKeyboardCrosshairAtIndex(keyboardCrosshairBarIndex, { immediateSnapshot: false });
            return;
        }
        if (param && param.time !== undefined) {
            const hoverIndex = findBarIndexByChartTime(param.time);
            if (hoverIndex >= 0) {
                lastMouseCrosshairBarIndex = hoverIndex;
            }
        }
        updateSignalCaptionFromCrosshair(param);
        if (isMorphSignalTab()) {
            if (!param || param.time === undefined) {
                clearMorphPatternOverlay();
            } else {
                drawMorphPatternOverlayForDay(param.time);
            }
        }
        const hoverTime = param && param.time !== undefined ? param.time : lastBarTime;
        scheduleFactorSnapshotForRightPanel(hoverTime, false);
        if (shouldHideSignalChartPanel()) {
            if (typeof secondaryChart.clearCrosshairPosition === "function") {
                secondaryChart.clearCrosshairPosition();
            }
            return;
        }
        if (syncCrosshairLock) {
            return;
        }
        syncCrosshairLock = true;
        try {
            if (!param || param.time === undefined || !param.point) {
                if (typeof secondaryChart.clearCrosshairPosition === "function") {
                    secondaryChart.clearCrosshairPosition();
                }
                if (isMorphSignalTab()) {
                    clearMorphPatternOverlay();
                }
                return;
            }
            const value = getSignalValueByTime(param.time);
            if (!Number.isFinite(value)) {
                if (typeof secondaryChart.clearCrosshairPosition === "function") {
                    secondaryChart.clearCrosshairPosition();
                }
                return;
            }
            if (typeof secondaryChart.setCrosshairPosition === "function") {
                try {
                    secondaryChart.setCrosshairPosition(value, param.time, secondarySeries);
                } catch (err) {
                    // 某些时间点副图尚无有效坐标时，清理十字线以免打断主流程。
                    if (typeof secondaryChart.clearCrosshairPosition === "function") {
                        secondaryChart.clearCrosshairPosition();
                    }
                }
            }
        } finally {
            syncCrosshairLock = false;
        }
    });
}
bindTimeScaleSync(chart, signalChart);
bindCrosshairSync(chart, signalChart, candlestickSeries, signalSeries);

function formatXAxisTimeLabel(time) {
    // 鏃ョ嚎鏄剧ず蹇呴』鏃跺尯鏃犲叧锛氫紭鍏堜娇鐢?BusinessDay 鍘熷骞存湀鏃ワ紝鍏舵鎸?UTC 绉掓椂闂磋В鏋愶紝
    // 避免本地时区导致不存在的日期错位显示。
    if (
        currentInterval === "1day" &&
        time &&
        typeof time === "object" &&
        "year" in time &&
        "month" in time &&
        "day" in time
    ) {
        return `${Number(time.year)}年${Number(time.month)}月${Number(time.day)}日`;
    }

    let dt = null;
    if (typeof time === "number") {
        dt = new Date(time * 1000);
    } else if (time && typeof time === "object" && "year" in time && "month" in time && "day" in time) {
        dt = new Date(Number(time.year), Number(time.month) - 1, Number(time.day), 0, 0, 0);
    }
    if (!(dt instanceof Date) || Number.isNaN(dt.getTime())) {
        return "--";
    }
    if (currentInterval === "1day") {
        const y = dt.getUTCFullYear();
        const m = dt.getUTCMonth() + 1;
        const d = dt.getUTCDate();
        return `${y}年${m}月${d}日`;
    }
    const y = dt.getUTCFullYear();
    const m = dt.getUTCMonth() + 1;
    const d = dt.getUTCDate();
    const hh = String(dt.getUTCHours()).padStart(2, "0");
    const mm = String(dt.getUTCMinutes()).padStart(2, "0");
    return `${y}年${m}月${d}日 ${hh}:${mm}`;
}

function formatLocalDateTime(tsSeconds) {
    const dt = new Date(tsSeconds * 1000);
    const useUtcClock = currentInterval !== "1day";
    const y = useUtcClock ? dt.getUTCFullYear() : dt.getFullYear();
    const m = String((useUtcClock ? dt.getUTCMonth() : dt.getMonth()) + 1).padStart(2, "0");
    const d = String(useUtcClock ? dt.getUTCDate() : dt.getDate()).padStart(2, "0");
    const hh = String(useUtcClock ? dt.getUTCHours() : dt.getHours()).padStart(2, "0");
    const mm = String(useUtcClock ? dt.getUTCMinutes() : dt.getMinutes()).padStart(2, "0");
    const ss = String(useUtcClock ? dt.getUTCSeconds() : dt.getSeconds()).padStart(2, "0");
    return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
}

function updatePageClock() {
    const nowTs = Math.floor(Date.now() / 1000);
    pageClock.textContent = `当前时间: ${formatLocalDateTime(nowTs)}`;
}

function getIntervalConfig() {
    return INTERVAL_CONFIG[currentInterval] || INTERVAL_CONFIG["1min"];
}

function alignToCurrentInterval(tsSeconds) {
    const stepSeconds = getIntervalConfig().alignStepSeconds;
    return Math.floor(tsSeconds / stepSeconds) * stepSeconds;
}

function getCurrentAdjustParam() {
    const key = String(currentAdjustMode || "qfq").trim();
    return ADJUST_MODE_PARAM[key] || "forward";
}

function keepDigits(value, maxLen) {
    return String(value || "").replace(/\D/g, "").slice(0, maxLen);
}

function persistWatchlistState() {
    try {
        const payload = {
            codes: watchlistCodes,
            selected: selectedWatchCode
        };
        localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(payload));
    } catch (err) {
        // 鏈湴瀛樺偍涓嶅彲鐢ㄦ椂闈欓粯闄嶇骇锛屼笉褰卞搷鏍稿績琛屾儏鍔熻兘
    }
    scheduleWatchlistRemoteSync();
}

function persistViewState() {
    try {
        const payload = {
            code: String(currentCode || "").trim().toUpperCase(),
            interval: String(currentInterval || "").trim(),
            adjustMode: String(currentAdjustMode || "qfq").trim()
        };
        localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(payload));
    } catch (err) {
        // 鏈湴瀛樺偍涓嶅彲鐢ㄦ椂闈欓粯闄嶇骇锛屼笉褰卞搷涓绘祦绋?
    }
}

function restoreWatchlistState() {
    try {
        const raw = localStorage.getItem(WATCHLIST_STORAGE_KEY);
        if (!raw) {
            return;
        }
        const parsed = JSON.parse(raw);
        if (!parsed || !Array.isArray(parsed.codes)) {
            return;
        }
        const normalizedCodes = [];
        const dedup = new Set();
        for (const item of parsed.codes) {
            const code = String(item || "").trim().toUpperCase();
            if (!code || dedup.has(code)) {
                continue;
            }
            dedup.add(code);
            normalizedCodes.push(code);
        }
        if (normalizedCodes.length > 0) {
            let codes = normalizedCodes;
            if (!PAGE_BOOT.allowYkrsCurve) {
                codes = normalizedCodes.filter((c) => !String(c || "").trim().toUpperCase().endsWith(".YKRS"));
            }
            if (codes.length === 0) {
                codes = ["301469.SZ"];
            }
            watchlistCodes = codes;
        }
        const selected = String(parsed.selected || "").trim().toUpperCase();
        if (selected && watchlistCodes.includes(selected)) {
            selectedWatchCode = selected;
        } else if (watchlistCodes.length > 0) {
            selectedWatchCode = watchlistCodes[0];
        }
        // 与输入框、拉数使用的 currentCode 对齐，避免首屏仍请求默认 code 导致日 K 错乱。
        if (selectedWatchCode) {
            codeInput.value = selectedWatchCode;
            currentCode = selectedWatchCode;
        }
    } catch (err) {
        // 瀛樺偍鏍煎紡寮傚父鏃跺拷鐣ユ棫鏁版嵁锛屼娇鐢ㄩ粯璁ゅ垪琛?
    }
}

function restoreViewState() {
    try {
        const raw = localStorage.getItem(VIEW_STORAGE_KEY);
        if (!raw) {
            // 无历史记录时使用默认 1day，并优先沿用自选项中的已选 code。
            currentInterval = "1day";
            intervalSelect.value = "1day";
            currentAdjustMode = "qfq";
            if (adjustModeSelect) {
                adjustModeSelect.value = currentAdjustMode;
            }
            if (selectedWatchCode) {
                currentCode = selectedWatchCode;
                codeInput.value = selectedWatchCode;
            }
            return;
        }
        const parsed = JSON.parse(raw);
        const savedCode = String(parsed && parsed.code ? parsed.code : "").trim().toUpperCase();
        const savedInterval = String(parsed && parsed.interval ? parsed.interval : "").trim();
        const savedAdjustMode = String(parsed && parsed.adjustMode ? parsed.adjustMode : "").trim();

        if (savedInterval && Object.prototype.hasOwnProperty.call(INTERVAL_CONFIG, savedInterval)) {
            currentInterval = savedInterval;
            intervalSelect.value = savedInterval;
        } else {
            currentInterval = "1day";
            intervalSelect.value = "1day";
        }
        if (Object.prototype.hasOwnProperty.call(ADJUST_MODE_PARAM, savedAdjustMode)) {
            currentAdjustMode = savedAdjustMode;
        } else {
            currentAdjustMode = "qfq";
        }
        if (adjustModeSelect) {
            adjustModeSelect.value = currentAdjustMode;
        }

        if (savedCode && !isYkrsCurveDeniedOnThisSurface(savedCode)) {
            currentCode = savedCode;
            codeInput.value = savedCode;
            if (watchlistCodes.includes(savedCode)) {
                selectedWatchCode = savedCode;
            }
        } else if (selectedWatchCode) {
            // 鏃犳湁鏁堝巻鍙?code 鏃讹紝鍥炶惤鍒拌嚜閫変腑椤?
            currentCode = selectedWatchCode;
            codeInput.value = selectedWatchCode;
        }
    } catch (err) {
        // 记录异常时回退默认值。
        currentInterval = "1day";
        intervalSelect.value = "1day";
        currentAdjustMode = "qfq";
        if (adjustModeSelect) {
            adjustModeSelect.value = currentAdjustMode;
        }
        if (selectedWatchCode) {
            currentCode = selectedWatchCode;
            codeInput.value = selectedWatchCode;
        }
    }
}


function persistFactorState() {
    try {
        localStorage.setItem(FACTOR_STORAGE_KEY, String(selectedFactorName || ""));
    } catch (err) {
        // 鏈湴瀛樺偍涓嶅彲鐢ㄦ椂闈欓粯闄嶇骇
    }
    persistQuantFactorUi();
}

function persistExpandedFactorGroups() {
    try {
        localStorage.setItem(
            FACTOR_GROUP_EXPAND_STORAGE_KEY,
            JSON.stringify(Array.from(expandedFactorGroupIds))
        );
    } catch (err) {
        // 鏈湴瀛樺偍涓嶅彲鐢ㄦ椂闈欓粯闄嶇骇
    }
}

function restoreFactorState() {
    try {
        const raw = localStorage.getItem(FACTOR_STORAGE_KEY);
        return String(raw || "").trim();
    } catch (err) {
        return "";
    }
}

function restoreExpandedFactorGroups() {
    expandedFactorGroupIds.clear();
    try {
        const raw = localStorage.getItem(FACTOR_GROUP_EXPAND_STORAGE_KEY);
        if (!raw) {
            return;
        }
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) {
            return;
        }
        for (const item of parsed) {
            const groupId = String(item || "").trim();
            if (groupId) {
                expandedFactorGroupIds.add(groupId);
            }
        }
    } catch (err) {
        // ignore
    }
}

function updateSignalCaptionTitle() {
    if (isMorphSignalTab()) {
        const levelKeys = getMorphActiveLevelKeys();
        const compoundKey = getMorphPrimarySignalKey(levelKeys);
        if (!compoundKey) {
            signalCaptionTitle.textContent = "形态面: --";
            return;
        }
        const windowLabel = `窗口 ${barsCache.length} 日`;
        const patternCount = morphLoadedLevelKey === compoundKey
            ? morphPatternPointsByName.size
            : 0;
        const patternPart = patternCount ? `${patternCount} 形态` : "当日形态数";
        const levelPart = levelKeys.map((key) => getMorphSignalLabel(key)).join(" / ");
        signalCaptionTitle.textContent = `形态面: ${levelPart} | ${patternPart} | ${windowLabel}`;
        return;
    }
    const visibleSlots = getVisibleSignalSlots();
    const adHocFactors = getAdHocActiveFactorNames();
    if (visibleSlots.length || adHocFactors.length) {
        const slotPart = visibleSlots
            .map((spec) => `${spec.label}:${getDisplayLabelForFactorColumn(signalSlotBindings[spec.key]) || signalSlotBindings[spec.key]}`)
            .join(" | ");
        const adHocPart = adHocFactors.length
            ? `附加 ${adHocFactors.length} 条`
            : "";
        signalCaptionTitle.textContent = [slotPart, adHocPart].filter(Boolean).join("，");
        return;
    }
    signalCaptionTitle.textContent = "因子强度: --";
}

function setFactorHint(text) {
    if (factorHint) {
        factorHint.textContent = text;
    }
}

function buildMissingFactorKey(code, factor, interval = "1day") {
    return `${String(interval || "").trim()}|${String(code || "").trim().toUpperCase()}|${String(factor || "").trim()}`;
}

function clearMissingFactorKeysForCurrentContext() {
    const code = String(currentCode || "").trim().toUpperCase();
    const interval = String(currentInterval || "").trim();
    if (!code) {
        return;
    }
    const prefix = `${interval}|${code}|`;
    for (const key of Array.from(missingFactorKeys)) {
        if (key.startsWith(prefix)) {
            missingFactorKeys.delete(key);
        }
    }
}

function isNearOldestVisibleBar() {
    const firstBarTime = getFirstBarTime();
    if (firstBarTime === null) {
        return false;
    }
    const timeRange = chart.timeScale().getVisibleRange();
    if (timeRange && timeRange.from !== undefined) {
        const leftVisibleTime = Number(timeRange.from);
        if (Number.isFinite(leftVisibleTime)) {
            const threshold = getIntervalConfig().leftEdgePreloadThresholdSeconds;
            return leftVisibleTime - firstBarTime <= threshold;
        }
    }
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (!logicalRange) {
        return false;
    }
    const span = Math.max(10, logicalRange.to - logicalRange.from);
    return logicalRange.from <= Math.max(40, span * 0.25);
}

/** 可见 K 线占已加载总量的比例；越大表示缩得越小、看得越多。 */
function getVisibleBarsCoverageRatio() {
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (!logicalRange || !barsCache.length) {
        return 0;
    }
    const span = Math.max(1, logicalRange.to - logicalRange.from);
    return span / barsCache.length;
}

function isChartZoomedOutView() {
    return getVisibleBarsCoverageRatio() >= 0.72;
}

/** 缂╁皬瑙嗗浘鏃讹細宸︾紭璐磋繎宸插姞杞芥渶鏃╀竴鏍癸紙涓嶅繀瀹屽叏閲嶅悎锛?*/
function isLeftEdgeNearCacheOldestWhenZoomedOut() {
    if (!isChartZoomedOutView()) {
        return false;
    }
    const firstBarTime = getFirstBarTime();
    if (firstBarTime === null) {
        return false;
    }
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (logicalRange) {
        const span = Math.max(10, logicalRange.to - logicalRange.from);
        const nearByLogicalIndex = logicalRange.from <= Math.max(3, barsCache.length * 0.08);
        const nearByVisibleSpan = logicalRange.from <= span * 0.12;
        if (nearByLogicalIndex || nearByVisibleSpan) {
            return true;
        }
    }
    const timeRange = chart.timeScale().getVisibleRange();
    if (timeRange && timeRange.from !== undefined && timeRange.to !== undefined) {
        const leftVisibleTime = Number(timeRange.from);
        const rightVisibleTime = Number(timeRange.to);
        if (Number.isFinite(leftVisibleTime) && Number.isFinite(rightVisibleTime)) {
            const visibleSpan = Math.max(
                getIntervalConfig().alignStepSeconds,
                rightVisibleTime - leftVisibleTime
            );
            const gap = leftVisibleTime - firstBarTime;
            const threshold = Math.max(
                getIntervalConfig().leftEdgePreloadThresholdSeconds,
                visibleSpan * 0.12
            );
            if (gap >= 0 && gap <= threshold) {
                return true;
            }
        }
    }
    return false;
}

function shouldLoadOlderBars(options = {}) {
    if (options.ignoreVisibleEdge) {
        return true;
    }
    if (options.behaviorTrigger) {
        return true;
    }
    if (isNearOldestVisibleBar()) {
        return true;
    }
    return isLeftEdgeNearCacheOldestWhenZoomedOut();
}

function captureVisibleLogicalSnapshot() {
    const logicalRange = chart.timeScale().getVisibleLogicalRange();
    if (!logicalRange || !barsCache.length) {
        return null;
    }
    return {
        from: Number(logicalRange.from),
        to: Number(logicalRange.to),
        coverage: getVisibleBarsCoverageRatio(),
    };
}

function isPanningChartLeft(previousSnapshot, currentSnapshot) {
    if (!previousSnapshot || !currentSnapshot) {
        return false;
    }
    if (!Number.isFinite(previousSnapshot.from) || !Number.isFinite(currentSnapshot.from)) {
        return false;
    }
    return currentSnapshot.from < previousSnapshot.from - 0.35;
}

function isZoomingChartOut(previousSnapshot, currentSnapshot) {
    if (!currentSnapshot) {
        return false;
    }
    if (!previousSnapshot) {
        return currentSnapshot.coverage >= 0.72;
    }
    return (
        currentSnapshot.coverage >= 0.72 &&
        currentSnapshot.coverage > previousSnapshot.coverage + 0.04
    );
}

function resetVisibleLogicalSnapshot() {
    lastVisibleLogicalSnapshot = null;
}

function scheduleBehaviorHistoryPrefetch() {
    if (shouldUseMorphBarWindow()) {
        return;
    }
    if (historyExhausted || !barsCache.length) {
        return;
    }
    if (historyPrefetchDebounceTimer) {
        clearTimeout(historyPrefetchDebounceTimer);
    }
    historyPrefetchDebounceTimer = setTimeout(() => {
        historyPrefetchDebounceTimer = null;
        void prefetchOlderBarsFromViewGesture(HISTORY_PREFETCH_GESTURE_ROUNDS);
    }, HISTORY_PREFETCH_DEBOUNCE_MS);
}

async function prefetchOlderBarsFromViewGesture(maxRounds = HISTORY_PREFETCH_GESTURE_ROUNDS) {
    if (shouldUseMorphBarWindow()) {
        return;
    }
    for (let round = 0; round < maxRounds; round += 1) {
        if (historyExhausted || isRequesting || isLoadingHistory || !barsCache.length) {
            break;
        }
        const firstBefore = getFirstBarTime();
        const lastBefore = getLastBarTime();
        await loadOlderBarsIfNeeded({ behaviorTrigger: true });
        if (historyExhausted || !didBarWindowChange(firstBefore, lastBefore)) {
            break;
        }
    }
}

function onMainChartViewportChange() {
    scheduleIndexOverlayViewportRefresh();
    scheduleMinuteOffscreenPrune();
    const currentSnapshot = captureVisibleLogicalSnapshot();
    const previousSnapshot = lastVisibleLogicalSnapshot;
    if (currentSnapshot) {
        lastVisibleLogicalSnapshot = currentSnapshot;
    }
    if (shouldUseMorphBarWindow()) {
        syncMorphWindowAtLatestFromViewport();
        if (!morphWindowChartInteracting) {
            syncMorphViewportLogicalRangeClamp();
        }
        const logicalRange = chart.timeScale().getVisibleLogicalRange();
        if (logicalRange && !isMorphWindowLogicalAtLeftShiftEdge(logicalRange)) {
            historyExhausted = false;
            lastHistoryRequestTo = null;
        }
        if (!morphWindowChartInteracting && !isMorphWindowEdgeCheckSuppressed()) {
            scheduleMorphWindowEdgeCheck();
        } else if (
            morphWindowChartInteracting
            && logicalRange
            && !historyExhausted
            && logicalRange.from <= MORPH_WINDOW_PRELOAD_EDGE_BARS
        ) {
            void preloadMorphWindowOlder();
        } else if (
            morphWindowChartInteracting
            && logicalRange
            && !morphWindowAtLatest
            && barsCache.length
            && logicalRange.to >= barsCache.length - 1 - MORPH_WINDOW_PRELOAD_EDGE_BARS
        ) {
            void preloadMorphWindowNewer();
        }
        scheduleMorphOverlayViewportRedraw();
        return;
    }
    if (currentInterval === "1day" || currentInterval === "1min") {
        void loadOlderBarsIfNeeded();
    }
    if (isMorphSignalTab()) {
        scheduleMorphOverlayViewportRedraw();
    }
    if (
        currentInterval !== "1min" && (
        isPanningChartLeft(previousSnapshot, currentSnapshot) ||
        isZoomingChartOut(previousSnapshot, currentSnapshot)
    )) {
        scheduleBehaviorHistoryPrefetch();
    }
}

async function prefetchOlderBarsForInitialDisplay(maxRounds = 5) {
    if (shouldUseMorphBarWindow()) {
        return;
    }
    for (let round = 0; round < maxRounds; round += 1) {
        if (historyExhausted || isRequesting || isLoadingHistory || !barsCache.length) {
            break;
        }
        const firstBefore = getFirstBarTime();
        const lastBefore = getLastBarTime();
        await loadOlderBarsIfNeeded({ ignoreVisibleEdge: true });
        if (historyExhausted || firstBefore === getFirstBarTime() || lastBefore === getLastBarTime()) {
            break;
        }
    }
}

function scheduleHistoryPrefetchAfterViewSettle() {
    if (shouldUseMorphBarWindow()) {
        return;
    }
    requestAnimationFrame(() => {
        void prefetchOlderBarsForInitialDisplay();
    });
}

function applyMissingFactorView() {
    signalPoints = [];
    lastSignalTime = null;
    renderSignalData();
    signalCaptionTitle.textContent = selectedFactorName
        ? `因子强度: ${getDisplayLabelForFactorColumn(selectedFactorName) || selectedFactorName}（该因子不存在）`
        : "因子强度: --";
    setFactorHint(selectedFactorName
        ? `该股票无因子数据: ${getDisplayLabelForFactorColumn(selectedFactorName) || selectedFactorName}`
        : "请选择一个因子后展示副图");
}

function renderFactorOptions() {
    if (!factorSelect) {
        if (!selectedFactorName && factorNames.length) {
            selectedFactorName = factorNames[0];
        }
        updateSignalCaptionTitle();
        persistFactorState();
        return;
    }
    factorSelect.innerHTML = "";
    if (!factorNames.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "暂无可用因子";
        factorSelect.appendChild(option);
        factorSelect.disabled = true;
        selectedFactorName = "";
        updateSignalCaptionTitle();
        return;
    }

    for (const name of factorNames) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = getDisplayLabelForFactorColumn(name) || name;
        factorSelect.appendChild(option);
    }
    factorSelect.disabled = false;

    if (!selectedFactorName || !factorNames.includes(selectedFactorName)) {
        selectedFactorName = factorNames[0];
    }
    factorSelect.value = selectedFactorName;
    updateSignalCaptionTitle();
    persistFactorState();
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function applyChartSize() {
    chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight
    });
    signalChart.applyOptions({
        width: signalChartContainer.clientWidth,
        height: signalChartContainer.clientHeight
    });
    if (shouldUseMorphBarWindow()) {
        updateMorphTimeScaleZoomLimits();
        syncMorphViewportLogicalRangeClamp();
    }
    if (isMorphSignalTab()) {
        resizeMorphPatternOverlayCanvas();
        redrawMorphPatternOverlayAtCachedTime();
    }
}

function applySignalChartVisibility() {
    const hidden = shouldHideSignalChartPanel();
    if (signalChartWrap) {
        signalChartWrap.style.display = hidden ? "none" : "";
    }
    if (splitterSignal) {
        splitterSignal.style.display = hidden ? "none" : "";
    }
    if (hidden && typeof signalChart.clearCrosshairPosition === "function") {
        signalChart.clearCrosshairPosition();
    }
    applyChartSize();
}

function edgeFloatNavigateToPage(filename) {
    if (window.EdgeFloatNav && typeof window.EdgeFloatNav.navigateToPage === "function") {
        window.EdgeFloatNav.navigateToPage(filename);
        return;
    }
    const name = String(filename || "").trim();
    if (!name) {
        return;
    }
    const href = window.location.href.split("#")[0].split("?")[0];
    const slash = Math.max(href.lastIndexOf("/"), href.lastIndexOf("\\"));
    const base = slash >= 0 ? href.slice(0, slash + 1) : href;
    window.location.href = `${base}${name}${window.location.search || ""}${window.location.hash || ""}`;
}

function initResizableLayout() {
    const setDragStyle = (dragging, cursor) => {
        document.body.style.userSelect = dragging ? "none" : "";
        document.body.style.cursor = dragging ? cursor : "";
    };

    const hideLeftPanel = PAGE_BOOT.portfolioMode;
    let leftWidth = hideLeftPanel ? 0 : (leftPanel.getBoundingClientRect().width || 220);
    let rightWidth = rightPanel.getBoundingClientRect().width || 280;

    const applyMainGridColumns = () => {
        const cols = hideLeftPanel
            ? `minmax(0, 1fr) 8px ${rightWidth}px`
            : `${leftWidth}px 8px minmax(0, 1fr) 8px ${rightWidth}px`;
        mainLayout.style.gridTemplateColumns = cols;
        document.getElementById('page-header').style.gridTemplateColumns = cols;
        applyChartSize();
    };

    const getSignalPaneMaxPx = () => {
        const colH = centerColumn.getBoundingClientRect().height;
        if (colH <= 0) {
            return SIGNAL_PANE_MAX_PX;
        }
        const bottomH = centerBottomPanel.getBoundingClientRect().height;
        const splitters = 24;
        const raw = colH - bottomH - MIN_CHART_STACK_PX - splitters;
        return Math.min(SIGNAL_PANE_MAX_PX, Math.max(SIGNAL_PANE_MIN_PX, raw));
    };

    const getCenterBottomMaxPx = () => {
        const colH = centerColumn.getBoundingClientRect().height;
        if (colH <= 0) {
            return CENTER_BOTTOM_HEIGHT_MAX_PX;
        }
        const signalH = signalChartWrap.getBoundingClientRect().height;
        const reserved = MIN_CHART_STACK_PX + signalH + 32;
        return Math.min(CENTER_BOTTOM_HEIGHT_MAX_PX, Math.max(CENTER_BOTTOM_HEIGHT_MIN_PX, colH - reserved));
    };

    applyMainGridColumns();
    applySignalChartVisibility();

    signalChartWrap.style.setProperty(
        "--signal-pane-height",
        `${clamp(INITIAL_SIGNAL_PANE_HEIGHT_PX, SIGNAL_PANE_MIN_PX, getSignalPaneMaxPx())}px`
    );

    centerBottomPanel.style.setProperty(
        "--center-bottom-height",
        `${clamp(INITIAL_CENTER_BOTTOM_HEIGHT_PX, CENTER_BOTTOM_HEIGHT_MIN_PX, getCenterBottomMaxPx())}px`
    );

    new ResizeObserver(() => {
        const raw = getComputedStyle(centerBottomPanel).getPropertyValue("--center-bottom-height").trim();
        let bottomPx = parseInt(raw, 10);
        if (!Number.isFinite(bottomPx)) {
            bottomPx = INITIAL_CENTER_BOTTOM_HEIGHT_PX;
        }
        const maxPx = getCenterBottomMaxPx();
        const capped = clamp(bottomPx, CENTER_BOTTOM_HEIGHT_MIN_PX, maxPx);
        if (capped !== bottomPx) {
            centerBottomPanel.style.setProperty("--center-bottom-height", `${capped}px`);
        }
        const rawSig = getComputedStyle(signalChartWrap).getPropertyValue("--signal-pane-height").trim();
        let sigPx = parseInt(rawSig, 10);
        if (!Number.isFinite(sigPx)) {
            sigPx = INITIAL_SIGNAL_PANE_HEIGHT_PX;
        }
        const sigMax = getSignalPaneMaxPx();
        const sigCapped = clamp(sigPx, SIGNAL_PANE_MIN_PX, sigMax);
        if (sigCapped !== sigPx) {
            signalChartWrap.style.setProperty("--signal-pane-height", `${sigCapped}px`);
        }
        applyChartSize();
    }).observe(centerColumn);

    splitterSignal.addEventListener("mousedown", (event) => {
        event.preventDefault();
        const startY = event.clientY;
        const startSignal = signalChartWrap.getBoundingClientRect().height;
        setDragStyle(true, "row-resize");

        const onMove = (moveEvent) => {
            const next = clamp(
                startSignal - (moveEvent.clientY - startY),
                SIGNAL_PANE_MIN_PX,
                getSignalPaneMaxPx()
            );
            signalChartWrap.style.setProperty("--signal-pane-height", `${next}px`);
            applyChartSize();
        };
        const onUp = () => {
            setDragStyle(false, "default");
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    });

    if (!hideLeftPanel) {
        splitterLeft.addEventListener("mousedown", (event) => {
            event.preventDefault();
            const startX = event.clientX;
            const startWidth = leftWidth;
            setDragStyle(true, "col-resize");

            const onMove = (moveEvent) => {
                leftWidth = clamp(startWidth + (moveEvent.clientX - startX), 120, 560);
                applyMainGridColumns();
            };
            const onUp = () => {
                setDragStyle(false, "default");
                window.removeEventListener("mousemove", onMove);
                window.removeEventListener("mouseup", onUp);
            };
            window.addEventListener("mousemove", onMove);
            window.addEventListener("mouseup", onUp);
        });
    }

    splitterRight.addEventListener("mousedown", (event) => {
        event.preventDefault();
        const startX = event.clientX;
        const startWidth = rightWidth;
        setDragStyle(true, "col-resize");

        const onMove = (moveEvent) => {
            rightWidth = clamp(startWidth - (moveEvent.clientX - startX), 160, 620);
            applyMainGridColumns();
        };
        const onUp = () => {
            setDragStyle(false, "default");
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    });

    splitterCenterV.addEventListener("mousedown", (event) => {
        event.preventDefault();
        const startY = event.clientY;
        const startBottom = centerBottomPanel.getBoundingClientRect().height;
        setDragStyle(true, "row-resize");

        const onMove = (moveEvent) => {
            // 与底部分割条一致：鼠标下移时下方面板变小，K 线区变大。
            const next = clamp(
                startBottom - (moveEvent.clientY - startY),
                CENTER_BOTTOM_HEIGHT_MIN_PX,
                getCenterBottomMaxPx()
            );
            centerBottomPanel.style.setProperty("--center-bottom-height", `${next}px`);
            applyChartSize();
        };
        const onUp = () => {
            setDragStyle(false, "default");
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    });
}

function setConnectedStatus() {
    refreshFailed = false;
}

function setBrokenStatus(message) {
    refreshFailed = true;
    logUiHint(`自动刷新失败（断流）: ${message}`);
}

function isNoDataErrorResponse(status, body) {
    if (status !== 404) {
        return false;
    }
    const message = body && body.error && body.error.message ? String(body.error.message) : "";
    return !message || message.includes("未找到") || message.includes("not found") || message.includes("No data");
}

async function fetchBars(code, fromTs, toTs, lastSeenBarTime = null, options = {}) {
    const { allowNotFound = false, limit = 5000 } = options;
    if (isCurveLineCode(code) && !getSelectedRunTag()) {
        if (allowNotFound) {
            return {
                bars: [],
                meta: { code, from: fromTs, to: toTs, has_new_data: false, row_count: 0 }
            };
        }
        throw new Error("组合曲线查询须先在结果展示页选择回测");
    }
    const params = new URLSearchParams({
        code,
        interval: currentInterval,
        adjust: getCurrentAdjustParam(),
        from: String(fromTs),
        to: String(toTs),
        limit: String(limit)
    });
    if (lastSeenBarTime !== null) {
        params.set("last_seen_bar_time", String(lastSeenBarTime));
    }
    if (isCurveLineCode(code)) {
        appendRunTagParam(params);
    }

    const url = `${API_BASE_URL}/api/market/bars?${params.toString()}`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        if (allowNotFound && isNoDataErrorResponse(resp.status, body)) {
            return {
                bars: [],
                meta: {
                    code,
                    from: fromTs,
                    to: toTs,
                    has_new_data: false,
                    row_count: 0
                }
            };
        }
        const message = body && body.error && body.error.message ? body.error.message : "接口请求失败";
        throw new Error(message);
    }
    return body;
}

async function fetchFactorNames() {
    const params = new URLSearchParams({ interval: "1day", refresh: "1" });
    const url = `${API_BASE_URL}/api/market/factors?${params.toString()}`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        const message = body && body.error && body.error.message ? body.error.message : "因子列表获取失败";
        throw new Error(message);
    }
    return {
        factors: Array.isArray(body.factors) ? body.factors : [],
        groups: Array.isArray(body.groups) ? body.groups : [],
        core_factors: Array.isArray(body.core_factors) ? body.core_factors : [],
        core_factor_labels: Array.isArray(body.core_factor_labels) ? body.core_factor_labels : [],
        factor_labels: body && body.factor_labels && typeof body.factor_labels === "object" ? body.factor_labels : {}
    };
}

async function fetchFactorSignals(code, factor, fromTs, toTs, lastSeenSignalTime = null, limitValue = FACTOR_FETCH_LIMIT_INITIAL) {
    const params = new URLSearchParams({
        code,
        interval: "1day",
        factor,
        from: String(fromTs),
        to: String(toTs),
        limit: String(limitValue)
    });
    if (lastSeenSignalTime !== null) {
        params.set("last_seen_signal_time", String(lastSeenSignalTime));
    }
    const url = `${API_BASE_URL}/api/market/signal?${params.toString()}`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        if (isNoDataErrorResponse(resp.status, body)) {
            return { signals: [], meta: { has_new_data: false, row_count: 0, no_factor: true } };
        }
        const message = body && body.error && body.error.message ? body.error.message : "因子数据获取失败";
        throw new Error(message);
    }
    return body;
}

async function fetchFactorCoupleSeries(code, factors) {
    const url = `${API_BASE_URL}/api/market/factor-couple`;
    const resp = await fetch(url, {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            code: String(code || "").trim(),
            interval: "1day",
            factors: Array.isArray(factors) ? factors.map((f) => String(f || "").trim()).filter(Boolean) : []
        })
    });
    const body = await resp.json();
    if (!resp.ok) {
        const message = body && body.error && body.error.message ? body.error.message : "因子耦合请求失败";
        throw new Error(message);
    }
    return body;
}

async function fetchFactorSnapshot(code, timeTs, mode = "core", groupId = "") {
    const params = new URLSearchParams({
        code,
        interval: "1day",
        time: String(timeTs),
        mode: String(mode || "core")
    });
    if (groupId) {
        params.set("group_id", String(groupId));
    }
    const url = `${API_BASE_URL}/api/market/factor-snapshot?${params.toString()}`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        if (isNoDataErrorResponse(resp.status, body)) {
            return { no_data: true, factors: {}, time: timeTs };
        }
        const message = body && body.error && body.error.message ? body.error.message : "因子快照获取失败";
        throw new Error(message);
    }
    return body;
}

async function fetchCodeSuggestions(keyword) {
    const params = new URLSearchParams({
        q: keyword,
        interval: currentInterval,
        limit: String(CODE_SUGGESTION_LIMIT)
    });
    const url = `${API_BASE_URL}/api/market/codes/search?${params.toString()}`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        const message = body && body.error && body.error.message ? body.error.message : "检索失败";
        throw new Error(message);
    }
    const rawItems = Array.isArray(body.items) ? body.items : [];
    const rawList = rawItems.length
        ? rawItems.map((item) => ({
            code: String((item && item.code) || "").trim().toUpperCase(),
            name: String((item && item.name) || "").trim(),
            pinyin_initials: String((item && item.pinyin_initials) || "").trim().toUpperCase(),
        })).filter((item) => item.code)
        : (Array.isArray(body.codes) ? body.codes : []).map((code) => ({
            code: String(code || "").trim().toUpperCase(),
            name: "",
            pinyin_initials: "",
        })).filter((item) => item.code);
    if (PAGE_BOOT.allowYkrsCurve) {
        return rawList;
    }
    return rawList.filter((item) => !item.code.endsWith(".YKRS"));
}

function normalizeWatchlistPayload(payload) {
    const parsed = payload && typeof payload === "object" ? payload : {};
    const rawCodes = Array.isArray(parsed.codes) ? parsed.codes : [];
    const normalizedCodes = [];
    const dedup = new Set();
    for (const item of rawCodes) {
        const code = String(item || "").trim().toUpperCase();
        if (!code || dedup.has(code)) {
            continue;
        }
        dedup.add(code);
        normalizedCodes.push(code);
    }
    const selectedRaw = String(parsed.selected || "").trim().toUpperCase();
    const selected = normalizedCodes.includes(selectedRaw)
        ? selectedRaw
        : (normalizedCodes[0] || "");
    return { codes: normalizedCodes, selected };
}

function shouldSyncWatchlistWithServer() {
    return !PAGE_BOOT.embedMode && !PAGE_BOOT.allowYkrsCurve;
}

function scheduleWatchlistRemoteSync() {
    if (!shouldSyncWatchlistWithServer()) {
        return;
    }
    if (watchlistSyncTimer) {
        clearTimeout(watchlistSyncTimer);
        watchlistSyncTimer = null;
    }
    watchlistSyncTimer = setTimeout(() => {
        watchlistSyncTimer = null;
        void syncWatchlistToServer();
    }, WATCHLIST_SYNC_DEBOUNCE_MS);
}

async function fetchWatchlistFromServer() {
    const url = `${API_BASE_URL}/api/watchlist`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok) {
        const message = body && body.error && body.error.message ? body.error.message : "自选股读取失败";
        throw new Error(message);
    }
    return normalizeWatchlistPayload(body);
}

async function syncWatchlistToServer() {
    const payload = normalizeWatchlistPayload({
        codes: watchlistCodes,
        selected: selectedWatchCode
    });
    const resp = await fetch(`${API_BASE_URL}/api/watchlist`, {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!resp.ok) {
        let message = "自选股同步失败";
        try {
            const body = await resp.json();
            message = body && body.error && body.error.message ? body.error.message : message;
        } catch (err) {
            // ignore parse error
        }
        throw new Error(message);
    }
}

async function hydrateWatchlistFromServer() {
    if (!shouldSyncWatchlistWithServer()) {
        return;
    }
    try {
        const remoteState = await fetchWatchlistFromServer();
        if (!remoteState.codes.length) {
            return;
        }
        watchlistCodes = remoteState.codes.filter(
            (c) => PAGE_BOOT.allowYkrsCurve || !String(c || "").trim().toUpperCase().endsWith(".YKRS"),
        );
        if (!watchlistCodes.length) {
            watchlistCodes = ["301469.SZ"];
        }
        const selectedRaw = String(remoteState.selected || "").trim().toUpperCase();
        selectedWatchCode = watchlistCodes.includes(selectedRaw)
            ? selectedRaw
            : (watchlistCodes[0] || "");
        if (selectedWatchCode) {
            currentCode = selectedWatchCode;
            codeInput.value = selectedWatchCode;
        }
        try {
            localStorage.setItem(
                WATCHLIST_STORAGE_KEY,
                JSON.stringify({ codes: watchlistCodes, selected: selectedWatchCode }),
            );
        } catch (err) {
            // ignore local cache write failure
        }
    } catch (err) {
        // 杩滅涓嶅彲鐢ㄦ椂淇濇寔 localStorage 绉掑紑锛屼笉涓柇涓绘祦绋?
    }
}

async function fetchLatestPriceForCode(code) {
    const nowTs = alignToCurrentInterval(Math.floor(Date.now() / 1000));
    const fromTs = nowTs - getIntervalConfig().latestPriceLookbackSeconds;
    const payload = await fetchBars(code, fromTs, nowTs, null, { allowNotFound: true });
    const bars = Array.isArray(payload.bars) ? payload.bars : [];
    if (!bars.length) {
        return null;
    }
    const latest = bars[bars.length - 1];
    return {
        code,
        price: Number(latest.close),
        time: Number(latest.time)
    };
}

function renderWatchlist() {
    if (!watchlistCards) {
        return;
    }
    watchlistCards.innerHTML = "";
    if (!watchlistCodes.length) {
        watchlistCards.innerHTML = '<div class="watchlist-detail">当前没有自选股，请先点击“加入自选股”</div>';
        return;
    }
    for (const code of watchlistCodes) {
        if (isYkrsCurveDeniedOnThisSurface(code)) {
            continue;
        }
        const info = watchlistPriceMap.get(code);
        const priceText = info ? info.price.toFixed(3) : "--";
        const timeText = info ? formatLocalDateTime(info.time) : "--";

        const card = document.createElement("div");
        card.className = `watchlist-detail watch-card${code === selectedWatchCode ? " active" : ""}`;
        card.innerHTML =
            `代码: <b>${code}</b><br>` +
            `最新价: <b>${priceText}</b><br>` +
            `时间: ${timeText}`;

        const del = document.createElement("button");
        del.type = "button";
        del.className = "watchlist-delete";
        del.textContent = "删";
        del.addEventListener("click", (event) => {
            event.stopPropagation();
            watchlistCodes = watchlistCodes.filter((c) => c !== code);
            watchlistPriceMap.delete(code);
            if (selectedWatchCode === code) {
                selectedWatchCode = watchlistCodes.length ? watchlistCodes[0] : "";
            }
            persistWatchlistState();
            renderWatchlist();
        });

        card.appendChild(del);
        card.addEventListener("click", async () => {
            selectedWatchCode = code;
            persistWatchlistState();
            codeInput.value = code;
            renderWatchlist();
            await switchCodeAndReload(code);
        });
        watchlistCards.appendChild(card);
    }
}

async function refreshWatchlistPrices() {
    const normalizedCurrent = String(currentCode || "").trim().toUpperCase();
    if (barsCache.length > 0) {
        const latest = barsCache[barsCache.length - 1];
        const latestClose = Number(latest && latest.close);
        const latestTime = Number(latest && latest.time);
        if (Number.isFinite(latestClose) && Number.isFinite(latestTime)) {
            watchlistPriceMap.set(normalizedCurrent, {
                code: normalizedCurrent,
                price: latestClose,
                time: latestTime
            });
        }
    } else if (normalizedCurrent) {
        try {
            const data = await fetchLatestPriceForCode(normalizedCurrent);
            if (data) {
                watchlistPriceMap.set(normalizedCurrent, data);
            }
        } catch (_err) {
            // 淇℃伅椤垫棤 K 绾跨紦瀛樻椂浠嶅皾璇曟媺褰撳墠 code 鐜颁环
        }
    }
    const tasks = watchlistCodes.map(async (code) => {
        const normalized = String(code || "").trim().toUpperCase();
        if (!normalized) {
            return;
        }
        if (
            normalized === normalizedCurrent
            && watchlistPriceMap.has(normalized)
        ) {
            return;
        }
        try {
            const data = await fetchLatestPriceForCode(code);
            if (data) {
                watchlistPriceMap.set(code, data);
            }
        } catch (err) {
            // 保留已有价格，避免单个 code 失败影响整个列表。
        }
    });
    await Promise.all(tasks);
    renderWatchlist();
}

function hideCodeSuggestions() {
    if (!codeSuggestions) {
        return;
    }
    codeSuggestions.classList.remove("show");
    codeSuggestions.innerHTML = "";
    codeSuggestItems = [];
    activeSuggestionIndex = -1;
}

function scheduleCodeSuggestions(keyword) {
    const raw = String(keyword || "").trim();
    if (codeSuggestTimer) {
        clearTimeout(codeSuggestTimer);
    }
    if (!raw) {
        hideCodeSuggestions();
        return;
    }
    codeSuggestTimer = setTimeout(async () => {
        codeSuggestTimer = null;
        try {
            const codes = await fetchCodeSuggestions(raw);
            renderCodeSuggestions(codes);
        } catch (err) {
            hideCodeSuggestions();
        }
    }, 250);
}

function getSuggestionCode(item) {
    return typeof item === "string"
        ? String(item || "").trim().toUpperCase()
        : String(item && item.code ? item.code : "").trim().toUpperCase();
}

function isLikelyCompleteCode(value) {
    return /^\d{6}\.[A-Z]{2}$/.test(String(value || "").trim().toUpperCase());
}

function pickBestSuggestionCode(raw, items) {
    const query = String(raw || "").trim().toUpperCase();
    if (!query || !Array.isArray(items) || !items.length) {
        return query;
    }
    if (activeSuggestionIndex >= 0 && activeSuggestionIndex < items.length) {
        return getSuggestionCode(items[activeSuggestionIndex]);
    }
    const exact = items.find((item) => getSuggestionCode(item) === query);
    if (exact) {
        return getSuggestionCode(exact);
    }
    const prefix = items.find((item) => getSuggestionCode(item).startsWith(query));
    if (prefix) {
        return getSuggestionCode(prefix);
    }
    return getSuggestionCode(items[0]);
}

async function resolveCodeInputOnEnter() {
    const raw = String(codeInput.value || "").trim().toUpperCase();
    if (!raw) {
        return "";
    }
    if (codeSuggestItems.length) {
        return pickBestSuggestionCode(raw, codeSuggestItems);
    }
    if (codeSuggestTimer) {
        clearTimeout(codeSuggestTimer);
        codeSuggestTimer = null;
    }
    try {
        const items = await fetchCodeSuggestions(raw);
        if (!Array.isArray(items) || !items.length) {
            return raw;
        }
        return pickBestSuggestionCode(raw, items);
    } catch (err) {
        return isLikelyCompleteCode(raw) ? raw : "";
    }
}

function renderCodeSuggestions(items) {
    if (!codeSuggestions) {
        return;
    }
    codeSuggestions.innerHTML = "";
    codeSuggestItems = items.slice(0, CODE_SUGGESTION_LIMIT);
    activeSuggestionIndex = -1;
    if (!codeSuggestItems.length) {
        hideCodeSuggestions();
        return;
    }
    for (const item of codeSuggestItems) {
        const code = typeof item === "string" ? item : String(item.code || "").trim().toUpperCase();
        const name = typeof item === "string" ? "" : String(item.name || "").trim();
        const li = document.createElement("li");
        li.textContent = name ? `${name} (${code})` : code;
        li.dataset.code = code;
        li.addEventListener("mousedown", async (event) => {
            event.preventDefault();
            codeInput.value = code;
            hideCodeSuggestions();
            await switchCodeAndReload();
        });
        codeSuggestions.appendChild(li);
    }
    codeSuggestions.classList.add("show");
}

function refreshSuggestionActiveStyle() {
    const children = codeSuggestions.querySelectorAll("li");
    children.forEach((item, index) => {
        if (index === activeSuggestionIndex) {
            item.classList.add("active");
        } else {
            item.classList.remove("active");
        }
    });
}

function bindHeaderTabEvents() {
    if (isMainBoardPage()) {
        bindMainBoardNavLinks();
        return;
    }
    headerTabs.forEach((tab) => {
        if (tab.dataset.headerTabBound === "1") {
            return;
        }
        tab.dataset.headerTabBound = "1";
        tab.addEventListener("click", (event) => {
            event.preventDefault();
            headerTabs.forEach((item) => item.classList.remove("active"));
            tab.classList.add("active");
            currentRightTabName = String(tab.textContent || "").trim();
            renderRightPanelByTab(currentRightTabName);
        });
    });
}

function bindMainBoardNavLinks() {
    if (!isMainBoardPage() || !headerTabsContainer) {
        return;
    }
    headerTabsContainer.querySelectorAll("a.header-tab").forEach((linkEl) => {
        if (linkEl.dataset.navBound === "1") {
            return;
        }
        linkEl.dataset.navBound = "1";
        linkEl.addEventListener("click", () => {
            const typed = String(codeInput && codeInput.value ? codeInput.value : currentCode || "").trim().toUpperCase();
            if (typed && !isYkrsCurveDeniedOnThisSurface(typed)) {
                currentCode = typed;
            }
            persistViewState();
        });
    });
}

function formatDateForInput(dateValue) {
    const dt = dateValue instanceof Date ? dateValue : new Date(dateValue);
    if (!(dt instanceof Date) || Number.isNaN(dt.getTime())) {
        return "";
    }
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, "0");
    const d = String(dt.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

bindHeaderTabEvents();

function rebuildBarsDayIndexMap() {
    barsDayIndexMap = new Map();
    for (let i = 0; i < barsCache.length; i += 1) {
        const dayKey = alignToCurrentInterval(Number(barsCache[i].time));
        if (Number.isFinite(dayKey)) {
            barsDayIndexMap.set(dayKey, i);
        }
    }
    barsDayIndexMapLength = barsCache.length;
}

function ensureBarsDayIndexMap() {
    if (barsDayIndexMapLength !== barsCache.length) {
        rebuildBarsDayIndexMap();
    }
}

function mergeBars(newBars, options = {}) {
    if (shouldUseMorphBarWindow()) {
        replaceMorphBarsWindow([...barsCache, ...(Array.isArray(newBars) ? newBars : [])]);
        return;
    }
    const byTime = new Map();
    for (const bar of barsCache) {
        byTime.set(Number(bar.time), bar);
    }
    for (const bar of newBars) {
        byTime.set(Number(bar.time), bar);
    }
    barsCache = Array.from(byTime.values()).sort((a, b) => Number(a.time) - Number(b.time));
    lastBarTime = barsCache.length > 0 ? Number(barsCache[barsCache.length - 1].time) : null;
    rebuildBarsDayIndexMap();
}

function getFirstBarTime() {
    if (!barsCache.length) {
        return null;
    }
    return Number(barsCache[0].time);
}

function updateBarAvailabilityMeta(meta) {
    if (!meta || typeof meta !== "object") {
        return;
    }
    const first = Number(meta.first_available_bar_time);
    const last = Number(meta.last_available_bar_time);
    if (Number.isFinite(first) && first > 0) {
        firstAvailableBarTime = alignToCurrentInterval(first);
    }
    if (Number.isFinite(last) && last > 0) {
        lastAvailableBarTime = alignToCurrentInterval(last);
    }
}

function isAtAvailableHistoryStart(firstBarTime = getFirstBarTime()) {
    if (!Number.isFinite(firstBarTime)) {
        return false;
    }
    if (!Number.isFinite(firstAvailableBarTime)) {
        return false;
    }
    return alignToCurrentInterval(firstBarTime) <= alignToCurrentInterval(firstAvailableBarTime);
}

function getLastBarTime() {
    if (!barsCache.length) {
        return null;
    }
    return Number(barsCache[barsCache.length - 1].time);
}

function didBarWindowChange(beforeFirstTime, beforeLastTime) {
    return getFirstBarTime() !== beforeFirstTime || getLastBarTime() !== beforeLastTime;
}

function toChartTime(timeSeconds) {
    const ts = Number(timeSeconds);
    if (!Number.isFinite(ts)) {
        return ts;
    }
    if (currentInterval !== "1day") {
        return ts;
    }
    const dt = new Date(ts * 1000);
    return {
        year: dt.getUTCFullYear(),
        month: dt.getUTCMonth() + 1,
        day: dt.getUTCDate()
    };
}

function getUtcDayStartSeconds(tsSeconds) {
    const ts = Number(tsSeconds);
    if (!Number.isFinite(ts)) {
        return null;
    }
    const dt = new Date(ts * 1000);
    return Math.floor(Date.UTC(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate()) / 1000);
}

function getTradingSessionMinuteTimes(dayStartSeconds) {
    const dayStart = Number(dayStartSeconds);
    if (!Number.isFinite(dayStart)) {
        return [];
    }
    const sessions = [
        [9, 30, 11, 30],
        [13, 0, 15, 0],
    ];
    const result = [];
    for (const [startHour, startMinute, endHour, endMinute] of sessions) {
        const start = dayStart + (startHour * 60 + startMinute) * 60;
        const end = dayStart + (endHour * 60 + endMinute) * 60;
        for (let ts = start; ts <= end; ts += 60) {
            result.push(ts);
        }
    }
    return result;
}

function buildLatestDayMinuteWhitespaceItems(existingTimes) {
    if (currentInterval !== "1min" || !barsCache.length) {
        return [];
    }
    const latestDayStart = getUtcDayStartSeconds(barsCache[barsCache.length - 1].time);
    if (latestDayStart === null) {
        return [];
    }
    const realTimes = existingTimes instanceof Set ? existingTimes : new Set();
    return getTradingSessionMinuteTimes(latestDayStart)
        .filter((ts) => !realTimes.has(ts))
        .map((ts) => ({ time: toChartTime(ts) }));
}

function withLatestDayMinuteWhitespace(seriesData) {
    if (currentInterval !== "1min" || !Array.isArray(seriesData) || !seriesData.length) {
        return seriesData;
    }
    const existingTimes = new Set();
    for (const item of seriesData) {
        const ts = Number(item && item.time);
        if (Number.isFinite(ts)) {
            existingTimes.add(ts);
        }
    }
    const whitespaceItems = buildLatestDayMinuteWhitespaceItems(existingTimes);
    if (!whitespaceItems.length) {
        return seriesData;
    }
    return [...seriesData, ...whitespaceItems].sort((a, b) => Number(a.time) - Number(b.time));
}

function formatTradeMarkerNumber(value, digits = 2) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return "--";
    }
    return numeric.toFixed(digits);
}

function formatTradeMarkerAmount(value) {
    const numeric = Math.abs(Number(value));
    if (!Number.isFinite(numeric)) {
        return "--";
    }
    if (numeric >= 100000000) {
        return `${(numeric / 100000000).toFixed(2)}亿`;
    }
    if (numeric >= 10000) {
        return `${(numeric / 10000).toFixed(2)}万`;
    }
    return numeric.toFixed(0);
}

function getDisplayedVolumeValue(bar) {
    const cumulativeVolume = Number(bar && bar.cumulative_volume);
    if (Number.isFinite(cumulativeVolume)) {
        return cumulativeVolume;
    }
    return Number((bar && bar.volume) || 0);
}

function renderChartData() {
    applyMainChartSeriesMode();
    const ohlc = withLatestDayMinuteWhitespace(barsCache.map((item) => ({
        time: toChartTime(item.time),
        open: Number(item.open),
        high: Number(item.high),
        low: Number(item.low),
        close: Number(item.close)
    })));
    const lineData = withLatestDayMinuteWhitespace(barsCache.map((item) => ({
        time: toChartTime(item.time),
        value: Number(item.close)
    })));
    const benchmarkLineData = benchmarkBarsCache.map((item) => ({
        time: toChartTime(item.time),
        value: Number(item.close)
    }));
    const volume = withLatestDayMinuteWhitespace(barsCache.map((item) => ({
        time: toChartTime(item.time),
        value: getDisplayedVolumeValue(item),
        color: getAShareBarColor(item)
    })));
    if (isMainChartLineMode()) {
        candlestickSeries.setData([]);
        mainLineSeries.setData(lineData);
        volumeSeries.setData([]);
    } else {
        mainLineSeries.setData([]);
        candlestickSeries.setData(ohlc);
        volumeSeries.setData(volume);
    }
    benchmarkLineSeries.setData(shouldShowBenchmarkOverlay() ? benchmarkLineData : []);
    const indexLineData = buildRebasedIndexOverlayLineData();
    const showIndexOverlay = shouldShowIndexOverlay() && indexLineData.length > 0;
    indexOverlayLineSeries.setData(showIndexOverlay ? indexLineData : []);
    applyIndexOverlaySeriesVisibility();
    applyBacktestOrderMarkers();
    applyChartTimeScaleBounds();
    updatePortfolioChartLegend();
}

function computeSignalInitialLimit() {
    if (!barsCache.length) {
        return FACTOR_FETCH_LIMIT_INITIAL;
    }
    return Math.min(
        FACTOR_FETCH_LIMIT_MAX,
        Math.max(300, barsCache.length)
    );
}

function computeSignalRangeFromBars() {
    const nowTs = alignToCurrentInterval(Math.floor(Date.now() / 1000));
    if (!barsCache.length) {
        return {
            fromTs: nowTs - INTERVAL_CONFIG["1day"].lookbackFallbacks[0],
            toTs: nowTs
        };
    }
    return {
        fromTs: Number(barsCache[0].time),
        toTs: Number(barsCache[barsCache.length - 1].time)
    };
}

function moveToLatest() {
    if (lastBarTime === null || !barsCache.length) {
        return;
    }
    const current = chart.timeScale().getVisibleLogicalRange();
    const span = current ? Math.max(10, current.to - current.from) : 100;
    const maxIndex = barsCache.length - 1;
    setMainChartVisibleLogicalRange({
        from: maxIndex - span * 0.8,
        to: maxIndex + span * 0.2
    });
}

function moveToLatestFixedWindow() {
    if (lastBarTime === null || !barsCache.length) {
        return;
    }
    const span = shouldUseMorphBarWindow()
        ? Math.min(100, MORPH_WINDOW_MAX_VISIBLE_BARS, barsCache.length)
        : 100;
    const maxIndex = barsCache.length - 1;
    if (shouldUseMorphBarWindow()) {
        suppressMorphWindowEdgeCheck();
    }
    setMainChartVisibleLogicalRange({
        from: maxIndex - span * 0.8,
        to: maxIndex + span * 0.2
    });
}

function resetViewAfterSymbolSwitch() {
    // 切换股票后恢复时间轴和价格轴自动缩放，避免沿用上一只股票的手动缩放状态。
    resetMorphWindowState();
    applyMainChartSeriesMode();
    chart.priceScale("right").applyOptions({ autoScale: true });
    signalChart.priceScale("right").applyOptions({ autoScale: true });
    moveToLatestFixedWindow();
    syncSignalChartViewportFromMain();
    scheduleHistoryPrefetchAfterViewSettle();
}

async function loadOlderBarsIfNeeded(options = {}) {
    if (shouldUseMorphBarWindow()) {
        return;
    }
    if (isLoadingHistory || historyExhausted || isRequesting || !barsCache.length) {
        return;
    }
    if (!shouldLoadOlderBars(options)) {
        return;
    }

    const firstBarTime = getFirstBarTime();
    if (firstBarTime === null) {
        return;
    }
    if (isAtAvailableHistoryStart(firstBarTime)) {
        historyExhausted = true;
        return;
    }

    let toTs = alignToCurrentInterval(firstBarTime - getIntervalConfig().alignStepSeconds);
    if (!Number.isFinite(toTs) || toTs <= 0) {
        historyExhausted = true;
        return;
    }
    if (lastHistoryRequestTo !== null && toTs >= lastHistoryRequestTo) {
        toTs = alignToCurrentInterval(lastHistoryRequestTo - getIntervalConfig().alignStepSeconds);
        if (!Number.isFinite(toTs) || toTs <= 0) {
            historyExhausted = true;
            return;
        }
    }

    isLoadingHistory = true;
    lastHistoryRequestTo = toTs;
    try {
        let incoming = [];
        let loadedFromTs = null;
        let loadedToTs = null;
        for (let round = 0; round < HISTORY_EMPTY_WINDOW_SKIP_ROUNDS; round += 1) {
            if (Number.isFinite(firstAvailableBarTime) && toTs <= firstAvailableBarTime) {
                historyExhausted = true;
                return;
            }
            const fromTs = alignToCurrentInterval(toTs - getIntervalConfig().historicalBackfillWindowSeconds);
            const payload = await fetchBars(currentCode, fromTs, toTs, null, {
                allowNotFound: true,
                limit: 5000,
            });
            updateBarAvailabilityMeta(payload.meta);
            incoming = Array.isArray(payload.bars) ? payload.bars : [];
            if (incoming.length > 0) {
                loadedFromTs = fromTs;
                loadedToTs = toTs;
                break;
            }
            if (!Number.isFinite(firstAvailableBarTime) || fromTs <= firstAvailableBarTime) {
                historyExhausted = true;
                return;
            }
            toTs = alignToCurrentInterval(fromTs - getIntervalConfig().alignStepSeconds);
            lastHistoryRequestTo = toTs;
        }
        if (incoming.length === 0) {
            if (isAtAvailableHistoryStart()) {
                historyExhausted = true;
            }
            return;
        }
        mergeBars(incoming, { trimSide: "oldest" });
        await refreshChartOverlays();
        renderChartData();
        await refreshBacktestOrderMarkers();
        if (currentInterval === "1day" && !isYkrsCode()) {
            const rangeFromTs = alignToCurrentInterval(loadedFromTs);
            const rangeToTs = alignToCurrentInterval(loadedToTs);
            if (getBoundSignalSlotFactorNames().size || getAdHocActiveFactorNames().length) {
                await backfillSignalsForRange(rangeFromTs, rangeToTs);
            } else if (isMorphSignalTab()) {
                void backfillMorphSignalsForRange(rangeFromTs, rangeToTs);
            } else {
                renderSignalData();
                syncSignalChartViewportFromMain();
            }
        }
    } catch (err) {
        const message = err instanceof Error ? err.message : "历史补数失败";
        logUiHint(`历史补数: ${message}`);
    } finally {
        isLoadingHistory = false;
    }
}

async function waitUntilRequestIdle(timeoutMs = 5000) {
    const start = Date.now();
    while (isRequesting) {
        if (Date.now() - start >= timeoutMs) {
            return false;
        }
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
    return true;
}

async function refreshBars(isInitialLoad = false) {
    if (isInfoBoardPage()) {
        return;
    }
    if (isRequesting) {
        return;
    }
    if (isYkrsCurveDeniedOnThisSurface()) {
        barsCache = [];
        benchmarkBarsCache = [];
        lastBarTime = null;
        candlestickSeries.setData([]);
        mainLineSeries.setData([]);
        benchmarkLineSeries.setData([]);
        volumeSeries.setData([]);
        backtestOrderItems = [];
        applyBacktestOrderMarkers();
        signalPoints = [];
        lastSignalTime = null;
        renderSignalData();
        setConnectedStatus();
        await refreshCenterBottomPanel();
        logUiHint(
            `未查询到 ${currentCode} 的有效数据。`,
        );
        return;
    }
    isRequesting = true;
    try {
        const nowTs = alignToCurrentInterval(Math.floor(Date.now() / 1000));
        let payload = null;
        let incoming = [];
        if (isInitialLoad) {
            firstAvailableBarTime = null;
            lastAvailableBarTime = null;
        }

        if (isInitialLoad || lastBarTime === null) {
            let loaded = false;

            if (isYkrsCode() && currentInterval === "1day" && getSelectedRunTag()) {
                try {
                    const backtestRange = await resolveYkrsDailyBarWindow();
                    if (backtestRange) {
                        payload = await fetchBars(
                            currentCode,
                            backtestRange.fromTs,
                            backtestRange.toTs,
                            null,
                            { allowNotFound: true }
                        );
                        incoming = Array.isArray(payload.bars) ? payload.bars : [];
                        loaded = incoming.length > 0;
                    }
                } catch (err) {
                    console.warn("按回测区间加载 YKRS 曲线失败", err);
                }
            }

            if (!loaded && !(isYkrsCode() && currentInterval === "1day")) {
                // 初始加载做扩窗回退，避免连接正常但看不到数据。
                for (const lookback of getIntervalConfig().lookbackFallbacks) {
                    const fromTs = nowTs - lookback;
                    payload = await fetchBars(currentCode, fromTs, nowTs, null, { allowNotFound: true });
                    incoming = Array.isArray(payload.bars) ? payload.bars : [];
                    if (incoming.length > 0) {
                        loaded = true;
                        break;
                    }
                }
            }

            if (!loaded) {
                barsCache = [];
                benchmarkBarsCache = [];
                indexOverlayBarsCache = [];
                candlestickSeries.setData([]);
                mainLineSeries.setData([]);
                benchmarkLineSeries.setData([]);
                indexOverlayLineSeries.setData([]);
                volumeSeries.setData([]);
                backtestOrderItems = [];
                applyBacktestOrderMarkers();
                signalPoints = [];
                lastSignalTime = null;
                renderSignalData();
                setConnectedStatus();
                await refreshCenterBottomPanel();
                if (!(isYkrsCode() && currentInterval === "1day" && !getSelectedRunTag())) {
                    logUiHint(`未查询到 ${currentCode} 的有效数据，请检查 code 或时间范围`);
                }
                return;
            }
        } else {
            const fromTs = lastBarTime;
            payload = await fetchBars(currentCode, fromTs, nowTs, lastBarTime, { allowNotFound: true });
            incoming = Array.isArray(payload.bars) ? payload.bars : [];
        }
        updateBarAvailabilityMeta(payload && payload.meta);

        if (isInitialLoad) {
            barsCache = [];
            historyExhausted = false;
            lastHistoryRequestTo = null;
            if (shouldUseMorphBarWindow()) {
                resetMorphWindowState();
            }
        }

        const skipMorphHistoricalRefresh = !isInitialLoad
            && shouldUseMorphBarWindow()
            && !morphWindowAtLatest;
        if (skipMorphHistoricalRefresh) {
            setConnectedStatus();
            return;
        }

        const hasNewData = payload.meta && payload.meta.has_new_data === true;

        if (shouldUseMorphBarWindow()) {
            replaceMorphBarsWindow(isInitialLoad ? incoming : [...barsCache, ...incoming]);
        } else {
            mergeBars(incoming, { trimSide: isInitialLoad ? "latest" : (hasNewData ? "latest" : "oldest") });
        }
        if (isInitialLoad) {
            benchmarkBarsCache = [];
            indexOverlayBarsCache = [];
            renderChartData();
            runBackgroundTask("refreshChartOverlays", async () => {
                await refreshChartOverlays();
                renderChartData();
                await syncIndexOverlayAfterBarsRefresh();
            });
            runBackgroundTask("refreshBacktestOrderMarkers", refreshBacktestOrderMarkers);
        } else {
            await refreshChartOverlays();
            renderChartData();
            await syncIndexOverlayAfterBarsRefresh();
            await refreshBacktestOrderMarkers();
        }
        if (PAGE_VIEW === "quant") {
            if (!isInitialLoad || getBoundSignalSlotFactorNames().size || activeFactorNames.length) {
                if (isInitialLoad) {
                    runBackgroundTask("refreshInitialSignalData", async () => {
                        await refreshSlotBoundSignalData(true);
                        if (activeFactorNames.length) {
                            await refreshSignalData(true);
                        }
                    });
                } else {
                    await refreshSlotBoundSignalData(isInitialLoad);
                    if (activeFactorNames.length) {
                        await refreshSignalData(isInitialLoad);
                    }
                }
            }
        } else if (PAGE_VIEW === "morph") {
            await refreshMorphSignalData(isInitialLoad);
        } else {
            renderSignalData();
        }
        /* 增量刷新不重绘中间下区，避免定时拉数打断回测表单输入焦点。 */
        if (isInitialLoad) {
            runBackgroundTask("refreshCenterBottomPanel", refreshCenterBottomPanel);
        }
        scheduleFactorSnapshotForRightPanel(lastBarTime, true);
        setConnectedStatus();

        if (isInitialLoad) {
            chart.priceScale("right").applyOptions({ autoScale: true });
            signalChart.priceScale("right").applyOptions({ autoScale: true });
            moveToLatestFixedWindow();
            syncSignalChartViewportFromMain();
            applyMorphMainChartTimeScaleOptions();
            if (!shouldUseMorphBarWindow()) {
                scheduleHistoryPrefetchAfterViewSettle();
            }
        } else {
            if (hasNewData && (!shouldUseMorphBarWindow() || morphWindowAtLatest)) {
                moveToLatest();
            }
        }
    } catch (err) {
        const message = err instanceof Error ? err.message : "鏈煡寮傚父";
        setBrokenStatus(message);
    } finally {
        isRequesting = false;
    }
}

function syncYkrsCurveSelectDom() {
    if (!PAGE_BOOT.allowYkrsCurve || !ykrsCurveSelect) {
        return;
    }
    const c = normalizeCodeValue(currentCode);
    if (YKRS_CURVE_PICKER_CODES.includes(c)) {
        ykrsCurveSelect.value = c;
    }
}

function initYkrsCurvePickerOnce() {
    if (!PAGE_BOOT.allowYkrsCurve || !ykrsCurveSelect) {
        return;
    }
    if (ykrsCurveSelect.dataset.portfolioPickerBound === "1") {
        return;
    }
    ykrsCurveSelect.dataset.portfolioPickerBound = "1";
    ykrsCurveSelect.addEventListener("change", () => {
        const v = String(ykrsCurveSelect.value || "").trim().toUpperCase();
        void switchCodeAndReload(v);
    });
    syncYkrsCurveSelectDom();
}

async function fetchMarketIndexCodes() {
    const url = `${API_BASE_URL}/api/market/index-codes`;
    const resp = await fetch(url, { method: "GET", cache: "no-store" });
    let body = {};
    try {
        body = await resp.json();
    } catch (_) {
        body = {};
    }
    if (!resp.ok) {
        if (isIndexRouteMissingResponse(resp.status, body)) {
            return [];
        }
        const message = body && body.error && body.error.message ? body.error.message : "指数列表获取失败";
        throw new Error(message);
    }
    return Array.isArray(body.items) ? body.items : [];
}

async function initPortfolioExtraSelectOnce() {
    if (!PAGE_BOOT.allowYkrsCurve || !portfolioExtraSelect) {
        return;
    }
    if (portfolioExtraSelect.dataset.portfolioExtraBound === "1") {
        return;
    }
    portfolioExtraSelect.dataset.portfolioExtraBound = "1";

    portfolioExtraSelect.innerHTML = '<option value="">指数叠加...</option>';

    const indexApiReady = await apiSupportsIndexOverlay();
    if (!indexApiReady) {
        setPortfolioIndexOverlayStatus(
            "API 鏈姞杞芥寚鏁版帴鍙ｏ細璇峰仠姝㈠苟閲嶆柊杩愯 鍙鍖?api_server.py锛屽啀鍒锋柊鏈〉",
            true
        );
    }

    try {
        const items = await fetchMarketIndexCodes();
        for (const item of items) {
            const code = normalizeCodeValue(item && item.code);
            if (!code) {
                continue;
            }
            const option = document.createElement("option");
            option.value = code;
            const name = String((item && item.name) || "").trim();
            option.dataset.indexName = name || code;
            option.textContent = name ? `${name} (${code})` : code;
            portfolioExtraSelect.appendChild(option);
        }
    } catch (err) {
        const message = err instanceof Error ? err.message : "指数列表加载失败";
        logUiHint(message);
        for (const code of ["000001.SH", "399001.SZ"]) {
            const option = document.createElement("option");
            option.value = code;
            option.textContent = code;
            portfolioExtraSelect.appendChild(option);
        }
    }

    portfolioExtraSelect.addEventListener("change", () => {
        selectedPortfolioIndexCode = normalizeCodeValue(portfolioExtraSelect.value);
        try {
            if (selectedPortfolioIndexCode) {
                sessionStorage.setItem(PORTFOLIO_INDEX_OVERLAY_STORAGE_KEY, selectedPortfolioIndexCode);
            } else {
                sessionStorage.removeItem(PORTFOLIO_INDEX_OVERLAY_STORAGE_KEY);
            }
        } catch (_) {
            /* ignore */
        }
        updatePortfolioChartLegend();
        void applyPortfolioIndexOverlaySelection(true);
    });

    try {
        const savedCode = normalizeCodeValue(sessionStorage.getItem(PORTFOLIO_INDEX_OVERLAY_STORAGE_KEY) || "");
        if (savedCode) {
            const hasOption = Array.from(portfolioExtraSelect.options).some((opt) => opt.value === savedCode);
            if (hasOption) {
                portfolioExtraSelect.value = savedCode;
                selectedPortfolioIndexCode = savedCode;
            }
        }
    } catch (_) {
        /* ignore */
    }
}

async function applyPortfolioIndexOverlaySelection(showHint = false) {
    if (!PAGE_BOOT.allowYkrsCurve) {
        return;
    }
    try {
        if (!barsCache.length) {
            if (showHint) {
                setPortfolioIndexOverlayStatus("请等待组合曲线加载完成后再选择指数", true);
            }
            return;
        }
        await refreshIndexOverlay();
        renderChartData();
        chart.priceScale("right").applyOptions({ autoScale: true });
        const lineData = buildRebasedIndexOverlayLineData();
        if (!selectedPortfolioIndexCode) {
            setPortfolioIndexOverlayStatus("");
            return;
        }
        const label = portfolioExtraSelect && portfolioExtraSelect.selectedOptions[0]
            ? portfolioExtraSelect.selectedOptions[0].textContent
            : selectedPortfolioIndexCode;
        if (!indexOverlayBarsCache.length) {
            const apiReady = await apiSupportsIndexOverlay();
            const msg = apiReady
                ? `未查到 ${selectedPortfolioIndexCode} 指数数据，请确认 D:\database\index_data_daily 已有 parquet`
                : `未查到指数数据，请确认 API 已支持 /api/market/index/bars`;
            if (showHint) {
                setPortfolioIndexOverlayStatus(msg, true);
            }
            return;
        }
        if (!lineData.length) {
            const msg = `${label}: 日期与组合曲线未对齐，指数 ${indexOverlayBarsCache.length} 条，对齐 0 条`;
            if (showHint) {
                setPortfolioIndexOverlayStatus(msg, true);
            }
            return;
        }
        const msg = `已加载 ${label} 绿线，${lineData.length} 点`;
        if (showHint) {
            setPortfolioIndexOverlayStatus(msg, false);
        }
    } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setPortfolioIndexOverlayStatus(`指数叠加失败: ${message}`, true);
        console.error(err);
    }
}

async function switchCodeAndReload(nextCodeArg = null) {
    const nextCode = String(nextCodeArg ?? codeInput.value).trim().toUpperCase();
    if (!nextCode) {
        logUiHint("code 不能为空");
        return;
    }
    if (isYkrsCurveDeniedOnThisSurface(nextCode)) {
        logUiHint("组合回测曲线仅在组合结果页提供。");
        return;
    }
    if (isSwitchingCode || isRequesting) {
        pendingSwitchCode = nextCode;
        logUiHint(`姝ｅ湪鍒锋柊锛屽凡鎺掗槦鍒囨崲鍒?${nextCode}`);
        return;
    }
    isSwitchingCode = true;
    try {
        const previousCode = currentCode;
        codeInput.value = nextCode;
        currentCode = nextCode;
        applySignalChartVisibility();
        if (isInfoBoardPage()) {
            persistViewState();
            clearCodeInputOnNextEdit = true;
            selectedWatchCode = currentCode;
            renderWatchlist();
            if (window.ChartBoardView && typeof window.ChartBoardView.onCodeChange === "function") {
                await window.ChartBoardView.onCodeChange(currentCode);
            }
            await refreshWatchlistPrices();
            return;
        }
        applyPrimaryRightTabLabel();
        beginRightPanelSnapshotInteraction();
        rightPanelSnapshotCache.clear();
        currentFactorSnapshotPayload = null;
        lastRenderedSnapshotKey = "";
        updateExportFactorOptions();
        currentBacktestPositionSnapshot = null;
        currentBacktestPositionHoverCode = "";
        snapshotRequestSeq += 1;
        barsCache = [];
        lastBarTime = null;
        backtestOrderItems = [];
        applyBacktestOrderMarkers();
        signalPoints = [];
        lastSignalTime = null;
        extraSignalPointsByFactor.clear();
        extraLastSignalTimeByFactor.clear();
        for (const factorName of Array.from(extraSignalSeriesByFactor.keys())) {
            clearExtraSignalSeries(factorName);
        }
        clearCoupledSignalLayer();
        slotSignalPointsByKey.clear();
        slotLastSignalTimeByKey.clear();
        clearMissingFactorKeysForCurrentContext();
        historyExhausted = false;
        lastHistoryRequestTo = null;
        firstAvailableBarTime = null;
        lastAvailableBarTime = null;
        morphPatternPointsByName.clear();
        morphEventsByDay.clear();
        morphLoadedLevelKey = "";
        morphSummaryPointsCache = [];
        resetMorphWindowState();
        resetVisibleLogicalSnapshot();
        await refreshBars(true);
        if (barsCache.length > 0) {
            persistViewState();
            clearCodeInputOnNextEdit = true;
            if (PAGE_VIEW === "quant") {
                await refreshSlotBoundSignalData(true);
                if (activeFactorNames.length) {
                    await refreshSignalData(true);
                }
            }
        } else {
            // 查询失败时不要覆盖上次浏览状态，并回退到可用 code。
            currentCode = previousCode;
            codeInput.value = previousCode;
            applySignalChartVisibility();
            applyPrimaryRightTabLabel();
            if (previousCode) {
                await refreshBars(true);
            }
            await refreshCenterBottomPanel();
        }
        selectedWatchCode = currentCode;
        await refreshWatchlistPrices();
    } finally {
        isSwitchingCode = false;
        syncYkrsCurveSelectDom();
        if (pendingSwitchCode) {
            const queuedCode = String(pendingSwitchCode || "").trim().toUpperCase();
            pendingSwitchCode = "";
            if (queuedCode) {
                setTimeout(() => {
                    void switchCodeAndReload(queuedCode);
                }, 0);
            }
        }
    }
}

async function switchIntervalAndReload() {
    const idle = await waitUntilRequestIdle(6000);
    if (!idle) {
        logUiHint("正在刷新，请稍后再切换周期");
        return;
    }
    currentInterval = intervalSelect.value;
    updateAdjustModeControlVisibility();
    applySignalChartVisibility();
    beginRightPanelSnapshotInteraction();
    rightPanelSnapshotCache.clear();
    currentFactorSnapshotPayload = null;
    lastRenderedSnapshotKey = "";
    updateExportFactorOptions();
    currentBacktestPositionSnapshot = null;
    currentBacktestPositionHoverCode = "";
    snapshotRequestSeq += 1;
    barsCache = [];
    lastBarTime = null;
    backtestOrderItems = [];
    applyBacktestOrderMarkers();
    signalPoints = [];
    lastSignalTime = null;
    extraSignalPointsByFactor.clear();
    extraLastSignalTimeByFactor.clear();
    for (const factorName of Array.from(extraSignalSeriesByFactor.keys())) {
        clearExtraSignalSeries(factorName);
    }
    clearCoupledSignalLayer();
    slotSignalPointsByKey.clear();
    slotLastSignalTimeByKey.clear();
    historyExhausted = false;
    lastHistoryRequestTo = null;
    morphPatternPointsByName.clear();
    morphEventsByDay.clear();
    morphLoadedLevelKey = "";
    morphSummaryPointsCache = [];
    resetMorphWindowState();
    resetVisibleLogicalSnapshot();
    await refreshBars(true);
    if (barsCache.length > 0) {
        persistViewState();
    }
    await refreshWatchlistPrices();
}

function startAutoRefresh() {
    if (document.visibilityState === "hidden") {
        return;
    }
    if (isFundamentalBoardPage()) {
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
        if (countdownTimer) {
            clearInterval(countdownTimer);
            countdownTimer = null;
        }
        return;
    }
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }
    if (countdownTimer) {
        clearInterval(countdownTimer);
        countdownTimer = null;
    }
    countdownValue = AUTO_REFRESH_SECONDS;

    refreshTimer = setInterval(async () => {
        if (isSwitchingCode || isRequesting) {
            return;
        }
        countdownValue = AUTO_REFRESH_SECONDS;
        if (isInfoBoardPage()) {
            if (
                window.ChartBoardView
                && typeof window.ChartBoardView.onCodeChange === "function"
                && String(currentCode || "").trim()
            ) {
                await window.ChartBoardView.onCodeChange(currentCode);
            }
        } else {
            await refreshBars(false);
        }
        await refreshWatchlistPrices();
    }, AUTO_REFRESH_SECONDS * 1000);
}

function syncWatchlistSelectionToCurrentCode() {
    const code = String(currentCode || "").trim().toUpperCase();
    if (!code) {
        return;
    }
    if (watchlistCodes.includes(code)) {
        selectedWatchCode = code;
    }
    codeInput.value = code;
    renderWatchlist();
}


if (signalTypeTogglesWrap) {
    applySignalTypeToggleUi();
    signalTypeTogglesWrap.addEventListener("click", (event) => {
        if (Date.now() < suppressSignalSlotClickUntil) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        const btnEl = event.target instanceof Element
            ? event.target.closest(".signal-type-toggle[data-signal-type]")
            : null;
        if (!btnEl || !signalTypeTogglesWrap.contains(btnEl)) {
            return;
        }
        const key = String(btnEl.dataset.signalType || "");
        if (!(key in signalTypeToggleState)) {
            return;
        }
        void toggleSignalSlotByKey(key);
    });
}

window.getSignalTypeToggleState = getSignalTypeToggleState;
window.getSignalSlotBindings = () => ({ ...signalSlotBindings });
codeInput.addEventListener("focusin", () => {
    consumePendingCodeInputClear();
    scheduleCodeSuggestions(codeInput.value);
});

codeInput.addEventListener("input", () => {
    scheduleCodeSuggestions(codeInput.value);
});

codeInput.addEventListener("keydown", async (event) => {
    const key0 = event.key;
    if (
        clearCodeInputOnNextEdit &&
        key0.length === 1 &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
    ) {
        event.preventDefault();
        clearCodeInputOnNextEdit = false;
        codeInput.value = key0;
        codeInput.setSelectionRange(1, 1);
        codeInput.dispatchEvent(new Event("input", { bubbles: true }));
        return;
    }
    if (event.key === "ArrowDown" && codeSuggestItems.length) {
        event.preventDefault();
        activeSuggestionIndex = Math.min(activeSuggestionIndex + 1, codeSuggestItems.length - 1);
        refreshSuggestionActiveStyle();
        return;
    }
    if (event.key === "ArrowUp" && codeSuggestItems.length) {
        event.preventDefault();
        activeSuggestionIndex = Math.max(activeSuggestionIndex - 1, 0);
        refreshSuggestionActiveStyle();
        return;
    }
    if (event.key === "Escape") {
        hideCodeSuggestions();
        return;
    }
    if (event.key === "Enter") {
        event.preventDefault();
        const resolved = await resolveCodeInputOnEnter();
        if (!resolved) {
            logUiHint("code 涓嶈兘涓虹┖");
            hideCodeSuggestions();
            return;
        }
        codeInput.value = resolved;
        hideCodeSuggestions();
        await switchCodeAndReload(resolved);
        countdownValue = AUTO_REFRESH_SECONDS;
    }
});

if (addWatchCurrentBtn) {
    addWatchCurrentBtn.addEventListener("click", async () => {
        const code = currentCode.trim().toUpperCase();
        if (!code) {
            return;
        }
        if (isYkrsCurveDeniedOnThisSurface(code)) {
            logUiHint("组合回测曲线不能加入主站自选。");
            return;
        }
        if (!watchlistCodes.includes(code)) {
            watchlistCodes.unshift(code);
        }
        selectedWatchCode = code;
        persistWatchlistState();
        persistViewState();
        renderWatchlist();
        await refreshWatchlistPrices();
    });
}

document.addEventListener("click", (event) => {
    if (!codeSuggestions.contains(event.target) && event.target !== codeInput) {
        hideCodeSuggestions();
    }
});

// 寤惰繜鍒拌皟鐢ㄦ椂鍐嶈В鏋?handler锛岄伩鍏?board_*.js 瑕嗙洊 stub 鍚庣洃鍚粛鎸囧悜绌哄嚱鏁?
document.addEventListener("keydown", (event) => {
});
bindDailyChartDoubleClickModal();

rightPanel.addEventListener("pointerdown", (event) => beginFactorSnapshotDrag(event));
rightPanel.addEventListener("pointerdown", (event) => beginFactorGroupDrag(event));
document.addEventListener("pointermove", (event) => moveFactorSnapshotDrag(event));
document.addEventListener("pointermove", (event) => moveFactorGroupDrag(event));
document.addEventListener("pointerup", (event) => endFactorSnapshotDrag(event));
document.addEventListener("pointerup", (event) => endFactorGroupDrag(event));
document.addEventListener("pointercancel", (event) => endFactorSnapshotDrag(event));
document.addEventListener("pointercancel", (event) => endFactorGroupDrag(event));

rightPanel.addEventListener("click", async (event) => {
    if (currentRightTabName !== "量化因子") {
        return;
    }
    if (Date.now() < suppressFactorSnapshotClickUntil) {
        return;
    }
    const coupleBtnEl = event.target instanceof Element ? event.target.closest("#factor-snapshot-couple-btn") : null;
    if (coupleBtnEl) {
        event.preventDefault();
        event.stopPropagation();
        void runFactorCoupleFromUi();
        return;
    }
    if (shouldUseBacktestPositionSnapshotPanel()) {
        const positionItem = event.target instanceof Element ? event.target.closest(".position-snapshot-item") : null;
        if (!positionItem || !currentBacktestPositionSnapshot) {
            return;
        }
        const itemCode = String(positionItem.getAttribute("data-position-code") || "").trim();
        if (!itemCode) {
            return;
        }
        currentBacktestPositionHoverCode = itemCode;
        renderBacktestPositionSnapshotToRightPanel(
            currentBacktestPositionSnapshot,
            Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime
        );
        return;
    }
    const groupToggleBtn = event.target instanceof Element ? event.target.closest(".factor-group-toggle") : null;
    if (groupToggleBtn) {
        event.preventDefault();
        event.stopPropagation();
        const groupId = String(groupToggleBtn.getAttribute("data-group-id") || "").trim();
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
    const clearBtn = event.target instanceof Element ? event.target.closest("#factor-clear-btn") : null;
    if (clearBtn) {
        await clearExtraActiveFactors();
        return;
    }
    const item = event.target instanceof Element ? event.target.closest(".factor-snapshot-item") : null;
    if (!item) {
        return;
    }
    const factorName = item.getAttribute("data-factor-name");
    if (!factorName) {
        return;
    }
    await toggleFactorActiveState(factorName);
});

rightPanel.addEventListener("mouseover", (event) => {
    if (currentRightTabName !== "量化因子" || !shouldUseBacktestPositionSnapshotPanel()) {
        return;
    }
    const positionItem = event.target instanceof Element ? event.target.closest(".position-snapshot-item") : null;
    if (!positionItem || !currentBacktestPositionSnapshot) {
        return;
    }
    const itemCode = String(positionItem.getAttribute("data-position-code") || "").trim();
    if (!itemCode || itemCode === currentBacktestPositionHoverCode) {
        return;
    }
    currentBacktestPositionHoverCode = itemCode;
    renderBacktestPositionSnapshotToRightPanel(
        currentBacktestPositionSnapshot,
        Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : lastBarTime
    );
});

new ResizeObserver(() => {
    applyChartSize();
}).observe(container);

new ResizeObserver(() => {
    applyChartSize();
}).observe(signalChartContainer);

document.addEventListener("keydown", onGlobalChartNavigationKeydown);
container.addEventListener("pointerdown", beginRightPanelSnapshotInteraction);
signalChartContainer.addEventListener("pointerdown", beginRightPanelSnapshotInteraction);
container.addEventListener("wheel", beginRightPanelSnapshotInteraction, { passive: true });
signalChartContainer.addEventListener("wheel", beginRightPanelSnapshotInteraction, { passive: true });
container.addEventListener("mousemove", exitKeyboardCrosshairMode);
signalChartContainer.addEventListener("mousemove", exitKeyboardCrosshairMode);

chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    onMainChartViewportChange();
});

chart.timeScale().subscribeVisibleTimeRangeChange(() => {
    if (shouldUseMorphBarWindow()) {
        scheduleMorphOverlayViewportRedraw();
        return;
    }
    onMainChartViewportChange();
});

bindMorphWindowChartInteractionGuard();

window.ChartBoardBoot = async function ChartBoardBoot() {
    await waitForApiReady();
    if (!isInfoBoardPage()) {
        runBackgroundTask("loadBacktestModelsCatalog", loadBacktestModelsCatalog);
    }
    initResizableLayout();
    if (isMainBoardPage()) {
        bindMainBoardNavLinks();
    }
    if (!PAGE_BOOT.embedMode && window.initEdgeFloatHud && typeof window.initEdgeFloatHud === "function") {
        window.initEdgeFloatHud({ pageId: "chart", onNavigate: edgeFloatNavigateToPage });
    }
    restoreWatchlistState();
    runBackgroundTask("hydrateWatchlistFromServer", async () => {
        await hydrateWatchlistFromServer();
        syncWatchlistSelectionToCurrentCode();
        renderWatchlist();
        await refreshWatchlistPrices();
    });
    installRightPanelModelOverlayHandlers();

    if (PAGE_BOOT.code) {
        currentCode = PAGE_BOOT.code;
        codeInput.value = PAGE_BOOT.code;
        selectedWatchCode = PAGE_BOOT.code;
        if (!watchlistCodes.includes(PAGE_BOOT.code)) {
            watchlistCodes.unshift(PAGE_BOOT.code);
        }
    }

    if (PAGE_BOOT.allowYkrsCurve) {
        currentInterval = "1day";
        intervalSelect.value = "1day";
        const titleEl = document.querySelector(".page-header-title");
        if (titleEl) {
            titleEl.textContent = "回测组合结果";
        }
        document.title = "回测组合结果";
    } else {
        // 最后浏览视图优先级高于 watchlist 选中项。
        restoreViewState();
    }

    updateAdjustModeControlVisibility();
    applySignalChartVisibility();
    if (isMainBoardPage()) {
        if (!isInfoBoardPage()) {
            restoreExpandedFactorGroups();
            restoreQuantFactorUi();
        }
    } else {
        applyPrimaryRightTabLabel();
        restoreExpandedFactorGroups();
        const activeTab = headerTabs.find((tab) => tab.classList.contains("active"));
        renderRightPanelByTab(activeTab ? activeTab.textContent.trim() : getPrimaryRightTabLabel());
    }
    syncWatchlistSelectionToCurrentCode();
    clearMissingFactorKeysForCurrentContext();
    if (PAGE_VIEW === "quant") {
        applySignalSlotBindingUi();
        runBackgroundTask("loadFactorOptions", loadFactorOptions);
    } else if (PAGE_VIEW === "morph") {
        installMorphPanelUi();
    }
    renderWatchlist();
    updatePageClock();
    setInterval(updatePageClock, 1000);
    initYkrsCurvePickerOnce();
    if (!isInfoBoardPage()) {
        await refreshBars(true);
    }
    initPortfolioPrintLightToggleOnce();
    runBackgroundTask("initPortfolioExtraSelectOnce", initPortfolioExtraSelectOnce);
    if (PAGE_BOOT.allowYkrsCurve && selectedPortfolioIndexCode) {
        runBackgroundTask("applyPortfolioIndexOverlaySelection", () => applyPortfolioIndexOverlaySelection(false));
    }
    runBackgroundTask("refreshWatchlistPrices", refreshWatchlistPrices);
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            startAutoRefresh();
        } else if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
    });
    if (isMainBoardPage()) {
        bindMainBoardNavLinks();
    }
    if (isMainBoardPage()) {
        runBackgroundTask("initViewForCurrentPage", initViewForCurrentPage);
    }
    startAutoRefresh();
};
