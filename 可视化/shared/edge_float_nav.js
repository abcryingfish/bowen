/**
 * 三页悬浮球互跳：index / 结果展示 / result，不展示当前页入口。
 */
(function (global) {
    const PAGES = [
        { id: "chart", file: "../量化因子/index.html", label: "打开 K 线主页面" },
        { id: "results", file: "../结果展示/index.html", label: "打开成果展示页" },
        { id: "portfolio", file: "../组合结果/index.html", label: "打开组合结果页" },
        { id: "live", file: "../实盘面/index.html", label: "打开实盘页面" },
    ];

    const PARAM_KEYS = ["api", "api_base", "code"];

    function navigateToPage(filename) {
        const name = String(filename || "").trim();
        if (!name) {
            return;
        }
        const cluster = global.document && global.document.getElementById
            ? global.document.getElementById("edge-float-cluster")
            : null;
        if (global.EdgeFloatHud && typeof global.EdgeFloatHud.persistHudPosition === "function") {
            global.EdgeFloatHud.persistHudPosition(cluster);
        }
        try {
            const cur = new URL(global.location.href);
            const next = new URL(name, cur.href);
            for (const key of PARAM_KEYS) {
                const v = cur.searchParams.get(key);
                if (v && !next.searchParams.get(key)) {
                    next.searchParams.set(key, v);
                }
            }
            global.location.href = next.href;
            return;
        } catch (_) {
            /* file:// 或相对路径回退 */
        }
        const href = global.location.href.split("#")[0].split("?")[0];
        const slash = Math.max(href.lastIndexOf("/"), href.lastIndexOf("\\"));
        const base = slash >= 0 ? href.slice(0, slash + 1) : href;
        const q = global.location.search || "";
        const hash = global.location.hash || "";
        global.location.href = `${base}${name}${q}${hash}`;
    }

    function onMenuButtonActivate(event, file, navigateFn, onAfterNavigate) {
        event.preventDefault();
        event.stopPropagation();
        const go = typeof navigateFn === "function" ? navigateFn : navigateToPage;
        go(file);
        if (typeof onAfterNavigate === "function") {
            onAfterNavigate();
        }
    }

    function renderMenu(menuEl, currentPageId, navigateFn, onAfterNavigate) {
        if (!menuEl) {
            return;
        }
        const current = String(currentPageId || "").trim();
        const go = typeof navigateFn === "function" ? navigateFn : navigateToPage;
        menuEl.replaceChildren();
        for (const page of PAGES) {
            if (page.id === current) {
                continue;
            }
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "edge-float-menu-btn field btn";
            btn.setAttribute("role", "menuitem");
            btn.textContent = page.label;
            const file = page.file;
            btn.addEventListener("click", (event) => onMenuButtonActivate(event, file, go, onAfterNavigate));
            btn.addEventListener("pointerdown", (event) => {
                if (event.button === 0) {
                    event.stopPropagation();
                }
            });
            menuEl.appendChild(btn);
        }
    }

    /** @deprecated 使用 renderMenu 内联绑定 */
    function bindMenuNavigate(menuEl, navigateFn, onAfterNavigate) {
        if (!menuEl) {
            return;
        }
        renderMenu(menuEl, "", navigateFn, onAfterNavigate);
    }

    global.edgeFloatNavigateToPage = navigateToPage;
    global.EdgeFloatNav = {
        PAGES,
        navigateToPage,
        renderMenu,
        bindMenuNavigate,
    };
})(window);
