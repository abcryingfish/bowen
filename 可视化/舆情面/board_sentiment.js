/* 舆情面 — 暂无数据，展示维护中 */

(function () {
    function renderMaintenanceState() {
        const main = document.getElementById("sentiment-content");
        const side = document.getElementById("right-panel-body");
        if (main) {
            main.innerHTML = `<div class="sentiment-maintenance" role="status">维护中</div>`;
        }
        if (side) {
            side.innerHTML = "";
        }
    }

    window.ChartBoardView = {
        id: "sentiment",
        label: "舆情面",
        init() {
            renderMaintenanceState();
        },
        onCodeChange() {
            renderMaintenanceState();
        },
    };
})();
