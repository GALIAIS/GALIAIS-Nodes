import json
import os
import random
import re
import sqlite3
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_DANBOORU_DB_PATH = ""
GALIAIS_NODES_SCHEMA_VERSION = "2.0.0"
GALIAIS_NODES_COMPOSER_VERSION = "2.0.0"
GALIAIS_NODES_TAXONOMY_VERSION = "danbooru-taxonomy-next"
_DANBOORU_CACHE_MISS = object()
_DANBOORU_OPTION_CACHE_LIMIT = 256
_DANBOORU_TREE_CACHE_LIMIT = 96
_DANBOORU_OPTION_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_DANBOORU_TREE_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_DANBOORU_RUNTIME_PATH_CACHE: dict[tuple[str, int, int], str] = {}


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
        reasoning_mode = str(provider_config.get("reasoning_mode") or "关闭")
        if reasoning_mode == "开启":
            effort = str(provider_config.get("reasoning_effort") or "").strip()
            if effort:
                body["reasoning_effort"] = effort
        if stream:
            return _stream_json_http_request(
                _url_join(base_url, "chat/completions"),
                provider_config.get("api_key", ""),
                body,
                timeout=int(provider_config.get("timeout") or 30),
            )
        payload = _json_http_request(
            "POST",
            _url_join(base_url, "chat/completions"),
            provider_config.get("api_key", ""),
            payload=body,
            timeout=int(provider_config.get("timeout") or 30),
        )
        choices = payload.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            content = str(message.get("content") or choices[0].get("text") or "")
        return {"content": content, "raw": payload}


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


