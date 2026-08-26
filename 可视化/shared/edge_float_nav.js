/**
 * Edge floating HUD page navigation.
 */
(function (global) {
    const PAGES = [
        { id: "chart", file: "../%E9%87%8F%E5%8C%96%E5%9B%A0%E5%AD%90/index.html", label: "\u91cf\u5316\u56e0\u5b50" },
        { id: "factor-validation", file: "../%E9%87%8F%E5%8C%96%E5%9B%A0%E5%AD%90%E6%9C%89%E6%95%88%E6%80%A7%E6%A3%80%E9%AA%8C/dashboard.html", label: "\u91cf\u5316\u56e0\u5b50\u6709\u6548\u6027\u68c0\u9a8c" },
        { id: "results", file: "../%E7%BB%93%E6%9E%9C%E5%B1%95%E7%A4%BA/index.html", label: "\u6210\u679c\u5c55\u793a" },
        { id: "portfolio", file: "../%E7%BB%84%E5%90%88%E7%BB%93%E6%9E%9C/index.html", label: "\u7ec4\u5408\u7ed3\u679c" },
        { id: "live", file: "../%E5%AE%9E%E7%9B%98%E9%9D%A2/index.html", label: "\u5b9e\u76d8\u9762" },
        { id: "multi-dimensional-analysis", file: "../%E5%A4%9A%E7%BB%B4%E5%BA%A6%E5%88%86%E6%9E%90/index.html", label: "\u591a\u7ef4\u5ea6\u5206\u6790" },
        { id: "model-validity", file: "../%E6%A8%A1%E5%9E%8B%E6%9C%89%E6%95%88%E6%80%A7/index.html", label: "\u4e2a\u80a1\u98ce\u683c\u6a21\u578b\u6709\u6548\u6027" },
        { id: "sector-rotation", file: "../%E6%9D%BF%E5%9D%97%E8%BD%AE%E5%8A%A8/index.html", label: "\u677f\u5757\u8f6e\u52a8" },
        { id: "market-research", file: "../%E5%B8%82%E5%9C%BA%E7%A0%94%E7%A9%B6/index.html", label: "\u5e02\u573a\u7814\u7a76" },
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
            /* file:// fallback */
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

    /** @deprecated Use renderMenu. */
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
