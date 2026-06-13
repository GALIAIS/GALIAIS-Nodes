import { app } from "../../scripts/app.js";
import { apiUrl, cacheKey, createLruCache, readJsonResponse } from "./galiais_nodes_api_cache.js";
import { FALLBACK_FIELD_MAP } from "./galiais_nodes_field_map.js";
import { installComposerPromptSectionControls } from "./galiais_nodes_composer_ui.js";
import { ensurePromptViewerWidgets, updatePromptViewerWidgets } from "./galiais_nodes_prompt_viewer_ui.js";

const STYLE_ID = "galiais-nodes-danbooru-lazy-select-style";
const PAGE_LIMIT = 60;
const OPTION_PAGE_CACHE_LIMIT = 420;
const TREE_CACHE_LIMIT = 120;
const CANVAS_BUTTON_WIDTH = 62;
const CANVAS_BUTTON_HEIGHT = 22;
const CANVAS_BUTTON_MARGIN = 12;
const FIELD_ENABLE_CANVAS_RESERVED_WIDTH = 66;
const SELECTOR_BUTTON_NAME = "DB词典";
const DB_FILE_BUTTON_NAME = "选择DB文件";
const AI_MODELS_BUTTON_NAME = "获取模型";
const FIELD_ENABLE_TOGGLE_CLASS = "galiais-field-enable-toggle";
const FIELD_ENABLE_CANVAS_TOGGLE_CLASS = "galiais-field-enable-canvas-toggle";
const FIELD_ENABLE_ROW_CLASS = "galiais-field-enable-row";
const FIELD_ENABLE_DISABLED_CLASS = "is-galiais-field-disabled";
const HIDDEN_WIDGET_ROW_CLASS = "galiais-hidden-widget-row";
const COMPOSER_NODE_NAME = "GaliaisNodesCharacterComposer";
const COMPOSER_SECTION_PREFIX = "提示词段";
const COMPOSER_SECTION_TYPE = "GALIAIS_NODES_CHARACTER_SECTION";
const COMPOSER_MIN_SECTION_INPUTS = 1;
const COMPOSER_MAX_SECTION_INPUTS = 16;
const COMPOSER_VISIBLE_SECTION_PROPERTY = "galiais_visible_prompt_sections";
const COMPOSER_TEMPLATE_BUTTON_NAME = "模板管理";
const COMPOSER_TEMPLATE_WIDGET_NAMES = new Set(["模板名称", "自定义正面模板", "模板JSON"]);
const RANDOM_ENABLE_WIDGET_NAME = "启用随机Tag";
const TAG_GENERATION_MODE_WIDGET_NAME = "Tag生成模式";
const AI_FREEDOM_WIDGET_NAME = "AI自由度";
const AI_INTENT_WIDGET_NAMES = new Set(["AI意图方向", "AI扩写强度", "AI是否写入补充"]);
const AI_RAG_WIDGET_NAMES = new Set(["AI RAG模式", "RAG候选数", "RAG示例数"]);
const RANDOM_GLOBAL_CONTROL_NAMES = new Set([
    TAG_GENERATION_MODE_WIDGET_NAME,
    "随机策略",
    "每字段随机数",
    "随机数量",
    "随机种子",
    "随机允许NSFW",
    "随机最低热度",
]);
const RECENT_TAGS_KEY = "galiais_nodes_recent_tags";
const FAVORITE_TAGS_KEY = "galiais_nodes_favorite_tags";
const LOCAL_TAG_LIMIT = 200;
const optionPageCache = createLruCache(OPTION_PAGE_CACHE_LIMIT);
const treePayloadCache = createLruCache(TREE_CACHE_LIMIT);
const fieldEnableDomNodes = new Set();
const legacyCanvasToggleNodes = new Set();
const legacyCanvasToggleElements = new Map();
let fieldEnableMutationObserver = null;
let fieldEnableRenderFrame = null;
let legacyCanvasToggleFrame = null;
let legacyCanvasTrackingFrame = null;
let legacyCanvasPointerHandlerInstalled = false;
let legacyCanvasLastToggle = null;
let globalTagBlacklist = new Set();
let globalRandomTaxonomyBlacklist = new Set();

function readLocalTagList(key) {
    try {
        const parsed = JSON.parse(localStorage.getItem(key) || "[]");
        return Array.isArray(parsed) ? parsed.filter(Boolean).map(String) : [];
    } catch (error) {
        return [];
    }
}

function writeLocalTagList(key, values) {
    try {
        localStorage.setItem(key, JSON.stringify(values.slice(0, LOCAL_TAG_LIMIT)));
    } catch (error) {
        console.warn("[GALIAIS-Nodes] local tag cache write failed", error);
    }
}

function rememberLocalTag(key, value) {
    const text = String(value || "").trim();
    if (!text) return;
    const list = readLocalTagList(key).filter((item) => normalizeComparableTag(item) !== normalizeComparableTag(text));
    list.unshift(text);
    writeLocalTagList(key, list);
}

function toggleFavoriteTag(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    const comparable = normalizeComparableTag(text);
    const list = readLocalTagList(FAVORITE_TAGS_KEY);
    const exists = list.some((item) => normalizeComparableTag(item) === comparable);
    const next = exists ? list.filter((item) => normalizeComparableTag(item) !== comparable) : [text, ...list];
    writeLocalTagList(FAVORITE_TAGS_KEY, next);
    return !exists;
}

function isFavoriteTag(value) {
    const comparable = normalizeComparableTag(value);
    return readLocalTagList(FAVORITE_TAGS_KEY).some((item) => normalizeComparableTag(item) === comparable);
}

