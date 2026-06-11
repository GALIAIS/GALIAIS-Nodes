import json
try:
    from .nodes_galiais_prompt_system import (
        DanbooruDictionary,
        GALIAIS_NODES_NEGATIVE_PRESETS,
        GALIAIS_NODES_QUALITY_PRESETS,
        apply_tag_weight,
        format_tag_display_parts,
        join_tag_display_parts,
        optional_danbooru_db_path,
        register_danbooru_field_set,
        join_prompt_parts,
        join_anima_prompt_parts,
        normalize_artist_tag,
        parse_tag_option,
        runtime_random_is_changed,
        split_tag_option_text,
        split_tag_text,
    )
except ImportError:  # direct test import
    from nodes_galiais_prompt_system import (
        DanbooruDictionary,
        GALIAIS_NODES_NEGATIVE_PRESETS,
        GALIAIS_NODES_QUALITY_PRESETS,
        apply_tag_weight,
        format_tag_display_parts,
        join_tag_display_parts,
        optional_danbooru_db_path,
        register_danbooru_field_set,
        join_prompt_parts,
        join_anima_prompt_parts,
        normalize_artist_tag,
        parse_tag_option,
        runtime_random_is_changed,
        split_tag_option_text,
        split_tag_text,
    )


def _metadata_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


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
register_danbooru_field_set("character", TAXONOMY_FIELDS, CATEGORY_FIELDS)


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


def field_enabled_controls(*labels: str):
    return {
        f"使用{label}": ("BOOLEAN", {"default": True})
        for label in labels
    }


def random_controls(default_allow_nsfw: bool = False):
    return {
        "启用随机Tag": ("BOOLEAN", {"default": False}),
        "随机策略": (["只补空字段", "追加到字段"], {"default": "只补空字段"}),
        "每字段随机数": ("INT", {"default": 1, "min": 0, "max": 10}),
        "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
        "随机允许NSFW": ("BOOLEAN", {"default": default_allow_nsfw}),
        "随机最低热度": ("INT", {"default": 0, "min": 0, "max": 100000000}),
    }


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


