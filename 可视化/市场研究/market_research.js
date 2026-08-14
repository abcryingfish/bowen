(function () {
    "use strict";

    const query = new URLSearchParams(window.location.search);
    const RANGE_CONFIG = {
        "20d": { calendarDays: 45, points: 20, label: "20日" },
        "60d": { calendarDays: 110, points: 60, label: "60日" },
        ytd: { calendarDays: null, points: 400, label: "年初至今" },
    };
    const MARKET_LABELS = { sh: "沪", sz: "深", star: "科创", "all-a": "全A" };
    const state = {
        market: MARKET_LABELS[query.get("market")] ? query.get("market") : "sh",
        range: "60d",
        customDays: null,
        payload: null,
        charts: [],
        series: [],
        pointByTime: new Map(),
        generation: 0,
    };

    function resolveApiBase() {
        const candidates = [window.MARKET_RESEARCH_API_BASE, query.get("api_base"), query.get("api")];
        try {
            candidates.push(localStorage.getItem("RESULTS_API_BASE"));
            candidates.push(localStorage.getItem("API_BASE_URL"));
        } catch (_) {
            // 无法读取本地配置时继续使用当前页面地址推断。
        }
        for (const rawValue of candidates) {
            const raw = String(rawValue || "").trim();
            if (!raw) continue;
            try {
                return new URL(/^https?:\/\//i.test(raw) ? raw : `http://${raw}`).origin;
            } catch (_) {
                // 忽略非法覆盖值。
            }
        }
        if (window.location.protocol === "https:") return window.location.origin;
        if (window.location.protocol === "http:") return `http://${window.location.hostname}:8000`;
        return "http://127.0.0.1:8000";
    }

    const API_BASE = resolveApiBase();

    async function apiFetch(path) {
        const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
        return payload;
    }

    function rangeRequest(now = new Date()) {
        const end = Math.floor(now.getTime() / 1000);
        const start = new Date(now);
        let points;
        if (state.range === "ytd") {
            start.setMonth(0, 1);
            points = RANGE_CONFIG.ytd.points;
        } else if (state.range === "custom") {
            points = Math.max(1, Math.min(2000, Math.floor(Number(state.customDays || 1))));
            start.setDate(start.getDate() - Math.ceil(points * 1.8) - 5);
        } else {
            const config = RANGE_CONFIG[state.range] || RANGE_CONFIG["60d"];
            points = config.points;
            start.setDate(start.getDate() - config.calendarDays);
        }
        start.setHours(0, 0, 0, 0);
        return { from: Math.floor(start.getTime() / 1000), to: end, points };
    }

    function rangeLabel() {
        if (state.range === "custom") return `${state.customDays}日`;
        return (RANGE_CONFIG[state.range] || RANGE_CONFIG["60d"]).label;
    }

    function createChartOptions(priceFormatter) {
        return {
            autoSize: true,
            layout: { background: { color: "#1e222d" }, textColor: "#d1d4dc", fontSize: 10, attributionLogo: false },
            localization: { priceFormatter },
            grid: { vertLines: { color: "#2b2b2b" }, horzLines: { color: "#2b2b2b" } },
            rightPriceScale: { borderColor: "#2b2b2b", scaleMargins: { top: 0.14, bottom: 0.14 } },
            timeScale: { borderColor: "#2b2b2b", timeVisible: false, rightOffset: 1, fixLeftEdge: true, fixRightEdge: true },
            crosshair: {
                mode: window.LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: "rgba(140,164,193,.32)", style: window.LightweightCharts.LineStyle.Dashed, labelBackgroundColor: "#3b82f6" },
                horzLine: { color: "rgba(140,164,193,.24)", style: window.LightweightCharts.LineStyle.Dashed, labelBackgroundColor: "#3b82f6" },
            },
            handleScroll: { mouseWheel: true, pressedMouseMove: true },
            handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
        };
    }

    function destroyCharts() {
        state.charts.forEach((chart) => chart.remove());
        state.charts = [];
        state.series = [];
    }

    function syncTimeScales(first, second) {
        let syncing = false;
        const bind = (source, target) => source.timeScale().subscribeVisibleLogicalRangeChange((range) => {
            if (!range || syncing) return;
            syncing = true;
            target.timeScale().setVisibleLogicalRange(range);
            syncing = false;
        });
        bind(first, second);
        bind(second, first);
    }

    function setMetricPoint(point) {
        if (!point) return;
        document.getElementById("concentration-date").textContent = point.date;
        document.getElementById("rsi-date").textContent = point.date;
        document.getElementById("concentration-value").textContent = Number.isFinite(Number(point.concentration))
            ? `${Number(point.concentration).toFixed(2)}%`
            : "--";
        document.getElementById("concentration-meta").textContent = `${point.stock_count}只 · Top ${point.top_count}只`;
        document.getElementById("rsi-value").textContent = Number.isFinite(Number(point.rsi_ratio))
            ? Number(point.rsi_ratio).toFixed(3)
            : "--";
        document.getElementById("rsi-meta").textContent = `覆盖 ${point.rsi_count}/${point.stock_count} · Top ${point.top_rsi_count}/${point.top_count}`;
        document.getElementById("latest-concentration").textContent = `${MARKET_LABELS[state.market]} ${Number(point.concentration).toFixed(2)}%`;
    }

    function bindCrosshair(chart) {
        chart.subscribeCrosshairMove((param) => {
            const timestamp = typeof param.time === "number" ? param.time : null;
            if (timestamp != null) setMetricPoint(state.pointByTime.get(timestamp));
        });
    }

    function renderCharts() {
        const marketPayload = state.payload?.markets?.[state.market];
        const points = Array.isArray(marketPayload?.points) ? marketPayload.points : [];
        const concentrationMount = document.getElementById("concentration-chart");
        const rsiMount = document.getElementById("rsi-chart");
        destroyCharts();
        concentrationMount.textContent = "";
        rsiMount.textContent = "";
        if (!points.length || !window.LightweightCharts) {
            concentrationMount.innerHTML = '<div class="chart-error">该区间暂无集中度数据</div>';
            rsiMount.innerHTML = '<div class="chart-error">该区间暂无 RSI 数据</div>';
            return;
        }

        state.pointByTime = new Map(points.map((point) => [Number(point.time), point]));
        const concentrationChart = window.LightweightCharts.createChart(
            concentrationMount,
            createChartOptions((price) => `${Number(price).toFixed(2)}%`),
        );
        const concentrationSeries = concentrationChart.addSeries(window.LightweightCharts.LineSeries, {
            color: "#6b9cff",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true,
        });
        concentrationSeries.setData(points
            .filter((point) => Number.isFinite(Number(point.concentration)))
            .map((point) => ({ time: Number(point.time), value: Number(point.concentration) })));

        const rsiChart = window.LightweightCharts.createChart(
            rsiMount,
            createChartOptions((price) => Number(price).toFixed(3)),
        );
        const rsiSeries = rsiChart.addSeries(window.LightweightCharts.LineSeries, {
            color: "#e9a23b",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true,
        });
        rsiSeries.setData(points
            .filter((point) => Number.isFinite(Number(point.rsi_ratio)))
            .map((point) => ({ time: Number(point.time), value: Number(point.rsi_ratio) })));
        rsiSeries.createPriceLine({ price: 1, color: "#687385", lineWidth: 1, lineStyle: window.LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: "" });

        state.charts = [concentrationChart, rsiChart];
        state.series = [concentrationSeries, rsiSeries];
        syncTimeScales(concentrationChart, rsiChart);
        bindCrosshair(concentrationChart);
        bindCrosshair(rsiChart);
        concentrationChart.timeScale().fitContent();
        rsiChart.timeScale().fitContent();
        setMetricPoint(points[points.length - 1]);
    }

    function selectMarket(market, updateUrl = true) {
        state.market = MARKET_LABELS[market] ? market : "sh";
        document.querySelectorAll("[data-market]").forEach((button) => {
            const active = button.dataset.market === state.market;
            button.classList.toggle("active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        if (updateUrl) {
            const url = new URL(window.location.href);
            url.searchParams.set("market", state.market);
            window.history.replaceState(null, "", url);
        }
        if (state.payload) {
            renderCharts();
            const count = state.payload.markets?.[state.market]?.points?.length || 0;
            const refreshButton = document.getElementById("refresh-research");
            if (!refreshButton?.disabled) {
                document.getElementById("research-state").textContent = `${MARKET_LABELS[state.market]} · ${rangeLabel()} · ${count} 个交易日`;
            }
        }
    }

    async function loadResearch(refresh = false) {
        const generation = ++state.generation;
        const status = document.getElementById("research-state");
        const refreshButton = document.getElementById("refresh-research");
        status.classList.remove("error");
        status.textContent = `正在计算 ${rangeLabel()} 市场集中度...`;
        refreshButton.disabled = true;
        try {
            const request = rangeRequest();
            const params = new URLSearchParams({
                from: String(request.from),
                to: String(request.to),
                points: String(request.points),
            });
            if (refresh) params.set("refresh", "1");
            const payload = await apiFetch(`/api/market/research/concentration?${params.toString()}`);
            if (generation !== state.generation) return;
            state.payload = payload;
            renderCharts();
            const count = payload.markets?.[state.market]?.points?.length || 0;
            status.textContent = `${MARKET_LABELS[state.market]} · ${rangeLabel()} · ${count} 个交易日`;
        } catch (error) {
            if (generation !== state.generation) return;
            status.classList.add("error");
            status.textContent = `市场研究读取失败：${error.message}`;
            destroyCharts();
            document.getElementById("concentration-chart").innerHTML = '<div class="chart-error">集中度读取失败</div>';
            document.getElementById("rsi-chart").innerHTML = '<div class="chart-error">RSI 比值读取失败</div>';
        } finally {
            if (generation === state.generation) refreshButton.disabled = false;
        }
    }

    function bindControls() {
        document.querySelectorAll("[data-market]").forEach((button) => {
            button.addEventListener("click", () => selectMarket(button.dataset.market));
        });
        document.querySelectorAll("[data-range]").forEach((button) => {
            button.addEventListener("click", () => {
                state.range = button.dataset.range;
                state.customDays = null;
                document.querySelectorAll("[data-range]").forEach((item) => item.classList.toggle("active", item === button));
                document.querySelector(".custom-range")?.classList.remove("is-active");
                void loadResearch();
            });
        });
        const customInput = document.getElementById("custom-range-days");
        const applyCustom = () => {
            const days = Math.floor(Number(customInput.value));
            if (!Number.isFinite(days) || days < 1 || days > 2000) {
                customInput.focus();
                return;
            }
            state.range = "custom";
            state.customDays = days;
            document.querySelectorAll("[data-range]").forEach((item) => item.classList.remove("active"));
            document.querySelector(".custom-range")?.classList.add("is-active");
            void loadResearch();
        };
        document.getElementById("custom-range-apply").addEventListener("click", applyCustom);
        customInput.addEventListener("keydown", (event) => { if (event.key === "Enter") applyCustom(); });
        document.getElementById("refresh-research").addEventListener("click", () => loadResearch(true));
    }

    function updateClock() {
        document.getElementById("page-clock").textContent = new Intl.DateTimeFormat("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: false,
        }).format(new Date());
    }

    document.addEventListener("DOMContentLoaded", () => {
        bindControls();
        selectMarket(state.market, false);
        updateClock();
        window.setInterval(updateClock, 1000);
        void loadResearch();
    });

    window.MarketResearch = { rangeRequest, selectMarket, loadResearch };
})();
