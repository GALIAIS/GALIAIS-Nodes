import json
import re
from pathlib import Path

try:
    from .nodes_galiais_prompt_system import (
        DanbooruDictionary,
        AI_TAG_GENERATION_MODES,
        GALIAIS_NODES_NEGATIVE_PRESETS,
        GALIAIS_NODES_QUALITY_PRESETS,
        ai_select_tags_for_fields,
        apply_tag_weight,
        format_tag_display_parts,
        join_tag_display_parts,
        optional_danbooru_db_path,
        join_prompt_parts,
        join_anima_prompt_parts,
        normalize_artist_tag,
        normalize_tag_blacklist,
        parse_tag_option,
        runtime_random_is_changed,
        split_tag_option_text,
        split_tag_text,
    )
except ImportError:  # direct test import
    from nodes_galiais_prompt_system import (
        DanbooruDictionary,
        AI_TAG_GENERATION_MODES,
        GALIAIS_NODES_NEGATIVE_PRESETS,
        GALIAIS_NODES_QUALITY_PRESETS,
        ai_select_tags_for_fields,
        apply_tag_weight,
        format_tag_display_parts,
        join_tag_display_parts,
        optional_danbooru_db_path,
        join_prompt_parts,
        join_anima_prompt_parts,
        normalize_artist_tag,
        normalize_tag_blacklist,
        parse_tag_option,
        runtime_random_is_changed,
        split_tag_option_text,
        split_tag_text,
    )

