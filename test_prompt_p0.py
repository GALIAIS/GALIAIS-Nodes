import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


def frontend_source_node_loader() -> str:
    js_dir = ROOT / "web" / "js"
    files = [
        "galiais_nodes_danbooru_lazy_select.js",
        "galiais_nodes_api_cache.js",
        "galiais_nodes_field_map.js",
        "galiais_nodes_composer_ui.js",
        "galiais_nodes_prompt_viewer_ui.js",
    ]
    return (
        "const fs = require(\"fs\");\n"
        "const path = require(\"path\");\n"
        f"const jsDir = {str(js_dir)!r};\n"
        f"const frontendFiles = {files!r};\n"
        "const source = frontendFiles.map((name) => {\n"
        "  const filePath = path.join(jsDir, name);\n"
        "  return fs.existsSync(filePath) ? fs.readFileSync(filePath, \"utf8\") : \"\";\n"
        "}).join(\"\\n\");\n"
    )


def load_package():
    spec = importlib.util.spec_from_file_location(
        "galiais_nodes_p0",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["galiais_nodes_p0"] = package
    spec.loader.exec_module(package)
    return package


def node_result(value):
    return value["result"] if isinstance(value, dict) and "result" in value else value


def test_character_section_weight_is_applied():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    section = character.character_section_text(
        "appearance",
        ["long hair, blue eyes"],
        weight=1.25,
    )

    assert section["text"] == "(long hair:1.25), (blue eyes:1.25)"
    assert section["tags"] == ["(long hair:1.25)", "(blue eyes:1.25)"]


def test_character_composer_groups_scoped_sections_by_character_slot():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    alice_identity = character.character_section_text("core", ["1girl, alice"])
    character._apply_character_scope(alice_identity, "角色1", "Alice")
    alice_outfit = character.character_section_text("outfit", ["red dress"])
    character._apply_character_scope(alice_outfit, "角色1", "Alice")
    alice_pose = character.character_section_text("pose", ["standing"])
    character._apply_character_scope(alice_pose, "角色1", "Alice")

    bob_identity = character.character_section_text("core", ["1boy, bob"])
    character._apply_character_scope(bob_identity, "角色2", "Bob")
    bob_outfit = character.character_section_text("outfit", ["black suit"])
    character._apply_character_scope(bob_outfit, "角色2", "Bob")
    bob_pose = character.character_section_text("pose", ["sitting"])
    character._apply_character_scope(bob_pose, "角色2", "Bob")

    scene = character.character_section_text("scene", ["classroom"])
    positive, negative, metadata = character.compose_character_prompt(
        [alice_pose, bob_pose, scene, bob_identity, alice_identity, bob_outfit, alice_outfit],
        multi_character_mode="自动",
    )

    assert negative == ""
    assert "1girl, alice, red dress, standing" in positive
    assert "1boy, bob, black suit, sitting" in positive
    assert positive.index("1girl") < positive.index("1boy") < positive.index("classroom")
    assert "; " in positive
    assert '"multi_character_enabled": true' in metadata
    assert '"slot": "角色1"' in metadata
    assert '"label": "Alice"' in metadata
    assert '"slot": "角色2"' in metadata
    assert '"label": "Bob"' in metadata


def test_character_composer_keeps_legacy_flat_mode_for_global_sections():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    identity = character.character_section_text("core", ["1girl, alice"])
    outfit = character.character_section_text("outfit", ["red dress"])
    positive, _, metadata = character.compose_character_prompt([outfit, identity], multi_character_mode="自动")

    assert positive == "1girl, alice, red dress"
    assert '"multi_character_enabled": false' in metadata


def test_character_composer_can_force_flat_mode_for_scoped_sections():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    identity = character.character_section_text("core", ["1girl, alice"])
    character._apply_character_scope(identity, "角色1", "Alice")
    outfit = character.character_section_text("outfit", ["red dress"])
    character._apply_character_scope(outfit, "角色1", "Alice")
    positive, _, metadata = character.compose_character_prompt(
        [outfit, identity],
        multi_character_mode="关闭",
    )

    assert positive == "1girl, alice, red dress"
    assert '"multi_character_enabled": false' in metadata


def test_character_composer_includes_quality_preset_before_artist_and_subject():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    identity = character.character_section_text("core", ["1girl, alice"])
    identity["artist"] = "@wlop"

    positive, _, metadata = character.compose_character_prompt(
        [identity],
        quality="masterpiece, best quality, score_7, safe",
    )

    assert positive.startswith("masterpiece, best quality, score_7, safe, @wlop, 1girl, alice")
    assert '"quality_included": true' in metadata
    assert '"quality_omitted_by_anima_template": false' in metadata


def test_character_composer_can_render_custom_template_order():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    identity = character.character_section_text("core", ["1girl, alice"])
    outfit = character.character_section_text("outfit", ["red dress"])
    scene = character.character_section_text("scene", ["classroom"])

    positive, _, metadata = character.compose_character_prompt(
        [scene, outfit, identity],
        quality="masterpiece, best quality",
        prefix="cinematic",
        suffix="soft light",
        template="{{quality}}, {{scene}}, {{core}}, {{outfit}}, {{suffix}}, {{prefix}}",
    )

    assert positive == "masterpiece, best quality, classroom, 1girl, alice, red dress, soft light, cinematic"
    assert '"template_mode": "custom"' in metadata
    assert '"template_slots"' in metadata


def test_character_composer_template_store_save_delete_and_export(tmp_path):
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    original_path = character.COMPOSER_TEMPLATE_STORE_PATH
    character.COMPOSER_TEMPLATE_STORE_PATH = tmp_path / "composer_templates.json"
    try:
        manager = character.GaliaisNodesCharacterComposerTemplateManager()
        saved_json, names_json, status_json = manager.run(
            "保存/更新",
            "scene_first",
            "{{scene}}, {{core}}",
            "场景优先",
            "",
        )
        exported_json, names_json, status_json = manager.run(
            "导出全部",
            "",
            "",
            "",
            "",
        )
        deleted_json, names_json, status_json = manager.run(
            "删除",
            "scene_first",
            "",
            "",
            "",
        )

        exported = json.loads(exported_json)
        deleted = json.loads(deleted_json)

        assert exported["templates"]["scene_first"]["template"] == "{{scene}}, {{core}}"
        assert exported["templates"]["scene_first"]["description"] == "场景优先"
        assert deleted["templates"] == {}
        assert "scene_first" not in json.loads(names_json)
        assert '"action": "删除"' in status_json
    finally:
        character.COMPOSER_TEMPLATE_STORE_PATH = original_path


def test_character_node_scope_accepts_new_and_legacy_position_args():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    node = character.GaliaisNodesCharacterIdentity()

    new_order = node.run(
        "1girl",
        "alice",
        "",
        "",
        "",
        "",
        True,
        1.0,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        "只补空字段",
        0,
        0,
        False,
        0,
        "角色1",
        "Alice",
        None,
    )
    old_order = node.run(
        "1girl",
        "alice",
        "",
        "",
        "",
        "",
        True,
        1.0,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        "只补空字段",
        0,
        0,
        False,
        0,
        None,
    )

    scoped_section = node_result(new_order)[0]
    legacy_section = node_result(old_order)[0]

    assert scoped_section["character_scope"]["slot"] == "角色1"
    assert scoped_section["character_scope"]["label"] == "Alice"
    assert legacy_section["character_scope"]["slot"] == "全局"


def test_prompt_builder_keeps_lighting_part():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    builder = system.GaliaisNodesPromptBuilder()

    positive, _, metadata = builder.run(
        "无",
        "1girl",
        "hatsune miku",
        "",
        "blue eyes",
        "white shirt",
        "standing",
        "classroom",
        "soft ambient",
        "anime style",
        "detailed",
        "无",
        True,
    )

    assert "soft ambient" in positive
    assert '"lighting": "soft ambient"' in metadata


def test_template_renders_dotted_slots_from_coarse_slots():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]

    rendered = system.render_prompt_template(
        "{{appearance.hair.hair_color}}, {{background.location.outdoor}}, {{quality.style.color_palette}}",
        {
            "外观": "blue hair",
            "场景": "forest",
            "风格": "pastel colors",
        },
    )

    assert rendered == "blue hair, forest, pastel colors"


def test_all_taxonomy_tree_exposes_runtime_taxonomy():
    system = load_package().NODE_CLASS_MAPPINGS["GaliaisNodesDanbooruDBLoader"].__module__
    system = sys.modules[system]
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return

    payload = system.DanbooruDictionary(str(db_path)).all_taxonomy_tree(include_counts=False)

    assert len(payload["leaves"]) >= 239
    assert any(
        leaf["taxonomy_id"] == "0.appearance.body.anatomy.anatomical_detail"
        for leaf in payload["leaves"]
    )
    appearance_node = next(node for node in payload["nodes"] if node["id"] == "appearance")
    assert appearance_node["taxonomy_prefix"] == "0.appearance"


def test_taxonomy_select_parses_selected_tags():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesDanbooruTaxonomySelect()

    text, metadata = node.run(
        "0.appearance.body.anatomy.anatomical_detail",
        "long hair (长发), blue eyes (蓝眼睛)",
        "",
        False,
        True,
        1.1,
        False,
        0,
        0,
    )

    assert text == "(long hair:1.10), (blue eyes:1.10)"
    assert '"taxonomy_id": "0.appearance.body.anatomy.anatomical_detail"' in metadata
    assert '"count": 2' in metadata


def test_taxonomy_select_can_randomize_tags_from_db():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return
    node = system.GaliaisNodesDanbooruTaxonomySelect()

    output = node.run(
        "0.appearance.eyes.color.eye_color",
        "",
        str(db_path),
        False,
        True,
        1.0,
        True,
        2,
        123,
    )
    text, metadata = node_result(output)

    assert len(system.split_tag_text(text)) == 2
    assert '"random_enabled": true' in metadata
    assert '"random_count": 2' in metadata
    assert '"random_items": [' in metadata
    assert isinstance(output, dict)
    tag_field = output["ui"]["galiais_random_fields"][0]["Tags"]
    assert "(" in tag_field and ")" in tag_field
    assert len(system.split_tag_option_text(tag_field)) == 2


def test_random_tag_selection_samples_full_candidate_set_uniformly():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "random.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            rows = [
                (index, f"tag_{index}", f"tag_{index}", 0, 100 + index, "test", f"0.test.{index}", 0)
                for index in range(10)
            ]
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        selected = set()
        for seed in range(1, 80):
            items = system.DanbooruDictionary(str(db_path)).random_options_for_field(
                "category:0",
                count=1,
                seed=seed,
            )
            selected.add(items[0]["tag"])

    assert selected == {f"tag_{index}" for index in range(10)}


def test_danbooru_blacklist_filters_options_and_random_selection():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "blacklist.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            rows = [
                (1, "blocked_tag", "blocked_tag", 0, 500, "test", "0.test.blocked", 0),
                (2, "safe_tag", "safe_tag", 0, 400, "test", "0.test.safe", 0),
                (3, "other_tag", "other_tag", 0, 300, "test", "0.test.other", 0),
            ]
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.executemany(
                """
                insert into danbooru_tag_localizations (
                    tag_name, locale, label, normalized_label, kind
                ) values (?, 'zh-CN', ?, ?, 'primary')
                """,
                [
                    ("blocked_tag", "屏蔽标签", "屏蔽标签"),
                    ("safe_tag", "安全标签", "安全标签"),
                    ("other_tag", "其他标签", "其他标签"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        dictionary = system.DanbooruDictionary(str(db_path))
        blacklist = system.GaliaisNodesTagBlacklist().run("blocked tag (屏蔽标签)", True)[0]

        options = dictionary.option_records_for_field("category:0", blacklist=blacklist)
        option_tags = {item["tag"] for item in options["items"]}
        assert option_tags == {"safe_tag", "other_tag"}

        random_items = dictionary.random_options_for_field(
            "category:0",
            count=10,
            seed=123,
            blacklist=blacklist,
        )
        random_tags = {item["tag"] for item in random_items}
        assert random_tags == {"safe_tag", "other_tag"}
        assert "blocked_tag" not in random_tags


def test_random_taxonomy_blacklist_filters_random_only():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "random_taxonomy_blacklist.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            rows = [
                (1, "classroom", "classroom", 0, 900, "scene", "0.scene.location.indoor_public", 0),
                (2, "architecture", "architecture", 0, 800, "scene", "0.scene.structure.architecture", 0),
                (3, "barrier", "barrier", 0, 700, "scene", "0.scene.structure.barrier_or_surface", 0),
            ]
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        dictionary = system.DanbooruDictionary(str(db_path))
        options = dictionary.option_records_for_field("scene_location", include_global_blacklist=False)
        random_items = dictionary.random_options_for_field(
            "scene_location",
            count=10,
            seed=123,
            taxonomy_blacklist="0.scene.structure",
            include_global_blacklist=False,
            include_global_taxonomy_blacklist=False,
        )

    assert {item["tag"] for item in options["items"]} == {"classroom", "architecture", "barrier"}
    assert {item["tag"] for item in random_items} == {"classroom"}
    assert all(not item["taxonomy_id"].startswith("0.scene.structure") for item in random_items)


def test_random_taxonomy_blacklist_keeps_explicit_children_when_parent_is_removed():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        blacklist_path = Path(temp_dir) / "taxonomy_blacklist.json"
        original_path = system.RANDOM_TAXONOMY_BLACKLIST_PATH
        system.RANDOM_TAXONOMY_BLACKLIST_PATH = blacklist_path
        try:
            child = "0.scene.structure.architecture"
            sibling = "0.scene.structure.barrier_or_surface"
            parent = "0.scene.structure"

            assert system.add_global_random_taxonomy_blacklist([child]) == (child,)
            assert set(system.add_global_random_taxonomy_blacklist((item for item in [parent]))) == {child, parent}
            assert system.remove_global_random_taxonomy_blacklist([parent]) == (child,)

            saved = json.loads(blacklist_path.read_text(encoding="utf-8"))
            assert saved["taxonomy_ids"] == [child]
            assert "<generator" not in json.dumps(saved, ensure_ascii=False)
            assert set(system.add_global_random_taxonomy_blacklist([sibling])) == {child, sibling}
        finally:
            system.RANDOM_TAXONOMY_BLACKLIST_PATH = original_path


def test_global_tag_blacklist_filters_dictionary_without_extra_node():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "global_blacklist.db"
        blacklist_path = Path(temp_dir) / "tag_blacklist.json"
        original_path = system.TAG_BLACKLIST_PATH
        system.TAG_BLACKLIST_PATH = blacklist_path
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, "blocked_tag", "blocked_tag", 0, 500, "test", "0.test.blocked", 0),
                    (2, "safe_tag", "safe_tag", 0, 400, "test", "0.test.safe", 0),
                ],
            )
            conn.commit()
            system.add_global_tag_blacklist("blocked tag")
            dictionary = system.DanbooruDictionary(str(db_path))

            options = dictionary.option_records_for_field("category:0", mark_blacklist_only=True)
            random_items = dictionary.random_options_for_field("category:0", count=10, seed=1)
        finally:
            conn.close()
            system.TAG_BLACKLIST_PATH = original_path

    assert {item["tag"] for item in options["items"]} == {"blocked_tag", "safe_tag"}
    assert {item["tag"] for item in options["items"] if item["is_blacklisted"]} == {"blocked_tag"}
    assert {item["tag"] for item in random_items} == {"safe_tag"}


