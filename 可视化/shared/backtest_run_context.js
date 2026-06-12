/**
 * 跨页共享当前选中的回测 run_tag（sessionStorage，关闭浏览器后清空）。
 */
(function (global) {
    const ACTIVE_RUN_TAG_KEY = "active_backtest_run_tag_v1";
    const ACTIVE_RUN_LABEL_KEY = "active_backtest_run_label_v1";

    function getActiveRunTag() {
        try {
            return String(sessionStorage.getItem(ACTIVE_RUN_TAG_KEY) || "").trim();
        } catch (_) {
            return "";
        }
    }

    function getActiveRunLabel() {
        try {
            const label = String(sessionStorage.getItem(ACTIVE_RUN_LABEL_KEY) || "").trim();
            return label || getActiveRunTag();
        } catch (_) {
            return getActiveRunTag();
        }
    }

    function setActiveRun(runTag, label) {
        const tag = String(runTag || "").trim();
        if (!tag) {
            clearActiveRun();
            return;
        }
        try {
            sessionStorage.setItem(ACTIVE_RUN_TAG_KEY, tag);
            sessionStorage.setItem(ACTIVE_RUN_LABEL_KEY, String(label || tag).trim() || tag);
        } catch (_) {
            /* ignore */
        }
    }

    function clearActiveRun() {
        try {
            sessionStorage.removeItem(ACTIVE_RUN_TAG_KEY);
            sessionStorage.removeItem(ACTIVE_RUN_LABEL_KEY);
        } catch (_) {
            /* ignore */
        }
    }

    function syncActiveRunFromUrl(searchParams) {
        const sp = searchParams || new URLSearchParams(global.location.search || "");
        const tag = String(sp.get("run_tag") || "").trim();
        if (tag) {
            setActiveRun(tag, String(sp.get("run_label") || "").trim() || tag);
        }
    }

    global.BacktestRunContext = {
        ACTIVE_RUN_TAG_KEY,
        ACTIVE_RUN_LABEL_KEY,
        getActiveRunTag,
        getActiveRunLabel,
        setActiveRun,
        clearActiveRun,
        syncActiveRunFromUrl,
    };
})(typeof window !== "undefined" ? window : globalThis);
