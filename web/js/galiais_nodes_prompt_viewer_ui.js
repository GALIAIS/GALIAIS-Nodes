export function ensurePromptViewerWidgets(node, helpers = {}) {
    const { ensureStyles } = helpers;

    if (!node || typeof node.addDOMWidget !== "function" || node._galiaisPromptViewer) {
        return false;
    }
    ensureStyles();
    const container = document.createElement("div");
    container.className = "galiais-nodes-prompt-viewer";
    const fields = {};
    for (const [key, labelText, rows] of [
        ["positive", "正面提示词", 4],
        ["negative", "负面提示词", 3],
        ["metadata", "元信息JSON", 4],
    ]) {
        const label = document.createElement("label");
        label.textContent = labelText;
        const textarea = document.createElement("textarea");
        textarea.readOnly = true;
        textarea.rows = rows;
        textarea.spellcheck = false;
        container.appendChild(label);
        container.appendChild(textarea);
        fields[key] = textarea;
    }
    const widget = node.addDOMWidget("GALIAIS输出", "galiais_prompt_viewer", container, {
        serialize: false,
    });
    widget.serialize = false;
    node._galiaisPromptViewer = { container, fields, widget };
    return true;
}

export function updatePromptViewerWidgets(node, message, helpers = {}) {
    ensurePromptViewerWidgets(node, helpers);
    const viewer = node?._galiaisPromptViewer;
    if (!viewer) return;
    const pick = (key) => {
        const value = message?.[key];
        if (Array.isArray(value)) return String(value[0] ?? "");
        return String(value ?? "");
    };
    viewer.fields.positive.value = pick("positive");
    viewer.fields.negative.value = pick("negative");
    viewer.fields.metadata.value = pick("metadata");
    helpers.app?.graph?.setDirtyCanvas(true, true);
}