def _build_positive_enrichment_messages(
    tags: str,
    context: str,
    language: str,
    detail_level: str,
    tag_context: dict | None = None,
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a professional anime image prompt analyst. "
                "Analyze Danbooru tags, their taxonomy, translations, safety flags, and visual roles. "
                "Write a compact natural-language positive prompt supplement that improves character, scene, "
                "composition, material, and mood readability. "
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
                    "context": str(context or ""),
                    "output_language": str(language or "中文"),
                    "detail_level": str(detail_level or "精炼"),
                    "danbooru_context": tag_context or {},
                    "requirements": [
                        "Preserve the meaning of the input tags.",
                        "Add only useful visual natural language.",
                        "Avoid contradicting the tags.",
                        "Use taxonomy and Chinese labels to infer visual intent when they are available.",
                        "Prefer one concise natural-language phrase over repeating tags one by one.",
                        "Keep the sentence suitable for image generation positive prompts.",
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]


CONFLICT_GROUPS = [
    ("情绪冲突", {"smile", "happy", "laughing"}, {"crying", "sad", "tears"}),
    ("眼睛状态冲突", {"open_eyes", "looking_at_viewer"}, {"closed_eyes", "eyes_closed"}),
    ("背景密度冲突", {"simple_background", "white_background"}, {"detailed_background", "scenery"}),
    ("裸露与保守服装冲突", {"nude", "topless", "naked"}, {"fully_clothed", "school_uniform"}),
]

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
        return conn

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
    ) -> dict:
        spec = danbooru_field_spec(field)
        safe_limit = min(200, max(1, int(limit or 50)))
        safe_offset = max(0, int(offset or 0))
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
                limit=safe_limit + 1,
                offset=safe_offset,
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
    ) -> list[dict]:
        spec = danbooru_field_spec(field)
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
                candidate_limit = max(120, min(2500, safe_count * 80))
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
                )
                rng = random.Random(int(seed)) if int(seed or 0) else random.SystemRandom()
                rows = list(rows)
                rng.shuffle(rows)
                rows = rows[:safe_count]
            else:
                rows = self._random_field_option_rows(
                    conn,
                    ids,
                    categories,
                    allow_nsfw=allow_nsfw,
                    min_post_count=int(min_post_count or 0),
                    count=safe_count,
                    seed=int(seed or 0),
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
            leaf_node = ensure_node(
                (domain, facet, group, leaf),
                leaf_label,
                row["taxonomy_id"],
            )
            leaf_node["taxonomy_id"] = row["taxonomy_id"]
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
            )
        return self._browse_field_option_rows(
            conn,
            taxonomy_ids,
            categories,
            allow_nsfw=allow_nsfw,
            min_post_count=min_post_count,
            limit=limit,
            offset=offset,
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
    ):
        ids = [str(item).strip() for item in taxonomy_ids if str(item).strip()]
        if not ids or not self._has_table(conn, "taxonomy_option_cache"):
            return []
        placeholders = ",".join("?" for _ in ids)
        nsfw_clause = "" if allow_nsfw else "and c.is_nsfw = 0"
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
            order by c.post_count desc, t.name collate nocase asc
            limit ? offset ?
            """,
            [*ids, min_post_count, max(1, int(limit)), max(0, int(offset))],
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
        table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_category_post_count")
        return conn.execute(
            f"""
            select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
            from {table}
            where category = ?
              and taxonomy_id in ({placeholders})
              and post_count >= ?
              {nsfw_clause}
            order by post_count desc, name collate nocase asc
            limit ?
            """,
            [category, *ids, min_post_count, max(1, int(limit))],
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
        requested = max(1, min(50, int(count or 1)))
        where_sql = f"""
            where ({" or ".join(where_parts)})
              and post_count >= ?
              {nsfw_clause}
        """
        total = int(conn.execute(
            f"""
            select count(*)
            from danbooru_tags
            {where_sql}
            """,
            [*params, min_post_count],
        ).fetchone()[0])
        if total <= 0:
            return []

        limit = min(requested, total)
        rng = random.Random(int(seed)) if int(seed or 0) else random.SystemRandom()
        offsets = []
        seen_offsets = set()
        while len(offsets) < limit:
            offset = rng.randrange(total)
            if offset in seen_offsets:
                continue
            seen_offsets.add(offset)
            offsets.append(offset)

        rows = []
        for offset in offsets:
            row = conn.execute(
                f"""
                select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
                from danbooru_tags
                {where_sql}
                order by name collate nocase asc
                limit 1 offset ?
                """,
                [*params, min_post_count, offset],
            ).fetchone()
            if row is not None:
                rows.append(row)
        return rows

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
    ):
        if not taxonomy_ids:
            return []
        placeholders = ",".join("?" for _ in taxonomy_ids)
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_taxonomy")
        return conn.execute(
            f"""
            select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
            from {table}
            where taxonomy_id in ({placeholders})
              and post_count >= ?
              {nsfw_clause}
            order by post_count desc, name collate nocase asc
            limit ?
            """,
            [*taxonomy_ids, min_post_count, max(1, int(limit))],
        ).fetchall()

    def _query_category_rows(
        self,
        conn,
        category_spec: dict,
        *,
        allow_nsfw: bool,
        min_post_count: int,
        limit: int,
    ):
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
        semantic_clause = ""
        params = [int(category_spec["category"]), min_post_count]
        semantic_category = category_spec.get("semantic_category")
        if semantic_category:
            semantic_clause = "and semantic_category_key = ?"
            params.append(str(semantic_category))
        params.append(max(1, int(limit)))
        table = self._indexed_table(conn, "danbooru_tags", "idx_danbooru_tags_category_post_count")
        return conn.execute(
            f"""
            select name, category, post_count, semantic_category_key, taxonomy_id, is_nsfw
            from {table}
            where category = ?
              and post_count >= ?
              {semantic_clause}
              {nsfw_clause}
            order by post_count desc, name collate nocase asc
            limit ?
            """,
            params,
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
                    order by post_count desc, name collate nocase asc
                    limit ?
                    """,
                    [*name_params, *field_params, min_post_count, max(1, int(limit))],
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
    ):
        names = [str(tag_name or "").strip() for tag_name in tag_names if str(tag_name or "").strip()]
        if not names:
            return []
        rows_by_name = {}
        nsfw_clause = "" if allow_nsfw else "and is_nsfw = 0"
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
                """,
                [*chunk, min_post_count],
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


class GaliaisNodesDanbooruDBLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "语言": (["zh-CN"], {"default": "zh-CN"}),
                "启动时验证": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("GALIAIS_NODES_DANBOORU_DB", "STRING", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("DB", "DB路径", "词典信息JSON", "总词条", "已翻译", "模板数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, DB路径, 语言, 启动时验证):
        selected_db_path = resolve_danbooru_db_path(DB路径)
        db_path = preferred_danbooru_runtime_path(selected_db_path)
        payload = {
            "db_path": db_path,
            "selected_db_path": selected_db_path,
            "locale": 语言,
            "auto_runtime": db_path != selected_db_path,
        }
        total_tags = 0
        translated_tags = 0
        template_count = 0
        if 启动时验证:
            stats = DanbooruDictionary(db_path, locale=语言).stats()
            payload.update(stats)
            payload["db_path"] = db_path
            payload["selected_db_path"] = selected_db_path
            payload["source_db_path"] = selected_db_path
            payload["auto_runtime"] = db_path != selected_db_path
            total_tags = stats["total_tags"]
            translated_tags = stats["translated_tags"]
            template_count = stats["template_count"]
        return (
            payload,
            db_path,
            _metadata_json(payload),
            total_tags,
            translated_tags,
            template_count,
        )


class GaliaisNodesProjectConfig:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "默认语言": (["zh-CN"], {"default": "zh-CN"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "默认输出格式": (["Anima", "通用Danbooru"], {"default": "Anima"}),
                "默认去重": ("BOOLEAN", {"default": True}),
                "默认负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "标准"}),
                "AI服务商URL": ("STRING", {"default": "", "multiline": False}),
                "AI密钥或环境变量": ("STRING", {"default": "", "multiline": False}),
                "AI模型": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_PROJECT_CONFIG", "GALIAIS_NODES_AI_PROVIDER", "STRING")
    RETURN_NAMES = ("项目配置", "AI服务商", "配置JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/config"

    def run(self, DB路径, 默认语言, 允许NSFW, 默认输出格式, 默认去重, 默认负面预设, AI服务商URL, AI密钥或环境变量, AI模型, DB=None):
        db_path = optional_danbooru_db_path(DB路径, DB)
        api_key, key_source = _resolve_api_key(AI密钥或环境变量)
        provider = {
            "base_url": _normalize_openai_base_url(AI服务商URL, "自动"),
            "api_key": api_key,
            "model": str(AI模型 or "").strip(),
            "api_mode": "自动",
            "timeout": 30,
            "temperature": 0.35,
            "max_tokens": 1200,
            "reasoning_mode": "关闭",
            "reasoning_effort": "medium",
            "service_tier": "auto",
            "stream": False,
            "api_key_source": key_source,
        }
        config = galiais_metadata(
            {
                "db_path": db_path,
                "locale": 默认语言,
                "allow_nsfw": bool(允许NSFW),
                "output_format": 默认输出格式,
                "dedupe": bool(默认去重),
                "negative_preset": 默认负面预设,
                "ai": {**provider, "api_key": _mask_secret(api_key)},
            }
        )
        return (config, provider, _metadata_json(config))


class GaliaisNodesDanbooruDictionaryInfo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "DB路径": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("词典信息JSON", "总词条", "已翻译", "模板数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, DB路径, DB=None):
        stats = DanbooruDictionary(resolve_danbooru_db_path(DB路径, DB)).stats()
        return (
            _metadata_json(stats),
            stats["total_tags"],
            stats["translated_tags"],
            stats["template_count"],
        )


class GaliaisNodesDanbooruTagResolver:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "词条": ("STRING", {"default": "", "multiline": True}),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "匹配模式": (["exact", "prefix", "contains"], {"default": "exact"}),
                "保留未匹配": ("BOOLEAN", {"default": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "最低热度": ("INT", {"default": 0, "min": 0, "max": 100000000}),
                "统一权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                "画师加At": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("英文Tags", "中文Labels", "解析JSON", "数量")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 词条, DB路径, 匹配模式, 保留未匹配, 允许NSFW, 最低热度, 统一权重, 画师加At, DB=None):
        dictionary = DanbooruDictionary(resolve_danbooru_db_path(DB路径, DB))
        terms = dictionary.resolve_terms(
            词条,
            match_mode=匹配模式,
            allow_nsfw=允许NSFW,
            keep_unresolved=保留未匹配,
            min_post_count=最低热度,
        )
        tags = []
        labels = []
        for term in terms:
            tag = term.tag
            if 画师加At and (term.category == 1 or term.semantic_category == "artist"):
                tag = "@" + tag.lstrip("@")
            tags.append(apply_tag_weight(tag, 统一权重))
            labels.append(term.label)
        tags = [tag for tag in tags if tag]
        return (
            join_prompt_parts(tags, dedupe=True),
            join_prompt_parts(labels, dedupe=True),
            _metadata_json([term.to_dict() for term in terms]),
            len(terms),
        )


class GaliaisNodesDanbooruQuerySelect:
    CANDIDATE_SLOTS = [f"第{i}项" for i in range(1, 21)]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "查询": ("STRING", {"default": "", "multiline": False}),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "查询语言": (["中英文", "中文", "英文"], {"default": "中英文"}),
                "匹配模式": (["smart", "exact", "prefix", "contains"], {"default": "smart"}),
                "候选序号": (cls.CANDIDATE_SLOTS, {"default": "第1项"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "最低热度": ("INT", {"default": 0, "min": 0, "max": 100000000}),
                "候选数量": ("INT", {"default": 20, "min": 1, "max": 20}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("英文Tag", "中文Label", "选中项", "候选JSON", "候选数量")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 查询, DB路径, 查询语言, 匹配模式, 候选序号, 允许NSFW, 最低热度, 候选数量, DB=None):
        dictionary = DanbooruDictionary(resolve_danbooru_db_path(DB路径, DB))
        terms = dictionary.query_search(
            查询,
            language=查询语言,
            match_mode=匹配模式,
            allow_nsfw=允许NSFW,
            min_post_count=最低热度,
            limit=候选数量,
        )
        if not terms:
            return ("", "", "none", "[]", 0)
        index = min(parse_candidate_index(候选序号), len(terms) - 1)
        selected = terms[index]
        return (
            selected.tag,
            selected.label,
            format_tag_option(selected),
            _metadata_json([term.to_dict() | {"option": format_tag_option(term)} for term in terms]),
            len(terms),
        )


class GaliaisNodesDanbooruTaxonomySelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "TaxonomyID": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "galiais_nodes_danbooru_field": "__taxonomy_id__",
                        "galiais_nodes_danbooru_lazy": True,
                    },
                ),
                "Tags": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "galiais_nodes_danbooru_field": "__selected_taxonomy_tags__",
                        "galiais_nodes_danbooru_lazy": True,
                    },
                ),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "去重": ("BOOLEAN", {"default": True}),
                "统一权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                "启用随机Tag": ("BOOLEAN", {"default": False}),
                "随机数量": ("INT", {"default": 1, "min": 0, "max": 50}),
                "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return runtime_random_is_changed(
            kwargs.get("启用随机Tag", False),
            kwargs.get("随机数量", 0),
            kwargs.get("随机种子", 0),
        )

    def run(self, TaxonomyID, Tags, DB路径, 允许NSFW, 去重, 统一权重, 启用随机Tag, 随机数量, 随机种子, DB=None):
        db_path = optional_danbooru_db_path(DB路径, DB)
        original_tags = str(Tags or "")
        tags = []
        for token in split_tag_option_text(Tags):
            parsed = parse_tag_option(token, db_path=db_path)
            if parsed:
                tags.append(apply_tag_weight(parsed, 统一权重))
        random_items = []
        random_display = []
        if 启用随机Tag and db_path and str(TaxonomyID or "").strip() and int(随机数量 or 0) > 0:
            random_items = DanbooruDictionary(db_path).random_options_for_field(
                "__taxonomy_id__",
                taxonomy_id=str(TaxonomyID or "").strip(),
                count=int(随机数量),
                seed=int(随机种子),
                allow_nsfw=bool(允许NSFW),
            )
            for item in random_items:
                random_display.append(format_tag_display_parts(item.get("tag", ""), item.get("label", "")))
                parsed = parse_tag_option(item.get("option") or item.get("tag") or "", db_path=db_path)
                if parsed:
                    tags.append(apply_tag_weight(parsed, 统一权重))
        text = join_prompt_parts(tags, dedupe=去重)
        random_field_value = join_tag_display_parts(random_display, dedupe=True)
        metadata = {
            "taxonomy_id": str(TaxonomyID or "").strip(),
            "count": len(split_tag_text(text)),
            "allow_nsfw": bool(允许NSFW),
            "dedupe": bool(去重),
            "weight": float(统一权重),
            "random_enabled": bool(启用随机Tag),
            "random_count": int(随机数量),
            "random_seed": int(随机种子),
            "random_items": random_items,
            "random_field_values": {"Tags": random_field_value} if random_field_value else {},
            "text": text,
        }
        result = (text, _metadata_json(metadata))
        if random_field_value:
            return {"ui": {"galiais_random_fields": [{"Tags": random_field_value}]}, "result": result}
        return result


class GaliaisNodesAIProvider:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "服务商URL": ("STRING", {"default": "", "multiline": False}),
                "API密钥": ("STRING", {"default": "", "multiline": False}),
                "模型": ("STRING", {"default": "", "multiline": False}),
                "接口模式": (["自动", "强制/v1", "保持原样"], {"default": "自动"}),
                "自动获取模型": ("BOOLEAN", {"default": False}),
                "超时秒": ("INT", {"default": 30, "min": 1, "max": 300}),
                "温度": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 2.0, "step": 0.05}),
                "最大Token": ("INT", {"default": 1200, "min": 64, "max": 32768}),
                "思考模式": (["关闭", "开启"], {"default": "关闭"}),
                "思考强度": (["minimal", "low", "medium", "high"], {"default": "medium"}),
                "服务层级": ("STRING", {"default": "auto", "multiline": False}),
                "流式响应": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_AI_PROVIDER", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("AI服务商", "模型", "可用模型JSON", "状态JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(
        self,
        服务商URL,
        API密钥,
        模型,
        接口模式,
        自动获取模型,
        超时秒,
        温度,
        最大Token,
        思考模式,
        思考强度,
        服务层级,
        流式响应,
    ):
        provider = {
            "base_url": _normalize_openai_base_url(服务商URL, 接口模式),
            "api_key": str(API密钥 or "").strip(),
            "model": str(模型 or "").strip(),
            "api_mode": 接口模式,
            "timeout": int(超时秒),
            "temperature": float(温度),
            "max_tokens": int(最大Token),
            "reasoning_mode": 思考模式,
            "reasoning_effort": 思考强度,
            "service_tier": str(服务层级 or "auto").strip() or "auto",
            "stream": bool(流式响应),
        }
        models = []
        error = ""
        if 自动获取模型:
            try:
                models = OpenAICompatibleClient().list_models(provider)
                if not provider["model"] and models:
                    provider["model"] = models[0]
            except Exception as exc:
                error = str(exc)
        status = {
            "base_url": provider["base_url"],
            "model": provider["model"],
            "available_model_count": len(models),
            "api_key": _mask_secret(provider["api_key"]),
            "reasoning_mode": provider["reasoning_mode"],
            "reasoning_effort": provider["reasoning_effort"],
            "service_tier": provider["service_tier"],
            "stream": provider["stream"],
            "error": error,
        }
        return (provider, provider["model"], _metadata_json(models), _metadata_json(status))


class GaliaisNodesPositivePromptAIEnricher:
    def __init__(self, client=None):
        self.client = client or OpenAICompatibleClient()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "正面提示词": ("STRING", {"default": "", "multiline": True}),
                "上下文说明": ("STRING", {"default": "", "multiline": True}),
                "输出语言": (["中文", "英文", "中英混合"], {"default": "中文"}),
                "合并模式": (["追加到末尾", "前置自然语言", "仅自然语言", "仅分析不合并"], {"default": "追加到末尾"}),
                "细节强度": (["精炼", "标准", "详细"], {"default": "标准"}),
                "去重": ("BOOLEAN", {"default": True}),
                "失败时返回原文": ("BOOLEAN", {"default": False}),
                "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "启用冲突剔除": ("BOOLEAN", {"default": False}),
                "冲突剔除策略": (["自动", "保留前者", "保留后者"], {"default": "自动"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("增强正面提示词", "自然语言补充", "分析JSON", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 正面提示词, 上下文说明, 输出语言, 合并模式, 细节强度, 去重, 失败时返回原文, 随机种子, 启用冲突剔除=False, 冲突剔除策略="自动", 允许NSFW=False, DB=None):
        if isinstance(启用冲突剔除, dict) and DB is None:
            DB = 启用冲突剔除
            启用冲突剔除 = False
            冲突剔除策略 = "自动"
            允许NSFW = False
        positive = str(正面提示词 or "").strip()
        provider = AI服务商 if isinstance(AI服务商, dict) else {}
        db_path = optional_danbooru_db_path(db=DB)
        diagnostics_before = _diagnose_prompt(positive, db_path=db_path, db=DB, allow_nsfw=bool(允许NSFW))
        prune_payload = {
            "enabled": bool(启用冲突剔除),
            "strategy": str(冲突剔除策略 or "自动"),
            "changed": False,
            "removed": [],
            "decisions": [],
            "prompt": positive,
        }
        ai_positive = positive
        if 启用冲突剔除:
            prune_payload = {
                "enabled": True,
                "strategy": str(冲突剔除策略 or "自动"),
                **_prune_prompt_conflicts(positive, mode=str(冲突剔除策略 or "自动"), db_path=db_path),
            }
            ai_positive = str(prune_payload.get("prompt") or positive).strip()
        tag_context = _build_positive_tag_context(ai_positive, DB)
        messages = _build_positive_enrichment_messages(ai_positive, 上下文说明, 输出语言, 细节强度, tag_context)
        raw_payload = {}
        try:
            response = self.client.chat_completion(provider, messages)
            raw_payload = response.get("raw", {})
            parsed = _extract_json_object(response.get("content", ""))
            natural = str(parsed.get("natural_language") or "").strip()
            analysis = parsed.get("analysis") if isinstance(parsed.get("analysis"), dict) else {}
            if not natural:
                natural = str(response.get("content") or "").strip()
            natural_empty = not bool(natural)
            if 合并模式 == "仅自然语言":
                enhanced = natural
            elif 合并模式 == "仅分析不合并":
                enhanced = ai_positive
            elif 合并模式 == "前置自然语言":
                enhanced = join_prompt_parts([natural, ai_positive], dedupe=去重)
            else:
                enhanced = join_prompt_parts([ai_positive, natural], dedupe=去重)
            analysis_payload = {
                "analysis": analysis,
                "added_focus": parsed.get("added_focus", []),
                "language": 输出语言,
                "detail_level": 细节强度,
                "seed": int(随机种子),
                "danbooru_context": tag_context,
                "diagnostics_before": diagnostics_before,
                "conflict_pruning_enabled": bool(启用冲突剔除),
                "conflict_pruning": prune_payload,
                "tags_sent_to_ai": ai_positive,
                "ai_called": True,
                "model": str(provider.get("model") or ""),
                "base_url": str(provider.get("base_url") or ""),
                "natural_language_empty": natural_empty,
            }
            if natural_empty:
                analysis_payload["warning"] = "AI返回为空，未生成自然语言补充。"
            return (
                enhanced,
                natural,
                _metadata_json(analysis_payload),
                _metadata_json(raw_payload),
            )
        except Exception as exc:
            if not 失败时返回原文:
                raise
            error_payload = {
                "error": str(exc),
                "fallback": True,
                "ai_called": False,
                "model": str(provider.get("model") or ""),
                "base_url": str(provider.get("base_url") or ""),
                "danbooru_context": tag_context,
                "diagnostics_before": diagnostics_before,
                "conflict_pruning_enabled": bool(启用冲突剔除),
                "conflict_pruning": prune_payload,
            }
            return (
                ai_positive if 启用冲突剔除 else positive,
                "",
                _metadata_json(error_payload),
                _metadata_json({**raw_payload, "error": str(exc), "fallback": True}),
            )


class GaliaisNodesAITagAnalyzer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("分析JSON", "分类摘要", "质量评分")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, 提示词, 允许NSFW, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        report = _diagnose_prompt(
            提示词,
            db_path=config.get("db_path", ""),
            db=DB,
            allow_nsfw=bool(允许NSFW or config.get("allow_nsfw", False)),
        )
        domains = {}
        for item in report.get("known", []):
            taxonomy_id = str(item.get("taxonomy_id") or "")
            parts = taxonomy_id.split(".")
            domain = parts[1] if len(parts) >= 5 else item.get("semantic_category") or "unknown"
            domains.setdefault(domain, []).append(item.get("tag"))
        return (_metadata_json(report), _metadata_json(domains), int(report.get("quality_score", 0)))


class _SimpleAITextNode:
    client_cls = OpenAICompatibleClient

    def __init__(self, client=None):
        self.client = client or self.client_cls()

    def _call(self, provider, task: str, payload: dict) -> tuple[str, str]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional anime image prompt assistant. "
                    "Return concise usable prompt text. Do not include explanations unless requested."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"task": task, **payload}, ensure_ascii=False),
            },
        ]
        response = self.client.chat_completion(provider if isinstance(provider, dict) else {}, messages)
        return (str(response.get("content") or "").strip(), _metadata_json(response.get("raw", {})))


class GaliaisNodesAINaturalPromptWriter(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "Tag分析JSON": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "输出语言": (["中文", "英文", "中英混合"], {"default": "英文"}),
                "细节强度": (["精炼", "标准", "详细"], {"default": "标准"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("自然语言提示词", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, Tag分析JSON, 输出语言, 细节强度):
        text, raw = self._call(
            AI服务商,
            "Write a natural-language positive prompt supplement from analyzed Danbooru tags.",
            {"analysis": _parse_json_object(Tag分析JSON), "language": 输出语言, "detail_level": 细节强度},
        )
        return (text, raw)


class GaliaisNodesAIConflictResolver(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "诊断JSON": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("修正建议", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 提示词, 诊断JSON):
        return self._call(
            AI服务商,
            "Resolve prompt conflicts and return corrected Danbooru tags only.",
            {"prompt": 提示词, "diagnostics": _parse_json_object(诊断JSON)},
        )


class GaliaisNodesAIStyleEnhancer(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "风格方向": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("风格增强提示词", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 提示词, 风格方向):
        return self._call(
            AI服务商,
            "Enhance visual style while preserving the original tags.",
            {"prompt": 提示词, "style_direction": 风格方向},
        )


class GaliaisNodesAICharacterDetailExpander(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "角色基础提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "扩写重点": ("STRING", {"default": "face, hair, body, outfit, pose", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("角色细节扩写", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 角色基础提示词, 扩写重点):
        return self._call(
            AI服务商,
            "Expand a character prompt with concrete visual details.",
            {"character_prompt": 角色基础提示词, "focus": 扩写重点},
        )


class GaliaisNodesAINegativePromptBuilder(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "正面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "标准"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("负面提示词", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 正面提示词, 负面预设):
        text, raw = self._call(
            AI服务商,
            "Build a negative prompt for this positive prompt. Return comma-separated negative tags.",
            {"positive_prompt": 正面提示词, "base_negative": GALIAIS_NODES_NEGATIVE_PRESETS.get(负面预设, "")},
        )
        return (join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS.get(负面预设, ""), text], dedupe=True), raw)


class GaliaisNodesPromptWeight:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "内容": ("STRING", {"default": "", "multiline": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("加权提示词",)
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 内容, 权重):
        weighted = [apply_tag_weight(tag, 权重) for tag in split_tag_text(内容)]
        return (join_prompt_parts(weighted, dedupe=False),)


class GaliaisNodesPromptSection:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "名称": ("STRING", {"default": "", "multiline": False}),
                "内容": ("STRING", {"default": "", "multiline": True}),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
            },
            "optional": {
                "前缀": ("STRING", {"default": "", "multiline": False}),
                "后缀": ("STRING", {"default": "", "multiline": False}),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_PROMPT_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("提示词段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 名称, 内容, 启用, 权重, 前缀="", 后缀=""):
        if not 启用:
            payload = {"name": 名称, "text": "", "enabled": False, "weight": 权重}
            return (payload, "", _metadata_json(payload))
        text = join_prompt_parts([前缀, 内容, 后缀], dedupe=True)
        if abs(权重 - 1.0) > 0.0001:
            text = join_prompt_parts(
                [apply_tag_weight(tag, 权重) for tag in split_tag_text(text)],
                dedupe=False,
            )
        payload = {"name": 名称, "text": text, "enabled": True, "weight": 权重}
        return (payload, text, _metadata_json(payload))


class GaliaisNodesPromptCombine:
    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            f"段{i}": ("STRING", {"default": "", "multiline": True, "forceInput": True})
            for i in range(1, 11)
        }
        return {
            "required": {
                "去重": ("BOOLEAN", {"default": True}),
                "分隔符": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 去重, 分隔符, **kwargs):
        ordered = [kwargs.get(f"段{i}", "") for i in range(1, 11)]
        prompt = join_prompt_parts(ordered, dedupe=去重, separator=分隔符)
        meta = {"parts": [p for p in ordered if str(p or "").strip()], "dedupe": 去重}
        return (prompt, _metadata_json(meta))


class GaliaisNodesPromptRandomPool:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "候选词条": ("STRING", {"default": "", "multiline": True}),
                "选择数量": ("INT", {"default": 1, "min": 0, "max": 100}),
                "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "允许重复": ("BOOLEAN", {"default": False}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("随机提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 候选词条, 选择数量, 随机种子, 允许重复, 权重):
        pool = split_tag_text(候选词条)
        rng = random.Random(int(随机种子))
        count = max(0, int(选择数量))
        if not pool or count == 0:
            return ("", _metadata_json({"selected": [], "seed": 随机种子}))
        if 允许重复:
            selected = [rng.choice(pool) for _ in range(count)]
        else:
            selected = rng.sample(pool, min(count, len(pool)))
        weighted = [apply_tag_weight(tag, 权重) for tag in selected]
        return (
            join_prompt_parts(weighted, dedupe=not 允许重复),
            _metadata_json({"selected": selected, "seed": 随机种子}),
        )


class GaliaisNodesNegativePreset:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "无"}),
                "追加内容": ("STRING", {"default": "", "multiline": True}),
                "去重": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("负面提示词",)
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 预设, 追加内容, 去重):
        return (join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS[预设], 追加内容], dedupe=去重),)


class GaliaisNodesPromptTemplate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "模板来源": (["手写", "词典模板ID"], {"default": "手写"}),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "模板ID或名称": ("STRING", {"default": "", "multiline": False}),
                "正面模板": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                    },
                ),
                "负面模板": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "质量": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "主体": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "角色": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "外观": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "服装": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "姿势": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "表情": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "镜头": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "场景": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "光照": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "风格": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "细节": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "自然语言": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 模板来源, DB路径, 模板ID或名称, 正面模板, 负面模板, **slots):
        db = slots.pop("DB", None)
        template_meta = None
        if 模板来源 == "词典模板ID":
            template_meta = DanbooruDictionary(
                resolve_danbooru_db_path(DB路径, db)
            ).template(模板ID或名称)
            if template_meta:
                正面模板 = template_meta.get("positive_template") or 正面模板
                负面模板 = template_meta.get("negative_template") or 负面模板
        positive = join_anima_prompt_parts([render_prompt_template(正面模板, slots)], dedupe=True)
        negative = render_prompt_template(负面模板, slots)
        return (
            positive,
            negative,
            _metadata_json({"template": template_meta, "slots": slots}),
        )


class GaliaisNodesPromptProfile:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "名称": ("STRING", {"default": "", "multiline": False}),
                "角色": ("STRING", {"default": "", "multiline": True}),
                "作品": ("STRING", {"default": "", "multiline": True}),
                "画师": ("STRING", {"default": "", "multiline": False}),
                "主体": ("STRING", {"default": "", "multiline": True}),
                "身体": ("STRING", {"default": "", "multiline": True}),
                "脸发眼": ("STRING", {"default": "", "multiline": True}),
                "服装": ("STRING", {"default": "", "multiline": True}),
                "姿态": ("STRING", {"default": "", "multiline": True}),
                "场景": ("STRING", {"default": "", "multiline": True}),
                "风格": ("STRING", {"default": "", "multiline": True}),
                "自然语言": ("STRING", {"default": "", "multiline": True}),
                "负面": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_PROMPT_PROFILE", "STRING")
    RETURN_NAMES = ("提示词档案", "档案JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/profile"

    def run(self, 名称, 角色, 作品, 画师, 主体, 身体, 脸发眼, 服装, 姿态, 场景, 风格, 自然语言, 负面, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        db_path = optional_danbooru_db_path(config.get("db_path", ""), DB)
        profile = galiais_metadata(
            {
                "name": str(名称 or "").strip(),
                "db_path": db_path,
                "sections": {
                    "artist": normalize_artist_tag(画师, db_path=db_path),
                    "subject": 主体,
                    "character": 角色,
                    "copyright": 作品,
                    "body": 身体,
                    "face_hair_eyes": 脸发眼,
                    "outfit": 服装,
                    "pose": 姿态,
                    "scene": 场景,
                    "style": 风格,
                    "natural_language": 自然语言,
                    "negative": 负面,
                },
                "config": config,
            }
        )
        return (profile, _metadata_json(profile))


class GaliaisNodesTypedComposerV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "主体": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "角色": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "作品": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "画师": ("STRING", {"default": "", "multiline": False}),
                "身体": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "脸发眼": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "服装": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "姿态动作": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "场景镜头": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "风格细节": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "自然语言": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "标准"}),
                "去重": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "提示词档案": ("GALIAIS_NODES_PROMPT_PROFILE",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("正面提示词", "负面提示词", "元信息JSON", "质量评分")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 主体, 角色, 作品, 画师, 身体, 脸发眼, 服装, 姿态动作, 场景镜头, 风格细节, 自然语言, 负面, 负面预设, 去重, 项目配置=None, 提示词档案=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        profile = 提示词档案 if isinstance(提示词档案, dict) else {}
        sections = profile.get("sections", {}) if isinstance(profile.get("sections"), dict) else {}
        db_path = optional_danbooru_db_path(config.get("db_path", profile.get("db_path", "")), DB)
        allow_nsfw = bool(config.get("allow_nsfw", False))
        dedupe = bool(去重 if 去重 is not None else config.get("dedupe", True))

        artist = normalize_artist_tag(画师 or sections.get("artist", ""), db_path=db_path)
        positive_parts = [
            artist,
            主体 or sections.get("subject", ""),
            角色 or sections.get("character", ""),
            作品 or sections.get("copyright", ""),
            身体 or sections.get("body", ""),
            脸发眼 or sections.get("face_hair_eyes", ""),
            服装 or sections.get("outfit", ""),
            姿态动作 or sections.get("pose", ""),
            场景镜头 or sections.get("scene", ""),
            风格细节 or sections.get("style", ""),
            自然语言 or sections.get("natural_language", ""),
        ]
        positive = join_anima_prompt_parts(positive_parts, dedupe=dedupe, allow_artist=True, db_path=db_path)
        negative = join_prompt_parts(
            [
                GALIAIS_NODES_NEGATIVE_PRESETS.get(负面预设, ""),
                负面 or sections.get("negative", ""),
            ],
            dedupe=dedupe,
        )
        report = _diagnose_prompt(positive, db_path=db_path, allow_nsfw=allow_nsfw)
        meta = galiais_metadata(
            {
                "ordered_sections": [
                    "artist",
                    "subject",
                    "character",
                    "copyright",
                    "body",
                    "face_hair_eyes",
                    "outfit",
                    "pose",
                    "scene",
                    "style",
                    "natural_language",
                ],
                "artist_before_subject": bool(artist),
                "negative_preset": 负面预设,
                "diagnostics": report,
                "profile_name": profile.get("name", ""),
                "db_path": db_path,
            }
        )
        return (positive, negative, _metadata_json(meta), int(report.get("quality_score", 0)))


class GaliaisNodesPromptBuilder:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "质量预设": (list(GALIAIS_NODES_QUALITY_PRESETS.keys()), {"default": "无"}),
                "主体": ("STRING", {"default": "", "multiline": True}),
                "角色": ("STRING", {"default": "", "multiline": True}),
                "画师": ("STRING", {"default": "", "multiline": False}),
                "外观": ("STRING", {"default": "", "multiline": True}),
                "服装": ("STRING", {"default": "", "multiline": True}),
                "姿势": ("STRING", {"default": "", "multiline": True}),
                "场景": ("STRING", {"default": "", "multiline": True}),
                "光照": ("STRING", {"default": "", "multiline": True}),
                "风格": ("STRING", {"default": "", "multiline": True}),
                "细节": ("STRING", {"default": "", "multiline": True}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "无"}),
                "去重": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "额外前缀": ("STRING", {"default": "", "multiline": True}),
                "额外后缀": ("STRING", {"default": "", "multiline": True}),
                "额外负面": ("STRING", {"default": "", "multiline": True}),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(
        self,
        质量预设,
        主体,
        角色,
        画师,
        外观,
        服装,
        姿势,
        场景,
        光照,
        风格,
        细节,
        负面预设,
        去重,
        额外前缀="",
        额外后缀="",
        额外负面="",
        DB=None,
    ):
        db_path = optional_danbooru_db_path(db=DB)
        parts = [
            额外前缀,
            主体,
            角色,
            外观,
            服装,
            姿势,
            场景,
            光照,
            风格,
            细节,
            额外后缀,
        ]
        artist = normalize_artist_tag(画师, db_path=db_path)
        parts = [artist, *parts]
        positive = join_anima_prompt_parts(parts, dedupe=去重, allow_artist=True, db_path=db_path)
        negative = join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS[负面预设], 额外负面], dedupe=去重)
        meta = {
            "quality_preset": 质量预设,
            "quality_omitted_by_anima_template": bool(GALIAIS_NODES_QUALITY_PRESETS[质量预设]),
            "negative_preset": 负面预设,
            "dedupe": 去重,
            "parts": {
                "subject": 主体,
                "character": 角色,
                "artist": artist,
                "artist_inserted_before_subject": bool(artist),
                "appearance": 外观,
                "clothing": 服装,
                "pose": 姿势,
                "scene": 场景,
                "lighting": 光照,
                "style": 风格,
                "detail": 细节,
            },
        }
        return (positive, negative, _metadata_json(meta))


class GaliaisNodesPromptInspector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True}),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("已识别Tags", "未识别", "报告JSON", "已识别数", "未识别数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 提示词, DB路径, 允许NSFW, DB=None):
        dictionary = DanbooruDictionary(resolve_danbooru_db_path(DB路径, DB))
        known = []
        unknown = []
        records = []
        for token in split_tag_text(提示词):
            clean = token.strip()
            clean = re.sub(r"^\((.*):[0-9.]+\)$", r"\1", clean)
            clean = clean.lstrip("@")
            matches = dictionary.resolve_terms(
                clean,
                match_mode="exact",
                allow_nsfw=允许NSFW,
                keep_unresolved=False,
            )
            if matches:
                known.append(matches[0].tag)
                records.append(matches[0].to_dict())
            else:
                unknown.append(token)
        known_text = join_prompt_parts(known, dedupe=True)
        unknown_text = join_prompt_parts(unknown, dedupe=True)
        return (
            known_text,
            unknown_text,
            _metadata_json({"known": records, "unknown": unknown}),
            len(known),
            len(unknown),
        )


class GaliaisNodesPromptInspectorV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("已识别Tags", "未识别", "诊断JSON", "质量评分", "问题数", "NSFW数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/diagnostics"

    def run(self, 提示词, 允许NSFW, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        allow_nsfw = bool(允许NSFW or config.get("allow_nsfw", False))
        report = _diagnose_prompt(提示词, db_path=config.get("db_path", ""), db=DB, allow_nsfw=allow_nsfw)
        known = [item.get("tag", "") for item in report.get("known", []) if item.get("tag")]
        unknown = report.get("unknown", [])
        return (
            join_prompt_parts(known, dedupe=True),
            join_prompt_parts(unknown, dedupe=True),
            _metadata_json(report),
            int(report.get("quality_score", 0)),
            len(report.get("issues", [])),
            len(report.get("nsfw_tags", [])),
        )


class GaliaisNodesPromptQualityScore:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "STRING")
    RETURN_NAMES = ("质量评分", "评级", "评分JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/diagnostics"

    def run(self, 提示词, 允许NSFW, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        report = _diagnose_prompt(
            提示词,
            db_path=config.get("db_path", ""),
            db=DB,
            allow_nsfw=bool(允许NSFW or config.get("allow_nsfw", False)),
        )
        score = int(report.get("quality_score", 0))
        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
        payload = galiais_metadata({"score": score, "grade": grade, "diagnostics": report})
        return (score, grade, _metadata_json(payload))


class GaliaisNodesDBCacheControl:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "操作": (["查看", "清空"], {"default": "查看"}),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("缓存JSON", "缓存项数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/config"

    def run(self, 操作):
        if 操作 == "清空":
            _DANBOORU_OPTION_CACHE.clear()
            _DANBOORU_TREE_CACHE.clear()
            _DANBOORU_RUNTIME_PATH_CACHE.clear()
            _TAG_EXISTS_CACHE.clear()
        counts = {
            "option_cache": len(_DANBOORU_OPTION_CACHE),
            "tree_cache": len(_DANBOORU_TREE_CACHE),
            "runtime_path_cache": len(_DANBOORU_RUNTIME_PATH_CACHE),
            "tag_exists_cache": len(_TAG_EXISTS_CACHE),
        }
        return (_metadata_json(galiais_metadata({"operation": 操作, "counts": counts})), sum(counts.values()))


class GaliaisNodesPromptViewer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "正面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "元信息JSON": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "标题": ("STRING", {"default": "GALIAIS-Nodes Prompt Output", "multiline": False}),
                "透传输出": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"
    OUTPUT_NODE = True

    def run(self, 正面提示词, 负面提示词, 元信息JSON, 标题, 透传输出):
        positive = str(正面提示词 or "")
        negative = str(负面提示词 or "")
        metadata = str(元信息JSON or "")
        if not 透传输出:
            result = ("", "", "")
        else:
            result = (positive, negative, metadata)
        return {
            "ui": {
                "title": [str(标题 or "GALIAIS-Nodes Prompt Output")],
                "positive": [positive],
                "negative": [negative],
                "metadata": [metadata],
            },
            "result": result,
        }


NODE_CLASS_MAPPINGS = {
    "GaliaisNodesProjectConfig": GaliaisNodesProjectConfig,
    "GaliaisNodesDanbooruDBLoader": GaliaisNodesDanbooruDBLoader,
    "GaliaisNodesDanbooruDictionaryInfo": GaliaisNodesDanbooruDictionaryInfo,
    "GaliaisNodesDanbooruTagResolver": GaliaisNodesDanbooruTagResolver,
    "GaliaisNodesDanbooruQuerySelect": GaliaisNodesDanbooruQuerySelect,
    "GaliaisNodesDanbooruTaxonomySelect": GaliaisNodesDanbooruTaxonomySelect,
    "GaliaisNodesAIProvider": GaliaisNodesAIProvider,
    "GaliaisNodesPositivePromptAIEnricher": GaliaisNodesPositivePromptAIEnricher,
    "GaliaisNodesAITagAnalyzer": GaliaisNodesAITagAnalyzer,
    "GaliaisNodesAINaturalPromptWriter": GaliaisNodesAINaturalPromptWriter,
    "GaliaisNodesAIConflictResolver": GaliaisNodesAIConflictResolver,
    "GaliaisNodesAIStyleEnhancer": GaliaisNodesAIStyleEnhancer,
    "GaliaisNodesAICharacterDetailExpander": GaliaisNodesAICharacterDetailExpander,
    "GaliaisNodesAINegativePromptBuilder": GaliaisNodesAINegativePromptBuilder,
    "GaliaisNodesPromptWeight": GaliaisNodesPromptWeight,
    "GaliaisNodesPromptSection": GaliaisNodesPromptSection,
    "GaliaisNodesPromptCombine": GaliaisNodesPromptCombine,
    "GaliaisNodesPromptRandomPool": GaliaisNodesPromptRandomPool,
    "GaliaisNodesNegativePreset": GaliaisNodesNegativePreset,
    "GaliaisNodesPromptTemplate": GaliaisNodesPromptTemplate,
    "GaliaisNodesPromptProfile": GaliaisNodesPromptProfile,
    "GaliaisNodesTypedComposerV2": GaliaisNodesTypedComposerV2,
    "GaliaisNodesPromptBuilder": GaliaisNodesPromptBuilder,
    "GaliaisNodesPromptInspector": GaliaisNodesPromptInspector,
    "GaliaisNodesPromptInspectorV2": GaliaisNodesPromptInspectorV2,
    "GaliaisNodesPromptQualityScore": GaliaisNodesPromptQualityScore,
    "GaliaisNodesDBCacheControl": GaliaisNodesDBCacheControl,
    "GaliaisNodesPromptViewer": GaliaisNodesPromptViewer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GaliaisNodesProjectConfig": "GALIAIS-Nodes Project Config",
    "GaliaisNodesDanbooruDBLoader": "GALIAIS-Nodes Danbooru DB Loader",
    "GaliaisNodesDanbooruDictionaryInfo": "GALIAIS-Nodes Danbooru Dictionary Info",
    "GaliaisNodesDanbooruTagResolver": "GALIAIS-Nodes Danbooru Tag Resolver",
    "GaliaisNodesDanbooruQuerySelect": "GALIAIS-Nodes Danbooru Query Select",
    "GaliaisNodesDanbooruTaxonomySelect": "GALIAIS-Nodes Danbooru Taxonomy Select",
    "GaliaisNodesAIProvider": "GALIAIS-Nodes AI Provider",
    "GaliaisNodesPositivePromptAIEnricher": "GALIAIS-Nodes Positive Prompt AI Enricher",
    "GaliaisNodesAITagAnalyzer": "GALIAIS-Nodes AI Tag Analyzer",
    "GaliaisNodesAINaturalPromptWriter": "GALIAIS-Nodes AI Natural Prompt Writer",
    "GaliaisNodesAIConflictResolver": "GALIAIS-Nodes AI Conflict Resolver",
    "GaliaisNodesAIStyleEnhancer": "GALIAIS-Nodes AI Style Enhancer",
    "GaliaisNodesAICharacterDetailExpander": "GALIAIS-Nodes AI Character Detail Expander",
    "GaliaisNodesAINegativePromptBuilder": "GALIAIS-Nodes AI Negative Prompt Builder",
    "GaliaisNodesPromptWeight": "GALIAIS-Nodes Prompt Weight",
    "GaliaisNodesPromptSection": "GALIAIS-Nodes Prompt Section",
    "GaliaisNodesPromptCombine": "GALIAIS-Nodes Prompt Combine",
    "GaliaisNodesPromptRandomPool": "GALIAIS-Nodes Prompt Random Pool",
    "GaliaisNodesNegativePreset": "GALIAIS-Nodes Negative Preset",
    "GaliaisNodesPromptTemplate": "GALIAIS-Nodes Prompt Template",
    "GaliaisNodesPromptProfile": "GALIAIS-Nodes Prompt Profile",
    "GaliaisNodesTypedComposerV2": "GALIAIS-Nodes Typed Composer V2",
    "GaliaisNodesPromptBuilder": "GALIAIS-Nodes Prompt Builder",
    "GaliaisNodesPromptInspector": "GALIAIS-Nodes Prompt Inspector",
    "GaliaisNodesPromptInspectorV2": "GALIAIS-Nodes Prompt Inspector V2",
    "GaliaisNodesPromptQualityScore": "GALIAIS-Nodes Prompt Quality Score",
    "GaliaisNodesDBCacheControl": "GALIAIS-Nodes DB Cache Control",
    "GaliaisNodesPromptViewer": "GALIAIS-Nodes Prompt Viewer",
}