def test_display_form_with_comma_label_is_parsed_as_one_tag():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]

    parts = system.split_tag_option_text("alpha (中文, 标签), beta (说明；补充), gamma (中文, 标签)")
    parsed = [system.parse_tag_option(part) for part in parts]

    assert parts == ["alpha (中文, 标签)", "beta (说明；补充)", "gamma (中文, 标签)"]
    assert parsed == ["alpha", "beta", "gamma"]


def test_character_body_can_randomize_empty_fields_from_db():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return
    node = character.GaliaisNodesCharacterBody()

    output = node.run(
        "blue eyes",
        "",
        "",
        "",
        "",
        True,
        1.0,
        True,
        True,
        True,
        True,
        True,
        True,
        "只补空字段",
        1,
        123,
        False,
        0,
        {"db_path": str(db_path)},
    )
    section, text, metadata = node_result(output)

    assert "blue eyes" in text
    assert len(system.split_tag_text(text)) >= 2
    assert "body_limbs" in section["random"]["items"]
    assert "body_shape" not in section["random"]["items"]
    assert isinstance(output, dict)
    assert output["ui"]["galiais_random_fields"][0]["四肢躯干"] == section["random"]["random_field_values"]["body_limbs"]
    assert "(" in output["ui"]["galiais_random_fields"][0]["四肢躯干"]
    assert "blue eyes" not in output["ui"]["galiais_random_fields"][0]["四肢躯干"]
    assert '"enabled": true' in metadata


def test_character_body_can_override_random_count_per_field():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "per_field_random.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            rows = [
                (1, "body_shape_a", "body_shape_a", 0, 900, "body", "0.appearance.body.build.body_build", 0),
                (2, "body_limbs_a", "body_limbs_a", 0, 800, "body", "0.appearance.body.limb.limbs_hands_feet", 0),
                (3, "body_limbs_b", "body_limbs_b", 0, 760, "body", "0.appearance.body.limb.limbs_hands_feet", 0),
                (5, "body_limbs_low", "body_limbs_low", 0, 200, "body", "0.appearance.body.limb.limbs_hands_feet", 0),
                (4, "skin_texture_a", "skin_texture_a", 0, 600, "body", "0.appearance.body.skin.skin_tone", 0),
            ]
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.executemany(
                """
                insert into danbooru_tag_localizations (
                    tag_name, locale, label, normalized_label, kind
                ) values (?, 'zh-CN', ?, ?, 'primary')
                """,
                [(row[1], row[1], row[1]) for row in rows],
            )
            conn.commit()
        finally:
            conn.close()

        node = character.GaliaisNodesCharacterBody()
        output = node.run(
            "",
            "",
            "",
            "",
            "",
            True,
            1.0,
            True,
            True,
            True,
            True,
            True,
            True,
            "只补空字段",
            1,
            123,
            False,
            0,
            {"db_path": str(db_path)},
            "全局",
            "",
            **{
                "随机数体型比例": -1,
                "随机数四肢躯干": 2,
                "随机数皮肤质感": 0,
                "随机数非人身体": -1,
                "最低热度体型比例": -1,
                "最低热度四肢躯干": 750,
                "最低热度皮肤质感": -1,
                "最低热度非人身体": -1,
            },
        )
    section = node_result(output)[0]

    assert len(section["random"]["items"]["body_shape"]) == 1
    assert len(section["random"]["items"]["body_limbs"]) == 2
    assert {item["tag"] for item in section["random"]["items"]["body_limbs"]} == {"body_limbs_a", "body_limbs_b"}
    assert "body_skin" not in section["random"]["items"]
    assert section["random"]["per_field_counts"]["body_shape"] == 1
    assert section["random"]["per_field_counts"]["body_limbs"] == 2
    assert section["random"]["per_field_counts"]["body_skin"] == 0
    assert section["random"]["per_field_min_post_counts"]["body_shape"] == 0
    assert section["random"]["per_field_min_post_counts"]["body_limbs"] == 750


def test_random_controls_expose_per_field_count_and_heat_inputs():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    style = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_style"]

    body_inputs = character.GaliaisNodesCharacterBody.INPUT_TYPES()["required"]
    style_inputs = style.GaliaisNodesDanbooruStyleSelect.INPUT_TYPES()["required"]

    assert body_inputs["随机数四肢躯干"][1]["default"] == -1
    assert body_inputs["随机数四肢躯干"][1]["min"] == -1
    assert body_inputs["最低热度四肢躯干"][1]["default"] == -1
    assert body_inputs["最低热度四肢躯干"][1]["min"] == -1
    assert "随机数身体补充" not in body_inputs
    assert "最低热度身体补充" not in body_inputs

    assert style_inputs["随机数渲染风格"][1]["default"] == -1
    assert style_inputs["最低热度渲染风格"][1]["default"] == -1
    assert "最低热度追加到提示词" not in style_inputs


def test_character_random_selection_respects_db_blacklist():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return
    db_payload = system.GaliaisNodesDanbooruDBLoader().run(
        str(db_path),
        "zh-CN",
        False,
        system.GaliaisNodesTagBlacklist().run("blue eyes", True)[0],
    )[0]
    node = character.GaliaisNodesCharacterFaceHairEyes()

    output = node.run(
        "",
        "",
        "",
        "",
        "",
        True,
        1.0,
        False,
        True,
        False,
        False,
        False,
        True,
        "只补空字段",
        20,
        123,
        False,
        0,
        db_payload,
        "全局",
        "",
    )
    section = node_result(output)[0]
    random_text = section["random"]["random_field_values"].get("face_eyes", "")

    assert "blue eyes" not in random_text
    assert all(item["tag"] != "blue_eyes" for item in section["random"]["items"].get("face_eyes", []))


def test_random_display_is_cleared_when_manual_fields_block_random_fill():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return
    node = character.GaliaisNodesCharacterBody()

    output = node.run(
        "blue eyes",
        "standing",
        "pale skin",
        "animal ears",
        "",
        True,
        1.0,
        True,
        True,
        True,
        True,
        True,
        True,
        "只补空字段",
        1,
        123,
        False,
        0,
        {"db_path": str(db_path)},
    )
    section, _, _ = node_result(output)

    assert isinstance(output, dict)
    assert output["ui"]["galiais_random_fields"] == []
    assert section["random"]["random_field_values"] == {}


def test_taxonomy_random_display_is_cleared_when_random_has_no_output():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesDanbooruTaxonomySelect()

    output = node.run(
        "0.appearance.eyes.color.eye_color",
        "blue eyes",
        "",
        False,
        True,
        1.0,
        True,
        2,
        123,
    )
    text, _ = node_result(output)

    assert text == "blue eyes"
    assert isinstance(output, dict)
    assert output["ui"]["galiais_random_fields"] == []


