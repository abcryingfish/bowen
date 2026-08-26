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
    const state = { prefix: "881", range: "60d", customDays: null, keyword: "", stockFilterCode: "", stockSectorCodes: null, searchRequestId: 0, sortMode: "model", sortOrder: "desc", sortActive: false, modelSortActive: true, modelSortPeriod: "ultra_short", modelSortEvent: "valley_bullish", sortRequestId: 0, allItems: [], modelSignalByCode: new Map(), modelHistoryByCode: new Map(), modelHistoryPromises: new Map(), modelDiagnosticsByCode: new Map(), modelSignalRequestId: 0, generation: 0, pendingControllers: new Set(), globalEventRow: null, globalEventSignal: null, globalEventCloseTimer: null, globalEventRequestId: 0, scrollHandler: null, visibleCardScheduler: null, constituentObserver: null, constituentChart: null, constituentSeries: null, constituentBollingerSeries: null, constituentBars: [], constituentCode: "", constituentChartRequestId: 0, constituentHistoryLoading: false, constituentHistoryExhausted: false, constituentFirstAvailableTime: null, controlScrollHandler: null, lastScrollY: 0, charts: new Map(), fundShareBySector: new Map(), fundSharePromise: null, queue: [], activeRequests: 0 };
    const MAX_CONCURRENT_REQUESTS = 4;
    const CONSTITUENT_INITIAL_HISTORY_DAYS = 365 * 3;
    const CONSTITUENT_HISTORY_BATCH_DAYS = 365 * 6;

    async function apiFetch(path, options = {}) {
        const timeoutMs = Math.max(0, Number(options.timeoutMs) || 0);
        const controller = new AbortController();
        let timeoutTriggered = false;
        const timer = timeoutMs ? window.setTimeout(() => { timeoutTriggered = true; controller.abort(); }, timeoutMs) : null;
        state.pendingControllers.add(controller);
        try {
            const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", signal: controller.signal });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
            return payload;
        } catch (error) {
            if (controller.signal.aborted) {
                const abortError = new Error(timeoutTriggered ? `请求超过 ${Math.round(timeoutMs / 1000)} 秒，请检查 API 服务后重试` : "请求已取消");
                abortError.name = "AbortError";
                throw abortError;
            }
            throw error;
        } finally {
            if (timer !== null) window.clearTimeout(timer);
            state.pendingControllers.delete(controller);
        }
    }

    function cancelPendingRequests() {
        state.pendingControllers.forEach((controller) => controller.abort());
        state.pendingControllers.clear();
        state.globalEventRequestId += 1;
        closeGlobalModelEventDetail();
    }

    function isAbortError(error) {
        return error?.name === "AbortError" || /请求已取消/.test(String(error?.message || ""));
    }

    const MODEL_PERIODS = [
        ["ultra_short", "超短", "3日内"],
        ["5d", "短期", "5天"],
        ["20d", "中期", "20天"],
    ];
    const MODEL_EVENTS = [
        ["valley_bullish", "波谷看涨"],
        ["peak_bearish", "波峰看跌"],
        ["two_sided_high_volatility", "双向高波"],
        ["sideways_bullish", "横盘看涨"],
        ["sideways_bearish", "横盘看跌"],
    ];
    const TECHNICAL_SUBGROUPS = ["ADX", "AMA", "APO", "AROON", "BOLL", "CCI", "CMO", "DEMA", "MACD", "MFI", "MOM", "PPO", "ROC", "RSI", "STOCH", "ULTOSC", "WILLR", "WMA"];

    function formatModelPercent(value) {
        const number = Number(value);
        return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "--";
    }

    function formatModelNumber(value) {
        const number = Number(value);
        return Number.isFinite(number) ? number.toFixed(4) : "--";
    }

    function sectorCodeKeys(value) {
        const raw = String(value || "").trim().toUpperCase();
        if (!raw) return [];
        const base = raw.split(".", 1)[0];
        return base && base !== raw ? [raw, base] : [raw];
    }

    function modelStateLabel(item, period) {
        const raw = String(item?.[`${period}_most_likely_state`] || "").trim();
        const knownLabels = new Set(MODEL_EVENTS.map(([, name]) => name));
        if (knownLabels.has(raw)) return raw;
        let bestName = "模型信号";
        let bestProbability = -Infinity;
        MODEL_EVENTS.forEach(([event, name]) => {
            const probability = Number(item?.[`${period}_prob_${event}`]);
            if (Number.isFinite(probability) && probability > bestProbability) {
                bestProbability = probability;
                bestName = name;
            }
        });
        return bestName;
    }

    const MODEL_GROUP_LABELS = {
        technical: "技术面",
        sideways_volatility: "横盘波动",
        relative_strength: "相对强弱",
        constituent_breadth: "成分广度",
        leader_diffusion: "龙头扩散",
        market_state_conditioned: "市场状态",
    };

    function modelEventDirection(event) {
        if (event === "valley_bullish" || event === "sideways_bullish") return "看涨";
        if (event === "peak_bearish" || event === "sideways_bearish") return "看跌";
        return "双向高波动";
    }

    function modelEventSide(event) {
        if (event === "valley_bullish" || event === "sideways_bullish") return "valley";
        if (event === "peak_bearish" || event === "sideways_bearish") return "peak";
        return null;
    }

    function renderModelEventDetail(detail, item, diagnostics, period, event) {
        const probability = Number(item?.[`${period}_prob_${event}`]);
        const side = modelEventSide(event);
        const groups = ["technical", "sideways_volatility", "relative_strength", "constituent_breadth", "leader_diffusion", "market_state_conditioned"];
        const values = groups.map((group) => {
            if (side) return { group, value: Number(diagnostics?.[`contrib_${group}_delta_${side}_${period}`]) };
            return {
                group,
                peak: Number(diagnostics?.[`contrib_${group}_delta_peak_${period}`]),
                valley: Number(diagnostics?.[`contrib_${group}_delta_valley_${period}`]),
            };
        });
        const magnitudes = values.map((entry) => side ? Math.abs(entry.value) : Math.abs(entry.peak || 0) + Math.abs(entry.valley || 0));
        const totalMagnitude = magnitudes.reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0);
        const rows = values.map((entry, index) => {
            const magnitude = magnitudes[index];
            const share = totalMagnitude > 0 ? magnitude / totalMagnitude : NaN;
            const contribution = side ? (Number.isFinite(entry.value) ? formatModelNumber(entry.value) : "--") : `峰 ${Number.isFinite(entry.peak) ? formatModelNumber(entry.peak) : "--"} / 谷 ${Number.isFinite(entry.valley) ? formatModelNumber(entry.valley) : "--"}`;
            return `<div><span>${MODEL_GROUP_LABELS[entry.group]}</span><strong>${contribution} · ${formatModelPercent(share)}</strong></div>`;
        }).join("");
        detail.innerHTML = `<div class="sector-signal-event-summary"><span>事件权重</span><strong>${formatModelPercent(probability)} · ${modelEventDirection(event)}</strong></div><small>构成占比（按贡献绝对值归一化）</small><div class="sector-signal-event-contributions">${rows}</div>`;
    }

    function globalModelEventDetailNode() {
        return document.getElementById("sector-global-event-detail");
    }

    function positionGlobalModelEventDetail(row) {
        const detail = globalModelEventDetailNode();
        if (!detail || !row) return;
        const rect = row.getBoundingClientRect();
        const margin = 12;
        const width = Math.min(360, Math.max(240, window.innerWidth - margin * 2));
        detail.style.width = `${width}px`;
        let left = rect.right - width;
        left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
        detail.style.left = `${left}px`;
        detail.style.top = `${Math.max(margin, rect.bottom + 6)}px`;
    }

    function closeGlobalModelEventDetail() {
        if (state.globalEventCloseTimer) window.clearTimeout(state.globalEventCloseTimer);
        state.globalEventCloseTimer = null;
        state.globalEventRow = null;
        state.globalEventSignal = null;
        const detail = globalModelEventDetailNode();
        if (!detail) return;
        detail.classList.remove("is-open", "is-loading");
        detail.setAttribute("aria-hidden", "true");
        detail.textContent = "";
    }

    function bindGlobalModelEventDetail() {
        const detail = globalModelEventDetailNode();
        if (!detail || detail.dataset.bound === "1") return;
        detail.dataset.bound = "1";
        detail.addEventListener("mouseenter", () => {
            if (state.globalEventCloseTimer) window.clearTimeout(state.globalEventCloseTimer);
            state.globalEventSignal?.classList.add("is-hovered");
        });
        detail.addEventListener("mouseleave", scheduleGlobalModelEventDetailClose);
        window.addEventListener("scroll", () => {
            if (detail.classList.contains("is-open") && state.globalEventRow) positionGlobalModelEventDetail(state.globalEventRow);
        }, { passive: true });
    }

    function scheduleGlobalModelEventDetailClose() {
        if (state.globalEventCloseTimer) window.clearTimeout(state.globalEventCloseTimer);
        state.globalEventCloseTimer = window.setTimeout(() => {
            const detail = globalModelEventDetailNode();
            if (state.globalEventRow?.matches(":hover") || state.globalEventSignal?.matches(":hover") || detail?.matches(":hover")) return;
            closeGlobalModelEventDetail();
        }, 180);
    }

    async function loadModelEventDetail(row) {
        const signal = row?.closest(".sector-signal");
        const card = row?.closest(".sector-card");
        const detail = globalModelEventDetailNode();
        const period = row?.closest(".sector-signal-popover-period")?.dataset.period;
        const event = row?.dataset.event;
        const code = card?.dataset.code;
        if (!signal || !detail || !period || !event || !code) return;
        if (state.globalEventCloseTimer) window.clearTimeout(state.globalEventCloseTimer);
        state.globalEventRow = row;
        state.globalEventSignal = signal;
        state.globalEventRequestId += 1;
        const requestId = state.globalEventRequestId;
        signal.classList.add("is-hovered");
        detail.classList.add("is-open", "is-loading");
        detail.setAttribute("aria-hidden", "false");
        detail.textContent = "正在读取构成...";
        positionGlobalModelEventDetail(row);
        try {
            const codeKey = String(code).toUpperCase();
            const item = state.modelSignalByCode.get(codeKey);
            if (!item) return;
            let diagnostics = state.modelDiagnosticsByCode.get(codeKey);
            if (!diagnostics) {
                const payload = await apiFetch(`/api/market/sector-model-signals?${new URLSearchParams({ sector_code: code, include_diagnostics: "1" }).toString()}`);
                diagnostics = payload.data?.diagnostics || {};
                state.modelDiagnosticsByCode.set(codeKey, diagnostics);
            }
            if (requestId !== state.globalEventRequestId || state.globalEventRow !== row) return;
            renderModelEventDetail(detail, item, diagnostics, period, event);
            positionGlobalModelEventDetail(row);
        } catch (error) {
            if (requestId === state.globalEventRequestId && error.name !== "AbortError") detail.textContent = `构成读取失败：${error.message}`;
        } finally {
            if (requestId === state.globalEventRequestId) detail.classList.remove("is-loading");
        }
    }

    async function loadSectorModelSignals(prefix, generation) {
        const requestId = ++state.modelSignalRequestId;
        try {
            let payload;
            try {
                payload = await apiFetch(`/api/market/sector-model-signals?prefix=${encodeURIComponent(prefix)}`);
            } catch (error) {
                // 浏览器可能保留旧的 API_BASE_URL；模型信号固定从本机 8000 服务重试一次。
                if (API_BASE === "http://127.0.0.1:8000" || API_BASE === "http://localhost:8000") throw error;
                const response = await fetch(`http://127.0.0.1:8000/api/market/sector-model-signals?prefix=${encodeURIComponent(prefix)}`, { cache: "no-store" });
                payload = await response.json();
                if (!response.ok) throw error;
            }
            if (requestId !== state.modelSignalRequestId || generation !== state.generation) return;
            const items = Array.isArray(payload.data?.items) ? payload.data.items : (Array.isArray(payload.items) ? payload.items : []);
            state.modelSignalByCode = new Map();
            items.forEach((item) => sectorCodeKeys(item.htsc_code || item.code).forEach((key) => state.modelSignalByCode.set(key, item)));
            document.querySelectorAll("#sector-grid .sector-card").forEach((card) => updateModelSignalCard(card));
            const latestTime = payload.data?.latest_time || "未知日期";
            const loadedCount = state.modelSignalByCode.size;
            document.getElementById("sector-state").textContent = `峰谷模型已加载：${latestTime}，${loadedCount} 个板块`;
            if (state.modelSortActive) sortCardsByModelSignal();
        } catch (error) {
            if (generation === state.generation && !isAbortError(error)) document.getElementById("sector-state").textContent = `模型信号读取失败：${error.message}`;
        }
    }

    function updateModelSignalCard(card, itemOverride = null) {
        const signal = card?.querySelector(".sector-signal");
        const item = itemOverride || sectorCodeKeys(card?.dataset.code).map((key) => state.modelSignalByCode.get(key)).find(Boolean);
        if (!signal || !item) return;
        const caption = signal.querySelector(".sector-signal-caption");
        if (caption) caption.textContent = `峰谷模型 · ${String(item.time || "").slice(0, 10) || "最新"} · 概率`;
        const ariaParts = [];
        MODEL_PERIODS.forEach(([period, label, horizon]) => {
            const stateName = modelStateLabel(item, period);
            const strength = formatModelPercent(item[`${period}_event_strength`]);
            const valleyProbability = Number(item[`${period}_prob_valley_bullish`]);
            const peakProbability = Number(item[`${period}_prob_peak_bearish`]);
            const bullish = valleyProbability >= peakProbability;
            const periodNode = signal.querySelector(`.sector-signal-period[data-period="${period}"]`);
            if (periodNode) {
                periodNode.classList.toggle("bullish", bullish);
                periodNode.classList.toggle("bearish", !bullish);
                periodNode.querySelector("strong").textContent = stateName;
                periodNode.querySelector(".sector-signal-period-strength").textContent = `概率 ${strength}`;
            }
            const popover = signal.querySelector(`.sector-signal-popover-period[data-period="${period}"]`);
            if (popover) {
                MODEL_EVENTS.forEach(([code, name], index) => {
                    const row = popover.querySelectorAll(".sector-signal-events > div")[index];
                    if (!row) return;
                    row.querySelector("span").textContent = name;
                    row.dataset.event = code;
                    row.querySelector("strong").textContent = formatModelPercent(item[`${period}_prob_${code}`]);
                });
            }
            ariaParts.push(`${label}${horizon}${stateName}${strength}`);
        });
        signal.setAttribute("aria-label", `峰谷模型信号：${ariaParts.join("；")}`);
    }

    function clearModelSignalCard(card, dateKey = "") {
        const signal = card?.querySelector(".sector-signal");
        if (!signal) return;
        signal.querySelectorAll(".sector-signal-period").forEach((periodNode) => {
            periodNode.classList.remove("bullish", "bearish");
            periodNode.querySelector("strong").textContent = "--";
            periodNode.querySelector(".sector-signal-period-strength").textContent = "--";
        });
        signal.querySelectorAll(".sector-signal-events > div").forEach((row) => { row.querySelector("strong").textContent = "--"; });
        const caption = signal.querySelector(".sector-signal-caption");
        if (caption) caption.textContent = dateKey ? `峰谷模型 · ${dateKey} · 暂无数据` : "峰谷模型 · 概率";
        signal.setAttribute("aria-label", dateKey ? `峰谷模型信号：${dateKey}暂无数据` : "峰谷模型信号");
    }

    function chartTimeKey(time) {
        if (time === null || time === undefined) return "";
        if (typeof time === "string") return /^\d{4}-\d{2}-\d{2}$/.test(time) ? time : String(time).slice(0, 10);
        if (typeof time === "object" && Number.isFinite(Number(time.year))) {
            return `${String(time.year).padStart(4, "0")}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}`;
        }
        const timestamp = Number(time);
        if (!Number.isFinite(timestamp)) return "";
        const date = new Date(timestamp * 1000);
        return date.toISOString().slice(0, 10);
    }

    async function loadModelHistoryForCard(code, limit = 400) {
        const codeKey = String(code || "").toUpperCase();
        if (!codeKey) return null;
        if (state.modelHistoryByCode.has(codeKey)) return state.modelHistoryByCode.get(codeKey);
        if (state.modelHistoryPromises.has(codeKey)) return state.modelHistoryPromises.get(codeKey);
        const promise = apiFetch(`/api/market/sector-model-signal-history?${new URLSearchParams({ sector_code: codeKey, limit: String(Math.max(60, Math.min(2000, Number(limit) || 400))) }).toString()}`)
            .then((payload) => {
                const rows = Array.isArray(payload.data?.items) ? payload.data.items : [];
                const history = new Map(rows.map((row) => [String(row.time || "").slice(0, 10), row]));
                state.modelHistoryByCode.set(codeKey, history);
                return history;
            })
            .finally(() => state.modelHistoryPromises.delete(codeKey));
        state.modelHistoryPromises.set(codeKey, promise);
        return promise;
    }

    async function updateModelSignalForChartDate(card, dateKey) {
        const code = String(card?.dataset.code || "").toUpperCase();
        if (!code || !dateKey) return;
        if (card.dataset.modelHoverDate === dateKey && card.dataset.modelHoverRendered === "1") return;
        card.dataset.modelHoverDate = dateKey;
        card.dataset.modelHoverRendered = "0";
        try {
            // 图表区间可能跨越模型最新日期；保留足够历史行，不能只取当前K线点数的末尾。
            const history = await loadModelHistoryForCard(code, 400);
            if (card.dataset.modelHoverDate !== dateKey || !card.isConnected) return;
            const item = history?.get(dateKey);
            if (item) updateModelSignalCard(card, item);
            else clearModelSignalCard(card, dateKey);
            card.dataset.modelHoverRendered = "1";
        } catch (error) {
            if (!isAbortError(error)) card.dataset.modelHistoryError = error.message || "历史模型信号读取失败";
        }
    }

    function bindChartModelSignalHover(card, chart) {
        chart.subscribeCrosshairMove((param) => {
            const dateKey = chartTimeKey(param?.time);
            if (!dateKey) {
                delete card.dataset.modelHoverDate;
                delete card.dataset.modelHoverRendered;
                delete card.dataset.modelHistoryError;
                updateModelSignalCard(card);
                return;
            }
            void updateModelSignalForChartDate(card, dateKey);
        });
    }

    function restoreLatestModelSignal(card) {
        if (!card) return;
        delete card.dataset.modelHoverDate;
        delete card.dataset.modelHoverRendered;
        delete card.dataset.modelHistoryError;
        updateModelSignalCard(card);
    }

    function closeModelSignalDialog() {
        const dialog = document.getElementById("model-signal-dialog");
        if (!dialog) return;
        dialog.classList.remove("is-open");
        dialog.setAttribute("aria-hidden", "true");
    }

    function renderModelSignalTable(title, rows, columns) {
        const head = columns.map((column) => `<th>${column.label}</th>`).join("");
        const body = rows.map((row) => `<tr><td>${row.label}</td>${columns.map((column) => `<td>${column.format(row[column.key])}</td>`).join("")}</tr>`).join("");
        return `<section class="model-signal-section"><h3>${title}</h3><div class="model-signal-table-wrap"><table class="model-signal-table"><thead><tr><th>项目</th>${head}</tr></thead><tbody>${body}</tbody></table></div></section>`;
    }

    async function openModelSignalDialog(code) {
        const dialog = document.getElementById("model-signal-dialog");
        const content = document.getElementById("model-signal-content");
        const status = document.getElementById("model-signal-state");
        if (!dialog || !content || !status) return;
        dialog.classList.add("is-open");
        dialog.setAttribute("aria-hidden", "false");
        status.classList.remove("error");
        status.textContent = "正在读取峰谷模型诊断...";
        content.textContent = "";
        try {
            const params = new URLSearchParams({ sector_code: code, include_diagnostics: "1", include_history: "1", history_limit: "120" });
            const payload = await apiFetch(`/api/market/sector-model-signals?${params.toString()}`);
            const item = payload.data?.items?.[0];
            const diagnostics = payload.data?.diagnostics || {};
            const history = payload.data?.history || [];
            if (!item) throw new Error("没有找到该板块的模型信号");
            document.getElementById("model-signal-title").textContent = `${code} · 峰谷模型信号`;
            document.getElementById("model-signal-meta").textContent = `信号日期：${item.time || "--"}`;
        const periodHtml = MODEL_PERIODS.map(([period, label, horizon]) => `<section class="model-signal-period"><h3>${label}（${horizon}）</h3><div class="model-signal-probs">${MODEL_EVENTS.map(([event, name]) => `<div class="model-signal-prob"><span>${name}</span><strong>${formatModelPercent(item[`${period}_prob_${event}`])}</strong></div>`).join("")}</div><div class="model-signal-metrics"><div class="model-signal-metric"><span>最大事件</span><strong>${modelStateLabel(item, period)}</strong></div><div class="model-signal-metric"><span>事件强度</span><strong>${formatModelPercent(item[`${period}_event_strength`])}</strong></div><div class="model-signal-metric"><span>方向强度</span><strong>${formatModelNumber(diagnostics[`direction_strength_${period}`])}</strong></div></div></section>`).join("");
            const targetRows = TARGETS_FOR_MODEL().map((target) => ({ label: target, score: diagnostics[`pred_${target}`], peak: diagnostics[`peak_rank_${target.split("_").slice(-1)[0]}`] }));
            const groupRows = GROUPS_FOR_MODEL().map((group) => ({ label: MODEL_GROUP_LABELS[group] || group, ultraPeak: diagnostics[`score_${group}_delta_peak_ultra_short`], ultraValley: diagnostics[`score_${group}_delta_valley_ultra_short`], shortPeak: diagnostics[`score_${group}_delta_peak_5d`], shortValley: diagnostics[`score_${group}_delta_valley_5d`], midPeak: diagnostics[`score_${group}_delta_peak_20d`], midValley: diagnostics[`score_${group}_delta_valley_20d`] }));
            const contributionRows = GROUPS_FOR_MODEL().map((group) => ({ label: MODEL_GROUP_LABELS[group] || group, ultraPeak: diagnostics[`contrib_${group}_delta_peak_ultra_short`], ultraValley: diagnostics[`contrib_${group}_delta_valley_ultra_short`], shortPeak: diagnostics[`contrib_${group}_delta_peak_5d`], shortValley: diagnostics[`contrib_${group}_delta_valley_5d`], midPeak: diagnostics[`contrib_${group}_delta_peak_20d`], midValley: diagnostics[`contrib_${group}_delta_valley_20d`] }));
            const historyHtml = history.slice(-30).reverse().map((row) => `<div class="model-signal-history-card"><span>${row.time}</span><strong>${modelStateLabel(row, "ultra_short")} · ${formatModelPercent(row.ultra_short_event_strength)}</strong><span>方向强度 ${formatModelNumber(row.direction_strength_ultra_short)}</span></div>`).join("");
            const scoreColumns = [{ key: "ultraPeak", label: "超短波峰", format: formatModelNumber }, { key: "ultraValley", label: "超短波谷", format: formatModelNumber }, { key: "shortPeak", label: "短期波峰", format: formatModelNumber }, { key: "shortValley", label: "短期波谷", format: formatModelNumber }, { key: "midPeak", label: "中期波峰", format: formatModelNumber }, { key: "midValley", label: "中期波谷", format: formatModelNumber }];
            content.innerHTML = `${periodHtml}${renderModelSignalTable("六个连续波峰/波谷预测分", TARGET_ROWS(diagnostics), [{ key: "ultra", label: "超短", format: formatModelNumber }, { key: "short", label: "短期", format: formatModelNumber }, { key: "mid", label: "中期", format: formatModelNumber }])}${renderModelSignalTable("六组因子评分", groupRows, scoreColumns)}${renderModelSignalTable("各组顶层预测贡献", contributionRows, scoreColumns)}${renderModelSignalTable("18个技术子组评分", TECHNICAL_ROWS(diagnostics), scoreColumns)}<section class="model-signal-section"><h3>历史方向和强度（最近30个交易日）</h3><div class="model-signal-history">${historyHtml || "暂无历史记录"}</div></section>`;
            status.textContent = `已加载 ${history.length} 条历史信号；技术子组评分保存在诊断文件中。`;
        } catch (error) {
            status.classList.add("error");
            status.textContent = `模型信号读取失败：${error.message}`;
        }
    }

    function GROUPS_FOR_MODEL() { return ["technical", "sideways_volatility", "relative_strength", "constituent_breadth", "leader_diffusion", "market_state_conditioned"]; }
    function TARGETS_FOR_MODEL() { return ["delta_peak_ultra_short", "delta_valley_ultra_short", "delta_peak_5d", "delta_valley_5d", "delta_peak_20d", "delta_valley_20d"]; }
    function TARGET_ROWS(diagnostics) {
        return [
            { label: "波峰预测分", ultra: diagnostics.pred_delta_peak_ultra_short, short: diagnostics.pred_delta_peak_5d, mid: diagnostics.pred_delta_peak_20d },
            { label: "波谷预测分", ultra: diagnostics.pred_delta_valley_ultra_short, short: diagnostics.pred_delta_valley_5d, mid: diagnostics.pred_delta_valley_20d },
        ];
    }

    function TECHNICAL_ROWS(diagnostics) {
        return TECHNICAL_SUBGROUPS.map((indicator) => ({
            label: indicator,
            ultraPeak: diagnostics[`score_${indicator}_delta_peak_ultra_short`],
            ultraValley: diagnostics[`score_${indicator}_delta_valley_ultra_short`],
            shortPeak: diagnostics[`score_${indicator}_delta_peak_5d`],
            shortValley: diagnostics[`score_${indicator}_delta_valley_5d`],
            midPeak: diagnostics[`score_${indicator}_delta_peak_20d`],
            midValley: diagnostics[`score_${indicator}_delta_valley_20d`],
        }));
    }

    function closeConstituentDialog() {
        const dialog = document.getElementById("constituent-dialog");
        if (!dialog) return;
        dialog.classList.remove("is-open");
        dialog.setAttribute("aria-hidden", "true");
        state.constituentObserver?.disconnect();
        state.constituentObserver = null;
        destroyConstituentChart();
    }

    function destroyConstituentChart() {
        state.constituentChartRequestId += 1;
        state.constituentChart?.remove();
        state.constituentChart = null;
        state.constituentSeries = null;
        state.constituentBollingerSeries = null;
        state.constituentBars = [];
        state.constituentCode = "";
        state.constituentHistoryLoading = false;
        state.constituentHistoryExhausted = false;
        state.constituentFirstAvailableTime = null;
        const mount = document.getElementById("constituent-chart");
        if (mount) mount.textContent = "";
    }

    function mergeConstituentBars(incoming) {
        const merged = new Map(state.constituentBars.map((bar) => [bar.time, bar]));
        selectOhlcBars(incoming).forEach((bar) => merged.set(bar.time, bar));
        state.constituentBars = Array.from(merged.values()).sort((left, right) => left.time - right.time);
    }

    function calculateConstituentBollingerBands(bars, period = 20, deviationMultiplier = 2) {
        const upper = [];
        const middle = [];
        const lower = [];
        const window = [];
        let sum = 0;
        let sumSquares = 0;
        (Array.isArray(bars) ? bars : []).forEach((bar) => {
            const close = Number(bar.close);
            if (!Number.isFinite(close)) return;
            window.push(close);
            sum += close;
            sumSquares += close * close;
            if (window.length > period) {
                const removed = window.shift();
                sum -= removed;
                sumSquares -= removed * removed;
            }
            const mean = sum / window.length;
            const variance = Math.max(0, sumSquares / window.length - mean * mean);
            const deviation = Math.sqrt(variance) * deviationMultiplier;
            middle.push({ time: bar.time, value: mean });
            upper.push({ time: bar.time, value: mean + deviation });
            lower.push({ time: bar.time, value: mean - deviation });
        });
        return { upper, middle, lower };
    }

    function renderConstituentChartData() {
        state.constituentSeries?.setData(state.constituentBars);
        if (!state.constituentBollingerSeries) return;
        const bands = calculateConstituentBollingerBands(state.constituentBars);
        state.constituentBollingerSeries.upper.setData(bands.upper);
        state.constituentBollingerSeries.middle.setData(bands.middle);
        state.constituentBollingerSeries.lower.setData(bands.lower);
    }

    function lockConstituentHistoryLeftEdge() {
        state.constituentHistoryExhausted = true;
        const timeScale = state.constituentChart?.timeScale();
        if (!timeScale) return;
        timeScale.applyOptions({ fixLeftEdge: true });
        const logicalRange = timeScale.getVisibleLogicalRange();
        if (logicalRange && logicalRange.from < 0) {
            const span = Math.max(1, logicalRange.to - logicalRange.from);
            timeScale.setVisibleLogicalRange({ from: 0, to: span });
        }
    }

    async function loadOlderConstituentBars(requestId) {
        if (
            requestId !== state.constituentChartRequestId
            || state.constituentHistoryLoading
            || state.constituentHistoryExhausted
            || !state.constituentBars.length
        ) return;
        const oldestTime = state.constituentBars[0].time;
        if (Number.isFinite(state.constituentFirstAvailableTime) && oldestTime <= state.constituentFirstAvailableTime) {
            lockConstituentHistoryLeftEdge();
            return;
        }
        state.constituentHistoryLoading = true;
        const to = oldestTime - 86400;
        const from = Math.max(0, to - CONSTITUENT_HISTORY_BATCH_DAYS * 86400);
        try {
            const params = new URLSearchParams({ code: state.constituentCode, from: String(from), to: String(to), limit: "5000" });
            const payload = await apiFetch(`/api/market/index/bars?${params.toString()}`, { timeoutMs: 20000 });
            if (requestId !== state.constituentChartRequestId || !state.constituentChart || !state.constituentSeries) return;
            const incoming = selectOhlcBars(payload.bars);
            if (!incoming.length) {
                lockConstituentHistoryLeftEdge();
                return;
            }
            const visibleRange = state.constituentChart.timeScale().getVisibleRange();
            const previousOldest = state.constituentBars[0].time;
            mergeConstituentBars(incoming);
            renderConstituentChartData();
            if (visibleRange) state.constituentChart.timeScale().setVisibleRange(visibleRange);
            if (state.constituentBars[0].time >= previousOldest) lockConstituentHistoryLeftEdge();
            if (Number.isFinite(state.constituentFirstAvailableTime) && state.constituentBars[0].time <= state.constituentFirstAvailableTime) {
                lockConstituentHistoryLeftEdge();
            }
        } catch (_) {
            // 单批历史读取失败时允许用户再次向左拖动重试。
        } finally {
            if (requestId === state.constituentChartRequestId) state.constituentHistoryLoading = false;
        }
    }

    async function loadConstituentHistoryChart(code) {
        destroyConstituentChart();
        const requestId = state.constituentChartRequestId;
        const mount = document.getElementById("constituent-chart");
        const chartState = document.getElementById("constituent-chart-state");
        if (!mount || !chartState) return;
        chartState.className = "constituent-chart-state";
        chartState.textContent = "正在读取板块历史行情...";
        state.constituentCode = code;
        try {
            const to = Math.floor(Date.now() / 1000);
            const from = to - CONSTITUENT_INITIAL_HISTORY_DAYS * 86400;
            const params = new URLSearchParams({ code, from: String(from), to: String(to), limit: "320" });
            const payload = await apiFetch(`/api/market/index/bars?${params.toString()}`, { timeoutMs: 20000 });
            if (requestId !== state.constituentChartRequestId || state.constituentCode !== code) return;
            mergeConstituentBars(payload.bars);
            if (!state.constituentBars.length || !window.LightweightCharts) throw new Error("该板块暂无可用历史行情");
            const firstAvailable = Number(payload.meta?.first_available_bar_time);
            state.constituentFirstAvailableTime = Number.isFinite(firstAvailable) ? firstAvailable : null;
            const chart = window.LightweightCharts.createChart(mount, {
                ...createChartOptions(),
                timeScale: { borderColor: "#2b2b2b", timeVisible: false, rightOffset: 4, barSpacing: 7, minBarSpacing: 1, fixRightEdge: true },
                leftPriceScale: { visible: false },
                handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
                handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
            });
            const series = chart.addSeries(window.LightweightCharts.CandlestickSeries, {
                upColor: "#ef5350", downColor: "#26a69a", borderVisible: false,
                wickUpColor: "#ef5350", wickDownColor: "#26a69a", priceLineVisible: false,
            });
            const bollingerSeriesOptions = {
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
            };
            const bollingerSeries = {
                upper: chart.addSeries(window.LightweightCharts.LineSeries, { ...bollingerSeriesOptions, color: "rgba(233,162,59,.9)" }),
                middle: chart.addSeries(window.LightweightCharts.LineSeries, { ...bollingerSeriesOptions, color: "rgba(107,156,255,.85)", lineStyle: window.LightweightCharts.LineStyle.Dashed }),
                lower: chart.addSeries(window.LightweightCharts.LineSeries, { ...bollingerSeriesOptions, color: "rgba(233,162,59,.9)" }),
            };
            state.constituentChart = chart;
            state.constituentSeries = series;
            state.constituentBollingerSeries = bollingerSeries;
            renderConstituentChartData();
            chart.timeScale().fitContent();
            if (Number.isFinite(state.constituentFirstAvailableTime) && state.constituentBars[0].time <= state.constituentFirstAvailableTime) {
                lockConstituentHistoryLeftEdge();
            }
            chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
                if (range && range.from <= Math.max(25, (range.to - range.from) * 0.2)) {
                    void loadOlderConstituentBars(requestId);
                }
            });
            chartState.classList.add("is-hidden");
        } catch (error) {
            if (requestId !== state.constituentChartRequestId) return;
            chartState.classList.add("error");
            chartState.textContent = `板块历史行情读取失败：${error.message}`;
        }
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
        void loadConstituentHistoryChart(code);
        try {
            const params = new URLSearchParams({ sector_code: code });
            const payload = await apiFetch(`/api/market/sector-constituents?${params.toString()}`, { timeoutMs: 20000 });
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
            leftPriceScale: { visible: true, borderColor: "#2b2b2b", scaleMargins: { top: 0.12, bottom: 0.12 } },
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
        const fundMetricLabel = ["885", "886"].includes(String(item.code || "").slice(0, 3)) ? "资金覆盖率" : "资金占比";
        const periodCards = MODEL_PERIODS.map(([period, label, horizon]) => `<div class="sector-signal-period" data-period="${period}"><div class="sector-signal-period-label"><span>${label}</span><small class="sector-signal-period-horizon">${horizon}</small></div><strong>--</strong><small class="sector-signal-period-strength">--</small></div>`).join("");
        const periodPopovers = MODEL_PERIODS.map(([period, label, horizon]) => `<section class="sector-signal-popover-period" data-period="${period}"><div class="sector-signal-popover-head"><strong>${label}</strong><span>${horizon}</span></div><div class="sector-signal-events">${MODEL_EVENTS.map(([, name]) => `<div class="sector-signal-event-row"><span>${name}</span><strong>--</strong></div>`).join("")}</div></section>`).join("");
        card.innerHTML = `<div class="sector-card-head"><div class="sector-name"><h2></h2><span></span></div><div class="sector-head-metrics"><div class="sector-signal" tabindex="0" aria-label="峰谷模型信号" title="加载后悬停查看超短、短期、中期共15个事件概率；点击打开详情"><div class="sector-signal-periods">${periodCards}</div><span class="sector-signal-caption">峰谷模型 · 概率</span><div class="sector-signal-popover" role="tooltip"><div class="sector-signal-popover-title"><strong>峰谷模型概率</strong><span>悬停查看15个概率</span></div>${periodPopovers}</div></div><div class="sector-performance"><strong>--</strong><span>${getRangeLabel()}涨跌幅</span></div><div class="sector-fund-share"><strong>--</strong><span>${fundMetricLabel}</span></div></div></div><div class="chart-mount"><div class="chart-placeholder">等待加载走势</div></div>`;
        card.querySelector("h2").textContent = item.name || item.code;
        card.querySelector(".sector-name span").textContent = item.code;
        const signal = card.querySelector(".sector-signal");
        if (signal) {
            const popover = signal.querySelector(".sector-signal-popover");
            let closeTimer = null;
            const keepPopoverOpen = () => {
                if (closeTimer) window.clearTimeout(closeTimer);
                signal.classList.add("is-hovered");
                signal.dataset.activePeriod ||= MODEL_PERIODS[0][0];
            };
            const schedulePopoverClose = () => {
                if (closeTimer) window.clearTimeout(closeTimer);
                closeTimer = window.setTimeout(() => {
                    if (signal.matches(":hover")) return;
                    signal.classList.remove("is-hovered");
                    delete signal.dataset.activePeriod;
                }, 180);
            };
            signal.addEventListener("mouseenter", keepPopoverOpen);
            signal.addEventListener("focus", () => { signal.dataset.activePeriod ||= MODEL_PERIODS[0][0]; });
            signal.addEventListener("mouseleave", schedulePopoverClose);
            popover?.addEventListener("mouseenter", keepPopoverOpen);
            popover?.addEventListener("mouseleave", schedulePopoverClose);
            signal.querySelectorAll(".sector-signal-period").forEach((periodNode) => {
                periodNode.addEventListener("mouseenter", () => { signal.dataset.activePeriod = periodNode.dataset.period || MODEL_PERIODS[0][0]; });
            });
            signal.querySelectorAll(".sector-signal-event-row").forEach((row) => {
                row.addEventListener("mouseenter", () => { void loadModelEventDetail(row); });
                row.addEventListener("mouseleave", scheduleGlobalModelEventDetailClose);
            });
            signal.addEventListener("click", (event) => {
            event.stopPropagation();
            void openModelSignalDialog(item.code);
            });
        }
        card.addEventListener("dblclick", () => { void openConstituentDialog(card); });
        updateModelSignalCard(card);
        return card;
    }

    function updateSectorSignal(card) {
        // 行情涨跌幅只更新 sector-performance，模型卡片由 updateModelSignalCard 统一渲染。
        // 保留此调用点是为了兼容已有的走势加载流程，避免收益刷新覆盖模型概率。
        updateModelSignalCard(card);
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

    function sortCardsByModelSignal() {
        const grid = document.getElementById("sector-grid");
        if (!grid) return;
        const key = `${state.modelSortPeriod}_prob_${state.modelSortEvent}`;
        const cards = Array.from(grid.querySelectorAll(".sector-card"));
        cards.sort((left, right) => {
            const leftItem = state.modelSignalByCode.get(String(left.dataset.code || "").toUpperCase());
            const rightItem = state.modelSignalByCode.get(String(right.dataset.code || "").toUpperCase());
            const leftValue = Number(leftItem?.[key]);
            const rightValue = Number(rightItem?.[key]);
            const leftLoaded = Number.isFinite(leftValue);
            const rightLoaded = Number.isFinite(rightValue);
            if (leftLoaded !== rightLoaded) return leftLoaded ? -1 : 1;
            if (!leftLoaded) return String(left.dataset.code).localeCompare(String(right.dataset.code));
            return rightValue - leftValue || String(left.dataset.code).localeCompare(String(right.dataset.code));
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

    async function loadSectorFundShares(generation) {
        const bounds = rangeTimestamps(state.range);
        const requestedLimit = state.range === "custom"
            ? Math.min(2000, Math.max(1, Number(state.customDays || 1)))
            : RANGE_CONFIG[state.range].points || 400;
        const params = new URLSearchParams({ prefix: state.prefix, from: String(bounds.from), to: String(bounds.to), limit: String(requestedLimit) });
        try {
            const payload = await apiFetch(`/api/market/sector-fund-shares?${params.toString()}`);
            if (generation !== state.generation) return;
            const grouped = new Map();
            (Array.isArray(payload.points) ? payload.points : []).forEach((point) => {
                const code = String(point.sector_code || "").toUpperCase();
                const value = Number(point.fund_share_pct);
                const time = Number(point.time);
                if (!code || !Number.isFinite(time) || !Number.isFinite(value)) return;
                if (!grouped.has(code)) grouped.set(code, []);
                grouped.get(code).push({ time, value });
            });
            state.fundShareBySector = grouped;
        } catch (error) {
            if (isAbortError(error)) return;
            if (generation === state.generation) state.fundShareBySector = new Map();
        }
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
            const [payload] = await Promise.all([
                apiFetch(`/api/market/index/bars?${params.toString()}`),
                state.fundSharePromise || Promise.resolve(),
            ]);
            if (!card.isConnected || generation !== state.generation) return;
            const pointLimit = state.range === "custom" ? Number(state.customDays) : RANGE_CONFIG[state.range].points;
            const data = selectOhlcBars(payload.bars, pointLimit);
            card.dataset.chartPointCount = String(data.length);
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
            const fundSharePoints = state.fundShareBySector.get(card.dataset.code) || [];
            const fundShareNode = card.querySelector(".sector-fund-share");
            if (fundSharePoints.length) {
                const line = chart.addSeries(window.LightweightCharts.LineSeries, {
                    color: "#e9a23b",
                    lineWidth: 2,
                    priceScaleId: "fund-share",
                    priceFormat: { type: "custom", formatter: (value) => `${Number(value).toFixed(1)}%` },
                    priceLineVisible: false,
                    lastValueVisible: true,
                });
                line.setData(fundSharePoints);
                const latest = fundSharePoints[fundSharePoints.length - 1].value;
                fundShareNode?.classList.add("has-value");
                if (fundShareNode) fundShareNode.querySelector("strong").textContent = `${latest.toFixed(1)}%`;
            } else if (fundShareNode) {
                fundShareNode.querySelector("strong").textContent = "--";
                fundShareNode.querySelector("span").textContent = "资金数据暂无快照";
            }
            chart.timeScale().fitContent();
            bindChartModelSignalHover(card, chart);
            card.addEventListener("mouseleave", () => restoreLatestModelSignal(card));
            state.charts.set(card.dataset.code, chart);
            const performance = card.querySelector(".sector-performance");
            card.dataset.return = String(change);
            performance.classList.add(change >= 0 ? "positive" : "negative");
            performance.querySelector("strong").textContent = `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
            updateSectorSignal(card, change);
            card.dataset.status = "ready";
        } catch (error) {
            if (isAbortError(error)) return;
            card.dataset.status = "error";
            if (card.isConnected && generation === state.generation) mount.innerHTML = `<div class="chart-error"></div>`;
            const errorNode = mount.querySelector(".chart-error");
            if (errorNode) errorNode.textContent = error.message || "走势读取失败";
        }
    }

    function renderSectors() {
        state.generation += 1;
        const generation = state.generation;
        cancelPendingRequests();
        destroyCharts();
        state.fundShareBySector = new Map();
        state.fundSharePromise = loadSectorFundShares(generation);
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
        void loadSectorModelSignals(state.prefix, generation);
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
        if (state.modelSortActive) sortCardsByModelSignal();
        else if (state.sortActive) void loadReturnsAndSort(generation);
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
            state.sortMode = "return";
            state.sortActive = true;
            state.modelSortActive = false;
            document.querySelectorAll("[data-sort]").forEach((item) => item.classList.toggle("active", item === button));
            modelSortTrigger?.classList.remove("active");
            void loadReturnsAndSort(state.generation);
        }));
        const modelSortMenu = document.querySelector(".model-sort-menu");
        const modelSortTrigger = modelSortMenu?.querySelector(".model-sort-trigger");
        const modelSortLabel = (period, event) => {
            const periodLabel = { ultra_short: "超短", "5d": "短期", "20d": "中期" }[period] || period;
            const eventLabel = { valley_bullish: "波谷看涨", peak_bearish: "波峰看跌" }[event] || event;
            return `峰谷模型：${periodLabel}·${eventLabel}`;
        };
        modelSortMenu?.addEventListener("mouseenter", () => modelSortTrigger?.setAttribute("aria-expanded", "true"));
        modelSortMenu?.addEventListener("mouseleave", () => modelSortTrigger?.setAttribute("aria-expanded", "false"));
        modelSortMenu?.addEventListener("focusin", () => modelSortTrigger?.setAttribute("aria-expanded", "true"));
        modelSortMenu?.addEventListener("focusout", (event) => { if (!modelSortMenu.contains(event.relatedTarget)) modelSortTrigger?.setAttribute("aria-expanded", "false"); });
        modelSortMenu?.querySelectorAll("[data-model-period]").forEach((option) => option.addEventListener("click", () => {
            state.sortMode = "model";
            state.sortActive = false;
            state.modelSortActive = true;
            state.modelSortPeriod = option.dataset.modelPeriod || "ultra_short";
            state.modelSortEvent = option.dataset.modelEvent || "valley_bullish";
            modelSortTrigger.textContent = modelSortLabel(state.modelSortPeriod, state.modelSortEvent);
            modelSortTrigger.classList.add("active");
            modelSortMenu.querySelectorAll(".model-sort-option").forEach((item) => item.classList.toggle("active", item === option));
            document.querySelectorAll("[data-sort]").forEach((item) => item.classList.remove("active"));
            sortCardsByModelSignal();
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
        bindGlobalModelEventDetail();
        bindControls();
        bindAutoCollapseControls();
        document.getElementById("constituent-close")?.addEventListener("click", closeConstituentDialog);
        document.querySelector("[data-close-constituents]")?.addEventListener("click", closeConstituentDialog);
        document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeConstituentDialog(); });
        document.getElementById("model-signal-close")?.addEventListener("click", closeModelSignalDialog);
        document.querySelector("[data-close-model-signal]")?.addEventListener("click", closeModelSignalDialog);
        document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeModelSignalDialog(); });
        updateClock();
        window.setInterval(updateClock, 1000);
        loadSectorList();
    });

    window.SectorRotation = { filterSectorItems, isStockCodeQuery, applySearchQuery, bindAutoCollapseControls, rangeTimestamps, normalizedCloseSeries, selectOhlcBars, calculateConstituentBollingerBands, renderSectors, loadSectorList };
})();
