(function () {
    "use strict";

    const COLORS = ["#26a69a", "#6b9cff", "#f59e0b", "#b58cff", "#ff7f9f", "#8be28b"];
    const SERIES_START = Date.UTC(2018, 0, 1) / 1000;
    const DAY_SECONDS = 24 * 60 * 60;
    const DEFAULT_ZOOM = 1.25;
    const ZOOM_STEPS = [1, 1.1, DEFAULT_ZOOM, 1.4, 1.5];
    const ZOOM_STORAGE_KEY = "model-validity.zoom";
    const chartRegistry = [];

    function buildDemoSeries(index, count = 240) {
        const offset = Number(index) || 0;
        return Array.from({ length: count }, (_, pointIndex) => {
            const wave = Math.sin((pointIndex + offset * 7) / 9.5) * 1.5;
            const cycle = Math.cos((pointIndex + offset * 3) / 24) * 0.9;
            const drift = pointIndex * (0.018 + offset * 0.002);
            return {
                time: SERIES_START + pointIndex * DAY_SECONDS,
                value: Number((100 + offset * 2 + wave + cycle + drift).toFixed(4)),
            };
        });
    }

    function buildChartOptions() {
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
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 4,
                barSpacing: 4,
                fixLeftEdge: true,
                fixRightEdge: true,
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
                vertTouchDrag: false,
            },
            handleScale: {
                axisPressedMouseMove: true,
                mouseWheel: true,
                pinch: true,
            },
        };
    }

    function buildSeriesOptions(color) {
        return {
            color,
            lineWidth: 2,
            crosshairMarkerVisible: true,
            crosshairMarkerRadius: 3,
            lastValueVisible: true,
            priceLineVisible: false,
            priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        };
    }

    function renderChart(mount, series, index) {
        if (!mount || !window.LightweightCharts || !Array.isArray(series) || series.length < 2) {
            return null;
        }
        const chart = window.LightweightCharts.createChart(mount, buildChartOptions());
        const lineSeries = chart.addSeries(window.LightweightCharts.LineSeries, buildSeriesOptions(COLORS[index % COLORS.length]));
        lineSeries.setData(series);
        chart.timeScale().fitContent();
        chartRegistry.push(chart);
        return chart;
    }

    function updateClock() {
        const clock = document.getElementById("page-clock");
        if (!clock) {
            return;
        }
        const now = new Date();
        const date = now.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
        const time = now.toLocaleTimeString("zh-CN", { hour12: false });
        clock.textContent = `${date} ${time}`;
    }

    function readStoredZoom() {
        try {
            const stored = Number(window.localStorage.getItem(ZOOM_STORAGE_KEY));
            return ZOOM_STEPS.includes(stored) ? stored : DEFAULT_ZOOM;
        } catch (_) {
            return DEFAULT_ZOOM;
        }
    }

    function persistZoom(zoom) {
        try {
            window.localStorage.setItem(ZOOM_STORAGE_KEY, String(zoom));
        } catch (_) {
            /* Private browsing or restricted storage should not block controls. */
        }
    }

    function initPageZoom() {
        const content = document.querySelector(".model-validity-zoom-content");
        const decrease = document.getElementById("model-validity-zoom-decrease");
        const reset = document.getElementById("model-validity-zoom-reset");
        const increase = document.getElementById("model-validity-zoom-increase");
        const value = document.getElementById("model-validity-zoom-value");
        if (!content || !decrease || !reset || !increase || !value) {
            return;
        }

        let currentZoom = DEFAULT_ZOOM;
        const applyZoom = (zoom, shouldPersist = true) => {
            const nextZoom = ZOOM_STEPS.includes(zoom) ? zoom : DEFAULT_ZOOM;
            currentZoom = nextZoom;
            content.style.setProperty("--model-validity-zoom", String(nextZoom));
            content.style.width = "100%";
            content.style.minHeight = `${(100 / nextZoom).toFixed(4)}vh`;
            value.textContent = `${Math.round(nextZoom * 100)}%`;
            const stepIndex = ZOOM_STEPS.indexOf(nextZoom);
            decrease.disabled = stepIndex <= 0;
            increase.disabled = stepIndex >= ZOOM_STEPS.length - 1;
            if (shouldPersist) {
                persistZoom(nextZoom);
            }
            window.requestAnimationFrame(() => {
                chartRegistry.forEach((chart) => {
                    try {
                        chart.resize(0, 0);
                    } catch (_) {
                        /* autoSize handles normal browser resizes */
                    }
                });
            });
        };

        decrease.addEventListener("click", () => {
            const index = ZOOM_STEPS.indexOf(currentZoom);
            applyZoom(ZOOM_STEPS[Math.max(0, index - 1)]);
        });
        reset.addEventListener("click", () => applyZoom(DEFAULT_ZOOM));
        increase.addEventListener("click", () => {
            const index = ZOOM_STEPS.indexOf(currentZoom);
            applyZoom(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, index + 1)]);
        });
        applyZoom(readStoredZoom(), false);
    }

    function init() {
        initPageZoom();
        for (let index = 0; index < 6; index += 1) {
            renderChart(document.getElementById(`chart-${index}`), buildDemoSeries(index), index);
        }
        updateClock();
        window.setInterval(updateClock, 1000);
        if (typeof window.initEdgeFloatHud === "function") {
            window.initEdgeFloatHud({ pageId: "model-validity", onNavigate: window.edgeFloatNavigateToPage });
        }
    }

    window.addEventListener("resize", () => {
        chartRegistry.forEach((chart) => {
            try {
                chart.resize(0, 0);
            } catch (_) {
                /* autoSize handles normal browser resizes */
            }
        });
    });

    window.ModelValidity = { buildDemoSeries, renderChart };
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
