/* 回测面板与模型 — 在 chart_board_core.js 之后加载（舆情/基本面页可省略） */

        function showBacktestValidationError(message) {
            const text = String(message || "").trim() || "回测参数无效";
            logUiHint(text);
            showBacktestModal({
                status: "failed",
                stage: "参数校验",
                progress: 0,
                message: text,
                log_tail: [text],
            });
        }

        function applyBacktestModelsFromList(models) {
            const list = Array.isArray(models) && models.length ? models : BACKTEST_MODEL_FALLBACK;
            if (!Array.isArray(models) || !models.length) {
                logUiHint("回测模型目录为空或不可用，已使用内置列表（与 model_registry 对齐）。");
            }
            BACKTEST_MODEL_CATALOG = list;
            const nextDoc = {};
            for (const m of list) {
                const id = String(m.id || "");
                if (!id) {
                    continue;
                }
                let html = String(m.description_html || "");
                if (m.web_runnable === false) {
                    html += "<p><em>此项不支持网页一键回测，请使用本地脚本。</em></p>";
                }
                nextDoc[id] = {
                    title: String(m.title || id),
                    html,
                };
            }
            const hz = nextDoc.hong_ziming_avg_position;
            if (hz) {
                nextDoc.__default__ = {
                    title: "默认（洪梓铭平均仓位）",
                    html:
                        "<p><em>与「洪梓铭平均仓位模型」相同：<code>adopt_model</code> 为空时服务侧采用该模型。</em></p>" +
                        hz.html,
                };
            }
            BACKTEST_MODEL_DOC = nextDoc;
        }

        async function loadBacktestModelsCatalog() {
            let models = [];
            try {
                const res = await fetch(`${API_BASE_URL}/api/backtest/models`, { method: "GET", cache: "no-store" });
                const data = res.ok ? await res.json().catch(() => ({})) : {};
                if (!res.ok) {
                    logUiHint(
                        "回测模型目录接口 HTTP " +
                        res.status +
                        "，将使用内置列表。请确认 api_server 已启动且路径为 /api/backtest/models。"
                    );
                }
                models = data && Array.isArray(data.models) ? data.models : [];
            } catch (err) {
                logUiHint("加载回测模型目录失败，将使用内置列表: " + (err && err.message ? err.message : String(err)));
                models = [];
            }
            applyBacktestModelsFromList(models);
        }

        function buildBacktestModelListHtml() {
            const model = String(backtestRules.adoptModel || "");
            const selCls = (v) => (model === v ? " is-selected" : "");
            const parts = [];
            parts.push(
                `<div class="center-backtest-model-option${selCls("")}" role="option" data-model-id="" tabindex="0">默认（洪梓铭平均仓位）</div>`
            );
            for (const m of BACKTEST_MODEL_CATALOG) {
                const id = String(m.id || "");
                if (!id) {
                    continue;
                }
                const suffix = m.web_runnable === false ? " · 仅本地" : "";
                const label = `${escapeHtml(String(m.title || id))}${escapeHtml(suffix)}`;
                parts.push(
                    `<div class="center-backtest-model-option${selCls(id)}" role="option" data-model-id="${escapeHtml(id)}" tabindex="0">${label}</div>`
                );
            }
            return parts.join("");
        }

        let modelOverlayHideTimer = null;

        function cancelModelOverlayHideTimer() {
            if (modelOverlayHideTimer !== null) {
                clearTimeout(modelOverlayHideTimer);
                modelOverlayHideTimer = null;
            }
        }

        function scheduleHideModelOverlay(delayMs = 120) {
            cancelModelOverlayHideTimer();
            modelOverlayHideTimer = setTimeout(() => {
                modelOverlayHideTimer = null;
                hideRightPanelModelOverlay();
            }, delayMs);
        }

        function isRightPanelModelOverlayVisible() {
            const overlay = document.getElementById("right-panel-model-overlay");
            return Boolean(overlay && overlay.classList.contains("visible"));
        }

        function hideRightPanelModelOverlay() {
            cancelModelOverlayHideTimer();
            const overlay = document.getElementById("right-panel-model-overlay");
            if (!overlay) {
                return;
            }
            overlay.classList.remove("visible");
            overlay.setAttribute("aria-hidden", "true");
        }

        function showRightPanelModelOverlayForModel(modelId) {
            cancelModelOverlayHideTimer();
            const overlay = document.getElementById("right-panel-model-overlay");
            const titleEl = document.getElementById("right-panel-model-overlay-title");
            const bodyEl = document.getElementById("right-panel-model-overlay-body");
            if (!overlay || !titleEl || !bodyEl) {
                return;
            }
            const docKey = modelId === "" ? "__default__" : modelId;
            const doc = BACKTEST_MODEL_DOC[docKey];
            if (!doc) {
                titleEl.textContent = modelId || "模型说明";
                bodyEl.innerHTML = "<p>暂无该模型的说明（占位）。</p>";
            } else {
                titleEl.textContent = doc.title;
                bodyEl.innerHTML = doc.html;
            }
            overlay.classList.add("visible");
            overlay.setAttribute("aria-hidden", "false");
        }

        function installRightPanelModelOverlayHandlers() {
            const overlay = document.getElementById("right-panel-model-overlay");
            if (overlay && overlay.dataset.boundHoverBridge !== "1") {
                overlay.dataset.boundHoverBridge = "1";
                overlay.addEventListener("mouseenter", () => {
                    cancelModelOverlayHideTimer();
                });
                overlay.addEventListener("mouseleave", (event) => {
                    const to = event.relatedTarget;
                    const list = document.getElementById("center-backtest-model-list");
                    if (list && to instanceof Node && list.contains(to)) {
                        return;
                    }
                    hideRightPanelModelOverlay();
                });
            }
        }

        document.addEventListener(
            "keydown",
            (event) => {
                if (event.key !== "Escape") {
                    return;
                }
                if (!isRightPanelModelOverlayVisible()) {
                    return;
                }
                event.preventDefault();
                hideRightPanelModelOverlay();
            },
            true
        );

        function shouldShowBacktestSummaryPanel(codeValue = currentCode) {
            return POSITION_SNAPSHOT_CODES.has(normalizeCodeValue(codeValue));
        }
        function shouldUseBacktestPositionSnapshotPanel(codeValue = currentCode) {
            return POSITION_SNAPSHOT_CODES.has(normalizeCodeValue(codeValue));
        }
        function shouldShowTraverseRuleThresholds() {
            return paramTraverseSwitchOn && String(backtestRules.adoptModel || "").trim() === "configurable_signal_rules";
        }

        function ensureTraverseFieldsOnRule(rule) {
            const th = Number(rule.threshold);
            const t = Number.isFinite(th) ? th : 1;
            let lo = Number(rule.threshold_lo);
            let hi = Number(rule.threshold_hi);
            if (!Number.isFinite(lo)) {
                lo = t - Math.max(Math.abs(t) * 0.15, 1e-6);
            }
            if (!Number.isFinite(hi)) {
                hi = t + Math.max(Math.abs(t) * 0.15, 1e-6);
            }
            if (hi <= lo) {
                hi = lo + 0.01;
            }
            rule.threshold_lo = lo;
            rule.threshold_hi = hi;
            let st = Number(rule.threshold_step);
            if (!Number.isFinite(st) || st <= 0) {
                const span = hi - lo;
                st = Math.max(span / 20, 0.01);
            }
            rule.threshold_step = st;
        }

        function ensureAllRulesTraverseFields() {
            if (!shouldShowTraverseRuleThresholds()) {
                return;
            }
            backtestRules.buy.forEach(ensureTraverseFieldsOnRule);
            backtestRules.sell.forEach(ensureTraverseFieldsOnRule);
        }

        function renderBacktestRuleBox(side) {
            const isBuy = side === "buy";
            const title = isBuy ? "买入因子" : "卖出因子";
            const rules = isBuy ? backtestRules.buy : backtestRules.sell;
            const traverseUi = shouldShowTraverseRuleThresholds();
            const itemsHtml = rules.length
                ? rules.map((rule, index) => {
                    if (traverseUi) {
                        ensureTraverseFieldsOnRule(rule);
                        const lo = escapeHtml(String(rule.threshold_lo));
                        const hi = escapeHtml(String(rule.threshold_hi));
                        const st = escapeHtml(String(rule.threshold_step));
                        return `
                    <div class="backtest-rule-item backtest-rule-item-traverse" data-backtest-rule-side="${side}" data-backtest-rule-index="${index}">
                        <div class="backtest-rule-name" title="${escapeHtml(rule.factor)}">${escapeHtml(rule.factor)}</div>
                        <div class="backtest-rule-traverse-row" title="参数寻优：仅在区间内按步长取值">
                            <label>下<input class="field backtest-rule-threshold-lo" type="number" step="any" value="${lo}"></label>
                            <label>上<input class="field backtest-rule-threshold-hi" type="number" step="any" value="${hi}"></label>
                            <label>步长<input class="field backtest-rule-threshold-step" type="number" step="any" value="${st}" title="阈值只取 下界 + n×步长"></label>
                        </div>
                        <button class="field btn backtest-rule-remove" type="button" title="删除因子">×</button>
                    </div>
                `;
                    }
                    return `
                    <div class="backtest-rule-item" data-backtest-rule-side="${side}" data-backtest-rule-index="${index}">
                        <div class="backtest-rule-name" title="${escapeHtml(rule.factor)}">${escapeHtml(rule.factor)}</div>
                        <input class="field backtest-rule-threshold" type="number" step="0.0001" value="${escapeHtml(String(rule.threshold))}" title="触发阈值：因子值 >= 阈值">
                        <button class="field btn backtest-rule-remove" type="button" title="删除因子">×</button>
                    </div>
                `;
                }).join("")
                : `<div class="backtest-rule-empty">${title}</div>`;
            return `
                <div class="backtest-rule-box">
                    <div class="backtest-rule-drop-zone${rules.length ? "" : " empty"}" data-backtest-rule-side="${side}" title="拖入后按因子值 >= 阈值触发">
                        ${itemsHtml}
                    </div>
                </div>
            `;
        }

        function renderBacktestSymbolBox(note = "") {
            const value = escapeHtml(backtestRules.codesText || "");
            const model = String(backtestRules.adoptModel || "");
            const selCls = (v) => (model === v ? " is-selected" : "");
            const hintLeft = note ? `<div class="backtest-symbol-hint">${escapeHtml(note)}</div>` : "";
            return `
                <div class="backtest-symbol-box">
                    <div class="backtest-symbol-columns">
                        <div class="backtest-symbol-column">
                            <textarea id="center-backtest-codes" class="field backtest-symbol-input" placeholder="回测标的 · 多标的 — 一行一个代码，逗号/空格分隔" autocomplete="off">${value}</textarea>
                            ${hintLeft}
                        </div>
                        <div class="backtest-symbol-column">
                            <div class="backtest-model-field">
                                <div id="center-backtest-model-list" class="center-backtest-model-list" role="listbox" aria-label="采用模型（悬停预览说明，点击选中）">
                                    ${buildBacktestModelListHtml()}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        function renderBacktestLeftColumnHtml() {
            return `
                <div class="center-bottom-box">${renderBacktestRuleBox("buy")}</div>
                <div class="center-bottom-box">${renderBacktestRuleBox("sell")}</div>
            `;
        }

        function countStrongSubsetCombos(n) {
            const k = Number(n) || 0;
            if (k <= 0) {
                return 0;
            }
            return (2 ** k) - 1;
        }

        function countStrongExhaustiveCombos(nBuy, nSell) {
            return countStrongSubsetCombos(nBuy) * countStrongSubsetCombos(nSell);
        }

        function refreshOptunaControlsVisibility() {
            const row = centerBottomPanel ? centerBottomPanel.querySelector(".center-bottom-optuna-row") : null;
            if (!row) {
                return;
            }
            const mid = String(backtestRules.adoptModel || "").trim();
            const show =
                paramTraverseSwitchOn &&
                (mid === "configurable_signal_rules" || mid === "zxw_strong_adjusted_only");
            if (paramTraverseSwitchOn && (
                mid === "zxw_factor_check_only"
                || mid === "zxw_factor_check_no_lookahead"
                || mid === "zxw_factor_check_dual_assumption"
            )) {
                row.style.display = "none";
                return;
            }
            row.style.display = show ? "flex" : "none";
            const trialsLabel = row.querySelector(".optuna-trials-label");
            const noteEl = row.querySelector(".optuna-mode-note");
            const isStrong = mid === "zxw_strong_adjusted_only";
            if (trialsLabel) {
                trialsLabel.style.display = isStrong ? "none" : "inline-flex";
            }
            if (noteEl) {
                if (isStrong) {
                    const nBuy = backtestRules.buy.length;
                    const nSell = backtestRules.sell.length;
                    const buySub = countStrongSubsetCombos(nBuy);
                    const sellSub = countStrongSubsetCombos(nSell);
                    const total = countStrongExhaustiveCombos(nBuy, nSell);
                    let note =
                        `强点：穷举 ${total} 组（买 ${nBuy}→${buySub} × 卖 ${nSell}→${sellSub}）；`
                        + "_卖… 仅影响止盈，止损用宽表总卖出信号";
                    if (nSell <= 1) {
                        note += "；卖出仅 1 个因子时卖出侧只有 1 种子集";
                    }
                    noteEl.textContent = note;
                } else {
                    noteEl.textContent =
                        "可配置：Optuna 遍历因子阈值区间；强点请选「只采用强点交易策略」";
                }
            }
        }

        function renderCenterBottomBacktestControls(summaryPath = "") {
            const titleAttr = summaryPath ? ` title="数据来源：${escapeHtml(summaryPath)}"` : "";
            const buyOperatorVisible = backtestRules.buy.length >= 2 ? " visible" : "";
            const sellOperatorVisible = backtestRules.sell.length >= 2 ? " visible" : "";
            const fromYearValue = escapeHtml(String(backtestRules.fromYear || ""));
            const fromMonthValue = escapeHtml(String(backtestRules.fromMonth || ""));
            const fromDayValue = escapeHtml(String(backtestRules.fromDay || ""));
            const toYearValue = escapeHtml(String(backtestRules.toYear || ""));
            const toMonthValue = escapeHtml(String(backtestRules.toMonth || ""));
            const toDayValue = escapeHtml(String(backtestRules.toDay || ""));
            return `
                <div class="center-bottom-backtest-row"${titleAttr}>
                    <span class="center-bottom-backtest-label">from</span>
                    <div class="date-group center-bottom-backtest-group">
                        <input id="center-backtest-from-year" class="field date-part year center-bottom-backtest-date-part" type="text" inputmode="numeric" maxlength="4" placeholder="YYYY" value="${fromYearValue}" autocomplete="off">
                        <span class="date-sep">-</span>
                        <input id="center-backtest-from-month" class="field date-part center-bottom-backtest-date-part" type="text" inputmode="numeric" maxlength="2" placeholder="MM" value="${fromMonthValue}" autocomplete="off">
                        <span class="date-sep">-</span>
                        <input id="center-backtest-from-day" class="field date-part center-bottom-backtest-date-part" type="text" inputmode="numeric" maxlength="2" placeholder="DD" value="${fromDayValue}" autocomplete="off">
                    </div>
                    <span class="center-bottom-backtest-sep">to</span>
                    <div class="date-group center-bottom-backtest-group">
                        <input id="center-backtest-to-year" class="field date-part year center-bottom-backtest-date-part" type="text" inputmode="numeric" maxlength="4" placeholder="YYYY" value="${toYearValue}" autocomplete="off">
                        <span class="date-sep">-</span>
                        <input id="center-backtest-to-month" class="field date-part center-bottom-backtest-date-part" type="text" inputmode="numeric" maxlength="2" placeholder="MM" value="${toMonthValue}" autocomplete="off">
                        <span class="date-sep">-</span>
                        <input id="center-backtest-to-day" class="field date-part center-bottom-backtest-date-part" type="text" inputmode="numeric" maxlength="2" placeholder="DD" value="${toDayValue}" autocomplete="off">
                    </div>
                    <input id="center-backtest-run-name" class="field center-bottom-backtest-name" type="text" maxlength="30" placeholder="名称（保存时由服务端加日期前缀）" value="${escapeHtml(backtestRules.runName || "")}" autocomplete="off">
                    <label class="backtest-operator-group${buyOperatorVisible}">
                        买入
                        <select id="center-backtest-buy-operator" class="field backtest-operator-select">
                            <option value="and"${backtestRules.buyOperator === "and" ? " selected" : ""}>AND</option>
                            <option value="or"${backtestRules.buyOperator === "or" ? " selected" : ""}>OR</option>
                        </select>
                    </label>
                    <label class="backtest-operator-group${sellOperatorVisible}">
                        卖出
                        <select id="center-backtest-sell-operator" class="field backtest-operator-select">
                            <option value="and"${backtestRules.sellOperator === "and" ? " selected" : ""}>AND</option>
                            <option value="or"${backtestRules.sellOperator === "or" ? " selected" : ""}>OR</option>
                        </select>
                    </label>
                    <button id="btn-center-run-backtest" class="field btn center-bottom-backtest-btn" type="button">回测</button>
                </div>
                <div class="center-bottom-backtest-row center-bottom-optuna-row" style="display:none; flex-wrap:wrap; align-items:center; gap:8px; margin-top:6px;">
                    <span class="center-bottom-backtest-label">Optuna</span>
                    <label class="optuna-trials-label" style="display:inline-flex; align-items:center; gap:4px;">trials
                        <input id="center-backtest-n-trials" class="field center-bottom-backtest-date-part" type="number" min="2" max="5000" step="1" value="${Number(backtestRules.nTrials) || 20}" style="width:4.5em;">
                    </label>
                    <label style="display:inline-flex; align-items:center; gap:4px;">目标字段
                        <input id="center-backtest-objective-key" class="field" type="text" value="${escapeHtml(String(backtestRules.objectiveKey || "夏普比率"))}" style="width:7em;" autocomplete="off">
                    </label>
                    <label style="display:inline-flex; align-items:center; gap:4px;">方向
                        <select id="center-backtest-objective-direction" class="field backtest-operator-select">
                            <option value="maximize"${String(backtestRules.objectiveDirection || "maximize") === "maximize" ? " selected" : ""}>最大化</option>
                            <option value="minimize"${String(backtestRules.objectiveDirection || "") === "minimize" ? " selected" : ""}>最小化</option>
                        </select>
                    </label>
                    <span class="optuna-mode-note summary-panel-note" style="margin:0;">「可配置信号规则」：遍历因子阈值区间；「强点交易策略」：穷举买入×卖出子集</span>
                </div>
            `;
        }

        function renderBacktestRulePanels() {
            const leftColumn = centerBottomPanel ? centerBottomPanel.querySelector(".center-bottom-column-left") : null;
            if (leftColumn) {
                leftColumn.innerHTML = renderBacktestLeftColumnHtml();
                bindBacktestRulePanels();
            }
            const buyOperatorEl = document.getElementById("center-backtest-buy-operator");
            const sellOperatorEl = document.getElementById("center-backtest-sell-operator");
            if (buyOperatorEl) {
                buyOperatorEl.closest(".backtest-operator-group")?.classList.toggle("visible", backtestRules.buy.length >= 2);
            }
            if (sellOperatorEl) {
                sellOperatorEl.closest(".backtest-operator-group")?.classList.toggle("visible", backtestRules.sell.length >= 2);
            }
            refreshOptunaControlsVisibility();
        }

        function addBacktestRule(side, factorName) {
            const target = side === "sell" ? backtestRules.sell : backtestRules.buy;
            const normalizedName = String(factorName || "").trim();
            if (!normalizedName) {
                return;
            }
            if (target.some((item) => item.factor === normalizedName)) {
                logUiHint(`${normalizedName} 已在${side === "sell" ? "卖出" : "买入"}因子中`);
                return;
            }
            target.push({ factor: normalizedName, threshold: 1 });
            if (shouldShowTraverseRuleThresholds()) {
                const last = target[target.length - 1];
                ensureTraverseFieldsOnRule(last);
            }
            renderBacktestRulePanels();
        }

        function addBacktestRules(side, factorNames) {
            const target = side === "sell" ? backtestRules.sell : backtestRules.buy;
            const existing = new Set(target.map((item) => item.factor));
            let addedCount = 0;
            for (const rawName of factorNames || []) {
                const factorName = String(rawName || "").trim();
                if (!factorName || existing.has(factorName)) {
                    continue;
                }
                existing.add(factorName);
                target.push({ factor: factorName, threshold: 1 });
                if (shouldShowTraverseRuleThresholds()) {
                    ensureTraverseFieldsOnRule(target[target.length - 1]);
                }
                addedCount += 1;
            }
            if (addedCount > 0) {
                renderBacktestRulePanels();
            } else {
                logUiHint("该组因子已全部在目标篮子中");
            }
        }

        function findBacktestRuleDropZoneAtPoint(clientX, clientY) {
            if (!centerBottomPanel) {
                return null;
            }
            const zones = centerBottomPanel.querySelectorAll(".backtest-rule-drop-zone");
            for (const zone of zones) {
                const rect = zone.getBoundingClientRect();
                if (
                    clientX >= rect.left &&
                    clientX <= rect.right &&
                    clientY >= rect.top &&
                    clientY <= rect.bottom
                ) {
                    return zone;
                }
            }
            return null;
        }

        function parseBacktestCodes(text) {
            const parts = String(text || "")
                .split(/[\s,，;；]+/)
                .map((item) => item.trim().toUpperCase())
                .filter(Boolean);
            return Array.from(new Set(parts));
        }

        function buildOptunaTemplateRules(rules, label) {
            return rules.map((rule) => {
                ensureTraverseFieldsOnRule(rule);
                const threshold = Number(rule.threshold);
                if (!Number.isFinite(threshold)) {
                    throw new Error(`${label}因子 ${rule.factor} 的参考阈值不是有效数字`);
                }
                const lo = Number(rule.threshold_lo);
                const hi = Number(rule.threshold_hi);
                const st = Number(rule.threshold_step);
                if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) {
                    throw new Error(`${label}因子 ${rule.factor}：请设置有效区间（下限 < 上限）`);
                }
                if (!Number.isFinite(st) || st <= 0) {
                    throw new Error(`${label}因子 ${rule.factor}：步长须为正数`);
                }
                if (st > hi - lo + 1e-12) {
                    throw new Error(`${label}因子 ${rule.factor}：步长不能大于区间长度`);
                }
                return {
                    factor: rule.factor,
                    threshold,
                    threshold_lo: lo,
                    threshold_hi: hi,
                    threshold_step: st,
                };
            });
        }

        function buildBacktestPayload(fromDate, toDate) {
            const codesInput = document.getElementById("center-backtest-codes");
            backtestRules.codesText = codesInput ? codesInput.value : backtestRules.codesText;
            const codes = parseBacktestCodes(backtestRules.codesText);
            if (!codes.length) {
                throw new Error("请先输入至少一个回测标的");
            }
            const adopt_model = backtestRules.adoptModel ? String(backtestRules.adoptModel).trim() : "";
            const isStrongAdjusted = adopt_model === "zxw_strong_adjusted_only";
            const isFactorCheck =
                adopt_model === "zxw_factor_check_only"
                || adopt_model === "zxw_factor_check_no_lookahead"
                || adopt_model === "zxw_factor_check_dual_assumption";
            if (isFactorCheck) {
                if (paramTraverseSwitchOn) {
                    throw new Error("因子检验模型不支持参数遍历，请关闭参数遍历开关");
                }
                if (!backtestRules.buy.length) {
                    throw new Error("因子检验模型请至少拖入一个买入因子");
                }
                if (!backtestRules.sell.length) {
                    throw new Error("因子检验模型请至少拖入一个卖出因子");
                }
            } else if (isStrongAdjusted) {
                if (!backtestRules.buy.length) {
                    throw new Error("强点模型请至少拖入一个买入因子");
                }
                if (
                    paramTraverseSwitchOn &&
                    !backtestRules.sell.length
                ) {
                    throw new Error("强点参数遍历请至少拖入一个卖出因子");
                }
            } else {
                if (!backtestRules.buy.length) {
                    throw new Error("请至少拖入一个买入因子");
                }
                if (!backtestRules.sell.length) {
                    throw new Error("请至少拖入一个卖出因子");
                }
            }
            const normalizeRules = (rules, label) => rules.map((rule) => {
                const threshold = Number(rule.threshold);
                if (!Number.isFinite(threshold)) {
                    throw new Error(`${label}因子 ${rule.factor} 的阈值不是有效数字`);
                }
                return { factor: rule.factor, threshold };
            });
            const runNameInput = document.getElementById("center-backtest-run-name");
            backtestRules.runName = runNameInput ? String(runNameInput.value || "").trim() : String(backtestRules.runName || "").trim();
            const payload = {
                codes,
                start_date: fromDate,
                end_date: toDate,
                run_name_base: backtestRules.runName,
                buy_operator: backtestRules.buyOperator,
                sell_operator: backtestRules.sellOperator,
                buy_rules: normalizeRules(backtestRules.buy, "买入"),
                sell_rules: normalizeRules(backtestRules.sell, "卖出"),
            };
            if (adopt_model) {
                payload.adopt_model = adopt_model;
            }
            if (
                paramTraverseSwitchOn &&
                (adopt_model === "configurable_signal_rules" || adopt_model === "zxw_strong_adjusted_only")
            ) {
                const ntEl = document.getElementById("center-backtest-n-trials");
                const okEl = document.getElementById("center-backtest-objective-key");
                const dirEl = document.getElementById("center-backtest-objective-direction");
                if (okEl) {
                    backtestRules.objectiveKey = String(okEl.value || "夏普比率");
                }
                if (dirEl) {
                    backtestRules.objectiveDirection = dirEl.value === "minimize" ? "minimize" : "maximize";
                }
                payload.run_mode = "optuna";
                payload.objective_key = String(backtestRules.objectiveKey || "夏普比率").trim() || "夏普比率";
                payload.objective_direction = String(backtestRules.objectiveDirection || "maximize").trim().toLowerCase() === "minimize"
                    ? "minimize"
                    : "maximize";
                if (adopt_model === "configurable_signal_rules") {
                    if (ntEl) {
                        const v = Math.max(2, Math.min(5000, Number(ntEl.value) || 20));
                        backtestRules.nTrials = v;
                        ntEl.value = String(v);
                    }
                    payload.n_trials = Math.max(2, Math.min(5000, Number(backtestRules.nTrials) || 20));
                    payload.buy_rules = buildOptunaTemplateRules(backtestRules.buy, "买入");
                    payload.sell_rules = buildOptunaTemplateRules(backtestRules.sell, "卖出");
                } else if (adopt_model === "zxw_strong_adjusted_only") {
                    payload.exhaustive_buy_sell_subsets = true;
                    payload.buy_rules = normalizeRules(backtestRules.buy, "买入");
                    payload.sell_rules = normalizeRules(backtestRules.sell, "卖出");
                }
            }
            return payload;
        }

        function bindBacktestRulePanels() {
            const codesInput = document.getElementById("center-backtest-codes");
            if (codesInput && codesInput.dataset.bound !== "1") {
                codesInput.dataset.bound = "1";
                codesInput.addEventListener("input", () => {
                    backtestRules.codesText = codesInput.value;
                });
            }
            const modelList = document.getElementById("center-backtest-model-list");
            if (modelList && modelList.dataset.boundModelHover !== "1") {
                modelList.dataset.boundModelHover = "1";
                modelList.addEventListener("mouseover", (event) => {
                    const opt = event.target instanceof Element ? event.target.closest(".center-backtest-model-option") : null;
                    if (!opt || !modelList.contains(opt)) {
                        return;
                    }
                    cancelModelOverlayHideTimer();
                    // data-model-id="" 表示默认模型，空字符串是合法 id，不能用 !id 否则永远不显示说明
                    const id = opt.getAttribute("data-model-id");
                    const modelId = id === null ? "" : String(id);
                    showRightPanelModelOverlayForModel(modelId);
                });
                modelList.addEventListener("mouseleave", (event) => {
                    const to = event.relatedTarget;
                    const overlay = document.getElementById("right-panel-model-overlay");
                    if (overlay && to instanceof Node && overlay.contains(to)) {
                        return;
                    }
                    scheduleHideModelOverlay(100);
                });
                modelList.addEventListener("click", (event) => {
                    const opt = event.target instanceof Element ? event.target.closest(".center-backtest-model-option") : null;
                    if (!opt || !modelList.contains(opt)) {
                        return;
                    }
                    const id = String(opt.dataset.modelId || "");
                    backtestRules.adoptModel = id;
                    modelList.querySelectorAll(".center-backtest-model-option").forEach((el) => {
                        el.classList.toggle("is-selected", String(el.dataset.modelId || "") === id);
                    });
                    refreshOptunaControlsVisibility();
                    renderBacktestRulePanels();
                });
            }
            const zones = centerBottomPanel ? centerBottomPanel.querySelectorAll(".backtest-rule-drop-zone") : [];
            zones.forEach((zone) => {
                if (zone.dataset.bound === "1") {
                    return;
                }
                zone.dataset.bound = "1";
                zone.addEventListener("click", (event) => {
                    const removeBtn = event.target instanceof Element ? event.target.closest(".backtest-rule-remove") : null;
                    if (!removeBtn) {
                        return;
                    }
                    const item = removeBtn.closest(".backtest-rule-item");
                    const side = item ? String(item.getAttribute("data-backtest-rule-side") || "") : "";
                    const index = item ? Number(item.getAttribute("data-backtest-rule-index")) : -1;
                    const target = side === "sell" ? backtestRules.sell : backtestRules.buy;
                    if (index >= 0 && index < target.length) {
                        target.splice(index, 1);
                        renderBacktestRulePanels();
                    }
                });
                zone.addEventListener("input", (event) => {
                    const el = event.target;
                    if (!(el instanceof Element)) {
                        return;
                    }
                    const input = el.closest(
                        ".backtest-rule-threshold, .backtest-rule-threshold-lo, .backtest-rule-threshold-hi, .backtest-rule-threshold-step",
                    );
                    if (!input) {
                        return;
                    }
                    const item = input.closest(".backtest-rule-item");
                    const side = item ? String(item.getAttribute("data-backtest-rule-side") || "") : "";
                    const index = item ? Number(item.getAttribute("data-backtest-rule-index")) : -1;
                    const target = side === "sell" ? backtestRules.sell : backtestRules.buy;
                    if (index < 0 || index >= target.length) {
                        return;
                    }
                    if (input.classList.contains("backtest-rule-threshold")) {
                        target[index].threshold = input.value;
                    } else if (input.classList.contains("backtest-rule-threshold-lo")) {
                        target[index].threshold_lo = input.value;
                    } else if (input.classList.contains("backtest-rule-threshold-hi")) {
                        target[index].threshold_hi = input.value;
                    } else if (input.classList.contains("backtest-rule-threshold-step")) {
                        target[index].threshold_step = input.value;
                    }
                });
            });
        }

        function composeCenterBacktestDateValue(yearInput, monthInput, dayInput) {
            const year = keepDigits(yearInput.value, 4);
            const month = keepDigits(monthInput.value, 2);
            const day = keepDigits(dayInput.value, 2);
            if (!year || !month || !day) {
                return "";
            }
            return `${year.padStart(4, "0")}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
        }

        function handleCenterRunBacktestClick() {
            const fromYearInput = document.getElementById("center-backtest-from-year");
            const fromMonthInput = document.getElementById("center-backtest-from-month");
            const fromDayInput = document.getElementById("center-backtest-from-day");
            const toYearInput = document.getElementById("center-backtest-to-year");
            const toMonthInput = document.getElementById("center-backtest-to-month");
            const toDayInput = document.getElementById("center-backtest-to-day");
            if (!fromYearInput || !fromMonthInput || !fromDayInput || !toYearInput || !toMonthInput || !toDayInput) {
                showBacktestValidationError("回测面板尚未就绪，请稍候或刷新页面");
                return;
            }
            const fromDate = composeCenterBacktestDateValue(fromYearInput, fromMonthInput, fromDayInput);
            const toDate = composeCenterBacktestDateValue(toYearInput, toMonthInput, toDayInput);
            if (!fromDate || !toDate) {
                showBacktestValidationError("请先选择完整回测日期区间");
                return;
            }
            if (!isValidYyyyMmDd(fromDate) || !isValidYyyyMmDd(toDate)) {
                showBacktestValidationError("日期格式应为 yyyy-mm-dd，且需为有效日期");
                return;
            }
            if (fromDate > toDate) {
                showBacktestValidationError("开始日期不能晚于结束日期");
                return;
            }
            try {
                const payload = buildBacktestPayload(fromDate, toDate);
                void startBacktestJob(payload);
            } catch (err) {
                const message = err instanceof Error ? err.message : "回测参数无效";
                showBacktestValidationError(message);
            }
        }

        function installCenterBacktestClickDelegation() {
            if (!centerBottomPanel || centerBottomPanel.dataset.backtestClickDelegated === "1") {
                return;
            }
            centerBottomPanel.dataset.backtestClickDelegated = "1";
            centerBottomPanel.addEventListener("click", (event) => {
                const target = event.target;
                if (!(target instanceof Element)) {
                    return;
                }
                const btn = target.closest("#btn-center-run-backtest");
                if (!btn || !centerBottomPanel.contains(btn)) {
                    return;
                }
                event.preventDefault();
                handleCenterRunBacktestClick();
            });
        }

        function bindCenterBottomBacktestControls() {
            const fromYearInput = document.getElementById("center-backtest-from-year");
            const fromMonthInput = document.getElementById("center-backtest-from-month");
            const fromDayInput = document.getElementById("center-backtest-from-day");
            const toYearInput = document.getElementById("center-backtest-to-year");
            const toMonthInput = document.getElementById("center-backtest-to-month");
            const toDayInput = document.getElementById("center-backtest-to-day");
            const runBtn = document.getElementById("btn-center-run-backtest");
            const buyOperatorEl = document.getElementById("center-backtest-buy-operator");
            const sellOperatorEl = document.getElementById("center-backtest-sell-operator");
            const runNameInput = document.getElementById("center-backtest-run-name");
            bindBacktestRulePanels();
            if (buyOperatorEl && buyOperatorEl.dataset.bound !== "1") {
                buyOperatorEl.dataset.bound = "1";
                buyOperatorEl.addEventListener("change", () => {
                    backtestRules.buyOperator = buyOperatorEl.value === "or" ? "or" : "and";
                });
            }
            if (sellOperatorEl && sellOperatorEl.dataset.bound !== "1") {
                sellOperatorEl.dataset.bound = "1";
                sellOperatorEl.addEventListener("change", () => {
                    backtestRules.sellOperator = sellOperatorEl.value === "or" ? "or" : "and";
                });
            }
            if (runNameInput && runNameInput.dataset.bound !== "1") {
                runNameInput.dataset.bound = "1";
                runNameInput.addEventListener("input", () => {
                    backtestRules.runName = String(runNameInput.value || "");
                });
            }
            const nTrialsInputEarly = document.getElementById("center-backtest-n-trials");
            if (nTrialsInputEarly && nTrialsInputEarly.dataset.boundOptuna !== "1") {
                nTrialsInputEarly.dataset.boundOptuna = "1";
                nTrialsInputEarly.addEventListener("change", () => {
                    const v = Math.max(2, Math.min(5000, Number(nTrialsInputEarly.value) || 20));
                    backtestRules.nTrials = v;
                    nTrialsInputEarly.value = String(v);
                });
            }
            const objectiveKeyInputEarly = document.getElementById("center-backtest-objective-key");
            if (objectiveKeyInputEarly && objectiveKeyInputEarly.dataset.boundOptuna !== "1") {
                objectiveKeyInputEarly.dataset.boundOptuna = "1";
                objectiveKeyInputEarly.addEventListener("input", () => {
                    backtestRules.objectiveKey = String(objectiveKeyInputEarly.value || "");
                });
            }
            const objectiveDirEarly = document.getElementById("center-backtest-objective-direction");
            if (objectiveDirEarly && objectiveDirEarly.dataset.boundOptuna !== "1") {
                objectiveDirEarly.dataset.boundOptuna = "1";
                objectiveDirEarly.addEventListener("change", () => {
                    backtestRules.objectiveDirection = objectiveDirEarly.value === "minimize" ? "minimize" : "maximize";
                });
            }
            refreshOptunaControlsVisibility();
            if (!fromYearInput || !fromMonthInput || !fromDayInput || !toYearInput || !toMonthInput || !toDayInput || !runBtn) {
                return;
            }

            const bindDatePartAutoAdvance = (yearInput, monthInput, dayInput, nextYearInput = null) => {
                yearInput.addEventListener("input", () => {
                    yearInput.value = keepDigits(yearInput.value, 4);
                    if (yearInput.value.length === 4) {
                        monthInput.focus();
                        monthInput.select();
                    }
                });
                monthInput.addEventListener("input", () => {
                    monthInput.value = keepDigits(monthInput.value, 2);
                    if (monthInput.value.length === 2) {
                        dayInput.focus();
                        dayInput.select();
                    }
                });
                dayInput.addEventListener("input", () => {
                    dayInput.value = keepDigits(dayInput.value, 2);
                    if (dayInput.value.length === 2 && nextYearInput) {
                        nextYearInput.focus();
                        nextYearInput.select();
                    }
                });
            };
            bindDatePartAutoAdvance(fromYearInput, fromMonthInput, fromDayInput, toYearInput);
            bindDatePartAutoAdvance(toYearInput, toMonthInput, toDayInput, null);

            const fillDateParts = (yearInput, monthInput, dayInput, date) => {
                const text = formatDateForInput(date);
                const [year, month, day] = text.split("-");
                yearInput.value = year;
                monthInput.value = month;
                dayInput.value = day;
            };
            const saveDatePartsToState = () => {
                backtestRules.fromYear = keepDigits(fromYearInput.value, 4);
                backtestRules.fromMonth = keepDigits(fromMonthInput.value, 2);
                backtestRules.fromDay = keepDigits(fromDayInput.value, 2);
                backtestRules.toYear = keepDigits(toYearInput.value, 4);
                backtestRules.toMonth = keepDigits(toMonthInput.value, 2);
                backtestRules.toDay = keepDigits(toDayInput.value, 2);
            };
            const composeDateValue = (yearInput, monthInput, dayInput) => {
                const year = keepDigits(yearInput.value, 4);
                const month = keepDigits(monthInput.value, 2);
                const day = keepDigits(dayInput.value, 2);
                if (!year || !month || !day) {
                    return "";
                }
                return `${year.padStart(4, "0")}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
            };
            const isDatePartsEmpty = (yearInput, monthInput, dayInput) => (
                !String(yearInput.value || "").trim() &&
                !String(monthInput.value || "").trim() &&
                !String(dayInput.value || "").trim()
            );
            const bindDatePartStateSync = (yearInput, monthInput, dayInput) => {
                const sync = () => {
                    yearInput.value = keepDigits(yearInput.value, 4);
                    monthInput.value = keepDigits(monthInput.value, 2);
                    dayInput.value = keepDigits(dayInput.value, 2);
                    saveDatePartsToState();
                };
                yearInput.addEventListener("input", sync);
                monthInput.addEventListener("input", sync);
                dayInput.addEventListener("input", sync);
            };
            bindDatePartStateSync(fromYearInput, fromMonthInput, fromDayInput);
            bindDatePartStateSync(toYearInput, toMonthInput, toDayInput);

            if (isDatePartsEmpty(toYearInput, toMonthInput, toDayInput)) {
                fillDateParts(toYearInput, toMonthInput, toDayInput, new Date());
            }
            if (isDatePartsEmpty(fromYearInput, fromMonthInput, fromDayInput)) {
                const toDate = composeDateValue(toYearInput, toMonthInput, toDayInput);
                const fromDate = new Date(toDate || Date.now());
                fromDate.setDate(fromDate.getDate() - 30);
                fillDateParts(fromYearInput, fromMonthInput, fromDayInput, fromDate);
            }
            saveDatePartsToState();
            refreshOptunaControlsVisibility();
        }

        function renderCenterBottomPlaceholder(title, message = "") {
            if (!centerBottomPanel) {
                return;
            }
            if (shouldShowBacktestSummaryPanel()) {
                renderBacktestSummaryStatusPanel(title || "组合详情", message || "");
                return;
            }
            centerBottomPanel.innerHTML = `
                <div class="center-bottom-layout">
                    <div class="center-bottom-column center-bottom-column-left">
                        ${renderBacktestLeftColumnHtml()}
                    </div>
                    <div class="center-bottom-column center-bottom-column-right">
                        <div class="center-bottom-box">
                            ${renderBacktestSymbolBox(message || title || "")}
                        </div>
                        <div class="center-bottom-box small-row">${renderCenterBottomBacktestControls()}</div>
                    </div>
                </div>
            `;
            installCenterBacktestClickDelegation();
            bindCenterBottomBacktestControls();
        }

        function renderBacktestSummaryStatusPanel(title, message = "") {
            if (!centerBottomPanel) {
                return;
            }
            centerBottomPanel.innerHTML = `
                <div class="center-bottom-layout">
                    <div class="center-bottom-box" style="grid-column: 1 / -1;">
                        ${title ? `<div class="factor-panel-title">${escapeHtml(title)}</div>` : ""}
                        ${message ? `<div class="summary-panel-note" style="margin-top: 0;">${escapeHtml(message)}</div>` : ""}
                    </div>
                </div>
            `;
        }

        function formatSummaryMetricValue(value) {
            if (value === null || value === undefined || value === "") {
                return "--";
            }
            const numeric = Number(value);
            if (Number.isFinite(numeric)) {
                return numeric.toFixed(2);
            }
            return String(value);
        }

        function renderBacktestSummaryPanel(summary) {
            if (!centerBottomPanel) {
                return;
            }
            const hiddenSummaryKeys = new Set([
                "summary_path",
                "server_time",
                "backtest_start",
                "backtest_end",
                "backtest_end_inclusive",
                "回测标的",
                "买入组合逻辑",
                "卖出组合逻辑",
                "买入因子",
                "卖出因子",
                "回测配置",
                "已平仓股票表现",
                "期末持仓股票表现"
            ]);
            const entries = Object.entries(summary || {}).filter(([key]) => !hiddenSummaryKeys.has(key));
            if (!entries.length) {
                renderBacktestSummaryStatusPanel("组合详情", "暂无可展示的组合摘要");
                return;
            }
            const cardsHtml = entries.map(([label, value]) => (
                `<div class="summary-card">` +
                `<div class="summary-card-label">${escapeHtml(String(label))}</div>` +
                `<div class="summary-card-value">${escapeHtml(formatSummaryMetricValue(value))}</div>` +
                `</div>`
            )).join("");
            const summaryPath = summary && summary.summary_path ? String(summary.summary_path) : "";
            centerBottomPanel.innerHTML = `
                <div class="center-bottom-layout">
                    <div class="center-bottom-box" style="grid-column: 1 / -1;">
                        <div class="factor-panel-title">${escapeHtml(currentCode)} 回测指标</div>
                        <div class="summary-grid">${cardsHtml}</div>
                        ${summaryPath ? `<div class="summary-panel-note" style="margin-top: 8px;">数据来源：${escapeHtml(summaryPath)}</div>` : ""}
                    </div>
                </div>
            `;
        }

        async function refreshCenterBottomPanel() {
            if (!shouldShowBacktestSummaryPanel()) {
                renderCenterBottomPlaceholder("");
                return;
            }
            const runTag = getSelectedRunTag();
            if (!runTag) {
                renderCenterBottomPlaceholder("");
                return;
            }
            const requestSeq = ++backtestSummaryRequestSeq;
            renderCenterBottomPlaceholder("组合详情", "正在加载组合摘要...");
            try {
                const summary = await fetchBacktestSummaryForActiveRun();
                if (requestSeq !== backtestSummaryRequestSeq) {
                    return;
                }
                if (!summary) {
                    renderCenterBottomPlaceholder("");
                    return;
                }
                renderBacktestSummaryPanel(summary);
            } catch (err) {
                if (requestSeq !== backtestSummaryRequestSeq) {
                    return;
                }
                const message = err instanceof Error ? err.message : "组合摘要加载失败";
                renderCenterBottomPlaceholder("组合详情", message);
            }
        }

        // 默认周期改为 1day；若有上次浏览记录，后续会被 restoreViewState 覆盖
        currentInterval = "1day";
        intervalSelect.value = currentInterval;
        barsCache = [];
        barsDayIndexMap = new Map();
        barsDayIndexMapLength = 0;
        benchmarkBarsCache = [];
        indexOverlayBarsCache = [];
        selectedPortfolioIndexCode = "";
        lastBarTime = null;
        refreshFailed = false;
        countdownValue = AUTO_REFRESH_SECONDS;
        refreshTimer = null;
        countdownTimer = null;
        isRequesting = false;
        isSwitchingCode = false;
        pendingSwitchCode = "";
        isLoadingHistory = false;
        historyExhausted = false;
        lastHistoryRequestTo = null;
        lastVisibleLogicalSnapshot = null;
        historyPrefetchDebounceTimer = null;
        watchlistCodes = [currentCode];
        watchlistPriceMap = new Map();
        selectedWatchCode = currentCode;
        factorNames = [];
        factorGroups = [];
        factorCoreNames = [];
        factorCoreLabels = [];
        factorLabelMap = {};
        selectedFactorName = "";
        signalPoints = [];
        lastSignalTime = null;
        backtestOrderItems = [];
        backtestOrderMarkersPlugin = null;
        missingFactorKeys.clear();
        currentRightTabName = getPageViewLabel();
        expandedFactorGroupIds.clear();
        snapshotDebounceTimer = null;
        snapshotRequestSeq = 0;
        rightPanelSnapshotCache.clear();
        currentFactorSnapshotTime = null;
        currentFactorSnapshotPayload = null;
        currentBacktestPositionSnapshot = null;
        currentBacktestPositionHoverCode = "";
        lastRenderedSnapshotKey = "";
        rightPanelSnapshotInteractionId = 0;
        rightPanelSnapshotPausedInteractionId = -1;
        activeFactorNames = [];
        factorOrderByGroup = {};
        factorGroupOrder = [];
        factorSnapshotDragState = null;
        factorGroupDragState = null;
        backtestRules = {
            buy: [],
            sell: [],
            buyOperator: "and",
            sellOperator: "and",
            codesText: "",
            runName: "",
            fromYear: "",
            fromMonth: "",
            fromDay: "",
            toYear: "",
            toMonth: "",
            toDay: "",
            adoptModel: "",
            nTrials: 20,
            objectiveKey: "夏普比率",
            objectiveDirection: "maximize",
        };
        installCenterBacktestClickDelegation();
        if (centerBottomPanel && !shouldShowBacktestSummaryPanel()) {
            renderCenterBottomPlaceholder("");
        }
        backtestJobPollTimer = null;
        suppressFactorSnapshotClickUntil = 0;
        suppressSignalSlotClickUntil = 0;
        extraSignalSeriesByFactor.clear();
        extraSignalPointsByFactor.clear();
        extraLastSignalTimeByFactor.clear();
        watchlistSyncTimer = null;
        coupledSignalPoints = [];
        coupledSignalSeries = null;


        /* --- view module stubs (overridden by board_*.js) --- */
        function parseBacktestDateToSeconds(value) {
            const text = String(value || "").trim();
            const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
            if (!match) {
                return NaN;
            }
            const y = Number(match[1]);
            const m = Number(match[2]);
            const d = Number(match[3]);
            if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) {
                return NaN;
            }
            return alignToCurrentInterval(Math.floor(Date.UTC(y, m - 1, d, 0, 0, 0) / 1000));
        }

        function getBacktestRangeFromSummary(summary) {
            if (!summary || typeof summary !== "object") {
                return null;
            }
            const startTs = parseBacktestDateToSeconds(summary.backtest_start || summary["回测开始日期"]);
            const endTs = parseBacktestDateToSeconds(summary.backtest_end || summary["回测结束日期"]);
            if (!Number.isFinite(startTs) || !Number.isFinite(endTs) || startTs > endTs) {
                return null;
            }
            return { fromTs: startTs, toTs: endTs };
        }

        ykrsDailyBarWindowCachedRunTag = "";

        function renderBacktestPositionSnapshotStatus(text) {
            const { headExtraEl, listEl } = getFactorSnapshotPanelElements();
            if (!headExtraEl || !listEl) {
                return;
            }
            setFactorSnapshotFilterUiVisible(false);
            currentFactorSnapshotPayload = null;
            currentBacktestPositionSnapshot = null;
            currentBacktestPositionHoverCode = "";
            lastRenderedSnapshotKey = "";
            headExtraEl.textContent = text;
            listEl.innerHTML = "";
            updateExportFactorOptions();
        }

        function renderBacktestPositionSnapshotToRightPanel(snapshot, targetTs) {
            const { headExtraEl, listEl } = getFactorSnapshotPanelElements();
            if (!headExtraEl || !listEl) {
                return;
            }
            setFactorSnapshotFilterUiVisible(false);
            currentFactorSnapshotPayload = null;
            currentBacktestPositionSnapshot = snapshot && typeof snapshot === "object" ? snapshot : null;
            const showTs = Number.isFinite(Number(targetTs)) ? Number(targetTs) : Number(snapshot && snapshot.time);
            currentFactorSnapshotTime = Number.isFinite(showTs) ? showTs : null;
            lastRenderedSnapshotKey = `${currentCode}|${Number.isFinite(currentFactorSnapshotTime) ? currentFactorSnapshotTime : "na"}|position`;
            const items = Array.isArray(snapshot && snapshot.items) ? snapshot.items : [];
            const displayDate = String(snapshot && snapshot.date ? snapshot.date : formatLocalDateTime(showTs)).trim();
            headExtraEl.textContent = `日期: ${displayDate || "--"} | 持仓数: ${items.length}`;

            if (!items.length) {
                currentBacktestPositionHoverCode = "";
                listEl.innerHTML = '<div class="position-snapshot-empty">该日无持仓记录</div>';
                updateExportFactorOptions();
                return;
            }

            const selectedItem = items.find((item) => String(item && item.code || "") === currentBacktestPositionHoverCode) || items[0];
            currentBacktestPositionHoverCode = String(selectedItem && selectedItem.code || "");
            const detailFields = [
                ["持仓数量", formatPositionSnapshotNumber(selectedItem.position_size, 2)],
                ["持仓均价", formatPositionSnapshotNumber(selectedItem.position_price, 2)],
                ["收盘价", formatPositionSnapshotNumber(selectedItem.close, 2)],
                ["持仓市值", formatPositionSnapshotNumber(selectedItem.market_value, 2)],
                ["仓位占比", formatPositionSnapshotPercent(selectedItem.weight_pct)],
                ["浮动盈亏", formatPositionSnapshotNumber(selectedItem.unrealized_pnl, 2)],
            ];
            const detailHtml = detailFields
                .map(([label, value]) => (
                    `<div class="position-snapshot-detail-item">` +
                    `<span class="position-snapshot-detail-label">${escapeHtml(label)}</span>` +
                    `<span class="position-snapshot-detail-value">${escapeHtml(value)}</span>` +
                    `</div>`
                ))
                .join("");
            const rowsHtml = items.map((item) => {
                const itemCode = String(item && item.code || "");
                const itemCodeDisplay = formatPositionSnapshotCode(itemCode);
                const isActiveItem = itemCode === currentBacktestPositionHoverCode;
                const activeClass = isActiveItem ? " active" : "";
                const dailyPnlPct = Number(item && item.daily_pnl_pct);
                const weightPct = Number(item && item.weight_pct);
                const trendClass = Number.isFinite(dailyPnlPct)
                    ? (dailyPnlPct > 0 ? " position-snapshot-item--pos" : (dailyPnlPct < 0 ? " position-snapshot-item--neg" : " position-snapshot-item--flat"))
                    : " position-snapshot-item--flat";
                const fillWidth = Number.isFinite(weightPct)
                    ? `${Math.max(0, Math.min(100, weightPct * 100))}%`
                    : "0%";
                const fillColor = Number.isFinite(dailyPnlPct)
                    ? (dailyPnlPct > 0 ? "rgba(239, 83, 80, 0.18)" : (dailyPnlPct < 0 ? "rgba(38, 166, 154, 0.18)" : "rgba(107, 156, 255, 0.16)"))
                    : "rgba(107, 156, 255, 0.16)";
                const contributionHtml = isActiveItem
                    ? (
                        `<span class="position-snapshot-contribution" style="text-align:right;">收益贡献</span>` +
                        `<span class="position-snapshot-active-label" style="text-align:right;" >股票代码</span>` +
                        `<span class="position-snapshot-active-label" style="text-align:right;">当日盈亏</span>` +
                        `<span class="position-snapshot-active-label" style="text-align:right;">仓位占比</span>` +
                        `<span class="position-snapshot-active-value">${escapeHtml(formatPositionSnapshotPercent(item && item.contribution_pct))}</span>` +
                        `<span class="position-snapshot-active-value">${escapeHtml(itemCodeDisplay)}</span>` +
                        `<span class="position-snapshot-active-value" style="text-align:right;">${escapeHtml(formatPositionSnapshotPercent(item && item.daily_pnl_pct))}</span>` +
                        `<span class="position-snapshot-active-value" style="text-align:right;">${escapeHtml(formatPositionSnapshotPercent(item && item.weight_pct))}</span>`
                    )
                    : "";
                return (
                    `<div class="position-snapshot-item${activeClass}${trendClass}" data-position-code="${escapeHtml(itemCode)}" style="--position-fill-width:${fillWidth}; --position-fill-color:${fillColor};">` +
                    (isActiveItem
                        ? contributionHtml
                        : (
                            `<span class="position-snapshot-cell">${escapeHtml(itemCodeDisplay)}</span>` +
                            `<span class="position-snapshot-cell position-snapshot-cell--number">${escapeHtml(formatPositionSnapshotPercent(item && item.daily_pnl_pct))}</span>` +
                            `<span class="position-snapshot-cell position-snapshot-cell--number">${escapeHtml(formatPositionSnapshotPercent(item && item.weight_pct))}</span>`
                        )) +
                    `</div>`
                );
            }).join("");
            listEl.innerHTML =
                `<div class="position-snapshot-wrap">` +
                `<div class="position-snapshot-detail">` +
                `<div class="position-snapshot-detail-title">${escapeHtml(currentBacktestPositionHoverCode || "---")}</div>` +
                `<div class="position-snapshot-detail-grid">${detailHtml}</div>` +
                `</div>` +
                `<div class="position-snapshot-table">` +
                `<div class="position-snapshot-table-header">` +
                `<span>代码</span>` +
                `<span style="text-align:right;">当日盈亏比</span>` +
                `<span style="text-align:right;">仓位占比</span>` +
                `</div>` +
                rowsHtml +
                `</div>` +
                `</div>`;
            updateExportFactorOptions();
        }

        async function fetchBacktestPositionSnapshot(code, timeTs) {
            const params = new URLSearchParams({
                code,
                time: String(timeTs)
            });
            appendRunTagParam(params);
            const url = `${API_BASE_URL}/api/backtest/positions/snapshot?${params.toString()}`;
            const resp = await fetch(url, { method: "GET", cache: "no-store" });
            const body = await resp.json();
            if (!resp.ok) {
                if (isNoDataErrorResponse(resp.status, body)) {
                    return { no_data: true, items: [], time: timeTs };
                }
                const message = body && body.error && body.error.message ? body.error.message : "组合持仓快照获取失败";
                throw new Error(message);
            }
            return body && typeof body === "object" ? body : { no_data: true, items: [], time: timeTs };
        }

        async function fetchBacktestOrders(code, fromTs, toTs) {
            const params = new URLSearchParams({
                code,
                from: String(fromTs),
                to: String(toTs)
            });
            appendRunTagParam(params);
            const url = `${API_BASE_URL}/api/backtest/orders?${params.toString()}`;
            const resp = await fetch(url, { method: "GET", cache: "no-store" });
            const body = await resp.json();
            if (!resp.ok) {
                const message = body && body.error && body.error.message ? body.error.message : "回测订单获取失败";
                throw new Error(message);
            }
            return body && typeof body === "object" ? body : { no_data: true, items: [] };
        }

        async function fetchLatestBacktestSummary() {
            const url = `${API_BASE_URL}/api/backtest/summary/latest`;
            const resp = await fetch(url, { method: "GET", cache: "no-store" });
            const body = await resp.json();
            if (!resp.ok) {
                const message = body && body.error && body.error.message ? body.error.message : "组合摘要获取失败";
                throw new Error(message);
            }
            return body && typeof body === "object" ? body : {};
        }

        async function fetchBacktestSummaryForActiveRun() {
            const runTag = getSelectedRunTag();
            if (!runTag) {
                return null;
            }
            const url = `${API_BASE_URL}/api/backtest/history/detail?run_tag=${encodeURIComponent(runTag)}`;
            const resp = await fetch(url, { method: "GET", cache: "no-store" });
            const body = await resp.json();
            if (!resp.ok) {
                const message = body && body.error && body.error.message ? body.error.message : "组合摘要获取失败";
                throw new Error(message);
            }
            const item = body && body.item ? body.item : null;
            const summary = item && item.summary ? item.summary : null;
            if (summary && typeof summary === "object") {
                if (item.summary_path) {
                    summary.summary_path = item.summary_path;
                }
                return summary;
            }
            return body && typeof body === "object" ? body : null;
        }

        async function submitBacktestRun(payload) {
            const resp = await fetch(`${API_BASE_URL}/api/backtest/run`, {
                method: "POST",
                cache: "no-store",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const body = await resp.json();
            if (!resp.ok) {
                const message = body && body.error && body.error.message ? body.error.message : "回测任务创建失败";
                throw new Error(message);
            }
            return body && typeof body === "object" ? body : {};
        }

        async function fetchBacktestJobStatus(jobId) {
            const params = new URLSearchParams({ id: String(jobId || "") });
            const resp = await fetch(`${API_BASE_URL}/api/backtest/jobs?${params.toString()}`, {
                method: "GET",
                cache: "no-store",
            });
            const body = await resp.json();
            if (!resp.ok) {
                const message = body && body.error && body.error.message ? body.error.message : "回测任务状态获取失败";
                throw new Error(message);
            }
            return body && typeof body === "object" ? body : {};
        }

        function ensureBacktestModal() {
            let mask = document.getElementById("backtest-modal-mask");
            if (mask) {
                return mask;
            }
            mask = document.createElement("div");
            mask.id = "backtest-modal-mask";
            mask.className = "backtest-modal-mask";
            mask.innerHTML = `
                <div class="backtest-modal" role="dialog" aria-modal="true" aria-labelledby="backtest-modal-title">
                    <div class="backtest-modal-header">
                        <span id="backtest-modal-title">回测运行中</span>
                        <button id="backtest-modal-cancel-job" class="field btn" type="button" style="display:none;">终止寻优</button>
                        <button id="backtest-modal-close" class="field btn" type="button">关闭</button>
                    </div>
                    <div id="backtest-modal-status" class="summary-panel-note" style="margin-top: 0;">准备启动</div>
                    <div class="backtest-progress-bar"><div id="backtest-progress-fill" class="backtest-progress-fill"></div></div>
                    <div id="backtest-log-tail" class="backtest-log-tail"></div>
                    <div class="backtest-modal-actions">
                        <button id="backtest-modal-refresh" class="field btn" type="button">刷新 YKRS</button>
                    </div>
                </div>
            `;
            document.body.appendChild(mask);
            const closeBtn = document.getElementById("backtest-modal-close");
            if (closeBtn) {
                closeBtn.addEventListener("click", () => {
                    mask.classList.remove("visible");
                });
            }
            const refreshBtn = document.getElementById("backtest-modal-refresh");
            if (refreshBtn) {
                refreshBtn.addEventListener("click", () => {
                    mask.classList.remove("visible");
                    if (PAGE_BOOT.allowYkrsCurve) {
                        void switchCodeAndReload("000000.YKRS");
                    } else if (typeof edgeFloatNavigateToPage === "function") {
                        edgeFloatNavigateToPage("../组合结果/index.html");
                    } else {
                        window.location.href = "../组合结果/index.html";
                    }
                });
            }
            const cancelJobBtn = document.getElementById("backtest-modal-cancel-job");
            if (cancelJobBtn) {
                cancelJobBtn.addEventListener("click", () => {
                    const jobId = String(mask.dataset.backtestJobId || "").trim();
                    if (!jobId) {
                        return;
                    }
                    cancelJobBtn.disabled = true;
                    void (async () => {
                        try {
                            const resp = await fetch(`${API_BASE_URL}/api/backtest/job/cancel`, {
                                method: "POST",
                                cache: "no-store",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ job_id: jobId }),
                            });
                            const body = await resp.json().catch(() => ({}));
                            if (!resp.ok) {
                                const message = body && body.error && body.error.message ? body.error.message : "终止请求失败";
                                throw new Error(message);
                            }
                            logUiHint(body && body.message ? body.message : "已请求终止寻优");
                        } catch (err) {
                            const message = err instanceof Error ? err.message : "终止请求失败";
                            logUiHint(message);
                        } finally {
                            cancelJobBtn.disabled = false;
                        }
                    })();
                });
            }
            return mask;
        }

        function showBacktestModal(job) {
            const payload = job && typeof job === "object" ? job : {};
            const mask = ensureBacktestModal();
            const title = document.getElementById("backtest-modal-title");
            const statusEl = document.getElementById("backtest-modal-status");
            const fillEl = document.getElementById("backtest-progress-fill");
            const logEl = document.getElementById("backtest-log-tail");
            const status = String(payload.status || "queued");
            const progress = Math.max(0, Math.min(100, Number(payload.progress || 0)));
            mask.dataset.backtestJobId = String(payload.job_id || "");
            if (title) {
                if (status === "done") {
                    title.textContent = "回测完成";
                } else if (status === "cancelled") {
                    title.textContent = "寻优已终止";
                } else if (status === "failed") {
                    title.textContent = "回测失败";
                } else {
                    title.textContent = "回测运行中";
                }
            }
            const cancelJobBtn = document.getElementById("backtest-modal-cancel-job");
            if (cancelJobBtn) {
                const showCancel = status === "running" && String(payload.run_mode || "") === "optuna";
                cancelJobBtn.style.display = showCancel ? "inline-block" : "none";
            }
            if (statusEl) {
                const jobId = payload.job_id ? `任务 ${payload.job_id} · ` : "";
                statusEl.textContent = `${jobId}${payload.stage || "--"} · ${progress}% · ${payload.message || ""}`;
            }
            if (fillEl) {
                fillEl.style.width = `${progress}%`;
            }
            if (logEl) {
                const lines = Array.isArray(payload.log_tail) ? payload.log_tail : [];
                logEl.textContent = lines.length ? lines.join("\n") : "等待日志...";
                logEl.scrollTop = logEl.scrollHeight;
            }
            mask.classList.add("visible");
        }

        async function pollBacktestJob(jobId) {
            if (backtestJobPollTimer) {
                clearTimeout(backtestJobPollTimer);
                backtestJobPollTimer = null;
            }
            try {
                const job = await fetchBacktestJobStatus(jobId);
                showBacktestModal(job);
                const runBtn = document.getElementById("btn-center-run-backtest");
                if (job.status === "done" || job.status === "cancelled") {
                    if (runBtn) {
                        runBtn.disabled = false;
                    }
                    logUiHint(job.status === "cancelled" ? (job.message || "寻优已终止") : `回测完成: ${job.run_tag || ""}`);
                    await refreshCenterBottomPanel();
                    return;
                }
                if (job.status === "failed") {
                    if (runBtn) {
                        runBtn.disabled = false;
                    }
                    logUiHint(job.error || "回测失败");
                    return;
                }
                backtestJobPollTimer = setTimeout(() => {
                    void pollBacktestJob(jobId);
                }, 1000);
            } catch (err) {
                const runBtn = document.getElementById("btn-center-run-backtest");
                if (runBtn) {
                    runBtn.disabled = false;
                }
                const message = err instanceof Error ? err.message : "回测状态查询失败";
                showBacktestModal({ status: "failed", stage: "状态查询", progress: 100, message, log_tail: [message] });
            }
        }

        async function startBacktestJob(payload) {
            const runBtn = document.getElementById("btn-center-run-backtest");
            if (runBtn) {
                runBtn.disabled = true;
            }
            showBacktestModal({ status: "queued", stage: "提交中", progress: 0, message: "正在创建回测任务", log_tail: [] });
            try {
                const job = await submitBacktestRun(payload);
                showBacktestModal(job);
                if (!job.job_id) {
                    throw new Error("后端未返回 job_id");
                }
                void pollBacktestJob(job.job_id);
            } catch (err) {
                if (runBtn) {
                    runBtn.disabled = false;
                }
                const message = err instanceof Error ? err.message : "回测任务创建失败";
                showBacktestModal({ status: "failed", stage: "任务创建", progress: 100, message, log_tail: [message] });
                logUiHint(message);
            }
        }

        function buildBacktestOrderMarkerText(order) {
            const side = String(order.side || "").toUpperCase();
            const sideText = side === "BUY" ? "买" : "卖";
            const price = formatTradeMarkerNumber(order.executed_price, 2);
            const size = formatTradeMarkerAmount(order.executed_size);
            const amount = formatTradeMarkerAmount(order.executed_value);
            const commission = formatTradeMarkerNumber(order.commission, 2);
            const signalRaw = String(order.signal || "").trim();
            const signalShort = signalRaw.length > 28 ? `${signalRaw.slice(0, 28)}…` : signalRaw;
            const signalPart = signalShort ? ` ${signalShort}` : "";
            return `${sideText} ${price} 数${size} 金${amount} 费${commission}${signalPart}`;
        }

        function buildBacktestOrderMarkers() {
            if (isMainChartLineMode() || currentInterval !== "1day") {
                return [];
            }
            return backtestOrderItems
                .map((order) => {
                    const side = String(order.side || "").toUpperCase();
                    const timeValue = Number(order.time);
                    if (!Number.isFinite(timeValue) || (side !== "BUY" && side !== "SELL")) {
                        return null;
                    }
                    return {
                        time: toChartTime(timeValue),
                        position: side === "BUY" ? "belowBar" : "aboveBar",
                        color: side === "BUY" ? "#ef5350" : "#26a69a",
                        shape: side === "BUY" ? "arrowUp" : "arrowDown",
                        text: buildBacktestOrderMarkerText(order),
                    };
                })
                .filter(Boolean);
        }

        function applyBacktestOrderMarkers() {
            const markers = buildBacktestOrderMarkers();
            if (typeof LightweightCharts.createSeriesMarkers === "function") {
                if (!backtestOrderMarkersPlugin) {
                    backtestOrderMarkersPlugin = LightweightCharts.createSeriesMarkers(candlestickSeries, markers);
                } else if (typeof backtestOrderMarkersPlugin.setMarkers === "function") {
                    backtestOrderMarkersPlugin.setMarkers(markers);
                }
                return;
            }
            if (typeof candlestickSeries.setMarkers === "function") {
                candlestickSeries.setMarkers(markers);
            }
        }

        async function refreshBacktestOrderMarkers() {
            if (isYkrsCode() || currentInterval !== "1day" || !barsCache.length || !getSelectedRunTag()) {
                backtestOrderItems = [];
                applyBacktestOrderMarkers();
                return;
            }
            const fromTs = Number(barsCache[0].time);
            const toTs = Number(barsCache[barsCache.length - 1].time);
            if (!Number.isFinite(fromTs) || !Number.isFinite(toTs)) {
                backtestOrderItems = [];
                applyBacktestOrderMarkers();
                return;
            }
            try {
                const payload = await fetchBacktestOrders(currentCode, fromTs, toTs);
                backtestOrderItems = Array.isArray(payload.items) ? payload.items : [];
            } catch (err) {
                backtestOrderItems = [];
                const message = err instanceof Error ? err.message : "回测交易标记获取失败";
                logUiHint(`回测交易标记: ${message}`);
            }
            applyBacktestOrderMarkers();
        }


        installCenterBacktestClickDelegation();
        if (centerBottomPanel && !shouldShowBacktestSummaryPanel()) {
            renderCenterBottomPlaceholder("");
        }