def _metadata_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _read_composer_template_store() -> dict:
    try:
        raw = json.loads(COMPOSER_TEMPLATE_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    templates = raw.get("templates") if isinstance(raw.get("templates"), dict) else {}
    normalized = {}
    for name, item in templates.items():
        if not isinstance(item, dict):
            continue
        safe_name = str(name or "").strip()
        template = str(item.get("template") or "").strip()
        if not safe_name or not template:
            continue
        normalized[safe_name] = {
            "template": template,
            "description": str(item.get("description") or "").strip(),
        }
    return {"version": 1, "templates": normalized}


def _write_composer_template_store(store: dict) -> dict:
    templates = store.get("templates") if isinstance(store.get("templates"), dict) else {}
    payload = {"version": 1, "templates": templates}
    tmp = COMPOSER_TEMPLATE_STORE_PATH.with_suffix(COMPOSER_TEMPLATE_STORE_PATH.suffix + ".tmp")
    tmp.write_text(_metadata_json(payload), encoding="utf-8")
    tmp.replace(COMPOSER_TEMPLATE_STORE_PATH)
    return payload


def _composer_template_names() -> list[str]:
    return sorted(_read_composer_template_store().get("templates", {}).keys())


def _normalize_template_name(name: str) -> str:
    return re.sub(r"\s+", "_", str(name or "").strip())


def _load_composer_template(name: str, inline_template: str = "") -> tuple[str, str]:
    text = str(inline_template or "").strip()
    if text:
        return text, "inline"
    safe_name = _normalize_template_name(name)
    if not safe_name:
        return "", "default"
    item = _read_composer_template_store().get("templates", {}).get(safe_name)
    if isinstance(item, dict) and str(item.get("template") or "").strip():
        return str(item["template"]).strip(), safe_name
    return "", "default"


ANIMA_SECTION_ORDER = {
    "core": 10,
    "face": 18,
    "appearance": 20,
    "body": 22,
    "outfit": 30,
    "pose": 40,
    "narrative": 55,
    "scene": 60,
    "object": 62,
    "meta": 80,
    "nsfw": 90,
}


TAXONOMY_FIELDS = {
    "identity_subject": [
        "0.subject.count.single_subject",
        "0.subject.count.multiple_subjects",
        "0.subject.count.no_subject",
        "0.subject.identity.gender_presentation",
    ],
    "identity_character": [
        "4.character.identity.named_character",
        "4.character.identity.alternate_identity",
        "4.character.variant.outfit_variant",
        "4.character.variant.event_or_seasonal_variant",
        "4.character.variant.crossover_or_costume_variant",
    ],
    "identity_work": [
        "3.copyright.medium.anime_manga",
        "3.copyright.medium.game_console_pc",
        "3.copyright.medium.mobile_gacha",
        "3.copyright.medium.visual_novel",
        "3.copyright.medium.vocal_synth",
        "3.copyright.medium.music_project",
        "3.copyright.medium.vtuber_agency",
        "3.copyright.medium.tabletop_or_card_game",
        "3.copyright.medium.western_media",
        "3.copyright.medium.meme_or_internet",
        "3.copyright.medium.original_work",
        "3.copyright.medium.unknown_or_other_work",
        "3.copyright.organization.faction_or_group",
    ],
    "identity_artist": [
        "1.artist.identity.person_artist",
        "1.artist.identity.circle_or_studio",
        "1.artist.style.signature_style",
    ],
    "identity_role": [
        "0.subject.identity.age_stage",
        "0.subject.identity.relationship",
        "4.character.role.archetype_role",
        "4.character.role.occupation_role",
        "4.character.species.human_character",
        "4.character.species.nonhuman_character",
        "4.character.variant.age_or_body_variant",
    ],
    "face_hair": [
        "0.appearance.hair.length.hair_length",
        "0.appearance.hair.color.natural_hair_color",
        "0.appearance.hair.color.fantasy_hair_color",
        "0.appearance.hair.style.bangs_and_parting",
        "0.appearance.hair.style.cut_shape",
        "0.appearance.hair.style.tied_hair",
        "0.appearance.hair.texture.hair_texture",
        "0.appearance.hair.accessory.hair_accessory",
    ],
    "face_eyes": [
        "0.appearance.eyes.color.eye_color",
        "0.appearance.eyes.shape.eye_shape",
        "0.appearance.eyes.pupil.pupil_design",
        "0.appearance.eyes.state.eye_state",
        "0.appearance.eyes.gaze.gaze_direction",
        "0.expression.gaze.viewer_engagement",
    ],
    "face_face": [
        "0.appearance.face.expression.facial_expression",
        "0.appearance.face.mouth.mouth_state",
        "0.appearance.face.teeth_tongue.teeth_or_tongue",
        "0.appearance.face.feature.face_feature",
        "0.appearance.face.makeup.cosmetic_makeup",
        "0.appearance.face.marking.facial_marking",
        "0.appearance.face.ears.ear_type",
    ],
    "face_expression": [
        "0.expression.emotion.positive_emotion",
        "0.expression.emotion.negative_emotion",
        "0.expression.emotion.embarrassment",
        "0.expression.emotion.neutral_or_cool",
        "0.expression.emotion.affection_or_desire",
        "0.expression.reaction.comic_or_exaggerated_reaction",
        "0.expression.reaction.physical_reaction",
        "0.expression.mental.thought_or_imagination",
    ],
    "body_shape": [
        "0.appearance.body.build.body_build",
        "0.appearance.body.proportion.body_proportion",
        "0.appearance.body.breast.breast_size_shape",
        "0.appearance.body.anatomy.anatomical_detail",
    ],
    "body_limbs": [
        "0.appearance.body.limb.limbs_hands_feet",
        "0.pose.gesture.arm_position",
        "0.pose.gesture.leg_position",
        "0.pose.gesture.head_or_torso",
        "0.subject.focus.body_focus",
    ],
    "body_skin": [
        "0.appearance.body.skin.skin_tone",
        "0.appearance.body.skin.skin_marking",
        "0.appearance.body.texture.body_surface_texture",
        "0.appearance.body.injury.bandage_or_wound",
    ],
    "body_nonhuman": [
        "0.appearance.body.animal.animal_ears_tail",
        "0.appearance.body.nonhuman.horns_wings_scales",
        "0.appearance.body.transformation_or_hybrid_state",
    ],
    "outfit_upper": [
        "0.clothing.upper.inner_top",
        "0.clothing.upper.outerwear",
        "0.clothing.upper.neckwear",
    ],
    "outfit_lower": [
        "0.clothing.lower.pants_shorts",
        "0.clothing.lower.skirt_dress_bottom",
        "0.clothing.lower.legwear",
        "0.clothing.lower.footwear",
    ],
    "outfit_onepiece": [
        "0.clothing.onepiece.dress",
        "0.clothing.onepiece.uniform",
        "0.clothing.onepiece.swimwear",
        "0.clothing.onepiece.armor_suit",
        "0.clothing.onepiece.traditional_wear",
        "0.clothing.onepiece.sleepwear_loungewear",
        "0.clothing.intimate.underwear_garment",
    ],
    "outfit_accessory": [
        "0.clothing.accessory.headwear",
        "0.clothing.accessory.eyewear",
        "0.clothing.accessory.jewelry",
        "0.clothing.accessory.gloves",
        "0.clothing.accessory.bag",
        "0.clothing.accessory.waist_belt_sash",
    ],
    "outfit_material_detail": [
        "0.clothing.material.fabric_material",
        "0.clothing.pattern.print_or_pattern",
        "0.clothing.detail.decorative_detail",
        "0.clothing.detail.functional_detail",
    ],
    "outfit_state": [
        "0.clothing.state.damage_or_wet",
        "0.clothing.state.fit_and_opening",
        "0.clothing.state.lift_or_removed",
        "0.clothing.state.unworn_or_carried",
    ],
    "pose_posture": [
        "0.pose.posture.standing_pose",
        "0.pose.posture.sitting_pose",
        "0.pose.posture.lying_pose",
        "0.pose.posture.kneeling_squatting",
        "0.pose.posture.dynamic_motion",
    ],
    "pose_gesture": [
        "0.pose.gesture.hand_gesture",
        "0.pose.gesture.arm_position",
        "0.pose.gesture.leg_position",
        "0.pose.gesture.head_or_torso",
    ],
    "pose_action": [
        "0.pose.action.holding_object",
        "0.pose.action.object_manipulation",
        "0.pose.action.daily_activity",
        "0.pose.action.performance_action",
        "0.pose.action.combat_action",
        "0.pose.action.directional_or_spatial_action",
        "0.pose.action.social_or_intentional_action",
        "0.pose.action.body_contact_or_support",
        "0.pose.action.body_manipulation",
        "0.pose.action.covering_or_hiding",
        "0.pose.action.force_or_impact_action",
    ],
    "pose_interaction": [
        "0.pose.interaction.physical_interaction",
        "0.subject.identity.relationship",
        "0.narrative.relationship.family_or_romance",
        "0.narrative.event.life_event_or_milestone",
        "0.narrative.sequence.temporal_context",
    ],
    "scene_camera": [
        "0.composition.framing.shot_size",
        "0.composition.framing.crop_boundary",
        "0.composition.camera.camera_angle",
        "0.composition.camera.view_direction",
        "0.composition.depth.focus_depth",
        "0.composition.layout.subject_placement",
        "0.composition.layout.paneling",
        "0.composition.perspective.lens_perspective",
        "0.subject.focus.body_focus",
        "0.subject.focus.object_focus",
    ],
    "scene_location": [
        "0.scene.location.indoor_private",
        "0.scene.location.indoor_public",
        "0.scene.location.outdoor_nature",
        "0.scene.location.outdoor_urban",
        "0.scene.location.water_or_sky",
        "0.scene.location.fantasy_or_sci_fi",
        "0.scene.location.real_world_or_brand_reference",
        "0.scene.background.background_density",
        "0.scene.background.background_pattern",
        "0.scene.structure.architecture",
        "0.scene.structure.barrier_or_surface",
        "0.scene.decor.ornament_or_decoration",
        "0.scene.object.temporary_shelter_or_outdoor_fixture",
        "0.scene.symbol.symbol_or_emblem",
        "0.scene.culture.region_or_period_theme",
        "0.scene.culture.holiday_or_festival",
    ],
    "scene_time_weather": [
        "0.scene.environment.weather",
        "0.scene.environment.time_of_day",
        "0.scene.environment.season",
    ],
    "scene_object": [
        "0.object.nature.animal",
        "0.object.nature.animal_species_specific",
        "0.object.nature.plant",
        "0.object.nature.plant_species_specific",
        "0.object.nature.biological_specimen",
        "0.object.nature.mineral_natural_object",
        "0.object.food.solid_food",
        "0.object.food.drink_container",
        "0.object.prop.weapon",
        "0.object.prop.tool",
        "0.object.prop.device",
        "0.object.prop.vehicle",
        "0.object.prop.furniture",
        "0.object.prop.instrument",
        "0.object.prop.book_paper",
        "0.object.prop.container",
        "0.object.prop.decorative_object",
        "0.object.prop.personal_accessory",
        "0.object.prop.string_or_fastener",
        "0.object.prop.shape_or_mechanical_part",
        "0.object.prop.brand_or_merchandise_item",
    ],
    "object_media_document": [
        "0.object.media.cover_or_physical_release",
        "0.object.prop.book_paper",
        "0.object.prop.page_or_document_piece",
    ],
    "object_prop_extra": [
        "0.object.prop.weapon",
        "0.object.prop.tool",
        "0.object.prop.device",
        "0.object.prop.vehicle",
        "0.object.prop.furniture",
        "0.object.prop.instrument",
        "0.object.prop.container",
        "0.object.prop.decorative_object",
        "0.object.prop.personal_accessory",
        "0.object.prop.string_or_fastener",
        "0.object.prop.shape_or_mechanical_part",
        "0.object.prop.brand_or_merchandise_item",
    ],
    "scene_visual_style": [
        "0.style.rendering.render_style",
        "0.style.line.line_art",
        "0.style.medium.art_medium",
        "0.style.design.decorative_or_graphic_design",
        "0.style.design.fashion_or_costume_style",
        "0.style.postprocess.analog_media_artifact",
        "0.style.postprocess.image_effect",
        "0.effect.damage.impact_effect",
        "0.effect.digital.digital_effect",
        "0.effect.elemental.elemental_effect",
        "0.effect.energy.aura_or_glow",
        "0.effect.material.liquid_or_material_state",
        "0.effect.motion.motion_effect",
        "0.effect.particle.particle_effect",
        "0.effect.supernatural.supernatural_effect",
        "0.effect.surface.mark_or_stain",
    ],
    "nsfw_exposure": [
        "0.nsfw.exposure.full_nudity",
        "0.nsfw.exposure.partial_nudity",
        "0.nsfw.exposure.underwear_exposure",
    ],
    "nsfw_body": [
        "0.nsfw.body.explicit_breasts",
        "0.nsfw.body.explicit_genitalia",
        "0.nsfw.body.sexual_body_state",
    ],
    "nsfw_act": [
        "0.nsfw.act.breast_or_thigh_sex",
        "0.nsfw.act.manual_or_self",
        "0.nsfw.act.oral_sex",
        "0.nsfw.act.penetrative_sex",
        "0.nsfw.act.sexual_impact_or_coercion",
    ],
    "nsfw_context": [
        "0.nsfw.context.sexual_theme",
        "0.nsfw.framing.sexual_framing",
        "0.nsfw.fluid.sexual_fluid",
    ],
    "nsfw_fetish_object": [
        "0.nsfw.fetish.bdsm_power",
        "0.nsfw.fetish.body_fluid_excretion",
        "0.nsfw.fetish.bondage_restraint",
        "0.nsfw.fetish.nonhuman_sexual",
        "0.nsfw.fetish.sex_toy",
        "0.nsfw.object.condom_or_sexual_item",
    ],
    "meta_reference": [
        "0.meta.reference.cosplay",
        "0.meta.reference.meme_or_internet",
    ],
    "meta_admin_quality": [
        "5.meta.admin.tag_status",
        "5.meta.quality.quality_rating",
    ],
    "meta_technical": [
        "5.meta.technical.aspect_ratio",
        "5.meta.technical.gameplay_or_ui",
        "5.meta.technical.resolution",
        "5.meta.technical.source_type",
    ],
    "meta_overlay_process": [
        "5.meta.censorship.censoring",
        "5.meta.language.translation",
        "5.meta.overlay.text_or_symbol",
        "5.meta.process.generation_or_editing",
        "5.meta.source.release_or_cover",
        "5.meta.event.challenge_or_celebration",
    ],
    "narrative_relationship": [
        "0.narrative.relationship.family_or_romance",
        "0.narrative.event.life_event_or_milestone",
        "0.narrative.sequence.temporal_context",
    ],
    "narrative_theme_state": [
        "0.narrative.event.threat_failure_or_death",
        "0.narrative.reference.crossover_or_canon",
        "0.narrative.state.supernatural_or_possession",
        "0.narrative.theme.symbolic_or_abstract_theme",
    ],
    "uncertain_review": [
        "9.uncertain.review.ambiguous_name",
        "9.uncertain.review.insufficient_context",
        "9.uncertain.review.policy_sensitive",
    ],
}

CATEGORY_FIELDS = {}


def combo(field: str, default: str = "", *, multiline: bool = False):
    return (
        "STRING",
        {
            "default": "" if default == "none" else default,
            "multiline": multiline,
            "galiais_nodes_danbooru_field": field,
            "galiais_nodes_danbooru_lazy": True,
        },
    )


def text(default: str = "", *, multiline: bool = True):
    return ("STRING", {"default": default, "multiline": multiline})


def optional_db():
    return {"DB": ("GALIAIS_NODES_DANBOORU_DB",)}


def optional_generation_inputs():
    return {
        "DB": ("GALIAIS_NODES_DANBOORU_DB",),
        "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
        "上游上下文": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
        "上游提示词段": ("GALIAIS_NODES_CHARACTER_SECTION",),
    }


def field_enabled_controls(*labels: str):
    return {
        f"使用{label}": ("BOOLEAN", {"default": True})
        for label in labels
    }


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


def random_controls(*labels: str, default_allow_nsfw: bool = False):
    return {
        "启用随机Tag": ("BOOLEAN", {"default": False}),
        "Tag生成模式": (AI_TAG_GENERATION_MODES, {"default": "规则随机"}),
        "AI自由度": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05}),
        "AI意图方向": (
            "STRING",
            {
                "default": "",
                "multiline": True,
                "tooltip": "粗略描述你想要的方向；AI只会从当前节点已启用字段的候选tag中选择，并把方向扩写成自然语言。",
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
        "随机允许NSFW": ("BOOLEAN", {"default": default_allow_nsfw}),
        "随机最低热度": ("INT", {"default": 0, "min": 0, "max": 100000000}),
        **random_min_post_count_controls(*labels),
    }


CHARACTER_SCOPE_OPTIONS = ["全局"] + [f"角色{i}" for i in range(1, 9)]
CHARACTER_SEPARATOR_OPTIONS = ["分号", "逗号", "换行"]
COMPOSER_TEMPLATE_STORE_PATH = Path(__file__).with_name("galiais_composer_templates.json")
COMPOSER_DEFAULT_TEMPLATE = "{{quality}}, {{prefix}}, {{all_sections}}, {{suffix}}"
COMPOSER_TEMPLATE_SLOT_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-\u4e00-\u9fff]+)\s*\}\}")