def test_frontend_random_execution_display_does_not_write_manual_widgets():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
if (/function\\s+applyRandomFieldBackfill\\s*\\(/.test(source)) {{
  throw new Error("random execution still backfills source widgets");
}}
if (!/function\\s+updateRandomFieldsWidget\\s*\\(/.test(source)) {{
  throw new Error("random execution display widget is missing");
}}
const handler = source.match(/nodeType\\.prototype\\.onExecuted = function \\(message\\) \\{{[\\s\\S]*?\\n\\s*\\}};/);
if (!handler || !handler[0].includes("updateRandomFieldsWidget(this, message || {{}})")) {{
  throw new Error("onExecuted does not update the display-only random widget");
}}
if (handler[0].includes("setWidgetValue(")) {{
  throw new Error("onExecuted still writes into manual widgets");
}}
if (!source.includes("const hasRandomFieldPayload = Object.prototype.hasOwnProperty.call(message || {{}}, \\"galiais_random_fields\\")")) {{
  throw new Error("random display does not distinguish clear payloads from missing payloads");
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_field_enable_controls_are_inline_toggles():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
for (const name of [
  "buildFieldEnablePairs",
  "hideFieldEnableWidgets",
  "renderVueFieldEnableToggles",
  "scheduleVueFieldEnableToggles",
  "ensureVueFieldEnableToggles",
  "ensureFieldEnableMutationObserver",
  "applyFieldEnableDimState"
]) {{
  if (!source.includes(`function ${{name}}`)) {{
    throw new Error(`${{name}} is missing`);
  }}
}}
if (!/enableWidget\\.hidden\\s*=\\s*true/.test(source)) {{
  throw new Error("field enable widgets are not hidden from layout");
}}
if (/enableWidget\\.serialize\\s*=\\s*false/.test(source)) {{
  throw new Error("field enable widgets must stay serialized");
}}
if (!source.includes("const FIELD_ENABLE_TOGGLE_CLASS = \\"galiais-field-enable-toggle\\"") ||
    !source.includes(".lg-node-widget") ||
    !source.includes("row.appendChild(button)")) {{
  throw new Error("field enable controls are not injected into Vue widget rows");
}}
if (!source.includes("new MutationObserver") ||
    !source.includes("ensureVueFieldEnableToggles(this)")) {{
  throw new Error("field enable controls are not restored after Vue rerenders");
}}
if (!source.includes("setWidgetValue(currentPair.enableWidget, !isFieldEnabled(currentPair.enableWidget))")) {{
  throw new Error("inline field toggles do not write back to hidden enable widgets");
}}
if (!source.includes("if (!isVueNodeMode(this) && toggleFieldEnableAtPosition(this, pos, fieldEnablePairs))")) {{
  throw new Error("legacy canvas field toggles are not limited to non-Vue node mode");
}}
if (!source.includes("widget._galiaisFieldEnabled = isFieldEnabled(pair.enableWidget)")) {{
  throw new Error("disabled fields are not marked for dim drawing");
}}
if (!source.includes("function syncFieldRandomControlVisibility(node, fieldEnablePairs)") ||
    !source.includes("const RANDOM_ENABLE_WIDGET_NAME") ||
    !source.includes("const AI_INTENT_WIDGET_NAMES = new Set") ||
    !source.includes("const AI_RAG_WIDGET_NAMES = new Set") ||
    !source.includes("const RANDOM_GLOBAL_CONTROL_NAMES = new Set") ||
    !source.includes("function setWidgetHiddenState(widget, hidden)") ||
    !source.includes("function syncVueWidgetRowVisibility(node)") ||
    !source.includes("function clearRandomFieldsWidget(node)") ||
    !source.includes("function ensureRandomEnableVisibilityCallback(node)") ||
    !source.includes("const randomEnableWidget = byName.get(RANDOM_ENABLE_WIDGET_NAME)") ||
    !source.includes("const randomEnabled = isFieldEnabled(randomEnableWidget)") ||
    !source.includes("const aiIntentModeEnabled = aiModeEnabled && modeValue.startsWith(\\"AI意图定向选择\\")") ||
    !source.includes("changed = setWidgetHiddenState(controlWidget, !aiIntentModeEnabled) || changed") ||
    !source.includes("changed = setWidgetHiddenState(controlWidget, !aiModeEnabled) || changed") ||
    !source.includes("changed = clearRandomFieldsWidget(node) || changed") ||
    !source.includes("changed = setWidgetHiddenState(controlWidget, !randomEnabled) || changed") ||
    !source.includes("for (const prefix of [") ||
    !source.includes("const hidden = !randomEnabled || (pair ? !isFieldEnabled(pair.enableWidget) : false)") ||
    !source.includes("syncVueWidgetRowVisibility(node)") ||
    !source.includes("const randomCallbackChanged = ensureRandomEnableVisibilityCallback(node)")) {{
  throw new Error("disabled fields do not hide their per-field random controls");
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_legacy_canvas_field_toggles_reserve_widget_space():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
for (const name of [
  "const FIELD_ENABLE_CANVAS_RESERVED_WIDTH",
  "function patchLegacyCanvasWidgetDraw",
  "function ensureLegacyCanvasFieldEnableLayout",
  "function updateLegacyCanvasFieldEnableToggles",
  "function scheduleLegacyCanvasFieldEnableToggles",
  "function removeLegacyCanvasFieldEnableToggles",
  "function handleLegacyCanvasFieldTogglePointer",
  "function ensureLegacyCanvasPointerHandler",
]) {{
  if (!source.includes(name)) {{
    throw new Error(`${{name}} is missing`);
  }}
}}
if (!source.includes("const reserved = Number(widget._galiaisCanvasReservedWidth || 0)") ||
    !source.includes("const drawWidth = Math.max(80, Number(width || 0) - reserved)") ||
    !source.includes("ctx, nodeArg, drawWidth, y, height, lowQuality")) {{
  throw new Error("legacy canvas widget draw width is not reduced for inline toggles");
}}
if (source.includes("FIELD_ENABLE_CANVAS_MIN_WIDTH") ||
    source.includes("legacyCanvasFieldEnableMinimumWidth") ||
    source.includes("node.setSize([minimumWidth")) {{
  throw new Error("legacy canvas field toggles must not force node width on refresh");
}}
if (!source.includes("ensureLegacyCanvasFieldEnableLayout(node, fieldEnablePairs)")) {{
  throw new Error("legacy canvas layout is not ensured during scrub");
}}
if (!source.includes("isVueNodeMode(this) && selectorFieldsForNode(this, lazyFields).length")) {{
  throw new Error("legacy canvas still draws the floating DB selector button over widgets");
}}
if (!source.includes("!isVueNodeMode(this) && toggleFieldEnableAtPosition(this, pos, fieldEnablePairs)")) {{
  throw new Error("legacy canvas field toggle hit testing is not isolated from Vue mode");
}}
if (!source.includes("element.addEventListener(\\"pointerdown\\", handleLegacyCanvasFieldTogglePointer, true)") ||
    !source.includes("eventToCanvasPosition(event)") ||
    !source.includes("nodeLocalPositionFromCanvas(node, canvasPos)")) {{
  throw new Error("legacy canvas field toggles are not captured at the canvas level");
}}
if (!source.includes("const FIELD_ENABLE_CANVAS_TOGGLE_CLASS = \\"galiais-field-enable-canvas-toggle\\"") ||
    !source.includes("document.body.appendChild(button)") ||
    !source.includes("button.addEventListener(\\"pointerdown\\"") ||
    !source.includes("canvasRectToClientRect(node, rect)") ||
    !source.includes("removeLegacyCanvasFieldEnableToggles(this)")) {{
  throw new Error("legacy canvas field toggles do not use real DOM overlays");
}}
if (!source.includes("canvas.convertEventToCanvasOffset(event)") ||
    !source.includes("canvas.convertCanvasToOffset([") ||
    !source.includes("function ensureLegacyCanvasTrackingLoop") ||
    !source.includes("legacyCanvasTrackingFrame") ||
    !source.includes("removeAllLegacyCanvasFieldEnableToggles")) {{
  throw new Error("legacy canvas overlays are not synchronized through LiteGraph canvas transforms");
}}
if (source.includes("drawFieldEnableToggles(this, ctx, fieldEnablePairs);\\n        }} else {{\\n            scheduleLegacyCanvasFieldEnableToggles")) {{
  throw new Error("legacy canvas still draws duplicate canvas toggles behind DOM overlays");
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_input_node_refresh_does_not_grow_multiline_widgets():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
if (!source.includes("function refreshNodeSize(node, changed = false, options = {{}})")) {{
  throw new Error("refreshNodeSize does not expose refresh sizing options");
}}
if (!source.includes("const allowHeightGrowth = options?.allowHeightGrowth !== false") ||
    !source.includes("let nextHeight = currentHeight") ||
    !source.includes("nextHeight = Math.max(currentHeight, computedHeight)")) {{
  throw new Error("refreshNodeSize cannot preserve saved node height");
}}
if (!source.includes("const fitHeight = options?.fitHeight === true") ||
    !source.includes("nextHeight = computedHeight") ||
    !source.includes("refreshNodeSize(node, true, {{ fitHeight: true }});") ||
    !source.includes("schedule(() => refreshNodeSize(node, true, {{ fitHeight: true }}));")) {{
  throw new Error("manual random toggles do not resize nodes to the current visible random controls");
}}
const protectedRefreshes = source.match(/refreshNodeSize\\(this, changed \\|\\| buttonChanged, \\{{ allowHeightGrowth: false \\}}\\)/g) || [];
if (protectedRefreshes.length < 1) {{
  throw new Error("tag input nodes do not preserve saved height on configure refresh");
}}
if (source.includes("refreshNodeSize(this, changed || buttonChanged);")) {{
  const configureBlock = source.match(/nodeType\\.prototype\\.onConfigure = function \\(\\) \\{{[\\s\\S]*?nodeType\\.prototype\\.onNodeCreated = function \\(\\) \\{{/);
  if (configureBlock && configureBlock[0].includes("refreshNodeSize(this, changed || buttonChanged);")) {{
    throw new Error("tag input nodes can still grow multiline supplemental fields on configure refresh");
  }}
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_danbooru_selector_passes_tag_blacklist_to_backend():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
if (!source.includes("function findDanbooruTagBlacklist()") ||
    !source.includes("function refreshGlobalTagBlacklist()") ||
    !source.includes("function updateGlobalTagBlacklist(action, tags)") ||
    !source.includes("/galiais-nodes/danbooru/tag_blacklist")) {{
  throw new Error("frontend does not use the global tag blacklist service");
}}
if (!source.includes("let blacklist = findDanbooruTagBlacklist()")) {{
  throw new Error("selector does not snapshot the current blacklist");
}}
if (!source.includes("let rowBlacklisted = !!item.is_blacklisted") ||
    !source.includes('const row = document.createElement("div")') ||
    !source.includes('row.setAttribute("role", "button")') ||
    !source.includes("const activateRow = () => {{") ||
    !source.includes('row.addEventListener("keydown", (event) => {{') ||
    !source.includes('row.dataset.blacklisted = item.is_blacklisted ? "1" : "0"') ||
    !source.includes(".galiais-nodes-danbooru-row-tools .galiais-nodes-danbooru-button") ||
    !source.includes("white-space: nowrap;") ||
    !source.includes("min-width: 58px;") ||
    !source.includes('const action = rowBlacklisted ? "remove" : "add"') ||
    !source.includes('blacklist = await updateGlobalTagBlacklist(action, [tagName])') ||
    !source.includes('rowBlacklisted = action === "add"') ||
    !source.includes('row.classList.toggle("is-blacklisted", rowBlacklisted)') ||
    !source.includes('row.removeAttribute("aria-disabled")') ||
    source.includes('const row = document.createElement("button");\\n        row.className = "galiais-nodes-danbooru-row"') ||
    source.includes('block.disabled = isBlacklisted') ||
    source.includes('if (isBlacklisted) return;')) {{
  throw new Error("selector rows cannot add tags directly to the blacklist");
}}
const blacklistParamCount = (source.match(/blacklist,/g) || []).length;
if (blacklistParamCount < 4) {{
  throw new Error("selector does not pass blacklist through cache, options and random requests");
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_tag_generation_mode_callback_uses_existing_layout_refresh():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
if (!source.includes("function ensureTagGenerationModeVisibilityCallback(node)")) {{
  throw new Error("tag generation mode callback is missing");
}}
if (source.includes("requestNodeLayoutRefresh")) {{
  throw new Error("tag generation mode callback calls an undefined layout refresh function");
}}
if (!source.includes("schedule(() => refreshNodeSize(node, true, {{ fitHeight: true }}));")) {{
  throw new Error("tag generation mode callback does not resize using the existing refreshNodeSize path");
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_danbooru_selector_supports_random_taxonomy_blacklist():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
if (!source.includes("let globalRandomTaxonomyBlacklist = new Set()") ||
    !source.includes("function refreshGlobalRandomTaxonomyBlacklist()") ||
    !source.includes("function updateGlobalRandomTaxonomyBlacklist(action, taxonomyIds)") ||
    !source.includes("/galiais-nodes/danbooru/random_taxonomy_blacklist")) {{
  throw new Error("frontend does not use random taxonomy blacklist service");
}}
if (!source.includes("let randomTaxonomyBlacklist = findRandomTaxonomyBlacklist()") ||
    !source.includes("taxonomy_blacklist: randomTaxonomyBlacklist")) {{
  throw new Error("random requests do not include random taxonomy blacklist");
}}
if (!source.includes("galiais-nodes-danbooru-tree-random-block") ||
    !source.includes("node.taxonomy_prefix || node.taxonomy_id || node.id") ||
    !source.includes('randomBlocked ? "已屏蔽" : "屏蔽"') ||
    source.includes('randomBlocked ? "已屏蔽" : "随机屏蔽"') ||
    !source.includes("randomTaxonomyBlacklist = await updateGlobalRandomTaxonomyBlacklist(action, [randomBlacklistPath])")) {{
  throw new Error("taxonomy tree rows cannot toggle random taxonomy blacklist");
}}
if (!source.includes("function isRandomTaxonomyBlockedByAncestorOrSelf(value)") ||
    !source.includes("function hasRandomTaxonomyBlockedDescendant(value)") ||
    !source.includes("const randomBlocked = isRandomTaxonomyBlockedByAncestorOrSelf(randomBlacklistPath)") ||
    !source.includes("const randomPartiallyBlocked = !randomBlocked && hasRandomTaxonomyBlockedDescendant(randomBlacklistPath)") ||
    !source.includes("is-random-partial-blocked") ||
    source.includes("function isRandomTaxonomyBlacklisted(value)")) {{
  throw new Error("taxonomy parent blocked state must not be caused by child-only blacklist entries");
}}
if (!source.includes("Promise.all([refreshGlobalTagBlacklist(), refreshGlobalRandomTaxonomyBlacklist()]")) {{
  throw new Error("selector does not refresh random taxonomy blacklist before random use");
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_runtime_random_nodes_only_force_refresh_for_auto_seed():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    style = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_style"]
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]

    assert character.GaliaisNodesCharacterBody.IS_CHANGED(
        启用随机Tag=False,
        每字段随机数=1,
        随机种子=0,
    ) is False
    assert character.GaliaisNodesCharacterBody.IS_CHANGED(
        启用随机Tag=True,
        每字段随机数=1,
        随机种子=123,
    ) == "random-fixed-seed:123"
    assert character.GaliaisNodesCharacterBody.IS_CHANGED(
        启用随机Tag=True,
        每字段随机数=0,
        随机种子=0,
    ) is False
    first = character.GaliaisNodesCharacterBody.IS_CHANGED(
        启用随机Tag=True,
        每字段随机数=1,
        随机种子=0,
    )
    second = character.GaliaisNodesCharacterBody.IS_CHANGED(
        启用随机Tag=True,
        每字段随机数=1,
        随机种子=0,
    )
    assert first != second
    assert first.startswith("random-auto-seed:")
    assert style.GaliaisNodesDanbooruStyleSelect.IS_CHANGED(
        启用随机Tag=True,
        每字段随机数=1,
        随机种子=123,
    ) == "random-fixed-seed:123"
    assert system.GaliaisNodesDanbooruTaxonomySelect.IS_CHANGED(
        启用随机Tag=True,
        随机数量=1,
        随机种子=123,
    ) == "random-fixed-seed:123"


def test_character_body_field_switch_disables_selected_and_random_tags():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return
    node = character.GaliaisNodesCharacterBody()

    output = node.run(
        "blue eyes",
        "",
        "",
        "",
        "manual body note",
        True,
        1.0,
        False,
        True,
        False,
        True,
        False,
        True,
        "只补空字段",
        1,
        123,
        False,
        0,
        {"db_path": str(db_path)},
    )
    section, text, metadata = node_result(output)

    assert "blue eyes" not in text
    assert "manual body note" not in text
    assert "body_shape" not in section["random"]["items"]
    assert "body_limbs" in section["random"]["items"]
    assert "体型比例" in section["fields"]["disabled_fields"]
    assert "身体补充" in section["fields"]["disabled_fields"]
    assert '"disabled_fields": [' in metadata


def test_character_fixed_fields_cover_all_runtime_taxonomy():
    package = load_package()
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return

    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    dictionary = system.DanbooruDictionary(str(db_path))
    leaves = {
        leaf["taxonomy_id"]
        for leaf in dictionary.all_taxonomy_tree(include_counts=False)["leaves"]
    }
    registered = set()
    for spec in system.GALIAIS_NODES_DANBOORU_FIELD_REGISTRY.values():
        registered.update(spec.get("taxonomy_ids", []))

    assert leaves - registered == set()
    for node in [
        "GaliaisNodesCharacterFaceHairEyes",
        "GaliaisNodesCharacterBody",
        "GaliaisNodesCharacterMetaTechnical",
        "GaliaisNodesCharacterNarrative",
        "GaliaisNodesCharacterObjectSupplement",
    ]:
        assert node in package.NODE_CLASS_MAPPINGS
        assert node in package.NODE_DISPLAY_NAME_MAPPINGS
    assert "GaliaisNodesCharacterAppearance" not in package.NODE_CLASS_MAPPINGS
    assert "GaliaisNodesCharacterAppearance" not in package.NODE_DISPLAY_NAME_MAPPINGS


def test_prompt_viewer_returns_ui_preview_and_passthrough():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    viewer = system.GaliaisNodesPromptViewer()

    result = viewer.run(
        "1girl, blue eyes",
        "bad hands",
        '{"source":"test"}',
        "示例",
        True,
    )

    assert result["result"] == ("1girl, blue eyes", "bad hands", '{"source":"test"}')
    assert result["ui"]["title"] == ["示例"]
    assert result["ui"]["positive"] == ["1girl, blue eyes"]
    assert result["ui"]["negative"] == ["bad hands"]
    assert result["ui"]["metadata"] == ['{"source":"test"}']


def test_ai_provider_masks_key_and_builds_config_without_network():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesAIProvider()

    provider, model, models_json, status_json, embedding_provider = node.run(
        "https://example.test",
        "sk-test-secret",
        "gpt-test",
        "",
        "自动",
        False,
        20,
        0.35,
        1200,
        "关闭",
        "medium",
        "auto",
        False,
    )

    assert provider["api_key"] == "sk-test-secret"
    assert provider["model"] == "gpt-test"
    assert provider["stream"] is False
    assert model == "gpt-test"
    assert embedding_provider["model"] == ""
    assert embedding_provider["provider_kind"] == "embedding"
    assert models_json == "[]"
    assert "sk-test-secret" not in status_json
    assert "sk-t...cret" in status_json


def test_ai_provider_splits_llm_and_embedding_models_and_outputs_embedding_provider():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesAIProvider()

    class FakeClient:
        def list_models(self, provider):
            return ["text-embedding-3-large", "gpt-5.4-mini", "bge-m3"]

    with patch.object(system, "OpenAICompatibleClient", return_value=FakeClient()):
        provider, model, models_json, status_json, embedding_provider = node.run(
            "https://example.test",
            "sk-test-secret",
            "",
            "",
            "自动",
            True,
            20,
            0.35,
            1200,
            "关闭",
            "medium",
            "fast",
            False,
            3,
            0.75,
            True,
        )

    status = json.loads(status_json)
    assert provider["model"] == "gpt-5.4-mini"
    assert model == "gpt-5.4-mini"
    assert embedding_provider["model"] == "text-embedding-3-large"
    assert embedding_provider["provider_kind"] == "embedding"
    assert embedding_provider["endpoint"] == "embeddings"
    assert embedding_provider["base_url"] == provider["base_url"]
    assert embedding_provider["api_key"] == "sk-test-secret"
    assert json.loads(models_json) == ["text-embedding-3-large", "gpt-5.4-mini", "bge-m3"]
    assert status["available_llm_models"] == ["gpt-5.4-mini"]
    assert status["available_embedding_models"] == ["text-embedding-3-large", "bge-m3"]
    assert status["embedding_model"] == "text-embedding-3-large"
    assert "sk-test-secret" not in status_json


def test_ai_provider_exposes_fast_service_tier_and_client_sends_it():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesAIProvider()
    inputs = node.INPUT_TYPES()["required"]

    assert "fast" in inputs["服务层级"][0]

    provider, _, _, status_json, _ = node.run(
        "https://example.test",
        "sk-test-secret",
        "gpt-test",
        "",
        "自动",
        False,
        20,
        0.35,
        1200,
        "关闭",
        "medium",
        "fast",
        False,
    )

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(request, timeout=30):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    with patch.object(system.urllib.request, "urlopen", side_effect=fake_urlopen):
        response = system.OpenAICompatibleClient().chat_completion(
            provider,
            [{"role": "user", "content": "hi"}],
        )

    assert provider["service_tier"] == "fast"
    assert '"service_tier": "fast"' in status_json
    assert captured["body"]["service_tier"] == "fast"
    assert response["content"] == "ok"


def test_ai_base_url_auto_normalizes_common_openai_endpoints():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]

    assert system._normalize_openai_base_url("https://gw2.oops.asia", "自动") == "https://gw2.oops.asia/v1"
    assert system._normalize_openai_base_url("https://gw2.oops.asia/v1", "自动") == "https://gw2.oops.asia/v1"
    assert system._normalize_openai_base_url("https://gw2.oops.asia/v1/models", "自动") == "https://gw2.oops.asia/v1"
    assert (
        system._normalize_openai_base_url("https://gw2.oops.asia/v1/chat/completions", "自动")
        == "https://gw2.oops.asia/v1"
    )
    assert (
        system._normalize_openai_base_url("https://gw2.oops.asia/v1/chat/completions", "保持原样")
        == "https://gw2.oops.asia/v1/chat/completions"
    )


def test_ai_http_request_uses_browser_compatible_headers():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"data":[]}'

    def fake_urlopen(request, timeout=30):
        captured["headers"] = dict(request.header_items())
        return FakeResponse()

    with patch.object(system.urllib.request, "urlopen", side_effect=fake_urlopen):
        payload = system._json_http_request("GET", "https://example.test/v1/models", "sk-test")

    assert payload == {"data": []}
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert "mozilla" in headers["user-agent"].lower()
    assert headers["accept-language"].startswith("zh-CN")
    assert headers["authorization"] == "Bearer sk-test"


def test_cloudflare_1010_error_is_explained_for_ai_provider():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    message = system._ai_http_error_message(
        "AI接口请求失败",
        403,
        '{"error_code":1010,"error_name":"browser_signature_banned","cloudflare_error":true}',
    )

    assert "Cloudflare" in message
    assert "browser_signature_banned/1010" in message
    assert "白名单" in message


def test_openai_compatible_client_parses_streaming_chat_completion():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"hello "}}]}\n',
                    b'data: {"choices":[{"delta":{"content":"world"},"finish_reason":"stop"}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "stream": True,
    }

    with patch.object(system.urllib.request, "urlopen", return_value=FakeResponse()):
        response = system.OpenAICompatibleClient().chat_completion(provider, [{"role": "user", "content": "hi"}])

    assert response["content"] == "hello world"
    assert response["raw"]["stream"] is True
    assert response["raw"]["event_count"] == 2


def test_openai_compatible_client_can_request_embeddings():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"data":[{"embedding":[0.1,0.2]},{"embedding":[0.3,0.4]}],"model":"text-embedding-3-large"}'

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "text-embedding-3-large",
        "api_mode": "保持原样",
        "timeout": 20,
    }

    with patch.object(system.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = system.OpenAICompatibleClient().embeddings(provider, ["alpha", "beta"])

    assert captured["url"] == "https://example.test/v1/embeddings"
    assert captured["body"]["model"] == "text-embedding-3-large"
    assert captured["body"]["input"] == ["alpha", "beta"]
    assert result["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]
    assert result["raw"]["model"] == "text-embedding-3-large"


def test_ai_provider_exposes_retry_and_stream_fallback_controls():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesAIProvider()
    inputs = node.INPUT_TYPES()["required"]

    assert "重试次数" in inputs
    assert "重试退避秒" in inputs
    assert "流式失败降级" in inputs

    provider, _, _, status_json, _ = node.run(
        "https://example.test",
        "sk-test-secret",
        "gpt-test",
        "",
        "自动",
        False,
        20,
        0.35,
        1200,
        "关闭",
        "medium",
        "auto",
        True,
        4,
        0.25,
        True,
    )

    assert provider["retry_count"] == 4
    assert provider["retry_backoff"] == 0.25
    assert provider["stream_fallback"] is True
    assert '"retry_count": 4' in status_json
    assert '"stream_fallback": true' in status_json


def test_ai_provider_health_check_reports_model_chat_and_stream_status():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "stream": False,
        "retry_count": 1,
        "retry_backoff": 0,
        "stream_fallback": True,
    }

    class FakeClient:
        def list_models(self, provider_config):
            return ["gpt-test", "gpt-other"]

        def chat_completion(self, provider_config, messages):
            raw = {"retry": {"attempts": 1}}
            if provider_config.get("stream"):
                raw = {"stream": True, "event_count": 1}
            return {"content": "OK", "raw": raw}

    node = system.GaliaisNodesAIProviderHealthCheck(client=FakeClient())
    ok, latency, report_json, suggestion = node.run(provider, True, True, True, True, "Reply OK")
    report = json.loads(report_json)

    assert ok is True
    assert latency >= 0
    assert report["checks"]["models"]["count"] == 2
    assert report["checks"]["models"]["current_model_listed"] is True
    assert report["checks"]["chat"]["ok"] is True
    assert report["checks"]["stream"]["ok"] is True
    assert "可用" in suggestion


def test_ai_provider_health_check_recommends_stream_disable_on_stream_failure():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "stream": False,
        "retry_count": 1,
        "retry_backoff": 0,
        "stream_fallback": True,
    }

    class FakeClient:
        def list_models(self, provider_config):
            return ["gpt-test"]

        def chat_completion(self, provider_config, messages):
            if provider_config.get("stream"):
                raise RuntimeError("AI流式接口连接失败: timed out")
            return {"content": "OK", "raw": {"retry": {"attempts": 1}}}

    node = system.GaliaisNodesAIProviderHealthCheck(client=FakeClient())
    ok, _, report_json, suggestion = node.run(provider, True, True, True, True, "Reply OK")
    report = json.loads(report_json)

    assert ok is False
    assert report["checks"]["chat"]["ok"] is True
    assert report["checks"]["stream"]["ok"] is False
    assert "流式响应" in suggestion


def test_openai_client_retries_stream_timeout_then_falls_back_to_non_stream():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"fallback ok"}}]}'

    def fake_urlopen(request, timeout=30):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(body)
        if body.get("stream"):
            raise system.urllib.error.URLError(TimeoutError(10060, "timed out"))
        return FakeResponse()

    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "stream": True,
        "retry_count": 2,
        "retry_backoff": 0,
        "stream_fallback": True,
    }

    with patch.object(system.urllib.request, "urlopen", side_effect=fake_urlopen):
        response = system.OpenAICompatibleClient().chat_completion(provider, [{"role": "user", "content": "hi"}])

    assert response["content"] == "fallback ok"
    assert len(calls) == 2
    assert calls[0]["stream"] is True
    assert "stream" not in calls[1]
    assert response["raw"]["retry"]["attempts"] == 2
    assert response["raw"]["retry"]["stream_fallback"] is True
    assert "AI流式接口连接失败" in response["raw"]["retry"]["errors"][0]


def test_openai_client_falls_back_when_stream_returns_empty_content():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    calls = []

    class EmptyStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            return iter([b"data: [DONE]\n"])

    class JsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"non stream ok"}}]}'

    def fake_urlopen(request, timeout=30):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(body)
        if body.get("stream"):
            return EmptyStreamResponse()
        return JsonResponse()

    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "stream": True,
        "retry_count": 2,
        "retry_backoff": 0,
        "stream_fallback": True,
    }

    with patch.object(system.urllib.request, "urlopen", side_effect=fake_urlopen):
        response = system.OpenAICompatibleClient().chat_completion(provider, [{"role": "user", "content": "hi"}])

    assert response["content"] == "non stream ok"
    assert len(calls) == 2
    assert response["raw"]["retry"]["stream_fallback"] is True
    assert "AI流式接口返回为空" in response["raw"]["retry"]["errors"][0]