def _runtime_random_is_changed(*args, **kwargs):
    return runtime_random_is_changed(
        kwargs.get("启用随机Tag", False),
        kwargs.get("每字段随机数", 0),
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


def _apply_random_fields(
    field_values: dict[str, str],
    *,
    db_path: str = "",
    enabled: bool = False,
    strategy: str = "只补空字段",
    per_field_count: int = 1,
    seed: int = 0,
    allow_nsfw: bool = False,
    min_post_count: int = 0,
) -> tuple[dict[str, str], dict]:
    values = {key: str(value or "") for key, value in field_values.items()}
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
        metadata["field_values"] = dict(values)
        return values, metadata

    append = strategy == "追加到字段"
    base_seed = int(seed or 0)
    dictionary = DanbooruDictionary(db_path)
    for index, (field, current) in enumerate(values.items()):
        if not append and str(current or "").strip():
            continue
        field_seed = base_seed + index if base_seed else 0
        options = dictionary.random_options_for_field(
            field,
            count=safe_count,
            seed=field_seed,
            allow_nsfw=bool(allow_nsfw),
            min_post_count=int(min_post_count or 0),
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
        return {}
    return {"galiais_random_fields": [widgets]}


def _section_result(section: dict, random_meta: dict | None = None, widget_mapping: dict[str, str] | None = None):
    result = _section_tuple(section)
    ui = _random_ui_payload(random_meta or {}, widget_mapping or {})
    if not ui:
        return result
    return {"ui": ui, "result": result}


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


def compose_character_prompt(
    sections,
    *,
    quality: str = "",
    negative: str = "",
    prefix: str = "",
    suffix: str = "",
    dedupe: bool = True,
):
    active_sections = [
        section for section in sections
        if isinstance(section, dict) and section.get("enabled", True) and section.get("text")
    ]
    ordered_sections = sorted(
        enumerate(active_sections),
        key=lambda item: (ANIMA_SECTION_ORDER.get(item[1].get("name"), 50), item[0]),
    )
    artist_tags = []
    for _, section in ordered_sections:
        artist = normalize_artist_tag(section.get("artist", ""))
        if artist:
            artist_tags.append(artist)
    ordered_text = [section["text"] for _, section in ordered_sections]
    positive = join_anima_prompt_parts(
        [prefix, *artist_tags, *ordered_text, suffix],
        dedupe=dedupe,
        allow_artist=True,
    )
    negative_prompt = join_prompt_parts([negative], dedupe=dedupe)
    metadata = {
        "quality": quality,
        "quality_omitted_by_anima_template": bool(str(quality or "").strip()),
        "negative": negative_prompt,
        "prefix": prefix,
        "suffix": suffix,
        "dedupe": dedupe,
        "sections": [section for _, section in ordered_sections],
    }
    return (positive, negative_prompt, _metadata_json(metadata))


class GaliaisNodesCharacterIdentity(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "主体人数": combo("identity_subject"),
                "角色": combo("identity_character"),
                "作品": combo("identity_work"),
                "画师": combo("identity_artist"),
                "年龄身份": combo("identity_role"),
                "身份补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("主体人数", "角色", "作品", "画师", "年龄身份", "身份补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("角色段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 主体人数, 角色, 作品, 画师, 年龄身份, 身份补充, 启用, 权重, 使用主体人数, 使用角色, 使用作品, 使用画师, 使用年龄身份, 使用身份补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("identity_subject", 主体人数, 使用主体人数),
                ("identity_character", 角色, 使用角色),
                ("identity_work", 作品, 使用作品),
                ("identity_artist", 画师, 使用画师),
                ("identity_role", 年龄身份, 使用年龄身份),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "core",
            [
                values.get("identity_subject", ""),
                values.get("identity_character", ""),
                values.get("identity_work", ""),
                values.get("identity_role", ""),
                _enabled_value(身份补充, 使用身份补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["artist"] = normalize_artist_tag(values.get("identity_artist", ""), db_path=db_path)
        section["artist_inserted_before_subject"] = bool(section["artist"])
        section["fields"] = _field_switch_metadata(
            ("identity_subject", "主体人数", 使用主体人数),
            ("identity_character", "角色", 使用角色),
            ("identity_work", "作品", 使用作品),
            ("identity_artist", "画师", 使用画师),
            ("identity_role", "年龄身份", 使用年龄身份),
            ("identity_note", "身份补充", 使用身份补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "identity_subject": "主体人数",
                "identity_character": "角色",
                "identity_work": "作品",
                "identity_artist": "画师",
                "identity_role": "年龄身份",
            },
        )


class GaliaisNodesCharacterFaceHairEyes(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "头发": combo("face_hair"),
                "眼睛视线": combo("face_eyes"),
                "脸部五官": combo("face_face"),
                "情绪表情": combo("face_expression"),
                "脸发眼补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("头发", "眼睛视线", "脸部五官", "情绪表情", "脸发眼补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("脸发眼段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 头发, 眼睛视线, 脸部五官, 情绪表情, 脸发眼补充, 启用, 权重, 使用头发, 使用眼睛视线, 使用脸部五官, 使用情绪表情, 使用脸发眼补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("face_hair", 头发, 使用头发),
                ("face_eyes", 眼睛视线, 使用眼睛视线),
                ("face_face", 脸部五官, 使用脸部五官),
                ("face_expression", 情绪表情, 使用情绪表情),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "face",
            [
                values.get("face_hair", ""),
                values.get("face_eyes", ""),
                values.get("face_face", ""),
                values.get("face_expression", ""),
                _enabled_value(脸发眼补充, 使用脸发眼补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("face_hair", "头发", 使用头发),
            ("face_eyes", "眼睛视线", 使用眼睛视线),
            ("face_face", "脸部五官", 使用脸部五官),
            ("face_expression", "情绪表情", 使用情绪表情),
            ("face_note", "脸发眼补充", 使用脸发眼补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "face_hair": "头发",
                "face_eyes": "眼睛视线",
                "face_face": "脸部五官",
                "face_expression": "情绪表情",
            },
        )


class GaliaisNodesCharacterBody(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "体型比例": combo("body_shape"),
                "四肢躯干": combo("body_limbs"),
                "皮肤质感": combo("body_skin"),
                "非人身体": combo("body_nonhuman"),
                "身体补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("体型比例", "四肢躯干", "皮肤质感", "非人身体", "身体补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("身体段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 体型比例, 四肢躯干, 皮肤质感, 非人身体, 身体补充, 启用, 权重, 使用体型比例, 使用四肢躯干, 使用皮肤质感, 使用非人身体, 使用身体补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("body_shape", 体型比例, 使用体型比例),
                ("body_limbs", 四肢躯干, 使用四肢躯干),
                ("body_skin", 皮肤质感, 使用皮肤质感),
                ("body_nonhuman", 非人身体, 使用非人身体),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "body",
            [
                values.get("body_shape", ""),
                values.get("body_limbs", ""),
                values.get("body_skin", ""),
                values.get("body_nonhuman", ""),
                _enabled_value(身体补充, 使用身体补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("body_shape", "体型比例", 使用体型比例),
            ("body_limbs", "四肢躯干", 使用四肢躯干),
            ("body_skin", "皮肤质感", 使用皮肤质感),
            ("body_nonhuman", "非人身体", 使用非人身体),
            ("body_note", "身体补充", 使用身体补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "body_shape": "体型比例",
                "body_limbs": "四肢躯干",
                "body_skin": "皮肤质感",
                "body_nonhuman": "非人身体",
            },
        )


class GaliaisNodesCharacterOutfit(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "上装外套": combo("outfit_upper"),
                "下装鞋袜": combo("outfit_lower"),
                "连体贴身": combo("outfit_onepiece"),
                "配饰": combo("outfit_accessory"),
                "材质细节": combo("outfit_material_detail"),
                "穿着状态": combo("outfit_state"),
                "服装补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("上装外套", "下装鞋袜", "连体贴身", "配饰", "材质细节", "穿着状态", "服装补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("服装段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 上装外套, 下装鞋袜, 连体贴身, 配饰, 材质细节, 穿着状态, 服装补充, 启用, 权重, 使用上装外套, 使用下装鞋袜, 使用连体贴身, 使用配饰, 使用材质细节, 使用穿着状态, 使用服装补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("outfit_upper", 上装外套, 使用上装外套),
                ("outfit_lower", 下装鞋袜, 使用下装鞋袜),
                ("outfit_onepiece", 连体贴身, 使用连体贴身),
                ("outfit_accessory", 配饰, 使用配饰),
                ("outfit_material_detail", 材质细节, 使用材质细节),
                ("outfit_state", 穿着状态, 使用穿着状态),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "outfit",
            [
                values.get("outfit_upper", ""),
                values.get("outfit_lower", ""),
                values.get("outfit_onepiece", ""),
                values.get("outfit_accessory", ""),
                values.get("outfit_material_detail", ""),
                values.get("outfit_state", ""),
                _enabled_value(服装补充, 使用服装补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("outfit_upper", "上装外套", 使用上装外套),
            ("outfit_lower", "下装鞋袜", 使用下装鞋袜),
            ("outfit_onepiece", "连体贴身", 使用连体贴身),
            ("outfit_accessory", "配饰", 使用配饰),
            ("outfit_material_detail", "材质细节", 使用材质细节),
            ("outfit_state", "穿着状态", 使用穿着状态),
            ("outfit_note", "服装补充", 使用服装补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "outfit_upper": "上装外套",
                "outfit_lower": "下装鞋袜",
                "outfit_onepiece": "连体贴身",
                "outfit_accessory": "配饰",
                "outfit_material_detail": "材质细节",
                "outfit_state": "穿着状态",
            },
        )


class GaliaisNodesCharacterPoseAction(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "整体姿态": combo("pose_posture"),
                "肢体手势": combo("pose_gesture"),
                "动作行为": combo("pose_action"),
                "互动关系": combo("pose_interaction"),
                "姿势补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("整体姿态", "肢体手势", "动作行为", "互动关系", "姿势补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("姿势段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 整体姿态, 肢体手势, 动作行为, 互动关系, 姿势补充, 启用, 权重, 使用整体姿态, 使用肢体手势, 使用动作行为, 使用互动关系, 使用姿势补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("pose_posture", 整体姿态, 使用整体姿态),
                ("pose_gesture", 肢体手势, 使用肢体手势),
                ("pose_action", 动作行为, 使用动作行为),
                ("pose_interaction", 互动关系, 使用互动关系),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "pose",
            [
                values.get("pose_posture", ""),
                values.get("pose_gesture", ""),
                values.get("pose_action", ""),
                values.get("pose_interaction", ""),
                _enabled_value(姿势补充, 使用姿势补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("pose_posture", "整体姿态", 使用整体姿态),
            ("pose_gesture", "肢体手势", 使用肢体手势),
            ("pose_action", "动作行为", 使用动作行为),
            ("pose_interaction", "互动关系", 使用互动关系),
            ("pose_note", "姿势补充", 使用姿势补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "pose_posture": "整体姿态",
                "pose_gesture": "肢体手势",
                "pose_action": "动作行为",
                "pose_interaction": "互动关系",
            },
        )


class GaliaisNodesCharacterSceneStyle(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "镜头构图": combo("scene_camera"),
                "地点背景": combo("scene_location"),
                "时间天气": combo("scene_time_weather"),
                "道具生物": combo("scene_object"),
                "画面风格": combo("scene_visual_style"),
                "场景补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("镜头构图", "地点背景", "时间天气", "道具生物", "画面风格", "场景补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("场景段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 镜头构图, 地点背景, 时间天气, 道具生物, 画面风格, 场景补充, 启用, 权重, 使用镜头构图, 使用地点背景, 使用时间天气, 使用道具生物, 使用画面风格, 使用场景补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("scene_camera", 镜头构图, 使用镜头构图),
                ("scene_location", 地点背景, 使用地点背景),
                ("scene_time_weather", 时间天气, 使用时间天气),
                ("scene_object", 道具生物, 使用道具生物),
                ("scene_visual_style", 画面风格, 使用画面风格),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "scene",
            [
                values.get("scene_camera", ""),
                values.get("scene_location", ""),
                values.get("scene_time_weather", ""),
                values.get("scene_object", ""),
                values.get("scene_visual_style", ""),
                _enabled_value(场景补充, 使用场景补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("scene_camera", "镜头构图", 使用镜头构图),
            ("scene_location", "地点背景", 使用地点背景),
            ("scene_time_weather", "时间天气", 使用时间天气),
            ("scene_object", "道具生物", 使用道具生物),
            ("scene_visual_style", "画面风格", 使用画面风格),
            ("scene_note", "场景补充", 使用场景补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "scene_camera": "镜头构图",
                "scene_location": "地点背景",
                "scene_time_weather": "时间天气",
                "scene_object": "道具生物",
                "scene_visual_style": "画面风格",
            },
        )


class GaliaisNodesCharacterNSFW(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "裸露": combo("nsfw_exposure"),
                "露骨身体": combo("nsfw_body"),
                "性行为": combo("nsfw_act"),
                "成人主题": combo("nsfw_context"),
                "性癖道具": combo("nsfw_fetish_object"),
                "NSFW补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": False}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("裸露", "露骨身体", "性行为", "成人主题", "性癖道具", "NSFW补充"),
                **random_controls(default_allow_nsfw=True),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("NSFW段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 裸露, 露骨身体, 性行为, 成人主题, 性癖道具, NSFW补充, 启用, 权重, 使用裸露, 使用露骨身体, 使用性行为, 使用成人主题, 使用性癖道具, 使用NSFW补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("nsfw_exposure", 裸露, 使用裸露),
                ("nsfw_body", 露骨身体, 使用露骨身体),
                ("nsfw_act", 性行为, 使用性行为),
                ("nsfw_context", 成人主题, 使用成人主题),
                ("nsfw_fetish_object", 性癖道具, 使用性癖道具),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "nsfw",
            [
                values.get("nsfw_exposure", ""),
                values.get("nsfw_body", ""),
                values.get("nsfw_act", ""),
                values.get("nsfw_context", ""),
                values.get("nsfw_fetish_object", ""),
                _enabled_value(NSFW补充, 使用NSFW补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("nsfw_exposure", "裸露", 使用裸露),
            ("nsfw_body", "露骨身体", 使用露骨身体),
            ("nsfw_act", "性行为", 使用性行为),
            ("nsfw_context", "成人主题", 使用成人主题),
            ("nsfw_fetish_object", "性癖道具", 使用性癖道具),
            ("nsfw_note", "NSFW补充", 使用NSFW补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "nsfw_exposure": "裸露",
                "nsfw_body": "露骨身体",
                "nsfw_act": "性行为",
                "nsfw_context": "成人主题",
                "nsfw_fetish_object": "性癖道具",
            },
        )


class GaliaisNodesCharacterNarrative(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "关系事件": combo("narrative_relationship"),
                "主题状态": combo("narrative_theme_state"),
                "引用梗": combo("meta_reference"),
                "叙事补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("关系事件", "主题状态", "引用梗", "叙事补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("叙事段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 关系事件, 主题状态, 引用梗, 叙事补充, 启用, 权重, 使用关系事件, 使用主题状态, 使用引用梗, 使用叙事补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("narrative_relationship", 关系事件, 使用关系事件),
                ("narrative_theme_state", 主题状态, 使用主题状态),
                ("meta_reference", 引用梗, 使用引用梗),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "narrative",
            [
                values.get("narrative_relationship", ""),
                values.get("narrative_theme_state", ""),
                values.get("meta_reference", ""),
                _enabled_value(叙事补充, 使用叙事补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("narrative_relationship", "关系事件", 使用关系事件),
            ("narrative_theme_state", "主题状态", 使用主题状态),
            ("meta_reference", "引用梗", 使用引用梗),
            ("narrative_note", "叙事补充", 使用叙事补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "narrative_relationship": "关系事件",
                "narrative_theme_state": "主题状态",
                "meta_reference": "引用梗",
            },
        )


class GaliaisNodesCharacterObjectSupplement(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "场景物件": combo("scene_object"),
                "媒介文档": combo("object_media_document"),
                "道具补充": combo("object_prop_extra"),
                "物件补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("场景物件", "媒介文档", "道具补充", "物件补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("物件段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 场景物件, 媒介文档, 道具补充, 物件补充, 启用, 权重, 使用场景物件, 使用媒介文档, 使用道具补充, 使用物件补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("scene_object", 场景物件, 使用场景物件),
                ("object_media_document", 媒介文档, 使用媒介文档),
                ("object_prop_extra", 道具补充, 使用道具补充),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "object",
            [
                values.get("scene_object", ""),
                values.get("object_media_document", ""),
                values.get("object_prop_extra", ""),
                _enabled_value(物件补充, 使用物件补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("scene_object", "场景物件", 使用场景物件),
            ("object_media_document", "媒介文档", 使用媒介文档),
            ("object_prop_extra", "道具补充", 使用道具补充),
            ("object_note", "物件补充", 使用物件补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "scene_object": "场景物件",
                "object_media_document": "媒介文档",
                "object_prop_extra": "道具补充",
            },
        )


class GaliaisNodesCharacterMetaTechnical(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "管理质量": combo("meta_admin_quality"),
                "技术规格": combo("meta_technical"),
                "覆盖处理": combo("meta_overlay_process"),
                "待复审": combo("uncertain_review"),
                "Meta补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("管理质量", "技术规格", "覆盖处理", "待复审", "Meta补充"),
                **random_controls(),
            },
            "optional": optional_db(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("Meta段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 管理质量, 技术规格, 覆盖处理, 待复审, Meta补充, 启用, 权重, 使用管理质量, 使用技术规格, 使用覆盖处理, 使用待复审, 使用Meta补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None):
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_random_fields(
            _random_field_values(
                ("meta_admin_quality", 管理质量, 使用管理质量),
                ("meta_technical", 技术规格, 使用技术规格),
                ("meta_overlay_process", 覆盖处理, 使用覆盖处理),
                ("uncertain_review", 待复审, 使用待复审),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            strategy=随机策略,
            per_field_count=每字段随机数,
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
        )
        section = character_section_text(
            "meta",
            [
                values.get("meta_admin_quality", ""),
                values.get("meta_technical", ""),
                values.get("meta_overlay_process", ""),
                values.get("uncertain_review", ""),
                _enabled_value(Meta补充, 使用Meta补充),
            ],
            enabled=启用,
            weight=权重,
            db_path=db_path,
        )
        section["fields"] = _field_switch_metadata(
            ("meta_admin_quality", "管理质量", 使用管理质量),
            ("meta_technical", "技术规格", 使用技术规格),
            ("meta_overlay_process", "覆盖处理", 使用覆盖处理),
            ("uncertain_review", "待复审", 使用待复审),
            ("meta_note", "Meta补充", 使用Meta补充),
        )
        section["random"] = random_meta
        return _section_result(
            section,
            random_meta,
            {
                "meta_admin_quality": "管理质量",
                "meta_technical": "技术规格",
                "meta_overlay_process": "覆盖处理",
                "uncertain_review": "待复审",
            },
        )


class GaliaisNodesCharacterComposer:
    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            f"角色段{i}": ("GALIAIS_NODES_CHARACTER_SECTION",)
            for i in range(1, 17)
        }
        return {
            "required": {
                "质量预设": (list(GALIAIS_NODES_QUALITY_PRESETS.keys()), {"default": "无"}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "无"}),
                "去重": ("BOOLEAN", {"default": True}),
                "额外前缀": ("STRING", {"default": "", "multiline": True}),
                "额外后缀": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": optional | {
                "额外负面": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "角色JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(
        self,
        质量预设,
        负面预设,
        去重,
        额外前缀,
        额外后缀,
        角色段1=None,
        角色段2=None,
        角色段3=None,
        角色段4=None,
        角色段5=None,
        角色段6=None,
        角色段7=None,
        角色段8=None,
        角色段9=None,
        角色段10=None,
        角色段11=None,
        角色段12=None,
        角色段13=None,
        角色段14=None,
        角色段15=None,
        角色段16=None,
        额外负面="",
    ):
        sections = [
            角色段1,
            角色段2,
            角色段3,
            角色段4,
            角色段5,
            角色段6,
            角色段7,
            角色段8,
            角色段9,
            角色段10,
            角色段11,
            角色段12,
            角色段13,
            角色段14,
            角色段15,
            角色段16,
        ]
        negative = join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS[负面预设], 额外负面], dedupe=去重)
        return compose_character_prompt(
            sections,
            quality=GALIAIS_NODES_QUALITY_PRESETS[质量预设],
            negative=negative,
            prefix=额外前缀,
            suffix=额外后缀,
            dedupe=去重,
        )


NODE_CLASS_MAPPINGS = {
    "GaliaisNodesCharacterIdentity": GaliaisNodesCharacterIdentity,
    "GaliaisNodesCharacterFaceHairEyes": GaliaisNodesCharacterFaceHairEyes,
    "GaliaisNodesCharacterBody": GaliaisNodesCharacterBody,
    "GaliaisNodesCharacterOutfit": GaliaisNodesCharacterOutfit,
    "GaliaisNodesCharacterPoseAction": GaliaisNodesCharacterPoseAction,
    "GaliaisNodesCharacterSceneStyle": GaliaisNodesCharacterSceneStyle,
    "GaliaisNodesCharacterNSFW": GaliaisNodesCharacterNSFW,
    "GaliaisNodesCharacterNarrative": GaliaisNodesCharacterNarrative,
    "GaliaisNodesCharacterObjectSupplement": GaliaisNodesCharacterObjectSupplement,
    "GaliaisNodesCharacterMetaTechnical": GaliaisNodesCharacterMetaTechnical,
    "GaliaisNodesCharacterComposer": GaliaisNodesCharacterComposer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GaliaisNodesCharacterIdentity": "GALIAIS-Nodes 01 角色身份",
    "GaliaisNodesCharacterFaceHairEyes": "GALIAIS-Nodes 02 脸发眼",
    "GaliaisNodesCharacterBody": "GALIAIS-Nodes 03 身体体态",
    "GaliaisNodesCharacterOutfit": "GALIAIS-Nodes 04 服装配饰",
    "GaliaisNodesCharacterPoseAction": "GALIAIS-Nodes 05 姿势动作",
    "GaliaisNodesCharacterSceneStyle": "GALIAIS-Nodes 06 场景画面",
    "GaliaisNodesCharacterNarrative": "GALIAIS-Nodes 07 叙事主题",
    "GaliaisNodesCharacterObjectSupplement": "GALIAIS-Nodes 08 物件补充",
    "GaliaisNodesCharacterMetaTechnical": "GALIAIS-Nodes 09 Meta技术",
    "GaliaisNodesCharacterNSFW": "GALIAIS-Nodes 10 NSFW 精细",
    "GaliaisNodesCharacterComposer": "GALIAIS-Nodes Final Composer",
}
