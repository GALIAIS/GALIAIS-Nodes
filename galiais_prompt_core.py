import json
import os
import random
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Iterable
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_DANBOORU_DB_PATH = ""
GALIAIS_NODES_SCHEMA_VERSION = "2.0.0"
GALIAIS_NODES_COMPOSER_VERSION = "2.0.0"
GALIAIS_NODES_TAXONOMY_VERSION = "danbooru-taxonomy-next"
_DANBOORU_CACHE_MISS = object()
_DANBOORU_OPTION_CACHE_LIMIT = 256
_DANBOORU_TREE_CACHE_LIMIT = 96
_AI_RESPONSE_CACHE_LIMIT = 128
_DANBOORU_OPTION_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_DANBOORU_TREE_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_AI_RESPONSE_CACHE: OrderedDict[str, dict] = OrderedDict()
_DANBOORU_RUNTIME_PATH_CACHE: dict[tuple[str, int, int], str] = {}
TAG_BLACKLIST_PATH = Path(__file__).with_name("galiais_tag_blacklist.json")
RANDOM_TAXONOMY_BLACKLIST_PATH = Path(__file__).with_name("galiais_random_taxonomy_blacklist.json")


def runtime_random_is_changed(enabled, count, seed):
    if not bool(enabled):
        return False
    if int(count or 0) <= 0:
        return False
    safe_seed = int(seed or 0)
    if safe_seed:
        return f"random-fixed-seed:{safe_seed}"
    return f"random-auto-seed:{random.SystemRandom().getrandbits(64)}"


def normalize_danbooru_db_path(db_path: str) -> str:
    text = str(db_path or "").strip().strip('"')
    if not text:
        raise ValueError("DB路径为空：请添加 GALIAIS-Nodes Danbooru DB Loader 并填写数据库文件路径。")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Danbooru dictionary database not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Danbooru dictionary path is not a file: {path}")
    return str(path)


def resolve_danbooru_db_path(db_path: str = "", db=None) -> str:
    if isinstance(db, dict):
        candidate = db.get("db_path") or db.get("DB路径") or db.get("path")
        if candidate:
            return normalize_danbooru_db_path(candidate)
    elif db:
        return normalize_danbooru_db_path(str(db))
    return normalize_danbooru_db_path(db_path)


def optional_danbooru_db_path(db_path: str = "", db=None) -> str:
    try:
        return resolve_danbooru_db_path(db_path, db)
    except Exception:
        return ""


def _db_cache_signature(db_path: str) -> tuple[str, int, int]:
    path = Path(db_path)
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _read_db_metadata(db_path: str) -> dict[str, str]:
    try:
        conn = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)
        try:
            row = conn.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'dictionary_metadata' limit 1"
            ).fetchone()
            if not row:
                return {}
            return {
                str(item[0]): str(item[1] or "")
                for item in conn.execute("select key, value from dictionary_metadata")
            }
        finally:
            conn.close()
    except Exception:
        return {}


def _runtime_candidate_paths(source_path: Path) -> list[Path]:
    candidates = [
        source_path.with_name("danbooru-dictionary.runtime.db"),
        source_path.with_name(source_path.stem + ".runtime.db"),
    ]
    unique = []
    seen = set()
    for candidate in candidates:
        text = str(candidate)
        if text in seen:
            continue
        seen.add(text)
        unique.append(candidate)
    return unique


def _runtime_matches_source(runtime_path: Path, source_path: Path) -> bool:
    metadata = _read_db_metadata(str(runtime_path))
    if metadata.get("runtime_db") != "1":
        return False
    runtime_source_path = metadata.get("runtime_source_path")
    if runtime_source_path and str(Path(runtime_source_path)) != str(source_path):
        return False
    try:
        source_stat = source_path.stat()
    except OSError:
        return False
    source_size = metadata.get("runtime_source_size")
    source_mtime = metadata.get("runtime_source_mtime_ns")
    if source_size and source_mtime and source_size == str(source_stat.st_size) and source_mtime == str(source_stat.st_mtime_ns):
        return True
    counts_text = metadata.get("runtime_counts_json")
    if counts_text:
        try:
            runtime_counts = json.loads(counts_text)
            source_counts = _source_runtime_table_counts(str(source_path))
        except Exception:
            runtime_counts = {}
            source_counts = {}
        comparable_keys = {"tags", "localizations", "taxonomy", "templates"}
        if comparable_keys.issubset(runtime_counts) and all(
            int(runtime_counts[key]) == int(source_counts.get(key, -1))
            for key in comparable_keys
        ):
            return True
    if source_size and source_mtime:
        return source_size == str(source_stat.st_size) and source_mtime == str(source_stat.st_mtime_ns)
    return bool(runtime_source_path) and str(Path(runtime_source_path)) == str(source_path)


def _source_runtime_table_counts(db_path: str) -> dict[str, int]:
    conn = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)
    try:
        template_count = 0
        has_templates = conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'prompt_templates' limit 1"
        ).fetchone()
        if has_templates:
            template_count = conn.execute("select count(*) from prompt_templates").fetchone()[0]
        return {
            "tags": int(conn.execute("select count(*) from danbooru_tags").fetchone()[0]),
            "localizations": int(conn.execute("select count(*) from danbooru_tag_localizations").fetchone()[0]),
            "taxonomy": int(conn.execute("select count(*) from tag_taxonomy").fetchone()[0]),
            "templates": int(template_count),
        }
    finally:
        conn.close()


def preferred_danbooru_runtime_path(db_path: str) -> str:
    normalized = normalize_danbooru_db_path(db_path)
    signature = _db_cache_signature(normalized)
    cached = _DANBOORU_RUNTIME_PATH_CACHE.get(signature)
    if cached and cached != normalized:
        return cached

    path = Path(normalized)
    metadata = _read_db_metadata(normalized)
    if metadata.get("runtime_db") == "1":
        _DANBOORU_RUNTIME_PATH_CACHE[signature] = normalized
        return normalized

    for candidate in _runtime_candidate_paths(path):
        if candidate.exists() and candidate.is_file() and _runtime_matches_source(candidate, path):
            runtime_path = str(candidate)
            _DANBOORU_RUNTIME_PATH_CACHE[signature] = runtime_path
            return runtime_path

    _DANBOORU_RUNTIME_PATH_CACHE[signature] = normalized
    return normalized


def _cache_get(cache: OrderedDict, key: tuple):
    if key not in cache:
        return _DANBOORU_CACHE_MISS
    value = cache.pop(key)
    cache[key] = value
    return value


def _cache_put(cache: OrderedDict, key: tuple, value: dict, limit: int) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > limit:
        cache.popitem(last=False)


def _taxonomy_category_from_id(taxonomy_id: str) -> int | None:
    head = str(taxonomy_id or "").split(".", 1)[0]
    if not head.isdigit():
        return None
    return int(head)


def _contains_cjk(value: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in str(value or "")
    )


def _contains_ascii_alnum(value: str) -> bool:
    return bool(re.search(r"[a-zA-Z0-9]", str(value or "")))


def _single_taxonomy_category(taxonomy_ids: list[str]) -> int | None:
    categories = {
        category
        for category in (_taxonomy_category_from_id(item) for item in taxonomy_ids)
        if category is not None
    }
    if len(categories) != 1:
        return None
    return next(iter(categories))

GALIAIS_NODES_NEGATIVE_PRESETS = {
    "标准": (
        "worst quality, low quality, score_1, score_2, score_3, lowres, blurry, "
        "jpeg artifacts, bad anatomy, bad hands, deformed hands, extra fingers, "
        "missing fingers, fused fingers, mutated hands, poorly drawn hands, text, "
        "watermark, signature, artist name"
    ),
    "轻量": "worst quality, low quality, blurry, watermark, text",
    "手部修复": (
        "bad hands, deformed hands, extra fingers, missing fingers, fused fingers, "
        "mutated hands, poorly drawn hands, bad anatomy"
    ),
    "写实": (
        "worst quality, low quality, blurry, noise, grain, overexposed, "
        "underexposed, out of focus, bad composition, watermark, text, logo"
    ),
    "无": "",
}

GALIAIS_NODES_QUALITY_PRESETS = {
    "Anima score_9": "masterpiece, best quality, score_9, safe",
    "Anima score_8": "masterpiece, best quality, score_8, safe",
    "Anima score_7": "masterpiece, best quality, score_7, safe",
    "通用高质量": "masterpiece, best quality, highres, detailed",
    "无": "",
}

TAG_SPLIT_RE = re.compile(r"[,，\n\r;；|]+")
TEMPLATE_SLOT_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-\u4e00-\u9fff]+)\s*\}\}")
TEMPLATE_DOTTED_SLOT_FALLBACKS = {
    "quality.style": "风格",
    "quality.lighting": "光照",
    "quality.detail": "细节",
    "quality.quality": "质量",
    "background.location": "场景",
    "background.environment": "场景",
    "composition.framing": "镜头",
    "composition.camera": "镜头",
    "appearance": "外观",
    "background": "场景",
    "composition": "镜头",
    "quality": "质量",
    "clothing": "服装",
    "pose": "姿势",
    "emotion": "表情",
    "style": "风格",
    "lighting": "光照",
    "character": "角色",
    "subject": "主体",
    "detail": "细节",
    "scene": "场景",
}
GALIAIS_NODES_DANBOORU_FIELD_REGISTRY: dict[str, dict] = {}
_DANBOORU_FIELD_IMPORT_ATTEMPTED = False
ANIMA_QUALITY_TAGS = {
    "masterpiece",
    "best quality",
    "best_quality",
    "high quality",
    "high_quality",
    "worst quality",
    "worst_quality",
    "low quality",
    "low_quality",
    "normal quality",
    "normal_quality",
    "highres",
    "lowres",
    "detailed",
    "safe",
}
ANIMA_LIGHT_COLOR_KEYWORDS = (
    "lighting",
    "lit",
    "sunlight",
    "moonlight",
    "backlight",
    "rim_light",
    "rim light",
    "chiaroscuro",
    "shadow",
    "shadows",
    "glow",
    "glowing",
    "color_palette",
    "colour_palette",
    "palette",
    "monochrome",
    "grayscale",
    "sepia",
    "pastel_color",
    "pastel colors",
    "pastel_colors",
)
TAXONOMY_DOMAIN_LABELS_ZH = {
    "appearance": "外观",
    "artist": "画师",
    "character": "角色",
    "clothing": "服装",
    "composition": "镜头构图",
    "copyright": "作品",
    "effect": "画面特效",
    "expression": "表情情绪",
    "meta": "元信息",
    "narrative": "叙事关系",
    "nsfw": "NSFW",
    "object": "物件道具",
    "pose": "姿势动作",
    "scene": "场景",
    "style": "风格",
    "subject": "主体",
    "uncertain": "待复审",
}
TAXONOMY_FACET_LABELS_ZH = {
    ("appearance", "body"): "身体",
    ("appearance", "eyes"): "眼睛",
    ("appearance", "face"): "脸部",
    ("appearance", "hair"): "头发",
    ("artist", "identity"): "画师身份",
    ("artist", "style"): "画师风格",
    ("character", "identity"): "角色身份",
    ("character", "role"): "角色定位",
    ("character", "species"): "角色种族",
    ("character", "variant"): "角色变体",
    ("clothing", "accessory"): "服装配饰",
    ("clothing", "detail"): "服装细节",
    ("clothing", "intimate"): "贴身衣物",
    ("clothing", "lower"): "下装",
    ("clothing", "material"): "服装材质",
    ("clothing", "onepiece"): "连体服装",
    ("clothing", "pattern"): "服装图案",
    ("clothing", "state"): "穿着状态",
    ("clothing", "upper"): "上装",
    ("composition", "camera"): "相机",
    ("composition", "depth"): "景深",
    ("composition", "framing"): "取景",
    ("composition", "layout"): "布局",
    ("composition", "perspective"): "透视",
    ("copyright", "medium"): "作品类型",
    ("copyright", "organization"): "组织阵营",
    ("effect", "damage"): "冲击破坏",
    ("effect", "digital"): "数字故障",
    ("effect", "elemental"): "元素效果",
    ("effect", "energy"): "能量发光",
    ("effect", "material"): "材质状态",
    ("effect", "motion"): "运动效果",
    ("effect", "particle"): "粒子效果",
    ("effect", "supernatural"): "超自然效果",
    ("effect", "surface"): "表面痕迹",
    ("expression", "emotion"): "情绪",
    ("expression", "gaze"): "视线互动",
    ("expression", "mental"): "心理想象",
    ("expression", "reaction"): "反应",
    ("nsfw", "act"): "性行为",
    ("nsfw", "body"): "露骨身体",
    ("nsfw", "context"): "成人语境",
    ("nsfw", "exposure"): "裸露",
    ("nsfw", "fetish"): "性癖",
    ("nsfw", "fluid"): "性液体",
    ("nsfw", "framing"): "色情构图",
    ("nsfw", "object"): "成人物品",
    ("object", "food"): "食物饮品",
    ("object", "media"): "媒体物",
    ("object", "nature"): "自然物",
    ("object", "prop"): "道具",
    ("pose", "action"): "动作",
    ("pose", "gesture"): "肢体手势",
    ("pose", "interaction"): "互动",
    ("pose", "posture"): "整体姿态",
    ("scene", "background"): "背景",
    ("scene", "culture"): "文化节日",
    ("scene", "decor"): "装饰",
    ("scene", "environment"): "环境",
    ("scene", "location"): "地点",
    ("scene", "object"): "场景物",
    ("scene", "structure"): "结构",
    ("scene", "symbol"): "符号",
    ("style", "color"): "色彩",
    ("style", "design"): "设计",
    ("style", "lighting"): "光照",
    ("style", "line"): "线稿",
    ("style", "medium"): "媒介",
    ("style", "postprocess"): "后期",
    ("style", "quality"): "质量细节",
    ("style", "rendering"): "渲染",
    ("subject", "count"): "人数",
    ("subject", "focus"): "主体焦点",
    ("subject", "identity"): "主体身份",
}


def _taxonomy_label(key: str, *, fallback: str = "") -> str:
    text = str(key or "").strip()
    if not text:
        return fallback
    return text.replace("_", " ").title()


def taxonomy_domain_label(domain: str) -> str:
    return TAXONOMY_DOMAIN_LABELS_ZH.get(str(domain or ""), _taxonomy_label(domain, fallback="未知"))


def taxonomy_facet_label(domain: str, facet: str) -> str:
    key = (str(domain or ""), str(facet or ""))
    return TAXONOMY_FACET_LABELS_ZH.get(key, _taxonomy_label(facet, fallback="未知"))


@dataclass(frozen=True)
class ResolvedTag:
    query: str
    tag: str
    label: str
    category: int | None
    semantic_category: str | None
    taxonomy_id: str | None
    post_count: int
    is_nsfw: bool
    source: str

    def to_dict(self):
        return asdict(self)


def split_tag_text(text: str) -> list[str]:
    items = []
    for part in TAG_SPLIT_RE.split(str(text or "")):
        item = part.strip()
        if item:
            items.append(item)
    return items


def split_tag_option_text(text: str) -> list[str]:
    items = []
    current = []
    depth = 0
    for char in str(text or ""):
        if char == "(":
            depth += 1
            current.append(char)
            continue
        if char == ")" and depth > 0:
            depth -= 1
            current.append(char)
            continue
        if depth == 0 and char in {",", "，", "\n", "\r", ";", "；"}:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
            continue
        current.append(char)
    item = "".join(current).strip()
    if item:
        items.append(item)
    return items