def test_positive_prompt_ai_enricher_appends_natural_language_from_mock_client():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class FakeClient:
        def chat_completion(self, provider_config, messages):
            return {
                "content": '{"natural_language":"a calm portrait with clear blue eyes","analysis":{"subject":"solo girl"}}',
                "raw": {"id": "mock"},
            }

    node = system.GaliaisNodesPositivePromptAIEnricher(client=FakeClient())
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, blue eyes",
        "",
        "中文",
        "追加到末尾",
        "精炼",
        True,
        True,
        0,
        None,
    )

    assert enhanced == "1girl, blue eyes, a calm portrait with clear blue eyes"
    assert natural == "a calm portrait with clear blue eyes"
    assert '"subject": "solo girl"' in analysis_json
    assert '"ai_called": true' in analysis_json
    assert '"natural_language_empty": false' in analysis_json
    assert '"id": "mock"' in raw_json


def test_positive_prompt_ai_enricher_marks_empty_ai_response():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class EmptyClient:
        def chat_completion(self, provider_config, messages):
            return {"content": "", "raw": {"id": "empty"}}

    node = system.GaliaisNodesPositivePromptAIEnricher(client=EmptyClient())
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, blue eyes",
        "",
        "中文",
        "追加到末尾",
        "精炼",
        True,
        True,
        0,
        None,
    )

    assert enhanced == "1girl, blue eyes"
    assert natural == ""
    assert '"ai_called": true' in analysis_json
    assert '"natural_language_empty": true' in analysis_json
    assert '"warning": "AI返回为空，未生成自然语言补充。"' in analysis_json
    assert '"id": "empty"' in raw_json


def test_positive_prompt_ai_enricher_reports_fallback_error_when_enabled():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]

    class FailingClient:
        def chat_completion(self, provider_config, messages):
            raise RuntimeError("boom")

    node = system.GaliaisNodesPositivePromptAIEnricher(client=FailingClient())
    enhanced, natural, analysis_json, raw_json = node.run(
        {"model": "gpt-test"},
        "1girl, blue eyes",
        "",
        "中文",
        "追加到末尾",
        "精炼",
        True,
        True,
        0,
        None,
    )

    assert enhanced == "1girl, blue eyes"
    assert natural == ""
    assert '"ai_called": false' in analysis_json
    assert '"fallback": true' in analysis_json
    assert '"error": "boom"' in analysis_json
    assert '"error": "boom"' in raw_json


def test_positive_prompt_ai_enricher_passes_db_tag_context_to_ai():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class CapturingClient:
        def __init__(self):
            self.messages = []

        def chat_completion(self, provider_config, messages):
            self.messages = messages
            return {
                "content": '{"natural_language":"a focused portrait emphasizing blue eyes","analysis":{"dominant_taxonomy":["0.appearance.eyes.color.eye_color"]}}',
                "raw": {"id": "db-context"},
            }

    client = CapturingClient()
    node = system.GaliaisNodesPositivePromptAIEnricher(client=client)
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, blue eyes",
        "",
        "英文",
        "追加到末尾",
        "标准",
        True,
        True,
        0,
        {"db_path": str(db_path)},
    )

    user_payload = client.messages[1]["content"]
    assert '"tag": "blue_eyes"' in user_payload
    assert "蓝瞳" in user_payload
    assert '"taxonomy_id": "0.appearance.eyes.color.eye_color"' in user_payload
    assert '"is_nsfw": false' in user_payload
    assert "one girl" in enhanced
    assert "blue eyes" in enhanced
    assert natural.count(".") >= 2
    assert "dominant_taxonomy" in analysis_json
    assert '"natural_language_quality_repaired": true' in analysis_json
    assert '"id": "db-context"' in raw_json


def test_positive_prompt_ai_enricher_can_prune_conflicts_before_ai_call():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class CapturingClient:
        def __init__(self):
            self.messages = []

        def chat_completion(self, provider_config, messages):
            self.messages = messages
            return {
                "content": '{"natural_language":"a happy portrait","analysis":{"conflict_pruned":true}}',
                "raw": {"id": "pruned"},
            }

    client = CapturingClient()
    node = system.GaliaisNodesPositivePromptAIEnricher(client=client)
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, smile, crying, blue eyes",
        "",
        "英文",
        "追加到末尾",
        "精炼",
        True,
        True,
        0,
        True,
        "保留前者",
        False,
        None,
    )

    user_payload = client.messages[1]["content"]
    assert '"tags": "1girl, smile, blue eyes"' in user_payload
    assert "crying" not in enhanced
    assert natural == "a happy portrait"
    assert '"conflict_pruning_enabled": true' in analysis_json
    assert '"removed": [' in analysis_json
    assert '"crying"' in analysis_json
    assert '"id": "pruned"' in raw_json


def test_positive_prompt_ai_enricher_sends_sanitized_generation_plan_to_ai():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class CapturingClient:
        def __init__(self):
            self.messages = []

        def chat_completion(self, provider_config, messages):
            self.messages = messages
            return {
                "content": '{"natural_language":"a warm portrait with a gentle smile","analysis":{"safe_generation":true}}',
                "raw": {"id": "sanitized-plan"},
            }

    client = CapturingClient()
    node = system.GaliaisNodesPositivePromptAIEnricher(client=client)
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, score_9, smile, crying, blue eyes",
        "",
        "英文",
        "追加到末尾",
        "精炼",
        True,
        True,
        0,
        False,
        "自动",
        False,
        None,
    )

    payload = json.loads(client.messages[1]["content"])
    plan = payload["danbooru_context"]["generation_plan"]

    assert payload["tags"] == "1girl, smile, blue eyes"
    assert plan["sanitized_prompt"] == "1girl, smile, blue eyes"
    assert any(item["tag"] == "crying" and item["reason"] == "情绪冲突" for item in plan["dropped_tags"])
    assert any(
        item["tag"] == "score_9" and item["reason"] == "质量/评分/控制类tag不适合扩写成自然语言"
        for item in plan["suppressed_tags"]
    )
    assert "crying" in plan["blocked_natural_language_terms"]
    assert "score 9" in plan["blocked_natural_language_terms"]
    assert natural == "a warm portrait with a gentle smile"
    assert enhanced == "1girl, score_9, smile, crying, blue eyes, a warm portrait with a gentle smile"
    assert '"sanitized_prompt": "1girl, smile, blue eyes"' in analysis_json
    assert '"id": "sanitized-plan"' in raw_json


