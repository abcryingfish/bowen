/**
 * 侧边悬浮球拖拽与菜单逻辑。
 * 依赖 edge_float_nav.js。
 */
(function (global) {
    const EDGE_FLOAT_HUD_POS_KEY = "edgeFloatHudPos";
    const PAD = 10;
    const CLUSTER_SIZE = 52;

    function isClusterVisible(cluster) {
        if (!cluster) {
            return false;
        }
        const st = global.getComputedStyle(cluster);
        if (st.display === "none" || st.visibility === "hidden") {
            return false;
        }
        return cluster.offsetWidth > 0 && cluster.offsetHeight > 0;
    }

    function parseStylePx(cluster, prop) {
        const v = parseFloat(cluster.style[prop]);
        return Number.isFinite(v) ? v : null;
    }

    function readClusterPos(cluster) {
        const r = cluster.getBoundingClientRect();
        const styleLeft = parseStylePx(cluster, "left");
        const styleTop = parseStylePx(cluster, "top");
        let left = r.left;
        let top = r.top;
        const w = r.width || cluster.offsetWidth || CLUSTER_SIZE;
        const h = r.height || cluster.offsetHeight || CLUSTER_SIZE;
        if (
            styleLeft != null &&
            styleTop != null &&
            (w === 0 || h === 0 || (Math.abs(left) < 1 && Math.abs(top) < 1 && (styleLeft > 1 || styleTop > 1)))
        ) {
            left = styleLeft;
            top = styleTop;
        }
        return { left, top, width: w, height: h };
    }

    function clampHudPos(left, top, cluster) {
        const w = cluster.offsetWidth || CLUSTER_SIZE;
        const h = cluster.offsetHeight || CLUSTER_SIZE;
        const vw = global.innerWidth;
        const vh = global.innerHeight;
        const maxL = Math.max(PAD, vw - w - PAD);
        const maxT = Math.max(PAD, vh - h - PAD);
        return {
            left: Math.min(Math.max(PAD, left), maxL),
            top: Math.min(Math.max(PAD, top), maxT),
        };
    }

    function loadSavedHudPos() {
        try {
            const raw = global.localStorage.getItem(EDGE_FLOAT_HUD_POS_KEY);
            if (!raw) {
                return null;
            }
            const p = JSON.parse(raw);
            const left = Number(p.left);
            const top = Number(p.top);
            if (!Number.isFinite(left) || !Number.isFinite(top)) {
                return null;
            }
            // 嵌入 iframe 时浮标会隐藏，旧逻辑可能把 10,10 写入 localStorage。
            if (left <= PAD + 1 && top <= PAD + 1) {
                return null;
            }
            return {
                left,
                top,
                dock: p.dock === "left" ? "left" : "right",
            };
        } catch (_) {
            return null;
        }
    }

    function saveHudPos(left, top, dock) {
        if (!Number.isFinite(left) || !Number.isFinite(top)) {
            return;
        }
        if (left < 0 || top < 0) {
            return;
        }
        try {
            global.localStorage.setItem(
                EDGE_FLOAT_HUD_POS_KEY,
                JSON.stringify({ left, top, dock: dock === "left" ? "left" : "right" }),
            );
        } catch (_) {
            /* ignore */
        }
    }
    /** 跳转前保存当前 DOM 位置，避免下一页读到旧值或 0,0 吸附结果。 */
    function persistHudPosition(cluster) {
        if (!cluster || !isClusterVisible(cluster)) {
            return;
        }
        const pos = readClusterPos(cluster);
        if (pos.width <= 0 || pos.height <= 0) {
            return;
        }
        const c = clampHudPos(pos.left, pos.top, cluster);
        const dock = cluster.dataset.dock === "left" ? "left" : "right";
        saveHudPos(c.left, c.top, dock);
    }

    function initEdgeFloatHud(options) {
        const pageId = (options && options.pageId) || "chart";
        const cluster = document.getElementById("edge-float-cluster");
        const hud = document.getElementById("edge-float-hud");
        const menu = document.getElementById("edge-float-menu");
        if (!cluster || !hud) {
            return;
        }
        if (!isClusterVisible(cluster)) {
            return;
        }

        const navigateFn =
            options && typeof options.onNavigate === "function"
                ? options.onNavigate
                : global.edgeFloatNavigateToPage;
        let drag = false;
        let ptrId = null;
        let sx = 0;
        let sy = 0;
        let ox = 0;
        let oy = 0;
        let menuHideTimer = null;

        function hideMenuImmediate() {
            if (menuHideTimer != null) {
                clearTimeout(menuHideTimer);
                menuHideTimer = null;
            }
            if (menu) {
                menu.classList.remove("is-open");
                menu.setAttribute("aria-hidden", "true");
            }
        }

        function scheduleHideMenu() {
            if (menuHideTimer != null) {
                clearTimeout(menuHideTimer);
            }
            menuHideTimer = global.setTimeout(() => {
                menuHideTimer = null;
                hideMenuImmediate();
            }, 400);
        }

        function positionMenu() {
            if (!menu || !menu.classList.contains("is-open")) {
                return;
            }
            const r = cluster.getBoundingClientRect();
            const dock = cluster.dataset.dock === "left" ? "left" : "right";
            const gap = 4;
            menu.style.display = "flex";
            const mw = menu.offsetWidth || 168;
            const mh = menu.offsetHeight || 160;
            let left;
            if (dock === "left") {
                left = r.right + gap;
            } else {
                left = r.left - gap - mw;
            }
            let top = r.top + r.height / 2 - mh / 2;
            top = Math.min(Math.max(8, top), global.innerHeight - mh - 8);
            left = Math.min(Math.max(8, left), global.innerWidth - mw - 8);
            menu.style.left = `${Math.round(left)}px`;
            menu.style.top = `${Math.round(top)}px`;
            menu.style.right = "auto";
            menu.style.bottom = "auto";
        }

        function showMenu() {
            if (!menu || drag) {
                return;
            }
            if (menuHideTimer != null) {
                clearTimeout(menuHideTimer);
                menuHideTimer = null;
            }
            menu.classList.add("is-open");
            menu.setAttribute("aria-hidden", "false");
            requestAnimationFrame(() => {
                requestAnimationFrame(positionMenu);
            });
        }

        let snapTransTimer = null;
        let menuFollowRaf = null;

        function stopMenuFollowRaf() {
            if (menuFollowRaf != null) {
                cancelAnimationFrame(menuFollowRaf);
                menuFollowRaf = null;
            }
        }

        function startMenuFollowRaf() {
            stopMenuFollowRaf();
            const tick = () => {
                if (menu && menu.classList.contains("is-open")) {
                    positionMenu();
                    menuFollowRaf = requestAnimationFrame(tick);
                } else {
                    menuFollowRaf = null;
                }
            };
            menuFollowRaf = requestAnimationFrame(tick);
        }

        function applyHorizontalEdgeSnap(snapOptions = {}) {
            if (!isClusterVisible(cluster)) {
                return false;
            }
            const animateSnap = Boolean(snapOptions.animateSnap);
            const pos = readClusterPos(cluster);
            if (pos.width <= 0 || pos.height <= 0) {
                return false;
            }
            const vw = global.innerWidth;
            const vh = global.innerHeight;
            const centerX = pos.left + pos.width / 2;
            const snapLeft = centerX < vw / 2;
            const dock = snapLeft ? "left" : "right";
            cluster.dataset.dock = dock;
            const left = snapLeft ? PAD : vw - cluster.offsetWidth - PAD;
            const top = Math.min(
                Math.max(PAD, pos.top),
                Math.max(PAD, vh - cluster.offsetHeight - PAD),
            );

            const applyPos = () => {
                if (!isClusterVisible(cluster)) {
                    return;
                }
                cluster.style.left = `${Math.round(left)}px`;
                cluster.style.top = `${Math.round(top)}px`;
                cluster.style.right = "auto";
                cluster.style.bottom = "auto";
                saveHudPos(left, top, dock);
                if (menu && menu.classList.contains("is-open")) {
                    positionMenu();
                }
            };

            if (snapTransTimer != null) {
                clearTimeout(snapTransTimer);
                snapTransTimer = null;
            }
            stopMenuFollowRaf();

            if (animateSnap) {
                cluster.style.transition =
                    "left 0.52s cubic-bezier(0.22, 0.82, 0.28, 1), top 0.52s cubic-bezier(0.22, 0.82, 0.28, 1)";
                requestAnimationFrame(() => {
                    requestAnimationFrame(applyPos);
                });
                if (menu && menu.classList.contains("is-open")) {
                    startMenuFollowRaf();
                }
                snapTransTimer = global.setTimeout(() => {
                    cluster.style.transition = "";
                    snapTransTimer = null;
                    stopMenuFollowRaf();
                    if (menu && menu.classList.contains("is-open")) {
                        positionMenu();
                    }
                }, 560);
            } else {
                cluster.style.transition = "none";
                applyPos();
            }
            return true;
        }

        function placeDefault() {
            const vw = global.innerWidth;
            const vh = global.innerHeight;
            const w = cluster.offsetWidth || CLUSTER_SIZE;
            const h = cluster.offsetHeight || CLUSTER_SIZE;
            cluster.style.left = `${Math.round(vw - w - PAD)}px`;
            cluster.style.top = `${Math.round((vh - h) / 2)}px`;
            cluster.style.right = "auto";
            cluster.style.bottom = "auto";
            cluster.dataset.dock = "right";
        }

        const saved = loadSavedHudPos();
        if (saved) {
            const c = clampHudPos(saved.left, saved.top, cluster);
            cluster.style.left = `${Math.round(c.left)}px`;
            cluster.style.top = `${Math.round(c.top)}px`;
            cluster.style.right = "auto";
            cluster.style.bottom = "auto";
            cluster.dataset.dock = saved.dock;
        } else {
            placeDefault();
        }

        let layoutSnapAttempts = 0;
        const scheduleLayoutSnap = () => {
            if (layoutSnapAttempts >= 12) {
                return;
            }
            layoutSnapAttempts += 1;
            requestAnimationFrame(() => {
                if (!isClusterVisible(cluster)) {
                    return;
                }
                const ok = applyHorizontalEdgeSnap({ animateSnap: false });
                if (!ok) {
                    scheduleLayoutSnap();
                }
            });
        };
        scheduleLayoutSnap();

        cluster.addEventListener("mouseenter", () => {
            showMenu();
        });
        cluster.addEventListener("mouseleave", (e) => {
            const rel = e.relatedTarget;
            if (rel && menu && (menu === rel || menu.contains(rel))) {
                return;
            }
            scheduleHideMenu();
        });

        if (menu) {
            menu.addEventListener("mouseenter", () => {
                if (menuHideTimer != null) {
                    clearTimeout(menuHideTimer);
                    menuHideTimer = null;
                }
                showMenu();
            });
            menu.addEventListener("mouseleave", (e) => {
                const rel = e.relatedTarget;
                if (rel && (cluster === rel || cluster.contains(rel))) {
                    return;
                }
                scheduleHideMenu();
            });
            if (global.EdgeFloatNav) {
                global.EdgeFloatNav.renderMenu(menu, pageId, navigateFn, hideMenuImmediate);
            }
        }

        hud.addEventListener("pointerdown", (e) => {
            if (e.button !== 0) {
                return;
            }
            hideMenuImmediate();
            cluster.style.transition = "none";
            drag = true;
            ptrId = e.pointerId;
            hud.setPointerCapture(ptrId);
            const r = cluster.getBoundingClientRect();
            sx = e.clientX;
            sy = e.clientY;
            ox = r.left;
            oy = r.top;
            e.preventDefault();
        });

        hud.addEventListener("pointermove", (e) => {
            if (!drag || e.pointerId !== ptrId) {
                return;
            }
            cluster.style.transition = "none";
            const nx = ox + (e.clientX - sx);
            const ny = oy + (e.clientY - sy);
            const maxL = global.innerWidth - cluster.offsetWidth - PAD;
            const maxT = global.innerHeight - cluster.offsetHeight - PAD;
            const cx = Math.min(Math.max(PAD, nx), Math.max(PAD, maxL));
            const cy = Math.min(Math.max(PAD, ny), Math.max(PAD, maxT));
            cluster.style.left = `${Math.round(cx)}px`;
            cluster.style.top = `${Math.round(cy)}px`;
            cluster.style.right = "auto";
            cluster.style.bottom = "auto";
            const vw = global.innerWidth;
            cluster.dataset.dock = cx + cluster.offsetWidth / 2 < vw / 2 ? "left" : "right";
            if (menu && menu.classList.contains("is-open")) {
                positionMenu();
            }
        });

        const endDrag = (e) => {
            if (!drag || (ptrId != null && e.pointerId !== ptrId)) {
                return;
            }
            drag = false;
            try {
                hud.releasePointerCapture(ptrId);
            } catch (_) {
                /* ignore */
            }
            ptrId = null;
            applyHorizontalEdgeSnap({ animateSnap: true });
        };

        hud.addEventListener("pointerup", endDrag);
        hud.addEventListener("pointercancel", endDrag);

        global.addEventListener("resize", () => {
            if (!isClusterVisible(cluster)) {
                return;
            }
            applyHorizontalEdgeSnap({ animateSnap: false });
        });

        global.addEventListener("beforeunload", () => {
            persistHudPosition(cluster);
        });

        global.addEventListener("pagehide", () => {
            persistHudPosition(cluster);
        });
    }

    global.EdgeFloatHud = {
        EDGE_FLOAT_HUD_POS_KEY,
        persistHudPosition,
        isClusterVisible,
    };
    global.initEdgeFloatHud = initEdgeFloatHud;
})(window);

