try:
    from .nodes_galiais_prompt_system import (
        DanbooruDictionary,
        format_tag_display_parts,
        join_tag_display_parts,
        join_prompt_parts,
        optional_danbooru_db_path,
        parse_tag_option,
        register_danbooru_field_set,
        runtime_random_is_changed,
        _metadata_json,
    )
except ImportError:
    from nodes_galiais_prompt_system import (
        DanbooruDictionary,
        format_tag_display_parts,
        join_tag_display_parts,
        join_prompt_parts,
        optional_danbooru_db_path,
        parse_tag_option,
        register_danbooru_field_set,
        runtime_random_is_changed,
        _metadata_json,
    )


STYLE_TAXONOMY_FIELDS = {
    "渲染风格": [
        "0.style.rendering.render_style",
        "0.style.line.line_art",
    ],
    "媒介": [
        "0.style.medium.art_medium",
        "0.style.postprocess.analog_media_artifact",
    ],
    "色彩": ["0.style.color.palette"],
    "光照": [
        "0.style.lighting.light_quality",
        "0.style.lighting.light_direction",
    ],
    "后期效果": ["0.style.postprocess.image_effect"],
    "设计风格": [
        "0.style.design.decorative_or_graphic_design",
        "0.style.design.fashion_or_costume_style",
    ],
    "质量细节": [
        "0.style.quality.quality_score",
        "0.style.quality.resolution_detail",
    ],
}
register_danbooru_field_set("style", STYLE_TAXONOMY_FIELDS)


def style_combo(field: str):
    return (
        "STRING",
        {
            "default": "",
            "multiline": False,
            "galiais_nodes_danbooru_field": field,
            "galiais_nodes_danbooru_lazy": True,
        },
    )


def random_controls():
    return {
        "启用随机Tag": ("BOOLEAN", {"default": False}),
        "随机策略": (["只补空字段", "追加到字段"], {"default": "只补空字段"}),
        "每字段随机数": ("INT", {"default": 1, "min": 0, "max": 10}),
        "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
        "随机允许NSFW": ("BOOLEAN", {"default": False}),
        "随机最低热度": ("INT", {"default": 0, "min": 0, "max": 100000000}),
    }


def field_enabled_controls(*labels: str):
    return {
        f"使用{label}": ("BOOLEAN", {"default": True})
        for label in labels
    }


def _merge_random_value(existing: str, items, *, append: bool) -> str:
    random_text = join_tag_display_parts(
        [
            format_tag_display_parts(item.get("tag", ""), item.get("label", ""))
            for item in items
        ],
        dedupe=True,
    )
    if not random_text:
        return str(existing or "")
    if append:
        return join_tag_display_parts([existing, random_text], dedupe=True)
    return str(existing or "").strip() or random_text


def _random_items_display(items) -> str:
    return join_tag_display_parts(
        [
            format_tag_display_parts(item.get("tag", ""), item.get("label", ""))
            for item in items
        ],
        dedupe=True,
    )


def _enabled_value(value, enabled: bool) -> str:
    return str(value or "") if enabled else ""


def _random_field_values(*items) -> dict[str, str]:
    return {
        key: str(value or "")
        for key, value, enabled in items
        if enabled
    }


def _runtime_random_is_changed(*args, **kwargs):
    return runtime_random_is_changed(
        kwargs.get("启用随机Tag", False),
        kwargs.get("每字段随机数", 0),
        kwargs.get("随机种子", 0),
    )


def _field_switch_metadata(*items) -> dict:
    return {
        "enabled": {key: bool(enabled) for key, label, enabled in items},
        "enabled_fields": [label for key, label, enabled in items if enabled],
        "disabled_fields": [label for key, label, enabled in items if not enabled],
    }


def _apply_random_fields(
    values: dict[str, str],
    *,
    db_path: str,
    enabled: bool,
    strategy: str,
    per_field_count: int,
    seed: int,
    allow_nsfw: bool,
    min_post_count: int,
):
    result = {key: str(value or "") for key, value in values.items()}
    safe_count = max(0, int(per_field_count or 0))
    metadata = {
        "enabled": bool(enabled),
        "strategy": str(strategy or "只补空字段"),
        "per_field_count": safe_count,
        "seed": int(seed or 0),
        "allow_nsfw": bool(allow_nsfw),
        "min_post_count": int(min_post_count or 0),
        "items": {},
        "field_values": {},
        "random_field_values": {},
    }
    if not enabled or not db_path or safe_count <= 0:
        metadata["field_values"] = dict(result)
        return result, metadata

    append = strategy == "追加到字段"
    base_seed = int(seed or 0)
    dictionary = DanbooruDictionary(db_path)
    for index, (field, current) in enumerate(result.items()):
        if not append and str(current or "").strip():
            continue
        field_seed = base_seed + index if base_seed else 0
        items = dictionary.random_options_for_field(
            field,
            count=safe_count,
            seed=field_seed,
            allow_nsfw=bool(allow_nsfw),
            min_post_count=int(min_post_count or 0),
        )
        if not items:
            continue
        result[field] = _merge_random_value(current, items, append=append)
        metadata["items"][field] = items
        random_text = _random_items_display(items)
        if random_text:
            metadata["random_field_values"][field] = random_text
    metadata["field_values"] = dict(result)
    return result, metadata