def test_positive_prompt_ai_enricher_sends_caption_blueprint_and_strengthens_short_standard_output():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class ShortClient:
        def __init__(self):
            self.messages = []

        def chat_completion(self, provider_config, messages):
            self.messages = messages
            return {
                "content": '{"natural_language":"nice image","analysis":{"too_short":true}}',
                "raw": {"id": "short"},
            }

    client = ShortClient()
    node = system.GaliaisNodesPositivePromptAIEnricher(client=client)
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, smile, blue eyes, looking at viewer, simple background",
        "",
        "英文",
        "仅自然语言",
        "标准",
        True,
        True,
        0,
        False,
        "自动",
        False,
        None,
    )

    payload = json.loads(client.messages[1]["content"])
    blueprint = payload["danbooru_context"]["caption_blueprint"]
    analysis = json.loads(analysis_json)

    assert "baseline_natural_language" in blueprint
    assert "one girl" in blueprint["baseline_natural_language"]
    assert "blue eyes" in blueprint["baseline_natural_language"]
    assert "looking at viewer" in blueprint["baseline_natural_language"]
    assert natural.count(".") >= 2
    assert "nice image" not in natural
    assert "_" not in natural
    assert enhanced == natural
    assert analysis["natural_language_quality_repaired"] is True
    assert '"id": "short"' in raw_json


def test_positive_prompt_ai_enricher_full_anima_mode_locks_tags_and_requests_complete_language():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class CapturingClient:
        def __init__(self):
            self.messages = []

        def chat_completion(self, provider_config, messages):
            self.messages = messages
            return {
                "content": json.dumps(
                    {
                        "natural_language": (
                            "A close-up anime portrait shows one girl looking directly at the viewer. "
                            "Her blue eyes and calm smile are framed by a clean daytime composition."
                        ),
                        "analysis": {"mode": "full_anima"},
                        "added_focus": ["composition", "gaze"],
                    }
                ),
                "raw": {"id": "full-anima"},
            }

    client = CapturingClient()
    node = system.GaliaisNodesPositivePromptAIEnricher(client=client)
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, blue eyes, smile, close-up, day",
        "",
        "英文",
        "追加到末尾",
        "详细",
        True,
        True,
        0,
        False,
        "自动",
        False,
        None,
        "Anima完整自然语言",
        2,
        4,
    )

    payload = json.loads(client.messages[1]["content"])
    system_prompt = client.messages[0]["content"]
    analysis = json.loads(analysis_json)

    assert payload["enrichment_mode"] == "Anima完整自然语言"
    assert payload["locked_tags"] == "1girl, blue eyes, smile, close-up, day"
    assert payload["sentence_range"] == {"min": 2, "max": 4}
    assert "Existing tags are locked" in system_prompt
    assert any("不要改写、删除、替换或新增 tag" in item for item in payload["requirements"])
    assert any("至少 2 句" in item for item in payload["requirements"])
    assert enhanced.startswith("1girl, blue eyes, smile, close-up, day, ")
    assert natural.count(".") >= 2
    assert analysis["enrichment_mode"] == "Anima完整自然语言"
    assert analysis["tag_lock"] is True
    assert '"id": "full-anima"' in raw_json


def test_positive_prompt_ai_enricher_scene_director_mode_requires_rich_background_blueprint():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class ShortSceneClient:
        def __init__(self):
            self.messages = []

        def chat_completion(self, provider_config, messages):
            self.messages = messages
            return {
                "content": '{"natural_language":"nice image","analysis":{"too_plain":true}}',
                "raw": {"id": "scene-director"},
            }

    client = ShortSceneClient()
    node = system.GaliaisNodesPositivePromptAIEnricher(client=client)
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, solo, long black hair, sitting, looking away, indoors, tiled wall, window, poster, bottle, vase, steam, warm lighting, detailed background",
        "参考方向：复古室内小房间，背景要有窗格、墙面海报、瓶罐、雾气和暖冷光层次；忽略任何R18内容。",
        "英文",
        "仅自然语言",
        "详细",
        True,
        True,
        0,
        False,
        "自动",
        False,
        None,
        "场景导演描述",
        3,
        6,
    )

    payload = json.loads(client.messages[1]["content"])
    system_prompt = client.messages[0]["content"]
    blueprint = payload["danbooru_context"]["scene_design_blueprint"]
    analysis = json.loads(analysis_json)

    assert payload["enrichment_mode"] == "场景导演描述"
    assert "scene_design_blueprint" in payload["danbooru_context"]
    assert "foreground" in blueprint
    assert "midground" in blueprint
    assert "background" in blueprint
    assert "lighting" in blueprint
    assert "atmosphere" in blueprint
    assert "environment_props" in blueprint
    assert "rich background" in system_prompt
    assert any("前景" in item and "中景" in item and "背景" in item for item in payload["requirements"])
    assert natural.count(".") >= 3
    assert "nice image" not in natural
    assert any(term in natural.lower() for term in ["window", "poster", "bottle", "vase", "steam", "tiled wall"])
    assert any(term in natural.lower() for term in ["foreground", "midground", "background", "layer"])
    assert enhanced == natural
    assert analysis["natural_language_quality_repaired"] is True
    assert analysis["generation_plan"]["scene_design_blueprint"] == blueprint
    assert '"id": "scene-director"' in raw_json


def test_positive_prompt_ai_enricher_tag_constrained_full_expansion_requires_full_image_blueprint():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    assert "Tag约束全面扩写" in system.AI_ENRICHMENT_MODES
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class ShortFullClient:
        def __init__(self):
            self.messages = []

        def chat_completion(self, provider_config, messages):
            self.messages = messages
            return {
                "content": '{"natural_language":"beautiful anime scene","analysis":{"too_plain":true}}',
                "raw": {"id": "tag-full-expansion"},
            }

    client = ShortFullClient()
    node = system.GaliaisNodesPositivePromptAIEnricher(client=client)
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "masterpiece, best quality, score_7, safe, 1girl, solo, long black hair, sitting, looking away, indoors, tiled wall, window, poster, bottle, vase, steam, warm lighting, detailed background, cinematic composition",
        "只根据tag进行完整画面设计，不新增tag，忽略R18方向。",
        "英文",
        "仅自然语言",
        "详细",
        True,
        True,
        123,
        False,
        "自动",
        False,
        None,
        "Tag约束全面扩写",
        4,
        8,
    )

    payload = json.loads(client.messages[1]["content"])
    system_prompt = client.messages[0]["content"]
    blueprint = payload["danbooru_context"]["full_image_detail_blueprint"]
    analysis = json.loads(analysis_json)

    assert payload["enrichment_mode"] == "Tag约束全面扩写"
    assert "full_image_detail_blueprint" in payload["danbooru_context"]
    for key in [
        "subject",
        "pose_action",
        "appearance",
        "composition_camera",
        "spatial_layers",
        "setting",
        "background_props",
        "lighting",
        "atmosphere",
        "color_design",
        "rendering_style",
        "narrative_intent",
        "safety_constraints",
        "output_contract",
    ]:
        assert key in blueprint
    assert "complete image design" in system_prompt
    assert "do not output new tags" in system_prompt
    assert any("主体" in item and "姿态" in item and "背景物件" in item for item in payload["requirements"])
    assert any("不新增 tag" in item for item in payload["requirements"])
    assert natural.count(".") >= 4
    assert "beautiful anime scene" not in natural
    assert any(term in natural.lower() for term in ["subject", "foreground", "midground", "background"])
    assert any(term in natural.lower() for term in ["window", "poster", "bottle", "vase", "steam", "tiled wall"])
    assert enhanced == natural
    assert analysis["natural_language_quality_repaired"] is True
    assert analysis["generation_plan"]["full_image_detail_blueprint"] == blueprint
    assert '"id": "tag-full-expansion"' in raw_json


def test_image_detail_blueprint_node_outputs_full_scene_dimensions():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesImageDetailBlueprint()

    blueprint_json, scene_text, full_text, diagnostics_json = node.run(
        "1girl, solo, long black hair, sitting, looking away, indoors, tiled wall, window, poster, bottle, vase, steam, warm lighting, detailed background, cinematic composition",
        "英文",
        "详细",
        True,
        "自动",
        False,
        None,
    )
    blueprint = json.loads(blueprint_json)
    diagnostics = json.loads(diagnostics_json)

    full_blueprint = blueprint["full_image_detail_blueprint"]
    for key in [
        "subject",
        "pose_action",
        "appearance",
        "outfit_materials",
        "composition_camera",
        "spatial_layers",
        "setting",
        "background_props",
        "lighting",
        "atmosphere",
        "color_design",
        "rendering_style",
        "narrative_intent",
        "safety_constraints",
        "output_contract",
    ]:
        assert key in full_blueprint
    assert blueprint["tag_lock"] is True
    assert "foreground" in full_blueprint["spatial_layers"]
    assert "background" in full_blueprint["spatial_layers"]
    assert "background" in scene_text.lower()
    assert "foreground" in full_text.lower()
    assert diagnostics["full_sentence_count"] >= 2


def test_prompt_orchestrator_chains_blueprint_ai_negative_and_quality():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
        "retry_count": 1,
        "retry_backoff": 0,
        "stream_fallback": True,
    }

    class FakeClient:
        def chat_completion(self, provider_config, messages):
            return {
                "content": '{"natural_language":"The foreground frames one girl near a window, while the midground contains posters and bottles. The background uses warm lighting, steam, and tiled walls to create depth.","analysis":{"ok":true}}',
                "raw": {"id": "orchestrator"},
            }

    node = system.GaliaisNodesPromptOrchestrator(client=FakeClient())
    positive, negative, natural, score, flow_json = node.run(
        provider,
        "masterpiece, best quality, score_7, safe, 1girl, solo, indoors, window, poster, bottle, steam, warm lighting, detailed background",
        "extra limbs",
        "标准",
        "英文",
        "详细",
        "Tag约束全面扩写",
        True,
        True,
        "自动",
        False,
        True,
        True,
        None,
    )
    flow = json.loads(flow_json)

    assert "1girl" in positive
    assert "foreground" in positive.lower()
    assert "bad hands" in negative
    assert "extra limbs" in negative
    assert natural.startswith("The foreground")
    assert isinstance(score, int)
    assert flow["ai_called"] is True
    assert flow["tag_lock"] is True
    assert flow["blueprint"]["full_image_detail_blueprint"]["output_contract"]["language"] == "英文"
    assert flow["ai_raw"]["id"] == "orchestrator"


def test_multi_character_coordinator_groups_roles_and_outputs_context():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    alice_identity = character.character_section_text("core", ["1girl, alice"])
    character._apply_character_scope(alice_identity, "角色1", "Alice")
    alice_outfit = character.character_section_text("outfit", ["red dress"])
    character._apply_character_scope(alice_outfit, "角色1", "Alice")
    bob_identity = character.character_section_text("core", ["1boy, bob"])
    character._apply_character_scope(bob_identity, "角色2", "Bob")
    bob_pose = character.character_section_text("pose", ["sitting"])
    character._apply_character_scope(bob_pose, "角色2", "Bob")

    node = character.GaliaisNodesMultiCharacterCoordinator()
    section, text, layout_json, context = node.run(
        True,
        "英文",
        "左到右",
        "交互",
        "Alice stands beside Bob.",
        True,
        alice_identity,
        alice_outfit,
        bob_identity,
        bob_pose,
    )
    layout = json.loads(layout_json)

    assert section["name"] == "narrative"
    assert "角色1" in layout["characters"]
    assert "角色2" in layout["characters"]
    assert layout["characters"]["角色1"]["label"] == "Alice"
    assert "1girl" in layout["characters"]["角色1"]["text"]
    assert "1boy" in layout["characters"]["角色2"]["text"]
    assert "left side" in text.lower()
    assert "right side" in text.lower()
    assert "Alice stands beside Bob" in text
    assert "multi_character_layout" in context


def test_scene_director_outputs_layered_scene_without_ai():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesSceneDirector()

    scene_prompt, scene_json, section_text = node.run(
        "1girl, solo, indoors, window, poster, bottle, steam, warm lighting, detailed background, cinematic composition",
        "英文",
        "详细",
        True,
        "自动",
        False,
        None,
    )
    scene = json.loads(scene_json)

    assert "foreground" in scene
    assert "midground" in scene
    assert "background" in scene
    assert "lighting" in scene
    assert "atmosphere" in scene
    assert "foreground" in scene_prompt.lower()
    assert "background" in scene_prompt.lower()
    assert "window" in scene_prompt.lower() or "poster" in scene_prompt.lower()
    assert section_text == scene_prompt


def test_prompt_quality_gate_returns_actionable_suggestions():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesPromptQualityGate()

    passed, score, grade, suggestions, gate_json = node.run(
        "1girl, smile, crying, simple background, detailed background",
        False,
        85,
        None,
    )
    payload = json.loads(gate_json)

    assert passed is False
    assert score < 85
    assert grade in {"B", "C", "D"}
    assert "冲突" in suggestions
    assert any(item["type"] == "conflicts" for item in payload["suggestions"])
    assert any(item["type"] == "scene_depth" for item in payload["suggestions"])


def test_ai_request_cache_reuses_identical_simple_task_calls():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def chat_completion(self, provider_config, messages):
            self.calls += 1
            return {"content": f"mock output {self.calls}", "raw": {"id": f"call-{self.calls}"}}

    fake = FakeClient()
    provider = {
        "base_url": "https://example.test/v1",
        "model": "gpt-test",
        "ai_cache_enabled": True,
    }
    writer = system.GaliaisNodesAINaturalPromptWriter(client=fake)

    first_text, first_raw = writer.run(provider, '{"known":[]}', "英文", "精炼")
    second_text, second_raw = writer.run(provider, '{"known":[]}', "英文", "精炼")

    assert first_text == second_text == "mock output 1"
    assert fake.calls == 1
    assert '"cache_hit": true' in second_raw


