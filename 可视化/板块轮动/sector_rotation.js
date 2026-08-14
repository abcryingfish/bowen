(function () {
    "use strict";

    const query = new URLSearchParams(window.location.search);
    function resolveSectorRotationApiBase() {
        const candidates = [
            window.SECTOR_ROTATION_API_BASE,
            query.get("api_base"),
            query.get("api"),
        ];
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
                const normalized = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
                return new URL(normalized).origin;
            } catch (_) {
                // 忽略非法覆盖值，继续尝试下一个地址。
            }
        }
        try {
            if (window.location.protocol === "https:") return window.location.origin;
            if (window.location.protocol === "http:") return `http://${window.location.hostname}:8000`;
        } catch (_) {
            // 非浏览器测试环境使用本机回退地址。
        }
        return "http://127.0.0.1:8000";
    }
    const API_BASE = resolveSectorRotationApiBase();
    const PREFIX_LABELS = { "881": "粗行业", "882": "地域", "885": "早期细分概念", "886": "后期细分概念" };
    const RANGE_CONFIG = {
        "20d": { calendarDays: 45, points: 20, label: "20日" },
        "60d": { calendarDays: 110, points: 60, label: "60日" },
        ytd: { calendarDays: null, points: null, label: "年初至今" },
    };
    const state = { prefix: "881", range: "60d", customDays: null, keyword: "", stockFilterCode: "", stockSectorCodes: null, searchRequestId: 0, sortOrder: "desc", sortActive: false, sortRequestId: 0, allItems: [], generation: 0, scrollHandler: null, visibleCardScheduler: null, constituentObserver: null, controlScrollHandler: null, lastScrollY: 0, charts: new Map(), queue: [], activeRequests: 0 };
    const MAX_CONCURRENT_REQUESTS = 4;

    async function apiFetch(path) {
        const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
        return payload;
    }

    function closeConstituentDialog() {
        const dialog = document.getElementById("constituent-dialog");
        if (!dialog) return;
        dialog.classList.remove("is-open");
        dialog.setAttribute("aria-hidden", "true");
        state.constituentObserver?.disconnect();
        state.constituentObserver = null;
    }

    function drawMiniCloseLine(canvas, closes) {
        const values = (Array.isArray(closes) ? closes : []).map(Number).filter(Number.isFinite);
        if (!canvas || values.length < 2) return;
        const width = 96;
        const height = 28;
        const ratio = Math.max(1, window.devicePixelRatio || 1);
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
        const context = canvas.getContext("2d");
        context.scale(ratio, ratio);
        const min = Math.min(...values);
        const max = Math.max(...values);
        const spread = max - min || 1;
        context.beginPath();
        values.forEach((value, index) => {
            const x = 2 + index / (values.length - 1) * (width - 4);
            const y = 3 + (max - value) / spread * (height - 6);
            if (index === 0) context.moveTo(x, y);
            else context.lineTo(x, y);
        });
        context.strokeStyle = values[values.length - 1] >= values[0] ? "#ef5350" : "#26a69a";
        context.lineWidth = 1.4;
        context.lineJoin = "round";
        context.lineCap = "round";
        context.stroke();
    }

    async function openConstituentDialog(card) {
        const dialog = document.getElementById("constituent-dialog");
        const title = document.getElementById("constituent-title");
        const meta = document.getElementById("constituent-meta");
        const status = document.getElementById("constituent-state");
        const list = document.getElementById("constituent-list");
        if (!dialog || !card) return;
        const code = String(card.dataset.code || "").toUpperCase();
        const name = card.querySelector(".sector-name h2")?.textContent || code;
        title.textContent = `${name} 成分股 · 20天曲线`;
        meta.textContent = code;
        status.className = "constituent-state";
        status.textContent = "正在读取成分股...";
        list.textContent = "";
        state.constituentObserver?.disconnect();
        state.constituentObserver = "IntersectionObserver" in window
            ? new IntersectionObserver((entries, observer) => {
                entries.forEach((entry) => {
                    if (!entry.isIntersecting) return;
                    drawMiniCloseLine(entry.target, entry.target._closeValues);
                    observer.unobserve(entry.target);
                });
            }, { root: list, rootMargin: "80px" })
            : null;
        dialog.classList.add("is-open");
        dialog.setAttribute("aria-hidden", "false");
        try {
            const params = new URLSearchParams({ sector_code: code });
            const payload = await apiFetch(`/api/market/sector-constituents?${params.toString()}`);
            const items = (Array.isArray(payload.items) ? payload.items : []).map((item) => {
                const closes = (Array.isArray(item.closes_20d) ? item.closes_20d : []).map(Number).filter(Number.isFinite);
                const returnRate = closes.length >= 2 && closes[0] !== 0
                    ? (closes[closes.length - 1] / closes[0] - 1) * 100
                    : null;
                return { ...item, closes, returnRate };
            }).sort((left, right) => {
                const leftValid = Number.isFinite(left.returnRate);
                const rightValid = Number.isFinite(right.returnRate);
                if (leftValid !== rightValid) return leftValid ? -1 : 1;
                if (!leftValid) return String(left.code || "").localeCompare(String(right.code || ""));
                return right.returnRate - left.returnRate || String(left.code || "").localeCompare(String(right.code || ""));
            });
            meta.textContent = `${code} · ${items.length} 只成分股`;
            status.textContent = items.length ? "" : "该板块暂无可用成分股";
            items.forEach((item) => {
                const row = document.createElement("div");
                row.className = "constituent-item";
                const stockName = document.createElement("span");
                stockName.className = "constituent-name";
                stockName.textContent = item.name || "未命名股票";
                const returnRate = item.returnRate;
                const returnNode = document.createElement("span");
                returnNode.className = "constituent-return";
                returnNode.textContent = Number.isFinite(returnRate)
                    ? `${returnRate >= 0 ? "+" : ""}${returnRate.toFixed(2)}%`
                    : "--";
                if (Number.isFinite(returnRate)) returnNode.classList.add(returnRate >= 0 ? "positive" : "negative");
                const stockCode = document.createElement("code");
                stockCode.textContent = item.code || "--";
                const sparkline = document.createElement("canvas");
                sparkline.className = "constituent-sparkline";
                sparkline.setAttribute("role", "img");
                sparkline.setAttribute("aria-label", `${item.name || item.code} 最近20个交易日收盘走势`);
                row.append(stockName, returnNode, sparkline, stockCode);
                list.appendChild(row);
                sparkline._closeValues = item.closes;
                if (state.constituentObserver) state.constituentObserver.observe(sparkline);
                else drawMiniCloseLine(sparkline, item.closes);
            });
        } catch (error) {
            status.classList.add("error");
            status.textContent = `成分股读取失败：${error.message}`;
        }
    }

    function rangeTimestamps(rangeKey, now = new Date()) {
        const end = Math.floor(now.getTime() / 1000);
        const config = RANGE_CONFIG[rangeKey] || RANGE_CONFIG["60d"];
        const start = new Date(now);
        if (rangeKey === "ytd") start.setMonth(0, 1);
        else if (rangeKey === "custom") start.setDate(start.getDate() - Math.ceil(Number(state.customDays || 1) * 1.8) - 5);
        else start.setDate(start.getDate() - config.calendarDays);
        start.setHours(0, 0, 0, 0);
        return { from: Math.floor(start.getTime() / 1000), to: end };
    }

    function getRangeLabel() {
        return state.range === "custom" ? `${state.customDays || "--"}日` : RANGE_CONFIG[state.range].label;
    }

    function filterSectorItems(items, prefix, keyword) {
        const term = String(keyword || "").trim().toLowerCase();
        return (Array.isArray(items) ? items : []).filter((item) => {
            const code = String(item.code || "").trim().toUpperCase();
            const name = String(item.name || "").trim();
            const initials = String(item.pinyin_initials || "").trim().toLowerCase();
            if (!code.endsWith(".THS") || !code.startsWith(prefix)) return false;
            if (state.stockSectorCodes instanceof Set && !state.stockSectorCodes.has(code)) return false;
            return !term || code.toLowerCase().includes(term) || name.toLowerCase().includes(term) || initials.includes(term);
        });
    }

    function isStockCodeQuery(value) {
        return /^\d{6}(?:\.(?:SH|SZ|BJ))?$/i.test(String(value || "").trim());
    }

    async function findStockCandidates(value) {
        const params = new URLSearchParams({ q: String(value || "").trim(), interval: "1day", limit: "8" });
        const payload = await apiFetch(`/api/market/codes/search?${params.toString()}`);
        const items = Array.isArray(payload.items) ? payload.items : [];
        return items.filter((item) => {
            const code = String(item?.code || "").toUpperCase();
            return /^\d{6}\.(SH|SZ|BJ)$/.test(code);
        }).map((item) => ({ type: "stock", code: String(item.code).toUpperCase(), name: String(item.name || "") }));
    }

    function findSectorCandidates(value) {
        const term = String(value || "").trim().toLowerCase();
        if (!term) return [];
        return state.allItems.map((item) => {
            const code = String(item.code || "").trim().toUpperCase();
            const name = String(item.name || "").trim();
            const initials = String(item.pinyin_initials || "").trim().toLowerCase();
            const codeText = code.toLowerCase();
            const nameText = name.toLowerCase();
            let rank = 99;
            if (codeText === term || nameText === term || initials === term) rank = 0;
            else if (codeText.startsWith(term) || nameText.startsWith(term) || initials.startsWith(term)) rank = 1;
            else if (codeText.includes(term) || nameText.includes(term) || initials.includes(term)) rank = 2;
            return { type: "sector", code, name, rank };
        }).filter((item) => item.rank < 99 && item.code.endsWith(".THS"))
            .sort((left, right) => left.rank - right.rank || left.name.localeCompare(right.name) || left.code.localeCompare(right.code));
    }

    function closeSearchSuggestions() {
        const input = document.getElementById("sector-search");
        const suggestions = document.getElementById("sector-search-suggestions");
        suggestions?.classList.remove("is-open");
        if (suggestions) suggestions.textContent = "";
        input?.setAttribute("aria-expanded", "false");
    }

    function setActiveSearchOption(index) {
        const suggestions = document.getElementById("sector-search-suggestions");
        const options = Array.from(suggestions?.querySelectorAll(".sector-search-option") || []);
        if (!options.length) return;
        const normalized = (index + options.length) % options.length;
        options.forEach((option, optionIndex) => {
            option.classList.toggle("is-active", optionIndex === normalized);
            option.setAttribute("aria-selected", optionIndex === normalized ? "true" : "false");
        });
        suggestions.dataset.activeIndex = String(normalized);
        options[normalized].scrollIntoView({ block: "nearest" });
    }

    function selectSectorCandidate(sector, input) {
        const prefix = String(sector.code || "").slice(0, 3);
        if (!PREFIX_LABELS[prefix]) return;
        input.value = sector.name || sector.code;
        closeSearchSuggestions();
        state.prefix = prefix;
        state.keyword = sector.code;
        state.stockFilterCode = "";
        state.stockSectorCodes = null;
        document.querySelectorAll("[data-prefix]").forEach((button) => button.classList.toggle("active", button.dataset.prefix === prefix));
        renderSectors();
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function renderSearchCandidates(candidates, requestId) {
        const input = document.getElementById("sector-search");
        const suggestions = document.getElementById("sector-search-suggestions");
        if (!input || !suggestions || requestId !== state.searchRequestId) return;
        suggestions.textContent = "";
        suggestions.dataset.activeIndex = "-1";
        candidates.forEach((candidate, candidateIndex) => {
            const item = document.createElement("li");
            const button = document.createElement("button");
            button.type = "button";
            button.className = "sector-search-option";
            button.setAttribute("role", "option");
            const name = document.createElement("span");
            name.textContent = candidate.name || (candidate.type === "sector" ? "未命名板块" : "未命名股票");
            const code = document.createElement("code");
            code.textContent = `${candidate.type === "sector" ? "板块" : "股票"} · ${candidate.code}`;
            button.append(name, code);
            button.addEventListener("mouseenter", () => setActiveSearchOption(candidateIndex));
            button.addEventListener("click", () => {
                if (candidate.type === "sector") selectSectorCandidate(candidate, input);
                else {
                    input.value = candidate.name || candidate.code;
                    closeSearchSuggestions();
                    void loadStockMemberships(candidate, requestId);
                }
            });
            item.appendChild(button);
            suggestions.appendChild(item);
        });
        suggestions.classList.add("is-open");
        input.setAttribute("aria-expanded", "true");
    }

    async function loadStockMemberships(stock, requestId) {
        const params = new URLSearchParams({ stock_code: stock.code });
        const payload = await apiFetch(`/api/market/sector-memberships?${params.toString()}`);
        if (requestId !== state.searchRequestId) return false;
        state.keyword = "";
        state.stockFilterCode = String(payload.stock_code || stock.code).toUpperCase();
        state.stockSectorCodes = new Set((payload.items || []).map((item) => String(item.code || "").toUpperCase()));
        renderSectors();
        return true;
    }

    async function applySearchQuery(value) {
        const raw = String(value || "").trim();
        const requestId = ++state.searchRequestId;
        if (!raw) {
            closeSearchSuggestions();
            state.keyword = "";
            state.stockFilterCode = "";
            state.stockSectorCodes = null;
            renderSectors();
            return;
        }
        const status = document.getElementById("sector-state");
        status.classList.remove("error");
        status.textContent = isStockCodeQuery(raw) ? `正在查询股票 ${raw.toUpperCase()} 所属板块...` : "正在检索股票或板块...";
        try {
            if (isStockCodeQuery(raw)) {
                closeSearchSuggestions();
                await loadStockMemberships({ code: raw.toUpperCase(), name: "" }, requestId);
                return;
            }
            const [stockCandidates, sectorCandidates] = await Promise.all([
                findStockCandidates(raw),
                Promise.resolve(findSectorCandidates(raw)),
            ]);
            if (requestId !== state.searchRequestId) return;
            const candidates = [...sectorCandidates, ...stockCandidates]
                .filter((item, index, items) => items.findIndex((candidate) => candidate.code === item.code) === index)
                .slice(0, 8);
            if (candidates.length) {
                renderSearchCandidates(candidates, requestId);
                const sectorCount = candidates.filter((item) => item.type === "sector").length;
                const stockCount = candidates.length - sectorCount;
                status.textContent = `找到 ${sectorCount} 个板块、${stockCount} 只股票，请选择`;
                return;
            }
            closeSearchSuggestions();
            if (requestId !== state.searchRequestId) return;
            state.keyword = raw;
            state.stockFilterCode = "";
            state.stockSectorCodes = null;
            renderSectors();
        } catch (error) {
            if (requestId !== state.searchRequestId) return;
            state.keyword = raw;
            state.stockFilterCode = "";
            state.stockSectorCodes = null;
            renderSectors();
            status.classList.add("error");
            status.textContent = `检索失败：${error.message}`;
        }
    }

    function createChartOptions() {
        return {
            autoSize: true,
            layout: { background: { color: "#1e222d" }, textColor: "#d1d4dc", fontSize: 10, attributionLogo: false },
            grid: { vertLines: { color: "#2b2b2b" }, horzLines: { color: "#2b2b2b" } },
            rightPriceScale: { borderColor: "#2b2b2b", scaleMargins: { top: 0.12, bottom: 0.12 } },
            timeScale: { borderColor: "#2b2b2b", timeVisible: false, rightOffset: 1, fixLeftEdge: true, fixRightEdge: true },
            crosshair: {
                mode: window.LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: "rgba(140,164,193,.32)", style: window.LightweightCharts.LineStyle.Dashed, labelBackgroundColor: "#3b82f6" },
                horzLine: { color: "rgba(140,164,193,.24)", style: window.LightweightCharts.LineStyle.Dashed, labelBackgroundColor: "#3b82f6" },
            },
            handleScroll: { mouseWheel: false, pressedMouseMove: true },
            handleScale: { axisPressedMouseMove: false, mouseWheel: false, pinch: false },
        };
    }

    function createSectorCard(item) {
        const card = document.createElement("article");
        card.className = "sector-card";
        card.dataset.code = item.code;
        card.innerHTML = `<div class="sector-card-head"><div class="sector-name"><h2></h2><span></span></div><div class="sector-performance"><strong>--</strong><span>${getRangeLabel()}涨跌幅</span></div></div><div class="chart-mount"><div class="chart-placeholder">等待加载走势</div></div>`;
        card.querySelector("h2").textContent = item.name || item.code;
        card.querySelector(".sector-name span").textContent = item.code;
        card.addEventListener("dblclick", () => { void openConstituentDialog(card); });
        return card;
    }

    function sortCardsByReturn() {
        const grid = document.getElementById("sector-grid");
        if (!grid) return;
        const cards = Array.from(grid.querySelectorAll(".sector-card"));
        cards.sort((left, right) => {
            const leftValue = Number(left.dataset.return);
            const rightValue = Number(right.dataset.return);
            const leftLoaded = Number.isFinite(leftValue);
            const rightLoaded = Number.isFinite(rightValue);
            if (leftLoaded !== rightLoaded) return leftLoaded ? -1 : 1;
            if (!leftLoaded) return String(left.dataset.code).localeCompare(String(right.dataset.code));
            const difference = state.sortOrder === "asc" ? leftValue - rightValue : rightValue - leftValue;
            return difference || String(left.dataset.code).localeCompare(String(right.dataset.code));
        });
        const fragment = document.createDocumentFragment();
        cards.forEach((card) => fragment.appendChild(card));
        grid.appendChild(fragment);
    }

    function destroyCharts() {
        state.charts.forEach((chart) => chart.remove());
        state.charts.clear();
        if (state.scrollHandler) window.removeEventListener("scroll", state.scrollHandler);
        state.scrollHandler = null;
        state.visibleCardScheduler = null;
        state.queue.length = 0;
    }

    async function loadReturnsAndSort(generation) {
        const cards = Array.from(document.querySelectorAll("#sector-grid .sector-card"));
        if (!cards.length) return;
        const requestId = ++state.sortRequestId;
        const status = document.getElementById("sector-state");
        status.classList.remove("error");
        status.textContent = `正在计算 ${cards.length} 个板块的收益率...`;
        try {
            const bounds = rangeTimestamps(state.range);
            const pointLimit = state.range === "custom" ? Number(state.customDays) : RANGE_CONFIG[state.range].points;
            const params = new URLSearchParams({ prefix: state.prefix, from: String(bounds.from), to: String(bounds.to) });
            if (pointLimit) params.set("points", String(pointLimit));
            if (state.stockSectorCodes instanceof Set) params.set("codes", cards.map((card) => card.dataset.code).join(","));
            let payload;
            try {
                payload = await apiFetch(`/api/market/index/returns?${params.toString()}`);
            } catch (error) {
                // 兼容未重启的旧 API：仅对当前筛选卡片读取 bars，避免排序按钮失效。
                if (!/HTTP 404|不存在|not found/i.test(String(error.message || ""))) throw error;
                const fallbackItems = await Promise.all(cards.map(async (card) => {
                    const barParams = new URLSearchParams({ code: card.dataset.code, from: String(bounds.from), to: String(bounds.to), limit: "400" });
                    const barPayload = await apiFetch(`/api/market/index/bars?${barParams.toString()}`);
                    const bars = selectOhlcBars(barPayload.bars, pointLimit);
                    if (bars.length < 2 || !Number(bars[0].close)) return null;
                    return { code: card.dataset.code, return_pct: (Number(bars[bars.length - 1].close) / Number(bars[0].close) - 1) * 100 };
                }));
                payload = { items: fallbackItems.filter(Boolean) };
            }
            if (generation !== state.generation || requestId !== state.sortRequestId) return;
            const returns = new Map((payload.items || []).map((item) => [String(item.code || "").toUpperCase(), Number(item.return_pct)]));
            cards.forEach((card) => {
                const value = returns.get(card.dataset.code);
                if (Number.isFinite(value)) card.dataset.return = String(value);
            });
            sortCardsByReturn();
            state.visibleCardScheduler?.();
            status.textContent = `排序完成：${returns.size}/${cards.length}`;
        } catch (error) {
            if (generation !== state.generation || requestId !== state.sortRequestId) return;
            status.classList.add("error");
            status.textContent = `收益率排序失败：${error.message}`;
        }
    }

    function normalizedCloseSeries(bars, points) {
        let selected = (Array.isArray(bars) ? bars : []).filter((bar) => Number.isFinite(Number(bar.close)) && Number(bar.close) > 0);
        if (points && selected.length > points) selected = selected.slice(-points);
        const base = Number(selected[0]?.close);
        if (!base) return [];
        return selected.map((bar) => ({ time: Number(bar.time), value: Number(bar.close) / base * 100 }));
    }

    function selectOhlcBars(bars, points) {
        let selected = (Array.isArray(bars) ? bars : []).filter((bar) =>
            [bar.open, bar.high, bar.low, bar.close].every((value) => Number.isFinite(Number(value)))
        );
        if (points && selected.length > points) selected = selected.slice(-points);
        return selected.map((bar) => ({
            time: Number(bar.time),
            open: Number(bar.open),
            high: Number(bar.high),
            low: Number(bar.low),
            close: Number(bar.close),
        }));
    }

    function enqueueCard(card, generation) {
        state.queue.push({ card, generation });
        drainQueue();
    }

    function drainQueue() {
        while (state.activeRequests < MAX_CONCURRENT_REQUESTS && state.queue.length) {
            const task = state.queue.shift();
            state.activeRequests += 1;
            loadSectorChart(task.card, task.generation).finally(() => {
                state.activeRequests -= 1;
                drainQueue();
            });
        }
    }

    async function loadSectorChart(card, generation) {
        if (!card?.isConnected || generation !== state.generation || card.dataset.loaded === "1") return;
        card.dataset.loaded = "1";
        card.dataset.status = "loading";
        const mount = card.querySelector(".chart-mount");
        mount.innerHTML = '<div class="chart-placeholder">正在读取走势...</div>';
        try {
            const bounds = rangeTimestamps(state.range);
            const requestedLimit = state.range === "custom" ? Math.min(5000, Math.max(60, Math.ceil(Number(state.customDays || 1) * 1.8) + 30)) : 400;
            const params = new URLSearchParams({ code: card.dataset.code, from: String(bounds.from), to: String(bounds.to), limit: String(requestedLimit) });
            const payload = await apiFetch(`/api/market/index/bars?${params.toString()}`);
            if (!card.isConnected || generation !== state.generation) return;
            const pointLimit = state.range === "custom" ? Number(state.customDays) : RANGE_CONFIG[state.range].points;
            const data = selectOhlcBars(payload.bars, pointLimit);
            if (data.length < 2 || !window.LightweightCharts) throw new Error("该区间暂无足够行情");
            mount.textContent = "";
            const chart = window.LightweightCharts.createChart(mount, createChartOptions());
            const firstClose = Number(data[0].close);
            const lastClose = Number(data[data.length - 1].close);
            const change = firstClose ? (lastClose / firstClose - 1) * 100 : 0;
            const series = chart.addSeries(window.LightweightCharts.CandlestickSeries, {
                upColor: "#ef5350",
                downColor: "#26a69a",
                borderVisible: false,
                wickUpColor: "#ef5350",
                wickDownColor: "#26a69a",
                priceLineVisible: false,
                lastValueVisible: true,
            });
            series.setData(data);
            chart.timeScale().fitContent();
            state.charts.set(card.dataset.code, chart);
            const performance = card.querySelector(".sector-performance");
            card.dataset.return = String(change);
            performance.classList.add(change >= 0 ? "positive" : "negative");
            performance.querySelector("strong").textContent = `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
            card.dataset.status = "ready";
        } catch (error) {
            card.dataset.status = "error";
            if (card.isConnected && generation === state.generation) mount.innerHTML = `<div class="chart-error"></div>`;
            const errorNode = mount.querySelector(".chart-error");
            if (errorNode) errorNode.textContent = error.message || "走势读取失败";
        }
    }

    function renderSectors() {
        state.generation += 1;
        const generation = state.generation;
        destroyCharts();
        const grid = document.getElementById("sector-grid");
        grid.textContent = "";
        const items = filterSectorItems(state.allItems, state.prefix, state.keyword);
        document.getElementById("sector-count").textContent = `${PREFIX_LABELS[state.prefix]} ${items.length} 个`;
        const status = document.getElementById("sector-state");
        status.classList.remove("error");
        status.textContent = items.length
            ? state.stockFilterCode
                ? `${state.stockFilterCode} 在当前分类中属于 ${items.length} 个板块`
                : `共 ${items.length} 个板块，图表随页面滚动加载`
            : state.stockFilterCode
                ? `${state.stockFilterCode} 在当前分类中没有匹配板块`
                : "没有匹配的板块";
        const fragment = document.createDocumentFragment();
        items.forEach((item) => fragment.appendChild(createSectorCard(item)));
        grid.appendChild(fragment);
        const cards = Array.from(grid.querySelectorAll(".sector-card"));
        let framePending = false;
        const scheduleVisibleCards = () => {
            framePending = false;
            if (generation !== state.generation) return;
            const lowerBound = window.innerHeight + 360;
            cards.forEach((card) => {
                if (card.dataset.queued === "1") return;
                const rect = card.getBoundingClientRect();
                if (rect.bottom < -360 || rect.top > lowerBound) return;
                card.dataset.queued = "1";
                enqueueCard(card, generation);
            });
        };
        state.visibleCardScheduler = scheduleVisibleCards;
        state.scrollHandler = () => {
            if (framePending) return;
            framePending = true;
            window.requestAnimationFrame(scheduleVisibleCards);
        };
        window.addEventListener("scroll", state.scrollHandler, { passive: true });
        window.requestAnimationFrame(scheduleVisibleCards);
        if (state.sortActive) void loadReturnsAndSort(generation);
    }

    async function loadSectorList(forceRefresh = false) {
        const status = document.getElementById("sector-state");
        status.classList.remove("error");
        status.textContent = "正在读取板块清单...";
        try {
            const payload = await apiFetch(`/api/market/index-codes${forceRefresh ? "?refresh=1" : ""}`);
            state.allItems = Array.isArray(payload.items) ? payload.items : [];
            renderSectors();
        } catch (error) {
            status.classList.add("error");
            status.textContent = `板块清单读取失败：${error.message}`;
        }
    }

    function bindControls() {
        document.querySelectorAll("[data-prefix]").forEach((button) => button.addEventListener("click", () => {
            document.querySelectorAll("[data-prefix]").forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
            state.prefix = button.dataset.prefix;
            renderSectors();
            window.scrollTo({ top: 0, behavior: "smooth" });
        }));
        document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", () => {
            document.querySelectorAll("[data-range]").forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
            state.range = button.dataset.range;
            document.getElementById("custom-range-apply")?.parentElement.classList.remove("is-active");
            renderSectors();
        }));
        const customInput = document.getElementById("custom-range-days");
        const customApply = document.getElementById("custom-range-apply");
        const applyCustomRange = () => {
            const days = Number(customInput?.value);
            if (!Number.isInteger(days) || days < 1 || days > 2000) {
                document.getElementById("sector-state").textContent = "自定义天数请输入 1 到 2000 之间的整数";
                document.getElementById("sector-state").classList.add("error");
                customInput?.focus();
                return;
            }
            state.customDays = days;
            state.range = "custom";
            document.querySelectorAll("[data-range]").forEach((item) => item.classList.remove("active"));
            customApply?.parentElement.classList.add("is-active");
            renderSectors();
        };
        customApply?.addEventListener("click", applyCustomRange);
        customInput?.addEventListener("keydown", (event) => { if (event.key === "Enter") applyCustomRange(); });
        document.querySelectorAll("[data-sort]").forEach((button) => button.addEventListener("click", () => {
            state.sortOrder = button.dataset.sort === "asc" ? "asc" : "desc";
            state.sortActive = true;
            document.querySelectorAll("[data-sort]").forEach((item) => item.classList.toggle("active", item === button));
            void loadReturnsAndSort(state.generation);
        }));
        let searchTimer = null;
        document.getElementById("sector-search").addEventListener("input", (event) => {
            window.clearTimeout(searchTimer);
            searchTimer = window.setTimeout(() => { void applySearchQuery(event.target.value); }, 180);
        });
        document.addEventListener("click", (event) => {
            if (!event.target.closest(".sector-search")) closeSearchSuggestions();
        });
        document.getElementById("sector-search").addEventListener("keydown", (event) => {
            const suggestions = document.getElementById("sector-search-suggestions");
            const options = Array.from(suggestions?.querySelectorAll(".sector-search-option") || []);
            if (event.key === "Escape") {
                closeSearchSuggestions();
                return;
            }
            if (!suggestions?.classList.contains("is-open") || !options.length) return;
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                const current = Number(suggestions.dataset.activeIndex || -1);
                setActiveSearchOption(event.key === "ArrowDown" ? current + 1 : current - 1);
            } else if (event.key === "Enter") {
                event.preventDefault();
                const current = Number(suggestions.dataset.activeIndex || -1);
                options[current >= 0 ? current : 0]?.click();
            }
        });
        document.getElementById("refresh-sectors").addEventListener("click", () => loadSectorList(true));
    }

    function bindAutoCollapseControls() {
        const controls = document.querySelector(".control-band");
        if (!controls) return;
        state.lastScrollY = Math.max(0, window.scrollY);
        let framePending = false;
        const update = () => {
            framePending = false;
            const currentY = Math.max(0, window.scrollY);
            const delta = currentY - state.lastScrollY;
            const interacting = controls.contains(document.activeElement);
            if (currentY <= 100 || delta < -6 || interacting) controls.classList.remove("is-collapsed");
            else if (delta > 8 && currentY > 160) controls.classList.add("is-collapsed");
            state.lastScrollY = currentY;
        };
        state.controlScrollHandler = () => {
            if (framePending) return;
            framePending = true;
            window.requestAnimationFrame(update);
        };
        window.addEventListener("scroll", state.controlScrollHandler, { passive: true });
        controls.addEventListener("focusin", () => controls.classList.remove("is-collapsed"));
    }

    function updateClock() {
        document.getElementById("page-clock").textContent = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date());
    }

    document.addEventListener("DOMContentLoaded", () => {
        bindControls();
        bindAutoCollapseControls();
        document.getElementById("constituent-close")?.addEventListener("click", closeConstituentDialog);
        document.querySelector("[data-close-constituents]")?.addEventListener("click", closeConstituentDialog);
        document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeConstituentDialog(); });
        updateClock();
        window.setInterval(updateClock, 1000);
        loadSectorList();
    });

    window.SectorRotation = { filterSectorItems, isStockCodeQuery, applySearchQuery, bindAutoCollapseControls, rangeTimestamps, normalizedCloseSeries, selectOhlcBars, renderSectors, loadSectorList };
})();