def _random_ui_payload(random_meta: dict, mapping: dict[str, str]) -> dict:
    if not isinstance(random_meta, dict) or not random_meta.get("enabled"):
        return {}
    field_values = random_meta.get("random_field_values") if isinstance(random_meta.get("random_field_values"), dict) else {}
    widgets = {
        widget: field_values[field]
        for field, widget in mapping.items()
        if field in field_values
    }
    if not widgets:
        return {"galiais_random_fields": []}
    return {"galiais_random_fields": [widgets]}


class GaliaisNodesDanbooruStyleSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "渲染风格": style_combo("渲染风格"),
                "媒介": style_combo("媒介"),
                "色彩": style_combo("色彩"),
                "光照": style_combo("光照"),
                "后期效果": style_combo("后期效果"),
                "设计风格": style_combo("设计风格"),
                "质量细节": style_combo("质量细节"),
                "追加到提示词": ("STRING", {"multiline": True, "default": ""}),
                "插入位置": (["append", "prepend", "only"], {"default": "append"}),
                "去重": ("BOOLEAN", {"default": True}),
                **field_enabled_controls("渲染风格", "媒介", "色彩", "光照", "后期效果", "设计风格", "质量细节", "追加到提示词"),
                **random_controls(),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/conditioning"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return _runtime_random_is_changed(*args, **kwargs)

    def run(self, 渲染风格, 媒介, 色彩, 光照, 后期效果, 设计风格, 质量细节, 追加到提示词, 插入位置, 去重, 使用渲染风格, 使用媒介, 使用色彩, 使用光照, 使用后期效果, 使用设计风格, 使用质量细节, 使用追加到提示词, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("渲染风格", 渲染风格, 使用渲染风格),
                ("媒介", 媒介, 使用媒介),
                ("色彩", 色彩, 使用色彩),
                ("光照", 光照, 使用光照),
                ("后期效果", 后期效果, 使用后期效果),
                ("设计风格", 设计风格, 使用设计风格),
                ("质量细节", 质量细节, 使用质量细节),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        style_tags = join_prompt_parts(
            [
                parse_tag_option(values.get("渲染风格", ""), db_path=db_path),
                parse_tag_option(values.get("媒介", ""), db_path=db_path),
                parse_tag_option(values.get("色彩", ""), db_path=db_path),
                parse_tag_option(values.get("光照", ""), db_path=db_path),
                parse_tag_option(values.get("后期效果", ""), db_path=db_path),
                parse_tag_option(values.get("设计风格", ""), db_path=db_path),
                parse_tag_option(values.get("质量细节", ""), db_path=db_path),
            ],
            dedupe=去重,
        )
        prompt = _enabled_value(追加到提示词, 使用追加到提示词).strip()
        metadata = {
            "style_tags": style_tags,
            "insert_position": 插入位置,
            "dedupe": bool(去重),
            "fields": _field_switch_metadata(
                ("style_render", "渲染风格", 使用渲染风格),
                ("style_medium", "媒介", 使用媒介),
                ("style_color", "色彩", 使用色彩),
                ("style_lighting", "光照", 使用光照),
                ("style_postprocess", "后期效果", 使用后期效果),
                ("style_design", "设计风格", 使用设计风格),
                ("style_quality", "质量细节", 使用质量细节),
                ("style_append_prompt", "追加到提示词", 使用追加到提示词),
            ),
            "random": random_meta,
        }
        ui = _random_ui_payload(
            random_meta,
            {
                "渲染风格": "渲染风格",
                "媒介": "媒介",
                "色彩": "色彩",
                "光照": "光照",
                "后期效果": "后期效果",
                "设计风格": "设计风格",
                "质量细节": "质量细节",
            },
        )
        if 插入位置 == "only":
            result = (style_tags, _metadata_json(metadata))
            return {"ui": ui, "result": result} if ui else result
        if 插入位置 == "prepend":
            result = (join_prompt_parts([style_tags, prompt], dedupe=去重), _metadata_json(metadata))
            return {"ui": ui, "result": result} if ui else result
        result = (join_prompt_parts([prompt, style_tags], dedupe=去重), _metadata_json(metadata))
        return {"ui": ui, "result": result} if ui else result


NODE_CLASS_MAPPINGS = {
    "GaliaisNodesDanbooruStyleSelect": GaliaisNodesDanbooruStyleSelect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GaliaisNodesDanbooruStyleSelect": "GALIAIS-Nodes Danbooru Style Select",
}