def character_scope_controls(default_slot: str = "全局"):
    safe_default = default_slot if default_slot in CHARACTER_SCOPE_OPTIONS else "全局"
    return {
        "角色槽位": (CHARACTER_SCOPE_OPTIONS, {"default": safe_default}),
        "角色标签": ("STRING", {"default": "", "multiline": False}),
    }


def _normalize_character_slot(slot: str) -> tuple[str, int | None, bool]:
    text_value = str(slot or "").strip()
    if text_value not in CHARACTER_SCOPE_OPTIONS:
        text_value = "全局"
    if text_value == "全局":
        return text_value, None, True
    try:
        return text_value, int(text_value.replace("角色", "", 1)), False
    except ValueError:
        return "全局", None, True


def _apply_character_scope(section: dict, slot: str = "全局", label: str = "") -> dict:
    normalized_slot, slot_index, is_global = _normalize_character_slot(slot)
    clean_label = str(label or "").strip()
    scope = {
        "slot": normalized_slot,
        "index": slot_index,
        "label": clean_label,
        "is_global": is_global,
    }
    section["character_scope"] = scope
    section["character_slot"] = normalized_slot
    section["character_label"] = clean_label
    return section


def _resolve_legacy_scope_args(DB, slot, label):
    if isinstance(label, dict) and isinstance(DB, str):
        return label, DB, slot
    if isinstance(DB, str) and DB in CHARACTER_SCOPE_OPTIONS and not isinstance(label, dict):
        return None, DB, slot
    if DB is None and isinstance(slot, dict) and not str(label or "").strip():
        return slot, "全局", ""
    return DB, slot, label


