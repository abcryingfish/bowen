/* 基本面 — 无 K 线，读取 /api/market/fundamental */

(function () {
    const TAB_KEYS = ["overview", "indicators", "income", "balance", "cashflow"];
    const TAB_LABELS = {
        overview: "概览",
        indicators: "财务指标",
        income: "利润表",
        balance: "资产负债表",
        cashflow: "现金流量表",
    };

    let activeTab = "overview";
    let panelData = null;
    let fetchToken = 0;
    const chartInstances = [];

    function escapeHtml(text) {
        return String(text ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
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

    function formatByType(value, format) {
        if (value === null || value === undefined || value === "") {
            return "—";
        }
        const num = Number(value);
        if (!Number.isFinite(num)) {
            return escapeHtml(value);
        }
        if (format === "percent") {
            return `${formatNumber(num, 2)}%`;
        }
        if (format === "money") {
            const abs = Math.abs(num);
            if (abs >= 1e8) {
                return `${formatNumber(num / 1e8, 2)} 亿`;
            }
            if (abs >= 1e4) {
                return `${formatNumber(num / 1e4, 2)} 万`;
            }
            return formatNumber(num, 2);
        }
        if (format === "ratio") {
            return formatNumber(num, 2);
        }
        return formatNumber(num, 4);
    }

    function destroyCharts() {
        while (chartInstances.length) {
            const chart = chartInstances.pop();
            try {
                chart.remove();
            } catch (_err) {
                /* ignore */
            }
        }
    }

    function periodLabelToChartTime(label) {
        const text = String(label || "").trim();
        const quarter = text.match(/^(\d{4})-Q([1-4])$/i);
        if (quarter) {
            const year = quarter[1];
            const month = String(Number(quarter[2]) * 3).padStart(2, "0");
            return `${year}-${month}-01`;
        }
        if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
            return text;
        }
        return null;
    }

    function renderMiniCharts(metrics) {
        destroyCharts();
        if (!Array.isArray(metrics) || !metrics.length || typeof LightweightCharts === "undefined") {
            return;
        }
        metrics.forEach((metric) => {
            const container = document.querySelector(`.fundamental-chart-box[data-metric-key="${metric.key}"]`);
            if (!container || !Array.isArray(metric.points) || metric.points.length < 2) {
                return;
            }
            const chart = LightweightCharts.createChart(container, {
                width: container.clientWidth || 280,
                height: container.clientHeight || 160,
                layout: {
                    background: { color: "#1a1f2b" },
                    textColor: "#9ca3af",
                },
                grid: {
                    vertLines: { color: "rgba(255,255,255,0.04)" },
                    horzLines: { color: "rgba(255,255,255,0.04)" },
                },
                rightPriceScale: { borderVisible: false },
                timeScale: { borderVisible: false, visible: false },
                crosshair: { mode: LightweightCharts.CrosshairMode ? LightweightCharts.CrosshairMode.Magnet : 0 },
            });
            const series = chart.addSeries(LightweightCharts.LineSeries, {
                color: "#5b7fd1",
                lineWidth: 2,
                priceLineVisible: false,
                lastValueVisible: true,
            });
            const data = metric.points.map((point, index) => {
                const time = periodLabelToChartTime(point.t) || `2020-01-${String(index + 1).padStart(2, "0")}`;
                return {
                    time,
                    value: Number(point.v),
                };
            });
            series.setData(data);
            chart.timeScale().fitContent();
            chartInstances.push(chart);
        });
    }

    function renderKvGrid(items) {
        return `<div class="fundamental-kv-grid">${items.map(([label, value]) => `
            <div class="fundamental-kv-item">
                <span class="fundamental-kv-label">${escapeHtml(label)}</span>
                <span class="fundamental-kv-value">${value}</span>
            </div>`).join("")}</div>`;
    }

    function renderOverviewTab(data) {
        const overview = data.overview;
        if (!overview || !Array.isArray(overview.kpis) || !overview.kpis.length) {
            return `<p class="fundamental-prose fundamental-state-msg">暂无概览 KPI 数据。</p>`;
        }
        const cards = overview.kpis.map((kpi) => {
            const yoyHtml = Number.isFinite(Number(kpi.yoy))
                ? `<span class="fundamental-kpi-yoy ${Number(kpi.yoy) >= 0 ? "up" : "down"}">同比 ${formatByType(kpi.yoy, "percent")}</span>`
                : "";
            return `
                <div class="fundamental-kpi-card">
                    <div class="fundamental-kpi-label">${escapeHtml(kpi.label)}</div>
                    <div class="fundamental-kpi-value">${formatByType(kpi.value, kpi.format)}</div>
                    ${yoyHtml}
                </div>`;
        }).join("");
        return `
            <section class="fundamental-section">
                <h3 class="fundamental-section-title">最新报告期关键指标</h3>
                <div class="fundamental-kpi-row">${cards}</div>
            </section>`;
    }

    function renderPeriodMatrixTable(section, emptyLabel) {
        if (!section || !Array.isArray(section.rows) || !section.rows.length) {
            return `<p class="fundamental-state-msg">暂无${escapeHtml(emptyLabel)}数据。</p>`;
        }
        const fields = section.fields || [];
        if (!fields.length) {
            return `<p class="fundamental-state-msg">暂无${escapeHtml(emptyLabel)}数据。</p>`;
        }
        const header = `<tr><th>报告期</th>${fields.map((field) => `<th class="num">${escapeHtml(field.label)}</th>`).join("")}</tr>`;
        const body = section.rows.slice().reverse().map((row) => `
            <tr>
                <td>${escapeHtml(row.period_label || row.end_date || "")}</td>
                ${fields.map((field) => `<td class="num">${formatByType(row[field.key], field.format)}</td>`).join("")}
            </tr>`).join("");
        return `
            <div class="fundamental-table-wrap">
                <table class="fundamental-table">
                    <thead>${header}</thead>
                    <tbody>${body}</tbody>
                </table>
            </div>`;
    }

    function renderIndicatorTable(indicators) {
        if (!indicators || !Array.isArray(indicators.rows) || !indicators.rows.length) {
            return `<p class="fundamental-state-msg">暂无财务指标数据。</p>`;
        }
        const columns = indicators.columns || [];
        const header = `<tr><th>报告期</th>${columns.map((col) => `<th class="num">${escapeHtml(col.label)}</th>`).join("")}</tr>`;
        const body = indicators.rows.slice().reverse().map((row) => `
            <tr>
                <td>${escapeHtml(row.period_label || row.end_date || "")}</td>
                ${columns.map((col) => `<td class="num">${formatByType(row[col.key], col.format)}</td>`).join("")}
            </tr>`).join("");
        return `
            <div class="fundamental-table-wrap">
                <table class="fundamental-table">
                    <thead>${header}</thead>
                    <tbody>${body}</tbody>
                </table>
            </div>`;
    }

    function renderIndicatorCharts(indicators) {
        const metrics = (indicators && indicators.chart_metrics) || [];
        if (!metrics.length) {
            return "";
        }
        const boxes = metrics.map((metric) => `
            <div class="fundamental-chart-card">
                <div class="fundamental-chart-title">${escapeHtml(metric.label)}</div>
                <div class="fundamental-chart-box" data-metric-key="${escapeHtml(metric.key)}"></div>
            </div>`).join("");
        return `
            <section class="fundamental-section">
                <h3 class="fundamental-section-title">历史趋势</h3>
                <div class="fundamental-chart-grid">${boxes}</div>
            </section>`;
    }

    function renderIndicatorsTab(data) {
        const indicators = data.indicators;
        return `
            ${renderIndicatorTable(indicators)}
            ${renderIndicatorCharts(indicators)}`;
    }

    function renderStatementTab(statementKey, data) {
        const section = data.statements && data.statements[statementKey];
        return renderPeriodMatrixTable(section, TAB_LABELS[statementKey]);
    }

    function renderTabPanels(data) {
        return TAB_KEYS.map((key) => `
            <div class="fundamental-tab-panel ${key === activeTab ? "is-active" : ""}" data-tab-panel="${key}">
                ${key === "overview" ? renderOverviewTab(data) : ""}
                ${key === "indicators" ? renderIndicatorsTab(data) : ""}
                ${key === "income" ? renderStatementTab("income", data) : ""}
                ${key === "balance" ? renderStatementTab("balance", data) : ""}
                ${key === "cashflow" ? renderStatementTab("cashflow", data) : ""}
            </div>`).join("");
    }

    function renderTabs() {
        return `
            <div class="fundamental-tabs" role="tablist">
                ${TAB_KEYS.map((key) => `
                    <button type="button" class="fundamental-tab ${key === activeTab ? "is-active" : ""}" data-tab="${key}" role="tab">
                        ${escapeHtml(TAB_LABELS[key])}
                    </button>`).join("")}
            </div>`;
    }

    function bindTabEvents(main) {
        main.querySelectorAll(".fundamental-tab").forEach((button) => {
            button.addEventListener("click", () => {
                activeTab = button.getAttribute("data-tab") || "overview";
                main.querySelectorAll(".fundamental-tab").forEach((el) => {
                    el.classList.toggle("is-active", el.getAttribute("data-tab") === activeTab);
                });
                main.querySelectorAll(".fundamental-tab-panel").forEach((el) => {
                    el.classList.toggle("is-active", el.getAttribute("data-tab-panel") === activeTab);
                });
                if (activeTab === "indicators" && panelData) {
                    requestAnimationFrame(() => renderMiniCharts(panelData.indicators && panelData.indicators.chart_metrics));
                }
            });
        });
    }

    function renderMainPanel(data) {
        const main = document.getElementById("fundamental-content");
        if (!main) {
            return;
        }
        const meta = data.meta || {};
        const title = meta.name || meta.code || "—";
        const metaParts = [meta.code, meta.latest_report ? `最新报告 ${meta.latest_report}` : "", meta.data_as_of ? `估值截至 ${meta.data_as_of}` : ""]
            .filter(Boolean)
            .join(" · ");
        main.innerHTML = `
            <div class="fundamental-head">
                <h2 class="fundamental-head-title">${escapeHtml(title)}</h2>
                <span class="fundamental-head-meta">${escapeHtml(metaParts)}</span>
            </div>
            ${renderTabs()}
            <div class="fundamental-tab-panels">${renderTabPanels(data)}</div>`;
        bindTabEvents(main);
        if (activeTab === "indicators") {
            requestAnimationFrame(() => renderMiniCharts(data.indicators && data.indicators.chart_metrics));
        }
    }

    function renderSidePanel(data) {
        const side = document.getElementById("right-panel-body");
        if (!side) {
            return;
        }
        const meta = data.meta || {};
        const snap = data.valuation_snapshot || {};
        side.innerHTML = `
            <div class="fundamental-side-block">
                <h3 class="fundamental-side-title">当前标的</h3>
                <ul class="fundamental-side-list">
                    <li><span>代码</span><span>${escapeHtml(meta.code || "—")}</span></li>
                    <li><span>简称</span><span>${escapeHtml(meta.name || snap.name || "—")}</span></li>
                    <li><span>最新报告</span><span>${escapeHtml(meta.latest_report || "—")}</span></li>
                </ul>
            </div>
            <div class="fundamental-side-block">
                <h3 class="fundamental-side-title">估值速览</h3>
                <ul class="fundamental-side-list">
                    <li><span>PE(TTM)</span><span>${formatByType(snap.pettm, "ratio")}</span></li>
                    <li><span>PB</span><span>${formatByType(snap.pb, "ratio")}</span></li>
                    <li><span>PS(TTM)</span><span>${formatByType(snap.psttm, "ratio")}</span></li>
                    <li><span>总市值</span><span>${formatByType(snap.total_market_val, "money")}</span></li>
                </ul>
            </div>
            <div class="fundamental-side-block">
                <h3 class="fundamental-side-title">交易速览</h3>
                <ul class="fundamental-side-list">
                    <li><span>日期</span><span>${escapeHtml(snap.time || "—")}</span></li>
                    <li><span>收盘</span><span>${formatByType(snap.close, "ratio")}</span></li>
                    <li><span>换手率</span><span>${formatByType(snap.turnover_rate, "percent")}</span></li>
                    <li><span>成交额</span><span>${formatByType(snap.value, "money")}</span></li>
                </ul>
            </div>`;
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
                <p class="fundamental-prose fundamental-state-msg">正在读取基本面数据…</p>`;
        }
        if (side) {
            side.innerHTML = `<div class="fundamental-side-block"><p class="fundamental-side-prose">加载中…</p></div>`;
        }
    }

    function renderErrorState(code, message) {
        destroyCharts();
        panelData = null;
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
        destroyCharts();
        panelData = null;
        const main = document.getElementById("fundamental-content");
        const side = document.getElementById("right-panel-body");
        if (main) {
            main.innerHTML = `
                <div class="fundamental-head">
                    <h2 class="fundamental-head-title">基本面</h2>
                    <span class="fundamental-head-meta">请在上方输入股票代码</span>
                </div>
                <p class="fundamental-prose">输入 code 并回车，或从左侧自选股选择，此处将显示估值、财务指标与三表数据。</p>`;
        }
        if (side) {
            side.innerHTML = `
                <div class="fundamental-side-block">
                    <h3 class="fundamental-side-title">提示</h3>
                    <p class="fundamental-side-prose">右侧栏显示估值与交易速览。</p>
                </div>`;
        }
    }

    function apiBaseUrl() {
        try {
            if (typeof resolveApiBaseUrl === "function") {
                return resolveApiBaseUrl();
            }
        } catch (_err) {
            /* ignore */
        }
        return "http://127.0.0.1:8000";
    }

    async function fetchFundamental(code) {
        const token = ++fetchToken;
        destroyCharts();
        renderLoadingState(code);
        try {
            const response = await fetch(`${apiBaseUrl()}/api/market/fundamental?code=${encodeURIComponent(code)}`, {
                cache: "no-store",
            });
            const payload = await response.json();
            if (token !== fetchToken) {
                return;
            }
            if (!response.ok) {
                const message = payload && payload.error && payload.error.message
                    ? payload.error.message
                    : `请求失败 (${response.status})`;
                renderErrorState(code, message);
                return;
            }
            panelData = payload;
            renderMainPanel(payload);
            renderSidePanel(payload);
        } catch (err) {
            if (token !== fetchToken) {
                return;
            }
            renderErrorState(code, err && err.message ? err.message : "网络请求失败");
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
