try:
    from .nodes_galiais_prompt_system import (
        AI_TAG_GENERATION_MODES,
        DanbooruDictionary,
        ai_select_tags_for_fields,
        format_tag_display_parts,
        join_tag_display_parts,
        join_prompt_parts,
        normalize_tag_blacklist,
        optional_danbooru_db_path,
        parse_tag_option,
        register_danbooru_field_set,
        runtime_random_is_changed,
        _metadata_json,
    )
except ImportError:
    from nodes_galiais_prompt_system import (
        AI_TAG_GENERATION_MODES,
        DanbooruDictionary,
        ai_select_tags_for_fields,
        format_tag_display_parts,
        join_tag_display_parts,
        join_prompt_parts,
        normalize_tag_blacklist,
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


def random_count_controls(*labels: str):
    return {
        f"随机数{label}": (
            "INT",
            {
                "default": -1,
                "min": -1,
                "step": 1,
                "tooltip": "-1=沿用每字段随机数，0=关闭本字段随机，正数=该字段最多随机数量；AI协同会按合理性少选",
            },
        )
        for label in labels
    }


def random_min_post_count_controls(*labels: str):
    return {
        f"最低热度{label}": (
            "INT",
            {
                "default": -1,
                "min": -1,
                "max": 100000000,
                "step": 1,
                "tooltip": "-1=沿用随机最低热度，0=本字段不限热度，正数=该字段最低热度",
            },
        )
        for label in labels
    }


def random_controls(*labels: str):
    return {
        "启用随机Tag": ("BOOLEAN", {"default": False}),
        "Tag生成模式": (AI_TAG_GENERATION_MODES, {"default": "规则随机"}),
        "AI自由度": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05}),
        "AI意图方向": (
            "STRING",
            {
                "default": "",
                "multiline": True,
                "tooltip": "粗略描述你想要的风格方向；AI只会从当前启用字段的候选tag中选择，并把方向扩写成自然语言。",
            },
        ),
        "AI扩写强度": (["精简", "标准", "完整"], {"default": "标准"}),
        "AI是否写入补充": (["只放元信息", "写入本节点补充", "关闭"], {"default": "只放元信息"}),
        "AI RAG模式": (["关闭", "轻量语义", "示例增强", "混合增强"], {"default": "关闭"}),
        "RAG候选数": ("INT", {"default": 12, "min": 0, "max": 200, "step": 1}),
        "RAG示例数": ("INT", {"default": 3, "min": 0, "max": 20, "step": 1}),
        "随机策略": (["只补空字段", "追加到字段"], {"default": "只补空字段"}),
        "每字段随机数": ("INT", {"default": 1, "min": 0}),
        **random_count_controls(*labels),
        "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
        "随机允许NSFW": ("BOOLEAN", {"default": False}),
        "随机最低热度": ("INT", {"default": 0, "min": 0, "max": 100000000}),
        **random_min_post_count_controls(*labels),
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


def _intent_expansion_note(random_meta: dict | None, write_mode: str | None = None) -> str:
    if not isinstance(random_meta, dict):
        return ""
    intent = random_meta.get("intent_expansion")
    if not isinstance(intent, dict):
        return ""
    mode = str(write_mode or intent.get("write_mode") or "只放元信息")
    if mode != "写入本节点补充":
        return ""
    return str(intent.get("natural_language") or "").strip()


def _random_field_values(*items) -> dict[str, str]:
    return {
        key: str(value or "")
        for key, value, enabled in items
        if enabled
    }


