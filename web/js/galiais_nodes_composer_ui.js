export function installComposerPromptSectionControls(nodeType, helpers = {}) {
    const {
        findWidget,
        setWidgetValue,
        setWidgetHiddenState,
        syncVueWidgetRowVisibility,
        refreshNodeSize,
        ensureStyles,
    } = helpers;
    const COMPOSER_SECTION_PREFIX = "提示词段";
    const COMPOSER_SECTION_TYPE = "GALIAIS_NODES_CHARACTER_SECTION";
    const COMPOSER_MIN_SECTION_INPUTS = 1;
    const COMPOSER_MAX_SECTION_INPUTS = 16;
    const COMPOSER_VISIBLE_SECTION_PROPERTY = "galiais_visible_prompt_sections";
    const COMPOSER_TEMPLATE_BUTTON_NAME = "模板管理";
    const COMPOSER_TEMPLATE_WIDGET_NAMES = new Set(["模板名称", "自定义正面模板", "模板JSON"]);

function promptSectionInputNumber(input) {
    const match = String(input?.name || "").match(/^提示词段(\d+)$/);
    if (!match) return 0;
    const value = Number(match[1] || 0);
    return Number.isFinite(value) ? value : 0;
}

function composerPromptSectionInputs(node) {
    return (node?.inputs || [])
        .map((input, index) => ({ input, index, number: promptSectionInputNumber(input) }))
        .filter((item) => item.number >= COMPOSER_MIN_SECTION_INPUTS && item.number <= COMPOSER_MAX_SECTION_INPUTS)
        .sort((left, right) => left.number - right.number);
}

function composerHighestConnectedSection(node) {
    let highest = 0;
    for (const item of composerPromptSectionInputs(node)) {
        if (item.input?.link !== null && item.input?.link !== undefined) {
            highest = Math.max(highest, item.number);
        }
    }
    return highest;
}

function composerVisibleSectionCount(node) {
    const stored = Number(node?.properties?.[COMPOSER_VISIBLE_SECTION_PROPERTY] || 0);
    const connected = composerHighestConnectedSection(node);
    return Math.max(
        COMPOSER_MIN_SECTION_INPUTS,
        Math.min(COMPOSER_MAX_SECTION_INPUTS, stored || connected || COMPOSER_MIN_SECTION_INPUTS),
    );
}

function setComposerVisibleSectionCount(node, count) {
    if (!node) return;
    node.properties = node.properties || {};
    node.properties[COMPOSER_VISIBLE_SECTION_PROPERTY] = Math.max(
        COMPOSER_MIN_SECTION_INPUTS,
        Math.min(COMPOSER_MAX_SECTION_INPUTS, Number(count || COMPOSER_MIN_SECTION_INPUTS)),
    );
}

function hasComposerPromptSectionInput(node, number) {
    const name = `${COMPOSER_SECTION_PREFIX}${number}`;
    return (node?.inputs || []).some((input) => input?.name === name);
}

function addComposerPromptSectionInput(node, number) {
    const name = `${COMPOSER_SECTION_PREFIX}${number}`;
    if (!node || hasComposerPromptSectionInput(node, number) || typeof node.addInput !== "function") return false;
    node.addInput(name, COMPOSER_SECTION_TYPE);
    return true;
}

function removeComposerPromptSectionInput(node, number) {
    const name = `${COMPOSER_SECTION_PREFIX}${number}`;
    const index = (node?.inputs || []).findIndex((input) => input?.name === name);
    if (index < 0 || (node.inputs[index]?.link !== null && node.inputs[index]?.link !== undefined)) return false;
    node.removeInput(index);
    return true;
}

function highestComposerPromptSectionNumber(node) {
    return composerPromptSectionInputs(node).reduce((highest, item) => Math.max(highest, item.number), 0);
}

function syncComposerPromptSectionInputs(node, minimumCount = COMPOSER_MIN_SECTION_INPUTS) {
    if (!node) return false;
    let changed = false;
    const requested = Math.max(
        Number(minimumCount || COMPOSER_MIN_SECTION_INPUTS),
        composerVisibleSectionCount(node),
        composerHighestConnectedSection(node),
    );
    const desired = Math.max(
        COMPOSER_MIN_SECTION_INPUTS,
        Math.min(COMPOSER_MAX_SECTION_INPUTS, requested),
    );
    for (let number = COMPOSER_MIN_SECTION_INPUTS; number <= desired; number += 1) {
        changed = addComposerPromptSectionInput(node, number) || changed;
    }
    for (let number = COMPOSER_MAX_SECTION_INPUTS; number > desired; number -= 1) {
        changed = removeComposerPromptSectionInput(node, number) || changed;
    }
    setComposerVisibleSectionCount(node, desired);
    if (changed) {
        refreshNodeSize(node, true, { fitHeight: true });
    }
    return changed;
}

function addNextComposerPromptSectionInput(node) {
    const current = composerVisibleSectionCount(node);
    if (current >= COMPOSER_MAX_SECTION_INPUTS) return false;
    setComposerVisibleSectionCount(node, current + 1);
    return syncComposerPromptSectionInputs(node, current + 1);
}

function removeLastComposerPromptSectionInput(node) {
    const sections = composerPromptSectionInputs(node);
    if (sections.length <= COMPOSER_MIN_SECTION_INPUTS) return false;
    const last = sections[sections.length - 1];
    if (last.input?.link !== null && last.input?.link !== undefined) return false;
    setComposerVisibleSectionCount(node, last.number - 1);
    return syncComposerPromptSectionInputs(node, last.number - 1);
}

function autoExtendComposerPromptSections(node) {
    const highest = highestComposerPromptSectionNumber(node);
    const connected = composerHighestConnectedSection(node);
    if (!highest || highest >= COMPOSER_MAX_SECTION_INPUTS || connected < highest) return false;
    setComposerVisibleSectionCount(node, highest + 1);
    return syncComposerPromptSectionInputs(node, highest + 1);
}

function hideComposerTemplateWidgets(node) {
    let changed = false;
    for (const name of COMPOSER_TEMPLATE_WIDGET_NAMES) {
        const widget = findWidget(node, name);
        changed = setWidgetHiddenState(widget, true) || changed;
    }
    syncVueWidgetRowVisibility(node);
    return changed;
}

function composerTemplateValue(node, name) {
    const widget = findWidget(node, name);
    return String(widget?.value ?? widget?.inputEl?.value ?? "");
}

function syncComposerTemplatePanelFromWidgets(node, controls) {
    controls.name.value = composerTemplateValue(node, "模板名称");
    controls.template.value = composerTemplateValue(node, "自定义正面模板");
    controls.json.value = composerTemplateValue(node, "模板JSON");
}

function applyComposerTemplatePanelToWidgets(node, controls) {
    setWidgetValue(findWidget(node, "模板名称"), controls.name.value);
    setWidgetValue(findWidget(node, "自定义正面模板"), controls.template.value);
    setWidgetValue(findWidget(node, "模板JSON"), controls.json.value);
    hideComposerTemplateWidgets(node);
    refreshNodeSize(node, true, { allowHeightGrowth: false });
}

function createComposerTemplateField(labelText, multiline = false) {
    const wrap = document.createElement("label");
    wrap.style.display = "grid";
    wrap.style.gap = "6px";
    wrap.style.fontSize = "12px";
    wrap.style.color = "#c8d2df";

    const label = document.createElement("span");
    label.textContent = labelText;
    wrap.appendChild(label);

    const input = multiline ? document.createElement("textarea") : document.createElement("input");
    input.style.width = "100%";
    input.style.boxSizing = "border-box";
    input.style.border = "1px solid #3c4654";
    input.style.borderRadius = "6px";
    input.style.background = "#0d1118";
    input.style.color = "#eef3f8";
    input.style.padding = "8px 10px";
    input.style.font = "12px ui-sans-serif, system-ui, Microsoft YaHei, sans-serif";
    input.style.outline = "none";
    if (multiline) {
        input.rows = 6;
        input.style.resize = "vertical";
        input.style.minHeight = "96px";
    }
    wrap.appendChild(input);
    return { wrap, input };
}

function openComposerTemplatePanel(node) {
    ensureStyles();
    const backdrop = document.createElement("div");
    backdrop.className = "galiais-nodes-danbooru-backdrop";
    const modal = document.createElement("div");
    modal.className = "galiais-nodes-danbooru-field-modal";
    modal.style.width = "min(620px, calc(100vw - 32px))";
    modal.style.maxHeight = "min(760px, calc(100vh - 32px))";

    const header = document.createElement("div");
    header.className = "galiais-nodes-danbooru-header";
    const title = document.createElement("div");
    title.className = "galiais-nodes-danbooru-title";
    title.textContent = "Final Composer 模板管理";
    header.appendChild(title);

    const body = document.createElement("div");
    body.style.display = "grid";
    body.style.gap = "12px";
    body.style.padding = "12px";
    body.style.overflow = "auto";

    const nameField = createComposerTemplateField("模板名称");
    const templateField = createComposerTemplateField("自定义正面模板", true);
    const jsonField = createComposerTemplateField("模板JSON", true);
    body.appendChild(nameField.wrap);
    body.appendChild(templateField.wrap);
    body.appendChild(jsonField.wrap);

    const footer = document.createElement("div");
    footer.className = "galiais-nodes-danbooru-footer";
    footer.style.display = "flex";
    footer.style.justifyContent = "flex-end";
    footer.style.gap = "8px";
    footer.style.padding = "12px";
    footer.style.borderTop = "1px solid #2a313d";

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "galiais-nodes-danbooru-button";
    closeButton.textContent = "取消";
    const applyButton = document.createElement("button");
    applyButton.type = "button";
    applyButton.className = "galiais-nodes-danbooru-button is-primary";
    applyButton.textContent = "应用";
    footer.appendChild(closeButton);
    footer.appendChild(applyButton);

    modal.appendChild(header);
    modal.appendChild(body);
    modal.appendChild(footer);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    const controls = { name: nameField.input, template: templateField.input, json: jsonField.input };
    syncComposerTemplatePanelFromWidgets(node, controls);

    const close = () => backdrop.remove();
    closeButton.addEventListener("click", close);
    backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) close();
    });
    applyButton.addEventListener("click", () => {
        applyComposerTemplatePanelToWidgets(node, controls);
        close();
    });
    nameField.input.focus();
}

