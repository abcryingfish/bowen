(function () {
    "use strict";

    const STORAGE_KEY = "result_print_light_v1";
    const STYLE_ID = "result-print-light-style";
    const IFRAME_HTML_CLASS = "portfolio-print-light";
    const OUTER_HTML_CLASS = "result-print-light";
    const FRAME_FALLBACK_CLASS = "result-print-light-iframe-fallback";
    const TOGGLE_ID = "portfolio-extra-day-toggle";

    const IFRAME_INLINE_CSS = `
html.portfolio-print-light {
    --bg: #ffffff;
    --panel: #f8fafc;
    --line: #cbd5e1;
    --text: #1e293b;
    --muted: #64748b;
}
html.portfolio-print-light,
html.portfolio-print-light body,
html.portfolio-print-light .workspace,
html.portfolio-print-light .layout,
html.portfolio-print-light #main-layout,
html.portfolio-print-light #center-column,
html.portfolio-print-light .chart-wrap {
    background: #ffffff !important;
    color: #1e293b !important;
}
html.portfolio-print-light .page-header-title,
html.portfolio-print-light .page-header-clock,
html.portfolio-print-light .left-panel,
html.portfolio-print-light .right-panel,
html.portfolio-print-light .center-bottom-panel,
html.portfolio-print-light .center-bottom-box,
html.portfolio-print-light .backtest-rule-box,
html.portfolio-print-light .backtest-symbol-box,
html.portfolio-print-light .factor-snapshot-panel,
html.portfolio-print-light .morph-panel,
html.portfolio-print-light .watchlist-card,
html.portfolio-print-light .right-panel-body {
    background: #ffffff !important;
    color: #1e293b !important;
    border-color: #cbd5e1 !important;
    box-shadow: none !important;
}
html.portfolio-print-light .header-center-tabs { background: #f8fafc !important; }
html.portfolio-print-light .header-tab {
    background: #f1f5f9 !important;
    color: #475569 !important;
    border-color: #cbd5e1 !important;
}
html.portfolio-print-light .header-tab.active {
    background: #ffffff !important;
    color: #1d4ed8 !important;
    border-top-color: #2563eb !important;
}
html.portfolio-print-light .field,
html.portfolio-print-light .btn,
html.portfolio-print-light select.field,
html.portfolio-print-light input.field,
html.portfolio-print-light textarea.field {
    background: #ffffff !important;
    color: #1e293b !important;
    border-color: #cbd5e1 !important;
}
html.portfolio-print-light .chart-toolbar,
html.portfolio-print-light .signal-chart-wrap,
html.portfolio-print-light .signal-chart-caption {
    background: #ffffff !important;
    color: #1e293b !important;
    border-color: #cbd5e1 !important;
}
html.portfolio-print-light .portfolio-chart-legend {
    background: rgba(255, 255, 255, 0.58) !important;
    color: #1e293b !important;
    border-color: rgba(203, 213, 225, 0.85) !important;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
}
html.portfolio-print-light .chart-legend-item,
html.portfolio-print-light .backtest-rule-item,
html.portfolio-print-light .factor-snapshot-head,
html.portfolio-print-light h3,
html.portfolio-print-light label {
    color: #1e293b !important;
}
html.portfolio-print-light .factor-snapshot-head-extra,
html.portfolio-print-light #factor-snapshot-head-extra {
    color: #1e293b !important;
}
html.portfolio-print-light .center-bottom-backtest-label,
html.portfolio-print-light .factor-hint,
html.portfolio-print-light .page-clock {
    color: #64748b !important;
}
html.portfolio-print-light .splitter-v,
html.portfolio-print-light .splitter-h {
    background: #e2e8f0 !important;
}
html.portfolio-print-light #chart-container,
html.portfolio-print-light #signal-chart-container {
    background: #ffffff !important;
}
html.portfolio-print-light #portfolio-extra-day-toggle.field.btn {
    background: #ffffff !important;
    border-color: #cbd5e1 !important;
    color: #334155 !important;
}
html.portfolio-print-light #portfolio-extra-day-toggle.field.btn.is-on {
    background: #1e293b !important;
    border-color: #0f172a !important;
    color: #ffffff !important;
}
html.portfolio-print-light .summary-card {
    background: #ffffff !important;
    border-color: #cbd5e1 !important;
}
html.portfolio-print-light .summary-card-label,
html.portfolio-print-light .summary-panel-note,
html.portfolio-print-light .position-snapshot-table-header,
html.portfolio-print-light .position-snapshot-detail-label,
html.portfolio-print-light .position-snapshot-contribution,
html.portfolio-print-light .position-snapshot-active-label,
html.portfolio-print-light .position-snapshot-empty {
    color: #64748b !important;
}
html.portfolio-print-light .summary-card-value,
html.portfolio-print-light .position-snapshot-detail-title,
html.portfolio-print-light .position-snapshot-cell {
    color: #1e293b !important;
}
html.portfolio-print-light .position-snapshot-detail-value,
html.portfolio-print-light .position-snapshot-cell--number,
html.portfolio-print-light .position-snapshot-active-value {
    color: #1d4ed8 !important;
}
html.portfolio-print-light .position-snapshot-detail {
    background: #ffffff !important;
    border-color: #cbd5e1 !important;
}
html.portfolio-print-light .position-snapshot-item {
    background: #f8fafc !important;
    border-color: #cbd5e1 !important;
}
html.portfolio-print-light .position-snapshot-item.active {
    border-color: #2563eb !important;
    box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.28) !important;
    background: #eff6ff !important;
}
html.portfolio-print-light .position-snapshot-item.active::before {
    opacity: 1;
}
html.portfolio-print-light .position-snapshot-item--pos {
    border-color: rgba(220, 38, 38, 0.75) !important;
    box-shadow: inset 0 0 0 1px rgba(220, 38, 38, 0.15) !important;
    background: #fff1f2 !important;
}
html.portfolio-print-light .position-snapshot-item--pos.active {
    border-color: #dc2626 !important;
    box-shadow: inset 0 0 0 1px rgba(220, 38, 38, 0.25) !important;
    background: #ffe4e6 !important;
}
html.portfolio-print-light .position-snapshot-item--neg {
    border-color: rgba(5, 150, 105, 0.75) !important;
    box-shadow: inset 0 0 0 1px rgba(5, 150, 105, 0.15) !important;
    background: #ecfdf5 !important;
}
html.portfolio-print-light .position-snapshot-item--neg.active {
    border-color: #059669 !important;
    box-shadow: inset 0 0 0 1px rgba(5, 150, 105, 0.25) !important;
    background: #d1fae5 !important;
}
html.portfolio-print-light .position-snapshot-item--flat {
    border-color: #94a3b8 !important;
    background: #f8fafc !important;
}
`.trim();

    function readSavedState() {
        try {
            return sessionStorage.getItem(STORAGE_KEY) === "1";
        } catch (_) {
            return false;
        }
    }

    function saveState(on) {
        try {
            if (on) {
                sessionStorage.setItem(STORAGE_KEY, "1");
            } else {
                sessionStorage.removeItem(STORAGE_KEY);
            }
        } catch (_) {
            /* ignore */
        }
    }

    function getIframeDocument(frame) {
        try {
            return frame.contentDocument || (frame.contentWindow && frame.contentWindow.document) || null;
        } catch (_) {
            return null;
        }
    }

    function injectIframeStyles(doc) {
        if (!doc || doc.getElementById(STYLE_ID)) {
            return;
        }
        const style = doc.createElement("style");
        style.id = STYLE_ID;
        style.textContent = IFRAME_INLINE_CSS;
        doc.head.appendChild(style);
    }

    function bindIframeToggle(doc, toggleFn) {
        const btn = doc.getElementById(TOGGLE_ID);
        if (!btn || btn.dataset.resultPrintBound === "1") {
            return Boolean(btn);
        }
        btn.dataset.resultPrintBound = "1";
        btn.addEventListener(
            "click",
            (event) => {
                event.preventDefault();
                event.stopPropagation();
                event.stopImmediatePropagation();
                toggleFn();
            },
            true
        );
        return true;
    }

    function initResultPrintLight(frame) {
        let printLightOn = readSavedState();
        let iframeReady = false;
        let useIframeFallback = false;

        function applyPrintLight(on) {
            printLightOn = Boolean(on);
            saveState(printLightOn);

            document.documentElement.classList.toggle(OUTER_HTML_CLASS, printLightOn);
            frame.classList.toggle(FRAME_FALLBACK_CLASS, printLightOn && useIframeFallback);

            const doc = getIframeDocument(frame);
            if (doc) {
                injectIframeStyles(doc);
                doc.documentElement.classList.toggle(IFRAME_HTML_CLASS, printLightOn);
                const btn = doc.getElementById(TOGGLE_ID);
                if (btn) {
                    btn.classList.toggle("is-on", printLightOn);
                    btn.setAttribute("aria-pressed", printLightOn ? "true" : "false");
                }
            }

            try {
                const win = frame.contentWindow;
                if (win && typeof win.applyPortfolioPrintLight === "function") {
                    win.applyPortfolioPrintLight(printLightOn);
                } else if (win && typeof win.setPortfolioPrintLightCharts === "function") {
                    win.setPortfolioPrintLightCharts(printLightOn);
                }
            } catch (_) {
                /* ignore */
            }
        }

        function trySetupIframe(attempt) {
            const doc = getIframeDocument(frame);
            if (!doc) {
                if (attempt < 80) {
                    window.setTimeout(() => trySetupIframe(attempt + 1), 200);
                } else {
                    useIframeFallback = true;
                    applyPrintLight(printLightOn);
                }
                return;
            }

            injectIframeStyles(doc);
            const bound = bindIframeToggle(doc, () => {
                applyPrintLight(!printLightOn);
            });

            if (!bound && attempt < 80) {
                window.setTimeout(() => trySetupIframe(attempt + 1), 200);
                return;
            }

            if (!bound) {
                useIframeFallback = true;
            }

            iframeReady = true;
            applyPrintLight(printLightOn);
        }

        frame.addEventListener("load", () => {
            trySetupIframe(0);
        });

        if (frame.src) {
            trySetupIframe(0);
        }

        return applyPrintLight;
    }

    window.initResultPrintLight = initResultPrintLight;
})();
