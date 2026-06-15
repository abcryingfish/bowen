/* 基本面 — QMT 公司数据原生表浏览 */

(function () {
    const DEFAULT_TABLES = [
        { key: "Income", label: "利润表" },
        { key: "Balance", label: "资产负债表" },
        { key: "CashFlow", label: "现金流量表" },
        { key: "PershareIndex", label: "主要指标" },
        { key: "Capital", label: "股本结构" },
    ];

    let activeTable = "Income";
    let tableSpecs = DEFAULT_TABLES.slice();
    let summaryData = null;
    let fetchToken = 0;

    function escapeHtml(text) {
        return String(text ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function apiBaseUrl() {
        try {
            const fromQuery = new URLSearchParams(window.location.search || "").get("apiBase");
            if (fromQuery) {
                return fromQuery.trim().replace(/\/+$/, "");
            }
        } catch (_err) {
            /* ignore */
        }
        try {
            if (typeof resolveApiBaseUrl === "function") {
                return resolveApiBaseUrl();
            }
        } catch (_err) {
            /* ignore */
        }
        return "http://127.0.0.1:8000";
    }

    function formatNumber(value, digits = 2) {
        const num = Number(value);
        if (!Number.isFinite(num)) {
            return "—";
        }
        return num.toLocaleString("zh-CN", {
            minimumFractionDigits: 0,
            maximumFractionDigits: digits,
        });
    }

    function formatValue(value, type) {
        if (value === null || value === undefined || value === "") {
            return "—";
        }
        if (type === "number") {
            return formatNumber(value, 4);
        }
        return escapeHtml(value);
    }

    function formatCompactNumber(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) {
            return "—";
        }
        const abs = Math.abs(num);
        if (abs >= 1e8) {
            return `${formatNumber(num / 1e8, 2)} 亿`;
        }
        if (abs >= 1e4) {
            return `${formatNumber(num / 1e4, 2)} 万`;
        }
        return formatNumber(num, 2);
    }

    async function fetchJson(path) {
        const response = await fetch(`${apiBaseUrl()}${path}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok) {
            const message = payload && payload.error && payload.error.message
                ? payload.error.message
                : `请求失败 (${response.status})`;
            throw new Error(message);
        }
        return payload;
    }

    function renderLoadingState(code) {
        const main = document.getElementById("fundamental-content");
        const side = document.getElementById("right-panel-body");
        if (main) {
            main.innerHTML = `
                <div class="fundamental-head">
                    <h2 class="fundamental-head-title">加载中</h2>
                    <span class="fundamental-head-meta">${escapeHtml(code)}</span>
                </div>
                <p class="fundamental-prose fundamental-state-msg">正在读取 QMT 公司数据…</p>`;
        }
        if (side) {
            side.innerHTML = `<div class="fundamental-side-block"><p class="fundamental-side-prose">加载中…</p></div>`;
        }
    }

    function renderErrorState(code, message) {
        summaryData = null;
        const main = document.getElementById("fundamental-content");
        const side = document.getElementById("right-panel-body");
        if (main) {
            main.innerHTML = `
                <div class="fundamental-head">
                    <h2 class="fundamental-head-title">暂无数据</h2>
                    <span class="fundamental-head-meta">${escapeHtml(code)}</span>
                </div>
                <p class="fundamental-prose fundamental-state-error">${escapeHtml(message)}</p>`;
        }
        if (side) {
            side.innerHTML = `
                <div class="fundamental-side-block">
                    <h3 class="fundamental-side-title">提示</h3>
                    <p class="fundamental-side-prose">${escapeHtml(message)}</p>
                </div>`;
        }
    }

    function renderEmptyState() {
        summaryData = null;
        const main = document.getElementById("fundamental-content");
        const side = document.getElementById("right-panel-body");
        if (main) {
            main.innerHTML = `
                <div class="fundamental-head">
                    <h2 class="fundamental-head-title">基本面</h2>
                    <span class="fundamental-head-meta">请在上方输入股票代码</span>
                </div>
                <p class="fundamental-prose">输入 code 并回车，或从左侧自选股选择，此处将显示 QMT 原生公司数据。</p>`;
        }
        if (side) {
            side.innerHTML = `
                <div class="fundamental-side-block">
                    <h3 class="fundamental-side-title">提示</h3>
                    <p class="fundamental-side-prose">右侧栏显示最新报告期与股本速览。</p>
                </div>`;
        }
    }

    function renderTabs() {
        return `
            <div class="fundamental-tabs" role="tablist">
                ${tableSpecs.map((item) => `
                    <button type="button" class="fundamental-tab ${item.key === activeTable ? "is-active" : ""}"
                        data-table="${escapeHtml(item.key)}" role="tab">
                        ${escapeHtml(item.label || item.key)}
                    </button>`).join("")}
            </div>`;
    }

    function renderTable(payload) {
        const columns = (payload && payload.columns) || [];
        const rows = (payload && payload.rows) || [];
        if (!columns.length || !rows.length) {
            return `<p class="fundamental-state-msg">暂无${escapeHtml(activeTable)}数据。</p>`;
        }
        const header = `<tr>${columns.map((column) => `<th class="${column.type === "number" ? "num" : ""}">${escapeHtml(column.label || column.key)}</th>`).join("")}</tr>`;
        const body = rows.map((row) => `
            <tr>
                ${columns.map((column) => `<td class="${column.type === "number" ? "num" : ""}">${formatValue(row[column.key], column.type)}</td>`).join("")}
            </tr>`).join("");
        return `
            <div class="fundamental-table-wrap">
                <table class="fundamental-table">
                    <thead>${header}</thead>
                    <tbody>${body}</tbody>
                </table>
            </div>`;
    }

    function renderMainShell(tablePayload) {
        const main = document.getElementById("fundamental-content");
        if (!main) {
            return;
        }
        const meta = (summaryData && summaryData.meta) || {};
        const tableMeta = (tablePayload && tablePayload.meta) || {};
        const title = meta.name || tableMeta.name || meta.code || "—";
        const metaParts = [
            meta.code,
            meta.latest_report ? `最新报告 ${meta.latest_report}` : "",
            tableMeta.label ? `当前表 ${tableMeta.label}` : "",
        ].filter(Boolean).join(" · ");
        main.innerHTML = `
            <div class="fundamental-head">
                <h2 class="fundamental-head-title">${escapeHtml(title)}</h2>
                <span class="fundamental-head-meta">${escapeHtml(metaParts)}</span>
            </div>
            ${renderTabs()}
            <div class="fundamental-tab-panels">
                <div class="fundamental-tab-panel is-active">
                    ${renderTable(tablePayload)}
                </div>
            </div>`;
        bindTabEvents(main);
    }

    function renderSidePanel() {
        const side = document.getElementById("right-panel-body");
        if (!side) {
            return;
        }
        const meta = (summaryData && summaryData.meta) || {};
        const latest = (summaryData && summaryData.latest_by_table) || {};
        const capital = latest.Capital || {};
        side.innerHTML = `
            <div class="fundamental-side-block">
                <h3 class="fundamental-side-title">当前标的</h3>
                <ul class="fundamental-side-list">
                    <li><span>代码</span><span>${escapeHtml(meta.code || "—")}</span></li>
                    <li><span>简称</span><span>${escapeHtml(meta.name || capital.name || "—")}</span></li>
                    <li><span>最新报告</span><span>${escapeHtml(meta.latest_report || "—")}</span></li>
                </ul>
            </div>
            <div class="fundamental-side-block">
                <h3 class="fundamental-side-title">股本速览</h3>
                <ul class="fundamental-side-list">
                    <li><span>报告期</span><span>${escapeHtml(capital.report_date || "—")}</span></li>
                    <li><span>总股本</span><span>${formatCompactNumber(capital.total_capital)}</span></li>
                    <li><span>流通股本</span><span>${formatCompactNumber(capital.circulating_capital)}</span></li>
                    <li><span>自由流通股本</span><span>${formatCompactNumber(capital.freeFloatCapital)}</span></li>
                </ul>
            </div>`;
    }

    function bindTabEvents(main) {
        main.querySelectorAll(".fundamental-tab").forEach((button) => {
            button.addEventListener("click", () => {
                const table = button.getAttribute("data-table") || "Income";
                if (table === activeTable) {
                    return;
                }
                activeTable = table;
                const code = summaryData && summaryData.meta && summaryData.meta.code;
                if (code) {
                    renderCurrentTable(code);
                }
            });
        });
    }

    async function renderCurrentTable(code) {
        const token = ++fetchToken;
        try {
            const payload = await fetchJson(`/api/company/qmt/table?code=${encodeURIComponent(code)}&table=${encodeURIComponent(activeTable)}&limit=12`);
            if (token !== fetchToken) {
                return;
            }
            renderMainShell(payload);
            renderSidePanel();
        } catch (err) {
            if (token !== fetchToken) {
                return;
            }
            renderErrorState(code, err && err.message ? err.message : "QMT 公司数据读取失败");
        }
    }

    async function fetchFundamental(code) {
        const token = ++fetchToken;
        renderLoadingState(code);
        try {
            const [tablesPayload, summaryPayload] = await Promise.all([
                fetchJson("/api/company/qmt/tables"),
                fetchJson(`/api/company/qmt/summary?code=${encodeURIComponent(code)}`),
            ]);
            if (token !== fetchToken) {
                return;
            }
            tableSpecs = Array.isArray(tablesPayload.tables) && tablesPayload.tables.length
                ? tablesPayload.tables
                : DEFAULT_TABLES.slice();
            summaryData = summaryPayload;
            if (!tableSpecs.some((item) => item.key === activeTable)) {
                activeTable = tableSpecs[0].key;
            }
            const tablePayload = await fetchJson(`/api/company/qmt/table?code=${encodeURIComponent(code)}&table=${encodeURIComponent(activeTable)}&limit=12`);
            if (token !== fetchToken) {
                return;
            }
            renderMainShell(tablePayload);
            renderSidePanel();
        } catch (err) {
            if (token !== fetchToken) {
                return;
            }
            renderErrorState(code, err && err.message ? err.message : "QMT 公司数据读取失败");
        }
    }

    function renderFundamental(code) {
        const normalized = String(code || "").trim().toUpperCase();
        if (!normalized) {
            renderEmptyState();
            return Promise.resolve();
        }
        return fetchFundamental(normalized);
    }

    function bootstrapFundamentalPanel() {
        const input = document.getElementById("code-input");
        const code = input ? String(input.value || "").trim().toUpperCase() : "";
        return renderFundamental(code);
    }

    window.ChartBoardView = {
        id: "fundamental",
        label: "基本面",
        init() {
            return bootstrapFundamentalPanel();
        },
        onCodeChange(code) {
            return renderFundamental(code);
        },
    };
})();