def _join_prompt_chunks(parts, separator: str = ", ") -> str:
    cleaned = [str(part or "").strip().strip(",") for part in parts if str(part or "").strip().strip(",")]
    return separator.join(cleaned)


def _normalize_parts(parts, db_path: str = ""):
    normalized = []
    for part in parts:
        for token in split_tag_option_text(str(part or "")):
            parsed = parse_tag_option(token, db_path=db_path)
            if parsed:
                normalized.append(parsed)
    return normalized


def _merge_random_field_value(existing: str, random_options, *, append: bool) -> str:
    random_text = join_tag_display_parts(
        [
            format_tag_display_parts(item.get("tag", ""), item.get("label", ""))
            for item in random_options
        ],
        dedupe=True,
    )
    if not random_text:
        return str(existing or "")
    if append:
        return join_tag_display_parts([existing, random_text], dedupe=True)
    return str(existing or "").strip() or random_text


def _random_options_display(random_options) -> str:
    return join_tag_display_parts(
        [
            format_tag_display_parts(item.get("tag", ""), item.get("label", ""))
            for item in random_options
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


class _RuntimeRandomRefreshMixin:
    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return _runtime_random_is_changed(*args, **kwargs)


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
    field_values: dict[str, str],
    *,
    db_path: str = "",
    enabled: bool = False,
    strategy: str = "只补空字段",
    per_field_count: int = 1,
    per_field_counts=None,
    seed: int = 0,
    allow_nsfw: bool = False,
    min_post_count: int = 0,
    per_field_min_post_counts=None,
    blacklist=None,
) -> tuple[dict[str, str], dict]:
    values = {key: str(value or "") for key, value in field_values.items()}
    safe_count = max(0, int(per_field_count or 0))
    safe_min_post_count = max(0, int(min_post_count or 0))
    effective_counts = _effective_random_counts(values.keys(), safe_count, per_field_counts)
    effective_min_post_counts = _effective_min_post_counts(values.keys(), safe_min_post_count, per_field_min_post_counts)
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
        metadata["field_values"] = dict(values)
        return values, metadata

    append = strategy == "追加到字段"
    base_seed = int(seed or 0)
    dictionary = DanbooruDictionary(db_path)
    for index, (field, current) in enumerate(values.items()):
        field_count = effective_counts.get(field, safe_count)
        if field_count <= 0:
            continue
        if not append and str(current or "").strip():
            continue
        field_seed = base_seed + index if base_seed else 0
        options = dictionary.random_options_for_field(
            field,
            count=field_count,
            seed=field_seed,
            allow_nsfw=bool(allow_nsfw),
            min_post_count=effective_min_post_counts.get(field, safe_min_post_count),
            blacklist=blacklist_tags,
        )
        if not options:
            continue
        values[field] = _merge_random_field_value(current, options, append=append)
        metadata["items"][field] = options
        random_text = _random_options_display(options)
        if random_text:
            metadata["random_field_values"][field] = random_text
    metadata["field_values"] = dict(values)
    return values, metadata


def _upstream_context_text(context: str = "", section=None) -> str:
    parts = [str(context or "").strip()]
    if isinstance(section, dict):
        for key in ("text", "character_label", "character_slot"):
            value = str(section.get(key) or "").strip()
            if value:
                parts.append(value)
    return join_prompt_parts(parts, dedupe=True)


def _apply_generated_fields(
    field_values: dict[str, str],
    *,
    db_path: str = "",
    enabled: bool = False,
    mode: str = "规则随机",
    provider=None,
    previous_context: str = "",
    upstream_section=None,
    role_slot: str = "",
    role_label: str = "",
    field_labels: dict[str, str] | None = None,
    ai_freedom: float = 0.35,
    strategy: str = "只补空字段",
    per_field_count: int = 1,
    per_field_counts=None,
    seed: int = 0,
    allow_nsfw: bool = False,
    min_post_count: int = 0,
    per_field_min_post_counts=None,
    blacklist=None,
    intent_text: str = "",
    intent_detail: str = "标准",
    intent_write_mode: str = "只放元信息",
    rag_mode: str = "关闭",
    rag_candidate_count: int = 12,
    rag_example_count: int = 3,
) -> tuple[dict[str, str], dict]:
    selected_mode = str(mode or "规则随机")
    if selected_mode in {"AI协同选择", "AI协同选择+规则兜底", "AI意图定向选择", "AI意图定向选择+规则兜底"} and enabled:
        values, metadata = ai_select_tags_for_fields(
            field_values,
            db_path=db_path,
            provider=provider if isinstance(provider, dict) else {},
            node_name="GALIAIS-Nodes 角色提示词节点",
            field_labels=field_labels or {},
            previous_context=_upstream_context_text(previous_context, upstream_section),
            role_slot=role_slot,
            role_label=role_label,
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
        return values, metadata
    values, metadata = _apply_random_fields(
        field_values,
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
    return values, metadata


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


def _with_intent_expansion_note(note: str, random_meta: dict | None, write_mode: str | None = None) -> str:
    extra = _intent_expansion_note(random_meta, write_mode)
    if not extra:
        return str(note or "")
    return join_prompt_parts([note, extra], dedupe=True)


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


def _section_result(section: dict, random_meta: dict | None = None, widget_mapping: dict[str, str] | None = None):
    _append_intent_expansion_to_section(section, random_meta)
    result = _section_tuple(section)
    ui = _random_ui_payload(random_meta or {}, widget_mapping or {})
    if not ui:
        return result
    return {"ui": ui, "result": result}


def _append_intent_expansion_to_section(section: dict, random_meta: dict | None = None) -> None:
    if not isinstance(section, dict) or not section.get("enabled", True):
        return
    note = _intent_expansion_note(random_meta)
    if not note:
        return
    current_text = str(section.get("text") or "").strip()
    merged_text = f"{current_text}, {note}".strip(" ,") if current_text else note
    section["text"] = merged_text
    section["tags"] = split_tag_text(merged_text)
    section["natural_language"] = note


def character_section_text(
    name: str,
    parts,
    *,
    enabled: bool = True,
    weight: float = 1.0,
    dedupe: bool = True,
    db_path: str = "",
) -> dict:
    if not enabled:
        return {"name": name, "text": "", "tags": [], "enabled": False, "weight": weight}

    text_value = join_anima_prompt_parts(_normalize_parts(parts, db_path=db_path), dedupe=dedupe, db_path=db_path)
    tags = split_tag_text(text_value)
    if abs(float(weight) - 1.0) > 0.0001:
        tags = [apply_tag_weight(tag, weight) for tag in tags]
        text_value = join_prompt_parts(tags, dedupe=False)

    return {
        "name": name,
        "text": text_value,
        "tags": tags,
        "enabled": True,
        "weight": weight,
    }


def _section_tuple(section: dict):
    return (section, section["text"], _metadata_json(section))


def _ordered_sections(active_sections):
    return sorted(
        enumerate(active_sections),
        key=lambda item: (ANIMA_SECTION_ORDER.get(item[1].get("name"), 50), item[0]),
    )


def _section_scope(section: dict) -> dict:
    scope = section.get("character_scope") if isinstance(section.get("character_scope"), dict) else {}
    slot, index, is_global = _normalize_character_slot(scope.get("slot") or section.get("character_slot", "全局"))
    return {
        "slot": slot,
        "index": index,
        "label": str(scope.get("label") or section.get("character_label") or "").strip(),
        "is_global": is_global,
    }


def _sections_text_and_artists(ordered_sections, *, dedupe: bool = True) -> tuple[str, list[str]]:
    artist_tags = []
    for _, section in ordered_sections:
        artist = normalize_artist_tag(section.get("artist", ""))
        if artist:
            artist_tags.append(artist)
    text_value = join_anima_prompt_parts(
        [*artist_tags, *[section["text"] for _, section in ordered_sections]],
        dedupe=dedupe,
        allow_artist=True,
    )
    return text_value, artist_tags


def _quality_prompt_text(quality: str, *, dedupe: bool = True) -> str:
    return join_prompt_parts([quality], dedupe=dedupe)


def _join_positive_with_quality(quality: str, parts, *, dedupe: bool = True, clean_body: bool = True) -> str:
    quality_text = _quality_prompt_text(quality, dedupe=dedupe)
    body = join_anima_prompt_parts(parts, dedupe=dedupe, allow_artist=True) if clean_body else _join_prompt_chunks(parts)
    return _join_prompt_chunks([quality_text, body])


def _section_text_map(ordered_sections, *, dedupe: bool = True) -> dict[str, str]:
    grouped = {}
    for _, section in ordered_sections:
        name = str(section.get("name") or "").strip()
        if not name:
            continue
        grouped.setdefault(name, []).append(section.get("text", ""))
    return {
        key: join_anima_prompt_parts(values, dedupe=dedupe, allow_artist=True)
        for key, values in grouped.items()
    }


def _composer_template_slots(
    *,
    quality: str,
    prefix: str,
    suffix: str,
    composed_text: str,
    ordered_sections,
    artist_tags,
    characters,
    dedupe: bool,
) -> dict[str, str]:
    section_map = _section_text_map(ordered_sections, dedupe=dedupe)
    slots = {
        "quality": _quality_prompt_text(quality, dedupe=dedupe),
        "prefix": prefix,
        "suffix": suffix,
        "all_sections": composed_text,
        "sections": composed_text,
        "artist": join_prompt_parts(artist_tags, dedupe=dedupe),
        "characters": "; ".join(
            str(character.get("text") or "").strip()
            for character in characters or []
            if str(character.get("text") or "").strip()
        ),
    }
    slots.update(section_map)
    aliases = {
        "主体": "core",
        "身份": "core",
        "角色身份": "core",
        "脸发眼": "face",
        "身体": "body",
        "服装": "outfit",
        "姿势": "pose",
        "姿态动作": "pose",
        "场景": "scene",
        "场景镜头": "scene",
        "物件": "object",
        "叙事": "narrative",
        "Meta": "meta",
        "meta": "meta",
        "NSFW": "nsfw",
        "nsfw": "nsfw",
        "全部": "all_sections",
        "质量": "quality",
        "前缀": "prefix",
        "后缀": "suffix",
        "画师": "artist",
        "多角色": "characters",
    }
    for alias, target in aliases.items():
        if alias not in slots:
            slots[alias] = slots.get(target, "")
    return slots


def _render_composer_template(template: str, slots: dict[str, str], *, dedupe: bool = True) -> str:
    def replace(match):
        key = match.group(1)
        return str(slots.get(key, "") or "")

    rendered = COMPOSER_TEMPLATE_SLOT_RE.sub(replace, str(template or ""))
    return join_prompt_parts([rendered], dedupe=dedupe)


def _compose_scoped_character_sections(ordered_sections, *, dedupe: bool = True, separator: str = "分号") -> tuple[str, list[dict]]:
    global_sections = []
    character_groups: dict[str, dict] = {}
    for original_index, section in ordered_sections:
        scope = _section_scope(section)
        if scope["is_global"]:
            global_sections.append((original_index, section))
            continue
        group = character_groups.setdefault(
            scope["slot"],
            {
                "slot": scope["slot"],
                "index": scope["index"] or 999,
                "label": scope["label"],
                "sections": [],
            },
        )
        if scope["label"] and not group["label"]:
            group["label"] = scope["label"]
        group["sections"].append((original_index, section))

    characters = []
    character_texts = []
    for group in sorted(character_groups.values(), key=lambda item: item["index"]):
        ordered_group_sections = _ordered_sections([section for _, section in group["sections"]])
        text_value, artist_tags = _sections_text_and_artists(ordered_group_sections, dedupe=dedupe)
        if not text_value:
            continue
        characters.append({
            "slot": group["slot"],
            "index": group["index"],
            "label": group["label"],
            "text": text_value,
            "artist_tags": artist_tags,
            "sections": [section for _, section in ordered_group_sections],
        })
        character_texts.append(text_value)

    global_text, global_artist_tags = _sections_text_and_artists(global_sections, dedupe=dedupe)
    separator_text = {
        "分号": "; ",
        "换行": "\n",
        "逗号": ", ",
    }.get(separator, "; ")
    text_parts = [*character_texts]
    if global_text:
        text_parts.append(global_text)
    scoped_text = separator_text.join(part for part in text_parts if str(part or "").strip())
    if global_text:
        characters.append({
            "slot": "全局",
            "index": None,
            "label": "",
            "text": global_text,
            "artist_tags": global_artist_tags,
            "sections": [section for _, section in global_sections],
        })
    return scoped_text, characters


def _coerce_character_sections(sections) -> list[dict]:
    return [
        section
        for section in sections
        if isinstance(section, dict) and section.get("enabled", True) and str(section.get("text") or "").strip()
    ]


def _position_phrase(index: int, layout: str, language: str) -> str:
    layout_text = str(layout or "左到右")
    if str(language or "") == "中文":
        if layout_text == "前后景":
            return "前景" if index == 0 else "中景" if index == 1 else "背景层"
        if layout_text == "中心环绕":
            return "画面中心" if index == 0 else "中心周围"
        if layout_text == "对称":
            return "左侧" if index == 0 else "右侧" if index == 1 else "后方"
        return "左侧" if index == 0 else "右侧" if index == 1 else "画面后侧"
    if layout_text == "前后景":
        return "in the foreground" if index == 0 else "in the midground" if index == 1 else "in the background layer"
    if layout_text == "中心环绕":
        return "at the center of the image" if index == 0 else "around the central subject"
    if layout_text == "对称":
        return "on the left side of the image" if index == 0 else "on the right side of the image" if index == 1 else "behind the main pair"
    return "on the left side of the image" if index == 0 else "on the right side of the image" if index == 1 else "toward the rear side of the image"


def build_multi_character_layout(
    sections,
    *,
    language: str = "英文",
    layout: str = "左到右",
    relation: str = "交互",
    extra_note: str = "",
    dedupe: bool = True,
) -> dict:
    active_sections = _coerce_character_sections(sections)
    ordered_sections = _ordered_sections(active_sections)
    _, characters = _compose_scoped_character_sections(ordered_sections, dedupe=dedupe, separator="分号")
    scoped_characters = [
        character for character in characters
        if str(character.get("slot") or "") != "全局" and str(character.get("text") or "").strip()
    ]
    global_character = next((character for character in characters if str(character.get("slot") or "") == "全局"), None)
    character_map = {}
    descriptions = []
    for index, character in enumerate(scoped_characters):
        slot = str(character.get("slot") or f"角色{index + 1}")
        label = str(character.get("label") or slot)
        position = _position_phrase(index, layout, language)
        text_value = str(character.get("text") or "").strip()
        character_map[slot] = {
            "slot": slot,
            "index": character.get("index"),
            "label": label,
            "position": position,
            "text": text_value,
            "sections": character.get("sections", []),
        }
        if str(language or "") == "中文":
            descriptions.append(f"{label}位于{position}，保留 {text_value}。")
        else:
            descriptions.append(f"{label} is {position}, preserving {text_value}.")
    if global_character and str(global_character.get("text") or "").strip():
        character_map["全局"] = {
            "slot": "全局",
            "index": None,
            "label": "",
            "position": "global",
            "text": str(global_character.get("text") or "").strip(),
            "sections": global_character.get("sections", []),
        }
    relation_text = str(relation or "").strip()
    if str(language or "") == "中文":
        relation_sentence = f"角色关系保持{relation_text or '清晰互动'}，每个角色的服装、动作和位置彼此分离。"
    else:
        relation_sentence = f"The character relationship stays {relation_text or 'clearly interactive'}, with each outfit, action, and position kept separate."
    note = str(extra_note or "").strip()
    narrative_text = " ".join([*descriptions, relation_sentence, note]).strip()
    return {
        "characters": character_map,
        "character_count": len(scoped_characters),
        "layout": str(layout or "左到右"),
        "relation": relation_text,
        "language": str(language or "英文"),
        "narrative_text": narrative_text,
        "global_text": str(global_character.get("text") or "").strip() if global_character else "",
    }


def compose_character_prompt(
    sections,
    *,
    quality: str = "",
    negative: str = "",
    prefix: str = "",
    suffix: str = "",
    dedupe: bool = True,
    multi_character_mode: str = "自动",
    character_separator: str = "分号",
    template: str = "",
    template_name: str = "",
):
    active_sections = [
        section for section in sections
        if isinstance(section, dict) and section.get("enabled", True) and section.get("text")
    ]
    ordered_sections = _ordered_sections(active_sections)
    scoped_requested = multi_character_mode == "开启" or (
        multi_character_mode == "自动"
        and any(not _section_scope(section)["is_global"] for _, section in ordered_sections)
    )
    if scoped_requested:
        composed_text, characters = _compose_scoped_character_sections(
            ordered_sections,
            dedupe=dedupe,
            separator=character_separator,
        )
        artist_tags = [
            artist
            for character in characters
            for artist in character.get("artist_tags", [])
        ]
    else:
        composed_text, artist_tags = _sections_text_and_artists(ordered_sections, dedupe=dedupe)
        characters = []
    selected_template, selected_template_source = _load_composer_template(template_name, template)
    template_slots = _composer_template_slots(
        quality=quality,
        prefix=prefix,
        suffix=suffix,
        composed_text=composed_text,
        ordered_sections=ordered_sections,
        artist_tags=artist_tags,
        characters=characters,
        dedupe=dedupe,
    )
    if selected_template:
        positive = _render_composer_template(selected_template, template_slots, dedupe=dedupe)
        template_mode = "custom"
    else:
        positive = _join_positive_with_quality(
            quality,
            [prefix, composed_text, suffix],
            dedupe=dedupe,
            clean_body=not scoped_requested,
        )
        template_mode = "default"
    negative_prompt = join_prompt_parts([negative], dedupe=dedupe)
    metadata = {
        "quality": quality,
        "quality_included": bool(_quality_prompt_text(quality, dedupe=dedupe)),
        "quality_omitted_by_anima_template": False,
        "negative": negative_prompt,
        "prefix": prefix,
        "suffix": suffix,
        "dedupe": dedupe,
        "template_mode": template_mode,
        "template_source": selected_template_source,
        "template_name": _normalize_template_name(template_name),
        "template": selected_template,
        "template_slots": template_slots,
        "multi_character_mode": multi_character_mode,
        "multi_character_enabled": bool(scoped_requested),
        "character_separator": character_separator,
        "artist_tags": artist_tags,
        "characters": characters,
        "sections": [section for _, section in ordered_sections],
    }
    return (positive, negative_prompt, _metadata_json(metadata))
