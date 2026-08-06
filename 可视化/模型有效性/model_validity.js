(function () {
    "use strict";

    const API_BASE = window.STYLE_MONITOR_API_BASE || "http://127.0.0.1:8000";
    const DEFAULT_ZOOM = 1.25;
    const ZOOM_STEPS = [1, 1.1, DEFAULT_ZOOM, 1.4, 1.5];
    const ZOOM_STORAGE_KEY = "model-validity.zoom";
    const COLORS = { high: "#26a69a", low: "#f59e0b", relative: "#6b9cff" };
    const state = { range: "60d", summary: null, charts: new Map(), selectedModelId: null, updateJobId: null, detailTab: "positions", detailLeg: "high" };

    function formatPercent(value) {
        return value == null || Number.isNaN(Number(value)) ? "--" : `${(Number(value) * 100).toFixed(2)}%`;
    }

    async function apiFetch(path, options) {
        const response = await fetch(`${API_BASE}${path}`, { ...options, headers: { "Content-Type": "application/json", ...(options && options.headers) } });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
        return payload;
    }

    function createChartOptions() {
        return { autoSize: true, layout: { background: { color: "rgba(0,0,0,0)" }, textColor: "rgba(224,231,255,.88)", fontSize: 11, attributionLogo: false }, grid: { vertLines: { color: "rgba(255,255,255,.05)" }, horzLines: { color: "rgba(255,255,255,.06)" } }, rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false, timeVisible: true, fixLeftEdge: true, fixRightEdge: true }, handleScroll: { mouseWheel: true, pressedMouseMove: true }, handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true } };
    }

    function createModelCard(model) {
        const card = document.createElement("article");
        card.className = "model-chart-card";
        card.dataset.modelId = model.model_id;
        card.innerHTML = `<div class="chart-card-head"><div><h2></h2><span class="model-meta"></span></div><button class="detail-button" type="button" title="查看持仓和交易">明细</button></div><div class="chart-legend"><button type="button" data-series="high"><i></i>高分</button><button type="button" data-series="low"><i></i>低分</button><button type="button" data-series="relative"><i></i>相对</button></div><div class="chart-mount"></div>`;
        card.querySelector("h2").textContent = model.title;
        card.querySelector(".model-meta").textContent = `${model.frequency || "--"} · 最新 ${model.latest_date || "--"}`;
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
        const payload = await apiFetch(`/api/style-monitor/curves?model_id=${encodeURIComponent(model.model_id)}&range=${encodeURIComponent(state.range)}`);
        if (!payload.series?.high?.length || !window.LightweightCharts) {
            mount.textContent = "该区间暂无完整净值数据";
            mount.classList.add("chart-empty");
            return;
        }
        mount.textContent = "";
        const chart = window.LightweightCharts.createChart(mount, createChartOptions());
        const series = {};
        for (const key of ["high", "low", "relative"]) {
            series[key] = chart.addSeries(window.LightweightCharts.LineSeries, { color: COLORS[key], lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: key });
            series[key].setData(payload.series[key]);
        }
        chart.timeScale().fitContent();
        state.charts.set(model.model_id, { chart, series });
        card.querySelectorAll("[data-series]").forEach((button) => button.addEventListener("click", () => {
            const key = button.dataset.series;
            const visible = button.classList.toggle("muted") ? false : true;
            series[key].applyOptions({ visible });
        }));
    }

    async function renderModelCharts() {
        const grid = document.getElementById("style-chart-grid");
        grid.textContent = "";
        state.charts.forEach(({ chart }) => chart.remove());
        state.charts.clear();
        for (const model of state.summary?.models || []) {
            const card = createModelCard(model);
            grid.appendChild(card);
            try { await loadCurve(model, card); } catch (error) { card.querySelector(".chart-mount").textContent = `曲线读取失败：${error.message}`; }
        }
    }

    async function renderPositions(modelId) {
        const payload = await apiFetch(`/api/style-monitor/positions?model_id=${encodeURIComponent(modelId)}&leg=${state.detailLeg}`);
        const content = document.getElementById("style-detail-content");
        content.textContent = "";
        const table = document.createElement("table");
        table.innerHTML = "<thead><tr><th>代码</th><th>分数</th><th>排名</th><th>权重</th><th>股数</th><th>价格</th></tr></thead><tbody></tbody>";
        const body = table.querySelector("tbody");
        payload.items.forEach((item) => { const row = document.createElement("tr"); [item.htsc_code, item.score ?? "--", item.rank ?? "--", formatPercent(item.actual_weight), item.shares, item.price].forEach((value) => { const cell = document.createElement("td"); cell.textContent = String(value); row.appendChild(cell); }); body.appendChild(row); });
        content.appendChild(table);
    }

    async function renderTrades(modelId) {
        const payload = await apiFetch(`/api/style-monitor/trades?model_id=${encodeURIComponent(modelId)}&leg=${state.detailLeg}&limit=200`);
        const content = document.getElementById("style-detail-content");
        content.textContent = "";
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

    async function pollUpdateJob() {
        if (!state.updateJobId) return;
        const job = await apiFetch(`/api/style-monitor/update/jobs/${encodeURIComponent(state.updateJobId)}`);
        const progress = document.getElementById("style-monitor-progress");
        progress.textContent = `${job.stage || "更新中"} ${job.progress || 0}%`;
        if (job.status === "done" || job.status === "failed") {
            state.updateJobId = null;
            if (job.status === "failed") document.getElementById("style-monitor-message").textContent = job.error || "更新失败";
            else await loadSummary();
            return;
        }
        window.setTimeout(pollUpdateJob, 1000);
    }

    async function startManualUpdate() {
        if (state.updateJobId) return;
        const button = document.getElementById("style-monitor-update");
        button.disabled = true;
        try { const job = await apiFetch("/api/style-monitor/update", { method: "POST", body: JSON.stringify({}) }); state.updateJobId = job.job_id; pollUpdateJob(); } catch (error) { document.getElementById("style-monitor-message").textContent = error.message; } finally { button.disabled = false; }
    }

    async function loadSummary() {
        const status = document.getElementById("style-monitor-state");
        try { state.summary = await apiFetch("/api/style-monitor/summary"); document.getElementById("style-monitor-as-of").textContent = `账本日期：${state.summary.as_of || "--"}`; status.textContent = state.summary.models.some((model) => model.latest_date) ? "" : "账本暂无数据，请手动更新"; renderRankings(); await renderModelCharts(); } catch (error) { status.textContent = `读取失败：${error.message}`; }
    }

    function initPageZoom() {
        const content = document.querySelector(".model-validity-zoom-content"); const value = document.getElementById("model-validity-zoom-value"); const buttons = [document.getElementById("model-validity-zoom-decrease"), document.getElementById("model-validity-zoom-reset"), document.getElementById("model-validity-zoom-increase")]; if (!content || !value) return;
        let current = DEFAULT_ZOOM; const apply = (zoom, persist = true) => { current = ZOOM_STEPS.includes(zoom) ? zoom : DEFAULT_ZOOM; content.style.setProperty("--model-validity-zoom", current); value.textContent = `${Math.round(current * 100)}%`; if (persist) { try { window.localStorage.setItem(ZOOM_STORAGE_KEY, String(current)); } catch (_) { /* restricted storage */ } } window.requestAnimationFrame(() => state.charts.forEach(({ chart }) => chart.resize(0, 0))); };
        buttons[0].addEventListener("click", () => apply(ZOOM_STEPS[Math.max(0, ZOOM_STEPS.indexOf(current) - 1)])); buttons[1].addEventListener("click", () => apply(DEFAULT_ZOOM)); buttons[2].addEventListener("click", () => apply(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, ZOOM_STEPS.indexOf(current) + 1)])); let stored = DEFAULT_ZOOM; try { stored = Number(window.localStorage.getItem(ZOOM_STORAGE_KEY)) || DEFAULT_ZOOM; } catch (_) { /* restricted storage */ } apply(stored, false);
    }

    function updateClock() { const clock = document.getElementById("page-clock"); if (clock) clock.textContent = new Date().toLocaleString("zh-CN", { hour12: false }); }
    function init() {
        initPageZoom(); updateClock(); window.setInterval(updateClock, 1000);
        document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", async () => { document.querySelectorAll("[data-range]").forEach((item) => item.classList.remove("active")); button.classList.add("active"); state.range = button.dataset.range; if (state.summary) await renderModelCharts(); }));
        document.getElementById("style-monitor-update").addEventListener("click", startManualUpdate);
        document.getElementById("style-detail-close").addEventListener("click", () => document.getElementById("style-detail-drawer").setAttribute("aria-hidden", "true"));
        document.querySelectorAll("[data-detail-tab]").forEach((button) => button.addEventListener("click", async () => { document.querySelectorAll("[data-detail-tab]").forEach((item) => item.classList.remove("active")); button.classList.add("active"); state.detailTab = button.dataset.detailTab; if (state.selectedModelId) await openModelDetail(state.selectedModelId); }));
        document.querySelectorAll("[data-detail-leg]").forEach((button) => button.addEventListener("click", async () => { document.querySelectorAll("[data-detail-leg]").forEach((item) => item.classList.remove("active")); button.classList.add("active"); state.detailLeg = button.dataset.detailLeg; if (state.selectedModelId) await openModelDetail(state.selectedModelId); }));
        loadSummary(); if (typeof window.initEdgeFloatHud === "function") window.initEdgeFloatHud({ pageId: "model-validity", onNavigate: window.edgeFloatNavigateToPage });
    }
    window.addEventListener("resize", () => state.charts.forEach(({ chart }) => chart.resize(0, 0)));
    window.ModelValidity = { apiFetch, createModelCard, renderRankings, renderModelCharts, loadCurve, openModelDetail, renderPositions, renderTrades, startManualUpdate, pollUpdateJob, formatPercent };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
