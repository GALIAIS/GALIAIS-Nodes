import json

try:
    from .nodes_galiais_prompt_system import (
        AI_TAG_GENERATION_MODES,
        GALIAIS_NODES_NEGATIVE_PRESETS,
        GALIAIS_NODES_QUALITY_PRESETS,
        optional_danbooru_db_path,
        register_danbooru_field_set,
    )
    from . import galiais_character_core as _galiais_character_core
except ImportError:  # direct test import
    from nodes_galiais_prompt_system import (
        AI_TAG_GENERATION_MODES,
        GALIAIS_NODES_NEGATIVE_PRESETS,
        GALIAIS_NODES_QUALITY_PRESETS,
        optional_danbooru_db_path,
        register_danbooru_field_set,
    )
    import galiais_character_core as _galiais_character_core

globals().update(
    {
        name: getattr(_galiais_character_core, name)
        for name in dir(_galiais_character_core)
        if not (name.startswith("__") and name.endswith("__"))
    }
)

def _sync_character_core_mutable_paths() -> None:
    _galiais_character_core.COMPOSER_TEMPLATE_STORE_PATH = COMPOSER_TEMPLATE_STORE_PATH

def _read_composer_template_store() -> dict:
    _sync_character_core_mutable_paths()
    return _galiais_character_core._read_composer_template_store()

def _write_composer_template_store(store: dict) -> dict:
    _sync_character_core_mutable_paths()
    return _galiais_character_core._write_composer_template_store(store)

def _composer_template_names() -> list[str]:
    _sync_character_core_mutable_paths()
    return _galiais_character_core._composer_template_names()

def _load_composer_template(name: str, inline_template: str = "") -> tuple[str, str]:
    _sync_character_core_mutable_paths()
    return _galiais_character_core._load_composer_template(name, inline_template)

def compose_character_prompt(*args, **kwargs):
    _sync_character_core_mutable_paths()
    return _galiais_character_core.compose_character_prompt(*args, **kwargs)

register_danbooru_field_set("character", TAXONOMY_FIELDS, CATEGORY_FIELDS)

