/* 信息页轻量 core：自选、换码、导航、布局（不含 K 线/因子/回测） */

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

(function () {
    "use strict";

    const PAGE_VIEW = String(window.PAGE_VIEW || "fundamental").trim().toLowerCase();
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

    function isMainBoardPage() {
        return Boolean(PAGE_VIEW_TO_FILE[PAGE_VIEW]);
    }

    function parsePortfolioBootOptions() {
        const sp = new URLSearchParams(window.location.search);
        const portfolioMode = sp.get("portfolio") === "1" || sp.get("result") === "1";
        const embedMode = sp.get("embed") === "1";
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
        return {
            portfolioMode,
            embedMode,
            allowYkrsCurve,
            code,
            lockCode: portfolioMode || sp.get("lock_code") === "1",
        };
    }

    const PAGE_BOOT = parsePortfolioBootOptions();

    if (window.BacktestRunContext) {
        BacktestRunContext.syncActiveRunFromUrl(new URLSearchParams(window.location.search));
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
                window.history.replaceState({}, "", `${u.pathname}${u.search}${u.hash}`);
            }
        } catch {
            /* ignore */
        }
    }
    scrubDisallowedYkrsFromLocation();

    const API_BASE_URL = resolveApiBaseUrl();
    const CODE_SUGGESTION_LIMIT = 5;
    const WATCHLIST_STORAGE_KEY = "quant_watchlist_v1";
    const WATCHLIST_SYNC_DEBOUNCE_MS = 800;
    const VIEW_STORAGE_KEY = "quant_last_view_v1";
    const INTERVAL_CONFIG = {
        "1min": {
            alignStepSeconds: 60,
            latestPriceLookbackSeconds: 30 * 24 * 60 * 60,
        },
        "1day": {
            alignStepSeconds: 24 * 60 * 60,
            latestPriceLookbackSeconds: 730 * 24 * 60 * 60,
        },
    };
    const API_READY_MAX_ATTEMPTS = 40;
    const API_READY_INTERVAL_MS = 500;

    const codeInput = document.getElementById("code-input");
    const intervalSelect = document.getElementById("interval-select");
    const codeSuggestions = document.getElementById("code-suggestions");
    const pageClock = document.getElementById("page-clock");
    const addWatchCurrentBtn = document.getElementById("btn-add-watch-current");
    const watchlistCards = document.getElementById("watchlist-cards");
    const mainLayout = document.getElementById("main-layout");
    const leftPanel = document.getElementById("left-panel");
    const rightPanel = document.getElementById("right-panel");
    const splitterLeft = document.getElementById("splitter-left");
    const splitterRight = document.getElementById("splitter-right");
    const headerTabsContainer = document.getElementById("header-tabs-container");

    let currentCode = codeInput ? codeInput.value.trim().toUpperCase() : "";
    let clearCodeInputOnNextEdit = false;
    let codeSuggestTimer = null;
    let codeSuggestItems = [];
    let activeSuggestionIndex = -1;
    let currentInterval = "1day";
    if (intervalSelect) {
        intervalSelect.value = currentInterval;
    }
    let isSwitchingCode = false;
    let isRequesting = false;
    let pendingSwitchCode = "";
    let watchlistCodes = [currentCode].filter(Boolean);
    let watchlistPriceMap = new Map();
    let selectedWatchCode = currentCode;
    let watchlistSyncTimer = null;
    let uiHintToastTimer = null;

    function isYkrsCode(codeValue = currentCode) {
        return String(codeValue || "").trim().toUpperCase().endsWith(".YKRS");
    }

    function isYkrsCurveDeniedOnThisSurface(codeValue = currentCode) {
        return isYkrsCode(codeValue) && !PAGE_BOOT.allowYkrsCurve;
    }

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function getIntervalConfig() {
        return INTERVAL_CONFIG[currentInterval] || INTERVAL_CONFIG["1day"];
    }

    function alignToCurrentInterval(tsSeconds) {
        const stepSeconds = getIntervalConfig().alignStepSeconds;
        return Math.floor(tsSeconds / stepSeconds) * stepSeconds;
    }

    function formatLocalDateTime(tsSeconds) {
        const dt = new Date(tsSeconds * 1000);
        const y = dt.getFullYear();
        const m = String(dt.getMonth() + 1).padStart(2, "0");
        const d = String(dt.getDate()).padStart(2, "0");
        const hh = String(dt.getHours()).padStart(2, "0");
        const mm = String(dt.getMinutes()).padStart(2, "0");
        const ss = String(dt.getSeconds()).padStart(2, "0");
        return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
    }

    function updatePageClock() {
        if (!pageClock) {
            return;
        }
        pageClock.textContent = `当前时间: ${formatLocalDateTime(Math.floor(Date.now() / 1000))}`;
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

    async function fetchApiHealthOnce(timeoutMs = 2500) {
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
        } catch {
            return false;
        } finally {
            clearTimeout(timer);
        }
    }

    async function waitForApiReady() {
        for (let attempt = 1; attempt <= API_READY_MAX_ATTEMPTS; attempt += 1) {
            if (await fetchApiHealthOnce()) {
                if (attempt > 1) {
                    logUiHint(`API 已就绪（${API_BASE_URL}）`);
                }
                return true;
            }
            if (attempt === 1 || attempt % 4 === 0) {
                logUiHint(`等待 API 就绪… (${attempt}/${API_READY_MAX_ATTEMPTS}) ${API_BASE_URL}`);
            }
            await new Promise((resolve) => setTimeout(resolve, API_READY_INTERVAL_MS));
        }
        logUiHint(
            "API 未响应：请用「可视化/start_api_server.bat」启动，并确保 8000 端口只有一个进程；"
            + "若刚重启过 API，请刷新本页或等待几秒后再试。",
        );
        return false;
    }

    function persistWatchlistState() {
        try {
            localStorage.setItem(
                WATCHLIST_STORAGE_KEY,
                JSON.stringify({ codes: watchlistCodes, selected: selectedWatchCode }),
            );
        } catch {
            /* ignore */
        }
        scheduleWatchlistRemoteSync();
    }

    function persistViewState() {
        try {
            localStorage.setItem(
                VIEW_STORAGE_KEY,
                JSON.stringify({
                    code: String(currentCode || "").trim().toUpperCase(),
                    interval: String(currentInterval || "").trim(),
                }),
            );
        } catch {
            /* ignore */
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
            if (!normalizedCodes.length) {
                return;
            }
            let codes = normalizedCodes;
            if (!PAGE_BOOT.allowYkrsCurve) {
                codes = normalizedCodes.filter((c) => !String(c || "").trim().toUpperCase().endsWith(".YKRS"));
            }
            if (!codes.length) {
                codes = ["301469.SZ"];
            }
            watchlistCodes = codes;
            const selected = String(parsed.selected || "").trim().toUpperCase();
            if (selected && watchlistCodes.includes(selected)) {
                selectedWatchCode = selected;
            } else if (watchlistCodes.length) {
                selectedWatchCode = watchlistCodes[0];
            }
            if (selectedWatchCode && codeInput) {
                codeInput.value = selectedWatchCode;
                currentCode = selectedWatchCode;
            }
        } catch {
            /* ignore */
        }
    }

    function restoreViewState() {
        try {
            const raw = localStorage.getItem(VIEW_STORAGE_KEY);
            if (!raw) {
                currentInterval = "1day";
                if (intervalSelect) {
                    intervalSelect.value = "1day";
                }
                if (selectedWatchCode && codeInput) {
                    currentCode = selectedWatchCode;
                    codeInput.value = selectedWatchCode;
                }
                return;
            }
            const parsed = JSON.parse(raw);
            const savedCode = String(parsed && parsed.code ? parsed.code : "").trim().toUpperCase();
            const savedInterval = String(parsed && parsed.interval ? parsed.interval : "").trim();
            if (savedInterval && Object.prototype.hasOwnProperty.call(INTERVAL_CONFIG, savedInterval)) {
                currentInterval = savedInterval;
                if (intervalSelect) {
                    intervalSelect.value = savedInterval;
                }
            } else {
                currentInterval = "1day";
                if (intervalSelect) {
                    intervalSelect.value = "1day";
                }
            }
            if (savedCode && !isYkrsCurveDeniedOnThisSurface(savedCode)) {
                currentCode = savedCode;
                if (codeInput) {
                    codeInput.value = savedCode;
                }
                if (watchlistCodes.includes(savedCode)) {
                    selectedWatchCode = savedCode;
                }
            } else if (selectedWatchCode && codeInput) {
                currentCode = selectedWatchCode;
                codeInput.value = selectedWatchCode;
            }
        } catch {
            currentInterval = "1day";
            if (intervalSelect) {
                intervalSelect.value = "1day";
            }
            if (selectedWatchCode && codeInput) {
                currentCode = selectedWatchCode;
                codeInput.value = selectedWatchCode;
            }
        }
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
        const selected = normalizedCodes.includes(selectedRaw) ? selectedRaw : (normalizedCodes[0] || "");
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
        const resp = await fetch(`${API_BASE_URL}/api/watchlist`, { method: "GET", cache: "no-store" });
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
            selected: selectedWatchCode,
        });
        const resp = await fetch(`${API_BASE_URL}/api/watchlist`, {
            method: "POST",
            cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!resp.ok) {
            throw new Error("自选股同步失败");
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
            if (selectedWatchCode && codeInput) {
                currentCode = selectedWatchCode;
                codeInput.value = selectedWatchCode;
            }
            try {
                localStorage.setItem(
                    WATCHLIST_STORAGE_KEY,
                    JSON.stringify({ codes: watchlistCodes, selected: selectedWatchCode }),
                );
            } catch {
                /* ignore */
            }
        } catch {
            /* 远端不可用时保持 localStorage */
        }
    }

    function isNoDataErrorResponse(status, body) {
        if (status !== 404) {
            return false;
        }
        const message = body && body.error && body.error.message ? String(body.error.message) : "";
        return message.includes("未找到对应股票数据") || message.includes("未找到对应分区");
    }

    async function fetchBars(code, fromTs, toTs, options = {}) {
        const { allowNotFound = false } = options;
        const params = new URLSearchParams({
            code,
            interval: currentInterval,
            from: String(fromTs),
            to: String(toTs),
            limit: "5000",
        });
        const resp = await fetch(`${API_BASE_URL}/api/market/bars?${params.toString()}`, {
            method: "GET",
            cache: "no-store",
        });
        const body = await resp.json();
        if (!resp.ok) {
            if (allowNotFound && isNoDataErrorResponse(resp.status, body)) {
                return { bars: [], meta: { code, from: fromTs, to: toTs, has_new_data: false, row_count: 0 } };
            }
            const message = body && body.error && body.error.message ? body.error.message : "接口请求失败";
            throw new Error(message);
        }
        return body;
    }

    async function fetchLatestPriceForCode(code) {
        const nowTs = alignToCurrentInterval(Math.floor(Date.now() / 1000));
        const fromTs = nowTs - getIntervalConfig().latestPriceLookbackSeconds;
        const payload = await fetchBars(code, fromTs, nowTs, { allowNotFound: true });
        const bars = Array.isArray(payload.bars) ? payload.bars : [];
        if (!bars.length) {
            return null;
        }
        const latest = bars[bars.length - 1];
        return {
            code,
            price: Number(latest.close),
            time: Number(latest.time),
        };
    }

    async function fetchCodeSuggestions(keyword) {
        const params = new URLSearchParams({
            q: keyword,
            interval: currentInterval,
            limit: String(CODE_SUGGESTION_LIMIT),
        });
        const resp = await fetch(`${API_BASE_URL}/api/market/codes/search?${params.toString()}`, {
            method: "GET",
            cache: "no-store",
        });
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
            })).filter((item) => item.code)
            : (Array.isArray(body.codes) ? body.codes : []).map((code) => ({
                code: String(code || "").trim().toUpperCase(),
                name: "",
            })).filter((item) => item.code);
        if (PAGE_BOOT.allowYkrsCurve) {
            return rawList;
        }
        return rawList.filter((item) => !item.code.endsWith(".YKRS"));
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
                if (codeInput) {
                    codeInput.value = code;
                }
                renderWatchlist();
                await switchCodeAndReload(code);
            });
            watchlistCards.appendChild(card);
        }
    }

    async function refreshWatchlistPrices() {
        const normalizedCurrent = String(currentCode || "").trim().toUpperCase();
        if (normalizedCurrent) {
            try {
                const data = await fetchLatestPriceForCode(normalizedCurrent);
                if (data) {
                    watchlistPriceMap.set(normalizedCurrent, data);
                }
            } catch {
                /* ignore */
            }
        }
        const tasks = watchlistCodes.map(async (code) => {
            const normalized = String(code || "").trim().toUpperCase();
            if (!normalized || (normalized === normalizedCurrent && watchlistPriceMap.has(normalized))) {
                return;
            }
            try {
                const data = await fetchLatestPriceForCode(code);
                if (data) {
                    watchlistPriceMap.set(code, data);
                }
            } catch {
                /* ignore */
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
                if (codeInput) {
                    codeInput.value = code;
                }
                hideCodeSuggestions();
                await switchCodeAndReload(code);
            });
            codeSuggestions.appendChild(li);
        }
        codeSuggestions.classList.add("show");
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
                renderCodeSuggestions(await fetchCodeSuggestions(raw));
            } catch {
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
        const raw = codeInput ? String(codeInput.value || "").trim().toUpperCase() : "";
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
        } catch {
            return isLikelyCompleteCode(raw) ? raw : "";
        }
    }

    function refreshSuggestionActiveStyle() {
        if (!codeSuggestions) {
            return;
        }
        codeSuggestions.querySelectorAll("li").forEach((item, index) => {
            item.classList.toggle("active", index === activeSuggestionIndex);
        });
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

    function isCodeInputTypingKeyBlocked() {
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

    function onGlobalCodeInputKeydown(event) {
        const key = event.key;
        if (
            isGlobalCodeInputTypingKey(key)
            && !event.ctrlKey
            && !event.metaKey
            && !event.altKey
            && !event.isComposing
            && !isCodeInputTypingKeyBlocked()
        ) {
            event.preventDefault();
            applyGlobalCodeInputTyping(key);
        }
    }

    async function switchCodeAndReload(nextCodeArg = null) {
        const nextCode = String(nextCodeArg ?? (codeInput ? codeInput.value : "")).trim().toUpperCase();
        if (!nextCode) {
            logUiHint("code 不能为空");
            return;
        }
        if (isYkrsCurveDeniedOnThisSurface(nextCode)) {
            logUiHint("组合回测曲线（代码以 .YKRS 结尾）仅在「组合结果」页（../组合结果/index.html）提供。");
            return;
        }
        if (isSwitchingCode || isRequesting) {
            pendingSwitchCode = nextCode;
            logUiHint(`正在刷新，已排队切换到 ${nextCode}`);
            return;
        }
        isSwitchingCode = true;
        try {
            if (codeInput) {
                codeInput.value = nextCode;
            }
            currentCode = nextCode;
            persistViewState();
            clearCodeInputOnNextEdit = true;
            selectedWatchCode = currentCode;
            renderWatchlist();
            if (window.ChartBoardView && typeof window.ChartBoardView.onCodeChange === "function") {
                await window.ChartBoardView.onCodeChange(currentCode);
            }
            await refreshWatchlistPrices();
        } finally {
            isSwitchingCode = false;
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
                const typed = String(codeInput?.value || currentCode || "").trim().toUpperCase();
                if (typed && !isYkrsCurveDeniedOnThisSurface(typed)) {
                    currentCode = typed;
                }
                persistViewState();
            });
        });
    }

    function initViewForCurrentPage() {
        if (!isMainBoardPage()) {
            return Promise.resolve();
        }
        if (window.ChartBoardView && typeof window.ChartBoardView.onCodeChange === "function") {
            return window.ChartBoardView.onCodeChange(currentCode);
        }
        if (window.ChartBoardView && typeof window.ChartBoardView.init === "function") {
            return Promise.resolve(window.ChartBoardView.init());
        }
        return Promise.resolve();
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

    function initInfoResizableLayout() {
        if (!mainLayout || !leftPanel || !rightPanel) {
            return;
        }
        const pageHeader = document.getElementById("page-header");
        const hideLeftPanel = PAGE_BOOT.portfolioMode;
        let leftWidth = hideLeftPanel ? 0 : (leftPanel.getBoundingClientRect().width || 220);
        let rightWidth = rightPanel.getBoundingClientRect().width || 280;

        const applyMainGridColumns = () => {
            const cols = hideLeftPanel
                ? `minmax(0, 1fr) 8px ${rightWidth}px`
                : `${leftWidth}px 8px minmax(0, 1fr) 8px ${rightWidth}px`;
            mainLayout.style.gridTemplateColumns = cols;
            if (pageHeader) {
                pageHeader.style.gridTemplateColumns = cols;
            }
        };

        applyMainGridColumns();

        const setDragStyle = (dragging, cursor) => {
            document.body.style.userSelect = dragging ? "none" : "";
            document.body.style.cursor = dragging ? cursor : "";
        };

        if (!hideLeftPanel && splitterLeft) {
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

        if (splitterRight) {
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
        }
    }

    function syncWatchlistSelectionToCurrentCode() {
        const code = String(currentCode || "").trim().toUpperCase();
        if (!code) {
            return;
        }
        if (watchlistCodes.includes(code)) {
            selectedWatchCode = code;
        }
        if (codeInput) {
            codeInput.value = code;
        }
        renderWatchlist();
    }

    if (codeInput) {
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
                    logUiHint("code 不能为空");
                    hideCodeSuggestions();
                    return;
                }
                codeInput.value = resolved;
                hideCodeSuggestions();
                await switchCodeAndReload(resolved);
            }
        });
        document.addEventListener("keydown", onGlobalCodeInputKeydown);
    }

    if (addWatchCurrentBtn) {
        addWatchCurrentBtn.addEventListener("click", async () => {
            const code = String(currentCode || "").trim().toUpperCase();
            if (!code) {
                return;
            }
            if (isYkrsCurveDeniedOnThisSurface(code)) {
                logUiHint("组合回测曲线（.YKRS）不能加入主站自选。");
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
        if (!codeSuggestions || !codeInput) {
            return;
        }
        if (!codeSuggestions.contains(event.target) && event.target !== codeInput) {
            hideCodeSuggestions();
        }
    });

    window.ChartBoardBoot = async function ChartBoardBoot() {
        await waitForApiReady();
        initInfoResizableLayout();
        if (isMainBoardPage()) {
            bindMainBoardNavLinks();
        }
        if (!PAGE_BOOT.embedMode && typeof initEdgeFloatHud === "function") {
            initEdgeFloatHud({ pageId: "chart", onNavigate: edgeFloatNavigateToPage });
        }
        restoreWatchlistState();
        await hydrateWatchlistFromServer();

        if (PAGE_BOOT.code && codeInput) {
            currentCode = PAGE_BOOT.code;
            codeInput.value = PAGE_BOOT.code;
            selectedWatchCode = PAGE_BOOT.code;
            if (!watchlistCodes.includes(PAGE_BOOT.code)) {
                watchlistCodes.unshift(PAGE_BOOT.code);
            }
        } else {
            restoreViewState();
        }

        syncWatchlistSelectionToCurrentCode();
        renderWatchlist();
        updatePageClock();
        setInterval(updatePageClock, 1000);
        await refreshWatchlistPrices();
        if (isMainBoardPage()) {
            await initViewForCurrentPage();
        }
    };
})();