def _positive_random_count(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _runtime_random_is_changed(*args, **kwargs):
    count = kwargs.get("每字段随机数", 0)
    if int(count or 0) <= 0:
        count = max(
            [0]
            + [
                _positive_random_count(value)
                for key, value in kwargs.items()
                if str(key).startswith("随机数") and _positive_random_count(value) > 0
            ]
        )
    return runtime_random_is_changed(
        kwargs.get("启用随机Tag", False),
        count,
        kwargs.get("随机种子", 0),
    )


def _field_switch_metadata(*items) -> dict:
    return {
        "enabled": {key: bool(enabled) for key, label, enabled in items},
        "enabled_fields": [label for key, label, enabled in items if enabled],
        "disabled_fields": [label for key, label, enabled in items if not enabled],
    }


def _random_count_overrides(field_labels: dict[str, str], kwargs: dict) -> dict[str, int]:
    return _int_field_overrides(field_labels, kwargs, "随机数", -1)


def _random_min_post_count_overrides(field_labels: dict[str, str], kwargs: dict) -> dict[str, int]:
    return _int_field_overrides(field_labels, kwargs, "最低热度", -1)


def _random_field_control_overrides(field_labels: dict[str, str], kwargs: dict) -> dict:
    return {
        "per_field_counts": _random_count_overrides(field_labels, kwargs),
        "per_field_min_post_counts": _random_min_post_count_overrides(field_labels, kwargs),
    }


def _int_field_overrides(field_labels: dict[str, str], kwargs: dict, prefix: str, default: int) -> dict[str, int]:
    overrides = {}
    for field, label in field_labels.items():
        widget_name = f"{prefix}{label}"
        if widget_name not in kwargs:
            continue
        try:
            overrides[field] = int(kwargs.get(widget_name))
        except (TypeError, ValueError):
            overrides[field] = default
    return overrides


def _effective_random_counts(fields, default_count: int, overrides=None) -> dict[str, int]:
    safe_default = max(0, int(default_count or 0))
    result = {}
    overrides = overrides or {}
    for field in fields:
        raw = overrides.get(field, -1)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = -1
        result[field] = safe_default if value < 0 else max(0, value)
    return result


def _effective_min_post_counts(fields, default_min_post_count: int, overrides=None) -> dict[str, int]:
    safe_default = max(0, int(default_min_post_count or 0))
    result = {}
    overrides = overrides or {}
    for field in fields:
        raw = overrides.get(field, -1)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = -1
        result[field] = safe_default if value < 0 else max(0, value)
    return result


def _apply_random_fields(
    values: dict[str, str],
    *,
    db_path: str,
    enabled: bool,
    strategy: str,
    per_field_count: int,
    per_field_counts=None,
    seed: int,
    allow_nsfw: bool,
    min_post_count: int,
    per_field_min_post_counts=None,
    blacklist=None,
):
    result = {key: str(value or "") for key, value in values.items()}
    safe_count = max(0, int(per_field_count or 0))
    safe_min_post_count = max(0, int(min_post_count or 0))
    effective_counts = _effective_random_counts(result.keys(), safe_count, per_field_counts)
    effective_min_post_counts = _effective_min_post_counts(result.keys(), safe_min_post_count, per_field_min_post_counts)
    blacklist_tags = normalize_tag_blacklist(blacklist)
    metadata = {
        "enabled": bool(enabled),
        "strategy": str(strategy or "只补空字段"),
        "per_field_count": safe_count,
        "per_field_counts": dict(effective_counts),
        "seed": int(seed or 0),
        "allow_nsfw": bool(allow_nsfw),
        "min_post_count": safe_min_post_count,
        "per_field_min_post_counts": dict(effective_min_post_counts),
        "blacklist_count": len(blacklist_tags),
        "items": {},
        "field_values": {},
        "random_field_values": {},
    }
    if not enabled or not db_path or not any(count > 0 for count in effective_counts.values()):
        metadata["field_values"] = dict(result)
        return result, metadata

    append = strategy == "追加到字段"
    base_seed = int(seed or 0)
    dictionary = DanbooruDictionary(db_path)
    for index, (field, current) in enumerate(result.items()):
        field_count = effective_counts.get(field, safe_count)
        if field_count <= 0:
            continue
        if not append and str(current or "").strip():
            continue
        field_seed = base_seed + index if base_seed else 0
        items = dictionary.random_options_for_field(
            field,
            count=field_count,
            seed=field_seed,
            allow_nsfw=bool(allow_nsfw),
            min_post_count=effective_min_post_counts.get(field, safe_min_post_count),
            blacklist=blacklist_tags,
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


def _apply_generated_fields(
    values: dict[str, str],
    *,
    db_path: str,
    enabled: bool,
    mode: str,
    provider=None,
    previous_context: str = "",
    field_labels: dict[str, str] | None = None,
    ai_freedom: float,
    strategy: str,
    per_field_count: int,
    per_field_counts=None,
    seed: int,
    allow_nsfw: bool,
    min_post_count: int,
    per_field_min_post_counts=None,
    blacklist=None,
    intent_text: str = "",
    intent_detail: str = "标准",
    intent_write_mode: str = "只放元信息",
    rag_mode: str = "关闭",
    rag_candidate_count: int = 12,
    rag_example_count: int = 3,
):
    selected_mode = str(mode or "规则随机")
    if selected_mode in {"AI协同选择", "AI协同选择+规则兜底", "AI意图定向选择", "AI意图定向选择+规则兜底"} and enabled:
        result, metadata = ai_select_tags_for_fields(
            values,
            db_path=db_path,
            provider=provider if isinstance(provider, dict) else {},
            node_name="GALIAIS-Nodes 风格提示词节点",
            field_labels=field_labels or {},
            previous_context=str(previous_context or ""),
            strategy=strategy,
            per_field_count=per_field_count,
            per_field_counts=per_field_counts,
            seed=seed,
            allow_nsfw=allow_nsfw,
            min_post_count=min_post_count,
            per_field_min_post_counts=per_field_min_post_counts,
            freedom=ai_freedom,
            blacklist=blacklist,
            fallback_to_random=selected_mode in {"AI协同选择+规则兜底", "AI意图定向选择+规则兜底"},
            intent_text=intent_text if selected_mode.startswith("AI意图定向选择") else "",
            intent_detail=intent_detail,
            rag_mode=rag_mode,
            rag_candidate_count=rag_candidate_count,
            rag_example_count=rag_example_count,
        )
        metadata["mode"] = selected_mode
        intent_meta = metadata.get("intent_expansion") if isinstance(metadata.get("intent_expansion"), dict) else {}
        intent_meta["write_mode"] = str(intent_write_mode or "只放元信息")
        metadata["intent_expansion"] = intent_meta
        return result, metadata
    result, metadata = _apply_random_fields(
        values,
        db_path=db_path,
        enabled=enabled,
        strategy=strategy,
        per_field_count=per_field_count,
        per_field_counts=per_field_counts,
        seed=seed,
        allow_nsfw=allow_nsfw,
        min_post_count=min_post_count,
        per_field_min_post_counts=per_field_min_post_counts,
        blacklist=blacklist,
    )
    metadata["mode"] = "规则随机"
    metadata["freedom"] = float(ai_freedom or 0.0)
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
                **random_controls("渲染风格", "媒介", "色彩", "光照", "后期效果", "设计风格", "质量细节"),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "上游上下文": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/conditioning"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return _runtime_random_is_changed(*args, **kwargs)

    def run(self, 渲染风格, 媒介, 色彩, 光照, 后期效果, 设计风格, 质量细节, 追加到提示词, 插入位置, 去重, 使用渲染风格, 使用媒介, 使用色彩, 使用光照, 使用后期效果, 使用设计风格, 使用质量细节, 使用追加到提示词, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, **kwargs):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
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
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            field_labels={
                "渲染风格": "渲染风格",
                "媒介": "媒介",
                "色彩": "色彩",
                "光照": "光照",
                "后期效果": "后期效果",
                "设计风格": "设计风格",
                "质量细节": "质量细节",
            },
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "渲染风格": "渲染风格",
                    "媒介": "媒介",
                    "色彩": "色彩",
                    "光照": "光照",
                    "后期效果": "后期效果",
                    "设计风格": "设计风格",
                    "质量细节": "质量细节",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        prompt = join_prompt_parts(
            [prompt, _intent_expansion_note(random_meta, kwargs.get("AI是否写入补充", "只放元信息"))],
            dedupe=去重,
        )
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