class GaliaisNodesCharacterIdentity(_RuntimeRandomRefreshMixin):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **character_scope_controls(),
                "主体人数": combo("identity_subject"),
                "角色": combo("identity_character"),
                "作品": combo("identity_work"),
                "画师": combo("identity_artist"),
                "年龄身份": combo("identity_role"),
                "身份补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("主体人数", "角色", "作品", "画师", "年龄身份", "身份补充"),
                **random_controls("主体人数", "角色", "作品", "画师", "年龄身份"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("角色段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 主体人数, 角色, 作品, 画师, 年龄身份, 身份补充, 启用, 权重, 使用主体人数, 使用角色, 使用作品, 使用画师, 使用年龄身份, 使用身份补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("identity_subject", 主体人数, 使用主体人数),
                ("identity_character", 角色, 使用角色),
                ("identity_work", 作品, 使用作品),
                ("identity_artist", 画师, 使用画师),
                ("identity_role", 年龄身份, 使用年龄身份),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "identity_subject": "主体人数",
                "identity_character": "角色",
                "identity_work": "作品",
                "identity_artist": "画师",
                "identity_role": "年龄身份",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "identity_subject": "主体人数",
                    "identity_character": "角色",
                    "identity_work": "作品",
                    "identity_artist": "画师",
                    "identity_role": "年龄身份",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
                "头发": combo("face_hair"),
                "眼睛视线": combo("face_eyes"),
                "脸部五官": combo("face_face"),
                "情绪表情": combo("face_expression"),
                "脸发眼补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("头发", "眼睛视线", "脸部五官", "情绪表情", "脸发眼补充"),
                **random_controls("头发", "眼睛视线", "脸部五官", "情绪表情"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("脸发眼段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 头发, 眼睛视线, 脸部五官, 情绪表情, 脸发眼补充, 启用, 权重, 使用头发, 使用眼睛视线, 使用脸部五官, 使用情绪表情, 使用脸发眼补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("face_hair", 头发, 使用头发),
                ("face_eyes", 眼睛视线, 使用眼睛视线),
                ("face_face", 脸部五官, 使用脸部五官),
                ("face_expression", 情绪表情, 使用情绪表情),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "face_hair": "头发",
                "face_eyes": "眼睛视线",
                "face_face": "脸部五官",
                "face_expression": "情绪表情",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "face_hair": "头发",
                    "face_eyes": "眼睛视线",
                    "face_face": "脸部五官",
                    "face_expression": "情绪表情",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
                "体型比例": combo("body_shape"),
                "四肢躯干": combo("body_limbs"),
                "皮肤质感": combo("body_skin"),
                "非人身体": combo("body_nonhuman"),
                "身体补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("体型比例", "四肢躯干", "皮肤质感", "非人身体", "身体补充"),
                **random_controls("体型比例", "四肢躯干", "皮肤质感", "非人身体"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("身体段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 体型比例, 四肢躯干, 皮肤质感, 非人身体, 身体补充, 启用, 权重, 使用体型比例, 使用四肢躯干, 使用皮肤质感, 使用非人身体, 使用身体补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("body_shape", 体型比例, 使用体型比例),
                ("body_limbs", 四肢躯干, 使用四肢躯干),
                ("body_skin", 皮肤质感, 使用皮肤质感),
                ("body_nonhuman", 非人身体, 使用非人身体),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "body_shape": "体型比例",
                "body_limbs": "四肢躯干",
                "body_skin": "皮肤质感",
                "body_nonhuman": "非人身体",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "body_shape": "体型比例",
                    "body_limbs": "四肢躯干",
                    "body_skin": "皮肤质感",
                    "body_nonhuman": "非人身体",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
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
                **random_controls("上装外套", "下装鞋袜", "连体贴身", "配饰", "材质细节", "穿着状态"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("服装段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 上装外套, 下装鞋袜, 连体贴身, 配饰, 材质细节, 穿着状态, 服装补充, 启用, 权重, 使用上装外套, 使用下装鞋袜, 使用连体贴身, 使用配饰, 使用材质细节, 使用穿着状态, 使用服装补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
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
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "outfit_upper": "上装外套",
                "outfit_lower": "下装鞋袜",
                "outfit_onepiece": "连体贴身",
                "outfit_accessory": "配饰",
                "outfit_material_detail": "材质细节",
                "outfit_state": "穿着状态",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "outfit_upper": "上装外套",
                    "outfit_lower": "下装鞋袜",
                    "outfit_onepiece": "连体贴身",
                    "outfit_accessory": "配饰",
                    "outfit_material_detail": "材质细节",
                    "outfit_state": "穿着状态",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
                "整体姿态": combo("pose_posture"),
                "肢体手势": combo("pose_gesture"),
                "动作行为": combo("pose_action"),
                "互动关系": combo("pose_interaction"),
                "姿势补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("整体姿态", "肢体手势", "动作行为", "互动关系", "姿势补充"),
                **random_controls("整体姿态", "肢体手势", "动作行为", "互动关系"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("姿势段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 整体姿态, 肢体手势, 动作行为, 互动关系, 姿势补充, 启用, 权重, 使用整体姿态, 使用肢体手势, 使用动作行为, 使用互动关系, 使用姿势补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("pose_posture", 整体姿态, 使用整体姿态),
                ("pose_gesture", 肢体手势, 使用肢体手势),
                ("pose_action", 动作行为, 使用动作行为),
                ("pose_interaction", 互动关系, 使用互动关系),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "pose_posture": "整体姿态",
                "pose_gesture": "肢体手势",
                "pose_action": "动作行为",
                "pose_interaction": "互动关系",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "pose_posture": "整体姿态",
                    "pose_gesture": "肢体手势",
                    "pose_action": "动作行为",
                    "pose_interaction": "互动关系",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
                "镜头构图": combo("scene_camera"),
                "地点背景": combo("scene_location"),
                "时间天气": combo("scene_time_weather"),
                "道具生物": combo("scene_object"),
                "画面风格": combo("scene_visual_style"),
                "场景补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("镜头构图", "地点背景", "时间天气", "道具生物", "画面风格", "场景补充"),
                **random_controls("镜头构图", "地点背景", "时间天气", "道具生物", "画面风格"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("场景段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 镜头构图, 地点背景, 时间天气, 道具生物, 画面风格, 场景补充, 启用, 权重, 使用镜头构图, 使用地点背景, 使用时间天气, 使用道具生物, 使用画面风格, 使用场景补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("scene_camera", 镜头构图, 使用镜头构图),
                ("scene_location", 地点背景, 使用地点背景),
                ("scene_time_weather", 时间天气, 使用时间天气),
                ("scene_object", 道具生物, 使用道具生物),
                ("scene_visual_style", 画面风格, 使用画面风格),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "scene_camera": "镜头构图",
                "scene_location": "地点背景",
                "scene_time_weather": "时间天气",
                "scene_object": "道具生物",
                "scene_visual_style": "画面风格",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "scene_camera": "镜头构图",
                    "scene_location": "地点背景",
                    "scene_time_weather": "时间天气",
                    "scene_object": "道具生物",
                    "scene_visual_style": "画面风格",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
                "裸露": combo("nsfw_exposure"),
                "露骨身体": combo("nsfw_body"),
                "性行为": combo("nsfw_act"),
                "成人主题": combo("nsfw_context"),
                "性癖道具": combo("nsfw_fetish_object"),
                "NSFW补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": False}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("裸露", "露骨身体", "性行为", "成人主题", "性癖道具", "NSFW补充"),
                **random_controls("裸露", "露骨身体", "性行为", "成人主题", "性癖道具", default_allow_nsfw=True),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("NSFW段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 裸露, 露骨身体, 性行为, 成人主题, 性癖道具, NSFW补充, 启用, 权重, 使用裸露, 使用露骨身体, 使用性行为, 使用成人主题, 使用性癖道具, 使用NSFW补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("nsfw_exposure", 裸露, 使用裸露),
                ("nsfw_body", 露骨身体, 使用露骨身体),
                ("nsfw_act", 性行为, 使用性行为),
                ("nsfw_context", 成人主题, 使用成人主题),
                ("nsfw_fetish_object", 性癖道具, 使用性癖道具),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "nsfw_exposure": "裸露",
                "nsfw_body": "露骨身体",
                "nsfw_act": "性行为",
                "nsfw_context": "成人主题",
                "nsfw_fetish_object": "性癖道具",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "nsfw_exposure": "裸露",
                    "nsfw_body": "露骨身体",
                    "nsfw_act": "性行为",
                    "nsfw_context": "成人主题",
                    "nsfw_fetish_object": "性癖道具",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
                "关系事件": combo("narrative_relationship"),
                "主题状态": combo("narrative_theme_state"),
                "引用梗": combo("meta_reference"),
                "叙事补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("关系事件", "主题状态", "引用梗", "叙事补充"),
                **random_controls("关系事件", "主题状态", "引用梗"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("叙事段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 关系事件, 主题状态, 引用梗, 叙事补充, 启用, 权重, 使用关系事件, 使用主题状态, 使用引用梗, 使用叙事补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("narrative_relationship", 关系事件, 使用关系事件),
                ("narrative_theme_state", 主题状态, 使用主题状态),
                ("meta_reference", 引用梗, 使用引用梗),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "narrative_relationship": "关系事件",
                "narrative_theme_state": "主题状态",
                "meta_reference": "引用梗",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "narrative_relationship": "关系事件",
                    "narrative_theme_state": "主题状态",
                    "meta_reference": "引用梗",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
                "场景物件": combo("scene_object"),
                "媒介文档": combo("object_media_document"),
                "道具补充": combo("object_prop_extra"),
                "物件补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("场景物件", "媒介文档", "道具补充", "物件补充"),
                **random_controls("场景物件", "媒介文档", "道具补充"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("物件段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 场景物件, 媒介文档, 道具补充, 物件补充, 启用, 权重, 使用场景物件, 使用媒介文档, 使用道具补充, 使用物件补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("scene_object", 场景物件, 使用场景物件),
                ("object_media_document", 媒介文档, 使用媒介文档),
                ("object_prop_extra", 道具补充, 使用道具补充),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "scene_object": "场景物件",
                "object_media_document": "媒介文档",
                "object_prop_extra": "道具补充",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "scene_object": "场景物件",
                    "object_media_document": "媒介文档",
                    "object_prop_extra": "道具补充",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
                **character_scope_controls(),
                "管理质量": combo("meta_admin_quality"),
                "技术规格": combo("meta_technical"),
                "覆盖处理": combo("meta_overlay_process"),
                "待复审": combo("uncertain_review"),
                "Meta补充": text("", multiline=True),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                **field_enabled_controls("管理质量", "技术规格", "覆盖处理", "待复审", "Meta补充"),
                **random_controls("管理质量", "技术规格", "覆盖处理", "待复审"),
            },
            "optional": optional_generation_inputs(),
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("Meta段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 管理质量, 技术规格, 覆盖处理, 待复审, Meta补充, 启用, 权重, 使用管理质量, 使用技术规格, 使用覆盖处理, 使用待复审, 使用Meta补充, 启用随机Tag, 随机策略, 每字段随机数, 随机种子, 随机允许NSFW, 随机最低热度, DB=None, 角色槽位="全局", 角色标签="", **kwargs):
        DB, 角色槽位, 角色标签 = _resolve_legacy_scope_args(DB, 角色槽位, 角色标签)
        db_path = optional_danbooru_db_path(db=DB)
        values, random_meta = _apply_generated_fields(
            _random_field_values(
                ("meta_admin_quality", 管理质量, 使用管理质量),
                ("meta_technical", 技术规格, 使用技术规格),
                ("meta_overlay_process", 覆盖处理, 使用覆盖处理),
                ("uncertain_review", 待复审, 使用待复审),
            ),
            db_path=db_path,
            enabled=启用随机Tag,
            mode=kwargs.get("Tag生成模式", "规则随机"),
            provider=kwargs.get("AI服务商"),
            previous_context=kwargs.get("上游上下文", ""),
            upstream_section=kwargs.get("上游提示词段"),
            role_slot=角色槽位,
            role_label=角色标签,
            ai_freedom=kwargs.get("AI自由度", 0.35),
            intent_text=kwargs.get("AI意图方向", ""),
            intent_detail=kwargs.get("AI扩写强度", "标准"),
            intent_write_mode=kwargs.get("AI是否写入补充", "只放元信息"),
            rag_mode=kwargs.get("AI RAG模式", "关闭"),
            rag_candidate_count=kwargs.get("RAG候选数", 12),
            rag_example_count=kwargs.get("RAG示例数", 3),
            field_labels={
                "meta_admin_quality": "管理质量",
                "meta_technical": "技术规格",
                "meta_overlay_process": "覆盖处理",
                "uncertain_review": "待复审",
            },
            strategy=随机策略,
            per_field_count=每字段随机数,
            **_random_field_control_overrides(
                {
                    "meta_admin_quality": "管理质量",
                    "meta_technical": "技术规格",
                    "meta_overlay_process": "覆盖处理",
                    "uncertain_review": "待复审",
                },
                kwargs,
            ),
            seed=随机种子,
            allow_nsfw=随机允许NSFW,
            min_post_count=随机最低热度,
            blacklist=DB,
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
        _apply_character_scope(section, 角色槽位, 角色标签)
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
            f"提示词段{i}": ("GALIAIS_NODES_CHARACTER_SECTION",)
            for i in range(1, 17)
        }
        return {
            "required": {
                "质量预设": (list(GALIAIS_NODES_QUALITY_PRESETS.keys()), {"default": "无"}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "无"}),
                "去重": ("BOOLEAN", {"default": True}),
                "多角色模式": (["自动", "开启", "关闭"], {"default": "自动"}),
                "角色分隔": (CHARACTER_SEPARATOR_OPTIONS, {"default": "分号"}),
                "额外前缀": ("STRING", {"default": "", "multiline": True}),
                "额外后缀": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": optional | {
                "额外负面": ("STRING", {"default": "", "multiline": True}),
                "模板名称": ("STRING", {"default": "", "multiline": False, "advanced": True}),
                "自定义正面模板": ("STRING", {"default": "", "multiline": True, "advanced": True}),
                "模板JSON": ("STRING", {"default": "", "multiline": True, "advanced": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "提示词JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(
        self,
        质量预设,
        负面预设,
        去重,
        多角色模式,
        角色分隔,
        额外前缀,
        额外后缀,
        模板名称="",
        自定义正面模板="",
        提示词段1=None,
        提示词段2=None,
        提示词段3=None,
        提示词段4=None,
        提示词段5=None,
        提示词段6=None,
        提示词段7=None,
        提示词段8=None,
        提示词段9=None,
        提示词段10=None,
        提示词段11=None,
        提示词段12=None,
        提示词段13=None,
        提示词段14=None,
        提示词段15=None,
        提示词段16=None,
        额外负面="",
        模板JSON="",
        **kwargs,
    ):
        template_from_json = ""
        if 模板JSON:
            try:
                template_payload = json.loads(模板JSON)
                if isinstance(template_payload, dict):
                    template_from_json = str(template_payload.get("template") or "").strip()
            except Exception:
                template_from_json = ""
        inline_template = str(自定义正面模板 or "").strip() or template_from_json
        sections = [
            提示词段1,
            提示词段2,
            提示词段3,
            提示词段4,
            提示词段5,
            提示词段6,
            提示词段7,
            提示词段8,
            提示词段9,
            提示词段10,
            提示词段11,
            提示词段12,
            提示词段13,
            提示词段14,
            提示词段15,
            提示词段16,
        ]
        negative = join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS[负面预设], 额外负面], dedupe=去重)
        return compose_character_prompt(
            sections,
            quality=GALIAIS_NODES_QUALITY_PRESETS[质量预设],
            negative=negative,
            prefix=额外前缀,
            suffix=额外后缀,
            dedupe=去重,
            multi_character_mode=多角色模式,
            character_separator=角色分隔,
            template=inline_template,
            template_name=模板名称,
        )


class GaliaisNodesMultiCharacterCoordinator:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "启用": ("BOOLEAN", {"default": True}),
                "输出语言": (["中文", "英文", "中英混合"], {"default": "英文"}),
                "空间布局": (["左到右", "前后景", "中心环绕", "对称"], {"default": "左到右"}),
                "角色关系": (["并列", "交互", "对视", "追逐", "保护", "对立", "自定义"], {"default": "交互"}),
                "关系补充": ("STRING", {"default": "", "multiline": True}),
                "去重": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                **{f"提示词段{i}": ("GALIAIS_NODES_CHARACTER_SECTION",) for i in range(1, 17)},
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_CHARACTER_SECTION", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("多角色叙事段", "叙事文本", "布局JSON", "上游上下文")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(
        self,
        启用,
        输出语言,
        空间布局,
        角色关系,
        关系补充,
        去重,
        提示词段1=None,
        提示词段2=None,
        提示词段3=None,
        提示词段4=None,
        提示词段5=None,
        提示词段6=None,
        提示词段7=None,
        提示词段8=None,
        提示词段9=None,
        提示词段10=None,
        提示词段11=None,
        提示词段12=None,
        提示词段13=None,
        提示词段14=None,
        提示词段15=None,
        提示词段16=None,
    ):
        sections = [
            提示词段1,
            提示词段2,
            提示词段3,
            提示词段4,
            提示词段5,
            提示词段6,
            提示词段7,
            提示词段8,
            提示词段9,
            提示词段10,
            提示词段11,
            提示词段12,
            提示词段13,
            提示词段14,
            提示词段15,
            提示词段16,
        ]
        layout = build_multi_character_layout(
            sections,
            language=输出语言,
            layout=空间布局,
            relation=角色关系,
            extra_note=关系补充,
            dedupe=去重,
        )
        text_value = layout.get("narrative_text", "") if 启用 else ""
        section = character_section_text(
            "narrative",
            [text_value],
            enabled=bool(启用),
            dedupe=bool(去重),
        )
        section["multi_character_layout"] = layout
        _apply_character_scope(section, "全局", "")
        context = _metadata_json(
            {
                "multi_character_layout": layout,
                "narrative_text": text_value,
                "enabled": bool(启用),
            }
        )
        return (section, text_value, _metadata_json(layout), context)


class GaliaisNodesCharacterComposerTemplateManager:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "操作": (["列出", "保存/更新", "删除", "导入JSON", "导出全部"], {"default": "列出"}),
                "模板名称": ("STRING", {"default": "", "multiline": False}),
                "正面模板": ("STRING", {"default": COMPOSER_DEFAULT_TEMPLATE, "multiline": True}),
                "描述": ("STRING", {"default": "", "multiline": True}),
                "导入JSON": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("模板JSON", "模板名称JSON", "状态JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 操作, 模板名称, 正面模板, 描述, 导入JSON):
        action = str(操作 or "列出")
        store = _read_composer_template_store()
        templates = dict(store.get("templates", {}))
        status = {"action": action, "changed": False, "error": ""}
        name = _normalize_template_name(模板名称)

        if action == "保存/更新":
            template_text = str(正面模板 or "").strip()
            if not name:
                status["error"] = "模板名称不能为空。"
            elif not template_text:
                status["error"] = "正面模板不能为空。"
            else:
                templates[name] = {
                    "template": template_text,
                    "description": str(描述 or "").strip(),
                }
                store = _write_composer_template_store({"templates": templates})
                status["changed"] = True
                status["template_name"] = name
        elif action == "删除":
            if not name:
                status["error"] = "模板名称不能为空。"
            else:
                status["deleted"] = name in templates
                templates.pop(name, None)
                store = _write_composer_template_store({"templates": templates})
                status["changed"] = True
                status["template_name"] = name
        elif action == "导入JSON":
            try:
                payload = json.loads(str(导入JSON or "{}"))
            except Exception as exc:
                payload = {}
                status["error"] = f"导入JSON解析失败: {exc}"
            if not status["error"]:
                imported = payload.get("templates") if isinstance(payload, dict) and isinstance(payload.get("templates"), dict) else {}
                if not imported and isinstance(payload, dict) and payload.get("template") and name:
                    imported = {name: {"template": payload.get("template"), "description": payload.get("description", "")}}
                for item_name, item in imported.items():
                    safe_name = _normalize_template_name(item_name)
                    if not safe_name or not isinstance(item, dict):
                        continue
                    template_text = str(item.get("template") or "").strip()
                    if not template_text:
                        continue
                    templates[safe_name] = {
                        "template": template_text,
                        "description": str(item.get("description") or "").strip(),
                    }
                store = _write_composer_template_store({"templates": templates})
                status["changed"] = True
                status["imported_count"] = len(imported)
        else:
            store = {"version": 1, "templates": templates}

        names = sorted(store.get("templates", {}).keys())
        status["count"] = len(names)
        return (_metadata_json(store), _metadata_json(names), _metadata_json(status))


class GaliaisNodesComposerTemplatePack:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "操作": (["导出包", "导入包", "列出包"], {"default": "导出包"}),
                "包名称": ("STRING", {"default": "galiais_composer_templates", "multiline": False}),
                "描述": ("STRING", {"default": "", "multiline": True}),
                "模板名前缀": ("STRING", {"default": "", "multiline": False}),
                "模板包JSON": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("模板包JSON", "模板名称JSON", "状态JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/character"

    def run(self, 操作, 包名称, 描述, 模板名前缀, 模板包JSON):
        action = str(操作 or "导出包")
        pack_name = _normalize_template_name(包名称) or "galiais_composer_templates"
        prefix = _normalize_template_name(模板名前缀)
        store = _read_composer_template_store()
        templates = dict(store.get("templates", {}))
        status = {"action": action, "changed": False, "error": "", "pack_name": pack_name}

        if action == "导入包":
            try:
                payload = json.loads(str(模板包JSON or "{}"))
            except Exception as exc:
                payload = {}
                status["error"] = f"模板包JSON解析失败: {exc}"
            imported_count = 0
            if not status["error"]:
                imported = payload.get("templates") if isinstance(payload, dict) and isinstance(payload.get("templates"), dict) else {}
                for item_name, item in imported.items():
                    if not isinstance(item, dict):
                        continue
                    safe_name = _normalize_template_name(item_name)
                    if prefix and safe_name:
                        safe_name = f"{prefix}_{safe_name}"
                    template_text = str(item.get("template") or "").strip()
                    if not safe_name or not template_text:
                        continue
                    templates[safe_name] = {
                        "template": template_text,
                        "description": str(item.get("description") or "").strip(),
                        "pack": str(payload.get("pack_name") or pack_name),
                    }
                    imported_count += 1
                store = _write_composer_template_store({"templates": templates})
                status["changed"] = imported_count > 0
                status["imported_count"] = imported_count
        elif action == "列出包":
            status["count"] = len(templates)
        else:
            status["count"] = len(templates)

        export_payload = {
            "schema_version": 2,
            "node_family": "GALIAIS-Nodes",
            "pack_name": pack_name,
            "description": str(描述 or "").strip(),
            "templates": store.get("templates", {}),
        }
        names = sorted(store.get("templates", {}).keys())
        status["count"] = len(names)
        return (_metadata_json(export_payload), _metadata_json(names), _metadata_json(status))


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
    "GaliaisNodesMultiCharacterCoordinator": GaliaisNodesMultiCharacterCoordinator,
    "GaliaisNodesCharacterComposer": GaliaisNodesCharacterComposer,
    "GaliaisNodesCharacterComposerTemplateManager": GaliaisNodesCharacterComposerTemplateManager,
    "GaliaisNodesComposerTemplatePack": GaliaisNodesComposerTemplatePack,
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
    "GaliaisNodesMultiCharacterCoordinator": "GALIAIS-Nodes Multi Character Coordinator",
    "GaliaisNodesCharacterComposer": "GALIAIS-Nodes Final Composer",
    "GaliaisNodesCharacterComposerTemplateManager": "GALIAIS-Nodes Composer Template Manager",
    "GaliaisNodesComposerTemplatePack": "GALIAIS-Nodes Composer Template Pack",
}



