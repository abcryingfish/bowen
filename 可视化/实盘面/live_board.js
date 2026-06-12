(function () {
    "use strict";

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
        } catch (_) {
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
        } catch (_) {
            /* ignore */
        }
        try {
            if (window.location.protocol === "http:" || window.location.protocol === "https:") {
                return `http://${window.location.hostname}:8000`;
            }
        } catch (_) {
            /* ignore */
        }
        return "http://127.0.0.1:8000";
    }

    const API_BASE_URL = resolveApiBaseUrl();
    const DEFAULT_ADJUST = "forward";
    const DAILY_INTERVAL = "1day";
    const LOOKBACK_DAYS = 220;
    const AUTO_REFRESH_MS = 30000;
    const DAY_SECONDS = 24 * 60 * 60;
    const FOCUS_INITIAL_LOOKBACK_DAYS = 365;
    const FOCUS_FETCH_LIMIT = 320;
    const FOCUS_HISTORY_WINDOW_SECONDS = 365 * DAY_SECONDS;
    const FOCUS_EDGE_PRELOAD_BARS = 18;
    const FOCUS_HISTORY_PREFETCH_DEBOUNCE_MS = 180;
    const FOCUS_PREFETCH_ROUNDS = 3;
    const SIGNAL_SLOT_BINDINGS_KEY = "SIGNAL_SLOT_BINDINGS_V1";
    const QUANT_FACTOR_UI_STORAGE_KEY = "quant_factor_ui_v1";
    const FACTOR_FETCH_LIMIT_INITIAL = 1200;
    const SIGNAL_TYPE_TOGGLE_SPECS = Object.freeze([
        { key: "fundamental_sell", label: "基本面卖点" },
        { key: "weak_sell", label: "弱卖" },
        { key: "fundamental_buy", label: "基本面买点" },
        { key: "weak_buy", label: "弱买" },
        { key: "strong_buy", label: "强买" },
    ]);
    const SIGNAL_SLOT_SERIES_COLORS = Object.freeze({
        strong_buy: "#ef5350",
        weak_buy: "#f59e0b",
        fundamental_buy: "#ec4899",
        weak_sell: "#4ade80",
        fundamental_sell: "#60a5fa",
    });

    const grid = document.getElementById("live-grid");
    const focusOverlay = document.getElementById("live-focus-overlay");
    const focusTitle = document.getElementById("live-focus-title");
    const focusSubtitle = document.getElementById("live-focus-subtitle");
    const focusChartHost = document.getElementById("live-focus-chart");
    const focusState = document.getElementById("live-focus-state");
    const focusSignalChartHost = document.getElementById("live-focus-signal-chart");
    const focusSignalState = document.getElementById("live-focus-signal-state");
    const tradePanel = document.getElementById("live-trade-panel");
    const tradeTicket = document.getElementById("live-trade-ticket");
    const tradePositionText = document.getElementById("live-trade-position");
    const tradePriceText = document.getElementById("live-trade-price");
    const tradeTicketSide = document.getElementById("live-trade-ticket-side");
    const tradeTicketSymbol = document.getElementById("live-trade-ticket-symbol");
    const tradeTicketClose = document.getElementById("live-trade-ticket-close");
    const tradePositionInput = document.getElementById("live-trade-position-input");
    const tradeCashText = document.getElementById("live-trade-cash");
    const tradeAmountText = document.getElementById("live-trade-amount");
    const tradeSharesText = document.getElementById("live-trade-shares");
    const tradeSubmit = document.getElementById("live-trade-submit");
    const chartRegistry = new Map();
    let focusChart = null;
    let focusSeries = null;
    let focusSignalChart = null;
    let focusSignalAnchorSeries = null;
    const focusSignalSeriesMap = new Map();
    const focusSignalPointsCache = new Map();
    const focusSignalLastTimeMap = new Map();
    let focusActiveSymbol = "";
    let focusTimeScaleSyncLock = false;
    let focusBarsCache = [];
    let focusHistoryExhausted = false;
    let focusIsLoadingHistory = false;
    let focusHistoryPrefetchDebounceTimer = null;
    let focusLastVisibleLogicalSnapshot = null;
    let focusSignalRefreshToken = 0;
    let tradeDraft = {
        side: "buy",
        symbol: "",
        name: "",
        positionPct: 0,
        price: 0,
        cash: 200000,
    };

    if (typeof window.initEdgeFloatHud === "function" && !window.__liveBoardEdgeFloatInit) {
        window.__liveBoardEdgeFloatInit = true;
        window.initEdgeFloatHud({ pageId: "live", onNavigate: window.edgeFloatNavigateToPage });
    }

    const stockPool = [
        ["000001.SZ", "平安银行"],
        ["000333.SZ", "美的集团"],
        ["000651.SZ", "格力电器"],
        ["000858.SZ", "五粮液"],
        ["002415.SZ", "海康威视"],
        ["002475.SZ", "立讯精密"],
        ["002594.SZ", "比亚迪"],
        ["300059.SZ", "东方财富"],
        ["300124.SZ", "汇川技术"],
        ["300308.SZ", "中际旭创"],
        ["300750.SZ", "宁德时代"],
        ["600036.SH", "招商银行"],
        ["600276.SH", "恒瑞医药"],
        ["600309.SH", "万华化学"],
        ["600519.SH", "贵州茅台"],
    ];

    function formatPercent(value) {
        return `${Number(value || 0).toFixed(1)}%`;
    }

    function formatMoney(value) {
        const n = Number(value || 0);
        if (!Number.isFinite(n)) {
            return "--";
        }
        return n.toLocaleString("zh-CN", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    function formatShares(value) {
        const n = Math.max(0, Math.floor(Number(value || 0) / 100) * 100);
        return `${n.toLocaleString("zh-CN")} 股`;
    }

    function positionForIndex(index) {
        return 8 + (index % 6) * 4 + (index % 3) * 1.5;
    }

    function buildCard([symbol, name], index) {
        const card = document.createElement("article");
        const positionPct = positionForIndex(index);
        card.className = "live-card";
        card.dataset.symbol = symbol;
        card.dataset.name = name;
        card.dataset.position = positionPct.toFixed(1);
        card.innerHTML = `
            <div class="live-card-body">
                <div class="live-mini-chart">
                    <div class="live-chart-meta">
                        <div class="live-card-name">${name}</div>
                        <div class="live-position-chip">${formatPercent(positionPct)}</div>
                    </div>
                    <div class="live-chart-surface" data-role="chart"></div>
                    <div class="live-chart-state" data-role="state">加载中...</div>
                </div>
            </div>
        `;
        return card;
    }

    function setCardState(card, text, kind) {
        const stateEl = card.querySelector('[data-role="state"]');
        if (!stateEl) {
            return;
        }
        stateEl.textContent = text || "";
        stateEl.dataset.kind = kind || "";
        stateEl.hidden = !text;
    }

    function createChartForCard(card) {
        const host = card.querySelector('[data-role="chart"]');
        if (!host || !window.LightweightCharts) {
            return null;
        }
        const chart = window.LightweightCharts.createChart(host, buildChartOptions({
            fontSize: 11,
            timeVisible: false,
            rightOffset: 2,
            barSpacing: 7,
            interactive: false,
        }));
        const series = chart.addSeries(window.LightweightCharts.CandlestickSeries, buildCandleSeriesOptions());
        return { chart, series };
    }

    function buildChartOptions({ fontSize, timeVisible, rightOffset, barSpacing, interactive }) {
        return {
            autoSize: true,
            layout: {
                background: { color: "rgba(0,0,0,0)" },
                textColor: "rgba(224, 231, 255, 0.88)",
                fontSize,
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: "rgba(255,255,255,0.05)" },
                horzLines: { color: "rgba(255,255,255,0.06)" },
            },
            crosshair: {
                mode: window.LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    color: "rgba(140, 164, 193, 0.32)",
                    width: 1,
                    style: window.LightweightCharts.LineStyle.Dashed,
                    labelBackgroundColor: "rgba(23, 30, 43, 0.96)",
                },
                horzLine: {
                    color: "rgba(140, 164, 193, 0.24)",
                    width: 1,
                    style: window.LightweightCharts.LineStyle.Dashed,
                    labelBackgroundColor: "rgba(23, 30, 43, 0.96)",
                },
            },
            rightPriceScale: {
                visible: true,
                borderVisible: false,
                scaleMargins: { top: 0.12, bottom: 0.12 },
            },
            leftPriceScale: { visible: false },
            timeScale: {
                borderVisible: false,
                timeVisible,
                secondsVisible: false,
                rightOffset,
                barSpacing,
                fixLeftEdge: !interactive,
                fixRightEdge: !interactive,
            },
            handleScroll: {
                mouseWheel: Boolean(interactive),
                pressedMouseMove: Boolean(interactive),
                horzTouchDrag: Boolean(interactive),
                vertTouchDrag: false,
            },
            handleScale: {
                axisPressedMouseMove: false,
                mouseWheel: Boolean(interactive),
                pinch: Boolean(interactive),
            },
        };
    }

    function buildCandleSeriesOptions() {
        return {
            upColor: "#ff5b5b",
            downColor: "#20c997",
            borderUpColor: "#ff5b5b",
            borderDownColor: "#20c997",
            wickUpColor: "#ff8d8d",
            wickDownColor: "#67e6d1",
            priceLineVisible: false,
            lastValueVisible: false,
        };
    }

    function buildSignalChartOptions() {
        return {
            autoSize: true,
            layout: {
                background: { color: "rgba(0,0,0,0)" },
                textColor: "rgba(224, 231, 255, 0.88)",
                fontSize: 11,
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: "rgba(255,255,255,0.05)" },
                horzLines: { color: "rgba(255,255,255,0.06)" },
            },
            rightPriceScale: {
                autoScale: true,
                visible: true,
                borderVisible: false,
                scaleMargins: { top: 0.12, bottom: 0.08 },
            },
            leftPriceScale: { visible: false },
            timeScale: {
                borderVisible: false,
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 6,
                barSpacing: 10,
                fixLeftEdge: true,
                fixRightEdge: true,
            },
            handleScroll: {
                mouseWheel: false,
                pressedMouseMove: false,
                horzTouchDrag: false,
                vertTouchDrag: false,
            },
            handleScale: {
                axisPressedMouseMove: false,
                mouseWheel: false,
                pinch: false,
            },
        };
    }

    function buildSignalSeriesOptions(color, primary) {
        return {
            priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
            priceScaleId: "right",
            color,
            lineWidth: 2,
            crosshairMarkerVisible: Boolean(primary),
            crosshairMarkerRadius: 3,
        };
    }

    function ensureFocusChart() {
        if (!focusChartHost || !window.LightweightCharts) {
            return null;
        }
        if (focusChart && focusSeries) {
            return { chart: focusChart, series: focusSeries };
        }
        focusChart = window.LightweightCharts.createChart(focusChartHost, buildChartOptions({
            fontSize: 12,
            timeVisible: true,
            rightOffset: 6,
            barSpacing: 10,
            interactive: true,
        }));
        focusSeries = focusChart.addSeries(window.LightweightCharts.CandlestickSeries, buildCandleSeriesOptions());
        bindFocusTimeScaleSync();
        return { chart: focusChart, series: focusSeries };
    }

    function ensureFocusSignalChart() {
        if (!focusSignalChartHost || !window.LightweightCharts) {
            return null;
        }
        if (focusSignalChart) {
            return focusSignalChart;
        }
        focusSignalChart = window.LightweightCharts.createChart(focusSignalChartHost, buildSignalChartOptions());
        focusSignalAnchorSeries = focusSignalChart.addSeries(window.LightweightCharts.LineSeries, {
            color: "rgba(0,0,0,0)",
            lineWidth: 1,
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
        });
        bindFocusTimeScaleSync();
        return focusSignalChart;
    }

    function syncFocusSignalViewportFromMain() {
        if (!focusChart || !focusSignalChart) {
            return;
        }
        const logicalRange = focusChart.timeScale().getVisibleLogicalRange();
        if (!logicalRange) {
            return;
        }
        focusTimeScaleSyncLock = true;
        try {
            focusSignalChart.timeScale().setVisibleLogicalRange(logicalRange);
        } catch (_) {
            try {
                focusSignalChart.timeScale().fitContent();
            } catch (__) {
                /* ignore */
            }
        } finally {
            focusTimeScaleSyncLock = false;
        }
    }

    function bindFocusTimeScaleSync() {
        if (!focusChart || !focusSignalChart) {
            return;
        }
        if (focusChart.__liveFocusTimeScaleBound) {
            return;
        }
        focusChart.__liveFocusTimeScaleBound = true;
        focusChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
            if (focusTimeScaleSyncLock) {
                return;
            }
            syncFocusSignalViewportFromMain();
            void handleFocusViewportChange(range);
        });
    }

    function normalizeBars(rawBars) {
        return rawBars.map((item) => ({
            time: Number(item.time),
            open: Number(item.open),
            high: Number(item.high),
            low: Number(item.low),
            close: Number(item.close),
            volume: Number(item.volume || 0),
        })).filter((item) => (
            Number.isFinite(item.time) &&
            Number.isFinite(item.open) &&
            Number.isFinite(item.high) &&
            Number.isFinite(item.low) &&
            Number.isFinite(item.close)
        ));
    }

    async function fetchBars(symbol, options = {}) {
        const params = new URLSearchParams();
        params.set("code", symbol);
        params.set("interval", DAILY_INTERVAL);
        params.set("limit", String(options.limit || 160));
        params.set("adjust", DEFAULT_ADJUST);
        const nowTs = Math.floor(Date.now() / 1000);
        const fromTs = Number.isFinite(options.from)
            ? Math.floor(options.from)
            : nowTs - LOOKBACK_DAYS * DAY_SECONDS;
        params.set("from", String(fromTs));
        if (Number.isFinite(options.to)) {
            params.set("to", String(Math.floor(options.to)));
        }
        const resp = await fetch(`${API_BASE_URL}/api/market/bars?${params.toString()}`, {
            method: "GET",
            cache: "no-store",
        });
        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }
        const payload = await resp.json();
        if (payload && payload.error) {
            throw new Error(payload.error.message || "API error");
        }
        const bars = Array.isArray(payload && payload.bars) ? payload.bars : [];
        return normalizeBars(bars);
    }

    async function fetchFactorSignals(code, factor, fromTs, toTs, limitValue = FACTOR_FETCH_LIMIT_INITIAL) {
        const params = new URLSearchParams({
            code,
            interval: DAILY_INTERVAL,
            factor,
            from: String(fromTs),
            to: String(toTs),
            limit: String(limitValue),
        });
        const resp = await fetch(`${API_BASE_URL}/api/market/signal?${params.toString()}`, {
            method: "GET",
            cache: "no-store",
        });
        const body = await resp.json();
        if (!resp.ok) {
            if (resp.status === 404 && body && body.error && String(body.error.message || "").includes("未找到")) {
                return { signals: [], meta: { has_new_data: false, row_count: 0, no_factor: true } };
            }
            const message = body && body.error && body.error.message ? body.error.message : "因子数据获取失败";
            throw new Error(message);
        }
        return body;
    }

    function buildSignalSeriesData(points) {
        return (Array.isArray(points) ? points : [])
            .map((item) => ({
                time: Number(item.time),
                value: Number(item.value),
            }))
            .filter((item) => Number.isFinite(item.time) && Number.isFinite(item.value));
    }

    function readSignalSlotBindings() {
        const defaults = Object.fromEntries(SIGNAL_TYPE_TOGGLE_SPECS.map((item) => [item.key, ""]));
        try {
            const raw = JSON.parse(localStorage.getItem(SIGNAL_SLOT_BINDINGS_KEY) || "{}");
            if (!raw || typeof raw !== "object") {
                return defaults;
            }
            const next = { ...defaults };
            for (const spec of SIGNAL_TYPE_TOGGLE_SPECS) {
                const value = String(raw[spec.key] || "").trim();
                if (value) {
                    next[spec.key] = value;
                }
            }
            return next;
        } catch (_) {
            return defaults;
        }
    }

    function readSignalTypeToggleState() {
        const defaults = Object.fromEntries(SIGNAL_TYPE_TOGGLE_SPECS.map((item) => [item.key, true]));
        try {
            const raw = localStorage.getItem(QUANT_FACTOR_UI_STORAGE_KEY);
            if (!raw) {
                return defaults;
            }
            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed !== "object" || !parsed.signalTypeToggleState || typeof parsed.signalTypeToggleState !== "object") {
                return defaults;
            }
            const next = { ...defaults };
            for (const spec of SIGNAL_TYPE_TOGGLE_SPECS) {
                const key = spec.key;
                if (key in parsed.signalTypeToggleState) {
                    next[key] = Boolean(parsed.signalTypeToggleState[key]);
                }
            }
            return next;
        } catch (_) {
            return defaults;
        }
    }

    function getVisibleSignalSlotsForFocus() {
        const bindings = readSignalSlotBindings();
        const toggles = readSignalTypeToggleState();
        return SIGNAL_TYPE_TOGGLE_SPECS
            .filter((spec) => Boolean(toggles[spec.key]) && String(bindings[spec.key] || "").trim())
            .map((spec) => ({
                key: spec.key,
                factor: String(bindings[spec.key] || "").trim(),
                color: SIGNAL_SLOT_SERIES_COLORS[spec.key] || "#3b82f6",
            }));
    }

    function applyBarsToCard(card, bars) {
        const reg = chartRegistry.get(card.dataset.symbol || "");
        if (!reg) {
            return;
        }
        reg.series.setData(bars);
        reg.chart.timeScale().fitContent();
    }

    function setFocusState(text, kind) {
        if (!focusState) {
            return;
        }
        focusState.textContent = text || "";
        focusState.dataset.kind = kind || "";
        focusState.hidden = !text;
    }

    function setFocusSignalState(text, kind) {
        if (!focusSignalState) {
            return;
        }
        if (kind === "loading") {
            focusSignalState.textContent = "";
            focusSignalState.dataset.kind = "";
            focusSignalState.hidden = true;
            return;
        }
        focusSignalState.textContent = text || "";
        focusSignalState.dataset.kind = kind || "";
        focusSignalState.hidden = !text;
    }

    function getTradeInputPct() {
        const raw = tradePositionInput ? Number(tradePositionInput.value) : 0;
        if (!Number.isFinite(raw)) {
            return 0;
        }
        return Math.max(0, Math.min(100, raw));
    }

    function setTradeTicketOpen(isOpen) {
        if (!tradeTicket) {
            return;
        }
        tradeTicket.classList.toggle("is-open", Boolean(isOpen));
        tradeTicket.setAttribute("aria-hidden", isOpen ? "false" : "true");
    }

    function updateTradeSummary() {
        if (tradePositionText) {
            tradePositionText.textContent = `仓位 ${formatPercent(tradeDraft.positionPct)}`;
        }
        if (tradePriceText) {
            tradePriceText.textContent = tradeDraft.price > 0 ? `参考价 ${tradeDraft.price.toFixed(2)}` : "参考价 --";
        }
    }

    function updateTradeTicket() {
        const pct = getTradeInputPct();
        const price = Math.max(0, Number(tradeDraft.price || 0));
        const baseCash = Math.max(0, Number(tradeDraft.cash || 0));
        const amount = baseCash * pct / 100;
        const shares = price > 0 ? amount / price : 0;
        const isBuy = tradeDraft.side === "buy";
        if (tradeTicket) {
            tradeTicket.classList.toggle("is-buy", isBuy);
            tradeTicket.classList.toggle("is-sell", !isBuy);
        }
        if (tradeTicketSide) {
            tradeTicketSide.textContent = isBuy ? "买入" : "卖出";
        }
        if (tradeTicketSymbol) {
            tradeTicketSymbol.textContent = `${tradeDraft.name || "--"} ${tradeDraft.symbol || ""}`.trim();
        }
        if (tradeCashText) {
            tradeCashText.textContent = `${formatMoney(baseCash)} 元`;
        }
        if (tradeAmountText) {
            tradeAmountText.textContent = `${formatMoney(amount)} 元`;
        }
        if (tradeSharesText) {
            tradeSharesText.textContent = formatShares(shares);
        }
        if (tradeSubmit) {
            tradeSubmit.textContent = isBuy ? "模拟买入" : "模拟卖出";
        }
        document.querySelectorAll("[data-trade-preset]").forEach((button) => {
            button.classList.toggle("is-active", Number(button.dataset.tradePreset) === pct);
        });
    }

    function openTradeTicket(side) {
        tradeDraft.side = side === "sell" ? "sell" : "buy";
        if (tradePositionInput && !tradePositionInput.value) {
            tradePositionInput.value = "25";
        }
        updateTradeTicket();
        setTradeTicketOpen(true);
    }

    function resetTradeDraftForFocus(card, bars) {
        const lastBar = Array.isArray(bars) && bars.length ? bars[bars.length - 1] : null;
        tradeDraft = {
            side: tradeDraft.side || "buy",
            symbol: card ? card.dataset.symbol || "" : "",
            name: card ? card.dataset.name || "" : "",
            positionPct: card ? Number(card.dataset.position || 0) : 0,
            price: lastBar ? Number(lastBar.close || 0) : 0,
            cash: 200000,
        };
        updateTradeSummary();
        updateTradeTicket();
    }

    function clearFocusSignalSeries() {
        if (!focusSignalChart) {
            focusSignalSeriesMap.clear();
            return;
        }
        for (const series of focusSignalSeriesMap.values()) {
            try {
                focusSignalChart.removeSeries(series);
            } catch (_) {
                /* ignore */
            }
        }
        focusSignalSeriesMap.clear();
    }

    function resetFocusSignalCaches() {
        focusSignalPointsCache.clear();
        focusSignalLastTimeMap.clear();
    }

    function mergeSignalPoints(existingPoints, incomingPoints) {
        const byTime = new Map();
        (Array.isArray(existingPoints) ? existingPoints : []).forEach((point) => {
            byTime.set(Number(point.time), point);
        });
        (Array.isArray(incomingPoints) ? incomingPoints : []).forEach((point) => {
            byTime.set(Number(point.time), point);
        });
        return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
    }

    function pruneSignalPointsToBarRange(points, bars) {
        if (!Array.isArray(points) || !points.length || !Array.isArray(bars) || !bars.length) {
            return [];
        }
        const minTime = Number(bars[0].time);
        const maxTime = Number(bars[bars.length - 1].time);
        return points.filter((point) => Number(point.time) >= minTime && Number(point.time) <= maxTime);
    }

    function ensureFocusSignalSeries(slotKey, color, primary) {
        if (!focusSignalChart) {
            return null;
        }
        let series = focusSignalSeriesMap.get(slotKey);
        if (!series) {
            series = focusSignalChart.addSeries(
                window.LightweightCharts.LineSeries,
                buildSignalSeriesOptions(color, primary)
            );
            focusSignalSeriesMap.set(slotKey, series);
        } else {
            series.applyOptions(buildSignalSeriesOptions(color, primary));
        }
        return series;
    }

    function mergeBarsByTime(existingBars, incomingBars) {
        const byTime = new Map();
        (Array.isArray(existingBars) ? existingBars : []).forEach((bar) => {
            byTime.set(Number(bar.time), bar);
        });
        (Array.isArray(incomingBars) ? incomingBars : []).forEach((bar) => {
            byTime.set(Number(bar.time), bar);
        });
        return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
    }

    function resetFocusBarsState() {
        focusBarsCache = [];
        focusHistoryExhausted = false;
        focusIsLoadingHistory = false;
        focusLastVisibleLogicalSnapshot = null;
        focusSignalRefreshToken += 1;
        resetFocusSignalCaches();
        if (focusHistoryPrefetchDebounceTimer) {
            clearTimeout(focusHistoryPrefetchDebounceTimer);
            focusHistoryPrefetchDebounceTimer = null;
        }
    }

    function setFocusBarsData(nextBars) {
        focusBarsCache = Array.isArray(nextBars) ? nextBars.slice() : [];
        if (focusSeries) {
            focusSeries.setData(focusBarsCache);
        }
        if (focusSignalAnchorSeries) {
            focusSignalAnchorSeries.setData(
                focusBarsCache.map((bar) => ({
                    time: Number(bar.time),
                    value: 0,
                }))
            );
        }
    }

    function clampFocusLogicalRange(range) {
        if (!range || !focusBarsCache.length) {
            return null;
        }
        const barCount = focusBarsCache.length;
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

    function setFocusChartVisibleLogicalRange(range) {
        if (!focusChart) {
            return;
        }
        const clamped = clampFocusLogicalRange(range);
        if (!clamped) {
            return;
        }
        focusChart.timeScale().setVisibleLogicalRange(clamped);
        syncFocusSignalViewportFromMain();
    }

    function focusLogicalRangeDiffers(a, b) {
        if (!a || !b) {
            return false;
        }
        return Math.abs(Number(a.from) - Number(b.from)) > 0.01
            || Math.abs(Number(a.to) - Number(b.to)) > 0.01;
    }

    function captureFocusVisibleLogicalSnapshot(rangeOverride) {
        const range = rangeOverride || (focusChart ? focusChart.timeScale().getVisibleLogicalRange() : null);
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

    function isFocusZoomingOut(previousSnapshot, currentSnapshot) {
        if (!previousSnapshot || !currentSnapshot) {
            return false;
        }
        return (currentSnapshot.to - currentSnapshot.from) > (previousSnapshot.to - previousSnapshot.from) + 0.1;
    }

    function isFocusPanningLeft(previousSnapshot, currentSnapshot) {
        if (!previousSnapshot || !currentSnapshot) {
            return false;
        }
        return currentSnapshot.from < previousSnapshot.from - 0.1;
    }

    async function loadOlderFocusBarsIfNeeded(options = {}) {
        if (!focusActiveSymbol || !focusChart || !focusBarsCache.length || focusHistoryExhausted || focusIsLoadingHistory) {
            return false;
        }
        const logicalRange = focusChart.timeScale().getVisibleLogicalRange();
        if (!options.ignoreVisibleEdge) {
            if (!logicalRange || logicalRange.from > FOCUS_EDGE_PRELOAD_BARS) {
                return false;
            }
        }
        const oldestTime = Number(focusBarsCache[0] && focusBarsCache[0].time);
        if (!Number.isFinite(oldestTime)) {
            return false;
        }
        focusIsLoadingHistory = true;
        const previousRange = captureFocusVisibleLogicalSnapshot(logicalRange);
        const previousLength = focusBarsCache.length;
        try {
            const olderBars = await fetchBars(focusActiveSymbol, {
                from: Math.max(0, oldestTime - FOCUS_HISTORY_WINDOW_SECONDS),
                to: oldestTime - DAY_SECONDS,
                limit: FOCUS_FETCH_LIMIT,
            });
            if (!focusActiveSymbol) {
                return false;
            }
            if (!olderBars.length) {
                focusHistoryExhausted = true;
                return false;
            }
            const mergedBars = mergeBarsByTime(olderBars, focusBarsCache);
            if (mergedBars.length === previousLength) {
                focusHistoryExhausted = true;
                return false;
            }
            setFocusBarsData(mergedBars);
            const addedCount = mergedBars.length - previousLength;
            if (previousRange && addedCount > 0) {
                setFocusChartVisibleLogicalRange({
                    from: previousRange.from + addedCount,
                    to: previousRange.to + addedCount,
                });
            } else {
                syncFocusSignalViewportFromMain();
            }
            await refreshFocusSignalData(focusActiveSymbol, focusBarsCache);
            return true;
        } finally {
            focusIsLoadingHistory = false;
        }
    }

    function scheduleFocusHistoryPrefetch() {
        if (focusHistoryExhausted || focusIsLoadingHistory || !focusBarsCache.length) {
            return;
        }
        if (focusHistoryPrefetchDebounceTimer) {
            clearTimeout(focusHistoryPrefetchDebounceTimer);
        }
        focusHistoryPrefetchDebounceTimer = setTimeout(() => {
            focusHistoryPrefetchDebounceTimer = null;
            void prefetchOlderFocusBarsFromViewGesture(FOCUS_PREFETCH_ROUNDS);
        }, FOCUS_HISTORY_PREFETCH_DEBOUNCE_MS);
    }

    async function prefetchOlderFocusBarsFromViewGesture(maxRounds = FOCUS_PREFETCH_ROUNDS) {
        for (let round = 0; round < maxRounds; round += 1) {
            if (focusHistoryExhausted || focusIsLoadingHistory || !focusBarsCache.length) {
                break;
            }
            const countBefore = focusBarsCache.length;
            const changed = await loadOlderFocusBarsIfNeeded();
            if (!changed || focusBarsCache.length === countBefore) {
                break;
            }
        }
    }

    async function prefetchOlderFocusBarsForInitialDisplay(maxRounds = FOCUS_PREFETCH_ROUNDS) {
        for (let round = 0; round < maxRounds; round += 1) {
            if (focusHistoryExhausted || focusIsLoadingHistory || !focusBarsCache.length) {
                break;
            }
            const countBefore = focusBarsCache.length;
            const changed = await loadOlderFocusBarsIfNeeded({ ignoreVisibleEdge: true });
            if (!changed || focusBarsCache.length === countBefore) {
                break;
            }
        }
    }

    function scheduleFocusHistoryPrefetchAfterViewSettle() {
        requestAnimationFrame(() => {
            void prefetchOlderFocusBarsForInitialDisplay();
        });
    }

    async function handleFocusViewportChange(range) {
        if (!focusChart || !focusBarsCache.length) {
            return;
        }
        const currentSnapshot = captureFocusVisibleLogicalSnapshot(range);
        const clampedSnapshot = clampFocusLogicalRange(currentSnapshot);
        if (currentSnapshot && clampedSnapshot && focusLogicalRangeDiffers(currentSnapshot, clampedSnapshot)) {
            setFocusChartVisibleLogicalRange(clampedSnapshot);
            focusLastVisibleLogicalSnapshot = clampedSnapshot;
            return;
        }
        const previousSnapshot = focusLastVisibleLogicalSnapshot;
        if (currentSnapshot) {
            focusLastVisibleLogicalSnapshot = currentSnapshot;
        }
        void loadOlderFocusBarsIfNeeded();
        if (isFocusPanningLeft(previousSnapshot, currentSnapshot) || isFocusZoomingOut(previousSnapshot, currentSnapshot)) {
            scheduleFocusHistoryPrefetch();
        }
    }

    async function refreshFocusSignalData(symbol, bars) {
        const signalChart = ensureFocusSignalChart();
        if (!signalChart) {
            return;
        }
        const refreshToken = ++focusSignalRefreshToken;
        const visibleSlots = getVisibleSignalSlotsForFocus();
        if (!visibleSlots.length || !Array.isArray(bars) || !bars.length) {
            clearFocusSignalSeries();
            resetFocusSignalCaches();
            setFocusSignalState("未选择副图因子", "empty");
            return;
        }
        const fromTs = Number(bars[0].time);
        const toTs = Number(bars[bars.length - 1].time);
        const signalLimit = Math.max(FACTOR_FETCH_LIMIT_INITIAL, Array.isArray(bars) ? bars.length + 240 : FACTOR_FETCH_LIMIT_INITIAL);
        setFocusSignalState("副图加载中...", "loading");
        const results = await Promise.all(visibleSlots.map(async (slot) => {
            try {
                const cacheKey = slot.key;
                const existingPoints = focusSignalPointsCache.get(cacheKey) || [];
                const cachedMinTime = existingPoints.length ? Number(existingPoints[0].time) : null;
                const cachedMaxTime = existingPoints.length ? Number(existingPoints[existingPoints.length - 1].time) : null;
                const hasLeftCoverage = Number.isFinite(cachedMinTime) && Number(cachedMinTime) <= fromTs;
                const hasRightCoverage = Number.isFinite(cachedMaxTime) && Number(cachedMaxTime) >= toTs;
                if (existingPoints.length && hasLeftCoverage && hasRightCoverage) {
                    return {
                        slot,
                        points: pruneSignalPointsToBarRange(existingPoints, bars),
                        clear: false,
                    };
                }
                const requestFromTs = (existingPoints.length && hasLeftCoverage && Number.isFinite(cachedMaxTime))
                    ? Math.max(fromTs, Number(cachedMaxTime))
                    : fromTs;
                const payload = await fetchFactorSignals(symbol, slot.factor, requestFromTs, toTs, signalLimit);
                const isNoFactor = Boolean(payload && payload.meta && payload.meta.no_factor === true);
                if (isNoFactor) {
                    return { slot, points: [], clear: true };
                }
                const incomingPoints = buildSignalSeriesData(Array.isArray(payload.signals) ? payload.signals : []);
                const mergedPoints = pruneSignalPointsToBarRange(
                    mergeSignalPoints(existingPoints, incomingPoints),
                    bars
                );
                return {
                    slot,
                    points: mergedPoints,
                    clear: false,
                };
            } catch (error) {
                console.warn("[live-board] focus signal load failed:", symbol, slot.factor, error);
                return {
                    slot,
                    points: pruneSignalPointsToBarRange(focusSignalPointsCache.get(slot.key) || [], bars),
                    clear: false,
                };
            }
        }));
        if (refreshToken !== focusSignalRefreshToken || focusActiveSymbol !== symbol) {
            return;
        }
        const visibleKeys = new Set(visibleSlots.map((slot) => slot.key));
        for (const key of Array.from(focusSignalSeriesMap.keys())) {
            if (!visibleKeys.has(key)) {
                const series = focusSignalSeriesMap.get(key);
                if (series && focusSignalChart) {
                    try {
                        focusSignalChart.removeSeries(series);
                    } catch (_) {
                        /* ignore */
                    }
                }
                focusSignalSeriesMap.delete(key);
                focusSignalPointsCache.delete(key);
                focusSignalLastTimeMap.delete(key);
            }
        }
        let hasAnyPoints = false;
        results.forEach((item, index) => {
            if (item.clear) {
                const existingSeries = focusSignalSeriesMap.get(item.slot.key);
                if (existingSeries) {
                    existingSeries.setData([]);
                }
                focusSignalPointsCache.delete(item.slot.key);
                focusSignalLastTimeMap.delete(item.slot.key);
                return;
            }
            const normalizedPoints = Array.isArray(item.points) ? item.points : [];
            const series = ensureFocusSignalSeries(item.slot.key, item.slot.color, index === 0);
            if (!series) {
                return;
            }
            series.setData(normalizedPoints);
            focusSignalPointsCache.set(item.slot.key, normalizedPoints);
            focusSignalLastTimeMap.set(
                item.slot.key,
                normalizedPoints.length ? Number(normalizedPoints[normalizedPoints.length - 1].time) : null
            );
            if (normalizedPoints.length > 0) {
                hasAnyPoints = true;
            }
        });
        if (!hasAnyPoints) {
            setFocusSignalState("副图暂无数据", "empty");
            return;
        }
        syncFocusSignalViewportFromMain();
        setFocusSignalState("", "");
    }

    async function openFocusDialog(card) {
        if (!card || !focusOverlay) {
            return;
        }
        const symbol = card.dataset.symbol || "";
        const name = card.dataset.name || symbol;
        resetFocusBarsState();
        focusActiveSymbol = symbol;
        if (focusTitle) {
            focusTitle.textContent = name;
        }
        if (focusSubtitle) {
            focusSubtitle.textContent = symbol;
        }
        focusOverlay.classList.add("is-open");
        focusOverlay.setAttribute("aria-hidden", "false");
        const reg = ensureFocusChart();
        if (!reg) {
            return;
        }
        setFocusState("加载中...", "loading");
        try {
            const nowTs = Math.floor(Date.now() / 1000);
            const bars = await fetchBars(symbol, {
                from: nowTs - FOCUS_INITIAL_LOOKBACK_DAYS * DAY_SECONDS,
                to: nowTs,
                limit: FOCUS_FETCH_LIMIT,
            });
            if (focusActiveSymbol !== symbol) {
                return;
            }
            if (!bars.length) {
                resetTradeDraftForFocus(card, []);
                setFocusBarsData([]);
                setFocusState("暂无日K", "empty");
                setFocusSignalState("副图暂无数据", "empty");
                return;
            }
            resetTradeDraftForFocus(card, bars);
            setFocusBarsData(bars);
            reg.chart.timeScale().fitContent();
            focusLastVisibleLogicalSnapshot = captureFocusVisibleLogicalSnapshot();
            if (focusLastVisibleLogicalSnapshot) {
                setFocusChartVisibleLogicalRange(focusLastVisibleLogicalSnapshot);
                focusLastVisibleLogicalSnapshot = captureFocusVisibleLogicalSnapshot();
            }
            setFocusState("", "");
            await refreshFocusSignalData(symbol, bars);
            window.requestAnimationFrame(() => {
                try {
                    reg.chart.resize(0, 0);
                    syncFocusSignalViewportFromMain();
                    scheduleFocusHistoryPrefetchAfterViewSettle();
                } catch (_) {
                    /* ignore */
                }
            });
        } catch (error) {
            console.warn("[live-board] focus load failed:", symbol, error);
            if (focusActiveSymbol === symbol) {
                setFocusState("加载失败", "error");
            }
        }
    }

    function closeFocusDialog() {
        focusActiveSymbol = "";
        resetFocusBarsState();
        if (focusChart) {
            try {
                focusChart.remove();
            } catch (_) {
                /* ignore */
            }
        }
        focusChart = null;
        focusSeries = null;
        if (focusSignalChart) {
            try {
                clearFocusSignalSeries();
                focusSignalChart.remove();
            } catch (_) {
                /* ignore */
            }
        }
        focusSignalChart = null;
        focusSignalAnchorSeries = null;
        if (focusChartHost) {
            focusChartHost.innerHTML = "";
        }
        if (focusSignalChartHost) {
            focusSignalChartHost.innerHTML = "";
        }
        setFocusState("加载中...", "loading");
        setFocusSignalState("副图加载中...", "loading");
        setTradeTicketOpen(false);
        resetTradeDraftForFocus(null, []);
        if (focusTitle) {
            focusTitle.textContent = "--";
        }
        if (focusSubtitle) {
            focusSubtitle.textContent = "--";
        }
        if (!focusOverlay) {
            return;
        }
        focusOverlay.classList.remove("is-open");
        focusOverlay.setAttribute("aria-hidden", "true");
    }

    async function loadCardData(card) {
        const symbol = card.dataset.symbol || "";
        setCardState(card, "加载中...", "loading");
        try {
            const bars = await fetchBars(symbol);
            if (!bars.length) {
                setCardState(card, "暂无日K", "empty");
                return;
            }
            applyBarsToCard(card, bars);
            setCardState(card, "", "");
        } catch (error) {
            console.warn("[live-board] load bars failed:", symbol, error);
            setCardState(card, "加载失败", "error");
        }
    }

    async function refreshGridData() {
        const cards = Array.from(document.querySelectorAll(".live-card"));
        await Promise.all(cards.map((card) => loadCardData(card)));
    }

    async function refreshFocusData() {
        if (!focusActiveSymbol || !focusChart || !focusSeries) {
            return;
        }
        setFocusState("加载中...", "loading");
        try {
            const cacheStart = Number(focusBarsCache[0] && focusBarsCache[0].time);
            const nowTs = Math.floor(Date.now() / 1000);
            const priorLength = focusBarsCache.length;
            const bars = await fetchBars(focusActiveSymbol, {
                from: Number.isFinite(cacheStart) ? cacheStart : nowTs - FOCUS_INITIAL_LOOKBACK_DAYS * DAY_SECONDS,
                to: nowTs,
                limit: Math.max(FOCUS_FETCH_LIMIT, priorLength || 0),
            });
            if (!focusActiveSymbol) {
                return;
            }
            if (!bars.length) {
                setFocusBarsData([]);
                setFocusState("暂无日K", "empty");
                setFocusSignalState("副图暂无数据", "empty");
                return;
            }
            const mergedBars = mergeBarsByTime(focusBarsCache, bars);
            setFocusBarsData(mergedBars);
            if (mergedBars.length > priorLength) {
                focusHistoryExhausted = false;
            }
            setFocusState("", "");
            await refreshFocusSignalData(focusActiveSymbol, mergedBars);
            syncFocusSignalViewportFromMain();
        } catch (error) {
            console.warn("[live-board] focus refresh failed:", focusActiveSymbol, error);
            if (focusActiveSymbol) {
                setFocusState("加载失败", "error");
                setFocusSignalState("副图加载失败", "error");
            }
        }
    }

    async function refreshAllData() {
        await refreshGridData();
        await refreshFocusData();
    }

    function renderGrid() {
        if (!grid) {
            return;
        }
        grid.innerHTML = "";
        stockPool.forEach((item, index) => {
            const card = buildCard(item, index);
            grid.appendChild(card);
            const chartParts = createChartForCard(card);
            if (chartParts) {
                chartRegistry.set(item[0], chartParts);
            }
        });
    }

    function resizeCharts() {
        chartRegistry.forEach((entry) => {
            try {
                entry.chart.resize(entry.chart.options().width || 0, entry.chart.options().height || 0);
            } catch (_) {
                try {
                    entry.chart.timeScale().fitContent();
                } catch (__) {
                    /* ignore */
                }
            }
        });
        if (focusChart) {
            try {
                focusChart.resize(0, 0);
                syncFocusSignalViewportFromMain();
            } catch (_) {
                /* ignore */
            }
        }
        if (focusSignalChart) {
            try {
                focusSignalChart.resize(0, 0);
                syncFocusSignalViewportFromMain();
            } catch (_) {
                /* ignore */
            }
        }
    }

    if (grid) {
        grid.addEventListener("dblclick", (event) => {
            const card = event.target.closest(".live-card");
            if (!card) {
                return;
            }
            openFocusDialog(card);
        });
    }

    if (focusOverlay) {
        focusOverlay.addEventListener("click", (event) => {
            if (event.target.classList.contains("live-focus-overlay") || event.target.classList.contains("live-focus-backdrop")) {
                closeFocusDialog();
            }
        });
    }

    if (tradePanel) {
        tradePanel.addEventListener("click", (event) => {
            const button = event.target.closest("[data-trade-side]");
            if (!button) {
                return;
            }
            openTradeTicket(button.dataset.tradeSide);
        });
    }

    if (tradeTicketClose) {
        tradeTicketClose.addEventListener("click", () => {
            setTradeTicketOpen(false);
        });
    }

    if (tradeTicket) {
        tradeTicket.addEventListener("click", (event) => {
            const button = event.target.closest("[data-trade-preset]");
            if (!button || !tradePositionInput) {
                return;
            }
            tradePositionInput.value = button.dataset.tradePreset || "0";
            updateTradeTicket();
        });
    }

    if (tradePositionInput) {
        tradePositionInput.addEventListener("input", updateTradeTicket);
    }

    if (tradeSubmit) {
        tradeSubmit.addEventListener("click", () => {
            updateTradeTicket();
            tradeSubmit.textContent = tradeDraft.side === "buy" ? "已模拟买入" : "已模拟卖出";
            window.setTimeout(updateTradeTicket, 900);
        });
    }

    window.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            if (tradeTicket && tradeTicket.classList.contains("is-open")) {
                setTradeTicketOpen(false);
                return;
            }
            closeFocusDialog();
        }
    });
    window.addEventListener("resize", resizeCharts);

    renderGrid();
    refreshAllData();
    window.setInterval(refreshAllData, AUTO_REFRESH_MS);
})();

