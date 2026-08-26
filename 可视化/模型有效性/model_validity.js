(function () {
    "use strict";

    function resolveApiBase() {
        const query = new URLSearchParams(window.location.search);
        const candidates = [window.STYLE_MONITOR_API_BASE, query.get("api_base"), query.get("api")];
        try {
            candidates.push(localStorage.getItem("RESULTS_API_BASE"));
            candidates.push(localStorage.getItem("API_BASE_URL"));
        } catch (_) {}
        for (const rawValue of candidates) {
            const raw = String(rawValue || "").trim();
            if (!raw) continue;
            try { return new URL(/^https?:\/\//i.test(raw) ? raw : `http://${raw}`).origin; } catch (_) {}
        }
        if (window.location.protocol === "https:") return window.location.origin;
        if (window.location.protocol === "http:") return `http://${window.location.hostname}:8000`;
        return "http://127.0.0.1:8000";
    }
    const API_BASE = resolveApiBase();
    const DEFAULT_ZOOM = 1.25;
    const ZOOM_STEPS = [1, 1.1, DEFAULT_ZOOM, 1.4, 1.5];
    const ZOOM_STORAGE_KEY = "model-validity.zoom";
    const COLORS = { high: "#26a69a", low: "#f59e0b", relative: "#6b9cff", benchmark: "#a78bfa" };
    const SERIES_KEYS = ["high", "low", "relative", "benchmark"];
    const SERIES_TITLES = { high: "高分", low: "低分", relative: "相对", benchmark: "基准" };
    const state = { range: "60d", customStartDate: "", customEndDate: "", benchmarkCode: "000001.SH", benchmarkName: "上证指数", benchmarkSuggestionTimer: null, benchmarkSuggestionItems: [], summary: null, charts: new Map(), selectedModelId: null, detailTab: "positions", detailLeg: "high", visibleRange: null, syncingTimeRange: false };

    function formatPercent(value) {
        return value == null || Number.isNaN(Number(value)) ? "--" : `${(Number(value) * 100).toFixed(2)}%`;
    }

    async function apiFetch(path, options) {
        const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...(options && options.headers) } });
        const payload = await response.json();
        if (!response.ok) {
            const error = new Error(payload.error?.message || `HTTP ${response.status}`);
            error.status = response.status;
            throw error;
        }
        return payload;
    }

    function createChartOptions() {
        return { autoSize: true, layout: { background: { color: "rgba(0,0,0,0)" }, textColor: "rgba(224,231,255,.88)", fontSize: 11, attributionLogo: false }, grid: { vertLines: { color: "rgba(255,255,255,.05)" }, horzLines: { color: "rgba(255,255,255,.06)" } }, rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false, timeVisible: true, fixLeftEdge: false, fixRightEdge: false }, handleScroll: { mouseWheel: true, pressedMouseMove: true }, handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true } };
    }

    function toDateString(value) {
        if (typeof value === "string") return value.slice(0, 10);
        if (typeof value === "number" && Number.isFinite(value)) return new Date(value * 1000).toISOString().slice(0, 10);
        if (value && typeof value === "object" && Number.isFinite(value.year) && Number.isFinite(value.month) && Number.isFinite(value.day)) return `${String(value.year).padStart(4, "0")}-${String(value.month).padStart(2, "0")}-${String(value.day).padStart(2, "0")}`;
        return null;
    }

    function calculateLookbackStart(endDate, days) {
        const end = toDateString(endDate);
        const count = Number(days);
        if (!end || !Number.isInteger(count) || count < 1 || count > 20000) return null;
        const date = new Date(`${end}T00:00:00Z`);
        if (!Number.isFinite(date.getTime())) return null;
        date.setUTCDate(date.getUTCDate() - count + 1);
        return date.toISOString().slice(0, 10);
    }

    function normalizeBenchmarkCode(value) {
        return String(value || "").trim().toUpperCase();
    }

    function isLikelyBenchmarkCode(value) {
        const code = normalizeBenchmarkCode(value);
        return /^\d{6}\.[A-Z]{2,4}$/.test(code) && !code.endsWith(".YKRS");
    }

    async function fetchBenchmarkSuggestions(keyword) {
        const query = normalizeBenchmarkCode(keyword);
        if (!query) return [];
        const params = new URLSearchParams({ q: query, interval: "1day", limit: "5" });
        const payload = await apiFetch(`/api/market/codes/search?${params.toString()}`);
        return (Array.isArray(payload.items) ? payload.items : []).map((item) => ({ code: normalizeBenchmarkCode(item.code), name: String(item.name || "").trim() })).filter((item) => item.code);
    }

    function hideBenchmarkSuggestions() {
        document.getElementById("style-benchmark-suggestions")?.classList.remove("show");
    }

    function renderBenchmarkSuggestions(items) {
        const list = document.getElementById("style-benchmark-suggestions");
        if (!list) return;
        list.textContent = "";
        state.benchmarkSuggestionItems = Array.isArray(items) ? items.slice(0, 5) : [];
        state.benchmarkSuggestionItems.forEach((item) => {
            const li = document.createElement("li");
            li.textContent = item.name ? `${item.name} (${item.code})` : item.code;
            li.dataset.code = item.code;
            li.addEventListener("mousedown", (event) => {
                event.preventDefault();
                const input = document.getElementById("style-benchmark-code");
                if (input) input.value = item.code;
                hideBenchmarkSuggestions();
            });
            list.appendChild(li);
        });
        list.classList.toggle("show", state.benchmarkSuggestionItems.length > 0);
    }

    async function resolveBenchmarkCode() {
        const input = document.getElementById("style-benchmark-code");
        const raw = normalizeBenchmarkCode(input?.value);
        if (!raw) return "";
        const exact = state.benchmarkSuggestionItems.find((item) => item.code === raw);
        if (exact) return exact.code;
        if (isLikelyBenchmarkCode(raw)) return raw;
        try {
            const items = await fetchBenchmarkSuggestions(raw);
            return items[0]?.code || "";
        } catch (_) {
            return "";
        }
    }

    function updateBenchmarkStatus() {
        const status = document.getElementById("style-benchmark-status");
        if (status) status.textContent = state.benchmarkName ? `当前：${state.benchmarkName}（${state.benchmarkCode || "默认"}）` : "";
    }

    async function applyBenchmark() {
        const status = document.getElementById("style-monitor-state");
        const input = document.getElementById("style-benchmark-code");
        const code = await resolveBenchmarkCode();
        if (!code) {
            if (status) status.textContent = "请输入有效的基准代码，例如 600000.SH";
            return;
        }
        state.benchmarkCode = code;
        if (input) input.value = code;
        hideBenchmarkSuggestions();
        state.benchmarkName = code === "000001.SH" ? "上证指数" : code === "399001.SZ" ? "深证成指" : code;
        updateBenchmarkStatus();
        if (state.summary) await renderModelCharts();
    }

    function normalizeSeriesForRange(data, range) {
        const points = Array.isArray(data) ? data : [];
        const from = toDateString(range?.from);
        const to = toDateString(range?.to);
        const inWindow = points.filter((point) => {
            const time = toDateString(point?.time);
            const value = Number(point?.value);
            return time && Number.isFinite(value) && (!from || time >= from) && (!to || time <= to);
        });
        const base = Number(inWindow[0]?.value);
        if (!Number.isFinite(base) || base === 0) return points.map((point) => ({ time: point.time }));
        return points.map((point) => {
            const time = toDateString(point?.time);
            const value = Number(point?.value);
            if (!time || !Number.isFinite(value) || (from && time < from) || (to && time > to)) return { time: point.time };
            return { time: point.time, value: value / base * 100 };
        });
    }

    function normalizePayloadForRange(rawSeries, range) {
        return Object.fromEntries(SERIES_KEYS.map((key) => [key, normalizeSeriesForRange(rawSeries?.[key], range)]));
    }

    function getRawDateBounds() {
        const dates = [];
        state.charts.forEach(({ rawSeries }) => Object.values(rawSeries || {}).forEach((series) => (series || []).forEach((point) => {
            const time = toDateString(point?.time);
            if (time) dates.push(time);
        })));
        if (!dates.length) return null;
        dates.sort();
        return { from: dates[0], to: dates[dates.length - 1] };
    }

    function renderNormalizedSeries(range) {
        if (!range) return;
        state.visibleRange = range;
        state.charts.forEach(({ series, rawSeries }) => {
            const normalized = normalizePayloadForRange(rawSeries, range);
            Object.keys(series).forEach((key) => series[key].setData(normalized[key]));
        });
    }

    function synchronizeVisibleRange(range) {
        if (!range?.from || !range?.to || state.syncingTimeRange) return;
        state.visibleRange = range;
        state.syncingTimeRange = true;
        try {
            state.charts.forEach(({ chart }) => chart.timeScale().setVisibleRange(range));
            renderNormalizedSeries(range);
        } finally {
            state.syncingTimeRange = false;
        }
    }

    function subscribeChartTimeRange(chart) {
        chart.timeScale().subscribeVisibleTimeRangeChange((range) => synchronizeVisibleRange(range));
    }

    function applyInitialVisibleRange() {
        const bounds = getRawDateBounds();
        if (bounds) synchronizeVisibleRange(state.visibleRange || bounds);
    }

    function createModelCard(model) {
        const card = document.createElement("article");
        card.className = "model-chart-card";
        card.dataset.modelId = model.model_id;
        card.innerHTML = `<div class="chart-card-head"><div><h2></h2><span class="model-meta"></span><span class="model-diagnostics"></span></div><button class="detail-button" type="button" title="查看持仓权重和换仓快照">明细</button></div><div class="chart-legend"><button type="button" data-series="high"><i></i>高分</button><button type="button" data-series="low"><i></i>低分</button><button type="button" data-series="relative"><i></i>相对</button><button type="button" data-series="benchmark"><i></i>基准</button></div><div class="chart-mount"></div>`;
        card.querySelector("h2").textContent = model.title;
        card.querySelector(".model-meta").textContent = `${model.frequency || "--"} · 最新 ${model.latest_date || "--"}`;
        card.querySelector(".model-diagnostics").textContent = `高/低持仓 ${model.holding_count_high ?? "--"}/${model.holding_count_low ?? "--"} · 行情覆盖 ${formatPercent(model.valid_price_coverage_high)}/${formatPercent(model.valid_price_coverage_low)} · 最近换仓 ${model.last_rebalance_date || "--"}`;
        card.querySelector(".detail-button").addEventListener("click", () => openModelDetail(model.model_id));
        return card;
    }

    function renderRankings() {
        const mount = document.getElementById("style-summary-rankings");
        mount.textContent = "";
        for (const horizon of ["1d", "5d", "20d"]) {
            const section = document.createElement("section");
            section.className = "ranking-column";
            const title = document.createElement("h2");
            title.textContent = horizon.toUpperCase();
            section.appendChild(title);
            const rows = state.summary?.rankings?.[horizon] || [];
            rows.forEach((row, index) => {
                const item = document.createElement("button");
                item.type = "button";
                item.className = "ranking-row";
                const model = state.summary.models.find((entry) => entry.model_id === row.model_id);
                item.innerHTML = `<span class="ranking-rank">${index + 1}</span><span class="ranking-title"></span><strong></strong>`;
                item.querySelector(".ranking-title").textContent = model?.title || row.model_id;
                item.querySelector("strong").textContent = formatPercent(row.value);
                item.addEventListener("click", () => openModelDetail(row.model_id));
                section.appendChild(item);
            });
            mount.appendChild(section);
        }
    }

    async function loadCurve(model, card) {
        const mount = card.querySelector(".chart-mount");
        if (!model.model_version) {
            mount.textContent = "尚未生成账本";
            mount.classList.add("chart-empty");
            return;
        }
        const params = new URLSearchParams({ model_id: model.model_id, range: state.range });
        if (state.range === "custom") {
            params.set("start_date", state.customStartDate);
            params.set("end_date", state.customEndDate);
        }
        if (state.benchmarkCode) params.set("benchmark_code", state.benchmarkCode);
        const payload = await apiFetch(`/api/style-monitor/curves?${params.toString()}`);
        if (!payload.series?.high?.length || !window.LightweightCharts) {
            mount.textContent = "该区间暂无完整理论曲线数据";
            mount.classList.add("chart-empty");
            return;
        }
        mount.textContent = "";
        const chart = window.LightweightCharts.createChart(mount, createChartOptions());
        const rawSeries = { ...(payload.series || {}), benchmark: payload.benchmark?.series || [] };
        if (payload.benchmark?.code) {
            state.benchmarkCode = payload.benchmark.code;
            state.benchmarkName = payload.benchmark.name || payload.benchmark.code;
            const input = document.getElementById("style-benchmark-code");
            if (input) input.value = payload.benchmark.code;
            updateBenchmarkStatus();
        }
        const series = {};
        for (const key of SERIES_KEYS) {
            if (key === "benchmark" && !rawSeries.benchmark.length) continue;
            if (!rawSeries[key]?.length) continue;
            series[key] = chart.addSeries(window.LightweightCharts.LineSeries, { color: COLORS[key], lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: SERIES_TITLES[key] });
            series[key].setData(rawSeries[key]);
        }
        state.charts.set(model.model_id, { chart, series, rawSeries, card });
        subscribeChartTimeRange(chart);
        card.querySelectorAll("[data-series]").forEach((button) => button.addEventListener("click", () => {
            const key = button.dataset.series;
            const visible = button.classList.toggle("muted") ? false : true;
            if (series[key]) series[key].applyOptions({ visible });
        }));
    }

    async function renderModelCharts() {
        const grid = document.getElementById("style-chart-grid");
        grid.textContent = "";
        state.charts.forEach(({ chart }) => chart.remove());
        state.charts.clear();
        state.visibleRange = null;
        for (const model of state.summary?.models || []) {
            const card = createModelCard(model);
            grid.appendChild(card);
            try { await loadCurve(model, card); } catch (error) { card.querySelector(".chart-mount").textContent = `曲线读取失败：${error.message}`; if (String(error.message || "").includes("基准")) document.getElementById("style-monitor-state").textContent = error.message; }
        }
        applyInitialVisibleRange();
    }

    async function renderPositions(modelId) {
        const payload = await apiFetch(`/api/style-monitor/positions?model_id=${encodeURIComponent(modelId)}&leg=${state.detailLeg}`);
        const content = document.getElementById("style-detail-content");
        content.textContent = "";
        if (!payload.items?.length && payload.message) {
            const note = document.createElement("p");
            note.className = "detail-note";
            note.textContent = payload.message;
            content.appendChild(note);
            return;
        }
        const table = document.createElement("table");
        table.innerHTML = "<thead><tr><th>代码</th><th>分数</th><th>排名</th><th>目标权重</th><th>生效权重</th></tr></thead><tbody></tbody>";
        const body = table.querySelector("tbody");
        payload.items.forEach((item) => { const row = document.createElement("tr"); [item.htsc_code, item.score ?? "--", item.rank ?? "--", formatPercent(item.target_weight), formatPercent(item.effective_weight)].forEach((value) => { const cell = document.createElement("td"); cell.textContent = String(value); row.appendChild(cell); }); body.appendChild(row); });
        content.appendChild(table);
    }

    async function renderTrades(modelId) {
        const payload = await apiFetch(`/api/style-monitor/trades?model_id=${encodeURIComponent(modelId)}&leg=${state.detailLeg}&limit=200`);
        const content = document.getElementById("style-detail-content");
        content.textContent = "";
        if (!payload.items?.length) {
            const note = document.createElement("p");
            note.className = "detail-note";
            note.textContent = payload.message || "等权收益指数不模拟现金交易";
            content.appendChild(note);
            return;
        }
        const table = document.createElement("table");
        table.innerHTML = "<thead><tr><th>日期</th><th>代码</th><th>方向</th><th>股数</th><th>成交额</th><th>费用</th></tr></thead><tbody></tbody>";
        const body = table.querySelector("tbody");
        payload.items.forEach((item) => { const row = document.createElement("tr"); [item.trade_date, item.htsc_code, item.side, item.shares, item.trade_value, item.commission].forEach((value) => { const cell = document.createElement("td"); cell.textContent = String(value); row.appendChild(cell); }); body.appendChild(row); });
        content.appendChild(table);
    }

    async function openModelDetail(modelId) {
        state.selectedModelId = modelId;
        const model = state.summary.models.find((entry) => entry.model_id === modelId);
        document.getElementById("style-detail-title").textContent = model?.title || modelId;
        document.getElementById("style-detail-drawer").setAttribute("aria-hidden", "false");
        if (state.detailTab === "positions") await renderPositions(modelId); else await renderTrades(modelId);
    }

    async function loadSummary() {
        const status = document.getElementById("style-monitor-state");
        try { state.summary = await apiFetch("/api/style-monitor/summary"); document.getElementById("style-monitor-as-of").textContent = `账本日期：${state.summary.as_of || "--"}`; status.textContent = state.summary.models.some((model) => model.latest_date) ? "" : "账本暂无数据"; renderRankings(); await renderModelCharts(); } catch (error) { status.textContent = `读取失败：${error.message}`; }
    }

    function initPageZoom() {
        const content = document.querySelector(".model-validity-zoom-content"); const value = document.getElementById("model-validity-zoom-value"); const buttons = [document.getElementById("model-validity-zoom-decrease"), document.getElementById("model-validity-zoom-reset"), document.getElementById("model-validity-zoom-increase")]; if (!content || !value) return;
        let current = DEFAULT_ZOOM; const apply = (zoom, persist = true) => { current = ZOOM_STEPS.includes(zoom) ? zoom : DEFAULT_ZOOM; content.style.setProperty("--model-validity-zoom", current); value.textContent = `${Math.round(current * 100)}%`; if (persist) { try { window.localStorage.setItem(ZOOM_STORAGE_KEY, String(current)); } catch (_) { /* restricted storage */ } } window.requestAnimationFrame(() => state.charts.forEach(({ chart }) => chart.resize(0, 0))); };
        buttons[0].addEventListener("click", () => apply(ZOOM_STEPS[Math.max(0, ZOOM_STEPS.indexOf(current) - 1)])); buttons[1].addEventListener("click", () => apply(DEFAULT_ZOOM)); buttons[2].addEventListener("click", () => apply(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, ZOOM_STEPS.indexOf(current) + 1)])); let stored = DEFAULT_ZOOM; try { stored = Number(window.localStorage.getItem(ZOOM_STORAGE_KEY)) || DEFAULT_ZOOM; } catch (_) { /* restricted storage */ } apply(stored, false);
    }

    async function applyCustomRange() {
        const startInput = document.getElementById("style-range-start");
        const lookbackInput = document.getElementById("style-range-lookback");
        const end = document.getElementById("style-range-end")?.value || "";
        const status = document.getElementById("style-monitor-state");
        let start = startInput?.value || "";
        const lookbackDays = lookbackInput?.value?.trim() || "";
        if (lookbackDays) {
            start = calculateLookbackStart(end, lookbackDays);
            if (!start) {
                status.textContent = "回看天数必须是 1 到 20000 的整数，并且需要先填写截止日期";
                return;
            }
            if (startInput) startInput.value = start;
        }
        if (!start || !end || start > end) {
            status.textContent = "Select a valid date range";
            return;
        }
        state.customStartDate = start;
        state.customEndDate = end;
        state.range = "custom";
        document.querySelectorAll("[data-range]").forEach((item) => item.classList.remove("active"));
        document.getElementById("style-range-apply")?.classList.add("active");
        if (state.summary) await renderModelCharts();
    }

    function updateClock() { const clock = document.getElementById("page-clock"); if (clock) clock.textContent = new Date().toLocaleString("zh-CN", { hour12: false }); }
    function init() {
        initPageZoom(); updateClock(); window.setInterval(updateClock, 1000);
        document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", async () => { document.querySelectorAll("[data-range]").forEach((item) => item.classList.remove("active")); button.classList.add("active"); document.getElementById("style-range-apply")?.classList.remove("active"); state.range = button.dataset.range; if (state.summary) await renderModelCharts(); }));
        document.getElementById("style-range-apply")?.addEventListener("click", applyCustomRange);
        const benchmarkInput = document.getElementById("style-benchmark-code");
        benchmarkInput?.addEventListener("input", () => {
            benchmarkInput.value = normalizeBenchmarkCode(benchmarkInput.value);
            if (state.benchmarkSuggestionTimer) window.clearTimeout(state.benchmarkSuggestionTimer);
            state.benchmarkSuggestionTimer = window.setTimeout(async () => {
                try { renderBenchmarkSuggestions(await fetchBenchmarkSuggestions(benchmarkInput.value)); } catch (_) { hideBenchmarkSuggestions(); }
            }, 180);
        });
        benchmarkInput?.addEventListener("keydown", async (event) => { if (event.key === "Enter") { event.preventDefault(); await applyBenchmark(); } else if (event.key === "Escape") hideBenchmarkSuggestions(); });
        benchmarkInput?.addEventListener("blur", () => window.setTimeout(hideBenchmarkSuggestions, 120));
        document.getElementById("style-benchmark-apply")?.addEventListener("click", applyBenchmark);
        document.getElementById("style-monitor-refresh")?.addEventListener("click", async () => {
            const button = document.getElementById("style-monitor-refresh");
            if (button) { button.disabled = true; button.textContent = "刷新中..."; }
            try { await loadSummary(); } finally { if (button) { button.disabled = false; button.textContent = "刷新账本"; } }
        });
        updateBenchmarkStatus();
        document.getElementById("style-range-start")?.addEventListener("input", () => { const lookback = document.getElementById("style-range-lookback"); if (lookback) lookback.value = ""; });
        document.getElementById("style-detail-close").addEventListener("click", () => document.getElementById("style-detail-drawer").setAttribute("aria-hidden", "true"));
        document.querySelectorAll("[data-detail-tab]").forEach((button) => button.addEventListener("click", async () => { document.querySelectorAll("[data-detail-tab]").forEach((item) => item.classList.remove("active")); button.classList.add("active"); state.detailTab = button.dataset.detailTab; if (state.selectedModelId) await openModelDetail(state.selectedModelId); }));
        document.querySelectorAll("[data-detail-leg]").forEach((button) => button.addEventListener("click", async () => { document.querySelectorAll("[data-detail-leg]").forEach((item) => item.classList.remove("active")); button.classList.add("active"); state.detailLeg = button.dataset.detailLeg; if (state.selectedModelId) await openModelDetail(state.selectedModelId); }));
        loadSummary(); if (typeof window.initEdgeFloatHud === "function") window.initEdgeFloatHud({ pageId: "model-validity", onNavigate: window.edgeFloatNavigateToPage });
    }
    window.addEventListener("resize", () => state.charts.forEach(({ chart }) => chart.resize(0, 0)));
    window.ModelValidity = { apiFetch, calculateLookbackStart, normalizeBenchmarkCode, isLikelyBenchmarkCode, createModelCard, renderRankings, renderModelCharts, loadCurve, openModelDetail, renderPositions, renderTrades, formatPercent };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