def test_frontend_uses_shared_api_cache_module():
    api_cache = (ROOT / "web" / "js" / "galiais_nodes_api_cache.js").read_text(encoding="utf-8")
    selector = (ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js").read_text(encoding="utf-8")

    assert "export function createLruCache" in api_cache
    assert "export async function readJsonResponse" in api_cache
    assert 'from "./galiais_nodes_api_cache.js"' in selector
    assert "const optionPageCache = createLruCache(OPTION_PAGE_CACHE_LIMIT)" in selector
    assert "function getLruCache" not in selector
    assert "function setLruCache" not in selector


def test_composer_template_pack_import_export_versioned_schema(tmp_path):
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    original_path = character.COMPOSER_TEMPLATE_STORE_PATH
    character.COMPOSER_TEMPLATE_STORE_PATH = tmp_path / "composer_templates.json"
    try:
        node = character.GaliaisNodesComposerTemplatePack()
        pack_json, names_json, status_json = node.run(
            "导入包",
            "cinematic_pack",
            "Cinematic templates",
            "",
            json.dumps(
                {
                    "schema_version": 2,
                    "pack_name": "cinematic_pack",
                    "templates": {
                        "scene_first": {
                            "template": "{{quality}}, {{scene}}, {{core}}",
                            "description": "Scene before character",
                        }
                    },
                },
                ensure_ascii=False,
            ),
        )
        exported_json, exported_names_json, exported_status_json = node.run(
            "导出包",
            "cinematic_pack",
            "Cinematic templates",
            "",
            "",
        )
        pack = json.loads(exported_json)
        names = json.loads(exported_names_json)
        status = json.loads(status_json)

        assert status["changed"] is True
        assert status["imported_count"] == 1
        assert pack["schema_version"] == 2
        assert pack["pack_name"] == "cinematic_pack"
        assert pack["templates"]["scene_first"]["template"] == "{{quality}}, {{scene}}, {{core}}"
        assert "scene_first" in names
        assert '"action": "导出包"' in exported_status_json
    finally:
        character.COMPOSER_TEMPLATE_STORE_PATH = original_path


def test_positive_prompt_ai_enricher_repairs_ai_output_that_mentions_dropped_tags():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    provider = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "api_mode": "保持原样",
        "timeout": 20,
        "temperature": 0.2,
        "max_tokens": 300,
        "reasoning_mode": "关闭",
        "reasoning_effort": "low",
        "service_tier": "auto",
        "stream": False,
    }

    class LeakingClient:
        def chat_completion(self, provider_config, messages):
            return {
                "content": '{"natural_language":"a crying portrait with blue eyes","analysis":{"bad":true}}',
                "raw": {"id": "leaking"},
            }

    node = system.GaliaisNodesPositivePromptAIEnricher(client=LeakingClient())
    enhanced, natural, analysis_json, raw_json = node.run(
        provider,
        "1girl, smile, crying, blue eyes",
        "",
        "英文",
        "追加到末尾",
        "精炼",
        True,
        True,
        0,
        False,
        "自动",
        False,
        None,
    )

    analysis = json.loads(analysis_json)

    assert "crying" not in natural.lower()
    assert "one girl" in natural
    assert "blue eyes" in natural
    assert "crying" not in enhanced.split(", ")[-1].lower()
    assert analysis["natural_language_repaired"] is True
    assert "crying" in analysis["natural_language_leaks"]
    assert '"id": "leaking"' in raw_json


def test_positive_prompt_ai_context_accepts_display_form_tags():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    db_path = ROOT.parent / "danbooru-dictionary.runtime.db"
    if not db_path.exists():
        return

    context = system._build_positive_tag_context(
        "blue eyes (蓝瞳), 1girl (单人女孩)",
        {"db_path": str(db_path)},
    )

    tags = {item["tag"] for item in context["resolved_tags"]}
    assert {"blue_eyes", "1girl"}.issubset(tags)
    assert not context["unresolved_tags"]
    assert context["taxonomy_groups"]["0.appearance.eyes.color.eye_color"]["label_zh"] == "瞳色"


def _create_ai_selection_test_db(path: Path, total: int = 8):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            create table danbooru_tags (
                id integer primary key,
                name text not null unique,
                normalized_name text not null default '',
                category integer,
                post_count integer not null default 0,
                semantic_category_key text,
                taxonomy_id text,
                is_nsfw integer not null default 0
            );
            create table danbooru_tag_localizations (
                id integer primary key autoincrement,
                tag_name text not null,
                locale text not null default 'zh-CN',
                label text not null,
                normalized_label text not null,
                kind text not null default 'primary'
            );
            """
        )
        rows = [
            (
                index,
                f"candidate_{index}",
                f"candidate_{index}",
                0,
                10000 - index,
                "test",
                "0.test.ai.selection",
                0,
            )
            for index in range(1, total + 1)
        ]
        rows[0] = (1, "valid_tag", "valid_tag", 0, 12000, "test", "0.test.ai.selection", 0)
        conn.executemany(
            """
            insert into danbooru_tags (
                id, name, normalized_name, category, post_count,
                semantic_category_key, taxonomy_id, is_nsfw
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.executemany(
            """
            insert into danbooru_tag_localizations (
                tag_name, locale, label, normalized_label, kind
            ) values (?, 'zh-CN', ?, ?, 'primary')
            """,
            [
                ("valid_tag", "有效标签", "有效标签"),
                *[
                    (f"candidate_{index}", f"候选{index}", f"候选{index}")
                    for index in range(2, total + 1)
                ],
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_ai_coordinated_tag_selection_uses_only_candidate_tags_and_context():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_selection.db"
        _create_ai_selection_test_db(db_path)

        class CapturingClient:
            def __init__(self):
                self.provider_config = {}
                self.messages = []

            def chat_completion(self, provider_config, messages):
                self.provider_config = provider_config
                self.messages = messages
                return {
                    "content": json.dumps(
                        {
                            "fields": {
                                "category:0": ["valid_tag", "not_in_candidates"],
                                "disabled_field": ["candidate_2"],
                            },
                            "analysis": {"picked": "valid_tag"},
                        }
                    ),
                    "raw": {"id": "ai-select"},
                }

        client = CapturingClient()
        provider = {
            "base_url": "https://example.test/v1",
            "model": "gpt-test",
            "temperature": 0.2,
            "max_tokens": 300,
        }
        values, metadata = system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider=provider,
            client=client,
            node_name="测试节点",
            field_labels={"category:0": "测试字段"},
            previous_context="1girl, solo",
            strategy="只补空字段",
            per_field_count=1,
            seed=10,
            allow_nsfw=False,
            min_post_count=0,
            freedom=0.25,
            fallback_to_random=False,
        )

    payload = json.loads(client.messages[1]["content"])

    assert values["category:0"] == "valid tag (有效标签)"
    assert "not_in_candidates" not in values["category:0"]
    assert payload["previous_context"] == "1girl, solo"
    assert payload["node_name"] == "测试节点"
    assert [field["field"] for field in payload["fields"]] == ["category:0"]
    assert payload["fields"][0]["label"] == "测试字段"
    assert metadata["ai_called"] is True
    assert metadata["selected_field_values"]["category:0"] == "valid tag (有效标签)"
    assert metadata["invalid_selections"]["category:0"] == ["not_in_candidates"]
    assert client.provider_config["temperature"] > provider["temperature"]


def test_ai_coordinated_tag_selection_freedom_expands_candidate_pool():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_freedom.db"
        _create_ai_selection_test_db(db_path, total=90)

        class FirstCandidateClient:
            def __init__(self):
                self.provider_config = {}
                self.candidate_count = 0

            def chat_completion(self, provider_config, messages):
                self.provider_config = provider_config
                payload = json.loads(messages[1]["content"])
                candidates = payload["fields"][0]["candidates"]
                self.candidate_count = len(candidates)
                return {
                    "content": json.dumps({"fields": {"category:0": [candidates[0]["tag"]]}}),
                    "raw": {"id": "freedom"},
                }

        provider = {"base_url": "https://example.test/v1", "model": "gpt-test", "temperature": 0.1}
        low_client = FirstCandidateClient()
        high_client = FirstCandidateClient()

        system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider=provider,
            client=low_client,
            field_labels={"category:0": "测试字段"},
            per_field_count=1,
            seed=2,
            freedom=0.0,
            fallback_to_random=False,
        )
        system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider=provider,
            client=high_client,
            field_labels={"category:0": "测试字段"},
            per_field_count=1,
            seed=2,
            freedom=1.0,
            fallback_to_random=False,
        )

    assert high_client.candidate_count > low_client.candidate_count
    assert high_client.provider_config["temperature"] > low_client.provider_config["temperature"]


def test_ai_coordinated_tag_selection_count_is_maximum_not_required():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_max_count.db"
        _create_ai_selection_test_db(db_path, total=30)

        class TwoCandidateClient:
            def __init__(self):
                self.payload = {}

            def chat_completion(self, provider_config, messages):
                self.payload = json.loads(messages[1]["content"])
                candidates = self.payload["fields"][0]["candidates"]
                return {
                    "content": json.dumps(
                        {"fields": {"category:0": [candidates[0]["tag"], candidates[1]["tag"]]}}
                    ),
                    "raw": {"id": "max-count"},
                }

        client = TwoCandidateClient()
        values, metadata = system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider={"base_url": "https://example.test/v1", "model": "gpt-test"},
            client=client,
            field_labels={"category:0": "测试字段"},
            per_field_count=10,
            seed=5,
            freedom=0.8,
            fallback_to_random=False,
        )

    assert client.payload["fields"][0]["max_select_count"] == 10
    assert "select_count" not in client.payload["fields"][0]
    assert "最多" in " ".join(client.payload["requirements"])
    assert len(metadata["selected_items"]["category:0"]) == 2
    assert len(system.split_tag_option_text(values["category:0"])) == 2


def test_random_count_controls_have_no_user_facing_upper_limit():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    style = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_style"]

    character_inputs = character.GaliaisNodesCharacterBody.INPUT_TYPES()["required"]
    style_inputs = style.GaliaisNodesDanbooruStyleSelect.INPUT_TYPES()["required"]

    assert "max" not in character_inputs["每字段随机数"][1]
    assert "max" not in character_inputs["随机数体型比例"][1]
    assert "max" not in style_inputs["每字段随机数"][1]
    assert "max" not in style_inputs["随机数渲染风格"][1]


def test_ai_coordinated_tag_selection_high_freedom_prioritizes_exploratory_candidates():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_freedom_order.db"
        _create_ai_selection_test_db(db_path, total=90)

        class CandidateOrderClient:
            def __init__(self):
                self.candidates = []
                self.requirements = []

            def chat_completion(self, provider_config, messages):
                payload = json.loads(messages[1]["content"])
                self.candidates = payload["fields"][0]["candidates"]
                self.requirements = payload["requirements"]
                return {
                    "content": json.dumps({"fields": {"category:0": [self.candidates[0]["tag"]]}}),
                    "raw": {"id": "freedom-order"},
                }

        provider = {"base_url": "https://example.test/v1", "model": "gpt-test", "temperature": 0.1}
        low_client = CandidateOrderClient()
        high_client = CandidateOrderClient()

        system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider=provider,
            client=low_client,
            field_labels={"category:0": "测试字段"},
            per_field_count=1,
            seed=2,
            freedom=0.0,
            fallback_to_random=False,
        )
        system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider=provider,
            client=high_client,
            field_labels={"category:0": "测试字段"},
            per_field_count=1,
            seed=2,
            freedom=1.0,
            fallback_to_random=False,
        )

    assert low_client.candidates[0]["tag"] == "valid_tag"
    assert low_client.candidates[0]["candidate_source"] == "popular"
    assert high_client.candidates[0]["tag"] != "valid_tag"
    assert high_client.candidates[0]["candidate_source"] == "exploratory"
    assert any(item["candidate_source"] == "exploratory" for item in high_client.candidates[:5])
    assert all("post_count" not in item for item in high_client.candidates)
    assert any("探索型" in item or "exploratory" in item.lower() for item in high_client.requirements)
    assert any("min_post_count" in item for item in high_client.requirements)


def test_ai_coordinated_tag_selection_high_freedom_demotes_generic_popular_tags():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_generic_demote.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            rows = [
                (1, "day", "day", 0, 500000, "scene", "0.scene.environment.time_of_day", 0),
                (2, "night", "night", 0, 300000, "scene", "0.scene.environment.time_of_day", 0),
                (3, "sunset", "sunset", 0, 200000, "scene", "0.scene.environment.time_of_day", 0),
                (4, "rain", "rain", 0, 100000, "scene", "0.scene.environment.weather", 0),
                (5, "fog", "fog", 0, 90000, "scene", "0.scene.environment.weather", 0),
                (6, "golden_hour", "golden_hour", 0, 80000, "scene", "0.scene.environment.time_of_day", 0),
                (7, "storm", "storm", 0, 70000, "scene", "0.scene.environment.weather", 0),
                (8, "twilight", "twilight", 0, 60000, "scene", "0.scene.environment.time_of_day", 0),
                (9, "snowing", "snowing", 0, 50000, "scene", "0.scene.environment.weather", 0),
                (10, "overcast", "overcast", 0, 40000, "scene", "0.scene.environment.weather", 0),
            ]
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        class CandidateCaptureClient:
            def __init__(self):
                self.candidates = []
                self.payload = {}

            def chat_completion(self, provider_config, messages):
                self.payload = json.loads(messages[1]["content"])
                self.candidates = self.payload["fields"][0]["candidates"]
                return {
                    "content": json.dumps({"fields": {"scene_time_weather": [self.candidates[0]["tag"]]}}),
                    "raw": {"id": "generic-demote"},
                }

        client = CandidateCaptureClient()
        system.ai_select_tags_for_fields(
            {"scene_time_weather": ""},
            db_path=str(db_path),
            provider={"base_url": "https://example.test/v1", "model": "gpt-test"},
            client=client,
            field_labels={"scene_time_weather": "时间天气"},
            per_field_count=1,
            seed=3,
            freedom=1.0,
            fallback_to_random=False,
        )

    top_tags = [item["tag"] for item in client.candidates[:5]]
    assert "day" not in top_tags
    assert client.payload["diversity_pressure"] == "high"
    assert client.payload["selection_run_id"]