def normalize_tag_name(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


_TAG_EXISTS_CACHE: dict[tuple[str, str], bool] = {}


def _strip_trailing_parenthetical(value: str) -> str:
    text = str(value or "").rstrip()
    if not text.endswith(")"):
        return text.strip()
    depth = 0
    for index in range(len(text) - 1, -1, -1):
        char = text[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                before = text[:index].rstrip()
                return before.strip() if before else text.strip()
    return text.strip()


def _danbooru_tag_exists(tag: str, db_path: str = "") -> bool:
    normalized = normalize_tag_name(tag)
    path_text = optional_danbooru_db_path(db_path)
    if not normalized or not path_text:
        return False
    cache_key = (path_text, normalized)
    if cache_key in _TAG_EXISTS_CACHE:
        return _TAG_EXISTS_CACHE[cache_key]
    try:
        conn = sqlite3.connect("file:" + path_text + "?mode=ro", uri=True)
        try:
            row = conn.execute(
                "select 1 from danbooru_tags where normalized_name = ? limit 1",
                (normalized,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        row = None
    exists = bool(row)
    _TAG_EXISTS_CACHE[cache_key] = exists
    return exists


def _prefix_upper_bound(value: str) -> str:
    text = str(value or "")
    if not text:
        return "\U0010ffff"
    last = ord(text[-1])
    if last >= 0x10FFFF:
        return text + "\U0010ffff"
    return text[:-1] + chr(last + 1)


def parse_tag_option(value: str, db_path: str = "") -> str:
    text = str(value or "").strip()
    if not text or text == "none":
        return ""
    text = text.split(" | ", 1)[0].strip()
    stripped = _strip_trailing_parenthetical(text)
    if stripped != text and not _danbooru_tag_exists(text, db_path):
        return stripped
    return text


def normalize_tag_blacklist(value=None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        nested = value.get("tag_blacklist") or value.get("Tag黑名单")
        if nested:
            return normalize_tag_blacklist(nested)
        if not value.get("enabled", True):
            return ()
        raw_items = value.get("normalized_tags")
        if raw_items is None:
            raw_items = value.get("tags")
        if raw_items is None:
            raw_items = value.get("text", "")
    elif isinstance(value, (list, tuple, set)) or (
        isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray))
    ):
        raw_items = value
    else:
        raw_items = split_tag_option_text(str(value or ""))
    if isinstance(raw_items, str):
        raw_items = split_tag_option_text(raw_items)

    normalized = []
    seen = set()
    for item in raw_items or []:
        text = str(item or "").strip()
        if not text:
            continue
        if " | " in text:
            text = text.split(" | ", 1)[0].strip()
        text = _strip_trailing_parenthetical(text)
        key = normalize_tag_name(text)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return tuple(normalized)


def normalize_taxonomy_blacklist(value=None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        nested = (
            value.get("taxonomy_blacklist")
            or value.get("random_taxonomy_blacklist")
            or value.get("随机分类黑名单")
        )
        if nested:
            return normalize_taxonomy_blacklist(nested)
        if not value.get("enabled", True):
            return ()
        raw_items = value.get("taxonomy_ids")
        if raw_items is None:
            raw_items = value.get("paths")
        if raw_items is None:
            raw_items = value.get("items")
        if raw_items is None:
            raw_items = value.get("text", "")
    elif isinstance(value, (list, tuple, set)) or (
        isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray))
    ):
        raw_items = value
    else:
        raw_items = split_tag_option_text(str(value or ""))
    if isinstance(raw_items, str):
        raw_items = split_tag_option_text(raw_items)

    normalized = []
    seen = set()
    for item in raw_items or []:
        text = str(item or "").strip()
        if not text:
            continue
        if " | " in text:
            text = text.split(" | ", 1)[0].strip()
        text = _strip_trailing_parenthetical(text).strip().strip(".")
        text = re.sub(r"\s+", "", text)
        if text.startswith("<") or text.endswith(">") or not re.match(r"^[0-9A-Za-z_.:-]+$", text):
            continue
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    normalized.sort()
    return tuple(normalized)


def _read_global_tag_blacklist() -> tuple[str, ...]:
    try:
        raw = json.loads(TAG_BLACKLIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ()
    return normalize_tag_blacklist(raw)


def _write_global_tag_blacklist(tags) -> tuple[str, ...]:
    normalized = normalize_tag_blacklist(tags)
    payload = galiais_metadata(
        {
            "enabled": True,
            "normalized_tags": list(normalized),
            "count": len(normalized),
        }
    )
    tmp = TAG_BLACKLIST_PATH.with_suffix(TAG_BLACKLIST_PATH.suffix + ".tmp")
    tmp.write_text(_metadata_json(payload), encoding="utf-8")
    tmp.replace(TAG_BLACKLIST_PATH)
    return normalized


def global_tag_blacklist(extra=None) -> tuple[str, ...]:
    merged = []
    seen = set()
    for tag in (*_read_global_tag_blacklist(), *normalize_tag_blacklist(extra)):
        if tag in seen:
            continue
        seen.add(tag)
        merged.append(tag)
    return tuple(merged)


def add_global_tag_blacklist(tags) -> tuple[str, ...]:
    return _write_global_tag_blacklist(global_tag_blacklist(tags))


def remove_global_tag_blacklist(tags) -> tuple[str, ...]:
    remove = set(normalize_tag_blacklist(tags))
    if not remove:
        return _read_global_tag_blacklist()
    return _write_global_tag_blacklist(tag for tag in _read_global_tag_blacklist() if tag not in remove)


def _read_global_random_taxonomy_blacklist() -> tuple[str, ...]:
    try:
        raw = json.loads(RANDOM_TAXONOMY_BLACKLIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ()
    return normalize_taxonomy_blacklist(raw)


def _write_global_random_taxonomy_blacklist(items) -> tuple[str, ...]:
    normalized = normalize_taxonomy_blacklist(items)
    payload = galiais_metadata(
        {
            "enabled": True,
            "taxonomy_ids": list(normalized),
            "count": len(normalized),
            "scope": "random_only",
        }
    )
    tmp = RANDOM_TAXONOMY_BLACKLIST_PATH.with_suffix(RANDOM_TAXONOMY_BLACKLIST_PATH.suffix + ".tmp")
    tmp.write_text(_metadata_json(payload), encoding="utf-8")
    tmp.replace(RANDOM_TAXONOMY_BLACKLIST_PATH)
    return normalized


def global_random_taxonomy_blacklist(extra=None) -> tuple[str, ...]:
    merged = []
    seen = set()
    for item in (*_read_global_random_taxonomy_blacklist(), *normalize_taxonomy_blacklist(extra)):
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return tuple(merged)


def add_global_random_taxonomy_blacklist(items) -> tuple[str, ...]:
    return _write_global_random_taxonomy_blacklist(global_random_taxonomy_blacklist(items))


def remove_global_random_taxonomy_blacklist(items) -> tuple[str, ...]:
    remove = set(normalize_taxonomy_blacklist(items))
    if not remove:
        return _read_global_random_taxonomy_blacklist()
    return _write_global_random_taxonomy_blacklist(
        item for item in _read_global_random_taxonomy_blacklist() if item not in remove
    )


def format_tag_option(term: ResolvedTag) -> str:
    label = term.label or term.tag
    return term.tag if label == term.tag else f"{term.tag} | {label}"


def format_tag_option_parts(tag: str, label: str) -> str:
    label = label or tag
    return tag if label == tag else f"{tag} | {label}"


def format_tag_display_parts(tag: str, label: str) -> str:
    clean_tag = str(tag or "").strip().replace("_", " ")
    clean_label = str(label or "").strip()
    if not clean_tag:
        return ""
    if not clean_label or clean_label == tag or clean_label == clean_tag:
        return clean_tag
    return f"{clean_tag} ({clean_label})"


def join_tag_display_parts(parts, dedupe: bool = True) -> str:
    result = []
    seen = set()
    for part in parts:
        for token in split_tag_option_text(str(part or "")):
            display = token.strip()
            if not display:
                continue
            key = normalize_tag_name(parse_tag_option(display))
            if dedupe and key and key in seen:
                continue
            if key:
                seen.add(key)
            result.append(display)
    return ", ".join(result)


def register_danbooru_field_set(
    group: str,
    taxonomy_fields: dict[str, list[str]],
    category_fields: dict[str, tuple[int, str | None]] | None = None,
) -> None:
    category_fields = category_fields or {}
    for field, taxonomy_ids in taxonomy_fields.items():
        text = str(field).strip()
        if not text:
            continue
        entry = GALIAIS_NODES_DANBOORU_FIELD_REGISTRY.setdefault(
            text,
            {
                "field": text,
                "groups": [],
                "taxonomy_ids": [],
                "categories": [],
            },
        )
        if group and group not in entry["groups"]:
            entry["groups"].append(group)
        for taxonomy_id in taxonomy_ids or []:
            taxonomy_id = str(taxonomy_id).strip()
            if taxonomy_id and taxonomy_id not in entry["taxonomy_ids"]:
                entry["taxonomy_ids"].append(taxonomy_id)
        if field in category_fields:
            category, semantic_category = category_fields[field]
            category_spec = {
                "category": int(category),
                "semantic_category": semantic_category,
            }
            if category_spec not in entry["categories"]:
                entry["categories"].append(category_spec)


def _ensure_danbooru_field_modules_loaded() -> None:
    global _DANBOORU_FIELD_IMPORT_ATTEMPTED
    if _DANBOORU_FIELD_IMPORT_ATTEMPTED:
        return
    _DANBOORU_FIELD_IMPORT_ATTEMPTED = True
    try:
        from . import nodes_galiais_character_prompt  # noqa: F401
    except Exception:
        try:
            import nodes_galiais_character_prompt  # noqa: F401
        except Exception:
            return


def danbooru_field_spec(field: str) -> dict | None:
    text = str(field or "").strip()
    if not text:
        return None
    spec = GALIAIS_NODES_DANBOORU_FIELD_REGISTRY.get(text)
    if spec:
        return spec
    _ensure_danbooru_field_modules_loaded()
    spec = GALIAIS_NODES_DANBOORU_FIELD_REGISTRY.get(text)
    if spec:
        return spec
    if text.startswith("category:"):
        try:
            category = int(text.split(":", 1)[1])
        except ValueError:
            return None
        return {
            "field": text,
            "groups": ["category"],
            "taxonomy_ids": [],
            "categories": [{"category": category, "semantic_category": None}],
        }
    if "." in text:
        return {
            "field": text,
            "groups": ["taxonomy"],
            "taxonomy_ids": [text],
            "categories": [],
        }
    return None


def parse_candidate_index(value: str) -> int:
    text = str(value or "").strip()
    match = re.search(r"(\d+)", text)
    if not match:
        return 0
    return max(0, int(match.group(1)) - 1)


def _clean_prompt_token(value: str) -> str:
    return str(value or "").strip().strip(",")


def join_prompt_parts(parts, dedupe: bool = True, separator: str = ", ") -> str:
    output = []
    seen = set()
    for part in parts:
        for token in split_tag_text(str(part or "")):
            cleaned = _clean_prompt_token(token)
            if not cleaned:
                continue
            key = normalize_tag_name(cleaned)
            if dedupe and key in seen:
                continue
            seen.add(key)
            output.append(cleaned)
    return separator.join(output)


def strip_prompt_weight(token: str) -> str:
    text = str(token or "").strip()
    match = re.fullmatch(r"\((.+):[0-9.]+\)", text)
    return match.group(1).strip() if match else text


def is_anima_forbidden_token(token: str, *, allow_artist: bool = False) -> bool:
    text = strip_prompt_weight(token).strip().lower()
    normalized = text.replace("_", " ")
    if not text or text == "none":
        return True
    if text.startswith("@"):
        return not allow_artist
    if text.startswith("score_"):
        return True
    if text in ANIMA_QUALITY_TAGS or normalized in ANIMA_QUALITY_TAGS:
        return True
    return any(keyword in text or keyword in normalized for keyword in ANIMA_LIGHT_COLOR_KEYWORDS)


def normalize_artist_tag(value: str, db_path: str = "") -> str:
    artists = []
    seen = set()
    for token in split_tag_option_text(value):
        artist = parse_tag_option(token, db_path=db_path).strip().lower()
        if not artist or artist == "none":
            continue
        artist = artist if artist.startswith("@") else "@" + artist
        key = normalize_tag_name(artist.lstrip("@"))
        if key in seen:
            continue
        seen.add(key)
        artists.append(artist)
    return ", ".join(artists)


def join_anima_prompt_parts(
    parts,
    dedupe: bool = True,
    separator: str = ", ",
    *,
    allow_artist: bool = False,
    db_path: str = "",
) -> str:
    output = []
    seen = set()
    for part in parts:
        for token in split_tag_text(str(part or "")):
            cleaned = parse_tag_option(strip_prompt_weight(token), db_path=db_path).strip().strip(",").lower()
            if is_anima_forbidden_token(cleaned, allow_artist=allow_artist):
                continue
            key = normalize_tag_name(cleaned)
            if dedupe and key in seen:
                continue
            seen.add(key)
            output.append(cleaned)
    return separator.join(output)


def apply_tag_weight(tag: str, weight: float) -> str:
    cleaned = _clean_prompt_token(tag)
    if not cleaned:
        return ""
    if weight <= 0:
        return ""
    if abs(weight - 1.0) < 0.0001:
        return cleaned
    return f"({cleaned}:{weight:.2f})"


def render_prompt_template(template: str, slots: dict[str, str]) -> str:
    def slot_value(key: str) -> str:
        if key in slots:
            return str(slots.get(key) or "").strip()
        parts = str(key or "").split(".")
        for length in range(len(parts) - 1, 0, -1):
            candidate = ".".join(parts[:length])
            if candidate in slots:
                return str(slots.get(candidate) or "").strip()
            fallback = TEMPLATE_DOTTED_SLOT_FALLBACKS.get(candidate)
            if fallback and fallback in slots:
                return str(slots.get(fallback) or "").strip()
        fallback = TEMPLATE_DOTTED_SLOT_FALLBACKS.get(parts[0] if parts else "")
        if fallback and fallback in slots:
            return str(slots.get(fallback) or "").strip()
        return ""

    def replace(match):
        key = match.group(1)
        return slot_value(key)

    rendered = TEMPLATE_SLOT_RE.sub(replace, str(template or ""))
    return join_prompt_parts([rendered], dedupe=True)


def _metadata_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def galiais_metadata(payload: dict | None = None, **extra) -> dict:
    data = dict(payload or {})
    data.update(extra)
    data.setdefault("schema_version", GALIAIS_NODES_SCHEMA_VERSION)
    data.setdefault("composer_version", GALIAIS_NODES_COMPOSER_VERSION)
    data.setdefault("taxonomy_version", GALIAIS_NODES_TAXONOMY_VERSION)
    return data


def _parse_json_object(value, default=None):
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return default if default is not None else {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return default if default is not None else {}
    return parsed if isinstance(parsed, dict) else (default if default is not None else {})


def _mask_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


def _resolve_api_key(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if text.startswith("env:"):
        env_name = text[4:].strip()
        return (os.environ.get(env_name, ""), f"env:{env_name}")
    if text.startswith("$"):
        env_name = text[1:].strip()
        return (os.environ.get(env_name, ""), f"env:{env_name}")
    return (text, "input" if text else "")


def _normalize_openai_base_url(base_url: str, api_mode: str = "自动") -> str:
    text = str(base_url or "").strip().rstrip("/")
    if not text:
        return ""
    mode = str(api_mode or "自动")
    if mode == "保持原样":
        return text
    text = re.sub(r"/v(\d+)/(models|chat/completions|completions|responses)$", r"/v\1", text)
    if mode == "强制/v1":
        return text if text.endswith("/v1") else f"{text}/v1"
    if re.search(r"/v\d+$", text):
        return text
    return f"{text}/v1"


def _url_join(base_url: str, path: str) -> str:
    return str(base_url or "").rstrip("/") + "/" + str(path or "").lstrip("/")


def _ai_http_headers(api_key: str, *, accept: str = "application/json") -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36 GALIAIS-Nodes/1.0"
        ),
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _ai_http_error_message(prefix: str, code: int, body: str) -> str:
    preview = str(body or "")[:500]
    try:
        payload = json.loads(body)
    except Exception:
        payload = {}
    error_code = str(payload.get("error_code") or payload.get("code") or "")
    error_name = str(payload.get("error_name") or payload.get("title") or "")
    if code == 403 and (error_code == "1010" or "browser_signature_banned" in preview):
        return (
            f"{prefix} 403: Cloudflare 拒绝了当前后端请求特征(browser_signature_banned/1010)。"
            "已使用浏览器兼容请求头，请确认服务商没有要求白名单、代理、浏览器验证或更换 API 网关。"
            f" 原始信息: {preview}"
        )
    if error_name:
        return f"{prefix} {code}: {error_name} {preview}"
    return f"{prefix} {code}: {preview}"


def _json_http_request(method: str, url: str, api_key: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = _ai_http_headers(api_key, accept="application/json")
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=str(method or "GET").upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout or 30))) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(_ai_http_error_message("AI接口请求失败", exc.code, body)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI接口连接失败: {exc.reason}") from exc
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI接口返回非JSON: {text[:500]}") from exc


def _stream_json_http_request(url: str, api_key: str, payload: dict, timeout: int = 30) -> dict:
    headers = _ai_http_headers(api_key, accept="text/event-stream, application/json")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    chunks = []
    event_count = 0
    finish_reason = ""
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout or 30))) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                event_count += 1
                choices = event.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                delta = choice.get("delta") or choice.get("message") or {}
                content = delta.get("content") or choice.get("text") or ""
                if content:
                    chunks.append(str(content))
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason") or "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(_ai_http_error_message("AI流式接口请求失败", exc.code, body)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI流式接口连接失败: {exc.reason}") from exc
    return {
        "content": "".join(chunks),
        "raw": {
            "stream": True,
            "event_count": event_count,
            "finish_reason": finish_reason,
        },
    }


def _safe_retry_count(value) -> int:
    try:
        return max(1, min(8, int(value or 1)))
    except (TypeError, ValueError):
        return 1


def _safe_retry_backoff(value) -> float:
    try:
        return max(0.0, min(10.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _is_retryable_ai_error(error: Exception) -> bool:
    text = str(error)
    retry_markers = [
        "AI接口连接失败",
        "AI流式接口连接失败",
        "AI流式接口返回为空",
        "timed out",
        "timeout",
        "WinError 10060",
        "Errno 10060",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
    ]
    if any(marker.lower() in text.lower() for marker in retry_markers):
        return True
    match = re.search(r"(?:AI接口请求失败|AI流式接口请求失败)\s+(\d+)", text)
    if match:
        code = int(match.group(1))
        return code == 429 or code >= 500
    return False


def _attach_retry_metadata(response: dict, retry_meta: dict) -> dict:
    if not isinstance(response, dict):
        response = {"content": str(response or ""), "raw": {}}
    raw = response.get("raw")
    if not isinstance(raw, dict):
        raw = {"value": raw}
    raw["retry"] = retry_meta
    response["raw"] = raw
    return response


def _ai_cache_enabled(provider_config: dict) -> bool:
    if not isinstance(provider_config, dict):
        return False
    value = provider_config.get("ai_cache_enabled", provider_config.get("cache_enabled", False))
    return bool(value)


def _ai_cache_ttl_seconds(provider_config: dict) -> int:
    if not isinstance(provider_config, dict):
        return 0
    try:
        return max(0, int(provider_config.get("ai_cache_ttl_seconds", provider_config.get("cache_ttl_seconds", 0)) or 0))
    except (TypeError, ValueError):
        return 0


def _stable_json_for_cache(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _ai_cache_key(provider_config: dict, messages: list[dict]) -> str:
    provider = provider_config if isinstance(provider_config, dict) else {}
    relevant = {
        "base_url": _normalize_openai_base_url(provider.get("base_url", ""), provider.get("api_mode", "自动")),
        "model": str(provider.get("model") or ""),
        "temperature": float(provider.get("temperature", 0.35)),
        "max_tokens": int(provider.get("max_tokens", 1200) or 1200),
        "reasoning_mode": str(provider.get("reasoning_mode") or "关闭"),
        "reasoning_effort": str(provider.get("reasoning_effort") or ""),
        "service_tier": str(provider.get("service_tier") or ""),
        "stream": bool(provider.get("stream", False)),
        "messages": messages,
    }
    return _stable_json_for_cache(relevant)


def _copy_ai_response(response: dict, *, cache_hit: bool) -> dict:
    copied = json.loads(json.dumps(response if isinstance(response, dict) else {"content": str(response or ""), "raw": {}}, ensure_ascii=False, default=str))
    raw = copied.get("raw")
    if not isinstance(raw, dict):
        raw = {"value": raw}
    raw["cache_hit"] = bool(cache_hit)
    copied["raw"] = raw
    return copied


def cached_ai_chat_completion(client, provider_config: dict, messages: list[dict]) -> dict:
    provider = provider_config if isinstance(provider_config, dict) else {}
    if not _ai_cache_enabled(provider):
        return client.chat_completion(provider, messages)
    cache_key = _ai_cache_key(provider, messages)
    ttl = _ai_cache_ttl_seconds(provider)
    now = time.time()
    cached = _AI_RESPONSE_CACHE.get(cache_key)
    if cached and (ttl <= 0 or now - float(cached.get("created_at", 0)) <= ttl):
        _AI_RESPONSE_CACHE.move_to_end(cache_key)
        return _copy_ai_response(cached.get("response", {}), cache_hit=True)
    response = client.chat_completion(provider, messages)
    _AI_RESPONSE_CACHE[cache_key] = {
        "created_at": now,
        "response": _copy_ai_response(response, cache_hit=False),
    }
    _AI_RESPONSE_CACHE.move_to_end(cache_key)
    while len(_AI_RESPONSE_CACHE) > _AI_RESPONSE_CACHE_LIMIT:
        _AI_RESPONSE_CACHE.popitem(last=False)
    return _copy_ai_response(response, cache_hit=False)


def ai_response_cache_status() -> dict:
    return {
        "ai_response_cache": len(_AI_RESPONSE_CACHE),
        "ai_response_cache_limit": _AI_RESPONSE_CACHE_LIMIT,
    }


def clear_ai_response_cache() -> None:
    _AI_RESPONSE_CACHE.clear()


class OpenAICompatibleClient:
    def list_models(self, provider_config: dict) -> list[str]:
        base_url = _normalize_openai_base_url(
            provider_config.get("base_url", ""),
            provider_config.get("api_mode", "自动"),
        )
        if not base_url:
            return []
        payload = _json_http_request(
            "GET",
            _url_join(base_url, "models"),
            provider_config.get("api_key", ""),
            timeout=int(provider_config.get("timeout") or 30),
        )
        data = payload.get("data", [])
        models = []
        for item in data:
            model_id = item.get("id") if isinstance(item, dict) else str(item)
            if model_id:
                models.append(str(model_id))
        return sorted(dict.fromkeys(models))

    def chat_completion(self, provider_config: dict, messages: list[dict]) -> dict:
        base_url = _normalize_openai_base_url(
            provider_config.get("base_url", ""),
            provider_config.get("api_mode", "自动"),
        )
        if not base_url:
            raise ValueError("AI服务商URL为空。")
        model = str(provider_config.get("model") or "").strip()
        if not model:
            raise ValueError("AI模型为空。")
        body = {
            "model": model,
            "messages": messages,
            "temperature": float(provider_config.get("temperature", 0.35)),
            "max_tokens": int(provider_config.get("max_tokens", 1200)),
        }
        stream = bool(provider_config.get("stream", False))
        if stream:
            body["stream"] = True
        service_tier = str(provider_config.get("service_tier") or "").strip()
        if service_tier and service_tier != "auto":
            body["service_tier"] = service_tier
        for penalty_key in ("presence_penalty", "frequency_penalty", "top_p"):
            if penalty_key in provider_config and provider_config.get(penalty_key) is not None:
                body[penalty_key] = float(provider_config.get(penalty_key))
        reasoning_mode = str(provider_config.get("reasoning_mode") or "关闭")
        if reasoning_mode == "开启":
            effort = str(provider_config.get("reasoning_effort") or "").strip()
            if effort:
                body["reasoning_effort"] = effort
        url = _url_join(base_url, "chat/completions")
        timeout = int(provider_config.get("timeout") or 30)
        retry_count = _safe_retry_count(provider_config.get("retry_count", 1))
        retry_backoff = _safe_retry_backoff(provider_config.get("retry_backoff", 0))
        stream_fallback = bool(provider_config.get("stream_fallback", True))
        errors = []
        attempts = 0
        fallback_used = False
        current_body = dict(body)
        current_stream = stream

        for attempt in range(1, retry_count + 1):
            attempts = attempt
            try:
                if current_stream:
                    response = _stream_json_http_request(
                        url,
                        provider_config.get("api_key", ""),
                        current_body,
                        timeout=timeout,
                    )
                    if not str(response.get("content") or "").strip():
                        raise RuntimeError("AI流式接口返回为空")
                    retry_meta = {
                        "attempts": attempts,
                        "max_attempts": retry_count,
                        "errors": errors,
                        "stream_fallback": fallback_used,
                        "final_stream": True,
                    }
                    return _attach_retry_metadata(response, retry_meta)
                payload = _json_http_request(
                    "POST",
                    url,
                    provider_config.get("api_key", ""),
                    payload=current_body,
                    timeout=timeout,
                )
                choices = payload.get("choices") or []
                content = ""
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message") or {}
                    content = str(message.get("content") or choices[0].get("text") or "")
                retry_meta = {
                    "attempts": attempts,
                    "max_attempts": retry_count,
                    "errors": errors,
                    "stream_fallback": fallback_used,
                    "final_stream": False,
                }
                return _attach_retry_metadata({"content": content, "raw": payload}, retry_meta)
            except Exception as exc:
                message = str(exc)
                errors.append(message)
                can_retry = attempt < retry_count and _is_retryable_ai_error(exc)
                if current_stream and stream_fallback and _is_retryable_ai_error(exc):
                    current_stream = False
                    current_body = dict(current_body)
                    current_body.pop("stream", None)
                    fallback_used = True
                    can_retry = True
                if not can_retry:
                    raise
                if retry_backoff > 0:
                    time.sleep(retry_backoff * (2 ** max(0, attempt - 1)))

        raise RuntimeError("AI接口请求失败: 重试耗尽。")

    def embeddings(self, provider_config: dict, texts) -> dict:
        base_url = _normalize_openai_base_url(
            provider_config.get("base_url", ""),
            provider_config.get("api_mode", "自动"),
        )
        if not base_url:
            raise ValueError("Embedding服务商URL为空。")
        model = str(provider_config.get("model") or "").strip()
        if not model:
            raise ValueError("Embedding模型为空。")
        if isinstance(texts, str):
            inputs = [texts]
        else:
            inputs = [str(item or "") for item in texts or []]
        body = {
            "model": model,
            "input": inputs,
        }
        payload = _json_http_request(
            "POST",
            _url_join(base_url, "embeddings"),
            provider_config.get("api_key", ""),
            payload=body,
            timeout=int(provider_config.get("timeout") or 30),
        )
        embeddings = []
        for item in payload.get("data") or []:
            if isinstance(item, dict) and isinstance(item.get("embedding"), list):
                embeddings.append(item["embedding"])
        return {"embeddings": embeddings, "raw": payload}


def _extract_json_object(text: str) -> dict:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return {"natural_language": raw, "analysis": {}}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"natural_language": raw, "analysis": {}}


def _tag_ai_context_item(term: ResolvedTag, taxonomy_meta: dict | None = None) -> dict:
    taxonomy_id = str(term.taxonomy_id or "")
    domain = facet = group = leaf = ""
    parts = taxonomy_id.split(".")
    taxonomy_meta = taxonomy_meta or {}
    if taxonomy_meta:
        domain = str(taxonomy_meta.get("domain") or "")
        facet = str(taxonomy_meta.get("facet") or "")
        group = str(taxonomy_meta.get("group_key") or "")
        leaf = str(taxonomy_meta.get("leaf_key") or "")
    elif len(parts) >= 5:
        domain, facet, group, leaf = parts[1], parts[2], parts[3], ".".join(parts[4:])
    elif len(parts) >= 4:
        domain, facet, group, leaf = parts[0], parts[1], parts[2], ".".join(parts[3:])
    return {
        "query": term.query,
        "tag": term.tag,
        "label_zh": term.label if term.label != term.tag else "",
        "category": term.category,
        "semantic_category": term.semantic_category,
        "taxonomy_id": taxonomy_id,
        "taxonomy": {
            "domain": domain,
            "facet": facet,
            "group": group,
            "leaf": leaf,
            "domain_zh": taxonomy_domain_label(domain) if domain else "",
            "facet_zh": taxonomy_facet_label(domain, facet) if domain and facet else "",
            "label_zh": str(taxonomy_meta.get("label_zh") or ""),
            "label_en": str(taxonomy_meta.get("label_en") or ""),
            "safety_scope": str(taxonomy_meta.get("safety_scope") or ""),
            "prompt_role": str(taxonomy_meta.get("prompt_role") or ""),
        },
        "post_count": term.post_count,
        "is_nsfw": term.is_nsfw,
        "source": term.source,
    }


def _build_positive_tag_context(tags: str, db=None) -> dict:
    raw_tags = split_tag_text(tags)
    context = {
        "raw_tags": raw_tags,
        "normalized_tags": [],
        "resolved_tags": [],
        "unresolved_tags": [],
        "taxonomy_groups": {},
        "has_nsfw": False,
        "db_used": False,
    }
    db_path = optional_danbooru_db_path("", db)
    if not db_path or not raw_tags:
        context["unresolved_tags"] = [strip_prompt_weight(item) for item in raw_tags]
        return context

    dictionary = DanbooruDictionary(db_path)
    normalized_tags = [
        parse_tag_option(strip_prompt_weight(item), db_path=db_path)
        for item in raw_tags
    ]
    context["normalized_tags"] = [item for item in normalized_tags if item]
    resolved = dictionary.resolve_terms(
        ", ".join(context["normalized_tags"]),
        match_mode="exact",
        allow_nsfw=True,
        keep_unresolved=True,
        min_post_count=0,
        limit_per_term=1,
    )
    taxonomy_meta = dictionary.taxonomy_metadata_for_ids(
        [term.taxonomy_id for term in resolved if term.taxonomy_id]
    )
    context["db_used"] = True
    for term in resolved[:120]:
        item = _tag_ai_context_item(term, taxonomy_meta.get(term.taxonomy_id or ""))
        if term.source in {"unresolved", "missing_dictionary"}:
            context["unresolved_tags"].append(term.query)
        else:
            context["resolved_tags"].append(item)
            context["has_nsfw"] = context["has_nsfw"] or bool(term.is_nsfw)
            group_key = term.taxonomy_id or term.semantic_category or "uncategorized"
            bucket = context["taxonomy_groups"].setdefault(
                group_key,
                {
                    "taxonomy_id": term.taxonomy_id,
                    "semantic_category": term.semantic_category,
                    "tags": [],
                    "label_zh": item["taxonomy"]["label_zh"]
                    or item["taxonomy"]["facet_zh"]
                    or item["taxonomy"]["domain_zh"],
                },
            )
            bucket["tags"].append(term.tag)
    return context


AI_ENRICHMENT_MODES = [
    "自然语言补充",
    "Anima完整自然语言",
    "Anima训练标注Caption",
    "场景导演描述",
    "Tag约束全面扩写",
]


def _safe_sentence_range(min_sentences, max_sentences, detail_level: str = "标准") -> tuple[int, int]:
    default_min = 1 if str(detail_level or "") == "精炼" else 2
    try:
        minimum = int(min_sentences)
    except (TypeError, ValueError):
        minimum = default_min
    try:
        maximum = int(max_sentences)
    except (TypeError, ValueError):
        maximum = max(3, minimum)
    minimum = max(1, min(8, minimum))
    maximum = max(minimum, min(12, maximum))
    return minimum, maximum


def _positive_enrichment_mode_requirements(mode: str, min_sentences: int, max_sentences: int) -> list[str]:
    selected = str(mode or "自然语言补充")
    base = [
        "已有 tag 是锁定输入，只能理解和扩写；不要改写、删除、替换或新增 tag。",
        "自然语言必须严格基于 locked_tags 和 danbooru_context.generation_plan.sanitized_prompt。",
        f"自然语言至少 {min_sentences} 句，最多 {max_sentences} 句。",
        "描述人物、构图、视角、动作、位置关系、场景、光影和材质时要具体。",
        "不要把 tag 列表机械翻译成句子，要组织成可直接用于 Anima 正向提示词的画面描述。",
    ]
    if selected == "Anima完整自然语言":
        return [
            *base,
            "输出完整 Anima 自然语言段，适合与原始 tag 一起进入正向提示词。",
            "优先补足 tag 没有表达清楚的空间关系、镜头意图、主体朝向和背景气氛。",
        ]
    if selected == "Anima训练标注Caption":
        return [
            *base,
            "输出接近训练标注 caption 的自然语言，简洁、客观、可学习。",
            "保留画面事实，不写营销式形容，不加入不存在的角色或物件。",
        ]
    if selected == "场景导演描述":
        return [
            *base,
            "必须按前景、中景、背景组织自然语言，写清主体位置、镜头角度、视线方向、环境层次、光源方向和画面气氛。",
            "必须主动补足 rich background：环境物件、墙面/窗户/装饰、材质、空气感、冷暖光关系和景深层次。",
            "自然语言应像场景导演说明，而不是 tag 翻译；让背景成为画面叙事的一部分。",
            "不要偏离角色既有外观和服装 tag。",
        ]
    if selected == "Tag约束全面扩写":
        return [
            *base,
            "tag 是硬约束但不是唯一信息源；可以在不冲突 tag 的前提下自主补全完整画面设计。",
            "必须覆盖主体、姿态动作、外观服装、构图镜头、前景/中景/背景、场景地点、背景物件、光影、氛围、色彩、渲染风格和叙事意图。",
            "不得输出新 tag，不新增 tag 列表；只能输出自然语言，让自然语言补足 tag 未明说但合理的画面细节。",
            "如果存在 simple background / white background 等限制背景的 tag，背景扩写必须克制；如果存在 detailed background / scenery / indoors / outdoors，则应主动丰富背景。",
            "自然语言必须形成完整图片说明，而不是 tag 翻译或短 caption。",
        ]
    return [
        "Preserve the meaning of the input tags.",
        "Add only useful visual natural language.",
        "Avoid contradicting the tags.",
        "Ignore dropped_tags and suppressed_tags when writing natural language.",
        "Do not mention any blocked_natural_language_terms.",
        "If the tags are too sparse or strange, write a conservative cohesive visual phrase instead of inventing details.",
        "Use taxonomy and Chinese labels to infer visual intent when they are available.",
        "Prefer one concise natural-language phrase over repeating tags one by one.",
        "Keep the sentence suitable for image generation positive prompts.",
        "已有 tag 是锁定输入，只能理解和扩写；不要改写、删除、替换或新增 tag。",
    ]


def _build_positive_enrichment_messages(
    tags: str,
    context: str,
    language: str,
    detail_level: str,
    tag_context: dict | None = None,
    enrichment_mode: str = "自然语言补充",
    min_sentences: int = 1,
    max_sentences: int = 3,
) -> list[dict]:
    mode = str(enrichment_mode or "自然语言补充")
    sentence_min, sentence_max = _safe_sentence_range(min_sentences, max_sentences, detail_level)
    return [
        {
            "role": "system",
            "content": (
                "You are a professional anime image prompt analyst. "
                "Analyze Danbooru tags, their taxonomy, translations, safety flags, and visual roles. "
                "Write natural-language positive prompt text that improves character, scene, composition, "
                "material, mood, spatial relationship, and camera readability. "
                "For scene director mode, design a rich background with foreground, midground, background, "
                "environment props, lighting, atmosphere, texture, depth, and visual storytelling. "
                "For Tag-constrained full expansion mode, create a complete image design from locked tags: "
                "subject, pose, appearance, outfit/materials, camera, foreground, midground, background, setting, "
                "props, lighting, atmosphere, color design, rendering style, and narrative intent; do not output new tags. "
                "Use danbooru_context.generation_plan.sanitized_prompt as the only source for natural language. "
                "Existing tags are locked: never rewrite, remove, replace, reorder, or add tags in the tag list. "
                "Never describe dropped_tags, suppressed_tags, blocked_natural_language_terms, score/rating tags, "
                "or mutually conflicting states that were removed by the plan. "
                "Do not remove or rewrite existing tags. Do not add negative prompt content. "
                "Do not add explicit NSFW content unless the input tags already contain NSFW context. "
                "Return only JSON with keys: natural_language, analysis, added_focus."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "tags": str(tags or ""),
                    "locked_tags": str(tags or ""),
                    "context": str(context or ""),
                    "output_language": str(language or "中文"),
                    "detail_level": str(detail_level or "精炼"),
                    "enrichment_mode": mode,
                    "sentence_range": {"min": sentence_min, "max": sentence_max},
                    "danbooru_context": tag_context or {},
                    "requirements": _positive_enrichment_mode_requirements(mode, sentence_min, sentence_max),
                },
                ensure_ascii=False,
            ),
        },
    ]


AI_TAG_GENERATION_MODES = [
    "规则随机",
    "AI协同选择",
    "AI协同选择+规则兜底",
    "AI意图定向选择",
    "AI意图定向选择+规则兜底",
]

AI_HIGH_FREEDOM_GENERIC_TAGS = {
    "full_body",
    "cowboy_shot",
    "upper_body",
    "portrait",
    "close-up",
    "close_up",
    "indoors",
    "outdoors",
    "outside",
    "simple_background",
    "white_background",
    "transparent_background",
    "day",
    "weather",
    "flower",
    "flowers",
    "comic",
    "anime_coloring",
    "traditional_media",
    "digital_media",
    "standing",
    "sitting",
    "smile",
}

AI_HIGH_FREEDOM_GENERIC_BY_FIELD = {
    "scene_camera": {
        "full_body",
        "cowboy_shot",
        "upper_body",
        "portrait",
        "close-up",
        "close_up",
    },
    "scene_location": {
        "indoors",
        "outdoors",
        "outside",
        "simple_background",
        "white_background",
        "transparent_background",
    },
    "scene_time_weather": {"day", "weather"},
    "scene_object": {"flower", "flowers"},
    "scene_visual_style": {"comic", "anime_coloring", "traditional_media", "digital_media"},
    "pose_posture": {"standing", "sitting"},
    "face_expression": {"smile"},
}

AI_RAG_MODES = ["关闭", "轻量语义", "示例增强", "混合增强"]


def _clamp_float(value, default: float = 0.35, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _ai_candidate_pool_size(per_field_count: int, freedom: float) -> int:
    safe_count = max(1, int(per_field_count or 1))
    free = _clamp_float(freedom)
    low = max(12, safe_count * 12)
    high = max(low + 1, min(180, 80 + safe_count * 36))
    return int(round(low + (high - low) * free))


def _ai_candidate_expansion_enabled(freedom: float) -> bool:
    return _clamp_float(freedom) >= 0.65


def _ai_selection_provider_config(provider: dict, freedom: float) -> dict:
    config = dict(provider or {})
    base_temperature = float(config.get("temperature", 0.35) or 0.35)
    free = _clamp_float(freedom)
    config["temperature"] = min(2.0, max(0.0, base_temperature + free * 0.95))
    config["max_tokens"] = max(256, int(config.get("max_tokens", 900) or 900))
    if free >= 0.65:
        config.setdefault("presence_penalty", min(1.2, 0.35 + free * 0.65))
        config.setdefault("frequency_penalty", min(1.0, 0.25 + free * 0.50))
    return config


def _field_fill_allowed(current: str, strategy: str) -> bool:
    return str(strategy or "只补空字段") == "追加到字段" or not str(current or "").strip()


def _format_ai_selection_display(items: list[dict]) -> str:
    return join_tag_display_parts(
        [
            format_tag_display_parts(item.get("tag", ""), item.get("label", ""))
            for item in items
        ],
        dedupe=True,
    )


def _merge_ai_selection_value(existing: str, selected_items: list[dict], *, append: bool) -> str:
    selected_text = _format_ai_selection_display(selected_items)
    if not selected_text:
        return str(existing or "")
    if append:
        return join_tag_display_parts([existing, selected_text], dedupe=True)
    return str(existing or "").strip() or selected_text


def _items_excluding_taxonomy_blacklist(items: list[dict], taxonomy_blacklist) -> list[dict]:
    blocked = normalize_taxonomy_blacklist(taxonomy_blacklist)
    if not blocked:
        return list(items)
    result = []
    for item in items:
        taxonomy_id = str(item.get("taxonomy_id") or "")
        if any(taxonomy_id == entry or taxonomy_id.startswith(f"{entry}.") for entry in blocked):
            continue
        result.append(item)
    return result


def _dedupe_candidate_items(items: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for item in items or []:
        tag = str(item.get("tag") or "").strip()
        key = normalize_tag_name(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _with_ai_candidate_source(items: list[dict], source: str) -> list[dict]:
    result = []
    label = {"exploratory": "探索型", "popular": "热门", "expanded": "扩展候选"}.get(source, source)
    for index, item in enumerate(items or []):
        candidate = dict(item)
        candidate["candidate_source"] = source
        candidate["candidate_source_label"] = label
        candidate["candidate_source_rank"] = index + 1
        result.append(candidate)
    return result


def _post_count_for_candidate(item: dict) -> int:
    try:
        return int(item.get("post_count") or 0)
    except (TypeError, ValueError):
        return 0


def _ai_selection_run_id(seed: int, freedom: float) -> str:
    safe_seed = int(seed or 0)
    if safe_seed:
        return f"seed-{safe_seed}-freedom-{_clamp_float(freedom):.2f}"
    return f"auto-{random.SystemRandom().getrandbits(64):016x}"


def _ai_effective_min_post_count(min_post_count: int, freedom: float) -> int:
    requested = max(0, int(min_post_count or 0))
    free = _clamp_float(freedom)
    if requested > 0 or free < 0.35:
        return requested
    if free >= 0.85:
        return 100
    if free >= 0.65:
        return 50
    return 25


def _generic_ai_tag_keys(field: str) -> set[str]:
    tags = set(AI_HIGH_FREEDOM_GENERIC_TAGS)
    tags.update(AI_HIGH_FREEDOM_GENERIC_BY_FIELD.get(str(field or ""), set()))
    return {normalize_tag_name(tag) for tag in tags}


def _split_generic_ai_items(field: str, items: list[dict]) -> tuple[list[dict], list[dict]]:
    generic = _generic_ai_tag_keys(field)
    specific = []
    generic_items = []
    for item in items or []:
        key = normalize_tag_name(item.get("tag", ""))
        if key in generic:
            generic_items.append(item)
        else:
            specific.append(item)
    return specific, generic_items


def _shuffle_candidate_items(items: list[dict], seed: int) -> list[dict]:
    result = list(items or [])
    rng = random.Random(int(seed)) if int(seed or 0) else random.SystemRandom()
    rng.shuffle(result)
    return result


def _interleave_candidate_items(primary: list[dict], secondary: list[dict], primary_stride: int = 2) -> list[dict]:
    result = []
    primary_index = 0
    secondary_index = 0
    stride = max(1, int(primary_stride or 1))
    while primary_index < len(primary) or secondary_index < len(secondary):
        for _ in range(stride):
            if primary_index >= len(primary):
                break
            result.append(primary[primary_index])
            primary_index += 1
        if secondary_index < len(secondary):
            result.append(secondary[secondary_index])
            secondary_index += 1
    return result


def _order_ai_candidate_items(
    hot_items: list[dict],
    random_items: list[dict],
    freedom: float,
    *,
    field: str = "",
    seed: int = 0,
) -> list[dict]:
    free = _clamp_float(freedom)
    popular = _with_ai_candidate_source(hot_items, "popular")
    exploratory = _with_ai_candidate_source(random_items, "exploratory")

    if free >= 0.85:
        exploratory, generic_exploratory = _split_generic_ai_items(field, exploratory)
        popular, generic_popular = _split_generic_ai_items(field, popular)
        viable_exploratory = [
            item for item in exploratory
            if _post_count_for_candidate(item) >= _ai_effective_min_post_count(0, free)
        ] or exploratory
        viable_exploratory = _shuffle_candidate_items(viable_exploratory, seed)
        popular = _shuffle_candidate_items(popular, seed + 1009 if seed else 0)
        generic_tail = []
        if len(viable_exploratory) + len(popular) < 8:
            generic_tail = _shuffle_candidate_items([*generic_exploratory, *generic_popular], seed + 2017 if seed else 0)
        return _dedupe_candidate_items([*viable_exploratory, *popular, *generic_tail])
    if free >= 0.65:
        exploratory, generic_exploratory = _split_generic_ai_items(field, exploratory)
        popular, generic_popular = _split_generic_ai_items(field, popular)
        exploratory = _shuffle_candidate_items(exploratory, seed)
        popular = _shuffle_candidate_items(popular, seed + 1009 if seed else 0)
        return _dedupe_candidate_items(
            [
                *_interleave_candidate_items(exploratory, popular, primary_stride=3),
                *generic_exploratory,
                *generic_popular,
            ]
        )
    if free >= 0.35:
        return _dedupe_candidate_items(_interleave_candidate_items(popular, exploratory, primary_stride=2))
    return _dedupe_candidate_items([*popular, *exploratory])


def _ai_candidates_for_field(
    dictionary,
    field: str,
    *,
    count: int,
    seed: int,
    allow_nsfw: bool,
    min_post_count: int,
    freedom: float,
    blacklist=None,
    taxonomy_blacklist=None,
) -> list[dict]:
    pool_size = _ai_candidate_pool_size(count, freedom)
    free = _clamp_float(freedom)
    random_count = int(round(pool_size * (0.12 + free * 0.78)))
    hot_count = max(1, pool_size - random_count)
    ai_min_post_count = _ai_effective_min_post_count(min_post_count, free)

    hot_payload = dictionary.option_records_for_field(
        field,
        allow_nsfw=allow_nsfw,
        min_post_count=ai_min_post_count,
        limit=hot_count,
        blacklist=blacklist,
    )
    hot_items = hot_payload.get("items", []) if isinstance(hot_payload, dict) else []
    random_items = dictionary.random_options_for_field(
        field,
        count=max(0, random_count),
        seed=seed,
        allow_nsfw=allow_nsfw,
        min_post_count=ai_min_post_count,
        blacklist=blacklist,
        taxonomy_blacklist=taxonomy_blacklist,
        max_count=200,
    )
    if ai_min_post_count > max(0, int(min_post_count or 0)) and not random_items:
        random_items = dictionary.random_options_for_field(
            field,
            count=max(0, random_count),
            seed=seed,
            allow_nsfw=allow_nsfw,
            min_post_count=max(0, int(min_post_count or 0)),
            blacklist=blacklist,
            taxonomy_blacklist=taxonomy_blacklist,
            max_count=200,
        )
    merged = _order_ai_candidate_items(hot_items, random_items, free, field=field, seed=seed)
    merged = _items_excluding_taxonomy_blacklist(merged, taxonomy_blacklist)
    return merged[:pool_size]


def _field_taxonomy_summary(field: str) -> list[dict]:
    spec = danbooru_field_spec(field) or {}
    items = []
    for taxonomy_id in spec.get("taxonomy_ids", []) or []:
        text = str(taxonomy_id or "").strip()
        if not text:
            continue
        parts = text.split(".")
        items.append(
            {
                "taxonomy_id": text,
                "domain": parts[1] if len(parts) > 1 else "",
                "facet": parts[2] if len(parts) > 2 else "",
                "group": parts[3] if len(parts) > 3 else "",
                "leaf": parts[4] if len(parts) > 4 else "",
            }
        )
    for category in spec.get("categories", []) or []:
        if not isinstance(category, dict):
            continue
        items.append(
            {
                "taxonomy_id": f"category:{category.get('category')}",
                "domain": str(category.get("semantic_category") or "category"),
                "facet": str(category.get("semantic_category") or "category"),
                "group": "category",
                "leaf": str(category.get("semantic_category") or category.get("category") or ""),
            }
        )
    return items


def _candidate_payload_items(candidates: list[dict]) -> list[dict]:
    return [
        {
            "tag": item.get("tag", ""),
            "label_zh": item.get("label", ""),
            "taxonomy_id": item.get("taxonomy_id", ""),
            "semantic_category": item.get("semantic_category", ""),
            "is_nsfw": bool(item.get("is_nsfw", False)),
            "candidate_source": item.get("candidate_source", ""),
            "candidate_source_label": item.get("candidate_source_label", ""),
        }
        for item in candidates
    ]


def _build_ai_field_payload(
    *,
    field: str,
    label: str,
    max_select_count: int,
    min_post_count: int,
    candidates: list[dict],
    include_taxonomy_scope: bool,
) -> dict:
    payload = {
        "field": field,
        "label": label,
        "max_select_count": max_select_count,
        "min_post_count": min_post_count,
        "candidate_count": len(candidates),
        "candidates": _candidate_payload_items(candidates),
    }
    if include_taxonomy_scope:
        payload["enabled_taxonomy_scope"] = _field_taxonomy_summary(field)
    return payload


def _safe_positive_int(value, default: int = 0, maximum: int | None = None) -> int:
    try:
        number = max(0, int(value if value is not None else default))
    except (TypeError, ValueError):
        number = max(0, int(default or 0))
    if maximum is not None:
        number = min(number, int(maximum))
    return number


def _normalize_ai_rag_mode(value: str) -> str:
    mode = str(value or "关闭").strip()
    return mode if mode in AI_RAG_MODES else "关闭"


def _ai_rag_query_text(*parts: str) -> str:
    text = " ".join(str(part or "").strip() for part in parts if str(part or "").strip())
    text = re.sub(r"[，。；、]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200]


def _build_ai_rag_context(
    *,
    dictionary,
    fields_to_fill: list[str],
    candidate_by_field: dict[str, list[dict]],
    field_labels: dict[str, str],
    mode: str,
    candidate_count: int,
    example_count: int,
    previous_context: str,
    intent_text: str,
    seed: int,
    allow_nsfw: bool,
    effective_min_post_counts: dict[str, int],
    blacklist=None,
    taxonomy_blacklist=None,
) -> dict:
    rag_mode = _normalize_ai_rag_mode(mode)
    safe_candidate_count = _safe_positive_int(candidate_count, default=12, maximum=200)
    safe_example_count = _safe_positive_int(example_count, default=3, maximum=20)
    result = {
        "enabled": rag_mode != "关闭" and safe_candidate_count > 0,
        "mode": rag_mode,
        "candidate_count": safe_candidate_count,
        "example_count": safe_example_count,
        "scope": "current_enabled_fields_only",
        "fields": [],
        "field_reference_counts": {},
        "query": "",
    }
    if not result["enabled"]:
        return result

    query = _ai_rag_query_text(intent_text, previous_context)
    result["query"] = query
    candidate_keys_by_field = {
        field: {normalize_tag_name(item.get("tag", "")) for item in candidate_by_field.get(field, [])}
        for field in fields_to_fill
    }
    base_seed = int(seed or 0)
    for index, field in enumerate(fields_to_fill):
        references = []
        fetch_count = max(safe_candidate_count, safe_candidate_count * 4)
        for attempt_query in ([query] if query else []):
            if not attempt_query:
                continue
            references = dictionary.random_options_for_field(
                field,
                count=fetch_count,
                seed=base_seed + 3000 + index if base_seed else 0,
                allow_nsfw=allow_nsfw,
                min_post_count=effective_min_post_counts.get(field, 0),
                query=attempt_query,
                blacklist=blacklist,
                taxonomy_blacklist=taxonomy_blacklist,
                max_count=max(200, fetch_count * 4),
            )
            if references:
                break
        if not references:
            references = dictionary.random_options_for_field(
                field,
                count=fetch_count,
                seed=base_seed + 4000 + index if base_seed else 0,
                allow_nsfw=allow_nsfw,
                min_post_count=effective_min_post_counts.get(field, 0),
                blacklist=blacklist,
                taxonomy_blacklist=taxonomy_blacklist,
                max_count=max(200, fetch_count * 4),
            )
        candidate_keys = candidate_keys_by_field.get(field, set())
        filtered = [
            item
            for item in _dedupe_candidate_items(references)
            if normalize_tag_name(item.get("tag", "")) not in candidate_keys
        ][:safe_candidate_count]
        if not filtered:
            continue
        field_payload = {
            "field": field,
            "label": field_labels.get(field, field),
            "references": _candidate_payload_items(filtered),
        }
        if rag_mode in {"示例增强", "混合增强"} and safe_example_count > 0:
            field_payload["examples"] = [
                {
                    "tags": [item.get("tag", "")],
                    "description": f"{item.get('tag', '').replace('_', ' ')} can be used as a visual reference within {field_labels.get(field, field)}.",
                }
                for item in filtered[:safe_example_count]
            ]
        result["fields"].append(field_payload)
        result["field_reference_counts"][field] = len(filtered)
    result["enabled"] = bool(result["fields"])
    return result


def _taxonomy_id_allowed_for_field(field: str, taxonomy_id: str) -> bool:
    text = str(taxonomy_id or "").strip()
    if not text:
        return False
    spec = danbooru_field_spec(field) or {}
    allowed_ids = [str(item).strip() for item in spec.get("taxonomy_ids", []) if str(item).strip()]
    if text.startswith("category:"):
        return False
    return any(text == item or text.startswith(f"{item}.") for item in allowed_ids)


def _extract_ai_expand_requests(parsed: dict) -> list[dict]:
    containers = []
    for key in ("expand_requests", "candidate_requests", "needs_more_candidates"):
        value = parsed.get(key) if isinstance(parsed, dict) else None
        if isinstance(value, list):
            containers.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            containers.append(value)
    if isinstance(parsed.get("fields"), list):
        for item in parsed["fields"]:
            if isinstance(item, dict) and item.get("request_more_candidates"):
                containers.append(item)
    return containers


def _ai_expand_candidates_for_field(
    dictionary,
    field: str,
    request: dict,
    *,
    seed: int,
    allow_nsfw: bool,
    min_post_count: int,
    freedom: float,
    blacklist=None,
    taxonomy_blacklist=None,
) -> list[dict]:
    free = _clamp_float(freedom)
    count = max(1, min(200, int(request.get("count") or 80)))
    requested_taxonomy_ids = [
        str(item or "").strip()
        for item in request.get("taxonomy_ids", request.get("taxonomy_id", [])) or []
        if str(item or "").strip()
    ]
    allowed_taxonomy_ids = [
        taxonomy_id for taxonomy_id in requested_taxonomy_ids
        if _taxonomy_id_allowed_for_field(field, taxonomy_id)
    ]
    query = str(request.get("query") or request.get("keyword") or "").strip()
    request_min_post = request.get("min_post_count", min_post_count)
    try:
        effective_min_post = max(
            _ai_effective_min_post_count(min_post_count, free),
            max(0, int(request_min_post or 0)),
        )
    except (TypeError, ValueError):
        effective_min_post = _ai_effective_min_post_count(min_post_count, free)

    if allowed_taxonomy_ids:
        raw_items = []
        for offset, taxonomy_id in enumerate(allowed_taxonomy_ids[:8]):
            raw_items.extend(
                dictionary.random_options_for_field(
                    field,
                    taxonomy_id=taxonomy_id,
                    count=max(1, count // max(1, len(allowed_taxonomy_ids[:8]))),
                    seed=seed + offset if seed else 0,
                    allow_nsfw=allow_nsfw,
                    min_post_count=effective_min_post,
                    query=query,
                    blacklist=blacklist,
                    taxonomy_blacklist=taxonomy_blacklist,
                    max_count=200,
                )
            )
        raw_items = [
            item for item in raw_items
            if any(
                str(item.get("taxonomy_id") or "") == taxonomy_id
                or str(item.get("taxonomy_id") or "").startswith(f"{taxonomy_id}.")
                for taxonomy_id in allowed_taxonomy_ids
            )
        ]
        return _with_ai_candidate_source(_dedupe_candidate_items(raw_items), "expanded")

    items = dictionary.random_options_for_field(
        field,
        count=count,
        seed=seed,
        allow_nsfw=allow_nsfw,
        min_post_count=effective_min_post,
        query=query,
        blacklist=blacklist,
        taxonomy_blacklist=taxonomy_blacklist,
        max_count=200,
    )
    return _with_ai_candidate_source(items, "expanded")


def _apply_ai_candidate_expansion_requests(
    *,
    dictionary,
    parsed: dict,
    fields_to_fill: list[str],
    candidate_by_field: dict[str, list[dict]],
    effective_min_post_counts: dict[str, int],
    seed: int,
    allow_nsfw: bool,
    freedom: float,
    blacklist=None,
    taxonomy_blacklist=None,
) -> dict:
    allowed_fields = set(fields_to_fill)
    result = {
        "enabled": _ai_candidate_expansion_enabled(freedom),
        "used": False,
        "requests": [],
        "ignored_requests": [],
        "added_counts": {},
    }
    if not result["enabled"]:
        return result

    raw_requests = _extract_ai_expand_requests(parsed)
    base_seed = int(seed or 0)
    for index, request in enumerate(raw_requests[:12]):
        field = str(request.get("field") or request.get("id") or "").strip()
        if field not in allowed_fields:
            ignored = dict(request)
            ignored["field"] = field
            ignored["reason"] = "field_not_enabled_for_current_node"
            result["ignored_requests"].append(ignored)
            continue
        before = len(candidate_by_field.get(field, []))
        expanded = _ai_expand_candidates_for_field(
            dictionary,
            field,
            request,
            seed=base_seed + 100 + index if base_seed else 0,
            allow_nsfw=allow_nsfw,
            min_post_count=effective_min_post_counts.get(field, 0),
            freedom=freedom,
            blacklist=blacklist,
            taxonomy_blacklist=taxonomy_blacklist,
        )
        if not expanded:
            continue
        candidate_by_field[field] = _items_excluding_taxonomy_blacklist(
            _dedupe_candidate_items([*expanded, *candidate_by_field.get(field, [])]),
            taxonomy_blacklist,
        )[:1500]
        added = max(0, len(candidate_by_field[field]) - before)
        accepted = dict(request)
        accepted["field"] = field
        accepted["added_count"] = added
        result["requests"].append(accepted)
        result["added_counts"][field] = result["added_counts"].get(field, 0) + added
        result["used"] = True
    return result


def _ai_selection_freedom_requirement(freedom: float) -> str:
    free = _clamp_float(freedom)
    if free >= 0.85:
        return (
            "AI自由度高：优先从 candidate_source=exploratory 的探索型候选中选择，"
            "尤其可选长尾候选；除非明显冲突，不要默认选择最常见 tag。"
        )
    if free >= 0.65:
        return (
            "AI自由度较高：探索型候选应占主要选择比例，热门候选只用于保持角色、服装、场景的基本连贯。"
        )
    if free >= 0.35:
        return "AI自由度中等：在热门候选和探索型候选之间平衡，优先避免冲突。"
    return "AI自由度低：优先选择 candidate_source=popular 的热门候选，保持保守稳定。"


def _build_ai_tag_selection_messages(
    *,
    node_name: str,
    fields_payload: list[dict],
    previous_context: str,
    freedom: float,
    role_slot: str = "",
    role_label: str = "",
    selection_run_id: str = "",
    intent_text: str = "",
    intent_detail: str = "标准",
    rag_context: dict | None = None,
) -> list[dict]:
    free = _clamp_float(freedom)
    diversity_pressure = "high" if free >= 0.85 else "medium" if free >= 0.35 else "low"
    clean_intent = str(intent_text or "").strip()
    clean_intent_detail = str(intent_detail or "标准").strip() or "标准"
    intent_mode = bool(clean_intent)
    safe_rag_context = rag_context if isinstance(rag_context, dict) else {"enabled": False, "mode": "关闭", "fields": []}
    return [
        {
            "role": "system",
            "content": (
                "You select coherent Danbooru tags for one GALIAIS-Nodes prompt section. "
                "You must choose only from the provided candidates for each field. "
                "Use previous_context to keep continuity with earlier sections. "
                "Do not invent tags. Do not choose tags from disabled or missing fields. "
                "Higher freedom means each execution should explore a different coherent direction. "
                "When diversity pressure is high, avoid generic default popular tags unless every stronger option conflicts. "
                "If a field's candidates are not enough, request more candidates only for that same field. "
                "If user_intent is provided, use it as the main direction while still selecting only candidate tags. "
                "RAG context is reference-only and may help interpret fields, but it is not an allowed tag source. "
                "Natural language may expand the user intent and selected candidate tags, but must not rename or invent DB tags. "
                "Return strict JSON only: {\"fields\":{\"field_id\":[\"tag\"]},\"natural_language\":\"...\",\"expand_requests\":[...],\"analysis\":{...}}."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "node_name": str(node_name or ""),
                    "previous_context": str(previous_context or ""),
                    "role_slot": str(role_slot or ""),
                    "role_label": str(role_label or ""),
                    "freedom": free,
                    "diversity_pressure": diversity_pressure,
                    "selection_run_id": str(selection_run_id or ""),
                    "intent_mode": intent_mode,
                    "user_intent": clean_intent,
                    "intent_detail": clean_intent_detail,
                    "rag_context": safe_rag_context,
                    "fields": fields_payload,
                    "response_schema": {
                        "fields": "object mapping enabled field_id to selected candidate tag strings",
                        "natural_language": "optional string; required when intent_mode is true; describe the final visual direction using selected tags and user_intent",
                        "expand_requests": "optional list; only current enabled fields and taxonomy scope",
                        "analysis": "object with concise reasoning, conflicts avoided, and why selected tags fit user_intent",
                    },
                    "requirements": [
                        "每个字段只能从该字段 candidates 中选择 tag。",
                        "max_select_count 是最多可选数量，不是必须数量；请按画面合理性选择 0 到 max_select_count 个 tag，不要为了填满数量而堆砌。",
                        "不要输出 candidates 之外的 tag。",
                        "优先让当前字段与 previous_context 不冲突。",
                        "保留手动已填写字段，当前 payload 只包含允许自动填写的字段。",
                        "如果候选之间明显冲突，少选或不选也可以。",
                        "高自由度时不要总是选择 full_body、day、flower、comic、indoors、outdoors、simple_background 等泛用默认词；除非其他候选明显不适合。",
                        "同一 selection_run_id 代表一次独立抽样；每次请求都应基于当前 candidates 选择新的合理组合。",
                        "如果当前字段候选不够，可输出 expand_requests；每个请求只能包含当前 fields 中存在且启用的 field。",
                        "expand_requests 只能要求当前字段绑定划分内的更多候选，不要请求其他节点、其他字段或完整数据库。",
                        "expand_requests 可包含 field、taxonomy_ids、query、count、min_post_count；taxonomy_ids 必须来自 enabled_taxonomy_scope。",
                        "角色身份节点中，如果选择 identity_character 和 identity_work，必须严格匹配角色 tag 括号中的作品来源；例如 firefly_(honkai:_star_rail) 必须搭配 honkai:_star_rail，不能搭配 genshin_impact。",
                        "当 intent_mode=true 时，优先贴近 user_intent；如果候选不足，先用 expand_requests 在当前字段划分内请求更多候选。",
                        "当 intent_mode=true 时，natural_language 必须把 user_intent、previous_context 和已选 tag 组合成自然语言画面描述；不要把 candidates 外的 tag 写进 fields。",
                        "natural_language 可使用自然语言补足构图、氛围、空间层次和画面关系，但不得改变 fields 内保留的标准 tag。",
                        "rag_context 只用于理解语义、组合关系和自然语言扩写；rag_context.references/examples 中的 tag 不能直接写入 fields，除非它也存在于同字段 candidates。",
                        _ai_selection_freedom_requirement(freedom),
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]


def _selection_list_from_ai_payload(parsed: dict, field: str, label: str) -> list:
    containers = []
    if isinstance(parsed.get("fields"), dict):
        containers.append(parsed["fields"])
    if isinstance(parsed.get("selections"), dict):
        containers.append(parsed["selections"])
    if isinstance(parsed.get("selected_tags"), dict):
        containers.append(parsed["selected_tags"])
    for container in containers:
        if field in container:
            value = container.get(field)
        elif label in container:
            value = container.get(label)
        else:
            continue
        if isinstance(value, str):
            return split_tag_option_text(value)
        if isinstance(value, list):
            return value
        return [value]
    if isinstance(parsed.get("fields"), list):
        for item in parsed["fields"]:
            if not isinstance(item, dict):
                continue
            item_field = str(item.get("field") or item.get("id") or item.get("label") or "")
            if item_field not in {field, label}:
                continue
            value = item.get("tags") or item.get("selected") or item.get("items") or []
            if isinstance(value, str):
                return split_tag_option_text(value)
            if isinstance(value, list):
                return value
            return [value]
    return []


def _validate_ai_selected_items(raw_items, candidates: list[dict], count: int) -> tuple[list[dict], list[str]]:
    by_key = {normalize_tag_name(item.get("tag", "")): item for item in candidates}
    selected = []
    invalid = []
    seen = set()
    for raw in raw_items or []:
        if isinstance(raw, dict):
            raw_value = raw.get("tag") or raw.get("name") or raw.get("value") or raw.get("option") or ""
        else:
            raw_value = raw
        raw_text = str(raw_value or "").strip()
        key = normalize_tag_name(raw_text)
        tag = raw_text
        if key not in by_key:
            tag = parse_tag_option(raw_text).strip()
            key = normalize_tag_name(tag)
        if not key:
            continue
        if key not in by_key:
            invalid.append(tag)
            continue
        if key in seen:
            continue
        if len(selected) < max(1, int(count or 1)):
            seen.add(key)
            selected.append(by_key[key])
    return selected, invalid


def _character_implied_work_key(tag: str) -> str:
    text = normalize_tag_name(tag)
    if not text.endswith(")"):
        return ""
    match = re.search(r"\(([^()]*)\)\s*$", text)
    if not match:
        return ""
    work = normalize_tag_name(match.group(1))
    if not work or work in {"cosplay", "alternate_costume", "swimsuit"}:
        return ""
    return work


def _selected_or_current_work_keys(current_work: str, selected_work: list[dict]) -> set[str]:
    keys = set()
    for item in selected_work or []:
        key = normalize_tag_name(item.get("tag", ""))
        if key:
            keys.add(key)
    for token in split_tag_option_text(str(current_work or "")):
        parsed = parse_tag_option(token)
        key = normalize_tag_name(parsed)
        if key:
            keys.add(key)
    return keys


def _find_identity_work_candidate(candidate_by_field: dict[str, list[dict]], work_key: str) -> dict | None:
    if not work_key:
        return None
    for item in candidate_by_field.get("identity_work", []) or []:
        if normalize_tag_name(item.get("tag", "")) == work_key:
            return item
    return None


def _enforce_identity_character_work_pairing(
    values: dict[str, str],
    selected_by_field: dict[str, list[dict]],
    candidate_by_field: dict[str, list[dict]],
) -> dict:
    meta = {
        "checked": False,
        "required_work": "",
        "corrected_work": None,
        "rejected_characters": [],
    }
    selected_characters = selected_by_field.get("identity_character") or []
    if not selected_characters:
        return meta

    required_work = ""
    for item in selected_characters:
        required_work = _character_implied_work_key(item.get("tag", ""))
        if required_work:
            break
    if not required_work:
        return meta

    meta["checked"] = True
    meta["required_work"] = required_work
    selected_work = selected_by_field.get("identity_work") or []
    work_keys = _selected_or_current_work_keys(values.get("identity_work", ""), selected_work)

    current_work_is_manual = bool(str(values.get("identity_work", "") or "").strip())
    if current_work_is_manual and required_work not in work_keys:
        meta["rejected_characters"] = [item.get("tag", "") for item in selected_characters]
        selected_by_field.pop("identity_character", None)
        return meta

    if required_work in work_keys:
        if selected_work and normalize_tag_name(selected_work[0].get("tag", "")) != required_work:
            candidate = _find_identity_work_candidate(candidate_by_field, required_work)
            if candidate:
                meta["corrected_work"] = {
                    "from": selected_work[0].get("tag", ""),
                    "to": candidate.get("tag", ""),
                }
                selected_by_field["identity_work"] = [candidate]
        return meta

    candidate = _find_identity_work_candidate(candidate_by_field, required_work)
    if candidate:
        selected_by_field["identity_work"] = [candidate]
        meta["corrected_work"] = {
            "from": selected_work[0].get("tag", "") if selected_work else "",
            "to": candidate.get("tag", ""),
        }
        return meta

    if "identity_work" in values:
        meta["rejected_characters"] = [item.get("tag", "") for item in selected_characters]
        selected_by_field.pop("identity_character", None)
    return meta


def _fallback_random_ai_fields(
    values: dict[str, str],
    fields_to_fill: list[str],
    *,
    dictionary,
    effective_counts: dict[str, int],
    effective_min_post_counts: dict[str, int],
    strategy: str,
    seed: int,
    allow_nsfw: bool,
    blacklist=None,
    taxonomy_blacklist=None,
) -> tuple[dict[str, str], dict[str, list[dict]], dict[str, str]]:
    result = dict(values)
    fallback_items = {}
    fallback_field_values = {}
    append = str(strategy or "只补空字段") == "追加到字段"
    base_seed = int(seed or 0)
    for index, field in enumerate(fields_to_fill):
        if not _field_fill_allowed(result.get(field, ""), strategy):
            continue
        count = effective_counts.get(field, 0)
        if count <= 0:
            continue
        items = dictionary.random_options_for_field(
            field,
            count=count,
            seed=base_seed + index if base_seed else 0,
            allow_nsfw=allow_nsfw,
            min_post_count=effective_min_post_counts.get(field, 0),
            blacklist=blacklist,
            taxonomy_blacklist=taxonomy_blacklist,
        )
        if not items:
            continue
        result[field] = _merge_ai_selection_value(result.get(field, ""), items, append=append)
        fallback_items[field] = items
        fallback_field_values[field] = _format_ai_selection_display(items)
    return result, fallback_items, fallback_field_values


def ai_select_tags_for_fields(
    field_values: dict[str, str],
    *,
    db_path: str = "",
    provider=None,
    client=None,
    node_name: str = "",
    field_labels: dict[str, str] | None = None,
    previous_context: str = "",
    role_slot: str = "",
    role_label: str = "",
    strategy: str = "只补空字段",
    per_field_count: int = 1,
    per_field_counts=None,
    seed: int = 0,
    allow_nsfw: bool = False,
    min_post_count: int = 0,
    per_field_min_post_counts=None,
    freedom: float = 0.35,
    blacklist=None,
    taxonomy_blacklist=None,
    fallback_to_random: bool = True,
    intent_text: str = "",
    intent_detail: str = "标准",
    rag_mode: str = "关闭",
    rag_candidate_count: int = 12,
    rag_example_count: int = 3,
) -> tuple[dict[str, str], dict]:
    values = {key: str(value or "") for key, value in field_values.items()}
    field_labels = field_labels or {}
    safe_count = max(0, int(per_field_count or 0))
    clean_intent = str(intent_text or "").strip()
    clean_intent_detail = str(intent_detail or "标准").strip() or "标准"
    clean_rag_mode = _normalize_ai_rag_mode(rag_mode)
    safe_rag_candidate_count = _safe_positive_int(rag_candidate_count, default=12, maximum=200)
    safe_rag_example_count = _safe_positive_int(rag_example_count, default=3, maximum=20)
    effective_counts = {
        field: safe_count if int((per_field_counts or {}).get(field, -1)) < 0 else max(0, int((per_field_counts or {}).get(field, 0)))
        for field in values
    }
    effective_min_post_counts = {
        field: max(0, int(min_post_count or 0))
        if int((per_field_min_post_counts or {}).get(field, -1)) < 0
        else max(0, int((per_field_min_post_counts or {}).get(field, 0)))
        for field in values
    }
    free = _clamp_float(freedom)
    metadata = {
        "enabled": bool(db_path and values),
        "mode": "AI协同选择+规则兜底" if fallback_to_random else "AI协同选择",
        "strategy": str(strategy or "只补空字段"),
        "freedom": free,
        "per_field_count": safe_count,
        "per_field_counts": dict(effective_counts),
        "seed": int(seed or 0),
        "allow_nsfw": bool(allow_nsfw),
        "min_post_count": max(0, int(min_post_count or 0)),
        "per_field_min_post_counts": dict(effective_min_post_counts),
        "candidate_counts": {},
        "candidates": {},
        "selected_items": {},
        "selected_field_values": {},
        "invalid_selections": {},
        "fallback_used": False,
        "fallback_items": {},
        "fallback_field_values": {},
        "field_values": dict(values),
        "ai_called": False,
        "intent_expansion": {
            "enabled": bool(clean_intent),
            "intent": clean_intent,
            "detail": clean_intent_detail,
            "natural_language": "",
            "write_mode": "只放元信息",
        },
        "rag": {
            "enabled": False,
            "mode": clean_rag_mode,
            "candidate_count": safe_rag_candidate_count,
            "example_count": safe_rag_example_count,
            "scope": "current_enabled_fields_only",
            "field_reference_counts": {},
            "fields": [],
        },
        "ai_expansion": {
            "enabled": _ai_candidate_expansion_enabled(free),
            "used": False,
            "requests": [],
            "ignored_requests": [],
            "added_counts": {},
        },
    }
    if not db_path or not values or not any(count > 0 for count in effective_counts.values()):
        return values, metadata

    dictionary = DanbooruDictionary(db_path)
    base_seed = int(seed or 0)
    selection_run_id = _ai_selection_run_id(base_seed, free)
    metadata["selection_run_id"] = selection_run_id
    metadata["effective_min_post_counts"] = {
        field: _ai_effective_min_post_count(effective_min_post_counts.get(field, 0), free)
        for field in values
    }
    fields_to_fill = [
        field
        for field, current in values.items()
        if effective_counts.get(field, 0) > 0 and _field_fill_allowed(current, strategy)
    ]
    if not fields_to_fill:
        return values, metadata

    fields_payload = []
    candidate_by_field = {}
    for index, field in enumerate(fields_to_fill):
        field_seed = base_seed + index if base_seed else 0
        candidates = _ai_candidates_for_field(
            dictionary,
            field,
            count=effective_counts.get(field, safe_count),
            seed=field_seed,
            allow_nsfw=bool(allow_nsfw),
            min_post_count=effective_min_post_counts.get(field, 0),
            freedom=free,
            blacklist=blacklist,
            taxonomy_blacklist=taxonomy_blacklist,
        )
        candidate_by_field[field] = candidates
        metadata["candidate_counts"][field] = len(candidates)
        metadata["candidates"][field] = candidates
        if not candidates:
            continue
        fields_payload.append(
            _build_ai_field_payload(
                field=field,
                label=field_labels.get(field, field),
                max_select_count=effective_counts.get(field, safe_count),
                min_post_count=effective_min_post_counts.get(field, 0),
                candidates=candidates,
                include_taxonomy_scope=_ai_candidate_expansion_enabled(free),
            )
        )

    if not fields_payload:
        if fallback_to_random:
            values, fallback_items, fallback_field_values = _fallback_random_ai_fields(
                values,
                fields_to_fill,
                dictionary=dictionary,
                effective_counts=effective_counts,
                effective_min_post_counts=effective_min_post_counts,
                strategy=strategy,
                seed=base_seed,
                allow_nsfw=bool(allow_nsfw),
                blacklist=blacklist,
                taxonomy_blacklist=taxonomy_blacklist,
            )
            metadata["fallback_used"] = bool(fallback_items)
            metadata["fallback_items"] = fallback_items
            metadata["fallback_field_values"] = fallback_field_values
            metadata["field_values"] = dict(values)
        return values, metadata

    rag_context = _build_ai_rag_context(
        dictionary=dictionary,
        fields_to_fill=fields_to_fill,
        candidate_by_field=candidate_by_field,
        field_labels=field_labels,
        mode=clean_rag_mode,
        candidate_count=safe_rag_candidate_count,
        example_count=safe_rag_example_count,
        previous_context=previous_context,
        intent_text=clean_intent,
        seed=base_seed,
        allow_nsfw=bool(allow_nsfw),
        effective_min_post_counts=effective_min_post_counts,
        blacklist=blacklist,
        taxonomy_blacklist=taxonomy_blacklist,
    )
    metadata["rag"] = rag_context

    try:
        messages = _build_ai_tag_selection_messages(
            node_name=node_name,
            fields_payload=fields_payload,
            previous_context=previous_context,
            freedom=free,
            role_slot=role_slot,
            role_label=role_label,
            selection_run_id=selection_run_id,
            intent_text=clean_intent,
            intent_detail=clean_intent_detail,
            rag_context=rag_context,
        )
        ai_client = client or OpenAICompatibleClient()
        response = ai_client.chat_completion(_ai_selection_provider_config(provider or {}, free), messages)
        metadata["ai_called"] = True
        metadata["raw"] = response.get("raw", {})
        parsed = _extract_json_object(response.get("content", ""))
        expansion = _apply_ai_candidate_expansion_requests(
            dictionary=dictionary,
            parsed=parsed,
            fields_to_fill=fields_to_fill,
            candidate_by_field=candidate_by_field,
            effective_min_post_counts=effective_min_post_counts,
            seed=base_seed,
            allow_nsfw=bool(allow_nsfw),
            freedom=free,
            blacklist=blacklist,
            taxonomy_blacklist=taxonomy_blacklist,
        )
        metadata["ai_expansion"] = expansion
        if expansion.get("requests") or expansion.get("ignored_requests"):
            fields_payload = [
                _build_ai_field_payload(
                    field=field,
                    label=field_labels.get(field, field),
                    max_select_count=effective_counts.get(field, safe_count),
                    min_post_count=effective_min_post_counts.get(field, 0),
                    candidates=candidate_by_field.get(field, []),
                    include_taxonomy_scope=False,
                )
                for field in fields_to_fill
                if candidate_by_field.get(field)
            ]
            messages = _build_ai_tag_selection_messages(
                node_name=node_name,
                fields_payload=fields_payload,
                previous_context=previous_context,
                freedom=free,
                role_slot=role_slot,
                role_label=role_label,
                selection_run_id=f"{selection_run_id}-expanded",
                intent_text=clean_intent,
                intent_detail=clean_intent_detail,
                rag_context=rag_context,
            )
            response = ai_client.chat_completion(_ai_selection_provider_config(provider or {}, free), messages)
            metadata["raw_expanded"] = response.get("raw", {})
            parsed = _extract_json_object(response.get("content", ""))
            metadata["candidate_counts"] = {field: len(items) for field, items in candidate_by_field.items()}
            metadata["candidates"] = dict(candidate_by_field)
        metadata["analysis"] = parsed.get("analysis", {}) if isinstance(parsed.get("analysis"), dict) else {}
        if clean_intent:
            natural = str(parsed.get("natural_language") or parsed.get("caption") or parsed.get("description") or "").strip()
            metadata["intent_expansion"].update(
                {
                    "enabled": True,
                    "intent": clean_intent,
                    "detail": clean_intent_detail,
                    "natural_language": natural,
                    "analysis": metadata.get("analysis", {}),
                }
            )
        append = str(strategy or "只补空字段") == "追加到字段"
        unfilled = []
        selected_by_field = {}
        for field in fields_to_fill:
            if not candidate_by_field.get(field):
                unfilled.append(field)
                continue
            label = field_labels.get(field, field)
            raw_selected = _selection_list_from_ai_payload(parsed, field, label)
            selected, invalid = _validate_ai_selected_items(
                raw_selected,
                candidate_by_field[field],
                effective_counts.get(field, safe_count),
            )
            if invalid:
                metadata["invalid_selections"][field] = invalid
            if not selected:
                unfilled.append(field)
                continue
            selected_by_field[field] = selected
        identity_pairing = _enforce_identity_character_work_pairing(values, selected_by_field, candidate_by_field)
        if identity_pairing.get("checked"):
            metadata["identity_pairing"] = identity_pairing
        for field, selected in selected_by_field.items():
            values[field] = _merge_ai_selection_value(values.get(field, ""), selected, append=append)
            metadata["selected_items"][field] = selected
            metadata["selected_field_values"][field] = _format_ai_selection_display(selected)
        for field in fields_to_fill:
            if field not in selected_by_field and field not in unfilled:
                unfilled.append(field)
        if fallback_to_random and unfilled:
            values, fallback_items, fallback_field_values = _fallback_random_ai_fields(
                values,
                unfilled,
                dictionary=dictionary,
                effective_counts=effective_counts,
                effective_min_post_counts=effective_min_post_counts,
                strategy=strategy,
                seed=base_seed,
                allow_nsfw=bool(allow_nsfw),
                blacklist=blacklist,
                taxonomy_blacklist=taxonomy_blacklist,
            )
            metadata["fallback_used"] = bool(fallback_items)
            metadata["fallback_items"] = fallback_items
            metadata["fallback_field_values"] = fallback_field_values
    except Exception as exc:
        metadata["error"] = str(exc)
        if fallback_to_random:
            values, fallback_items, fallback_field_values = _fallback_random_ai_fields(
                values,
                fields_to_fill,
                dictionary=dictionary,
                effective_counts=effective_counts,
                effective_min_post_counts=effective_min_post_counts,
                strategy=strategy,
                seed=base_seed,
                allow_nsfw=bool(allow_nsfw),
                blacklist=blacklist,
                taxonomy_blacklist=taxonomy_blacklist,
            )
            metadata["fallback_used"] = bool(fallback_items)
            metadata["fallback_items"] = fallback_items
            metadata["fallback_field_values"] = fallback_field_values
        else:
            raise
    metadata["items"] = {
        **metadata.get("selected_items", {}),
        **metadata.get("fallback_items", {}),
    }
    metadata["random_field_values"] = {
        **metadata.get("selected_field_values", {}),
        **metadata.get("fallback_field_values", {}),
    }
    metadata["field_values"] = dict(values)
    return values, metadata


CONFLICT_GROUPS = [
    ("情绪冲突", {"smile", "happy", "laughing"}, {"crying", "sad", "tears"}),
    ("眼睛状态冲突", {"open_eyes", "looking_at_viewer"}, {"closed_eyes", "eyes_closed"}),
    ("背景密度冲突", {"simple_background", "white_background"}, {"detailed_background", "scenery"}),
    ("裸露与保守服装冲突", {"nude", "topless", "naked"}, {"fully_clothed", "school_uniform"}),
]

AI_SUPPRESSED_NATURAL_TAG_PREFIXES = ("score_", "rating:")
AI_SUPPRESSED_NATURAL_TAGS = {
    "masterpiece",
    "best_quality",
    "highres",
    "absurdres",
    "newest",
    "recent",
    "general",
    "sensitive",
    "questionable",
    "explicit",
    "safe",
}

AI_COUNT_PHRASES_EN = {
    "1girl": "one girl",
    "1boy": "one boy",
    "solo": "a solo subject",
    "2girls": "two girls",
    "2boys": "two boys",
    "1girl_1boy": "one girl and one boy",
}

AI_COMPOSITION_TAGS = {
    "looking_at_viewer",
    "portrait",
    "close-up",
    "close_up",
    "upper_body",
    "full_body",
    "cowboy_shot",
    "dynamic_angle",
    "from_below",
    "from_above",
}

AI_BACKGROUND_TAGS = {
    "simple_background",
    "white_background",
    "detailed_background",
    "scenery",
    "indoors",
    "outdoors",
}

AI_EXPRESSION_TAGS = {
    "smile",
    "happy",
    "angry",
    "frown",
    "sad",
    "serious",
    "embarrassed",
    "blush",
    "crying",
}

ANIMA_ORDER_HINTS = {
    "artist": 5,
    "subject": 10,
    "character": 20,
    "appearance": 30,
    "clothing": 40,
    "pose": 50,
    "composition": 60,
    "scene": 70,
    "style": 80,
    "meta": 90,
    "nsfw": 100,
}


def _prompt_tokens_for_diagnostics(prompt: str, db_path: str = "") -> list[str]:
    tokens = []
    for token in split_tag_text(prompt):
        clean = parse_tag_option(strip_prompt_weight(token), db_path=db_path).strip()
        if clean:
            tokens.append(clean)
    return tokens


def _diagnose_prompt(prompt: str, *, db=None, db_path: str = "", allow_nsfw: bool = False) -> dict:
    resolved_db_path = optional_danbooru_db_path(db_path, db)
    tokens = _prompt_tokens_for_diagnostics(prompt, resolved_db_path)
    normalized = [normalize_tag_name(token.lstrip("@")) for token in tokens]
    seen = {}
    duplicates = []
    for original, key in zip(tokens, normalized):
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.setdefault(key, original)

    known = []
    unknown = []
    nsfw_tags = []
    taxonomy_positions = []
    if resolved_db_path:
        dictionary = DanbooruDictionary(resolved_db_path)
        for index, token in enumerate(tokens):
            clean = token.lstrip("@")
            matches = dictionary.resolve_terms(clean, match_mode="exact", allow_nsfw=True, keep_unresolved=False)
            if matches:
                term = matches[0]
                known.append(term.to_dict())
                if term.is_nsfw:
                    nsfw_tags.append(term.tag)
                domain = ""
                if term.taxonomy_id:
                    parts = term.taxonomy_id.split(".")
                    domain = parts[1] if len(parts) >= 5 else parts[0]
                taxonomy_positions.append((index, domain or term.semantic_category or "unknown", term.tag))
            else:
                unknown.append(token)
    else:
        unknown = []

    conflicts = []
    token_set = set(normalized)
    for name, left, right in CONFLICT_GROUPS:
        left_hit = sorted(token_set & left)
        right_hit = sorted(token_set & right)
        if left_hit and right_hit:
            conflicts.append({"type": name, "left": left_hit, "right": right_hit})

    order_warnings = []
    last_rank = -1
    last_domain = ""
    for index, domain, tag in taxonomy_positions:
        rank = ANIMA_ORDER_HINTS.get(domain, last_rank)
        if rank < last_rank and domain != "unknown":
            order_warnings.append(
                {
                    "tag": tag,
                    "domain": domain,
                    "message": f"{domain} 类 tag 出现在 {last_domain} 之后，可能不符合 Anima 输出顺序。",
                }
            )
        if rank >= 0:
            last_rank = max(last_rank, rank)
            last_domain = domain

    issues = []
    if duplicates:
        issues.append({"severity": "warning", "type": "duplicate_tags", "items": duplicates})
    if unknown:
        issues.append({"severity": "info", "type": "unknown_tags", "items": unknown[:80]})
    if nsfw_tags and not allow_nsfw:
        issues.append({"severity": "error", "type": "nsfw_in_sfw_prompt", "items": nsfw_tags})
    if conflicts:
        issues.append({"severity": "warning", "type": "conflicts", "items": conflicts})
    if order_warnings:
        issues.append({"severity": "info", "type": "anima_order", "items": order_warnings})

    completeness_dimensions = {
        "subject": any(item.get("semantic_category") == "subject" or ".subject." in str(item.get("taxonomy_id") or "") for item in known),
        "appearance": any(item.get("semantic_category") == "appearance" for item in known),
        "clothing": any(item.get("semantic_category") == "clothing" for item in known),
        "pose": any(".pose." in str(item.get("taxonomy_id") or "") for item in known),
        "scene": any(item.get("semantic_category") == "scene" for item in known),
        "style": any(item.get("semantic_category") == "style" for item in known),
    }
    completeness = sum(1 for value in completeness_dimensions.values() if value)
    score = 100
    score -= min(25, len(duplicates) * 4)
    score -= min(25, len(conflicts) * 12)
    score -= 30 if nsfw_tags and not allow_nsfw else 0
    score -= min(20, len(unknown) * 2)
    score += completeness * 3
    score = max(0, min(100, score))
    return galiais_metadata(
        {
            "token_count": len(tokens),
            "known_count": len(known),
            "unknown_count": len(unknown),
            "duplicates": duplicates,
            "unknown": unknown,
            "known": known,
            "nsfw_tags": nsfw_tags,
            "conflicts": conflicts,
            "order_warnings": order_warnings,
            "issues": issues,
            "quality_score": score,
            "completeness": completeness_dimensions,
            "allow_nsfw": bool(allow_nsfw),
        }
    )


def _prune_prompt_conflicts(prompt: str, *, mode: str = "保留前者", db_path: str = "") -> dict:
    tokens = _prompt_tokens_for_diagnostics(prompt, db_path)
    normalized = [normalize_tag_name(token.lstrip("@")) for token in tokens]
    remove_keys = set()
    decisions = []
    for name, left, right in CONFLICT_GROUPS:
        left_indices = [index for index, key in enumerate(normalized) if key in left]
        right_indices = [index for index, key in enumerate(normalized) if key in right]
        if not left_indices or not right_indices:
            continue
        if mode == "保留后者":
            remove_indices = left_indices
            keep_indices = right_indices
        elif mode == "自动":
            left_first = min(left_indices)
            right_first = min(right_indices)
            if left_first <= right_first:
                keep_indices = left_indices
                remove_indices = right_indices
            else:
                keep_indices = right_indices
                remove_indices = left_indices
        else:
            keep_indices = left_indices
            remove_indices = right_indices
        removed = [tokens[index] for index in remove_indices]
        kept = [tokens[index] for index in keep_indices]
        remove_keys.update(normalized[index] for index in remove_indices)
        decisions.append({"type": name, "kept": kept, "removed": removed, "mode": mode})

    pruned_tokens = [
        token
        for token, key in zip(tokens, normalized)
        if key not in remove_keys
    ]
    return {
        "original": join_prompt_parts(tokens, dedupe=False),
        "prompt": join_prompt_parts(pruned_tokens, dedupe=True),
        "removed": [item for decision in decisions for item in decision["removed"]],
        "decisions": decisions,
        "changed": bool(remove_keys),
    }


def _token_block_terms(token: str) -> list[str]:
    clean = strip_prompt_weight(parse_tag_option(token)).strip()
    terms = []
    for value in {clean, normalize_tag_name(clean), clean.replace("_", " ")}:
        text = str(value or "").strip().lower()
        if text and text not in terms:
            terms.append(text)
    return terms


def _is_suppressed_natural_language_tag(normalized: str) -> bool:
    key = normalize_tag_name(normalized)
    return key in AI_SUPPRESSED_NATURAL_TAGS or any(key.startswith(prefix) for prefix in AI_SUPPRESSED_NATURAL_TAG_PREFIXES)


def _build_ai_generation_plan(prompt: str, *, conflict_mode: str = "自动", db_path: str = "", allow_nsfw: bool = False) -> dict:
    tokens = _prompt_tokens_for_diagnostics(prompt, db_path)
    normalized = [normalize_tag_name(token.lstrip("@")) for token in tokens]
    keep = [True for _ in tokens]
    dropped_tags = []
    suppressed_tags = []
    decisions = []

    for name, left, right in CONFLICT_GROUPS:
        left_indices = [index for index, key in enumerate(normalized) if key in left]
        right_indices = [index for index, key in enumerate(normalized) if key in right]
        if not left_indices or not right_indices:
            continue
        if conflict_mode == "保留后者":
            remove_indices = left_indices
            keep_indices = right_indices
        elif conflict_mode == "保留前者":
            remove_indices = right_indices
            keep_indices = left_indices
        else:
            left_first = min(left_indices)
            right_first = min(right_indices)
            if left_first <= right_first:
                keep_indices = left_indices
                remove_indices = right_indices
            else:
                keep_indices = right_indices
                remove_indices = left_indices
        for index in remove_indices:
            keep[index] = False
            dropped_tags.append(
                {
                    "tag": tokens[index],
                    "normalized": normalized[index],
                    "reason": name,
                }
            )
        decisions.append(
            {
                "type": name,
                "kept": [tokens[index] for index in keep_indices],
                "removed": [tokens[index] for index in remove_indices],
                "mode": conflict_mode,
            }
        )

    for index, key in enumerate(normalized):
        if keep[index] and _is_suppressed_natural_language_tag(key):
            keep[index] = False
            suppressed_tags.append(
                {
                    "tag": tokens[index],
                    "normalized": key,
                    "reason": "质量/评分/控制类tag不适合扩写成自然语言",
                }
            )
        if keep[index] and not allow_nsfw and key in {"rating:explicit", "explicit"}:
            keep[index] = False
            suppressed_tags.append(
                {
                    "tag": tokens[index],
                    "normalized": key,
                    "reason": "SFW模式下不扩写显式NSFW控制tag",
                }
            )

    kept_tokens = [token for token, enabled in zip(tokens, keep) if enabled]
    blocked_terms = []
    for item in [*dropped_tags, *suppressed_tags]:
        for term in _token_block_terms(item["tag"]):
            if term and term not in blocked_terms:
                blocked_terms.append(term)

    return {
        "original_prompt": join_prompt_parts(tokens, dedupe=False),
        "sanitized_prompt": join_prompt_parts(kept_tokens, dedupe=True),
        "kept_tags": kept_tokens,
        "dropped_tags": dropped_tags,
        "suppressed_tags": suppressed_tags,
        "conflict_decisions": decisions,
        "blocked_natural_language_terms": blocked_terms,
        "changed": len(kept_tokens) != len(tokens),
    }


def _naturalize_tag_text(token: str) -> str:
    text = strip_prompt_weight(parse_tag_option(token)).strip().lower()
    if text in AI_COUNT_PHRASES_EN:
        return AI_COUNT_PHRASES_EN[text]
    return text.replace("_", " ")


def _append_unique(target: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in target:
        target.append(text)


def _build_caption_blueprint(plan: dict, tag_context: dict | None = None, language: str = "英文", detail_level: str = "标准") -> dict:
    tags = [str(item or "").strip() for item in plan.get("kept_tags", []) if str(item or "").strip()]
    normalized = [normalize_tag_name(item) for item in tags]
    count_terms = []
    expression_terms = []
    feature_terms = []
    composition_terms = []
    background_terms = []
    style_terms = []

    taxonomy_by_tag = {}
    resolved_context_tags = (tag_context or {}).get("resolved_tags", []) if isinstance(tag_context, dict) else []
    for item in resolved_context_tags:
        taxonomy_by_tag[normalize_tag_name(item.get("tag", ""))] = item

    for tag, key in zip(tags, normalized):
        phrase = _naturalize_tag_text(tag)
        taxonomy = taxonomy_by_tag.get(key, {}).get("taxonomy", {})
        domain = str(taxonomy.get("domain") or "")
        facet = str(taxonomy.get("facet") or "")
        if key in AI_COUNT_PHRASES_EN:
            _append_unique(count_terms, phrase)
        elif key in AI_EXPRESSION_TAGS:
            _append_unique(expression_terms, phrase)
        elif key in AI_COMPOSITION_TAGS or domain == "composition" or facet in {"camera", "framing"}:
            _append_unique(composition_terms, phrase)
        elif key in AI_BACKGROUND_TAGS or domain == "scene":
            _append_unique(background_terms, phrase)
        elif domain == "style":
            _append_unique(style_terms, phrase)
        else:
            _append_unique(feature_terms, phrase)

    subject = count_terms[0] if count_terms else "the subject"
    primary = [*expression_terms[:2], *feature_terms[:5]]
    secondary = [*composition_terms[:3], *background_terms[:3], *style_terms[:3]]
    if str(language or "") == "中文":
        first = f"画面以{subject}为主体"
        if primary:
            first += "，突出" + "、".join(primary)
        first += "。"
        second = "构图保持清晰稳定"
        if secondary:
            second += "，并呈现" + "、".join(secondary)
        second += "。"
    else:
        first = f"The image focuses on {subject}"
        if primary:
            first += " with " + ", ".join(primary)
        first += "."
        second = "The composition keeps the subject readable"
        if secondary:
            second += " with " + ", ".join(secondary)
        second += "."
    return {
        "subject_terms": count_terms,
        "expression_terms": expression_terms,
        "feature_terms": feature_terms,
        "composition_terms": composition_terms,
        "background_terms": background_terms,
        "style_terms": style_terms,
        "baseline_natural_language": f"{first} {second}",
        "detail_level": str(detail_level or "标准"),
    }


def _build_scene_design_blueprint(plan: dict, tag_context: dict | None = None, language: str = "英文", detail_level: str = "详细") -> dict:
    caption = _build_caption_blueprint(plan, tag_context, language=language, detail_level=detail_level)
    tags = [str(item or "").strip() for item in plan.get("kept_tags", []) if str(item or "").strip()]
    normalized = [normalize_tag_name(item) for item in tags]
    taxonomy_by_tag = {}
    resolved_context_tags = (tag_context or {}).get("resolved_tags", []) if isinstance(tag_context, dict) else []
    for item in resolved_context_tags:
        taxonomy_by_tag[normalize_tag_name(item.get("tag", ""))] = item

    subject_terms = list(caption.get("subject_terms") or [])
    feature_terms = list(caption.get("feature_terms") or [])
    composition_terms = list(caption.get("composition_terms") or [])
    background_terms = list(caption.get("background_terms") or [])
    style_terms = list(caption.get("style_terms") or [])
    prop_terms = []
    lighting_terms = []
    atmosphere_terms = []
    texture_terms = []
    pose_terms = []

    for tag, key in zip(tags, normalized):
        phrase = _naturalize_tag_text(tag)
        taxonomy = taxonomy_by_tag.get(key, {}).get("taxonomy", {})
        domain = str(taxonomy.get("domain") or "")
        facet = str(taxonomy.get("facet") or "")
        if any(word in key for word in ("light", "lighting", "shadow", "glow", "backlight")):
            _append_unique(lighting_terms, phrase)
        if any(word in key for word in ("steam", "mist", "fog", "smoke", "haze", "dust")):
            _append_unique(atmosphere_terms, phrase)
        if any(word in key for word in ("tile", "wood", "glass", "metal", "paper", "fabric", "ceramic")):
            _append_unique(texture_terms, phrase)
        if key in {"sitting", "standing", "lying", "kneeling", "leaning", "looking_away", "looking_at_viewer"} or domain == "pose":
            _append_unique(pose_terms, phrase)
        if domain == "scene" or facet in {"object", "decor", "structure", "background", "location", "environment"}:
            _append_unique(prop_terms, phrase)
        if key in {"window", "poster", "bottle", "vase", "tiled_wall", "wall", "curtains", "shelf"}:
            _append_unique(prop_terms, phrase)
            _append_unique(background_terms, phrase)

    subject = subject_terms[0] if subject_terms else "the main subject"
    foreground = [
        f"place {subject} as the main foreground focus",
        *pose_terms[:2],
        *feature_terms[:3],
    ]
    midground = [
        "use nearby props and surfaces to frame the subject",
        *prop_terms[:4],
        *texture_terms[:2],
    ]
    background = [
        "build a rich background instead of an empty backdrop",
        *background_terms[:5],
        *style_terms[:2],
    ]
    lighting = [
        "separate the subject from the room with layered light",
        *(lighting_terms[:3] or ["soft warm key light", "cool ambient back light"]),
    ]
    atmosphere = [
        "add visible air depth and lived-in atmosphere",
        *(atmosphere_terms[:3] or ["subtle haze", "soft depth of field"]),
    ]
    camera = [
        *(composition_terms[:4] or ["stable cinematic composition", "clear subject silhouette"]),
        "keep foreground, midground, and background readable",
    ]
    environment_props = prop_terms[:8] or background_terms[:8] or ["room details", "wall decorations", "small objects"]

    return {
        "foreground": foreground,
        "midground": midground,
        "background": background,
        "lighting": lighting,
        "atmosphere": atmosphere,
        "camera": camera,
        "environment_props": environment_props,
        "texture_terms": texture_terms,
        "pose_terms": pose_terms,
        "style_terms": style_terms,
        "detail_level": str(detail_level or "详细"),
    }


def _scene_design_sentence_from_blueprint(blueprint: dict, language: str) -> str:
    if str(language or "") == "中文":
        foreground = "、".join((blueprint.get("foreground") or [])[:4])
        midground = "、".join((blueprint.get("midground") or [])[:4])
        background = "、".join((blueprint.get("background") or [])[:5])
        lighting = "、".join((blueprint.get("lighting") or [])[:4])
        atmosphere = "、".join((blueprint.get("atmosphere") or [])[:3])
        camera = "、".join((blueprint.get("camera") or [])[:3])
        return (
            f"前景以{foreground}建立主体焦点。"
            f"中景安排{midground}，让人物和环境产生空间联系。"
            f"背景加入{background}，避免空背景并形成可读的室内层次。"
            f"光影使用{lighting}，同时用{atmosphere}增强空气感。"
            f"镜头保持{camera}。"
        )
    foreground = ", ".join((blueprint.get("foreground") or [])[:4])
    midground = ", ".join((blueprint.get("midground") or [])[:4])
    background = ", ".join((blueprint.get("background") or [])[:5])
    lighting = ", ".join((blueprint.get("lighting") or [])[:4])
    atmosphere = ", ".join((blueprint.get("atmosphere") or [])[:3])
    camera = ", ".join((blueprint.get("camera") or [])[:3])
    return (
        f"In the foreground, {foreground} establishes the main visual focus. "
        f"The midground uses {midground} to connect the subject with the surrounding room. "
        f"The background becomes a rich background with {background}, avoiding an empty backdrop and adding readable layers. "
        f"The lighting uses {lighting}, while {atmosphere} adds air depth and atmosphere. "
        f"The camera keeps {camera}."
    )


def _build_full_image_detail_blueprint(plan: dict, tag_context: dict | None = None, language: str = "英文", detail_level: str = "详细") -> dict:
    caption = _build_caption_blueprint(plan, tag_context, language=language, detail_level=detail_level)
    scene = _build_scene_design_blueprint(plan, tag_context, language=language, detail_level=detail_level)
    tags = [str(item or "").strip() for item in plan.get("kept_tags", []) if str(item or "").strip()]
    normalized = [normalize_tag_name(item) for item in tags]
    taxonomy_by_tag = {}
    resolved_context_tags = (tag_context or {}).get("resolved_tags", []) if isinstance(tag_context, dict) else []
    for item in resolved_context_tags:
        taxonomy_by_tag[normalize_tag_name(item.get("tag", ""))] = item

    appearance_terms = []
    outfit_terms = []
    pose_terms = list(scene.get("pose_terms") or [])
    setting_terms = []
    color_terms = []
    narrative_terms = []
    safety_terms = []

    background_limited = any(key in {"simple_background", "white_background", "transparent_background"} for key in normalized)
    background_rich = any(key in {"detailed_background", "scenery", "indoors", "outdoors"} for key in normalized)

    for tag, key in zip(tags, normalized):
        phrase = _naturalize_tag_text(tag)
        taxonomy = taxonomy_by_tag.get(key, {}).get("taxonomy", {})
        domain = str(taxonomy.get("domain") or "")
        facet = str(taxonomy.get("facet") or "")
        if domain in {"appearance", "body", "face"} or facet in {"hair", "eyes", "body", "skin"}:
            _append_unique(appearance_terms, phrase)
        if domain in {"clothing", "outfit"} or facet in {"clothing", "accessory", "material"}:
            _append_unique(outfit_terms, phrase)
        if domain == "scene" or facet in {"location", "environment"} or key in {"indoors", "outdoors"}:
            _append_unique(setting_terms, phrase)
        if any(word in key for word in ("red", "blue", "green", "yellow", "purple", "black", "white", "warm", "cool", "color")):
            _append_unique(color_terms, phrase)
        if domain == "narrative" or facet in {"relationship", "event", "theme", "state"}:
            _append_unique(narrative_terms, phrase)
        if key in {"safe", "sensitive", "questionable", "explicit", "rating:explicit"}:
            _append_unique(safety_terms, phrase)

    subject_terms = caption.get("subject_terms") or ["the main subject"]
    feature_terms = caption.get("feature_terms") or []
    composition_terms = caption.get("composition_terms") or []
    style_terms = caption.get("style_terms") or []

    return {
        "subject": {
            "source_tags": subject_terms[:4],
            "instruction": "define the main subject clearly without changing locked tags",
        },
        "pose_action": {
            "source_tags": pose_terms[:6],
            "instruction": "describe posture, body orientation, gaze direction, hand action, and intent",
        },
        "appearance": {
            "source_tags": [*appearance_terms[:6], *feature_terms[:4]],
            "instruction": "expand hair, eyes, expression, body silhouette, and visible constant traits only when consistent",
        },
        "outfit_materials": {
            "source_tags": outfit_terms[:8],
            "instruction": "describe clothing layers, accessories, material, folds, shine, and texture when tags support them",
        },
        "composition_camera": {
            "source_tags": composition_terms[:8],
            "instruction": "describe shot size, camera angle, subject placement, focus, negative space, and readability",
        },
        "spatial_layers": {
            "foreground": scene.get("foreground", []),
            "midground": scene.get("midground", []),
            "background": scene.get("background", []),
            "instruction": "make foreground, midground, and background separate and readable",
        },
        "setting": {
            "source_tags": setting_terms[:8],
            "background_limited": background_limited,
            "background_rich": background_rich,
            "instruction": "build location details from tags; keep simple if background-limited, enrich if detailed background is present",
        },
        "background_props": {
            "source_tags": scene.get("environment_props", []),
            "instruction": "add plausible environmental objects in natural language without outputting them as new tags",
        },
        "lighting": {
            "source_tags": scene.get("lighting", []),
            "instruction": "describe key light, rim light, ambient light, shadows, and warm/cool contrast",
        },
        "atmosphere": {
            "source_tags": scene.get("atmosphere", []),
            "instruction": "describe air depth, haze, steam, dust, humidity, depth of field, and lived-in mood",
        },
        "color_design": {
            "source_tags": color_terms[:8],
            "instruction": "describe palette, accent colors, saturation, and warm/cool balance",
        },
        "rendering_style": {
            "source_tags": style_terms[:8],
            "instruction": "describe line quality, shading, painterly or cel rendering, detail density, and finish",
        },
        "narrative_intent": {
            "source_tags": narrative_terms[:8],
            "instruction": "explain what the character seems to be doing and how the environment supports the moment",
        },
        "safety_constraints": {
            "source_tags": safety_terms[:6],
            "blocked_terms": list(plan.get("blocked_natural_language_terms") or []),
            "instruction": "do not describe dropped or suppressed tags; respect SFW/NSFW constraints from locked tags",
        },
        "output_contract": {
            "instruction": "return natural language only; do not output new tags; do not rewrite locked tags; produce a complete image description",
            "language": str(language or "英文"),
            "detail_level": str(detail_level or "详细"),
        },
    }


def _full_image_sentence_from_blueprint(blueprint: dict, language: str) -> str:
    subject = ", ".join((blueprint.get("subject", {}).get("source_tags") or ["the main subject"])[:4])
    pose = ", ".join((blueprint.get("pose_action", {}).get("source_tags") or ["a clear readable pose"])[:4])
    appearance = ", ".join((blueprint.get("appearance", {}).get("source_tags") or ["distinct visible features"])[:5])
    outfit = ", ".join((blueprint.get("outfit_materials", {}).get("source_tags") or ["carefully rendered materials"])[:4])
    layers = blueprint.get("spatial_layers", {})
    foreground = ", ".join((layers.get("foreground") or ["a readable foreground focus"])[:4])
    midground = ", ".join((layers.get("midground") or ["supporting midground details"])[:4])
    background = ", ".join((layers.get("background") or ["a coherent background"])[:5])
    props = ", ".join((blueprint.get("background_props", {}).get("source_tags") or ["environmental details"])[:5])
    lighting = ", ".join((blueprint.get("lighting", {}).get("source_tags") or ["layered lighting"])[:4])
    atmosphere = ", ".join((blueprint.get("atmosphere", {}).get("source_tags") or ["soft atmospheric depth"])[:4])
    color = ", ".join((blueprint.get("color_design", {}).get("source_tags") or ["balanced color design"])[:4])
    style = ", ".join((blueprint.get("rendering_style", {}).get("source_tags") or ["polished anime rendering"])[:4])
    if str(language or "") == "中文":
        return (
            f"画面以{subject}为主体，通过{pose}建立动作和视线关系，并突出{appearance}。"
            f"服装与材质表现为{outfit}，细节服务于角色轮廓而不改变既有 tag。"
            f"前景使用{foreground}，中景安排{midground}，背景扩展为{background}，并加入{props}形成完整空间。"
            f"光影以{lighting}塑造主体和环境的分离，同时用{atmosphere}增强空气感。"
            f"色彩保持{color}，渲染风格偏向{style}，整体自然语言只补全画面设计而不新增 tag。"
        )
    return (
        f"The image centers on {subject}, using {pose} to define the action, body orientation, and gaze while emphasizing {appearance}. "
        f"The outfit and material treatment read as {outfit}, supporting the silhouette without changing any locked tags. "
        f"The foreground uses {foreground}, the midground adds {midground}, and the background expands into {background} with {props} to form a complete spatial design. "
        f"The lighting uses {lighting} to separate the subject from the setting, while {atmosphere} adds air depth and mood. "
        f"The color design keeps {color}, the rendering style leans toward {style}, and the natural language only completes the image design without outputting new tags."
    )


def _natural_language_mentions_blocked_term(text: str, blocked_terms: list[str]) -> list[str]:
    normalized_text = str(text or "").lower().replace("_", " ")
    leaks = []
    for term in blocked_terms or []:
        clean = str(term or "").strip().lower().replace("_", " ")
        if clean and clean in normalized_text and clean not in leaks:
            leaks.append(clean)
    return leaks


def _fallback_natural_language_from_plan(plan: dict, language: str) -> str:
    fallback_kind = str(plan.get("natural_language_fallback_blueprint") or "caption") if isinstance(plan, dict) else "caption"
    full_blueprint = plan.get("full_image_detail_blueprint") if isinstance(plan, dict) else None
    if fallback_kind == "full_image" and isinstance(full_blueprint, dict):
        return _full_image_sentence_from_blueprint(full_blueprint, language)
    scene_blueprint = plan.get("scene_design_blueprint") if isinstance(plan, dict) else None
    if fallback_kind == "scene" and isinstance(scene_blueprint, dict):
        return _scene_design_sentence_from_blueprint(scene_blueprint, language)
    blueprint = plan.get("caption_blueprint") if isinstance(plan, dict) else None
    if isinstance(blueprint, dict) and blueprint.get("baseline_natural_language"):
        return str(blueprint["baseline_natural_language"]).strip()
    return _build_caption_blueprint(plan, language=language).get("baseline_natural_language", "")


def _natural_language_sentence_count(text: str) -> int:
    return len([item for item in re.split(r"[.!?。！？]+", str(text or "")) if item.strip()])


def _natural_language_is_weak(text: str, detail_level: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    if "_" in clean:
        return True
    words = re.findall(r"[A-Za-z\u4e00-\u9fff]+", clean)
    if str(detail_level or "") in {"标准", "详细"} and len(words) < 6:
        return True
    if str(detail_level or "") in {"标准", "详细"} and _natural_language_sentence_count(clean) < 2:
        return True
    weak_phrases = {"nice image", "good image", "beautiful image", "anime image", "high quality image"}
    return clean.lower() in weak_phrases


def _strengthen_natural_language_with_blueprint(natural: str, plan: dict, detail_level: str, language: str) -> tuple[str, bool]:
    if not _natural_language_is_weak(natural, detail_level):
        return str(natural or "").strip(), False
    return _fallback_natural_language_from_plan(plan, language), True


def _repair_natural_language_with_plan(natural: str, plan: dict, language: str) -> tuple[str, bool, list[str]]:
    blocked_terms = list(plan.get("blocked_natural_language_terms") or [])
    leaks = _natural_language_mentions_blocked_term(natural, blocked_terms)
    if not leaks:
        return str(natural or "").strip(), False, []
    return _fallback_natural_language_from_plan(plan, language), True, leaks


def _literal_tag(query: str, source: str = "literal") -> ResolvedTag:
    tag = normalize_tag_name(query)
    return ResolvedTag(
        query=query,
        tag=tag,
        label=query,
        category=None,
        semantic_category=None,
        taxonomy_id=None,
        post_count=0,
        is_nsfw=False,
        source=source,
    )


class DanbooruDictionary:
    def __init__(self, db_path: str = "", locale: str = "zh-CN"):
        self.source_db_path = resolve_danbooru_db_path(db_path)
        self.db_path = preferred_danbooru_runtime_path(self.source_db_path)
        self.locale = locale
        self._index_cache = {}
        self._table_cache = {}

    def _connect(self):
        path = Path(self.db_path)
        conn = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def _has_index(self, conn, index_name: str) -> bool:
        if index_name in self._index_cache:
            return self._index_cache[index_name]
        row = conn.execute(
            "select 1 from sqlite_master where type = 'index' and name = ? limit 1",
            (index_name,),
        ).fetchone()
        exists = bool(row)
        self._index_cache[index_name] = exists
        return exists

    def _indexed_table(self, conn, table: str, index_name: str) -> str:
        if self._has_index(conn, index_name):
            return f"{table} indexed by {index_name}"
        return table

    def _has_table(self, conn, table_name: str) -> bool:
        if table_name in self._table_cache:
            return self._table_cache[table_name]
        row = conn.execute(
            "select 1 from sqlite_master where type in ('table', 'virtual') and name = ? limit 1",
            (table_name,),
        ).fetchone()
        exists = bool(row)
        self._table_cache[table_name] = exists
        return exists

    def _metadata_value(self, conn, key: str) -> str:
        if not self._has_table(conn, "dictionary_metadata"):
            return ""
        row = conn.execute(
            "select value from dictionary_metadata where key = ? limit 1",
            (key,),
        ).fetchone()
        return str(row["value"] or "") if row else ""

    def _is_runtime_db(self, conn) -> bool:
        return self._metadata_value(conn, "runtime_db") == "1"

    def stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("select count(*) from danbooru_tags").fetchone()[0]
            translated = conn.execute(
                """
                select count(distinct tag_name)
                from danbooru_tag_localizations
                where locale = ? and kind in ('primary', 'alias')
                """,
                (self.locale,),
            ).fetchone()[0]
            templates = conn.execute(
                "select count(*) from sqlite_master where type='table' and name='prompt_templates'"
            ).fetchone()[0]
            template_count = 0
            if templates:
                template_count = conn.execute("select count(*) from prompt_templates").fetchone()[0]
            runtime_db = self._is_runtime_db(conn)
            fts_enabled = self._has_table(conn, "danbooru_tag_search_fts")
            option_cache_rows = 0
            if self._has_table(conn, "taxonomy_option_cache"):
                option_cache_rows = conn.execute("select count(*) from taxonomy_option_cache").fetchone()[0]
        return {
            "db_path": self.db_path,
            "source_db_path": self.source_db_path,
            "locale": self.locale,
            "total_tags": int(total),
            "translated_tags": int(translated),
            "template_count": int(template_count),
            "runtime_db": bool(runtime_db),
            "fts_enabled": bool(fts_enabled),
            "option_cache_rows": int(option_cache_rows),
        }

    def resolve_terms(
        self,
        text: str,
        *,
        match_mode: str = "exact",
        allow_nsfw: bool = True,
        keep_unresolved: bool = True,
        min_post_count: int = 0,
        limit_per_term: int = 1,
    ) -> list[ResolvedTag]:
        terms = split_tag_text(text)
        if not terms:
            return []

        resolved = []
        seen = set()
        try:
            with self._connect() as conn:
                for query in terms:
                    matches = self._resolve_one(
                        conn,
                        query,
                        match_mode=match_mode,
                        allow_nsfw=allow_nsfw,
                        min_post_count=min_post_count,
                        limit=limit_per_term,
                    )
                    if not matches and keep_unresolved:
                        matches = [_literal_tag(query, "unresolved")]
                    for item in matches:
                        key = normalize_tag_name(item.tag)
                        if key in seen:
                            continue
                        seen.add(key)
                        resolved.append(item)
        except FileNotFoundError:
            if keep_unresolved:
                for query in terms:
                    item = _literal_tag(query, "missing_dictionary")
                    key = normalize_tag_name(item.tag)
                    if key not in seen:
                        seen.add(key)
                        resolved.append(item)
            else:
                raise
        return resolved

    def taxonomy_metadata_for_ids(self, taxonomy_ids) -> dict[str, dict]:
        ids = sorted({str(item or "").strip() for item in taxonomy_ids if str(item or "").strip()})
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            if not self._has_table(conn, "tag_taxonomy"):
                return {}
            rows = conn.execute(
                f"""
                select
                    id,
                    domain,
                    facet,
                    group_key,
                    leaf_key,
                    label_zh,
                    label_en,
                    safety_scope,
                    prompt_role
                from tag_taxonomy
                where id in ({placeholders})
                """,
                ids,
            ).fetchall()
        return {str(row["id"]): dict(row) for row in rows}

    def search(
        self,
        query: str,
        *,
        match_mode: str = "smart",
        allow_nsfw: bool = True,
        min_post_count: int = 0,
        limit: int = 20,
    ) -> list[ResolvedTag]:
        with self._connect() as conn:
            return self._resolve_one(
                conn,
                query,
                match_mode=match_mode,
                allow_nsfw=allow_nsfw,
                min_post_count=min_post_count,
                limit=limit,
            )

    def query_search(
        self,
        query: str,
        *,
        language: str = "中英文",
        match_mode: str = "contains",
        allow_nsfw: bool = False,
        min_post_count: int = 0,
        limit: int = 20,
    ) -> list[ResolvedTag]:
        text = str(query or "").strip()
        if not text:
            return []
        mode = match_mode if match_mode in {"smart", "exact", "prefix", "contains"} else "smart"
        language = language if language in {"中文", "英文", "中英文"} else "中英文"
        if mode == "smart":
            for candidate_mode in ("exact", "prefix", "contains"):
                results = self.query_search(
                    text,
                    language=language,
                    match_mode=candidate_mode,
                    allow_nsfw=allow_nsfw,
                    min_post_count=min_post_count,
                    limit=limit,
                )
                if results:
                    return results
            return []
        with self._connect() as conn:
            results = []
            if language in {"英文", "中英文"}:
                results.extend(
                    self._search_by_name(
                        conn,
                        text,
                        match_mode=mode,
                        allow_nsfw=allow_nsfw,
                        min_post_count=min_post_count,
                        limit=limit,
                    )
                )
            if language in {"中文", "中英文"}:
                results.extend(
                    self._search_by_label(
                        conn,
                        text,
                        match_mode=mode,
                        allow_nsfw=allow_nsfw,
                        min_post_count=min_post_count,
                        limit=limit,
                    )
                )

        deduped = []
        seen = set()
        for item in sorted(results, key=lambda term: (-term.post_count, term.tag.lower())):
            key = normalize_tag_name(item.tag)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def template(self, template_id: str) -> dict[str, str] | None:
        with self._connect() as conn:
            has_table = conn.execute(
                "select count(*) from sqlite_master where type='table' and name='prompt_templates'"
            ).fetchone()[0]
            if not has_table:
                return None
            row = conn.execute(
                """
                select id, name, platform, positive_template, negative_template
                from prompt_templates
                where id = ? or name = ?
                limit 1
                """,
                (template_id, template_id),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def options_for_taxonomy(
        self,
        taxonomy_ids,
        *,
        limit: int = 80,
        allow_nsfw: bool = False,
        min_post_count: int = 0,
    ) -> list[str]:
        ids = [str(item).strip() for item in taxonomy_ids if str(item).strip()]
        if not ids:
            return ["none"]

        placeholders = ",".join("?" for _ in ids)
        nsfw_clause = "" if allow_nsfw else "and t.is_nsfw = 0"
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select
                    t.name,
                    coalesce(lp.label, t.name) as label
                from danbooru_tags t
                left join danbooru_tag_localizations lp
                    on lp.tag_name = t.name
                    and lp.locale = ?
                    and lp.kind = 'primary'
                where t.taxonomy_id in ({placeholders})
                  and t.post_count >= ?
                  {nsfw_clause}
                order by t.post_count desc, t.name collate nocase asc
                limit ?
                """,
                [self.locale, *ids, int(min_post_count), max(1, int(limit))],
            ).fetchall()

        options = ["none"]
        for row in rows:
            tag = row["name"]
            label = row["label"] or tag
            options.append(format_tag_option_parts(tag, label))
        return options

    def options_for_category(
        self,
        category: int,
        *,
        semantic_category: str | None = None,
        limit: int = 80,
        allow_nsfw: bool = False,
        min_post_count: int = 0,
    ) -> list[str]:
        nsfw_clause = "" if allow_nsfw else "and t.is_nsfw = 0"
        semantic_clause = ""
        params = [self.locale, int(category), int(min_post_count)]
        if semantic_category:
            semantic_clause = "and t.semantic_category_key = ?"
            params.append(str(semantic_category))
        params.append(max(1, int(limit)))

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select
                    t.name,
                    coalesce(lp.label, t.name) as label
                from danbooru_tags t
                left join danbooru_tag_localizations lp
                    on lp.tag_name = t.name
                    and lp.locale = ?
                    and lp.kind = 'primary'
                where t.category = ?
                  and t.post_count >= ?
                  {semantic_clause}
                  {nsfw_clause}
                order by t.post_count desc, t.name collate nocase asc
                limit ?
                """,
                params,
            ).fetchall()

        options = ["none"]
        for row in rows:
            options.append(format_tag_option_parts(row["name"], row["label"] or row["name"]))
        return options

    def option_records_for_field(
        self,
        field: str,
        *,
        query: str = "",
        language: str = "中英文",
        allow_nsfw: bool = False,
        min_post_count: int = 0,
        limit: int = 50,
        offset: int = 0,
        blacklist=None,
        include_global_blacklist: bool = True,
        mark_blacklist_only: bool = False,
    ) -> dict:
        spec = danbooru_field_spec(field)
        safe_limit = min(200, max(1, int(limit or 50)))
        safe_offset = max(0, int(offset or 0))
        blacklist_tags = global_tag_blacklist(blacklist) if include_global_blacklist else normalize_tag_blacklist(blacklist)
        if not spec:
            return {
                "field": str(field or ""),
                "query": str(query or ""),
                "offset": safe_offset,
                "limit": safe_limit,
                "items": [],
                "has_more": False,
            }

        text = str(query or "").strip()
        language = language if language in {"中文", "英文", "中英文"} else "中英文"
        cache_key = (
            _db_cache_signature(self.db_path),
            self.locale,
            "options",
            spec.get("field", str(field or "")),
            text,
            language,
            bool(allow_nsfw),
            int(min_post_count or 0),
            blacklist_tags,
            bool(mark_blacklist_only),
            safe_limit,
            safe_offset,
        )
        cached = _cache_get(_DANBOORU_OPTION_CACHE, cache_key)
        if cached is not _DANBOORU_CACHE_MISS:
            return cached

        taxonomy_ids = [
            str(item).strip()
            for item in spec.get("taxonomy_ids", [])
            if str(item).strip()
        ]
        categories = [
            item
            for item in spec.get("categories", [])
            if isinstance(item, dict) and "category" in item
        ]
        with self._connect() as conn:
            rows = self._field_option_rows(
                conn,
                taxonomy_ids,
                categories,
                query=text,
                language=language,
                allow_nsfw=allow_nsfw,
                min_post_count=int(min_post_count or 0),
                limit=safe_limit + 1 + (0 if mark_blacklist_only else len(blacklist_tags)),
                offset=safe_offset,
                blacklist_tags=() if mark_blacklist_only else blacklist_tags,
            )
            labels = self._primary_labels_for_tags(conn, [row["name"] for row in rows[:safe_limit]])

        items = []
        for row in rows[:safe_limit]:
            tag = row["name"]
            label = labels.get(tag, tag)
            items.append(
                {
                    "tag": tag,
                    "label": label,
                    "option": format_tag_option_parts(tag, label),
                    "category": row["category"],
                    "semantic_category": row["semantic_category_key"],
                    "taxonomy_id": row["taxonomy_id"],
                    "post_count": int(row["post_count"] or 0),
                    "is_nsfw": bool(row["is_nsfw"]),
                    "is_blacklisted": normalize_tag_name(tag) in blacklist_tags,
                }
            )
        payload = {
            "field": spec.get("field", str(field or "")),
            "query": text,
            "offset": safe_offset,
            "limit": safe_limit,
            "items": items,
            "has_more": len(rows) > safe_limit,
        }
        _cache_put(_DANBOORU_OPTION_CACHE, cache_key, payload, _DANBOORU_OPTION_CACHE_LIMIT)
        return payload

    def random_options_for_field(
        self,
        field: str,
        *,
        taxonomy_id: str = "",
        count: int = 1,
        seed: int = 0,
        allow_nsfw: bool = False,
        min_post_count: int = 0,
        query: str = "",
        language: str = "中英文",
        blacklist=None,
        include_global_blacklist: bool = True,
        taxonomy_blacklist=None,
        include_global_taxonomy_blacklist: bool = True,
        max_count: int = 50,
    ) -> list[dict]:
        spec = danbooru_field_spec(field)
        blacklist_tags = global_tag_blacklist(blacklist) if include_global_blacklist else normalize_tag_blacklist(blacklist)
        taxonomy_blacklist_items = (
            global_random_taxonomy_blacklist(taxonomy_blacklist)
            if include_global_taxonomy_blacklist
            else normalize_taxonomy_blacklist(taxonomy_blacklist)
        )
        ids = []
        categories = []
        if taxonomy_id:
            ids = [str(taxonomy_id).strip()]
        elif spec:
            ids = [str(item).strip() for item in spec.get("taxonomy_ids", []) if str(item).strip()]
            categories = [item for item in spec.get("categories", []) if isinstance(item, dict) and "category" in item]
        if not ids and not categories:
            return []
        safe_count = max(0, int(count or 0))
        if safe_count <= 0:
            return []
        with self._connect() as conn:
            text = str(query or "").strip()
            if text:
                candidate_limit = 10000
                rows = self._field_option_rows(
                    conn,
                    ids,
                    categories,
                    query=text,
                    language=language,
                    allow_nsfw=allow_nsfw,
                    min_post_count=int(min_post_count or 0),
                    limit=candidate_limit,
                    offset=0,
                    blacklist_tags=blacklist_tags,
                )
                rows = self._filter_random_taxonomy_blacklist(rows, taxonomy_blacklist_items)
                rng = random.Random(int(seed)) if int(seed or 0) else random.SystemRandom()
                rows = list(rows)
                rows = rng.sample(rows, min(safe_count, len(rows)))
            else:
                rows = self._random_field_option_rows(
                    conn,
                    ids,
                    categories,
                    allow_nsfw=allow_nsfw,
                    min_post_count=int(min_post_count or 0),
                    count=safe_count,
                    seed=int(seed or 0),
                    blacklist_tags=blacklist_tags,
                    taxonomy_blacklist=taxonomy_blacklist_items,
                    max_count=max_count,
                )
            labels = self._primary_labels_for_tags(conn, [row["name"] for row in rows])
        items = []
        for row in rows:
            tag = row["name"]
            label = labels.get(tag, tag)
            items.append(
                {
                    "tag": tag,
                    "label": label,
                    "option": format_tag_option_parts(tag, label),
                    "category": row["category"],
                    "semantic_category": row["semantic_category_key"],
                    "taxonomy_id": row["taxonomy_id"],
                    "post_count": int(row["post_count"] or 0),
                    "is_nsfw": bool(row["is_nsfw"]),
                }
            )
        return items

    def taxonomy_tree_for_field(
        self,
        field: str,
        *,
        allow_nsfw: bool = False,
        min_post_count: int = 0,
        include_counts: bool = True,
    ) -> dict:
        spec = danbooru_field_spec(field)
        if not spec:
            return {
                "field": str(field or ""),
                "nodes": [],
                "leaves": [],
                "counts_included": bool(include_counts),
            }
        taxonomy_ids = [
            str(item).strip()
            for item in spec.get("taxonomy_ids", [])
            if str(item).strip()
        ]
        categories = [
            item
            for item in spec.get("categories", [])
            if isinstance(item, dict) and "category" in item
        ]
        if not taxonomy_ids and not categories:
            return {
                "field": spec.get("field", str(field or "")),
                "nodes": [],
                "leaves": [],
                "counts_included": bool(include_counts),
            }
        cache_key = (
            _db_cache_signature(self.db_path),
            self.locale,
            "tree",
            spec.get("field", str(field or "")),
            bool(allow_nsfw),
            int(min_post_count or 0),
            bool(include_counts),
        )
        cached = _cache_get(_DANBOORU_TREE_CACHE, cache_key)
        if cached is not _DANBOORU_CACHE_MISS:
            return cached
        with self._connect() as conn:
            rows = self._taxonomy_tree_rows(
                conn,
                taxonomy_ids,
                categories,
                allow_nsfw=allow_nsfw,
                min_post_count=int(min_post_count or 0),
                include_counts=include_counts,
            )
        payload = self._taxonomy_tree_payload(
            spec.get("field", str(field or "")),
            rows,
            include_counts=include_counts,
        )
        _cache_put(_DANBOORU_TREE_CACHE, cache_key, payload, _DANBOORU_TREE_CACHE_LIMIT)
        return payload

    def all_taxonomy_tree(
        self,
        *,
        allow_nsfw: bool = False,
        min_post_count: int = 0,
        include_counts: bool = False,
    ) -> dict:
        cache_key = (
            _db_cache_signature(self.db_path),
            self.locale,
            "all_taxonomy_tree",
            bool(allow_nsfw),
            int(min_post_count or 0),
            bool(include_counts),
        )
        cached = _cache_get(_DANBOORU_TREE_CACHE, cache_key)
        if cached is not _DANBOORU_CACHE_MISS:
            return cached
        with self._connect() as conn:
            rows = self._all_taxonomy_tree_rows(
                conn,
                allow_nsfw=allow_nsfw,
                min_post_count=int(min_post_count or 0),
                include_counts=include_counts,
            )
        payload = self._taxonomy_tree_payload(
            "__all_taxonomy__",
            rows,
            include_counts=include_counts,
        )
        _cache_put(_DANBOORU_TREE_CACHE, cache_key, payload, _DANBOORU_TREE_CACHE_LIMIT)
        return payload

    def _taxonomy_tree_payload(self, field: str, rows, *, include_counts: bool) -> dict:
        tree = []
        index = {}
        leaves = []

        def ensure_node(path: tuple[str, ...], label: str, node_id: str | None = None):
            key = "/".join(path)
            if key in index:
                return index[key]
            parent = tree if len(path) == 1 else ensure_node(path[:-1], path[-2])["children"]
            node = {
                "id": node_id or key,
                "label": label or "unknown",
                "count": 0,
                "children": [],
            }
            parent.append(node)
            index[key] = node
            return node

        for row in rows:
            domain = row["taxonomy_domain"] or "unknown"
            facet = row["taxonomy_facet"] or "unknown"
            group = row["taxonomy_group"] or "unknown"
            leaf = row["taxonomy_leaf"] or row["taxonomy_id"] or "unknown"
            leaf_label = row.get("taxonomy_label_zh") or row.get("taxonomy_label_en") or _taxonomy_label(leaf)
            count = int(row["count"] or 0)
            domain_node = ensure_node((domain,), taxonomy_domain_label(domain))
            facet_node = ensure_node((domain, facet), taxonomy_facet_label(domain, facet))
            group_node = ensure_node((domain, facet, group), _taxonomy_label(group))
            domain_node["taxonomy_prefix"] = f"0.{domain}"
            facet_node["taxonomy_prefix"] = f"0.{domain}.{facet}"
            group_node["taxonomy_prefix"] = f"0.{domain}.{facet}.{group}"
            leaf_node = ensure_node(
                (domain, facet, group, leaf),
                leaf_label,
                row["taxonomy_id"],
            )
            leaf_node["taxonomy_id"] = row["taxonomy_id"]
            leaf_node["taxonomy_prefix"] = row["taxonomy_id"]
            leaf_node["count"] = count
            leaf_node["label_en"] = row.get("taxonomy_label_en") or leaf
            for node in (domain_node, facet_node, group_node):
                node["count"] += count
            leaves.append(
                {
                    "taxonomy_id": row["taxonomy_id"],
                    "domain": domain,
                    "facet": facet,
                    "group": group,
                    "leaf": leaf,
                    "label": leaf_label,
                    "label_en": row.get("taxonomy_label_en") or leaf,
                    "count": count,
                }
            )
        payload = {
            "field": str(field or ""),
            "nodes": tree,
            "leaves": leaves,
            "counts_included": bool(include_counts),
        }
        return payload

    def _taxonomy_tree_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        categories: list[dict],
        *,
        allow_nsfw: bool,
        min_post_count: int,
        include_counts: bool = True,
    ):
        if not include_counts:
            return self._taxonomy_tree_shape_rows(conn, taxonomy_ids, categories)
        if taxonomy_ids and not categories and int(min_post_count or 0) == 0:
            cached_rows = self._taxonomy_count_cache_rows(
                conn,
                taxonomy_ids,
                allow_nsfw=allow_nsfw,
            )
            if len(cached_rows) == len({str(item).strip() for item in taxonomy_ids if str(item).strip()}):
                return cached_rows
        rows = []
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        if taxonomy_ids:
            placeholders = ",".join("?" for _ in taxonomy_ids)
            table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_taxonomy")
            rows.extend(
                conn.execute(
                    f"""
                    select
                        taxonomy_id,
                        taxonomy_domain,
                        taxonomy_facet,
                        taxonomy_group,
                        taxonomy_leaf,
                        max(tx.label_zh) as taxonomy_label_zh,
                        max(tx.label_en) as taxonomy_label_en,
                        count(*) as count
                    from {table}
                    left join tag_taxonomy tx on tx.id = taxonomy_id
                    where taxonomy_id in ({placeholders})
                      and post_count >= ?
                      {nsfw_clause}
                    group by taxonomy_id
                    """,
                    [*taxonomy_ids, min_post_count],
                ).fetchall()
            )
        for category_spec in categories:
            semantic_clause = ""
            params = [int(category_spec["category"]), min_post_count]
            semantic_category = category_spec.get("semantic_category")
            if semantic_category:
                semantic_clause = "and semantic_category_key = ?"
                params.append(str(semantic_category))
            table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_category_post_count")
            rows.extend(
                conn.execute(
                    f"""
                    select
                        coalesce(taxonomy_id, 'category:' || category) as taxonomy_id,
                        coalesce(taxonomy_domain, semantic_category_key, 'category') as taxonomy_domain,
                        coalesce(taxonomy_facet, semantic_category_key, 'category') as taxonomy_facet,
                        coalesce(taxonomy_group, 'category_' || category) as taxonomy_group,
                        coalesce(taxonomy_leaf, semantic_category_key, 'category_' || category) as taxonomy_leaf,
                        max(tx.label_zh) as taxonomy_label_zh,
                        max(tx.label_en) as taxonomy_label_en,
                        count(*) as count
                    from {table}
                    left join tag_taxonomy tx on tx.id = taxonomy_id
                    where category = ?
                      and post_count >= ?
                      {semantic_clause}
                      {nsfw_clause}
                    group by taxonomy_id
                    """,
                    params,
                ).fetchall()
            )
        return self._merge_taxonomy_tree_rows(rows)

    def _taxonomy_tree_shape_rows(self, conn, taxonomy_ids: list[str], categories: list[dict]):
        rows = []
        ids = [str(item).strip() for item in taxonomy_ids if str(item).strip()]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            rows.extend(
                conn.execute(
                    f"""
                    select
                        tx.id as taxonomy_id,
                        tx.domain as taxonomy_domain,
                        tx.facet as taxonomy_facet,
                        tx.group_key as taxonomy_group,
                        tx.leaf_key as taxonomy_leaf,
                        tx.label_zh as taxonomy_label_zh,
                        tx.label_en as taxonomy_label_en,
                        0 as count
                    from tag_taxonomy tx
                    where tx.id in ({placeholders})
                    """,
                    ids,
                ).fetchall()
            )
        for category_spec in categories:
            params = [int(category_spec["category"])]
            semantic_category = category_spec.get("semantic_category")
            if semantic_category:
                rows.append(
                    {
                        "taxonomy_id": f"category:{int(category_spec['category'])}:{semantic_category}",
                        "taxonomy_domain": semantic_category,
                        "taxonomy_facet": semantic_category,
                        "taxonomy_group": f"category_{int(category_spec['category'])}",
                        "taxonomy_leaf": semantic_category,
                        "taxonomy_label_zh": "",
                        "taxonomy_label_en": semantic_category,
                        "count": 0,
                    }
                )
                continue
            rows.extend(
                conn.execute(
                    """
                    select
                        tx.id as taxonomy_id,
                        tx.domain as taxonomy_domain,
                        tx.facet as taxonomy_facet,
                        tx.group_key as taxonomy_group,
                        tx.leaf_key as taxonomy_leaf,
                        tx.label_zh as taxonomy_label_zh,
                        tx.label_en as taxonomy_label_en,
                        0 as count
                    from tag_taxonomy tx
                    where tx.danbooru_category = ?
                    """,
                    params,
                ).fetchall()
            )
        return self._merge_taxonomy_tree_rows(rows)

    def _all_taxonomy_tree_rows(
        self,
        conn,
        *,
        allow_nsfw: bool,
        min_post_count: int,
        include_counts: bool = True,
    ):
        if include_counts and int(min_post_count or 0) == 0:
            cached_rows = self._taxonomy_count_cache_rows(
                conn,
                [],
                allow_nsfw=allow_nsfw,
                include_all=True,
            )
            if cached_rows:
                return cached_rows
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        if include_counts:
            rows = conn.execute(
                f"""
                select
                    tx.id as taxonomy_id,
                    tx.domain as taxonomy_domain,
                    tx.facet as taxonomy_facet,
                    tx.group_key as taxonomy_group,
                    tx.leaf_key as taxonomy_leaf,
                    tx.label_zh as taxonomy_label_zh,
                    tx.label_en as taxonomy_label_en,
                    coalesce(stats.count, 0) as count
                from tag_taxonomy tx
                left join (
                    select taxonomy_id, count(*) as count
                    from danbooru_tags
                    where taxonomy_id is not null
                      and post_count >= ?
                      {nsfw_clause}
                    group by taxonomy_id
                ) stats on stats.taxonomy_id = tx.id
                where coalesce(tx.is_selectable, 1) != 0
                order by tx.sort_order asc, tx.id collate nocase asc
                """,
                (int(min_post_count),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select
                    tx.id as taxonomy_id,
                    tx.domain as taxonomy_domain,
                    tx.facet as taxonomy_facet,
                    tx.group_key as taxonomy_group,
                    tx.leaf_key as taxonomy_leaf,
                    tx.label_zh as taxonomy_label_zh,
                    tx.label_en as taxonomy_label_en,
                    0 as count
                from tag_taxonomy tx
                where coalesce(tx.is_selectable, 1) != 0
                order by tx.sort_order asc, tx.id collate nocase asc
                """
            ).fetchall()
        return self._merge_taxonomy_tree_rows(rows)

    def _taxonomy_count_cache_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        *,
        allow_nsfw: bool,
        include_all: bool = False,
    ):
        if not self._has_table(conn, "taxonomy_count_cache"):
            return []
        count_column = "total_count" if allow_nsfw else "sfw_count"
        params = []
        id_clause = ""
        if not include_all:
            ids = [str(item).strip() for item in taxonomy_ids if str(item).strip()]
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            id_clause = f"and tx.id in ({placeholders})"
            params.extend(ids)
        rows = conn.execute(
            f"""
            select
                tx.id as taxonomy_id,
                tx.domain as taxonomy_domain,
                tx.facet as taxonomy_facet,
                tx.group_key as taxonomy_group,
                tx.leaf_key as taxonomy_leaf,
                tx.label_zh as taxonomy_label_zh,
                tx.label_en as taxonomy_label_en,
                coalesce(cc.{count_column}, 0) as count
            from tag_taxonomy tx
            left join taxonomy_count_cache cc on cc.taxonomy_id = tx.id
            where coalesce(tx.is_selectable, 1) != 0
              {id_clause}
            order by tx.sort_order asc, tx.id collate nocase asc
            """,
            params,
        ).fetchall()
        return self._merge_taxonomy_tree_rows(rows)

    def _merge_taxonomy_tree_rows(self, rows):
        merged = {}
        for row in rows:
            taxonomy_id = row["taxonomy_id"]
            if taxonomy_id in merged:
                merged[taxonomy_id]["count"] += int(row["count"] or 0)
                continue
            merged[taxonomy_id] = {
                "taxonomy_id": taxonomy_id,
                "taxonomy_domain": row["taxonomy_domain"],
                "taxonomy_facet": row["taxonomy_facet"],
                "taxonomy_group": row["taxonomy_group"],
                "taxonomy_leaf": row["taxonomy_leaf"],
                "taxonomy_label_zh": row["taxonomy_label_zh"],
                "taxonomy_label_en": row["taxonomy_label_en"],
                "count": int(row["count"] or 0),
            }
        return sorted(
            merged.values(),
            key=lambda item: (
                str(item["taxonomy_domain"] or ""),
                str(item["taxonomy_facet"] or ""),
                str(item["taxonomy_group"] or ""),
                str(item["taxonomy_leaf"] or ""),
            ),
        )

    def _field_option_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        categories: list[dict],
        *,
        query: str,
        language: str,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
        offset: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        if not taxonomy_ids and not categories:
            return []
        if query:
            return self._search_field_option_rows(
                conn,
                taxonomy_ids,
                categories,
                query=query,
                language=language,
                allow_nsfw=allow_nsfw,
                min_post_count=min_post_count,
                limit=limit,
                offset=offset,
                blacklist_tags=blacklist_tags,
            )
        return self._browse_field_option_rows(
            conn,
            taxonomy_ids,
            categories,
            allow_nsfw=allow_nsfw,
            min_post_count=min_post_count,
            limit=limit,
            offset=offset,
            blacklist_tags=blacklist_tags,
        )

    def _browse_field_option_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        categories: list[dict],
        *,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
        offset: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        candidate_rows = []
        category_rows_added = False
        if taxonomy_ids and not categories:
            cached_rows = self._query_taxonomy_option_cache_rows(
                conn,
                taxonomy_ids,
                allow_nsfw=allow_nsfw,
                min_post_count=min_post_count,
                limit=limit,
                offset=offset,
                blacklist_tags=blacklist_tags,
            )
            if len(cached_rows) >= limit:
                return cached_rows
        if taxonomy_ids and not categories:
            fast_rows = self._query_taxonomy_rows_by_category_index(
                conn,
                taxonomy_ids,
                allow_nsfw=allow_nsfw,
                min_post_count=min_post_count,
                limit=offset + limit,
                blacklist_tags=blacklist_tags,
            )
            if len(fast_rows) >= offset + limit:
                return self._dedupe_sort_rows(fast_rows)[offset : offset + limit]
            candidate_rows.extend(fast_rows)
        if categories:
            for category_spec in categories:
                candidate_rows.extend(
                    self._query_category_rows(
                        conn,
                        category_spec,
                        allow_nsfw=allow_nsfw,
                        min_post_count=min_post_count,
                        limit=offset + limit,
                        blacklist_tags=blacklist_tags,
                    )
                )
                if category_spec.get("semantic_category") is None:
                    category_rows_added = True
        if taxonomy_ids and not category_rows_added:
            candidate_rows.extend(
                self._query_taxonomy_rows(
                    conn,
                    taxonomy_ids,
                    allow_nsfw=allow_nsfw,
                    min_post_count=min_post_count,
                    limit=offset + limit,
                    blacklist_tags=blacklist_tags,
                )
            )
        rows = self._dedupe_sort_rows(candidate_rows)
        return rows[offset : offset + limit]

    def _query_taxonomy_option_cache_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        *,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
        offset: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        ids = [str(item).strip() for item in taxonomy_ids if str(item).strip()]
        if not ids or not self._has_table(conn, "taxonomy_option_cache"):
            return []
        placeholders = ",".join("?" for _ in ids)
        nsfw_clause = "" if allow_nsfw else "and c.is_nsfw = 0"
        blacklist_clause, blacklist_params = self._blacklist_sql_clause("t", blacklist_tags)
        rows = conn.execute(
            f"""
            select
                t.name,
                t.category,
                t.post_count,
                t.semantic_category_key,
                t.taxonomy_id,
                t.is_nsfw
            from taxonomy_option_cache c
            join danbooru_tags t on t.name = c.tag_name
            where c.taxonomy_id in ({placeholders})
              and c.post_count >= ?
              {nsfw_clause}
              {blacklist_clause}
            order by c.post_count desc, t.name collate nocase asc
            limit ? offset ?
            """,
            [*ids, min_post_count, *blacklist_params, max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
        return rows

    def _query_taxonomy_rows_by_category_index(
        self,
        conn,
        taxonomy_ids: list[str],
        *,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        category = _single_taxonomy_category(taxonomy_ids)
        if category is None:
            return []
        ids = [str(item).strip() for item in taxonomy_ids if str(item).strip()]
        if len(ids) <= 1:
            return []
        if any(".nsfw." in item for item in ids):
            return []
        placeholders = ",".join("?" for _ in ids)
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        blacklist_clause, blacklist_params = self._blacklist_sql_clause("", blacklist_tags)
        table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_category_post_count")
        return conn.execute(
            f"""
            select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
            from {table}
            where category = ?
              and taxonomy_id in ({placeholders})
              and post_count >= ?
              {nsfw_clause}
              {blacklist_clause}
            order by post_count desc, name collate nocase asc
            limit ?
            """,
            [category, *ids, min_post_count, *blacklist_params, max(1, int(limit))],
        ).fetchall()

    def _random_field_option_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        categories: list[dict],
        *,
        allow_nsfw: bool,
        min_post_count: int,
        count: int,
        seed: int,
        blacklist_tags: tuple[str, ...] = (),
        taxonomy_blacklist: tuple[str, ...] = (),
        max_count: int = 50,
    ):
        clauses = self._field_filter_clauses(taxonomy_ids, categories)
        if not clauses:
            return []
        where_parts = []
        params = []
        for clause, clause_params in clauses:
            where_parts.append(f"({clause})")
            params.extend(clause_params)
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        blacklist_clause, blacklist_params = self._blacklist_sql_clause("", blacklist_tags)
        taxonomy_blacklist_clause, taxonomy_blacklist_params = self._taxonomy_blacklist_sql_clause("", taxonomy_blacklist)
        requested = max(1, min(max(1, int(max_count or 50)), int(count or 1)))
        where_sql = f"""
            where ({" or ".join(where_parts)})
              and post_count >= ?
              {nsfw_clause}
              {blacklist_clause}
              {taxonomy_blacklist_clause}
        """
        candidate_rows = conn.execute(
            f"""
            select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
            from danbooru_tags
            {where_sql}
            order by name collate nocase asc
            """,
            [*params, min_post_count, *blacklist_params, *taxonomy_blacklist_params],
        ).fetchall()
        if not candidate_rows:
            return []

        limit = min(requested, len(candidate_rows))
        rng = random.Random(int(seed)) if int(seed or 0) else random.SystemRandom()
        return rng.sample(list(candidate_rows), limit)

    def _search_field_option_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        categories: list[dict],
        *,
        query: str,
        language: str,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
        offset: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        candidate_rows = []
        normalized_query = normalize_tag_name(query)
        label_query = str(query or "").strip().lower()
        search_cap = max(500, offset + limit * 4)

        if normalized_query and language in {"英文", "中英文"}:
            for mode in ("exact", "prefix", "contains"):
                if mode == "contains":
                    tag_names = self._query_fts_tag_names(conn, normalized_query, limit=search_cap * 2)
                    if tag_names:
                        candidate_rows.extend(
                            self._query_rows_by_names(
                                conn,
                                tag_names,
                                taxonomy_ids,
                                categories,
                                allow_nsfw=allow_nsfw,
                                min_post_count=min_post_count,
                                blacklist_tags=blacklist_tags,
                            )
                        )
                        if len(self._dedupe_sort_rows(candidate_rows)) >= offset + limit:
                            break
                rows = self._query_name_search_rows(
                    conn,
                    taxonomy_ids,
                    categories,
                    normalized_query,
                    mode=mode,
                    allow_nsfw=allow_nsfw,
                    min_post_count=min_post_count,
                    limit=search_cap,
                    blacklist_tags=blacklist_tags,
                )
                candidate_rows.extend(rows)
                if mode == "prefix" and len(rows) >= offset + limit:
                    break
                if mode != "exact" and len(self._dedupe_sort_rows(candidate_rows)) >= offset + limit:
                    break

        if label_query and language in {"中文", "中英文"}:
            for mode in ("exact", "prefix", "contains"):
                if mode == "contains":
                    tag_names = self._query_fts_tag_names(conn, label_query, limit=search_cap * 2)
                    if tag_names:
                        candidate_rows.extend(
                            self._query_rows_by_names(
                                conn,
                                tag_names,
                                taxonomy_ids,
                                categories,
                                allow_nsfw=allow_nsfw,
                                min_post_count=min_post_count,
                                blacklist_tags=blacklist_tags,
                            )
                        )
                        if len(self._dedupe_sort_rows(candidate_rows)) >= offset + limit:
                            break
                tag_names = self._query_localization_tag_names(
                    conn,
                    label_query,
                    mode=mode,
                    limit=search_cap * 2,
                )
                if tag_names:
                    candidate_rows.extend(
                        self._query_rows_by_names(
                            conn,
                            tag_names,
                            taxonomy_ids,
                            categories,
                            allow_nsfw=allow_nsfw,
                            min_post_count=min_post_count,
                            blacklist_tags=blacklist_tags,
                        )
                    )
                if mode == "prefix" and len(tag_names) >= offset + limit:
                    break
                if mode != "exact" and len(self._dedupe_sort_rows(candidate_rows)) >= offset + limit:
                    break

        rows = self._dedupe_sort_rows(candidate_rows, query=normalized_query)
        return rows[offset : offset + limit]

    def _query_taxonomy_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        *,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        if not taxonomy_ids:
            return []
        placeholders = ",".join("?" for _ in taxonomy_ids)
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        blacklist_clause, blacklist_params = self._blacklist_sql_clause("", blacklist_tags)
        table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_taxonomy")
        return conn.execute(
            f"""
            select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
            from {table}
            where taxonomy_id in ({placeholders})
              and post_count >= ?
              {nsfw_clause}
              {blacklist_clause}
            order by post_count desc, name collate nocase asc
            limit ?
            """,
            [*taxonomy_ids, min_post_count, *blacklist_params, max(1, int(limit))],
        ).fetchall()

    def _query_category_rows(
        self,
        conn,
        category_spec: dict,
        *,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        blacklist_clause, blacklist_params = self._blacklist_sql_clause("", blacklist_tags)
        semantic_clause = ""
        params = [int(category_spec["category"]), min_post_count]
        semantic_category = category_spec.get("semantic_category")
        if semantic_category:
            semantic_clause = "and semantic_category_key = ?"
            params.append(str(semantic_category))
        table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_category_post_count")
        return conn.execute(
            f"""
            select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
            from {table}
            where category = ?
              and post_count >= ?
              {semantic_clause}
              {nsfw_clause}
              {blacklist_clause}
            order by post_count desc, name collate nocase asc
            limit ?
            """,
            [*params, *blacklist_params, max(1, int(limit))],
        ).fetchall()

    def _query_fts_tag_names(self, conn, query: str, *, limit: int) -> list[str]:
        if not query or not self._has_table(conn, "danbooru_tag_search_fts"):
            return []
        terms = [
            part
            for part in re.split(r"[\s_]+", str(query or "").strip())
            if part
        ]
        if not terms:
            return []
        fts_query = " ".join(f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms)
        try:
            rows = conn.execute(
                """
                select tag_name
                from danbooru_tag_search_fts
                where danbooru_tag_search_fts match ?
                limit ?
                """,
                (fts_query, max(1, int(limit))),
            ).fetchall()
        except sqlite3.DatabaseError:
            return []
        names = []
        seen = set()
        for row in rows:
            tag = row["tag_name"]
            if tag in seen:
                continue
            seen.add(tag)
            names.append(tag)
        return names

    def _query_name_search_rows(
        self,
        conn,
        taxonomy_ids: list[str],
        categories: list[dict],
        normalized_query: str,
        *,
        mode: str,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        if not normalized_query:
            return []
        if mode == "exact":
            name_clause = "normalized_name = ?"
            name_params = [normalized_query]
        elif mode == "prefix":
            name_clause = "normalized_name >= ? and normalized_name < ?"
            name_params = [normalized_query, _prefix_upper_bound(normalized_query)]
        else:
            name_clause = "normalized_name like ?"
            name_params = ["%" + normalized_query + "%"]
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        blacklist_clause, blacklist_params = self._blacklist_sql_clause("", blacklist_tags)
        rows = []
        table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_normalized_name")
        for field_clause, field_params in self._field_filter_clauses(taxonomy_ids, categories):
            rows.extend(
                conn.execute(
                    f"""
                    select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
                    from {table}
                    where {name_clause}
                      and {field_clause}
                      and post_count >= ?
                      {nsfw_clause}
                      {blacklist_clause}
                    order by post_count desc, name collate nocase asc
                    limit ?
                    """,
                    [*name_params, *field_params, min_post_count, *blacklist_params, max(1, int(limit))],
                ).fetchall()
            )
        return rows

    def _query_localization_tag_names(self, conn, label_query: str, *, mode: str, limit: int) -> list[str]:
        if not label_query:
            return []
        if mode == "exact":
            clause = "normalized_label = ?"
            params = [self.locale, label_query]
        elif mode == "prefix":
            clause = "normalized_label >= ? and normalized_label < ?"
            params = [self.locale, label_query, _prefix_upper_bound(label_query)]
        else:
            clause = "normalized_label like ?"
            params = [self.locale, "%" + label_query + "%"]
        rows = conn.execute(
            f"""
            select tag_name
            from {self._indexed_table(conn, "danbooru_tag_localizations", "idx_danbooru_tag_localizations_lookup")}
            where locale = ?
              and {clause}
              and kind in ('primary', 'alias')
            limit ?
            """,
            [*params, max(1, int(limit))],
        ).fetchall()
        tag_names = []
        seen = set()
        for row in rows:
            tag = row["tag_name"]
            if tag in seen:
                continue
            seen.add(tag)
            tag_names.append(tag)
        return tag_names

    def _query_rows_by_names(
        self,
        conn,
        tag_names: list[str],
        taxonomy_ids: list[str],
        categories: list[dict],
        *,
        allow_nsfw: bool,
        min_post_count: int,
        blacklist_tags: tuple[str, ...] = (),
    ):
        names = [str(tag_name or "").strip() for tag_name in tag_names if str(tag_name or "").strip()]
        if not names:
            return []
        rows_by_name = {}
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        blacklist_clause, blacklist_params = self._blacklist_sql_clause("", blacklist_tags)
        for chunk_start in range(0, len(names), 500):
            chunk = names[chunk_start : chunk_start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
                from danbooru_tags
                where name in ({placeholders})
                  and post_count >= ?
                  {nsfw_clause}
                  {blacklist_clause}
                """,
                [*chunk, min_post_count, *blacklist_params],
            ).fetchall()
            for row in rows:
                if self._row_matches_field(row, taxonomy_ids, categories):
                    rows_by_name[row["name"]] = row
        return [rows_by_name[name] for name in names if name in rows_by_name]

    def _row_matches_field(self, row, taxonomy_ids: list[str], categories: list[dict]) -> bool:
        if row["taxonomy_id"] in taxonomy_ids:
            return True
        for category_spec in categories:
            if row["category"] != int(category_spec["category"]):
                continue
            semantic_category = category_spec.get("semantic_category")
            if semantic_category and row["semantic_category_key"] != semantic_category:
                continue
            return True
        return False

    def _field_filter_clauses(self, taxonomy_ids: list[str], categories: list[dict]):
        clauses = []
        if taxonomy_ids:
            placeholders = ",".join("?" for _ in taxonomy_ids)
            clauses.append((f"taxonomy_id in ({placeholders})", list(taxonomy_ids)))
        for category_spec in categories:
            params = [int(category_spec["category"])]
            clause = "category = ?"
            semantic_category = category_spec.get("semantic_category")
            if semantic_category:
                clause += " and semantic_category_key = ?"
                params.append(str(semantic_category))
            clauses.append((clause, params))
        return clauses

    def _blacklist_sql_clause(self, table_alias: str, blacklist_tags: tuple[str, ...]):
        tags = normalize_tag_blacklist(blacklist_tags)
        if not tags:
            return "", []
        prefix = f"{table_alias}." if table_alias else ""
        placeholders = ",".join("?" for _ in tags)
        return f"and {prefix}normalized_name not in ({placeholders})", list(tags)

    def _taxonomy_blacklist_sql_clause(self, table_alias: str, taxonomy_blacklist: tuple[str, ...]):
        items = normalize_taxonomy_blacklist(taxonomy_blacklist)
        if not items:
            return "", []
        prefix = f"{table_alias}." if table_alias else ""
        clauses = []
        params = []
        for item in items:
            clauses.append(f"({prefix}taxonomy_id = ? or {prefix}taxonomy_id like ?)")
            params.extend([item, f"{item}.%"])
        return f"and not ({' or '.join(clauses)})", params

    def _filter_random_taxonomy_blacklist(self, rows, taxonomy_blacklist: tuple[str, ...]):
        items = normalize_taxonomy_blacklist(taxonomy_blacklist)
        if not items:
            return list(rows)
        result = []
        for row in rows:
            taxonomy_id = str(row["taxonomy_id"] or "")
            if any(taxonomy_id == item or taxonomy_id.startswith(f"{item}.") for item in items):
                continue
            result.append(row)
        return result

    def _primary_labels_for_tags(self, conn, tag_names: list[str]) -> dict[str, str]:
        if not tag_names:
            return {}
        labels = {}
        for chunk_start in range(0, len(tag_names), 500):
            chunk = tag_names[chunk_start : chunk_start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                select tag_name, label
                from danbooru_tag_localizations
                where locale = ?
                  and kind = 'primary'
                  and tag_name in ({placeholders})
                """,
                [self.locale, *chunk],
            ).fetchall()
            for row in rows:
                labels[row["tag_name"]] = row["label"]
        return labels

    def _dedupe_sort_rows(self, rows, *, query: str = "") -> list:
        best = {}
        for row in rows:
            name = row["name"]
            current = best.get(name)
            if current is None or int(row["post_count"] or 0) > int(current["post_count"] or 0):
                best[name] = row
        return sorted(
            best.values(),
            key=lambda row: (
                0 if query and row["name"] == query else 1,
                0 if query and str(row["name"]).startswith(query) else 1,
                -int(row["post_count"] or 0),
                str(row["name"]).lower(),
            ),
        )

    def _resolve_one(
        self,
        conn,
        query: str,
        *,
        match_mode: str,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
    ) -> list[ResolvedTag]:
        normalized = normalize_tag_name(query)
        label_query = str(query or "").strip().lower()
        mode = match_mode if match_mode in {"exact", "prefix", "contains"} else "exact"
        if mode == "exact":
            return self._resolve_exact(
                conn,
                query,
                normalized=normalized,
                label_query=label_query,
                allow_nsfw=allow_nsfw,
                min_post_count=min_post_count,
                limit=limit,
            )

        op_value = normalized
        label_value = label_query
        name_clause = "t.normalized_name like ?"
        label_clause = "l.normalized_label like ?"
        if mode == "prefix":
            op_value = normalized + "%"
            label_value = label_query + "%"
        elif mode == "contains":
            op_value = "%" + normalized + "%"
            label_value = "%" + label_query + "%"

        nsfw_clause = "" if allow_nsfw else "and t.is_nsfw = 0"
        rows = conn.execute(
            f"""
            select
                t.name,
                t.category,
                t.post_count,
                t.semantic_category_key,
                t.taxonomy_id,
                t.is_nsfw,
                coalesce(lp.label, l.label, t.name) as label,
                case
                    when {name_clause} then 'tag'
                    when {label_clause} then 'localization'
                    else 'dictionary'
                end as source
            from danbooru_tags t
            left join danbooru_tag_localizations lp
                on lp.tag_name = t.name
                and lp.locale = ?
                and lp.kind = 'primary'
            left join danbooru_tag_localizations l
                on l.tag_name = t.name
                and l.locale = ?
                and l.kind in ('primary', 'alias')
            where t.post_count >= ?
              {nsfw_clause}
              and ({name_clause} or l.normalized_label = ? or {label_clause})
            group by t.name
            order by
                case when t.normalized_name = ? then 0 else 1 end,
                case when l.normalized_label = ? then 0 else 1 end,
                t.post_count desc,
                t.name collate nocase asc
            limit ?
            """,
            [
                op_value,
                label_value,
                self.locale,
                self.locale,
                min_post_count,
                op_value,
                label_query,
                label_value,
                normalized,
                label_query,
                max(1, int(limit)),
            ],
        ).fetchall()

        return self._rows_to_terms(query, rows)

    def _search_by_name(
        self,
        conn,
        query: str,
        *,
        match_mode: str,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
    ) -> list[ResolvedTag]:
        normalized = normalize_tag_name(query)
        if match_mode == "exact":
            value = normalized
            clause = "t.normalized_name = ?"
        elif match_mode == "prefix":
            value = normalized + "%"
            clause = "t.normalized_name like ?"
        else:
            value = "%" + normalized + "%"
            clause = "t.normalized_name like ?"
        nsfw_clause = "" if allow_nsfw else "and t.is_nsfw = 0"
        rows = conn.execute(
            f"""
            select
                t.name,
                t.category,
                t.post_count,
                t.semantic_category_key,
                t.taxonomy_id,
                t.is_nsfw,
                coalesce(lp.label, t.name) as label,
                'tag' as source
            from danbooru_tags t
            left join danbooru_tag_localizations lp
                on lp.tag_name = t.name
                and lp.locale = ?
                and lp.kind = 'primary'
            where {clause}
              and t.post_count >= ?
              {nsfw_clause}
            order by
                case when t.normalized_name = ? then 0 else 1 end,
                t.post_count desc,
                t.name collate nocase asc
            limit ?
            """,
            (self.locale, value, min_post_count, normalized, max(1, int(limit))),
        ).fetchall()
        return self._rows_to_terms(query, rows)

    def _search_by_label(
        self,
        conn,
        query: str,
        *,
        match_mode: str,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
    ) -> list[ResolvedTag]:
        label_query = str(query or "").strip().lower()
        if match_mode == "exact":
            value = label_query
            clause = "l.normalized_label = ?"
        elif match_mode == "prefix":
            value = label_query + "%"
            clause = "l.normalized_label like ?"
        else:
            value = "%" + label_query + "%"
            clause = "l.normalized_label like ?"
        nsfw_clause = "" if allow_nsfw else "and t.is_nsfw = 0"
        rows = conn.execute(
            f"""
            select
                t.name,
                t.category,
                t.post_count,
                t.semantic_category_key,
                t.taxonomy_id,
                t.is_nsfw,
                coalesce(lp.label, l.label, t.name) as label,
                'localization' as source
            from danbooru_tag_localizations l
            join danbooru_tags t on t.name = l.tag_name
            left join danbooru_tag_localizations lp
                on lp.tag_name = t.name
                and lp.locale = ?
                and lp.kind = 'primary'
            where l.locale = ?
              and {clause}
              and l.kind in ('primary', 'alias')
              and t.post_count >= ?
              {nsfw_clause}
            group by t.name
            order by
                case when l.normalized_label = ? then 0 else 1 end,
                case when l.kind = 'primary' then 0 else 1 end,
                t.post_count desc,
                t.name collate nocase asc
            limit ?
            """,
            (
                self.locale,
                self.locale,
                value,
                min_post_count,
                label_query,
                max(1, int(limit)),
            ),
        ).fetchall()
        return self._rows_to_terms(query, rows)

    def _resolve_exact(
        self,
        conn,
        query: str,
        *,
        normalized: str,
        label_query: str,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
    ) -> list[ResolvedTag]:
        nsfw_clause = "" if allow_nsfw else "and t.is_nsfw = 0"
        rows = conn.execute(
            f"""
            select
                t.name,
                t.category,
                t.post_count,
                t.semantic_category_key,
                t.taxonomy_id,
                t.is_nsfw,
                coalesce(lp.label, t.name) as label,
                'tag' as source
            from danbooru_tags t
            left join danbooru_tag_localizations lp
                on lp.tag_name = t.name
                and lp.locale = ?
                and lp.kind = 'primary'
            where t.normalized_name = ?
              and t.post_count >= ?
              {nsfw_clause}
            order by t.post_count desc, t.name collate nocase asc
            limit ?
            """,
            (self.locale, normalized, min_post_count, max(1, int(limit))),
        ).fetchall()
        if rows:
            return self._rows_to_terms(query, rows)

        rows = conn.execute(
            f"""
            select
                t.name,
                t.category,
                t.post_count,
                t.semantic_category_key,
                t.taxonomy_id,
                t.is_nsfw,
                coalesce(lp.label, l.label, t.name) as label,
                'localization' as source
            from danbooru_tag_localizations l
            join danbooru_tags t on t.name = l.tag_name
            left join danbooru_tag_localizations lp
                on lp.tag_name = t.name
                and lp.locale = ?
                and lp.kind = 'primary'
            where l.locale = ?
              and l.normalized_label = ?
              and l.kind in ('primary', 'alias')
              and t.post_count >= ?
              {nsfw_clause}
            group by t.name
            order by
                case when l.kind = 'primary' then 0 else 1 end,
                t.post_count desc,
                t.name collate nocase asc
            limit ?
            """,
            (
                self.locale,
                self.locale,
                label_query,
                min_post_count,
                max(1, int(limit)),
            ),
        ).fetchall()
        return self._rows_to_terms(query, rows)

    def _rows_to_terms(self, query: str, rows) -> list[ResolvedTag]:
        return [
            ResolvedTag(
                query=query,
                tag=row["name"],
                label=row["label"] or row["name"],
                category=row["category"],
                semantic_category=row["semantic_category_key"],
                taxonomy_id=row["taxonomy_id"],
                post_count=int(row["post_count"] or 0),
                is_nsfw=bool(row["is_nsfw"]),
                source=row["source"],
            )
            for row in rows
        ]


def _request_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "是", "启用"}


def _request_int(value, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _json_response(web, payload, status: int = 200):
    return web.json_response(
        payload,
        status=status,
        dumps=lambda data: json.dumps(data, ensure_ascii=False),
    )


def _select_db_file_dialog(initial_path: str = "") -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError(f"无法加载 Tk 文件选择窗口：{exc}") from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        initial = str(initial_path or "").strip().strip('"')
        initial_dir = ""
        initial_file = ""
        if initial:
            initial_candidate = Path(initial)
            if initial_candidate.is_dir():
                initial_dir = str(initial_candidate)
            else:
                parent = initial_candidate.parent
                initial_dir = str(parent) if parent.exists() else ""
                initial_file = initial_candidate.name
        path = filedialog.askopenfilename(
            parent=root,
            title="选择 Danbooru 词典数据库",
            initialdir=initial_dir or None,
            initialfile=initial_file or None,
            filetypes=[
                ("SQLite DB", "*.db *.sqlite *.sqlite3"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return ""
        return normalize_danbooru_db_path(path)
    except Exception as exc:
        raise RuntimeError(f"DB文件选择失败：{exc}") from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def _register_galiais_nodes_danbooru_routes() -> None:
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        return

    if getattr(PromptServer.instance, "_galiais_nodes_danbooru_routes_registered", False):
        return
    PromptServer.instance._galiais_nodes_danbooru_routes_registered = True
    routes = PromptServer.instance.routes

    @routes.get("/galiais-nodes/danbooru/options")
    async def galiais_nodes_danbooru_options(request):
        query = request.rel_url.query
        field = str(query.get("field", "")).strip()
        if not field:
            return _json_response(web, {"error": "missing field", "items": []}, status=400)
        try:
            payload = DanbooruDictionary(query.get("db_path", "")).option_records_for_field(
                field,
                query=query.get("q", ""),
                language=query.get("language", "中英文"),
                allow_nsfw=_request_bool(query.get("allow_nsfw"), False),
                min_post_count=_request_int(query.get("min_post_count"), 0, minimum=0),
                limit=_request_int(query.get("limit"), 50, minimum=1, maximum=200),
                offset=_request_int(query.get("offset"), 0, minimum=0),
                blacklist=query.get("blacklist", ""),
                mark_blacklist_only=True,
            )
        except Exception as exc:
            return _json_response(
                web,
                {"error": str(exc), "field": field, "items": [], "has_more": False},
                status=500,
            )
        return _json_response(web, payload)

    @routes.get("/galiais-nodes/danbooru/random")
    async def galiais_nodes_danbooru_random(request):
        query = request.rel_url.query
        field = str(query.get("field", "")).strip()
        taxonomy_id = str(query.get("taxonomy_id", "")).strip()
        if not field and not taxonomy_id:
            return _json_response(web, {"error": "missing field", "items": []}, status=400)
        try:
            items = DanbooruDictionary(query.get("db_path", "")).random_options_for_field(
                field or "__taxonomy_id__",
                taxonomy_id=taxonomy_id,
                count=_request_int(query.get("count"), 1, minimum=1, maximum=50),
                seed=_request_int(query.get("seed"), 0, minimum=0, maximum=0xFFFFFFFF),
                allow_nsfw=_request_bool(query.get("allow_nsfw"), False),
                min_post_count=_request_int(query.get("min_post_count"), 0, minimum=0),
                query=query.get("q", ""),
                language=query.get("language", "中英文"),
                blacklist=query.get("blacklist", ""),
                taxonomy_blacklist=query.get("taxonomy_blacklist", ""),
            )
            payload = {
                "field": field or "__taxonomy_id__",
                "taxonomy_id": taxonomy_id,
                "items": items,
                "count": len(items),
            }
        except Exception as exc:
            return _json_response(
                web,
                {"error": str(exc), "field": field, "taxonomy_id": taxonomy_id, "items": []},
                status=500,
            )
        return _json_response(web, payload)

    @routes.get("/galiais-nodes/danbooru/tree")
    async def galiais_nodes_danbooru_tree(request):
        query = request.rel_url.query
        field = str(query.get("field", "")).strip()
        if not field:
            return _json_response(web, {"error": "missing field", "nodes": []}, status=400)
        try:
            payload = DanbooruDictionary(query.get("db_path", "")).taxonomy_tree_for_field(
                field,
                allow_nsfw=_request_bool(query.get("allow_nsfw"), False),
                min_post_count=_request_int(query.get("min_post_count"), 0, minimum=0),
                include_counts=_request_bool(query.get("include_counts"), True),
            )
        except Exception as exc:
            return _json_response(
                web,
                {"error": str(exc), "field": field, "nodes": [], "leaves": []},
                status=500,
            )
        return _json_response(web, payload)

    @routes.get("/galiais-nodes/danbooru/all_taxonomy_tree")
    async def galiais_nodes_danbooru_all_taxonomy_tree(request):
        query = request.rel_url.query
        try:
            payload = DanbooruDictionary(query.get("db_path", "")).all_taxonomy_tree(
                allow_nsfw=_request_bool(query.get("allow_nsfw"), False),
                min_post_count=_request_int(query.get("min_post_count"), 0, minimum=0),
                include_counts=_request_bool(query.get("include_counts"), False),
            )
        except Exception as exc:
            return _json_response(
                web,
                {"error": str(exc), "field": "__all_taxonomy__", "nodes": [], "leaves": []},
                status=500,
            )
        return _json_response(web, payload)

    @routes.get("/galiais-nodes/danbooru/fields")
    async def galiais_nodes_danbooru_fields(request):
        return _json_response(
            web,
            {
                "fields": sorted(
                    {
                        key: {
                            "field": value["field"],
                            "groups": value.get("groups", []),
                            "taxonomy_count": len(value.get("taxonomy_ids", [])),
                            "category_count": len(value.get("categories", [])),
                        }
                        for key, value in GALIAIS_NODES_DANBOORU_FIELD_REGISTRY.items()
                    }.values(),
                    key=lambda item: item["field"],
                )
            },
        )

    @routes.get("/galiais-nodes/danbooru/select_db")
    async def galiais_nodes_danbooru_select_db(request):
        query = request.rel_url.query
        try:
            path = _select_db_file_dialog(query.get("current", ""))
        except Exception as exc:
            return _json_response(web, {"error": str(exc), "path": ""}, status=500)
        return _json_response(web, {"path": path})

    @routes.get("/galiais-nodes/danbooru/tag_blacklist")
    async def galiais_nodes_danbooru_tag_blacklist(request):
        tags = _read_global_tag_blacklist()
        return _json_response(web, {"tags": list(tags), "count": len(tags)})

    @routes.post("/galiais-nodes/danbooru/tag_blacklist")
    async def galiais_nodes_danbooru_update_tag_blacklist(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = str(body.get("action") or "add").strip().lower()
        tags = body.get("tags", body.get("tag", ""))
        try:
            if action == "clear":
                next_tags = _write_global_tag_blacklist(())
            elif action in {"remove", "delete"}:
                next_tags = remove_global_tag_blacklist(tags)
            else:
                next_tags = add_global_tag_blacklist(tags)
        except Exception as exc:
            return _json_response(web, {"error": str(exc), "tags": []}, status=500)
        _DANBOORU_OPTION_CACHE.clear()
        return _json_response(web, {"tags": list(next_tags), "count": len(next_tags)})

    @routes.get("/galiais-nodes/danbooru/random_taxonomy_blacklist")
    async def galiais_nodes_danbooru_random_taxonomy_blacklist(request):
        items = _read_global_random_taxonomy_blacklist()
        return _json_response(web, {"taxonomy_ids": list(items), "count": len(items), "scope": "random_only"})

    @routes.post("/galiais-nodes/danbooru/random_taxonomy_blacklist")
    async def galiais_nodes_danbooru_update_random_taxonomy_blacklist(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = str(body.get("action") or "add").strip().lower()
        items = body.get("taxonomy_ids", body.get("taxonomy_id", body.get("items", "")))
        try:
            if action == "clear":
                next_items = _write_global_random_taxonomy_blacklist(())
            elif action in {"remove", "delete"}:
                next_items = remove_global_random_taxonomy_blacklist(items)
            else:
                next_items = add_global_random_taxonomy_blacklist(items)
        except Exception as exc:
            return _json_response(web, {"error": str(exc), "taxonomy_ids": []}, status=500)
        _DANBOORU_OPTION_CACHE.clear()
        return _json_response(web, {"taxonomy_ids": list(next_items), "count": len(next_items), "scope": "random_only"})

    @routes.post("/galiais-nodes/ai/models")
    async def galiais_nodes_ai_models(request):
        try:
            body = await request.json()
            provider = {
                "base_url": body.get("base_url", ""),
                "api_key": body.get("api_key", ""),
                "api_mode": body.get("api_mode", "自动"),
                "timeout": _request_int(body.get("timeout"), 30, minimum=1, maximum=300),
            }
            models = OpenAICompatibleClient().list_models(provider)
            return _json_response(web, {"models": models, "count": len(models)})
        except Exception as exc:
            return _json_response(web, {"error": str(exc), "models": []}, status=500)


_register_galiais_nodes_danbooru_routes()
