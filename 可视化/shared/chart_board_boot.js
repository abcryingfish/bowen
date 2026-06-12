/* 看板启动：须在 base + board_*.js 之后加载 */
(function () {
    if (typeof window.ChartBoardBoot !== "function" || window.__chartBoardBooted) {
        return;
    }
    window.__chartBoardBooted = true;
    void window.ChartBoardBoot();
})();