def test_ai_coordinated_tag_selection_expands_only_enabled_field_taxonomy():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_taxonomy_expand.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            rows = [
                (1, "city", "city", 0, 9000, "scene", "0.scene.location.outdoor_urban", 0),
                (2, "alley", "alley", 0, 8000, "scene", "0.scene.location.outdoor_urban", 0),
                (3, "rooftop", "rooftop", 0, 7000, "scene", "0.scene.location.outdoor_urban", 0),
                (4, "library", "library", 0, 6000, "scene", "0.scene.location.indoor_public", 0),
                (5, "forest", "forest", 0, 5000, "scene", "0.scene.location.outdoor_nature", 0),
                (6, "from_side", "from_side", 0, 4000, "composition", "0.composition.camera.view_direction", 0),
            ]
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        class ExpandThenSelectClient:
            def __init__(self):
                self.payloads = []

            def chat_completion(self, provider_config, messages):
                payload = json.loads(messages[1]["content"])
                self.payloads.append(payload)
                if len(self.payloads) == 1:
                    return {
                        "content": json.dumps(
                            {
                                "expand_requests": [
                                    {
                                        "field": "scene_location",
                                        "taxonomy_ids": ["0.scene.location.outdoor_urban"],
                                        "query": "city",
                                        "count": 3,
                                    },
                                    {
                                        "field": "scene_camera",
                                        "taxonomy_ids": ["0.composition.camera.view_direction"],
                                        "query": "from",
                                        "count": 3,
                                    },
                                ],
                                "analysis": {"need_more": True},
                            }
                        ),
                        "raw": {"id": "expand-request"},
                    }
                candidates = payload["fields"][0]["candidates"]
                return {
                    "content": json.dumps({"fields": {"scene_location": [candidates[0]["tag"]]}}),
                    "raw": {"id": "expanded-select"},
                }

        client = ExpandThenSelectClient()
        values, metadata = system.ai_select_tags_for_fields(
            {"scene_location": ""},
            db_path=str(db_path),
            provider={"base_url": "https://example.test/v1", "model": "gpt-test"},
            client=client,
            field_labels={"scene_location": "地点背景"},
            per_field_count=1,
            seed=7,
            freedom=1.0,
            fallback_to_random=False,
        )

    assert len(client.payloads) == 2
    second_candidates = client.payloads[1]["fields"][0]["candidates"]
    assert values["scene_location"]
    assert metadata["ai_expansion"]["used"] is True
    assert metadata["ai_expansion"]["ignored_requests"][0]["field"] == "scene_camera"
    assert {item["field"] for item in metadata["ai_expansion"]["requests"]} == {"scene_location"}
    assert all(item["taxonomy_id"].startswith("0.scene.location") for item in second_candidates)
    assert all(item["tag"] != "from_side" for item in second_candidates)


def test_ai_coordinated_identity_character_work_pairing_autocorrects_mismatched_work():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_identity_pair.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            rows = [
                (1, "firefly_(honkai:_star_rail)", "firefly_(honkai:_star_rail)", 4, 9000, "character", "4.character.identity.named_character", 0),
                (2, "honkai:_star_rail", "honkai:_star_rail", 3, 8000, "copyright", "3.copyright.medium.mobile_gacha", 0),
                (3, "genshin_impact", "genshin_impact", 3, 7000, "copyright", "3.copyright.medium.mobile_gacha", 0),
            ]
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.executemany(
                """
                insert into danbooru_tag_localizations (
                    tag_name, locale, label, normalized_label, kind
                ) values (?, 'zh-CN', ?, ?, 'primary')
                """,
                [
                    ("firefly_(honkai:_star_rail)", "流萤", "流萤"),
                    ("honkai:_star_rail", "崩坏：星穹铁道", "崩坏：星穹铁道"),
                    ("genshin_impact", "原神", "原神"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        class MismatchedIdentityClient:
            def chat_completion(self, provider_config, messages):
                return {
                    "content": json.dumps(
                        {
                            "fields": {
                                "identity_character": ["firefly_(honkai:_star_rail)"],
                                "identity_work": ["genshin_impact"],
                            }
                        }
                    ),
                    "raw": {"id": "identity-mismatch"},
                }

        values, metadata = system.ai_select_tags_for_fields(
            {"identity_character": "", "identity_work": ""},
            db_path=str(db_path),
            provider={"base_url": "https://example.test/v1", "model": "gpt-test"},
            client=MismatchedIdentityClient(),
            field_labels={"identity_character": "角色", "identity_work": "作品"},
            per_field_count=1,
            seed=11,
            freedom=0.8,
            fallback_to_random=False,
        )

    assert "firefly" in values["identity_character"]
    assert "honkai: star rail" in values["identity_work"]
    assert "genshin" not in values["identity_work"]
    assert metadata["identity_pairing"]["corrected_work"]["to"] == "honkai:_star_rail"


def test_ai_coordinated_identity_character_rejects_manual_mismatched_work():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_identity_manual_pair.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                create table danbooru_tags (
                    id integer primary key,
                    name text not null unique,
                    normalized_name text not null default '',
                    category integer,
                    post_count integer not null default 0,
                    semantic_category_key text,
                    taxonomy_id text,
                    is_nsfw integer not null default 0
                );
                create table danbooru_tag_localizations (
                    id integer primary key autoincrement,
                    tag_name text not null,
                    locale text not null default 'zh-CN',
                    label text not null,
                    normalized_label text not null,
                    kind text not null default 'primary'
                );
                """
            )
            conn.executemany(
                """
                insert into danbooru_tags (
                    id, name, normalized_name, category, post_count,
                    semantic_category_key, taxonomy_id, is_nsfw
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, "firefly_(honkai:_star_rail)", "firefly_(honkai:_star_rail)", 4, 9000, "character", "4.character.identity.named_character", 0),
                    (2, "genshin_impact", "genshin_impact", 3, 7000, "copyright", "3.copyright.medium.mobile_gacha", 0),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        class FireflyClient:
            def chat_completion(self, provider_config, messages):
                return {
                    "content": json.dumps({"fields": {"identity_character": ["firefly_(honkai:_star_rail)"]}}),
                    "raw": {"id": "identity-manual-mismatch"},
                }

        values, metadata = system.ai_select_tags_for_fields(
            {"identity_character": "", "identity_work": "genshin impact"},
            db_path=str(db_path),
            provider={"base_url": "https://example.test/v1", "model": "gpt-test"},
            client=FireflyClient(),
            field_labels={"identity_character": "角色", "identity_work": "作品"},
            per_field_count=1,
            seed=12,
            freedom=0.8,
            fallback_to_random=False,
        )

    assert values["identity_character"] == ""
    assert values["identity_work"] == "genshin impact"
    assert metadata["identity_pairing"]["rejected_characters"] == ["firefly_(honkai:_star_rail)"]


def test_ai_coordinated_tag_selection_can_fallback_to_rule_random_when_ai_invalid():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_fallback.db"
        _create_ai_selection_test_db(db_path)

        class InvalidClient:
            def chat_completion(self, provider_config, messages):
                return {
                    "content": json.dumps({"fields": {"category:0": ["missing_tag"]}}),
                    "raw": {"id": "invalid"},
                }

        values, metadata = system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider={"base_url": "https://example.test/v1", "model": "gpt-test"},
            client=InvalidClient(),
            field_labels={"category:0": "测试字段"},
            strategy="只补空字段",
            per_field_count=1,
            seed=5,
            allow_nsfw=False,
            min_post_count=0,
            fallback_to_random=True,
        )

    assert values["category:0"]
    assert "missing_tag" not in values["category:0"]
    assert metadata["fallback_used"] is True
    assert metadata["fallback_items"]["category:0"]
    assert metadata["invalid_selections"]["category:0"] == ["missing_tag"]


def test_ai_intent_directed_tag_selection_sends_intent_and_keeps_natural_language_metadata():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_intent_selection.db"
        _create_ai_selection_test_db(db_path)

        class IntentClient:
            def __init__(self):
                self.payload = {}

            def chat_completion(self, provider_config, messages):
                self.payload = json.loads(messages[1]["content"])
                return {
                    "content": json.dumps(
                        {
                            "fields": {"category:0": ["valid_tag", "invented_tag"]},
                            "natural_language": "A neon rainy alley frames the character with cinematic reflections.",
                            "analysis": {"intent_used": True},
                        }
                    ),
                    "raw": {"id": "intent-select"},
                }

        client = IntentClient()
        values, metadata = system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider={"base_url": "https://example.test/v1", "model": "gpt-test"},
            client=client,
            node_name="GALIAIS-Nodes 测试节点",
            field_labels={"category:0": "测试字段"},
            previous_context="1girl, solo",
            strategy="只补空字段",
            per_field_count=2,
            seed=11,
            freedom=0.85,
            fallback_to_random=False,
            intent_text="赛博夜景、雨中街道、孤独但华丽、电影感",
            intent_detail="完整",
        )

    assert "valid tag (有效标签)" in values["category:0"]
    assert "invented_tag" not in values["category:0"]
    assert client.payload["intent_mode"] is True
    assert client.payload["user_intent"] == "赛博夜景、雨中街道、孤独但华丽、电影感"
    assert client.payload["intent_detail"] == "完整"
    assert "natural_language" in client.payload["response_schema"]
    assert metadata["intent_expansion"]["enabled"] is True
    assert metadata["intent_expansion"]["natural_language"].startswith("A neon rainy alley")
    assert metadata["invalid_selections"]["category:0"] == ["invented_tag"]


def test_ai_tag_selection_rag_context_is_scoped_to_enabled_fields_and_not_a_tag_source():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "ai_rag_selection.db"
        _create_ai_selection_test_db(db_path, total=80)

        class RagClient:
            def __init__(self):
                self.payload = {}

            def chat_completion(self, provider_config, messages):
                self.payload = json.loads(messages[1]["content"])
                candidate_tag = self.payload["fields"][0]["candidates"][0]["tag"]
                rag_tags = [
                    item["tag"]
                    for field in self.payload.get("rag_context", {}).get("fields", [])
                    for item in field.get("references", [])
                ]
                assert rag_tags
                rag_only_tag = rag_tags[0]
                assert rag_only_tag not in {item["tag"] for item in self.payload["fields"][0]["candidates"]}
                assert all(str(item.get("field")) == "category:0" for item in self.payload["rag_context"]["fields"])
                return {
                    "content": json.dumps(
                        {
                            "fields": {"category:0": [candidate_tag, rag_only_tag]},
                            "natural_language": "The selected direction uses a more specific long-tail reference while keeping the tag set locked.",
                            "analysis": {"rag_used": True},
                        }
                    ),
                    "raw": {"id": "rag-select"},
                }

        client = RagClient()
        values, metadata = system.ai_select_tags_for_fields(
            {"category:0": ""},
            db_path=str(db_path),
            provider={"base_url": "https://example.test/v1", "model": "gpt-test"},
            client=client,
            field_labels={"category:0": "测试字段"},
            previous_context="cinematic rainy street",
            strategy="只补空字段",
            per_field_count=1,
            seed=17,
            freedom=0.75,
            fallback_to_random=False,
            intent_text="更具体的长尾候选，不要普通默认词",
            rag_mode="轻量语义",
            rag_candidate_count=8,
            rag_example_count=2,
        )

    assert client.payload["rag_context"]["enabled"] is True
    assert client.payload["rag_context"]["mode"] == "轻量语义"
    assert len(client.payload["rag_context"]["fields"][0]["references"]) <= 8
    assert values["category:0"]
    assert metadata["invalid_selections"]["category:0"]
    assert metadata["rag"]["enabled"] is True
    assert metadata["rag"]["field_reference_counts"]["category:0"] > 0


def test_character_scene_intent_mode_can_write_ai_natural_language_to_note():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]
    db_payload = {"db_path": "E:/fake/runtime.db"}

    def fake_generated_fields(field_values, **kwargs):
        assert kwargs["mode"] == "AI意图定向选择"
        assert kwargs["intent_text"] == "雨夜赛博街区"
        assert kwargs["intent_detail"] == "完整"
        values = dict(field_values)
        values["scene_location"] = "city (城市)"
        values["scene_time_weather"] = "rain (雨)"
        return values, {
            "mode": "AI意图定向选择",
            "intent_expansion": {
                "enabled": True,
                "write_mode": "写入本节点补充",
                "natural_language": "A rainy neon city street stretches behind the character with layered signs and reflective pavement.",
            },
        }

    with patch.object(character, "_apply_generated_fields", side_effect=fake_generated_fields), patch.object(
        character, "optional_danbooru_db_path", return_value="E:/fake/runtime.db"
    ):
        section, text, metadata_json = character.GaliaisNodesCharacterSceneStyle().run(
            "",
            "",
            "",
            "",
            "",
            "manual scene note",
            True,
            1.0,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            "只补空字段",
            1,
            42,
            False,
            0,
            DB=db_payload,
            **{
                "Tag生成模式": "AI意图定向选择",
                "AI意图方向": "雨夜赛博街区",
                "AI扩写强度": "完整",
                "AI是否写入补充": "写入本节点补充",
            },
        )

    assert "city" in text
    assert "rain" in text
    assert "manual scene note" in text
    assert "rainy neon city street" in text
    assert "intent_expansion" in metadata_json
    assert section["random"]["intent_expansion"]["write_mode"] == "写入本节点补充"


def test_character_nodes_expose_ai_coordinated_random_controls():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    inputs = character.GaliaisNodesCharacterBody.INPUT_TYPES()
    composer_inputs = character.GaliaisNodesCharacterComposer.INPUT_TYPES()

    assert inputs["required"]["Tag生成模式"][0] == [
        "规则随机",
        "AI协同选择",
        "AI协同选择+规则兜底",
        "AI意图定向选择",
        "AI意图定向选择+规则兜底",
    ]
    assert "AI自由度" in inputs["required"]
    assert "AI意图方向" in inputs["required"]
    assert "AI扩写强度" in inputs["required"]
    assert "AI是否写入补充" in inputs["required"]
    assert "AI RAG模式" in inputs["required"]
    assert "RAG候选数" in inputs["required"]
    assert "RAG示例数" in inputs["required"]
    assert "AI服务商" in inputs["optional"]
    assert "上游上下文" in inputs["optional"]
    assert "上游提示词段" in inputs["optional"]
    assert "上游角色段" not in inputs["optional"]
    assert "提示词段1" in composer_inputs["optional"]
    assert "提示词段16" in composer_inputs["optional"]
    assert "角色段1" not in composer_inputs["optional"]
    assert "模板名称" not in composer_inputs["required"]
    assert "自定义正面模板" not in composer_inputs["required"]
    assert composer_inputs["optional"]["模板名称"][1]["advanced"] is True
    assert composer_inputs["optional"]["自定义正面模板"][1]["advanced"] is True
    assert composer_inputs["optional"]["模板JSON"][1]["advanced"] is True
    assert character.GaliaisNodesCharacterComposer.RETURN_NAMES == ("正面提示词", "负面提示词", "提示词JSON")