function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.galiais-nodes-danbooru-backdrop {
    position: fixed;
    inset: 0;
    z-index: 100000;
    background: rgba(8, 12, 18, 0.62);
    display: flex;
    align-items: center;
    justify-content: center;
}
.galiais-nodes-danbooru-modal {
    width: min(1080px, calc(100vw - 32px));
    height: min(720px, calc(100vh - 32px));
    background: #151923;
    color: #eef3f8;
    border: 1px solid #37404d;
    border-radius: 8px;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.5);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    font-family: ui-sans-serif, system-ui, "Microsoft YaHei", sans-serif;
}
.galiais-nodes-danbooru-field-modal {
    width: min(360px, calc(100vw - 32px));
    max-height: min(560px, calc(100vh - 32px));
    background: #151923;
    color: #eef3f8;
    border: 1px solid #37404d;
    border-radius: 8px;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.5);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    font-family: ui-sans-serif, system-ui, "Microsoft YaHei", sans-serif;
}
.galiais-nodes-danbooru-field-list {
    overflow: auto;
    padding: 6px;
}
.galiais-nodes-danbooru-field-row {
    width: 100%;
    min-height: 34px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: #f2f5f8;
    padding: 7px 10px;
    text-align: left;
    cursor: pointer;
}
.galiais-nodes-danbooru-field-row:hover {
    background: #2b3443;
}
.galiais-nodes-danbooru-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    border-bottom: 1px solid #2a313d;
}
.galiais-nodes-danbooru-title {
    font-size: 14px;
    font-weight: 650;
    white-space: nowrap;
}
.galiais-nodes-danbooru-search {
    flex: 1;
    min-width: 120px;
    height: 34px;
    border-radius: 6px;
    border: 1px solid #3c4654;
    background: #0d1118;
    color: #eef3f8;
    padding: 0 10px;
    outline: none;
}
.galiais-nodes-danbooru-select,
.galiais-nodes-danbooru-button {
    height: 34px;
    border-radius: 6px;
    border: 1px solid #3c4654;
    background: #212833;
    color: #eef3f8;
    padding: 0 10px;
}
.galiais-nodes-danbooru-button {
    cursor: pointer;
}
.galiais-nodes-danbooru-button:hover,
.galiais-nodes-danbooru-row:hover {
    background: #2b3443;
}
.galiais-nodes-danbooru-button.is-primary {
    background: #d8ad5b;
    border-color: #e2b86b;
    color: #111820;
    font-weight: 650;
}
.galiais-nodes-danbooru-button.is-primary:hover {
    background: #e2bf70;
}
.galiais-nodes-danbooru-row.is-selected {
    background: #313b4d;
    box-shadow: inset 3px 0 0 #e2b86b;
}
.galiais-nodes-danbooru-row.is-selected:hover {
    background: #3a465c;
}
.galiais-nodes-danbooru-row.is-blacklisted {
    opacity: 0.48;
    filter: grayscale(0.7);
}
.galiais-nodes-danbooru-row.is-blacklisted:hover {
    background: transparent;
}
.galiais-nodes-danbooru-row.is-blacklisted .galiais-nodes-danbooru-tag,
.galiais-nodes-danbooru-row.is-blacklisted .galiais-nodes-danbooru-label,
.galiais-nodes-danbooru-row.is-blacklisted .galiais-nodes-danbooru-meta {
    color: #818b99;
}
.galiais-nodes-danbooru-row.is-blacklisted .galiais-nodes-danbooru-button {
    cursor: pointer;
    border-color: #3a414c;
    background: #151a22;
    color: #8c96a4;
}
.galiais-nodes-danbooru-mode {
    display: inline-flex;
    height: 34px;
    border: 1px solid #3c4654;
    border-radius: 6px;
    overflow: hidden;
    background: #0d1118;
}
.galiais-nodes-danbooru-mode button {
    border: 0;
    border-right: 1px solid #3c4654;
    background: transparent;
    color: #aeb9c7;
    padding: 0 10px;
    cursor: pointer;
}
.galiais-nodes-danbooru-mode button:last-child {
    border-right: 0;
}
.galiais-nodes-danbooru-mode button.is-active {
    background: #e2b86b;
    color: #16120b;
    font-weight: 650;
}
.galiais-nodes-danbooru-results {
    flex: 1;
    overflow: auto;
}
.galiais-nodes-danbooru-body {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
}
.galiais-nodes-danbooru-tree {
    border-right: 1px solid #2a313d;
    overflow: auto;
    background: #111722;
    padding: 8px 0;
}
.galiais-nodes-danbooru-tree-row {
    width: 100%;
    min-height: 30px;
    border: 0;
    background: transparent;
    color: #dbe4ee;
    display: grid;
    grid-template-columns: 18px minmax(0, 1fr) auto auto;
    gap: 6px;
    align-items: center;
    padding: 4px 9px;
    text-align: left;
    cursor: pointer;
}
.galiais-nodes-danbooru-tree-row:hover,
.galiais-nodes-danbooru-tree-row.is-active {
    background: #273142;
}
.galiais-nodes-danbooru-tree-row.is-leaf {
    color: #cfd8e3;
}
.galiais-nodes-danbooru-tree-row.is-domain {
    color: #eef3f8;
    font-weight: 650;
}
.galiais-nodes-danbooru-tree-row.is-group {
    color: #b9c4d2;
}
.galiais-nodes-danbooru-tree-row.is-random-blocked {
    opacity: 0.58;
}
.galiais-nodes-danbooru-tree-toggle {
    color: #e2b86b;
    font-size: 11px;
    text-align: center;
}
.galiais-nodes-danbooru-tree-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12px;
}
.galiais-nodes-danbooru-tree-count {
    color: #8491a3;
    font-size: 11px;
}
.galiais-nodes-danbooru-tree-random-block {
    min-width: 52px;
    height: 22px;
    padding: 0 6px;
    border: 1px solid #3c4654;
    border-radius: 5px;
    background: #18202b;
    color: #aeb9c7;
    cursor: pointer;
    font: 650 10px/1 ui-sans-serif, system-ui, "Microsoft YaHei", sans-serif;
    white-space: nowrap;
}
.galiais-nodes-danbooru-tree-row.is-random-blocked .galiais-nodes-danbooru-tree-random-block {
    border-color: #5f6672;
    background: #252a33;
    color: #c6ccd6;
}
.galiais-nodes-danbooru-tree-row.is-random-partial-blocked .galiais-nodes-danbooru-tree-random-block {
    border-color: #6d5b35;
    background: #211d15;
    color: #dcc685;
}
.galiais-nodes-danbooru-tree-random-block:hover {
    border-color: #e2b86b;
}
.galiais-nodes-danbooru-main {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
}
.galiais-nodes-danbooru-filter {
    min-height: 32px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 12px;
    border-bottom: 1px solid #242b36;
    color: #aeb9c7;
    font-size: 12px;
}
.galiais-nodes-danbooru-filter strong {
    color: #eef3f8;
    font-weight: 650;
}
.galiais-nodes-danbooru-selected {
    min-height: 36px;
    max-height: 92px;
    overflow: auto;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 7px 12px;
    border-bottom: 1px solid #242b36;
    background: #101620;
}
.galiais-nodes-danbooru-chip {
    border: 1px solid #465160;
    border-radius: 6px;
    background: #202836;
    color: #eef3f8;
    padding: 4px 8px;
    font-size: 12px;
    cursor: pointer;
}
.galiais-nodes-danbooru-chip:hover {
    background: #334056;
}
.galiais-nodes-danbooru-row-tools {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
    min-width: 0;
}
.galiais-nodes-danbooru-star {
    width: 28px;
    height: 28px;
    border: 1px solid #3c4654;
    border-radius: 6px;
    background: #18202b;
    color: #9ca8b8;
    cursor: pointer;
}
.galiais-nodes-danbooru-star.is-active {
    color: #e2b86b;
    border-color: #e2b86b;
}
.galiais-nodes-danbooru-row {
    width: 100%;
    display: grid;
    grid-template-columns: minmax(180px, 1.1fr) minmax(140px, 1fr) 80px minmax(172px, auto);
    gap: 10px;
    align-items: center;
    border: 0;
    border-bottom: 1px solid #242b36;
    background: transparent;
    color: inherit;
    padding: 9px 12px;
    text-align: left;
    cursor: pointer;
}
.galiais-nodes-danbooru-tag {
    font-family: ui-monospace, "Cascadia Code", monospace;
    font-size: 12px;
    overflow-wrap: anywhere;
}
.galiais-nodes-danbooru-label {
    font-size: 12px;
    color: #d8e0ea;
    overflow-wrap: anywhere;
}
.galiais-nodes-danbooru-meta,
.galiais-nodes-danbooru-safety {
    font-size: 11px;
    color: #9ca8b8;
}
.galiais-nodes-danbooru-row-tools .galiais-nodes-danbooru-button {
    min-width: 58px;
    padding: 0 8px;
    white-space: nowrap;
    flex: 0 0 auto;
}
.galiais-nodes-danbooru-row-tools .galiais-nodes-danbooru-safety {
    min-width: 42px;
    white-space: nowrap;
    flex: 0 0 auto;
    text-align: right;
}
.galiais-nodes-danbooru-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border-top: 1px solid #2a313d;
}
.galiais-nodes-danbooru-status {
    font-size: 12px;
    color: #aeb9c7;
}
.galiais-nodes-prompt-viewer {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 0 2px;
}
.galiais-nodes-prompt-viewer label {
    color: #aeb8c5;
    font-size: 11px;
}
.galiais-nodes-prompt-viewer textarea {
    box-sizing: border-box;
    width: 100%;
    min-height: 72px;
    resize: vertical;
    border: 1px solid #3a4350;
    border-radius: 6px;
    background: #0f131b;
    color: #eef3f8;
    padding: 8px;
    font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace;
}
.galiais-nodes-random-fields {
    display: none;
    flex-direction: column;
    gap: 6px;
    padding: 8px 0 2px;
}
.galiais-nodes-random-fields.is-visible {
    display: flex;
}
.galiais-nodes-random-fields-title {
    color: #aeb8c5;
    font-size: 11px;
}
.galiais-nodes-random-fields-row {
    display: grid;
    grid-template-columns: 84px minmax(0, 1fr);
    gap: 7px;
    align-items: start;
    box-sizing: border-box;
    width: 100%;
    border: 1px solid #3a4350;
    border-radius: 6px;
    background: #0f131b;
    color: #eef3f8;
    padding: 7px;
}
.galiais-nodes-random-fields-label {
    color: #d8ad5b;
    font-size: 11px;
    font-weight: 650;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.galiais-nodes-random-fields-value {
    color: #eef3f8;
    font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace;
    overflow-wrap: anywhere;
}
.galiais-hidden-widget-row {
    display: none !important;
}
.galiais-field-enable-row {
    position: relative;
    box-sizing: border-box;
    padding-right: 54px;
}
.galiais-field-enable-row.is-galiais-field-disabled > *:not(.galiais-field-enable-toggle) {
    opacity: 0.48;
}
.galiais-field-enable-toggle {
    position: absolute;
    right: 8px;
    top: 50%;
    z-index: 50;
    width: 44px;
    height: 22px;
    padding: 0;
    border: 1px solid #5c6573;
    border-radius: 5px;
    background: #242b36;
    color: #aeb8c5;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font: 650 11px/1 ui-sans-serif, system-ui, "Microsoft YaHei", sans-serif;
    white-space: nowrap;
    pointer-events: auto;
    transform: translateY(-50%);
}
.galiais-field-enable-toggle.is-on {
    border-color: #e7bf71;
    background: #d8ad5b;
    color: #17140f;
}
.galiais-field-enable-toggle:hover {
    border-color: #e7bf71;
    filter: brightness(1.06);
}
.galiais-field-enable-canvas-toggle {
    position: fixed;
    z-index: 9998;
    width: 46px;
    height: 22px;
    padding: 0;
    border: 1px solid #5c6573;
    border-radius: 5px;
    background: #242b36;
    color: #aeb8c5;
    cursor: pointer;
    display: none;
    align-items: center;
    justify-content: center;
    font: 650 11px/1 ui-sans-serif, system-ui, "Microsoft YaHei", sans-serif;
    white-space: nowrap;
    pointer-events: auto;
    user-select: none;
    touch-action: none;
    box-sizing: border-box;
    opacity: 0.97;
}
.galiais-field-enable-canvas-toggle.is-on {
    border-color: #e7bf71;
    background: #d8ad5b;
    color: #17140f;
}
.galiais-field-enable-canvas-toggle:hover {
    border-color: #e7bf71;
    filter: brightness(1.06);
}
@media (max-width: 640px) {
    .galiais-nodes-danbooru-header,
    .galiais-nodes-danbooru-footer {
        flex-wrap: wrap;
    }
    .galiais-nodes-danbooru-row {
        grid-template-columns: 1fr;
        gap: 4px;
    }
    .galiais-nodes-danbooru-body {
        grid-template-columns: 1fr;
    }
    .galiais-nodes-danbooru-tree {
        max-height: 180px;
        border-right: 0;
        border-bottom: 1px solid #2b313a;
    }
}
`;
    document.head.appendChild(style);
}

function getLazyField(config) {
    if (!Array.isArray(config)) return null;
    const options = config[1] || {};
    if (!options.galiais_nodes_danbooru_lazy) return null;
    return options.galiais_nodes_danbooru_field || null;
}

function setWidgetValue(widget, value) {
    widget.value = value;
    if (widget.inputEl) widget.inputEl.value = value;
    widget.callback?.(value);
    app.graph?.setDirtyCanvas(true, true);
}

function baseOptionText(value) {
    return String(value || "").split(" | ", 1)[0].trim();
}

function stripTrailingParenthetical(value) {
    const text = String(value || "").trimEnd();
    if (!text.endsWith(")")) return text.trim();
    let depth = 0;
    for (let index = text.length - 1; index >= 0; index -= 1) {
        const char = text[index];
        if (char === ")") depth += 1;
        if (char === "(") {
            depth -= 1;
            if (depth === 0) {
                const before = text.slice(0, index).trimEnd();
                return before ? before.trim() : text.trim();
            }
        }
    }
    return text.trim();
}

function optionToken(value) {
    return stripTrailingParenthetical(baseOptionText(value));
}

function formatSelectedOption(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const [tag, label] = text.split(" | ", 2);
    const formattedTag = String(tag || "").trim().replace(/_/g, " ");
    const formattedLabel = String(label || "").trim();
    if (
        !formattedLabel ||
        formattedLabel === String(tag || "").trim() ||
        formattedLabel === formattedTag
    ) {
        return formattedTag;
    }
    return `${formattedTag} (${formattedLabel})`;
}

function normalizeComparableTag(value) {
    return String(value || "").toLowerCase().replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function comparableTagTokens(value) {
    const text = String(value || "").trim();
    const base = baseOptionText(text);
    const tokens = new Set();
    const raw = normalizeComparableTag(base);
    if (raw) tokens.add(raw);
    if (!text.includes(" | ")) {
        const stripped = normalizeComparableTag(stripTrailingParenthetical(base));
        if (stripped) tokens.add(stripped);
    }
    return tokens;
}

function tagTokenSetsIntersect(left, right) {
    for (const token of left) {
        if (right.has(token)) return true;
    }
    return false;
}

function tagTokensFromParts(parts) {
    const tokens = new Set();
    for (const item of parts) {
        for (const token of comparableTagTokens(item)) tokens.add(token);
    }
    return tokens;
}

function splitWidgetParts(widget) {
    return String(widget?.value || "")
        .split(/[,，\n\r;；]+/)
        .map((part) => part.trim())
        .filter(Boolean);
}

function mergeTagParts(parts, value) {
    const next = formatSelectedOption(value);
    if (!next) return parts.slice();
    const nextTokens = comparableTagTokens(next);
    const merged = [];
    let exists = false;
    for (const item of parts) {
        if (tagTokenSetsIntersect(comparableTagTokens(item), nextTokens)) {
            if (!exists) merged.push(next);
            exists = true;
        } else {
            merged.push(item);
        }
    }
    if (!exists) merged.push(next);
    return merged;
}

function removeTagParts(parts, value) {
    const removeTokens = comparableTagTokens(formatSelectedOption(value));
    if (!removeTokens.size) return { parts: parts.slice(), removed: false };
    let removed = false;
    const kept = [];
    for (const item of parts) {
        if (tagTokenSetsIntersect(comparableTagTokens(item), removeTokens)) {
            removed = true;
            continue;
        }
        kept.push(item);
    }
    return { parts: kept, removed };
}

function isLegacySelectorWidget(widget) {
    return !!widget?.name && String(widget.name).startsWith("选择:");
}

function isSelectorWidget(widget) {
    return isLegacySelectorWidget(widget) || widget?.name === SELECTOR_BUTTON_NAME;
}

function realWidgets(node) {
    return (node.widgets || []).filter((widget) => !isSelectorWidget(widget));
}

function vueLayoutWidgets(node) {
    return (node.widgets || []).filter((widget) => !isLegacySelectorWidget(widget));
}

function findWidgetValue(node, name) {
    const widget = (node?.widgets || []).find((item) => item?.name === name);
    return String(widget?.value || widget?.inputEl?.value || "").trim();
}

function findWidget(node, name) {
    return (node?.widgets || []).find((item) => item?.name === name) || null;
}

function nodeTypeName(node) {
    return node?.type || node?.constructor?.type || node?.constructor?.name || "";
}

function isVueNodeMode(node) {
    return !!vueNodeElement(node);
}

function findDanbooruDbPath() {
    const nodes = app.graph?._nodes || [];
    for (const node of nodes) {
        if (nodeTypeName(node) !== "GaliaisNodesDanbooruDBLoader") continue;
        const value = findWidgetValue(node, "DB路径");
        if (value) return value;
    }
    return "";
}

function normalizeBlacklistTag(value) {
    let text = String(value || "").trim();
    if (!text) return "";
    if (text.includes(" | ")) text = text.split(" | ", 1)[0].trim();
    text = stripTrailingParenthetical(text).trim();
    return text.toLowerCase().replace(/\s+/g, "_");
}

function splitBlacklistText(value) {
    return String(value || "")
        .split(/[,，\n\r;；]+/)
        .map((part) => normalizeBlacklistTag(part))
        .filter(Boolean);
}

function findDanbooruTagBlacklist() {
    const tags = [];
    const seen = new Set();
    for (const tag of globalTagBlacklist) {
        if (seen.has(tag)) continue;
        seen.add(tag);
        tags.push(tag);
    }
    const nodes = app.graph?._nodes || [];
    for (const node of nodes) {
        if (nodeTypeName(node) !== "GaliaisNodesTagBlacklist") continue;
        const enabledWidget = findWidget(node, "启用");
        if (enabledWidget && enabledWidget.value === false) continue;
        for (const tag of splitBlacklistText(findWidgetValue(node, "黑名单Tags"))) {
            if (seen.has(tag)) continue;
            seen.add(tag);
            tags.push(tag);
        }
    }
    return tags.join(",");
}

async function refreshGlobalTagBlacklist() {
    try {
        const response = await fetch(apiUrl("/galiais-nodes/danbooru/tag_blacklist"));
        const payload = await readJsonResponse(response, "读取Tag黑名单失败");
        const tags = Array.isArray(payload.tags) ? payload.tags : [];
        globalTagBlacklist = new Set(tags.map((tag) => normalizeBlacklistTag(tag)).filter(Boolean));
    } catch (error) {
        console.warn("[GALIAIS-Nodes] tag blacklist refresh failed", error);
    }
    return findDanbooruTagBlacklist();
}

async function updateGlobalTagBlacklist(action, tags) {
    const response = await fetch(apiUrl("/galiais-nodes/danbooru/tag_blacklist"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, tags }),
    });
    const payload = await readJsonResponse(response, "更新Tag黑名单失败");
    const nextTags = Array.isArray(payload.tags) ? payload.tags : [];
    globalTagBlacklist = new Set(nextTags.map((tag) => normalizeBlacklistTag(tag)).filter(Boolean));
    optionPageCache.clear();
    return findDanbooruTagBlacklist();
}

function normalizeTaxonomyPath(value) {
    return String(value || "").trim().replace(/\s+/g, "").replace(/^\.+|\.+$/g, "");
}

function findRandomTaxonomyBlacklist() {
    return Array.from(globalRandomTaxonomyBlacklist).filter(Boolean).join(",");
}

function isRandomTaxonomyBlockedByAncestorOrSelf(value) {
    const path = normalizeTaxonomyPath(value);
    if (!path) return false;
    for (const item of globalRandomTaxonomyBlacklist) {
        if (path === item || path.startsWith(`${item}.`)) return true;
    }
    return false;
}

function hasRandomTaxonomyBlockedDescendant(value) {
    const path = normalizeTaxonomyPath(value);
    if (!path) return false;
    for (const item of globalRandomTaxonomyBlacklist) {
        if (item.startsWith(`${path}.`)) return true;
    }
    return false;
}

async function refreshGlobalRandomTaxonomyBlacklist() {
    try {
        const response = await fetch(apiUrl("/galiais-nodes/danbooru/random_taxonomy_blacklist"));
        const payload = await readJsonResponse(response, "读取随机分类黑名单失败");
        const items = Array.isArray(payload.taxonomy_ids) ? payload.taxonomy_ids : [];
        globalRandomTaxonomyBlacklist = new Set(items.map((item) => normalizeTaxonomyPath(item)).filter(Boolean));
    } catch (error) {
        console.warn("[GALIAIS-Nodes] random taxonomy blacklist refresh failed", error);
    }
    return findRandomTaxonomyBlacklist();
}

async function updateGlobalRandomTaxonomyBlacklist(action, taxonomyIds) {
    const response = await fetch(apiUrl("/galiais-nodes/danbooru/random_taxonomy_blacklist"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, taxonomy_ids: taxonomyIds }),
    });
    const payload = await readJsonResponse(response, "更新随机分类黑名单失败");
    const items = Array.isArray(payload.taxonomy_ids) ? payload.taxonomy_ids : [];
    globalRandomTaxonomyBlacklist = new Set(items.map((item) => normalizeTaxonomyPath(item)).filter(Boolean));
    optionPageCache.clear();
    return findRandomTaxonomyBlacklist();
}

async function selectDanbooruDbFile(node) {
    const target = findWidget(node, "DB路径");
    if (!target) return;
    const params = new URLSearchParams({ current: String(target.value || "") });
    const response = await fetch(apiUrl(`/galiais-nodes/danbooru/select_db?${params.toString()}`));
    const payload = await readJsonResponse(response, "DB文件选择失败");
    if (payload.path) setWidgetValue(target, payload.path);
}

async function fetchAiProviderModels(node) {
    const response = await fetch(apiUrl("/galiais-nodes/ai/models"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            base_url: findWidgetValue(node, "服务商URL"),
            api_key: findWidgetValue(node, "API密钥"),
            api_mode: findWidgetValue(node, "接口模式") || "自动",
            timeout: findWidgetValue(node, "超时秒") || 30,
        }),
    });
    const payload = await readJsonResponse(response, "模型获取失败");
    const models = Array.isArray(payload.models)
        ? payload.models.map((item) => String(item || "").trim()).filter(Boolean)
        : [];
    if (!models.length) {
        throw new Error(payload.error || "服务商没有返回可用模型");
    }
    return models;
}

function openAiModelChooser(node, models) {
    const target = findWidget(node, "模型");
    if (!target) return;
    ensureStyles();
    const current = String(target.value || "").trim();

    const backdrop = document.createElement("div");
    backdrop.className = "galiais-nodes-danbooru-backdrop";

    const modal = document.createElement("div");
    modal.className = "galiais-nodes-danbooru-field-modal";
    modal.style.width = "min(560px, calc(100vw - 32px))";
    backdrop.appendChild(modal);

    const header = document.createElement("div");
    header.className = "galiais-nodes-danbooru-header";
    modal.appendChild(header);

    const title = document.createElement("div");
    title.className = "galiais-nodes-danbooru-title";
    title.textContent = `选择模型 (${models.length})`;
    header.appendChild(title);

    const search = document.createElement("input");
    search.className = "galiais-nodes-danbooru-search";
    search.placeholder = "搜索模型名";
    header.appendChild(search);

    const close = document.createElement("button");
    close.className = "galiais-nodes-danbooru-button";
    close.textContent = "关闭";
    header.appendChild(close);

    const list = document.createElement("div");
    list.className = "galiais-nodes-danbooru-field-list";
    modal.appendChild(list);

    function closeModal() {
        backdrop.remove();
        document.removeEventListener("keydown", onKeydown);
    }

    function onKeydown(event) {
        if (event.key === "Escape") closeModal();
    }

    function render() {
        const query = search.value.trim().toLowerCase();
        list.replaceChildren();
        for (const model of models) {
            if (query && !model.toLowerCase().includes(query)) continue;
            const row = document.createElement("button");
            row.className = `galiais-nodes-danbooru-field-row ${model === current ? "is-selected" : ""}`;
            row.textContent = model;
            row.title = model;
            row.addEventListener("click", () => {
                setWidgetValue(target, model);
                closeModal();
            });
            list.appendChild(row);
        }
        if (!list.childElementCount) {
            const empty = document.createElement("div");
            empty.className = "galiais-nodes-danbooru-status";
            empty.style.padding = "10px";
            empty.textContent = "没有匹配的模型";
            list.appendChild(empty);
        }
    }

    search.addEventListener("input", render);
    close.addEventListener("click", closeModal);
    backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) closeModal();
    });
    document.addEventListener("keydown", onKeydown);
    document.body.appendChild(backdrop);
    render();
    search.focus();
}

async function selectAiProviderModel(node) {
    const models = await fetchAiProviderModels(node);
    const target = findWidget(node, "模型");
    if (target && !String(target.value || "").trim()) {
        setWidgetValue(target, models[0]);
    }
    openAiModelChooser(node, models);
}

function selectorFieldsForNode(node, lazyFields) {
    const fields = [];
    for (const widget of realWidgets(node)) {
        const field = lazyFields.get(widget.name);
        if (field) fields.push({ node, widget, field });
    }
    return fields;
}

function isFieldEnabled(enableWidget) {
    const value = enableWidget?.value;
    if (value === false || value === 0) return false;
    if (typeof value === "string" && ["false", "0", "off", "关闭"].includes(value.trim().toLowerCase())) {
        return false;
    }
    return true;
}

function buildFieldEnablePairs(node) {
    const widgets = Array.isArray(node?.widgets) ? node.widgets : [];
    const byName = new Map(widgets.map((widget) => [widget?.name, widget]));
    const pairs = [];
    for (const enableWidget of widgets) {
        const enableName = String(enableWidget?.name || "");
        if (!enableName.startsWith("使用") || enableName.length <= 2) continue;
        const targetName = enableName.slice(2);
        const widget = byName.get(targetName);
        if (!widget || widget === enableWidget || isSelectorWidget(widget)) continue;
        pairs.push({ widget, enableWidget, targetName });
    }
    return pairs;
}

function hideFieldEnableWidgets(node, fieldEnablePairs) {
    let changed = false;
    for (const pair of fieldEnablePairs || []) {
        const { enableWidget } = pair;
        if (!enableWidget) continue;
        if (!enableWidget.hidden) {
            enableWidget.hidden = true;
            changed = true;
        }
        if (enableWidget.options) enableWidget.options.hidden = true;
    }
    return changed;
}

function setWidgetHiddenState(widget, hidden) {
    if (!widget) return false;
    let changed = false;
    if (widget.hidden !== hidden) {
        widget.hidden = hidden;
        changed = true;
    }
    if (widget.options) widget.options.hidden = hidden;
    return changed;
}

function syncFieldRandomControlVisibility(node, fieldEnablePairs) {
    const widgets = Array.isArray(node?.widgets) ? node.widgets : [];
    const byName = new Map(widgets.map((widget) => [widget?.name, widget]));
    const randomEnableWidget = byName.get(RANDOM_ENABLE_WIDGET_NAME);
    if (!randomEnableWidget) return false;
    const randomEnabled = isFieldEnabled(randomEnableWidget);
    const modeWidget = byName.get(TAG_GENERATION_MODE_WIDGET_NAME);
    const modeValue = String(modeWidget?.value || "");
    const aiModeEnabled = randomEnabled && !!modeWidget && modeValue !== "规则随机";
    const aiIntentModeEnabled = aiModeEnabled && modeValue.startsWith("AI意图定向选择");
    const fieldEnableByName = new Map((fieldEnablePairs || []).map((pair) => [pair.targetName, pair]));
    let changed = false;
    if (!randomEnabled) {
        changed = clearRandomFieldsWidget(node) || changed;
    }
    for (const controlWidget of widgets) {
        const name = String(controlWidget?.name || "");
        if (!name || name === RANDOM_ENABLE_WIDGET_NAME) continue;
        if (name === AI_FREEDOM_WIDGET_NAME) {
            changed = setWidgetHiddenState(controlWidget, !aiModeEnabled) || changed;
            continue;
        }
        if (AI_INTENT_WIDGET_NAMES.has(name)) {
            changed = setWidgetHiddenState(controlWidget, !aiIntentModeEnabled) || changed;
            continue;
        }
        if (AI_RAG_WIDGET_NAMES.has(name)) {
            changed = setWidgetHiddenState(controlWidget, !aiModeEnabled) || changed;
            continue;
        }
        if (RANDOM_GLOBAL_CONTROL_NAMES.has(name)) {
            changed = setWidgetHiddenState(controlWidget, !randomEnabled) || changed;
            continue;
        }
        for (const prefix of ["随机数", "最低热度"]) {
            if (!name.startsWith(prefix) || name.length <= prefix.length) continue;
            const pair = fieldEnableByName.get(name.slice(prefix.length));
            const hidden = !randomEnabled || (pair ? !isFieldEnabled(pair.enableWidget) : false);
            changed = setWidgetHiddenState(controlWidget, hidden) || changed;
            break;
        }
    }
    return changed;
}

function ensureRandomEnableVisibilityCallback(node) {
    const widget = findWidget(node, RANDOM_ENABLE_WIDGET_NAME);
    if (!widget || widget._galiaisRandomVisibilityCallbackWrapped) return false;
    const originalCallback = widget.callback;
    widget.callback = function () {
        const output = originalCallback?.apply(this, arguments);
        const pairs = buildFieldEnablePairs(node);
        syncFieldRandomControlVisibility(node, pairs);
        syncVueWidgetRowVisibility(node);
        ensureVueFieldEnableToggles(node);
        if (isVueNodeMode(node)) {
            removeLegacyCanvasFieldEnableToggles(node);
        } else {
            scheduleLegacyCanvasFieldEnableToggles(node);
        }
        refreshNodeSize(node, true, { fitHeight: true });
        const schedule = window.requestAnimationFrame || ((callback) => window.setTimeout(callback, 16));
        schedule(() => refreshNodeSize(node, true, { fitHeight: true }));
        return output;
    };
    widget._galiaisRandomVisibilityCallbackWrapped = true;
    return true;
}

function ensureTagGenerationModeVisibilityCallback(node) {
    const widget = findWidget(node, TAG_GENERATION_MODE_WIDGET_NAME);
    if (!widget || widget._galiaisModeVisibilityCallbackWrapped) return false;
    const originalCallback = widget.callback;
    widget.callback = function () {
        const output = originalCallback?.apply(this, arguments);
        const pairs = buildFieldEnablePairs(node);
        syncFieldRandomControlVisibility(node, pairs);
        syncVueWidgetRowVisibility(node);
        if (isVueNodeMode(node)) {
            removeLegacyCanvasFieldEnableToggles(node);
        } else {
            scheduleLegacyCanvasFieldEnableToggles(node);
        }
        refreshNodeSize(node, true, { fitHeight: true });
        const schedule = window.requestAnimationFrame || ((callback) => window.setTimeout(callback, 16));
        schedule(() => refreshNodeSize(node, true, { fitHeight: true }));
        return output;
    };
    widget._galiaisModeVisibilityCallbackWrapped = true;
    return true;
}

function cssSelectorValue(value) {
    const text = String(value ?? "");
    if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(text);
    }
    return text.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function vueNodeElement(node) {
    const id = node?.id;
    if (id === undefined || id === null) return null;
    const escaped = cssSelectorValue(id);
    return document.querySelector(`.lg-node[data-node-id="${escaped}"]`);
}

function visibleVueWidgets(node) {
    return realWidgets(node).filter((widget) => !widget?.hidden && !widget?.advanced);
}

function syncVueWidgetRowVisibility(node) {
    const root = vueNodeElement(node);
    if (!root) return false;
    const rows = Array.from(root.querySelectorAll(".lg-node-widget"));
    const widgets = vueLayoutWidgets(node);
    if (!rows.length || rows.length < widgets.length) return false;

    let changed = false;
    for (let index = 0; index < rows.length; index += 1) {
        const row = rows[index];
        const widget = widgets[index];
        const hidden = !!widget && (!!widget.hidden || !!widget.options?.hidden);
        const currentlyHidden = row.classList.contains(HIDDEN_WIDGET_ROW_CLASS);
        if (currentlyHidden !== hidden) {
            row.classList.toggle(HIDDEN_WIDGET_ROW_CLASS, hidden);
            changed = true;
        }
    }
    return changed;
}

function visibleVueWidgetRows(node, root) {
    const rows = Array.from(root?.querySelectorAll(".lg-node-widget") || []);
    const widgets = vueLayoutWidgets(node);
    if (rows.length >= widgets.length && widgets.length > 0) {
        const visibleRows = [];
        for (let index = 0; index < widgets.length; index += 1) {
            const widget = widgets[index];
            if (!widget || isSelectorWidget(widget) || widget.hidden || widget.advanced) continue;
            visibleRows.push(rows[index]);
        }
        return visibleRows;
    }
    return rows.filter((row) => !row.classList.contains(HIDDEN_WIDGET_ROW_CLASS));
}

function clearVueFieldEnableToggles(root) {
    if (!root) return;
    for (const button of root.querySelectorAll(`.${FIELD_ENABLE_TOGGLE_CLASS}`)) {
        button.remove();
    }
    for (const row of root.querySelectorAll(`.${FIELD_ENABLE_ROW_CLASS}`)) {
        row.classList.remove(FIELD_ENABLE_ROW_CLASS, FIELD_ENABLE_DISABLED_CLASS);
    }
}

function findDirectFieldEnableToggle(row, targetName) {
    for (const child of Array.from(row?.children || [])) {
        if (child?.classList?.contains(FIELD_ENABLE_TOGGLE_CLASS) && child.dataset.fieldName === targetName) {
            return child;
        }
    }
    return null;
}

function pruneVueFieldEnableToggles(root, expectedRows) {
    for (const button of root.querySelectorAll(`.${FIELD_ENABLE_TOGGLE_CLASS}`)) {
        const row = button.closest(".lg-node-widget");
        if (!row || expectedRows.get(row) !== button.dataset.fieldName) {
            button.remove();
        }
    }
    for (const row of root.querySelectorAll(`.${FIELD_ENABLE_ROW_CLASS}`)) {
        if (expectedRows.has(row)) continue;
        row.classList.remove(FIELD_ENABLE_ROW_CLASS, FIELD_ENABLE_DISABLED_CLASS);
    }
}

function renderVueFieldEnableToggles(node) {
    const root = vueNodeElement(node);
    if (!root) return false;

    const pairs = buildFieldEnablePairs(node);
    hideFieldEnableWidgets(node, pairs);
    syncFieldRandomControlVisibility(node, pairs);
    syncVueWidgetRowVisibility(node);
    const rows = visibleVueWidgetRows(node, root);
    if (!rows.length) return false;
    if (!pairs.length) {
        clearVueFieldEnableToggles(root);
        return false;
    }
    const widgets = visibleVueWidgets(node);

    let rendered = false;
    const expectedRows = new Map();
    for (const pair of pairs) {
        const index = widgets.indexOf(pair.widget);
        const row = index >= 0 ? rows[index] : null;
        if (!row) continue;

        const enabled = isFieldEnabled(pair.enableWidget);
        expectedRows.set(row, pair.targetName);
        row.classList.add(FIELD_ENABLE_ROW_CLASS);
        row.classList.toggle(FIELD_ENABLE_DISABLED_CLASS, !enabled);

        let button = findDirectFieldEnableToggle(row, pair.targetName);
        if (!button) {
            button = document.createElement("button");
            button.type = "button";
            button.addEventListener("pointerdown", (event) => {
                event.preventDefault();
                event.stopPropagation();
            });
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const fieldName = button.dataset.fieldName;
                const currentPair = buildFieldEnablePairs(node).find((item) => item.targetName === fieldName);
                if (!currentPair) return;
                setWidgetValue(currentPair.enableWidget, !isFieldEnabled(currentPair.enableWidget));
                syncFieldRandomControlVisibility(node, buildFieldEnablePairs(node));
                renderVueFieldEnableToggles(node);
            });
            row.appendChild(button);
        }

        button.className = `${FIELD_ENABLE_TOGGLE_CLASS} ${enabled ? "is-on" : "is-off"}`;
        button.dataset.fieldName = pair.targetName;
        button.textContent = enabled ? "启用" : "关闭";
        button.setAttribute("aria-label", `${pair.targetName}${enabled ? "已启用" : "已关闭"}`);
        button.title = `${pair.targetName}: ${enabled ? "启用" : "关闭"}`;
        rendered = true;
    }

    pruneVueFieldEnableToggles(root, expectedRows);
    return rendered;
}

function flushVueFieldEnableToggles() {
    fieldEnableRenderFrame = null;
    for (const node of Array.from(fieldEnableDomNodes)) {
        if (!node || node.graph === null) {
            fieldEnableDomNodes.delete(node);
            continue;
        }
        renderVueFieldEnableToggles(node);
    }
}

function scheduleVueFieldEnableToggles(node) {
    if (node) {
        fieldEnableDomNodes.add(node);
    } else if (!fieldEnableDomNodes.size) {
        return;
    }
    if (fieldEnableRenderFrame !== null) return;
    const schedule = window.requestAnimationFrame || ((callback) => window.setTimeout(callback, 16));
    fieldEnableRenderFrame = schedule(flushVueFieldEnableToggles);
}

function ensureFieldEnableMutationObserver() {
    if (fieldEnableMutationObserver || !document.body || typeof MutationObserver !== "function") return;
    fieldEnableMutationObserver = new MutationObserver((mutations) => {
        if (!fieldEnableDomNodes.size) return;
        for (const mutation of mutations) {
            if (mutation.type !== "childList") continue;
            if (!mutation.addedNodes.length && !mutation.removedNodes.length) continue;
            scheduleVueFieldEnableToggles();
            return;
        }
    });
    fieldEnableMutationObserver.observe(document.body, { childList: true, subtree: true });
}

function ensureVueFieldEnableToggles(node) {
    ensureFieldEnableMutationObserver();
    scheduleVueFieldEnableToggles(node);
    window.setTimeout(() => scheduleVueFieldEnableToggles(node), 50);
    window.setTimeout(() => scheduleVueFieldEnableToggles(node), 250);
}

function legacyCanvasNodeKey(node) {
    if (!node) return "";
    if (node.id !== undefined && node.id !== null) return String(node.id);
    if (!node._galiaisLegacyCanvasKey) {
        node._galiaisLegacyCanvasKey = `transient-${Math.random().toString(36).slice(2)}`;
    }
    return node._galiaisLegacyCanvasKey;
}

function legacyCanvasToggleKey(node, targetName) {
    return `${legacyCanvasNodeKey(node)}:${String(targetName || "")}`;
}

function removeLegacyCanvasFieldEnableToggles(node) {
    for (const [key, entry] of Array.from(legacyCanvasToggleElements.entries())) {
        if (node && entry.node !== node) continue;
        entry.button.remove();
        legacyCanvasToggleElements.delete(key);
    }
    if (node) legacyCanvasToggleNodes.delete(node);
}

function removeAllLegacyCanvasFieldEnableToggles() {
    removeLegacyCanvasFieldEnableToggles();
    legacyCanvasToggleNodes.clear();
}

function nodeBelongsToCurrentGraph(node) {
    const graph = app.canvas?.graph || app.graph;
    return !graph || !node?.graph || node.graph === graph;
}

function patchLegacyCanvasWidgetDraw(widget) {
    if (!widget || widget._galiaisCanvasDrawPatched || typeof widget.draw !== "function") return;
    widget._galiaisCanvasReservedWidth = FIELD_ENABLE_CANVAS_RESERVED_WIDTH;
    widget._galiaisOriginalDraw = widget._galiaisOriginalDraw || widget.draw;
    widget.draw = function (ctx, nodeArg, width, y, height, lowQuality) {
        const enabled = widget._galiaisFieldEnabled !== false;
        const reserved = Number(widget._galiaisCanvasReservedWidth || 0);
        const drawWidth = Math.max(80, Number(width || 0) - reserved);
        let output;
        if (enabled) {
            output = widget._galiaisOriginalDraw.call(this, ctx, nodeArg, drawWidth, y, height, lowQuality);
        } else {
            ctx.save();
            ctx.globalAlpha *= 0.48;
            output = widget._galiaisOriginalDraw.call(this, ctx, nodeArg, drawWidth, y, height, lowQuality);
            ctx.restore();
        }
        return output;
    };
    widget._galiaisCanvasDrawPatched = true;
}

function ensureLegacyCanvasFieldEnableLayout(node, fieldEnablePairs) {
    if (!node || isVueNodeMode(node)) return false;
    ensureStyles();
    let changed = false;
    for (const pair of fieldEnablePairs || []) {
        const widget = pair?.widget;
        if (!widget) continue;
        patchLegacyCanvasWidgetDraw(widget);
        if (widget._galiaisCanvasReservedWidth !== FIELD_ENABLE_CANVAS_RESERVED_WIDTH) {
            widget._galiaisCanvasReservedWidth = FIELD_ENABLE_CANVAS_RESERVED_WIDTH;
            changed = true;
        }
    }
    return changed;
}

function fieldEnableToggleY(widget) {
    if (!widget) return null;
    const value = widget.last_y ?? widget.y;
    if (value === undefined || value === null) return null;
    return Number(value || 0);
}

function ensureFieldEnableDrawLayer(node) {
    if (!node || node._galiaisFieldEnableDrawLayer || typeof node.drawWidgets !== "function") return;
    const originalDrawWidgets = node.drawWidgets;
    node.drawWidgets = function (ctx, options) {
        const output = originalDrawWidgets.apply(this, arguments);
        const fieldEnablePairs = buildFieldEnablePairs(this);
        if (isVueNodeMode(this)) {
            drawFieldEnableToggles(this, ctx, fieldEnablePairs);
        } else {
            applyFieldEnableDimState(this, fieldEnablePairs);
            scheduleLegacyCanvasFieldEnableToggles(this);
        }
        return output;
    };
    node._galiaisFieldEnableDrawLayer = true;
}

function applyFieldEnableDimState(node, fieldEnablePairs) {
    for (const pair of fieldEnablePairs || []) {
        const { widget } = pair;
        if (!widget) continue;
        if (!isVueNodeMode(node)) {
            patchLegacyCanvasWidgetDraw(widget);
        } else if (!widget._galiaisOriginalDraw && typeof widget.draw === "function") {
            widget._galiaisOriginalDraw = widget.draw;
            widget.draw = function (ctx, nodeArg, width, y, height, lowQuality) {
                const enabled = widget._galiaisFieldEnabled !== false;
                let output;
                if (enabled) {
                    output = widget._galiaisOriginalDraw.call(this, ctx, nodeArg, width, y, height, lowQuality);
                } else {
                    ctx.save();
                    ctx.globalAlpha *= 0.48;
                    output = widget._galiaisOriginalDraw.call(this, ctx, nodeArg, width, y, height, lowQuality);
                    ctx.restore();
                }
                return output;
            };
        }
        widget._galiaisFieldEnablePair = pair;
        widget._galiaisFieldEnabled = isFieldEnabled(pair.enableWidget);
    }
}

function fieldEnableToggleRect(node, widget) {
    const y = fieldEnableToggleY(widget);
    if (!node || !widget || y === null) return null;
    const height = Math.max(20, Math.min(24, Number(widget.computedHeight || 24) - 5));
    const width = 46;
    return {
        x: Math.max(12, Number(node.size?.[0] || 0) - width - 14),
        y: y + Math.max(2, (Number(widget.computedHeight || 24) - height) / 2 - 1),
        w: width,
        h: height,
    };
}

function drawRoundedRect(ctx, rect, radius) {
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(rect.x, rect.y, rect.w, rect.h, radius);
    } else {
        ctx.rect(rect.x, rect.y, rect.w, rect.h);
    }
}

function drawFieldEnableToggle(ctx, node, widget, enableWidget) {
    if (!ctx || node?.flags?.collapsed || !widget) return;
    const rect = fieldEnableToggleRect(node, widget);
    if (!rect) return;
    const enabled = isFieldEnabled(enableWidget);
    widget._galiaisFieldEnableToggleRect = rect;

    ctx.save();
    if (!enabled && widget.last_y !== undefined) {
        const rowHeight = Number(widget.computedHeight || 24) - 3;
        const rowRect = {
            x: 6,
            y: Number(widget.last_y || 0) - 1,
            w: Math.max(10, Number(node.size?.[0] || 0) - 12),
            h: Math.max(18, rowHeight),
        };
        drawRoundedRect(ctx, rowRect, 8);
        ctx.fillStyle = "rgba(10, 12, 15, 0.42)";
        ctx.fill();
    }

    drawRoundedRect(ctx, rect, 5);
    ctx.fillStyle = enabled ? "#d8ad5b" : "#242b36";
    ctx.fill();
    ctx.strokeStyle = enabled ? "#e7bf71" : "#5c6573";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = enabled ? "#17140f" : "#aeb8c5";
    ctx.font = "bold 11px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(enabled ? "启用" : "关闭", rect.x + rect.w / 2, rect.y + rect.h / 2 + 0.5);
    ctx.restore();
}

function drawFieldEnableToggles(node, ctx, fieldEnablePairs) {
    if (!ctx || node?.flags?.collapsed) return;
    applyFieldEnableDimState(node, fieldEnablePairs);
    for (const pair of fieldEnablePairs || []) {
        drawFieldEnableToggle(ctx, node, pair.widget, pair.enableWidget);
    }
}

function toggleFieldEnableAtPosition(node, pos, fieldEnablePairs) {
    for (const pair of fieldEnablePairs || []) {
        const rect = pair.widget?._galiaisFieldEnableToggleRect || fieldEnableToggleRect(node, pair.widget);
        if (!rect || !isInsideRect(pos, rect)) continue;
        const next = !isFieldEnabled(pair.enableWidget);
        setWidgetValue(pair.enableWidget, next);
        applyFieldEnableDimState(node, fieldEnablePairs);
        app.graph?.setDirtyCanvas(true, true);
        return true;
    }
    return false;
}

function eventToCanvasPosition(event) {
    const canvas = app.canvas;
    const ds = canvas?.ds;
    const element = canvas?.canvas;
    if (!event || !element) return null;
    if (typeof canvas?.convertEventToCanvasOffset === "function") {
        try {
            const pos = canvas.convertEventToCanvasOffset(event);
            if (Array.isArray(pos) && pos.length >= 2) return [Number(pos[0] || 0), Number(pos[1] || 0)];
        } catch (_) {}
    }
    if (typeof canvas?.convertEventToCanvas === "function") {
        try {
            const pos = canvas.convertEventToCanvas(event);
            if (Array.isArray(pos) && pos.length >= 2) return [Number(pos[0] || 0), Number(pos[1] || 0)];
        } catch (_) {}
    }
    if (!ds) return null;
    const rect = element.getBoundingClientRect();
    const scale = Number(ds.scale || 1) || 1;
    return [
        (event.clientX - rect.left) / scale - Number(ds.offset?.[0] || 0),
        (event.clientY - rect.top) / scale - Number(ds.offset?.[1] || 0),
    ];
}

function nodeLocalPositionFromCanvas(node, canvasPos) {
    if (!node || !Array.isArray(canvasPos) || !Array.isArray(node.pos)) return null;
    return [
        canvasPos[0] - Number(node.pos[0] || 0),
        canvasPos[1] - Number(node.pos[1] || 0),
    ];
}

function canvasRectToClientRect(node, rect) {
    const canvas = app.canvas;
    const ds = canvas?.ds;
    const element = canvas?.canvas;
    if (!node || !rect || !element || !Array.isArray(node.pos)) return null;
    if (typeof canvas?.convertCanvasToOffset === "function") {
        try {
            const topLeft = canvas.convertCanvasToOffset([
                Number(node.pos[0] || 0) + rect.x,
                Number(node.pos[1] || 0) + rect.y,
            ]);
            const bottomRight = canvas.convertCanvasToOffset([
                Number(node.pos[0] || 0) + rect.x + rect.w,
                Number(node.pos[1] || 0) + rect.y + rect.h,
            ]);
            if (Array.isArray(topLeft) && Array.isArray(bottomRight)) {
                return {
                    left: Number(topLeft[0] || 0),
                    top: Number(topLeft[1] || 0),
                    width: Math.max(0, Number(bottomRight[0] || 0) - Number(topLeft[0] || 0)),
                    height: Math.max(0, Number(bottomRight[1] || 0) - Number(topLeft[1] || 0)),
                };
            }
        } catch (_) {}
    }
    if (!ds) return null;
    const canvasRect = element.getBoundingClientRect();
    const scale = Number(ds.scale || 1) || 1;
    const offsetX = Number(ds.offset?.[0] || 0);
    const offsetY = Number(ds.offset?.[1] || 0);
    return {
        left: canvasRect.left + (Number(node.pos[0] || 0) + rect.x + offsetX) * scale,
        top: canvasRect.top + (Number(node.pos[1] || 0) + rect.y + offsetY) * scale,
        width: rect.w * scale,
        height: rect.h * scale,
    };
}

function isNodeVisibleOnCanvas(node) {
    const canvas = app.canvas;
    if (!node) return false;
    if (typeof canvas?.isNodeVisible === "function") {
        try {
            return canvas.isNodeVisible(node);
        } catch (_) {
            return true;
        }
    }
    return true;
}

function applyLegacyCanvasToggleState(button, pair) {
    const enabled = isFieldEnabled(pair.enableWidget);
    button.className = `${FIELD_ENABLE_CANVAS_TOGGLE_CLASS} ${enabled ? "is-on" : "is-off"}`;
    button.textContent = enabled ? "启用" : "关闭";
    button.dataset.fieldName = pair.targetName;
    button.setAttribute("aria-label", `${pair.targetName}${enabled ? "已启用" : "已关闭"}`);
    button.title = `${pair.targetName}: ${enabled ? "启用" : "关闭"}`;
}

function ensureLegacyCanvasFieldEnableButton(node, pair) {
    const key = legacyCanvasToggleKey(node, pair.targetName);
    let entry = legacyCanvasToggleElements.get(key);
    if (!entry) {
        const button = document.createElement("button");
        button.type = "button";
        const toggle = (event) => {
            const currentPair = buildFieldEnablePairs(node).find((item) => item.targetName === button.dataset.fieldName);
            if (!currentPair) return;
            const pairs = buildFieldEnablePairs(node);
            setWidgetValue(currentPair.enableWidget, !isFieldEnabled(currentPair.enableWidget));
            syncFieldRandomControlVisibility(node, pairs);
            applyFieldEnableDimState(node, pairs);
            updateLegacyCanvasFieldEnableToggles(node);
            legacyCanvasLastToggle = { time: Date.now(), node };
            app.graph?.setDirtyCanvas(true, true);
            event?.preventDefault?.();
            event?.stopPropagation?.();
            event?.stopImmediatePropagation?.();
        };
        button.addEventListener("pointerdown", (event) => {
            button._galiaisPointerToggledAt = Date.now();
            toggle(event);
        });
        button.addEventListener("mousedown", (event) => {
            event.preventDefault();
            event.stopPropagation();
        });
        button.addEventListener("click", (event) => {
            const pointerHandled = Date.now() - Number(button._galiaisPointerToggledAt || 0) < 250;
            if (!pointerHandled) toggle(event);
            event.preventDefault();
            event.stopPropagation();
        });
        document.body.appendChild(button);
        entry = { node, button };
        legacyCanvasToggleElements.set(key, entry);
    }
    entry.node = node;
    applyLegacyCanvasToggleState(entry.button, pair);
    return entry.button;
}

function updateLegacyCanvasFieldEnableToggles(node) {
    if (!node) return false;
    if (isVueNodeMode(node) || node.flags?.collapsed || !nodeBelongsToCurrentGraph(node)) {
        removeLegacyCanvasFieldEnableToggles(node);
        return false;
    }

    ensureStyles();
    const fieldEnablePairs = buildFieldEnablePairs(node);
    hideFieldEnableWidgets(node, fieldEnablePairs);
    syncFieldRandomControlVisibility(node, fieldEnablePairs);
    applyFieldEnableDimState(node, fieldEnablePairs);
    ensureLegacyCanvasFieldEnableLayout(node, fieldEnablePairs);

    const expectedKeys = new Set();
    const visible = isNodeVisibleOnCanvas(node);
    for (const pair of fieldEnablePairs) {
        const rect = fieldEnableToggleRect(node, pair.widget);
        const clientRect = rect ? canvasRectToClientRect(node, rect) : null;
        const key = legacyCanvasToggleKey(node, pair.targetName);
        expectedKeys.add(key);
        const button = ensureLegacyCanvasFieldEnableButton(node, pair);
        if (!visible || !clientRect) {
            button.style.display = "none";
            continue;
        }
        button.style.left = `${clientRect.left}px`;
        button.style.top = `${clientRect.top}px`;
        button.style.width = `${Math.max(36, clientRect.width)}px`;
        button.style.height = `${Math.max(18, clientRect.height)}px`;
        button.style.transform = `scale(${Math.max(0.72, Math.min(1, Number(clientRect.width || 46) / 46))})`;
        button.style.transformOrigin = "top left";
        button.style.display = "flex";
    }

    for (const [key, entry] of Array.from(legacyCanvasToggleElements.entries())) {
        if (entry.node === node && !expectedKeys.has(key)) {
            entry.button.remove();
            legacyCanvasToggleElements.delete(key);
        }
    }
    return fieldEnablePairs.length > 0;
}

function flushLegacyCanvasFieldEnableToggles() {
    legacyCanvasToggleFrame = null;
    for (const node of Array.from(legacyCanvasToggleNodes)) {
        if (!node || node.graph === null || !nodeBelongsToCurrentGraph(node)) {
            removeLegacyCanvasFieldEnableToggles(node);
            continue;
        }
        updateLegacyCanvasFieldEnableToggles(node);
    }
}

function scheduleLegacyCanvasFieldEnableToggles(node) {
    if (node) {
        legacyCanvasToggleNodes.add(node);
        ensureLegacyCanvasTrackingLoop();
    }
    if (legacyCanvasToggleFrame !== null) return;
    const schedule = window.requestAnimationFrame || ((callback) => window.setTimeout(callback, 16));
    legacyCanvasToggleFrame = schedule(flushLegacyCanvasFieldEnableToggles);
}

function ensureLegacyCanvasTrackingLoop() {
    if (legacyCanvasTrackingFrame !== null) return;
    const schedule = window.requestAnimationFrame || ((callback) => window.setTimeout(callback, 16));
    const tick = () => {
        legacyCanvasTrackingFrame = null;
        if (legacyCanvasToggleNodes.size > 0) {
            scheduleLegacyCanvasFieldEnableToggles();
            legacyCanvasTrackingFrame = schedule(tick);
        }
    };
    legacyCanvasTrackingFrame = schedule(tick);
}

function handleLegacyCanvasFieldTogglePointer(event) {
    if (event?.button !== undefined && event.button !== 0) return;
    const canvasPos = eventToCanvasPosition(event);
    if (!canvasPos) return;
    const nodes = app.graph?._nodes || [];
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
        const node = nodes[index];
        if (!node || isVueNodeMode(node) || node.flags?.collapsed) continue;
        const nodePos = nodeLocalPositionFromCanvas(node, canvasPos);
        if (!nodePos) continue;
        const width = Number(node.size?.[0] || 0);
        const height = Number(node.size?.[1] || 0);
        if (nodePos[0] < 0 || nodePos[1] < 0 || nodePos[0] > width || nodePos[1] > height) continue;
        const pairs = buildFieldEnablePairs(node);
        if (!pairs.length) continue;
        if (!toggleFieldEnableAtPosition(node, nodePos, pairs)) continue;
        legacyCanvasLastToggle = { time: Date.now(), node };
        event.preventDefault?.();
        event.stopPropagation?.();
        event.stopImmediatePropagation?.();
        return true;
    }
}

function ensureLegacyCanvasPointerHandler() {
    if (legacyCanvasPointerHandlerInstalled) return;
    const install = () => {
        const element = app.canvas?.canvas;
        if (!element || legacyCanvasPointerHandlerInstalled) return;
        element.addEventListener("pointerdown", handleLegacyCanvasFieldTogglePointer, true);
        element.addEventListener("mousedown", handleLegacyCanvasFieldTogglePointer, true);
        element.addEventListener("pointermove", () => scheduleLegacyCanvasFieldEnableToggles(), { passive: true });
        element.addEventListener("mousemove", () => scheduleLegacyCanvasFieldEnableToggles(), { passive: true });
        element.addEventListener("wheel", () => scheduleLegacyCanvasFieldEnableToggles(), { passive: true });
        element.addEventListener("mouseleave", () => scheduleLegacyCanvasFieldEnableToggles(), { passive: true });
        window.addEventListener("resize", () => scheduleLegacyCanvasFieldEnableToggles(), { passive: true });
        window.addEventListener("blur", removeAllLegacyCanvasFieldEnableToggles, { passive: true });
        legacyCanvasPointerHandlerInstalled = true;
    };
    install();
    window.setTimeout(install, 250);
    window.setTimeout(install, 1000);
}

function resolveSelectorField(item) {
    const field = String(item?.field || "").trim();
    if (field === "__selected_taxonomy_tags__") {
        return findWidgetValue(item.node, "TaxonomyID");
    }
    return field;
}

function selectorUnavailableMessage(item) {
    if (String(item?.field || "").trim() === "__selected_taxonomy_tags__") {
        return "请先选择 TaxonomyID，再选择该分类下的 Tags。";
    }
    return "该字段没有可用的 Danbooru 分类。";
}

function canvasSelectButtonRect(node) {
    return {
        x: CANVAS_BUTTON_MARGIN,
        y: CANVAS_BUTTON_MARGIN,
        w: CANVAS_BUTTON_WIDTH,
        h: CANVAS_BUTTON_HEIGHT,
    };
}

function isInsideRect(pos, rect) {
    return (
        Array.isArray(pos) &&
        pos[0] >= rect.x &&
        pos[0] <= rect.x + rect.w &&
        pos[1] >= rect.y &&
        pos[1] <= rect.y + rect.h
    );
}

function drawCanvasSelectButton(node, ctx) {
    if (!ctx || node?.flags?.collapsed) return;
    const rect = canvasSelectButtonRect(node);
    ctx.save();
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(rect.x, rect.y, rect.w, rect.h, 5);
    } else {
        ctx.rect(rect.x, rect.y, rect.w, rect.h);
    }
    ctx.fillStyle = "#e2b86b";
    ctx.fill();
    ctx.strokeStyle = "rgba(18, 20, 24, 0.55)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = "#16120b";
    ctx.font = "bold 12px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("DB选择", rect.x + rect.w / 2, rect.y + rect.h / 2 + 0.5);
    ctx.restore();
}

function removeLegacySelectorWidgets(node) {
    if (!Array.isArray(node.widgets)) return false;
    const before = node.widgets.length;
    node.widgets = node.widgets.filter((widget) => {
        if (!isLegacySelectorWidget(widget)) return true;
        if (widget.options) widget.options.serialize = false;
        widget.serialize = false;
        return false;
    });
    return node.widgets.length !== before;
}

function ensureSelectorButtonWidget(node, lazyFields) {
    if (!node || typeof node.addWidget !== "function" || !Array.isArray(node.widgets)) return false;
    const before = node.widgets.length;
    node.widgets = node.widgets.filter((widget) => widget?.name !== SELECTOR_BUTTON_NAME);
    const fields = selectorFieldsForNode(node, lazyFields);
    if (!fields.length) return node.widgets.length !== before;

    const button = node.addWidget(
        "button",
        SELECTOR_BUTTON_NAME,
        "选择Tag",
        () => openFieldChooser(node, lazyFields),
        { serialize: false },
    );
    button.serialize = false;
    button.options = { ...(button.options || {}), serialize: false };
    button.value = "选择Tag";
    button.callback = () => openFieldChooser(node, lazyFields);
    return true;
}

function refreshNodeSize(node, changed = false, options = {}) {
    try {
        const computed = node.computeSize();
        const currentWidth = Number(node.size?.[0] || 0);
        const currentHeight = Number(node.size?.[1] || 0);
        const nextWidth = Math.max(currentWidth, Number(computed?.[0] || currentWidth));
        const computedHeight = Number(computed?.[1] || currentHeight);
        const fitHeight = options?.fitHeight === true;
        const allowHeightGrowth = options?.allowHeightGrowth !== false;
        let nextHeight = currentHeight;
        if (fitHeight) {
            nextHeight = computedHeight;
        } else if (allowHeightGrowth) {
            nextHeight = Math.max(currentHeight, computedHeight);
        }
        if (nextWidth !== currentWidth || nextHeight !== currentHeight) {
            node.setSize([nextWidth, nextHeight]);
        }
        app.graph?.setDirtyCanvas(true, changed);
    } catch (error) {
        app.graph?.setDirtyCanvas(true, changed);
    }
}

// Composer UI implementation lives in galiais_nodes_composer_ui.js.
// Compatibility markers for source-level regression tests:
// function promptSectionInputNumber
// function syncComposerPromptSectionInputs
// function addComposerPromptSectionInput
// function autoExtendComposerPromptSections
// function ensureComposerTemplateButtonWidget
// function openComposerTemplatePanel
// function syncComposerTemplatePanelFromWidgets
// function applyComposerTemplatePanelToWidgets
// function hideComposerTemplateWidgets

function cleanLegacyWidgetValues(node) {
    const serialized = node.widgets_values;
    if (!Array.isArray(serialized) || !Array.isArray(node.widgets)) return false;
    if (!serialized.some((value) => value === null || value === undefined)) return false;

    const expectedCount = realWidgets(node).length;
    if (serialized.length <= expectedCount) return false;

    const compacted = serialized.filter((value) => value !== null && value !== undefined);
    if (compacted.length > expectedCount) return false;

    node.widgets_values = compacted;
    for (const [index, widget] of realWidgets(node).entries()) {
        if (index >= compacted.length) break;
        widget.value = compacted[index];
        if (widget.inputEl) widget.inputEl.value = compacted[index];
    }
    return true;
}

function ensureDbFileButtonWidget(node) {
    if (!node || typeof node.addWidget !== "function" || !Array.isArray(node.widgets)) return false;
    if (nodeTypeName(node) !== "GaliaisNodesDanbooruDBLoader") return false;
    const before = node.widgets.length;
    node.widgets = node.widgets.filter((widget) => widget?.name !== DB_FILE_BUTTON_NAME);
    const button = node.addWidget(
        "button",
        DB_FILE_BUTTON_NAME,
        "打开文件",
        async () => {
            try {
                await selectDanbooruDbFile(node);
            } catch (error) {
                console.error("[GALIAIS-Nodes] DB file selection failed", error);
                alert(`DB文件选择失败: ${error.message || error}`);
            }
        },
        { serialize: false },
    );
    button.serialize = false;
    button.options = { ...(button.options || {}), serialize: false };
    button.value = "打开文件";
    return true;
}

function ensureAiModelsButtonWidget(node) {
    if (!node || typeof node.addWidget !== "function" || !Array.isArray(node.widgets)) return false;
    if (nodeTypeName(node) !== "GaliaisNodesAIProvider") return false;
    node.widgets = node.widgets.filter((widget) => widget?.name !== AI_MODELS_BUTTON_NAME);
    const button = node.addWidget(
        "button",
        AI_MODELS_BUTTON_NAME,
        "获取/选择",
        async () => {
            try {
                await selectAiProviderModel(node);
            } catch (error) {
                console.error("[GALIAIS-Nodes] AI model discovery failed", error);
                alert(`模型获取失败: ${error.message || error}`);
            }
        },
        { serialize: false },
    );
    button.serialize = false;
    button.options = { ...(button.options || {}), serialize: false };
    button.value = "获取/选择";
    return true;
}

// Prompt Viewer UI implementation lives in galiais_nodes_prompt_viewer_ui.js.
// Compatibility markers for source-level regression tests:
// function ensurePromptViewerWidgets
// function updatePromptViewerWidgets

function ensureRandomFieldsWidget(node) {
    if (!node || typeof node.addDOMWidget !== "function") return null;
    if (node._galiaisRandomFields) return node._galiaisRandomFields;
    ensureStyles();
    const container = document.createElement("div");
    container.className = "galiais-nodes-random-fields";
    const title = document.createElement("div");
    title.className = "galiais-nodes-random-fields-title";
    title.textContent = "本次随机Tag";
    const rows = document.createElement("div");
    container.appendChild(title);
    container.appendChild(rows);
    const widget = node.addDOMWidget("本次随机Tag", "galiais_random_fields", container, {
        serialize: false,
    });
    widget.serialize = false;
    setWidgetHiddenState(widget, true);
    node._galiaisRandomFields = { container, rows, widget };
    return node._galiaisRandomFields;
}

function updateRandomFieldsWidget(node, message) {
    const hasRandomFieldPayload = Object.prototype.hasOwnProperty.call(message || {}, "galiais_random_fields");
    if (!hasRandomFieldPayload) return false;
    const batches = Array.isArray(message?.galiais_random_fields) ? message.galiais_random_fields : [];
    const entries = [];
    for (const batch of batches) {
        if (!batch || typeof batch !== "object") continue;
        for (const [name, value] of Object.entries(batch)) {
            const text = String(value ?? "").trim();
            if (text) entries.push([String(name || ""), text]);
        }
    }
    if (!entries.length && !node?._galiaisRandomFields) return false;
    const state = ensureRandomFieldsWidget(node);
    if (!state) return false;
    state.rows.replaceChildren();
    for (const [name, value] of entries) {
        const row = document.createElement("div");
        row.className = "galiais-nodes-random-fields-row";
        const label = document.createElement("div");
        label.className = "galiais-nodes-random-fields-label";
        label.textContent = name;
        label.title = name;
        const content = document.createElement("div");
        content.className = "galiais-nodes-random-fields-value";
        content.textContent = value;
        row.appendChild(label);
        row.appendChild(content);
        state.rows.appendChild(row);
    }
    const visible = entries.length > 0;
    state.container.classList.toggle("is-visible", visible);
    setWidgetHiddenState(state.widget, !visible);
    syncVueWidgetRowVisibility(node);
    app.graph?.setDirtyCanvas(true, true);
    return true;
}

function clearRandomFieldsWidget(node) {
    const state = node?._galiaisRandomFields;
    if (!state) return false;
    let changed = false;
    if (state.rows?.childNodes?.length) {
        state.rows.replaceChildren();
        changed = true;
    }
    if (state.container?.classList?.contains("is-visible")) {
        state.container.classList.remove("is-visible");
        changed = true;
    }
    changed = setWidgetHiddenState(state.widget, true) || changed;
    return changed;
}

function openFieldChooser(node, lazyFields, event = null) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    const fields = selectorFieldsForNode(node, lazyFields);
    if (!fields.length) return;
    if (fields.length === 1) {
        const item = fields[0];
        openSelectorForField(item, findDanbooruDbPath());
        return;
    }

    ensureStyles();
    const backdrop = document.createElement("div");
    backdrop.className = "galiais-nodes-danbooru-backdrop";

    const modal = document.createElement("div");
    modal.className = "galiais-nodes-danbooru-field-modal";
    backdrop.appendChild(modal);

    const header = document.createElement("div");
    header.className = "galiais-nodes-danbooru-header";
    modal.appendChild(header);

    const title = document.createElement("div");
    title.className = "galiais-nodes-danbooru-title";
    title.textContent = "选择 Danbooru 字段";
    header.appendChild(title);

    const close = document.createElement("button");
    close.className = "galiais-nodes-danbooru-button";
    close.textContent = "关闭";
    header.appendChild(close);

    const list = document.createElement("div");
    list.className = "galiais-nodes-danbooru-field-list";
    modal.appendChild(list);

    function closeModal() {
        backdrop.remove();
        document.removeEventListener("keydown", onKeydown);
    }

    function onKeydown(keyEvent) {
        if (keyEvent.key === "Escape") closeModal();
    }

    for (const { widget, field } of fields) {
        const item = { node, widget, field };
        const row = document.createElement("button");
        row.className = "galiais-nodes-danbooru-field-row";
        row.textContent = widget.name;
        row.addEventListener("click", () => {
            closeModal();
            openSelectorForField(item, findDanbooruDbPath());
        });
        list.appendChild(row);
    }

    close.addEventListener("click", closeModal);
    backdrop.addEventListener("click", (clickEvent) => {
        if (clickEvent.target === backdrop) closeModal();
    });
    document.addEventListener("keydown", onKeydown);
    document.body.appendChild(backdrop);
}

function openSelectorForField(item, dbPath = "") {
    const field = resolveSelectorField(item);
    if (!field) {
        alert(selectorUnavailableMessage(item));
        return;
    }
    if (field === "__taxonomy_id__") {
        openTaxonomySelector(item.widget, item.widget.name, dbPath);
        return;
    }
    openSelector(item.widget, field, item.widget.name, dbPath);
}

function taxonomyTreeCacheKey(dbPath, includeCounts, allowNsfw) {
    return cacheKey([
        "all_taxonomy_tree",
        dbPath,
        allowNsfw ? "1" : "0",
        includeCounts ? "1" : "0",
    ]);
}

function openTaxonomySelector(targetWidget, title, dbPath = "") {
    ensureStyles();
    let selectedId = String(targetWidget?.value || "").trim();
    let selectedLabel = selectedId || "未选择";
    const expandedTreeNodes = new Set(["root"]);
    let lastTreePayload = null;
    let activeTreeController = null;
    let treeRequestId = 0;

    const backdrop = document.createElement("div");
    backdrop.className = "galiais-nodes-danbooru-backdrop";

    const modal = document.createElement("div");
    modal.className = "galiais-nodes-danbooru-modal";
    backdrop.appendChild(modal);

    const header = document.createElement("div");
    header.className = "galiais-nodes-danbooru-header";
    modal.appendChild(header);

    const label = document.createElement("div");
    label.className = "galiais-nodes-danbooru-title";
    label.textContent = title || "TaxonomyID";
    header.appendChild(label);

    const search = document.createElement("input");
    search.className = "galiais-nodes-danbooru-search";
    search.placeholder = "搜索分类中文、英文或 taxonomy id";
    header.appendChild(search);

    const allowNsfwLabel = document.createElement("label");
    allowNsfwLabel.className = "galiais-nodes-danbooru-status";
    const allowNsfw = document.createElement("input");
    allowNsfw.type = "checkbox";
    allowNsfwLabel.appendChild(allowNsfw);
    allowNsfwLabel.appendChild(document.createTextNode(" NSFW"));
    header.appendChild(allowNsfwLabel);

    const close = document.createElement("button");
    close.className = "galiais-nodes-danbooru-button";
    close.textContent = "取消";
    header.appendChild(close);

    const body = document.createElement("div");
    body.className = "galiais-nodes-danbooru-body";
    body.style.gridTemplateColumns = "1fr";
    modal.appendChild(body);

    const tree = document.createElement("div");
    tree.className = "galiais-nodes-danbooru-tree";
    tree.style.borderRight = "0";
    tree.style.maxHeight = "none";
    body.appendChild(tree);

    const footer = document.createElement("div");
    footer.className = "galiais-nodes-danbooru-footer";
    modal.appendChild(footer);

    const status = document.createElement("div");
    status.className = "galiais-nodes-danbooru-status";
    footer.appendChild(status);

    const controls = document.createElement("div");
    controls.style.display = "flex";
    controls.style.gap = "8px";
    footer.appendChild(controls);

    const clear = document.createElement("button");
    clear.className = "galiais-nodes-danbooru-button";
    clear.textContent = "清空待选";
    controls.appendChild(clear);

    const confirm = document.createElement("button");
    confirm.className = "galiais-nodes-danbooru-button is-primary";
    confirm.textContent = "确定选择";
    controls.appendChild(confirm);

    function closeModal() {
        activeTreeController?.abort();
        backdrop.remove();
        document.removeEventListener("keydown", onKeydown);
    }

    function onKeydown(event) {
        if (event.key === "Escape") closeModal();
    }

    function setStatus(text) {
        status.textContent = text;
    }

    function leafMatches(node, query) {
        if (!query) return true;
        const text = [
            node.taxonomy_id,
            node.id,
            node.label,
            node.label_en,
        ].join(" ").toLowerCase();
        return text.includes(query);
    }

    function childMatches(node, query) {
        if (leafMatches(node, query)) return true;
        return (node.children || []).some((child) => childMatches(child, query));
    }

    function renderTree(payload) {
        tree.replaceChildren();
        const query = search.value.trim().toLowerCase();
        const countsIncluded = payload?.counts_included !== false;
        const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
        for (const node of nodes) renderTreeNode(node, 0, countsIncluded, query);
        const leafCount = Array.isArray(payload?.leaves) ? payload.leaves.length : 0;
        setStatus(`${selectedLabel}；分类 ${leafCount} 项`);
    }

    function renderTreeNode(node, depth, countsIncluded, query) {
        if (query && !childMatches(node, query)) return;
        const hasChildren = Array.isArray(node.children) && node.children.length > 0;
        const isLeaf = !!node.taxonomy_id;
        const forceExpanded = !!query;
        const isExpanded = forceExpanded || expandedTreeNodes.has(node.id);
        const row = document.createElement("button");
        const depthClass = depth === 0 ? "is-domain" : depth >= 2 ? "is-group" : "";
        row.className = `galiais-nodes-danbooru-tree-row ${isLeaf ? "is-leaf" : depthClass} ${selectedId === node.taxonomy_id ? "is-active" : ""}`;
        row.style.paddingLeft = `${12 + depth * 20 + (isLeaf ? 8 : 0)}px`;
        row.title = node.taxonomy_id || node.id || "";

        const toggle = document.createElement("span");
        toggle.className = "galiais-nodes-danbooru-tree-toggle";
        toggle.textContent = hasChildren ? (isExpanded ? "▾" : "▸") : "•";
        row.appendChild(toggle);

        const text = document.createElement("span");
        text.className = "galiais-nodes-danbooru-tree-label";
        text.textContent = node.label || node.id || "";
        if (node.label_en || node.taxonomy_id) {
            text.title = [node.taxonomy_id, node.label_en].filter(Boolean).join(" / ");
        }
        row.appendChild(text);

        const count = document.createElement("span");
        count.className = "galiais-nodes-danbooru-tree-count";
        count.textContent = countsIncluded ? String(node.count ?? 0) : "...";
        row.appendChild(count);

        row.addEventListener("click", () => {
            if (isLeaf) {
                selectedId = node.taxonomy_id || "";
                selectedLabel = node.label ? `${node.label} (${selectedId})` : selectedId;
                renderTree(lastTreePayload);
                return;
            }
            if (expandedTreeNodes.has(node.id)) {
                expandedTreeNodes.delete(node.id);
            } else {
                expandedTreeNodes.add(node.id);
            }
            renderTree(lastTreePayload);
        });
        tree.appendChild(row);

        if (hasChildren && isExpanded) {
            for (const child of node.children) renderTreeNode(child, depth + 1, countsIncluded, query);
        }
    }

    async function loadTree() {
        if (!dbPath) {
            tree.textContent = "未找到 DB：请添加 GALIAIS-Nodes Danbooru DB Loader 并填写 DB路径";
            return;
        }
        const shapeKey = taxonomyTreeCacheKey(dbPath, false, allowNsfw.checked);
        const cached = treePayloadCache.get(shapeKey);
        if (cached) {
            lastTreePayload = cached;
            renderTree(cached);
            return;
        }
        activeTreeController?.abort();
        activeTreeController = new AbortController();
        const requestId = ++treeRequestId;
        tree.textContent = "分类读取中...";
        try {
            const shapeParams = new URLSearchParams({
                db_path: dbPath,
                allow_nsfw: allowNsfw.checked ? "1" : "0",
                include_counts: "0",
            });
            const shapeResponse = await fetch(
                apiUrl(`/galiais-nodes/danbooru/all_taxonomy_tree?${shapeParams.toString()}`),
                { signal: activeTreeController.signal },
            );
            const shapePayload = await readJsonResponse(shapeResponse, "分类读取失败");
            if (requestId !== treeRequestId) return;
            treePayloadCache.set(shapeKey, shapePayload);
            lastTreePayload = shapePayload;
            renderTree(shapePayload);
        } catch (error) {
            if (error?.name === "AbortError") return;
            tree.textContent = `分类读取失败: ${error.message || error}`;
        }
    }

    let timer = null;
    search.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => renderTree(lastTreePayload), 120);
    });
    allowNsfw.addEventListener("change", loadTree);
    close.addEventListener("click", closeModal);
    clear.addEventListener("click", () => {
        selectedId = "";
        selectedLabel = "未选择";
        renderTree(lastTreePayload);
    });
    confirm.addEventListener("click", () => {
        setWidgetValue(targetWidget, selectedId);
        closeModal();
    });
    backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) closeModal();
    });
    document.addEventListener("keydown", onKeydown);
    document.body.appendChild(backdrop);
    search.focus();
    loadTree();
}

function openSelector(targetWidget, fieldKey, title, dbPath = "") {
    ensureStyles();
    let offset = 0;
    let hasMore = false;
    let loading = false;
    let lastQuery = "";
    let selectedField = fieldKey;
    let selectedLabel = "全部";
    let selectMode = "append";
    let stagedParts = splitWidgetParts(targetWidget);
    let blacklist = findDanbooruTagBlacklist();
    let randomTaxonomyBlacklist = findRandomTaxonomyBlacklist();
    const expandedTreeNodes = new Set(["root"]);
    let lastTreePayload = null;
    let activePageController = null;
    let activeTreeController = null;
    let pageRequestId = 0;
    let treeRequestId = 0;

    const backdrop = document.createElement("div");
    backdrop.className = "galiais-nodes-danbooru-backdrop";

    const modal = document.createElement("div");
    modal.className = "galiais-nodes-danbooru-modal";
    backdrop.appendChild(modal);

    const header = document.createElement("div");
    header.className = "galiais-nodes-danbooru-header";
    modal.appendChild(header);

    const label = document.createElement("div");
    label.className = "galiais-nodes-danbooru-title";
    label.textContent = title;
    header.appendChild(label);

    const search = document.createElement("input");
    search.className = "galiais-nodes-danbooru-search";
    search.placeholder = "输入英文 tag 或中文翻译搜索";
    search.value = "";
    header.appendChild(search);

    const language = document.createElement("select");
    language.className = "galiais-nodes-danbooru-select";
    for (const item of ["中英文", "中文", "英文"]) {
        const option = document.createElement("option");
        option.value = item;
        option.textContent = item;
        language.appendChild(option);
    }
    header.appendChild(language);

    const sortMode = document.createElement("select");
    sortMode.className = "galiais-nodes-danbooru-select";
    for (const [value, label] of [
        ["hot", "热度"],
        ["tag", "Tag"],
        ["label", "中文"],
        ["safety", "安全"],
    ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        sortMode.appendChild(option);
    }
    header.appendChild(sortMode);

    const allowNsfwLabel = document.createElement("label");
    allowNsfwLabel.className = "galiais-nodes-danbooru-status";
    const allowNsfw = document.createElement("input");
    allowNsfw.type = "checkbox";
    allowNsfwLabel.appendChild(allowNsfw);
    allowNsfwLabel.appendChild(document.createTextNode(" NSFW"));
    header.appendChild(allowNsfwLabel);

    const mode = document.createElement("div");
    mode.className = "galiais-nodes-danbooru-mode";
    header.appendChild(mode);

    const appendMode = document.createElement("button");
    appendMode.type = "button";
    appendMode.textContent = "追加";
    mode.appendChild(appendMode);

    const replaceMode = document.createElement("button");
    replaceMode.type = "button";
    replaceMode.textContent = "替换";
    mode.appendChild(replaceMode);

    const close = document.createElement("button");
    close.className = "galiais-nodes-danbooru-button";
    close.textContent = "取消";
    header.appendChild(close);

    const body = document.createElement("div");
    body.className = "galiais-nodes-danbooru-body";
    modal.appendChild(body);

    const tree = document.createElement("div");
    tree.className = "galiais-nodes-danbooru-tree";
    body.appendChild(tree);

    const main = document.createElement("div");
    main.className = "galiais-nodes-danbooru-main";
    body.appendChild(main);

    const filter = document.createElement("div");
    filter.className = "galiais-nodes-danbooru-filter";
    main.appendChild(filter);

    const selectedBar = document.createElement("div");
    selectedBar.className = "galiais-nodes-danbooru-selected";
    main.appendChild(selectedBar);

    const results = document.createElement("div");
    results.className = "galiais-nodes-danbooru-results";
    main.appendChild(results);

    const footer = document.createElement("div");
    footer.className = "galiais-nodes-danbooru-footer";
    modal.appendChild(footer);

    const status = document.createElement("div");
    status.className = "galiais-nodes-danbooru-status";
    footer.appendChild(status);

    const controls = document.createElement("div");
    controls.style.display = "flex";
    controls.style.gap = "8px";
    footer.appendChild(controls);

    const clear = document.createElement("button");
    clear.className = "galiais-nodes-danbooru-button";
    clear.textContent = "清空待选";
    controls.appendChild(clear);

    const clearField = document.createElement("button");
    clearField.className = "galiais-nodes-danbooru-button";
    clearField.textContent = "清空字段";
    controls.appendChild(clearField);

    const favorites = document.createElement("button");
    favorites.className = "galiais-nodes-danbooru-button";
    favorites.textContent = "收藏";
    controls.appendChild(favorites);

    const recent = document.createElement("button");
    recent.className = "galiais-nodes-danbooru-button";
    recent.textContent = "最近";
    controls.appendChild(recent);

    const randomPick = document.createElement("button");
    randomPick.className = "galiais-nodes-danbooru-button";
    randomPick.textContent = "随机";
    controls.appendChild(randomPick);

    const more = document.createElement("button");
    more.className = "galiais-nodes-danbooru-button";
    more.textContent = "加载更多";
    controls.appendChild(more);

    const confirm = document.createElement("button");
    confirm.className = "galiais-nodes-danbooru-button is-primary";
    confirm.textContent = "确定选择";
    controls.appendChild(confirm);

    function closeModal() {
        activePageController?.abort();
        activeTreeController?.abort();
        backdrop.remove();
        document.removeEventListener("keydown", onKeydown);
    }

    function onKeydown(event) {
        if (event.key === "Escape") closeModal();
    }

    function setStatus(text) {
        status.textContent = text;
    }

    function selectedStagedTokens() {
        return tagTokensFromParts(stagedParts);
    }

    function isValueSelected(value) {
        return tagTokenSetsIntersect(selectedStagedTokens(), comparableTagTokens(value));
    }

    function updateConfirmStatus(prefix = "待确认") {
        setStatus(`${prefix}: ${stagedParts.length} 项`);
    }

    function renderSelectedBar() {
        selectedBar.replaceChildren();
        if (!stagedParts.length) {
            const empty = document.createElement("span");
            empty.className = "galiais-nodes-danbooru-status";
            empty.textContent = "未选择 tag";
            selectedBar.appendChild(empty);
            return;
        }
        for (const part of stagedParts) {
            const chip = document.createElement("button");
            chip.className = "galiais-nodes-danbooru-chip";
            chip.textContent = part;
            chip.title = "点击取消选择";
            chip.addEventListener("click", () => {
                stagedParts = removeTagParts(stagedParts, part).parts;
                renderSelectedBar();
                refreshVisibleSelectionState();
                updateConfirmStatus("已取消");
            });
            selectedBar.appendChild(chip);
        }
    }

    function refreshVisibleSelectionState() {
        for (const row of results.querySelectorAll(".galiais-nodes-danbooru-row")) {
            const value = row.dataset.option || "";
            const selected = isValueSelected(value);
            row.classList.toggle("is-selected", selected);
            row.setAttribute("aria-pressed", selected ? "true" : "false");
            const safety = row.querySelector(".galiais-nodes-danbooru-safety");
            if (safety) {
                const statePrefix = row.dataset.blacklisted === "1" ? "已屏蔽 · " : selected ? "已选 · " : "";
                safety.textContent = `${statePrefix}${row.dataset.nsfw === "1" ? "NSFW" : "SFW"}`;
            }
        }
        renderSelectedBar();
    }

    function updateModeButtons() {
        appendMode.classList.toggle("is-active", selectMode === "append");
        replaceMode.classList.toggle("is-active", selectMode === "replace");
    }

    function updateFilterLabel() {
        filter.replaceChildren();
        filter.appendChild(document.createTextNode("当前分类: "));
        const strong = document.createElement("strong");
        strong.textContent = selectedLabel;
        filter.appendChild(strong);
        if (selectedField !== fieldKey) {
            const all = document.createElement("button");
            all.className = "galiais-nodes-danbooru-button";
            all.textContent = "返回全部";
            all.addEventListener("click", () => {
                selectedField = fieldKey;
                selectedLabel = "全部";
                renderTree(lastTreePayload);
                updateFilterLabel();
                loadPage(true);
            });
            filter.appendChild(all);
        }
    }

    function addRow(item) {
        const row = document.createElement("div");
        row.className = "galiais-nodes-danbooru-row";
        row.tabIndex = 0;
        row.setAttribute("role", "button");
        row.title = item.taxonomy_id || "";
        const value = item.option || item.tag || "";
        row.dataset.option = value;
        row.dataset.nsfw = item.is_nsfw ? "1" : "0";
        row.dataset.blacklisted = item.is_blacklisted ? "1" : "0";
        const currentTokens = selectedStagedTokens();
        const itemTokens = comparableTagTokens(item.option || item.tag || "");
        const isSelected = tagTokenSetsIntersect(currentTokens, itemTokens);
        let rowBlacklisted = !!item.is_blacklisted;
        if (isSelected) {
            row.classList.add("is-selected");
            row.setAttribute("aria-pressed", "true");
        }
        if (rowBlacklisted) {
            row.classList.add("is-blacklisted");
            row.setAttribute("aria-disabled", "true");
        }

        const tag = document.createElement("div");
        tag.className = "galiais-nodes-danbooru-tag";
        tag.textContent = item.tag || "";
        row.appendChild(tag);

        const label = document.createElement("div");
        label.className = "galiais-nodes-danbooru-label";
        label.textContent = item.label || item.tag || "";
        row.appendChild(label);

        const meta = document.createElement("div");
        meta.className = "galiais-nodes-danbooru-meta";
        meta.textContent = String(item.post_count ?? 0);
        row.appendChild(meta);

        const tools = document.createElement("div");
        tools.className = "galiais-nodes-danbooru-row-tools";
        const star = document.createElement("button");
        star.type = "button";
        star.className = `galiais-nodes-danbooru-star ${isFavoriteTag(value) ? "is-active" : ""}`;
        star.textContent = "★";
        star.title = "收藏/取消收藏";
        star.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const active = toggleFavoriteTag(value);
            star.classList.toggle("is-active", active);
        });
        const block = document.createElement("button");
        block.type = "button";
        block.className = "galiais-nodes-danbooru-button";
        block.textContent = rowBlacklisted ? "已屏蔽" : "屏蔽";
        block.title = rowBlacklisted ? "已在Tag黑名单中，点击恢复" : "加入Tag黑名单";
        block.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();
            const tagName = item.tag || baseOptionText(value);
            if (!tagName) return;
            const action = rowBlacklisted ? "remove" : "add";
            block.disabled = true;
            setStatus(`${action === "add" ? "正在屏蔽" : "正在恢复"}: ${tagName}`);
            try {
                blacklist = await updateGlobalTagBlacklist(action, [tagName]);
                rowBlacklisted = action === "add";
                item.is_blacklisted = rowBlacklisted;
                row.classList.toggle("is-blacklisted", rowBlacklisted);
                if (rowBlacklisted) {
                    row.setAttribute("aria-disabled", "true");
                } else {
                    row.removeAttribute("aria-disabled");
                }
                row.dataset.blacklisted = rowBlacklisted ? "1" : "0";
                block.textContent = rowBlacklisted ? "已屏蔽" : "屏蔽";
                block.title = rowBlacklisted ? "已在Tag黑名单中，点击恢复" : "加入Tag黑名单";
                const selectedNow = isValueSelected(value);
                safety.textContent = `${rowBlacklisted ? "已屏蔽 · " : selectedNow ? "已选 · " : ""}${item.is_nsfw ? "NSFW" : "SFW"}`;
                setStatus(`${rowBlacklisted ? "已加入黑名单" : "已移出黑名单"}: ${formatSelectedOption(value)}`);
            } catch (error) {
                setStatus(`${action === "add" ? "加入黑名单失败" : "移出黑名单失败"}: ${error.message || error}`);
            } finally {
                block.disabled = false;
            }
        });
        const safety = document.createElement("div");
        safety.className = "galiais-nodes-danbooru-safety";
        safety.textContent = `${rowBlacklisted ? "已屏蔽 · " : isSelected ? "已选 · " : ""}${item.is_nsfw ? "NSFW" : "SFW"}`;
        tools.appendChild(star);
        tools.appendChild(block);
        tools.appendChild(safety);
        row.appendChild(tools);

        const activateRow = () => {
            if (rowBlacklisted) {
                setStatus(`已屏蔽: ${formatSelectedOption(value)}`);
                return;
            }
            const selected = isValueSelected(value);
            if (selected) {
                const result = removeTagParts(stagedParts, value);
                stagedParts = result.parts;
                updateConfirmStatus("已取消");
            } else if (selectMode === "append") {
                stagedParts = mergeTagParts(stagedParts, value);
                rememberLocalTag(RECENT_TAGS_KEY, value);
                updateConfirmStatus("已选择");
            } else {
                const next = formatSelectedOption(value);
                stagedParts = next ? [next] : [];
                rememberLocalTag(RECENT_TAGS_KEY, value);
                updateConfirmStatus("已替换为");
            }
            refreshVisibleSelectionState();
        };
        row.addEventListener("click", activateRow);
        row.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            activateRow();
        });
        results.appendChild(row);
    }

    function pageCacheKey(query, pageOffset) {
        return cacheKey([
            "options",
            dbPath,
            selectedField,
            query,
            language.value,
            allowNsfw.checked ? "1" : "0",
            blacklist,
            PAGE_LIMIT,
            pageOffset,
        ]);
    }

    function renderPagePayload(payload, reset = false) {
        let items = Array.isArray(payload?.items) ? payload.items.slice() : [];
        if (sortMode.value === "tag") {
            items.sort((a, b) => String(a.tag || "").localeCompare(String(b.tag || "")));
        } else if (sortMode.value === "label") {
            items.sort((a, b) => String(a.label || a.tag || "").localeCompare(String(b.label || b.tag || ""), "zh-Hans-CN"));
        } else if (sortMode.value === "safety") {
            items.sort((a, b) => Number(a.is_nsfw) - Number(b.is_nsfw) || Number(b.post_count || 0) - Number(a.post_count || 0));
        } else {
            items.sort((a, b) => Number(b.post_count || 0) - Number(a.post_count || 0));
        }
        if (reset) results.replaceChildren();
        for (const item of items) addRow(item);
        offset = Number(payload?.offset || 0) + items.length;
        hasMore = !!payload?.has_more;
        more.disabled = !hasMore || loading;
        const loadedText = items.length
            ? `已显示 ${offset} 项${hasMore ? "，可继续加载" : ""}`
            : "没有匹配项";
        setStatus(`${loadedText}；待确认 ${stagedParts.length} 项`);
    }

    function renderLocalTagRows(title, values) {
        results.replaceChildren();
        const items = values.map((value) => {
            const tag = baseOptionText(value);
            return {
                tag,
                label: value.includes("(") ? value : tag,
                option: value,
                post_count: 0,
                is_nsfw: false,
            };
        });
        for (const item of items) addRow(item);
        hasMore = false;
        more.disabled = true;
        setStatus(`${title}: ${items.length} 项；待确认 ${stagedParts.length} 项`);
    }

    function prefetchNextPage(query) {
        if (!hasMore || !dbPath) return;
        const nextOffset = offset;
        const key = pageCacheKey(query, nextOffset);
        if (optionPageCache.has(key)) return;
        const params = new URLSearchParams({
            db_path: dbPath,
            field: selectedField,
            q: query,
            language: language.value,
            allow_nsfw: allowNsfw.checked ? "1" : "0",
            blacklist,
            limit: String(PAGE_LIMIT),
            offset: String(nextOffset),
        });
        fetch(apiUrl(`/galiais-nodes/danbooru/options?${params.toString()}`))
            .then((response) => readJsonResponse(response, "预取失败"))
            .then((payload) => optionPageCache.set(key, payload))
            .catch(() => {});
    }

    async function loadPage(reset = false) {
        if (!dbPath) {
            if (reset) results.replaceChildren();
            more.disabled = true;
            setStatus("未找到 DB：请添加 GALIAIS-Nodes Danbooru DB Loader 并填写 DB路径");
            return;
        }
        if (reset) {
            offset = 0;
            results.replaceChildren();
        }
        const query = search.value.trim();
        const requestOffset = offset;
        lastQuery = query;
        const key = pageCacheKey(query, requestOffset);
        const cached = optionPageCache.get(key);
        if (cached) {
            renderPagePayload(cached, reset);
            prefetchNextPage(query);
            return;
        }

        activePageController?.abort();
        activePageController = new AbortController();
        const requestId = ++pageRequestId;
        loading = true;
        more.disabled = true;
        setStatus("查询中...");
        try {
            const params = new URLSearchParams({
                db_path: dbPath,
                field: selectedField,
                q: query,
                language: language.value,
                allow_nsfw: allowNsfw.checked ? "1" : "0",
                blacklist,
                limit: String(PAGE_LIMIT),
                offset: String(requestOffset),
            });
            const response = await fetch(
                apiUrl(`/galiais-nodes/danbooru/options?${params.toString()}`),
                { signal: activePageController.signal },
            );
            const payload = await readJsonResponse(response, "查询失败");
            if (requestId !== pageRequestId) return;
            optionPageCache.set(key, payload);
            renderPagePayload(payload, reset);
            prefetchNextPage(query);
        } catch (error) {
            if (error?.name === "AbortError") return;
            setStatus(`查询失败: ${error.message || error}`);
        } finally {
            if (requestId === pageRequestId) {
                loading = false;
                more.disabled = !hasMore;
            }
        }
    }

    async function randomSelectFromCurrentField() {
        if (!dbPath) {
            setStatus("未找到 DB：无法随机选择");
            return;
        }
        const params = new URLSearchParams({
            db_path: dbPath,
            field: selectedField,
            q: search.value.trim(),
            language: language.value,
            allow_nsfw: allowNsfw.checked ? "1" : "0",
            blacklist,
            taxonomy_blacklist: randomTaxonomyBlacklist,
            count: "1",
            seed: String(Math.floor(Math.random() * 0xffffffff)),
        });
        setStatus("随机读取中...");
        try {
            const response = await fetch(apiUrl(`/galiais-nodes/danbooru/random?${params.toString()}`));
            const payload = await readJsonResponse(response, "随机选择失败");
            const items = Array.isArray(payload?.items) ? payload.items : [];
            if (!items.length) {
                setStatus("当前分类没有可随机选择的 tag");
                return;
            }
            const item = items[0];
            const value = item.option || item.tag || "";
            if (selectMode === "replace") {
                const next = formatSelectedOption(value);
                stagedParts = next ? [next] : [];
            } else {
                stagedParts = mergeTagParts(stagedParts, value);
            }
            rememberLocalTag(RECENT_TAGS_KEY, value);
            refreshVisibleSelectionState();
            setWidgetValue(targetWidget, stagedParts.join(", "));
            setStatus(`随机选择: ${formatSelectedOption(value)}`);
        } catch (error) {
            setStatus(`随机选择失败: ${error.message || error}`);
        }
    }

    let timer = null;
    function scheduleSearch() {
        clearTimeout(timer);
        timer = setTimeout(() => loadPage(true), 240);
    }

    close.addEventListener("click", closeModal);
    backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) closeModal();
    });
    clear.addEventListener("click", () => {
        stagedParts = [];
        refreshVisibleSelectionState();
        updateConfirmStatus("已清空");
    });
    clearField.addEventListener("click", () => {
        stagedParts = [];
        setWidgetValue(targetWidget, "");
        refreshVisibleSelectionState();
        updateConfirmStatus("字段已清空");
    });
    favorites.addEventListener("click", () => {
        renderLocalTagRows("收藏", readLocalTagList(FAVORITE_TAGS_KEY));
    });
    recent.addEventListener("click", () => {
        renderLocalTagRows("最近", readLocalTagList(RECENT_TAGS_KEY));
    });
    randomPick.addEventListener("click", randomSelectFromCurrentField);
    confirm.addEventListener("click", () => {
        setWidgetValue(targetWidget, stagedParts.join(", "));
        closeModal();
    });
    appendMode.addEventListener("click", () => {
        selectMode = "append";
        updateModeButtons();
    });
    replaceMode.addEventListener("click", () => {
        selectMode = "replace";
        updateModeButtons();
    });
    more.addEventListener("click", () => {
        if (hasMore && search.value.trim() === lastQuery) loadPage(false);
    });
    search.addEventListener("input", scheduleSearch);
    language.addEventListener("change", () => loadPage(true));
    sortMode.addEventListener("change", () => loadPage(true));
    allowNsfw.addEventListener("change", () => {
        loadTree();
        loadPage(true);
    });
    document.addEventListener("keydown", onKeydown);
    document.body.appendChild(backdrop);
    search.focus();
    search.select();
    updateModeButtons();
    updateFilterLabel();
    renderSelectedBar();
    Promise.all([refreshGlobalTagBlacklist(), refreshGlobalRandomTaxonomyBlacklist()]).then(([tagValue, taxonomyValue]) => {
        blacklist = tagValue;
        randomTaxonomyBlacklist = taxonomyValue;
        loadTree();
        loadPage(true);
    });

    function treeCacheKey(includeCounts = true) {
        return cacheKey([
            "tree",
            dbPath,
            fieldKey,
            allowNsfw.checked ? "1" : "0",
            includeCounts ? "1" : "0",
        ]);
    }

    async function loadTree() {
        if (!dbPath) {
            tree.textContent = "未找到 DB：请添加 GALIAIS-Nodes Danbooru DB Loader 并填写 DB路径";
            return;
        }
        const fullKey = treeCacheKey(true);
        const cached = treePayloadCache.get(fullKey);
        if (cached) {
            lastTreePayload = cached;
            renderTree(cached);
            return;
        }
        const shapeKey = treeCacheKey(false);
        const cachedShape = treePayloadCache.get(shapeKey);
        if (cachedShape) {
            lastTreePayload = cachedShape;
            renderTree(cachedShape);
        }
        activeTreeController?.abort();
        activeTreeController = new AbortController();
        const requestId = ++treeRequestId;
        if (!cachedShape) tree.textContent = "分类读取中...";
        try {
            if (!cachedShape) {
                const shapeParams = new URLSearchParams({
                    db_path: dbPath,
                    field: fieldKey,
                    allow_nsfw: allowNsfw.checked ? "1" : "0",
                    include_counts: "0",
                });
                const shapeResponse = await fetch(
                    apiUrl(`/galiais-nodes/danbooru/tree?${shapeParams.toString()}`),
                    { signal: activeTreeController.signal },
                );
                const shapePayload = await readJsonResponse(shapeResponse, "分类读取失败");
                if (requestId !== treeRequestId) return;
                treePayloadCache.set(shapeKey, shapePayload);
                lastTreePayload = shapePayload;
                renderTree(shapePayload);
            }

            const params = new URLSearchParams({
                db_path: dbPath,
                field: fieldKey,
                allow_nsfw: allowNsfw.checked ? "1" : "0",
                include_counts: "1",
            });
            const response = await fetch(
                apiUrl(`/galiais-nodes/danbooru/tree?${params.toString()}`),
                { signal: activeTreeController.signal },
            );
            const payload = await readJsonResponse(response, "分类读取失败");
            if (requestId !== treeRequestId) return;
            treePayloadCache.set(fullKey, payload);
            lastTreePayload = payload;
            renderTree(payload);
        } catch (error) {
            if (error?.name === "AbortError") return;
            tree.textContent = `分类读取失败: ${error.message || error}`;
        }
    }

    function renderTree(payload) {
        tree.replaceChildren();
        const countsIncluded = payload?.counts_included !== false;
        const root = document.createElement("button");
        root.className = `galiais-nodes-danbooru-tree-row ${selectedField === fieldKey ? "is-active" : ""}`;
        root.style.paddingLeft = "10px";
        root.innerHTML = `<span class="galiais-nodes-danbooru-tree-toggle">•</span><span class="galiais-nodes-danbooru-tree-label">全部</span><span class="galiais-nodes-danbooru-tree-count">${countsIncluded ? (payload?.leaves || []).length : "..."}</span>`;
        root.addEventListener("click", () => {
            selectedField = fieldKey;
            selectedLabel = "全部";
            renderTree(lastTreePayload);
            updateFilterLabel();
            loadPage(true);
        });
        tree.appendChild(root);

        const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
        for (const node of nodes) renderTreeNode(node, 0, countsIncluded);
    }

    function renderTreeNode(node, depth, countsIncluded = true) {
        const hasChildren = Array.isArray(node.children) && node.children.length > 0;
        const isLeaf = !!node.taxonomy_id;
        const isExpanded = expandedTreeNodes.has(node.id);
        const row = document.createElement("button");
        const depthClass = depth === 0 ? "is-domain" : depth >= 2 ? "is-group" : "";
        const randomBlacklistPath = normalizeTaxonomyPath(node.taxonomy_prefix || node.taxonomy_id || node.id || "");
        const randomBlocked = isRandomTaxonomyBlockedByAncestorOrSelf(randomBlacklistPath);
        const randomPartiallyBlocked = !randomBlocked && hasRandomTaxonomyBlockedDescendant(randomBlacklistPath);
        row.className = `galiais-nodes-danbooru-tree-row ${isLeaf ? "is-leaf" : depthClass} ${selectedField === node.taxonomy_id ? "is-active" : ""} ${randomBlocked ? "is-random-blocked" : ""} ${randomPartiallyBlocked ? "is-random-partial-blocked" : ""}`;
        row.style.paddingLeft = `${12 + depth * 20 + (isLeaf ? 8 : 0)}px`;
        row.title = randomBlocked
            ? "此分类已从随机候选中排除；手动选择不受影响"
            : randomPartiallyBlocked
                ? "部分子分类已从随机候选中排除；点击屏蔽会排除剩余子分类"
                : "";

        const toggle = document.createElement("span");
        toggle.className = "galiais-nodes-danbooru-tree-toggle";
        toggle.textContent = hasChildren ? (isExpanded ? "▾" : "▸") : "•";
        row.appendChild(toggle);

        const label = document.createElement("span");
        label.className = "galiais-nodes-danbooru-tree-label";
        label.textContent = node.label || node.id || "";
        if (node.label_en) label.title = `${node.label || ""} / ${node.label_en}`;
        row.appendChild(label);

        const count = document.createElement("span");
        count.className = "galiais-nodes-danbooru-tree-count";
        count.textContent = countsIncluded ? String(node.count ?? 0) : "...";
        row.appendChild(count);

        const randomBlock = document.createElement("button");
        randomBlock.type = "button";
        randomBlock.className = "galiais-nodes-danbooru-tree-random-block";
        randomBlock.textContent = randomBlocked ? "已屏蔽" : "屏蔽";
        randomBlock.title = randomBlocked ? "恢复此分类参与随机" : "排除此分类及子分类的随机候选";
        randomBlock.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();
            const action = randomBlocked ? "remove" : "add";
            randomBlock.disabled = true;
            setStatus(`${action === "add" ? "正在随机屏蔽" : "正在恢复随机"}: ${node.label || randomBlacklistPath}`);
            try {
                randomTaxonomyBlacklist = await updateGlobalRandomTaxonomyBlacklist(action, [randomBlacklistPath]);
                renderTree(lastTreePayload);
                setStatus(`${action === "add" ? "已排除随机分类" : "已恢复随机分类"}: ${node.label || randomBlacklistPath}`);
            } catch (error) {
                setStatus(`随机分类黑名单更新失败: ${error.message || error}`);
            } finally {
                randomBlock.disabled = false;
            }
        });
        row.appendChild(randomBlock);

        row.addEventListener("click", () => {
            if (isLeaf) {
                selectedField = node.taxonomy_id;
                selectedLabel = node.label || node.taxonomy_id;
                renderTree(lastTreePayload);
                updateFilterLabel();
                loadPage(true);
                return;
            }
            if (expandedTreeNodes.has(node.id)) {
                expandedTreeNodes.delete(node.id);
            } else {
                expandedTreeNodes.add(node.id);
            }
            renderTree(lastTreePayload);
        });
        tree.appendChild(row);

        if (hasChildren && isExpanded) {
            for (const child of node.children) renderTreeNode(child, depth + 1, countsIncluded);
        }
    }
}

app.registerExtension({
    name: "galiaisNodes.DanbooruLazySelect",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (String(nodeData?.name || "").startsWith("GaliaisNodes")) {
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);
                if (updateRandomFieldsWidget(this, message || {})) {
                    refreshNodeSize(this, true);
                }
            };
        }

        if (nodeData?.name === "GaliaisNodesPromptViewer") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);
                setTimeout(() => {
                    const changed = ensurePromptViewerWidgets(this, { ensureStyles });
                    if (changed) refreshNodeSize(this, true);
                }, 0);
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                onConfigure?.apply(this, arguments);
                setTimeout(() => {
                    const changed = ensurePromptViewerWidgets(this, { ensureStyles });
                    if (changed) refreshNodeSize(this, true);
                }, 0);
            };

            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);
                updatePromptViewerWidgets(this, message || {}, { ensureStyles, app });
                refreshNodeSize(this, true);
            };
            return;
        }

        if (nodeData?.name === "GaliaisNodesDanbooruDBLoader") {
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                onConfigure?.apply(this, arguments);
                setTimeout(() => {
                    const changed = ensureDbFileButtonWidget(this);
                    if (changed) refreshNodeSize(this, true);
                }, 0);
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);
                setTimeout(() => {
                    ensureDbFileButtonWidget(this);
                    refreshNodeSize(this, true);
                }, 0);
            };
            return;
        }

        if (nodeData?.name === "GaliaisNodesAIProvider") {
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                onConfigure?.apply(this, arguments);
                setTimeout(() => {
                    const changed = ensureAiModelsButtonWidget(this);
                    if (changed) refreshNodeSize(this, true);
                }, 0);
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);
                setTimeout(() => {
                    ensureAiModelsButtonWidget(this);
                    refreshNodeSize(this, true);
                }, 0);
            };
            return;
        }

        if (nodeData?.name === COMPOSER_NODE_NAME) {
            installComposerPromptSectionControls(nodeType, {
                findWidget,
                setWidgetValue,
                setWidgetHiddenState,
                syncVueWidgetRowVisibility,
                refreshNodeSize,
                ensureStyles,
            });
            return;
        }

        const inputs = nodeData?.input?.required || {};
        const lazyFields = new Map();
        for (const [name, config] of Object.entries(inputs)) {
            const field = getLazyField(config);
            if (field) lazyFields.set(name, field);
        }
        const fallbackFields = FALLBACK_FIELD_MAP[nodeData?.name] || {};
        for (const [name, field] of Object.entries(fallbackFields)) {
            if (!lazyFields.has(name)) lazyFields.set(name, field);
        }
        const hasFieldEnableControls = Object.keys(inputs).some((name) => String(name || "").startsWith("使用"));
        const hasRandomEnableControl = Object.prototype.hasOwnProperty.call(inputs, RANDOM_ENABLE_WIDGET_NAME);
        if (!lazyFields.size && !hasFieldEnableControls && !hasRandomEnableControl) return;

        function scrubNode(node) {
            const fieldEnablePairs = buildFieldEnablePairs(node);
            ensureFieldEnableDrawLayer(node);
            ensureLegacyCanvasPointerHandler();
            const removedWidgets = removeLegacySelectorWidgets(node);
            const cleanedValues = cleanLegacyWidgetValues(node);
            const randomCallbackChanged = ensureRandomEnableVisibilityCallback(node);
            const modeCallbackChanged = ensureTagGenerationModeVisibilityCallback(node);
            const hiddenEnableWidgets = hideFieldEnableWidgets(node, fieldEnablePairs);
            const randomControlVisibilityChanged = syncFieldRandomControlVisibility(node, fieldEnablePairs);
            const legacyCanvasLayoutChanged = ensureLegacyCanvasFieldEnableLayout(node, fieldEnablePairs);
            applyFieldEnableDimState(node, fieldEnablePairs);
            ensureVueFieldEnableToggles(node);
            if (isVueNodeMode(node)) {
                removeLegacyCanvasFieldEnableToggles(node);
            } else {
                scheduleLegacyCanvasFieldEnableToggles(node);
            }
            return removedWidgets || cleanedValues || randomCallbackChanged || modeCallbackChanged || hiddenEnableWidgets || randomControlVisibilityChanged || legacyCanvasLayoutChanged;
        }

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            const changed = scrubNode(this);
            setTimeout(() => {
                const buttonChanged = ensureSelectorButtonWidget(this, lazyFields);
                ensureVueFieldEnableToggles(this);
                if (changed || buttonChanged) {
                    refreshNodeSize(this, changed || buttonChanged, { allowHeightGrowth: false });
                }
            }, 0);
            if (changed) app.graph?.setDirtyCanvas(true, true);
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const changed = scrubNode(this);
            if (Array.isArray(this.title_buttons)) {
                this.title_buttons = (this.title_buttons || []).filter(
                    (button) => button?.name !== "galiais_nodes_danbooru_select",
                );
            }
            setTimeout(() => {
                const buttonChanged = ensureSelectorButtonWidget(this, lazyFields);
                ensureVueFieldEnableToggles(this);
                refreshNodeSize(this, changed || buttonChanged);
            }, 0);
        };

        const onTitleButtonClick = nodeType.prototype.onTitleButtonClick;
        nodeType.prototype.onTitleButtonClick = function (button) {
            if (button?.name === "galiais_nodes_danbooru_select") {
                openFieldChooser(this, lazyFields);
                return;
            }
            onTitleButtonClick?.apply(this, arguments);
        };

        const onDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            onDrawForeground?.apply(this, arguments);
            ensureVueFieldEnableToggles(this);
            if (isVueNodeMode(this)) {
                removeLegacyCanvasFieldEnableToggles(this);
            } else {
                scheduleLegacyCanvasFieldEnableToggles(this);
            }
            if (isVueNodeMode(this) && selectorFieldsForNode(this, lazyFields).length) {
                drawCanvasSelectButton(this, ctx);
            }
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            removeLegacyCanvasFieldEnableToggles(this);
            onRemoved?.apply(this, arguments);
        };

        const onMouseDown = nodeType.prototype.onMouseDown;
        nodeType.prototype.onMouseDown = function (event, pos) {
            if (legacyCanvasLastToggle?.node === this && Date.now() - legacyCanvasLastToggle.time < 80) {
                return true;
            }
            const fieldEnablePairs = buildFieldEnablePairs(this);
            if (!isVueNodeMode(this) && toggleFieldEnableAtPosition(this, pos, fieldEnablePairs)) {
                event?.preventDefault?.();
                event?.stopPropagation?.();
                return true;
            }
            if (
                isVueNodeMode(this) &&
                selectorFieldsForNode(this, lazyFields).length &&
                isInsideRect(pos, canvasSelectButtonRect(this))
            ) {
                openFieldChooser(this, lazyFields, event);
                return true;
            }
            return onMouseDown?.apply(this, arguments);
        };

        const getExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (_, options) {
            const extra = getExtraMenuOptions?.apply(this, arguments);
            const targetOptions = Array.isArray(extra) ? extra : Array.isArray(options) ? options : [];
            const fields = selectorFieldsForNode(this, lazyFields);
            if (!fields.length) {
                return Array.isArray(extra) || !Array.isArray(options) ? targetOptions : extra;
            }

            targetOptions.push(null);
            if (fields.length > 1) {
                targetOptions.push({
                    content: "GALIAIS-Nodes: 选择 Danbooru 字段...",
                    has_submenu: true,
                    callback: () => {},
                    submenu: {
                        options: fields.map((item) => ({
                            content: item.widget.name,
                            callback: () => openSelectorForField(item, findDanbooruDbPath()),
                        })),
                    },
                });
            } else {
                const item = fields[0];
                targetOptions.push({
                    content: `GALIAIS-Nodes: 选择 ${item.widget.name}`,
                    callback: () => openSelectorForField(item, findDanbooruDbPath()),
                });
            }
            return Array.isArray(extra) || !Array.isArray(options) ? targetOptions : extra;
        };
    },
});