function ensureComposerTemplateButtonWidget(node) {
    if (!node || typeof node.addWidget !== "function" || !Array.isArray(node.widgets)) return false;
    const existing = findWidget(node, COMPOSER_TEMPLATE_BUTTON_NAME);
    if (existing) {
        existing.callback = () => openComposerTemplatePanel(node);
        existing.value = "打开模板面板";
        existing.serialize = false;
        existing.options = { ...(existing.options || {}), serialize: false };
        return false;
    }
    const widget = node.addWidget(
        "button",
        COMPOSER_TEMPLATE_BUTTON_NAME,
        "打开模板面板",
        () => openComposerTemplatePanel(node),
        { serialize: false },
    );
    widget.serialize = false;
    widget.options = { ...(widget.options || {}), serialize: false };
    widget.value = "打开模板面板";
    return true;
}


function install(nodeType) {
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
        onConfigure?.apply(this, arguments);
        setTimeout(() => {
            const hiddenChanged = hideComposerTemplateWidgets(this);
            const buttonChanged = ensureComposerTemplateButtonWidget(this);
            syncComposerPromptSectionInputs(this, 1);
            if (hiddenChanged || buttonChanged) refreshNodeSize(this, true, { allowHeightGrowth: false });
        }, 0);
    };

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
        onNodeCreated?.apply(this, arguments);
        setComposerVisibleSectionCount(this, COMPOSER_MIN_SECTION_INPUTS);
        setTimeout(() => {
            hideComposerTemplateWidgets(this);
            ensureComposerTemplateButtonWidget(this);
            syncComposerPromptSectionInputs(this, 1);
        }, 0);
    };

    const onConnectionsChange = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function () {
        const output = onConnectionsChange?.apply(this, arguments);
        setTimeout(() => {
            autoExtendComposerPromptSections(this);
        }, 0);
        return output;
    };
}

    return install(nodeType);
}