def test_character_prompt_nodes_keep_identity_role_section_but_remove_composer_role_inputs():
    load_package()
    character = sys.modules["galiais_nodes_p0.nodes_galiais_character_prompt"]

    source = (ROOT / "nodes_galiais_character_prompt.py").read_text(encoding="utf-8")
    assert "上游角色段" not in source
    assert "角色段1" not in character.GaliaisNodesCharacterComposer.INPUT_TYPES()["optional"]

    assert character.GaliaisNodesCharacterIdentity.RETURN_NAMES[0] == "角色段"
    composer = character.GaliaisNodesCharacterComposer()
    legacy_section = {
        "enabled": True,
        "name": "legacy",
        "items": [{"tag": "legacy role tag", "weight": 1.0, "source": "manual"}],
    }
    positive, _, _ = composer.run(
        "无",
        "无",
        True,
        "自动",
        "分号",
        "",
        "",
        角色段1=legacy_section,
    )
    assert "legacy role tag" not in positive


def test_frontend_character_composer_can_add_prompt_sections_on_demand():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
for (const name of [
  "const COMPOSER_NODE_NAME = \\"GaliaisNodesCharacterComposer\\"",
  "const COMPOSER_SECTION_PREFIX = \\"提示词段\\"",
  "function promptSectionInputNumber",
  "function syncComposerPromptSectionInputs",
  "function addComposerPromptSectionInput",
  "function autoExtendComposerPromptSections",
  "function installComposerPromptSectionControls",
]) {{
  if (!source.includes(name)) {{
    throw new Error(`${{name}} is missing`);
  }}
}}
if (!source.includes("syncComposerPromptSectionInputs(this, 1)") ||
    !source.includes("nodeType.prototype.onConnectionsChange = function") ||
    !source.includes("autoExtendComposerPromptSections(this)") ||
    !source.includes("node.addInput(name, COMPOSER_SECTION_TYPE)") ||
    !source.includes("node.removeInput(index)") ||
    !source.includes("refreshNodeSize(node, true, {{ fitHeight: true }});")) {{
  throw new Error("Final Composer does not support on-demand prompt section inputs");
}}
if (source.includes("GALIAIS-Nodes: 添加提示词段") || source.includes("GALIAIS-Nodes: 删除最后提示词段")) {{
  throw new Error("Final Composer still relies on right-click prompt section actions");
}}
if (source.includes("角色段1") || source.includes("上游角色段")) {{
  throw new Error("frontend still exposes old role section input wording");
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_character_composer_templates_are_managed_in_button_panel():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
{frontend_source_node_loader()}
for (const name of [
  "const COMPOSER_TEMPLATE_BUTTON_NAME = \\"模板管理\\"",
  "const COMPOSER_TEMPLATE_WIDGET_NAMES = new Set",
  "function ensureComposerTemplateButtonWidget",
  "function openComposerTemplatePanel",
  "function syncComposerTemplatePanelFromWidgets",
  "function applyComposerTemplatePanelToWidgets",
  "function hideComposerTemplateWidgets",
]) {{
  if (!source.includes(name)) {{
    throw new Error(`${{name}} is missing`);
  }}
}}
if (!source.includes("hideComposerTemplateWidgets(this)") ||
    !source.includes("ensureComposerTemplateButtonWidget(this)") ||
    !source.includes("openComposerTemplatePanel(node)") ||
    !source.includes("setWidgetHiddenState(widget, true)") ||
    !source.includes("findWidget(node, \\"模板名称\\")") ||
    !source.includes("findWidget(node, \\"自定义正面模板\\")") ||
    !source.includes("findWidget(node, \\"模板JSON\\")")) {{
  throw new Error("Final Composer template widgets are not hidden behind a management panel");
}}
if (source.includes("GALIAIS-Nodes: 添加提示词段") || source.includes("GALIAIS-Nodes: 删除最后提示词段")) {{
  throw new Error("Final Composer template panel test found obsolete prompt section context menu actions");
}}
"""
    subprocess.run(["node", "-e", script], check=True)


def test_enterprise_nodes_are_registered():
    package = load_package()
    for node in [
        "GaliaisNodesProjectConfig",
        "GaliaisNodesTagBlacklist",
        "GaliaisNodesDanbooruRuntimeDBBuilder",
        "GaliaisNodesAIProviderHealthCheck",
        "GaliaisNodesImageDetailBlueprint",
        "GaliaisNodesSceneDirector",
        "GaliaisNodesPromptOrchestrator",
        "GaliaisNodesPromptProfile",
        "GaliaisNodesTypedComposerV2",
        "GaliaisNodesPromptInspectorV2",
        "GaliaisNodesPromptQualityScore",
        "GaliaisNodesPromptQualityGate",
        "GaliaisNodesDBCacheControl",
        "GaliaisNodesAITagAnalyzer",
        "GaliaisNodesAINaturalPromptWriter",
        "GaliaisNodesAIConflictResolver",
        "GaliaisNodesAIStyleEnhancer",
        "GaliaisNodesAICharacterDetailExpander",
        "GaliaisNodesAINegativePromptBuilder",
        "GaliaisNodesMultiCharacterCoordinator",
        "GaliaisNodesCharacterComposerTemplateManager",
        "GaliaisNodesComposerTemplatePack",
    ]:
        assert node in package.NODE_CLASS_MAPPINGS
        assert node in package.NODE_DISPLAY_NAME_MAPPINGS


def test_runtime_db_builder_node_builds_runtime_database(tmp_path):
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    from test_build_runtime_db import create_source_db

    source = tmp_path / "source.db"
    output = tmp_path / "runtime.db"
    create_source_db(source)

    node = system.GaliaisNodesDanbooruRuntimeDBBuilder()
    runtime_path, source_path, status_json, built = node.run(
        str(source),
        str(output),
        True,
        True,
        True,
        True,
        100,
    )
    status = json.loads(status_json)

    assert built is True
    assert runtime_path == str(output)
    assert source_path == str(source)
    assert status["built"] is True
    assert status["message"] == "运行库构建完成。"
    assert output.exists()

    conn = sqlite3.connect(output)
    try:
        metadata = dict(conn.execute("select key, value from dictionary_metadata"))
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
        assert metadata["runtime_db"] == "1"
        assert "taxonomy_option_cache" in tables
        assert "taxonomy_ai_memory" not in tables
    finally:
        conn.close()


def test_project_config_reads_api_key_from_environment_and_masks_output():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    os.environ["GALIAIS_TEST_KEY"] = "sk-env-secret"
    node = system.GaliaisNodesProjectConfig()

    config, provider, embedding_provider, config_json = node.run(
        "",
        "zh-CN",
        False,
        "Anima",
        True,
        "标准",
        "https://example.test",
        "env:GALIAIS_TEST_KEY",
        "gpt-test",
        "text-embedding-3-large",
        None,
    )

    assert provider["api_key"] == "sk-env-secret"
    assert provider["api_key_source"] == "env:GALIAIS_TEST_KEY"
    assert provider["base_url"] == "https://example.test/v1"
    assert embedding_provider["model"] == "text-embedding-3-large"
    assert embedding_provider["provider_kind"] == "embedding"
    assert config["embedding"]["model"] == "text-embedding-3-large"
    assert "sk-env-secret" not in config_json
    assert config["schema_version"] == system.GALIAIS_NODES_SCHEMA_VERSION


def test_typed_composer_v2_orders_artist_before_subject_and_scores():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    node = system.GaliaisNodesTypedComposerV2()

    positive, negative, metadata, score = node.run(
        "1girl",
        "hatsune miku",
        "vocaloid",
        "ke-ta",
        "slim body",
        "blue eyes",
        "school uniform",
        "standing",
        "classroom",
        "anime style",
        "soft portrait lighting",
        "bad hands",
        "标准",
        True,
        {"allow_nsfw": False},
        None,
        None,
    )

    assert positive.startswith("@ke-ta, 1girl")
    assert "bad hands" in negative
    assert '"artist_before_subject": true' in metadata
    assert '"schema_version":' in metadata
    assert isinstance(score, int)


def test_inspector_v2_and_quality_score_report_duplicates_and_conflicts():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    inspector = system.GaliaisNodesPromptInspectorV2()
    quality = system.GaliaisNodesPromptQualityScore()

    _, _, report_json, score, issue_count, _ = inspector.run(
        "smile, crying, smile",
        False,
        {},
        None,
    )
    quality_score, grade, quality_json = quality.run("smile, crying, smile", False, {}, None)

    assert '"duplicate_tags"' in report_json
    assert '"conflicts"' in report_json
    assert issue_count >= 2
    assert quality_score == score
    assert grade in {"A", "B", "C", "D"}
    assert '"quality_score"' in quality_json


def test_ai_task_nodes_use_mock_client():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]

    class FakeClient:
        def chat_completion(self, provider_config, messages):
            return {"content": "mock output", "raw": {"id": "mock-task"}}

    provider = {"base_url": "https://example.test/v1", "model": "gpt-test"}
    writer = system.GaliaisNodesAINaturalPromptWriter(client=FakeClient())
    text, raw = writer.run(provider, '{"known":[]}', "英文", "精炼")

    assert text == "mock output"
    assert '"id": "mock-task"' in raw


if __name__ == "__main__":
    test_character_section_weight_is_applied()
    test_character_composer_groups_scoped_sections_by_character_slot()
    test_character_composer_keeps_legacy_flat_mode_for_global_sections()
    test_character_composer_can_force_flat_mode_for_scoped_sections()
    test_character_composer_includes_quality_preset_before_artist_and_subject()
    test_character_composer_can_render_custom_template_order()
    test_character_composer_template_store_save_delete_and_export(Path(tempfile.mkdtemp()))
    test_character_node_scope_accepts_new_and_legacy_position_args()
    test_prompt_builder_keeps_lighting_part()
    test_template_renders_dotted_slots_from_coarse_slots()
    test_all_taxonomy_tree_exposes_runtime_taxonomy()
    test_taxonomy_select_parses_selected_tags()
    test_taxonomy_select_can_randomize_tags_from_db()
    test_random_taxonomy_blacklist_filters_random_only()
    test_display_form_with_comma_label_is_parsed_as_one_tag()
    test_character_body_can_randomize_empty_fields_from_db()
    test_character_random_selection_respects_db_blacklist()
    test_random_display_is_cleared_when_manual_fields_block_random_fill()
    test_taxonomy_random_display_is_cleared_when_random_has_no_output()
    test_frontend_random_execution_display_does_not_write_manual_widgets()
    test_frontend_field_enable_controls_are_inline_toggles()
    test_frontend_legacy_canvas_field_toggles_reserve_widget_space()
    test_frontend_input_node_refresh_does_not_grow_multiline_widgets()
    test_frontend_danbooru_selector_passes_tag_blacklist_to_backend()
    test_frontend_tag_generation_mode_callback_uses_existing_layout_refresh()
    test_frontend_danbooru_selector_supports_random_taxonomy_blacklist()
    test_runtime_random_nodes_only_force_refresh_for_auto_seed()
    test_character_body_field_switch_disables_selected_and_random_tags()
    test_character_fixed_fields_cover_all_runtime_taxonomy()
    test_prompt_viewer_returns_ui_preview_and_passthrough()
    test_ai_provider_masks_key_and_builds_config_without_network()
    test_ai_base_url_auto_normalizes_common_openai_endpoints()
    test_ai_http_request_uses_browser_compatible_headers()
    test_cloudflare_1010_error_is_explained_for_ai_provider()
    test_openai_compatible_client_parses_streaming_chat_completion()
    test_openai_compatible_client_can_request_embeddings()
    test_positive_prompt_ai_enricher_appends_natural_language_from_mock_client()
    test_positive_prompt_ai_enricher_marks_empty_ai_response()
    test_positive_prompt_ai_enricher_reports_fallback_error_when_enabled()
    test_positive_prompt_ai_enricher_passes_db_tag_context_to_ai()
    test_positive_prompt_ai_enricher_can_prune_conflicts_before_ai_call()
    test_positive_prompt_ai_enricher_sends_sanitized_generation_plan_to_ai()
    test_positive_prompt_ai_enricher_sends_caption_blueprint_and_strengthens_short_standard_output()
    test_positive_prompt_ai_enricher_full_anima_mode_locks_tags_and_requests_complete_language()
    test_positive_prompt_ai_enricher_repairs_ai_output_that_mentions_dropped_tags()
    test_positive_prompt_ai_context_accepts_display_form_tags()
    test_ai_coordinated_tag_selection_uses_only_candidate_tags_and_context()
    test_ai_coordinated_tag_selection_freedom_expands_candidate_pool()
    test_ai_coordinated_tag_selection_high_freedom_prioritizes_exploratory_candidates()
    test_ai_coordinated_tag_selection_high_freedom_demotes_generic_popular_tags()
    test_ai_coordinated_tag_selection_expands_only_enabled_field_taxonomy()
    test_ai_coordinated_identity_character_work_pairing_autocorrects_mismatched_work()
    test_ai_coordinated_identity_character_rejects_manual_mismatched_work()
    test_ai_coordinated_tag_selection_can_fallback_to_rule_random_when_ai_invalid()
    test_ai_intent_directed_tag_selection_sends_intent_and_keeps_natural_language_metadata()
    test_ai_tag_selection_rag_context_is_scoped_to_enabled_fields_and_not_a_tag_source()
    test_character_scene_intent_mode_can_write_ai_natural_language_to_note()
    test_character_nodes_expose_ai_coordinated_random_controls()
    test_enterprise_nodes_are_registered()
    test_project_config_reads_api_key_from_environment_and_masks_output()
    test_typed_composer_v2_orders_artist_before_subject_and_scores()
    test_inspector_v2_and_quality_score_report_duplicates_and_conflicts()
    test_ai_task_nodes_use_mock_client()
    print("prompt P0 tests passed")
