(function () {
    "use strict";

    const SECTOR_CODE = "881101.THS";
    const TREND_LOOKBACK_BARS = 240;
    const DEFAULT_VISIBLE_BARS = 120;
    const MIN_ANCHOR_SPAN = 8;
    const INTERSECTION_TOLERANCE = 0.002;
    const TOUCH_TOLERANCE = 0.006;
    const MAX_CURRENT_DISTANCE = 0.15;
    const MAX_TREND_LINES_PER_DIRECTION = 3;
    const FIB_LEVELS = [
        { ratio: 0, label: "0%", color: "rgba(184, 190, 200, .95)" },
        { ratio: 0.236, label: "23.6%", color: "rgba(78, 168, 222, .95)" },
        { ratio: 0.382, label: "38.2%", color: "rgba(42, 177, 160, .95)" },
        { ratio: 0.5, label: "50%", color: "rgba(239, 204, 112, .95)" },
        { ratio: 0.618, label: "61.8%", color: "rgba(248, 169, 105, .95)" },
        { ratio: 0.786, label: "78.6%", color: "rgba(239, 120, 88, .95)" },
        { ratio: 1, label: "100%", color: "rgba(184, 190, 200, .95)" },
    ];
    const query = new URLSearchParams(window.location.search);

    function resolveApiBase() {
        const candidates = [query.get("api_base"), query.get("api")];
        try {
            candidates.push(localStorage.getItem("RESULTS_API_BASE"));
            candidates.push(localStorage.getItem("API_BASE_URL"));
        } catch (_) {
            // 本地配置不可用时，继续按当前页面地址推断。
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
        if (window.location.protocol === "http:") return `http://${window.location.hostname}:8000`;
        return "http://127.0.0.1:8000";
    }

    function normalizeBars(rows) {
        return (Array.isArray(rows) ? rows : [])
            .map((row) => ({
                time: Number(row.time),
                open: Number(row.open),
                high: Number(row.high),
                low: Number(row.low),
                close: Number(row.close),
            }))
            .filter((bar) => Object.values(bar).every(Number.isFinite))
            .sort((left, right) => left.time - right.time);
    }

    function updateSummary(bar, previousBar) {
        const node = document.getElementById("quote-summary");
        if (!node || !bar) return;
        const change = previousBar?.close ? (bar.close / previousBar.close - 1) * 100 : 0;
        node.className = `quote-summary ${change >= 0 ? "positive" : "negative"}`;
        node.textContent = `收 ${bar.close.toFixed(2)}  ${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
    }

    function findSwingPoints(bars, leftBars = 5, rightBars = 5) {
        const swingLows = [];
        const swingHighs = [];
        for (let index = leftBars; index < bars.length - rightBars; index += 1) {
            const current = bars[index];
            const left = bars.slice(index - leftBars, index);
            const right = bars.slice(index + 1, index + rightBars + 1);
            const leftLowest = Math.min(...left.map((bar) => bar.low));
            const rightLowest = Math.min(...right.map((bar) => bar.low));
            const leftHighest = Math.max(...left.map((bar) => bar.high));
            const rightHighest = Math.max(...right.map((bar) => bar.high));
            if (current.low < leftLowest && current.low < rightLowest) {
                swingLows.push({ index, value: current.low, time: current.time });
            }
            if (current.high > leftHighest && current.high > rightHighest) {
                swingHighs.push({ index, value: current.high, time: current.time });
            }
        }
        return { swingLows, swingHighs };
    }

    function trendValueAtIndex(anchor, other, index) {
        const span = other.index - anchor.index;
        if (!span) return anchor.value;
        return anchor.value + (other.value - anchor.value) * ((index - anchor.index) / span);
    }

    function crossesPriceBetweenAnchors(bars, anchors, direction) {
        const [older, newer] = anchors;
        for (let index = older.index + 1; index < newer.index; index += 1) {
            const lineValue = trendValueAtIndex(older, newer, index);
            if (direction === "up" && bars[index].low < lineValue * (1 - INTERSECTION_TOLERANCE)) return true;
            if (direction === "down" && bars[index].high > lineValue * (1 + INTERSECTION_TOLERANCE)) return true;
        }
        return false;
    }

    function countTrendTouches(points, anchors) {
        const [older, newer] = anchors;
        return points.filter((point) => {
            if (point.index < older.index) return false;
            const lineValue = trendValueAtIndex(older, newer, point.index);
            return Math.abs(point.value - lineValue) / Math.max(1, Math.abs(lineValue)) <= TOUCH_TOLERANCE;
        }).length;
    }

    function findTwoCloseBreakIndex(bars, anchors, direction) {
        const [older, newer] = anchors;
        let previousBroken = false;
        for (let index = newer.index + 1; index < bars.length; index += 1) {
            const trendValue = trendValueAtIndex(older, newer, index);
            const broken = direction === "up"
                ? bars[index].close < trendValue
                : bars[index].close > trendValue;
            if (broken && previousBroken) return index;
            previousBroken = broken;
        }
        return null;
    }

    function selectTrendCandidates(bars, points, direction) {
        const firstIndex = Math.max(5, bars.length - TREND_LOOKBACK_BARS);
        const visiblePoints = points.filter((point) => point.index >= firstIndex);
        const currentClose = bars[bars.length - 1].close;
        const selected = [];
        for (let newerIndex = visiblePoints.length - 1; newerIndex > 0; newerIndex -= 1) {
            const newer = visiblePoints[newerIndex];
            const candidates = [];
            for (let olderIndex = newerIndex - 1; olderIndex >= 0; olderIndex -= 1) {
                const older = visiblePoints[olderIndex];
                const span = newer.index - older.index;
                const hasExpectedSlope = direction === "up"
                    ? newer.value > older.value
                    : newer.value < older.value;
                if (!hasExpectedSlope || span < MIN_ANCHOR_SPAN) continue;
                const anchors = [older, newer];
                if (crossesPriceBetweenAnchors(bars, anchors, direction)) continue;
                const breakIndex = findTwoCloseBreakIndex(bars, anchors, direction);
                const referenceIndex = breakIndex ?? bars.length - 1;
                const referenceValue = trendValueAtIndex(older, newer, referenceIndex);
                const referenceClose = breakIndex === null ? currentClose : bars[referenceIndex].close;
                const currentDistance = Math.abs(referenceClose - referenceValue) / Math.max(1, Math.abs(referenceClose));
                if (referenceValue <= 0 || (breakIndex === null && currentDistance > MAX_CURRENT_DISTANCE)) continue;
                candidates.push({
                    anchors,
                    touchCount: countTrendTouches(visiblePoints, anchors),
                    currentDistance,
                    span,
                    breakIndex,
                });
            }
            if (candidates.length) {
                candidates.sort((left, right) =>
                    right.touchCount - left.touchCount
                    || right.span - left.span
                    || left.currentDistance - right.currentDistance
                );
                selected.push(candidates[0]);
                if (selected.length >= MAX_TREND_LINES_PER_DIRECTION) break;
            }
        }
        return selected;
    }

    function makeFutureBusinessTimes(lastTime, count) {
        const times = [];
        let candidate = lastTime;
        while (times.length < count) {
            candidate += 86400;
            const weekday = new Date(candidate * 1000).getUTCDay();
            if (weekday !== 0 && weekday !== 6) times.push(candidate);
        }
        return times;
    }

    function makeTrendData(bars, candidate, futureBars = 20) {
        if (!candidate) return [];
        const [anchor, latest] = candidate.anchors;
        const finalHistoryIndex = candidate.breakIndex === null
            ? bars.length - 1
            : Math.min(bars.length - 1, candidate.breakIndex + 3);
        const data = bars.slice(anchor.index, finalHistoryIndex + 1).map((bar, offset) => ({
            time: bar.time,
            value: trendValueAtIndex(anchor, latest, anchor.index + offset),
        }));
        if (candidate.breakIndex === null) {
            makeFutureBusinessTimes(bars[bars.length - 1].time, futureBars).forEach((time, offset) => {
                data.push({
                    time,
                    value: trendValueAtIndex(anchor, latest, bars.length + offset),
                });
            });
        }
        return data;
    }

    function trendColor(direction, invalid, rank) {
        const opacity = [1, 0.85, 0.7][rank] || 0.6;
        if (invalid) return `rgba(154, 162, 174, ${opacity})`;
        return direction === "up"
            ? `rgba(240, 164, 75, ${opacity})`
            : `rgba(109, 156, 255, ${opacity})`;
    }

    function setTrendState(id, text) {
        const node = document.getElementById(id);
        if (node) node.textContent = text;
    }

    function selectFibonacciWave(bars, swingLows, swingHighs) {
        const firstIndex = Math.max(5, bars.length - TREND_LOOKBACK_BARS);
        const points = [
            ...swingLows.map((point) => ({ ...point, type: "low" })),
            ...swingHighs.map((point) => ({ ...point, type: "high" })),
        ].filter((point) => point.index >= firstIndex)
            .sort((left, right) => left.index - right.index);
        for (let endIndex = points.length - 1; endIndex > 0; endIndex -= 1) {
            const end = points[endIndex];
            for (const minimumMove of [0.15, 0.08]) {
                for (let startIndex = endIndex - 1; startIndex >= 0; startIndex -= 1) {
                    const start = points[startIndex];
                    const span = end.index - start.index;
                    const move = Math.abs(end.value - start.value) / Math.max(1, Math.abs(start.value));
                    if (start.type !== end.type && span >= MIN_ANCHOR_SPAN && move >= minimumMove) {
                        return {
                            start,
                            end,
                            direction: end.value > start.value ? "up" : "down",
                        };
                    }
                }
            }
        }
        return null;
    }

    function addFibonacciRetracement(chart, candlesticks, bars, swingLows, swingHighs) {
        const wave = selectFibonacciWave(bars, swingLows, swingHighs);
        const summary = document.getElementById("fib-summary");
        if (!wave) {
            if (summary) summary.textContent = "FIB · 当前窗口无合格波段";
            return;
        }
        const futureTimes = makeFutureBusinessTimes(bars[bars.length - 1].time, 20);
        const times = [
            ...bars.slice(wave.start.index).map((bar) => bar.time),
            ...futureTimes,
        ];
        FIB_LEVELS.forEach((level) => {
            const value = wave.end.value + (wave.start.value - wave.end.value) * level.ratio;
            const boundary = level.ratio === 0 || level.ratio === 1;
            const series = chart.addSeries(window.LightweightCharts.LineSeries, {
                color: level.color,
                lineWidth: boundary ? 3 : 2,
                lineStyle: boundary ? window.LightweightCharts.LineStyle.Solid : window.LightweightCharts.LineStyle.Dashed,
                priceLineVisible: false,
                lastValueVisible: true,
                title: level.label,
            });
            series.setData(times.map((time) => ({ time, value })));
        });
        window.LightweightCharts.createSeriesMarkers(candlesticks, [
            {
                time: wave.start.time,
                position: wave.start.type === "high" ? "aboveBar" : "belowBar",
                color: "#e9c46a",
                shape: wave.start.type === "high" ? "arrowDown" : "arrowUp",
                text: "Fib 起点",
            },
            {
                time: wave.end.time,
                position: wave.end.type === "high" ? "aboveBar" : "belowBar",
                color: "#e9c46a",
                shape: wave.end.type === "high" ? "arrowDown" : "arrowUp",
                text: "Fib 终点",
            },
        ]);
        if (summary) {
            const startDate = new Date(wave.start.time * 1000).toISOString().slice(0, 10);
            const endDate = new Date(wave.end.time * 1000).toISOString().slice(0, 10);
            summary.textContent = `FIB · ${wave.direction === "up" ? "上升" : "下降"}波段 · ${startDate} ${wave.start.value.toFixed(2)} → ${endDate} ${wave.end.value.toFixed(2)}`;
        }
    }

    function addTrendLines(chart, bars, swingLows, swingHighs) {
        const groups = [
            { direction: "up", candidates: selectTrendCandidates(bars, swingLows, "up"), stateId: "uptrend-state", swatch: ".trend-up" },
            { direction: "down", candidates: selectTrendCandidates(bars, swingHighs, "down"), stateId: "downtrend-state", swatch: ".trend-down" },
        ];
        groups.forEach(({ direction, candidates, stateId, swatch }) => {
            candidates.forEach((candidate, rank) => {
                const invalid = candidate.breakIndex !== null;
                const confirmed = candidate.touchCount >= 3;
                const color = trendColor(direction, invalid, rank);
                const series = chart.addSeries(window.LightweightCharts.LineSeries, {
                    color,
                    lineWidth: rank === 0 ? 3 : 2,
                    lineStyle: confirmed ? window.LightweightCharts.LineStyle.Solid : window.LightweightCharts.LineStyle.Dashed,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
                series.setData(makeTrendData(bars, candidate));
                window.LightweightCharts.createSeriesMarkers(series, candidate.anchors.map((point) => ({
                    time: point.time,
                    position: "inBar",
                    color,
                    shape: "circle",
                    size: rank === 0 ? 1 : 0.7,
                })));
            });
            const activeCount = candidates.filter((candidate) => candidate.breakIndex === null).length;
            const confirmedCount = candidates.filter((candidate) => candidate.touchCount >= 3).length;
            const status = candidates.length
                ? `${candidates.length}根 · ${activeCount}有效 · ${confirmedCount}确认`
                : "近期无合格线";
            setTrendState(stateId, status);
            if (candidates.length && activeCount === 0) document.querySelector(swatch)?.classList.add("invalid");
        });
    }

    async function loadChart() {
        const mount = document.getElementById("kline-chart");
        const chartState = document.getElementById("chart-state");
        try {
            if (!window.LightweightCharts) throw new Error("图表组件加载失败");
            const now = Math.floor(Date.now() / 1000);
            const from = now - 365 * 10 * 86400;
            const params = new URLSearchParams({ code: SECTOR_CODE, from: String(from), to: String(now), limit: "3000" });
            const response = await fetch(`${resolveApiBase()}/api/market/index/bars?${params.toString()}`, { cache: "no-store" });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
            const bars = normalizeBars(payload.bars);
            if (!bars.length) throw new Error("该板块暂无可用日 K 数据");

            const chart = window.LightweightCharts.createChart(mount, {
                autoSize: true,
                layout: { background: { color: "#13161b" }, textColor: "#aeb4be", fontSize: 11, attributionLogo: false },
                grid: { vertLines: { color: "#20242a" }, horzLines: { color: "#20242a" } },
                rightPriceScale: { borderColor: "#343942", scaleMargins: { top: 0.08, bottom: 0.08 } },
                timeScale: { borderColor: "#343942", timeVisible: false, rightOffset: 2, barSpacing: 7, minBarSpacing: 1 },
                crosshair: {
                    mode: window.LightweightCharts.CrosshairMode.Normal,
                    vertLine: { color: "rgba(174,180,190,.35)", style: window.LightweightCharts.LineStyle.Dashed, labelBackgroundColor: "#4c5668" },
                    horzLine: { color: "rgba(174,180,190,.35)", style: window.LightweightCharts.LineStyle.Dashed, labelBackgroundColor: "#4c5668" },
                },
                handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
                handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
            });
            const candlesticks = chart.addSeries(window.LightweightCharts.CandlestickSeries, {
                upColor: "#ef5350",
                downColor: "#26a69a",
                borderVisible: false,
                wickUpColor: "#ef5350",
                wickDownColor: "#26a69a",
                priceLineVisible: false,
            });
            candlesticks.setData(bars);
            const { swingLows, swingHighs } = findSwingPoints(bars, 5, 5);
            addFibonacciRetracement(chart, candlesticks, bars, swingLows, swingHighs);
            addTrendLines(chart, bars, swingLows, swingHighs);
            chart.timeScale().setVisibleLogicalRange({
                from: Math.max(0, bars.length - DEFAULT_VISIBLE_BARS),
                to: bars.length + 19,
            });
            updateSummary(bars[bars.length - 1], bars[bars.length - 2]);
            chartState.classList.add("is-hidden");
        } catch (error) {
            chartState.classList.add("error");
            chartState.textContent = `行情读取失败：${error.message}`;
        }
    }

    window.addEventListener("DOMContentLoaded", loadChart, { once: true });
}());
