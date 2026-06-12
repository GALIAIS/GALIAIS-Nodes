import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


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
const fs = require("fs");
const source = fs.readFileSync({str(js_path)!r}, "utf8");
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
const fs = require("fs");
const source = fs.readFileSync({str(js_path)!r}, "utf8");
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
"""
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_legacy_canvas_field_toggles_reserve_widget_space():
    js_path = ROOT / "web" / "js" / "galiais_nodes_danbooru_lazy_select.js"
    script = f"""
const fs = require("fs");
const source = fs.readFileSync({str(js_path)!r}, "utf8");
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

    provider, model, models_json, status_json = node.run(
        "https://example.test",
        "sk-test-secret",
        "gpt-test",
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
    assert models_json == "[]"
    assert "sk-test-secret" not in status_json
    assert "sk-t...cret" in status_json


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
    assert "a focused portrait emphasizing blue eyes" in enhanced
    assert natural == "a focused portrait emphasizing blue eyes"
    assert "dominant_taxonomy" in analysis_json
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


def test_enterprise_nodes_are_registered():
    package = load_package()
    for node in [
        "GaliaisNodesProjectConfig",
        "GaliaisNodesPromptProfile",
        "GaliaisNodesTypedComposerV2",
        "GaliaisNodesPromptInspectorV2",
        "GaliaisNodesPromptQualityScore",
        "GaliaisNodesDBCacheControl",
        "GaliaisNodesAITagAnalyzer",
        "GaliaisNodesAINaturalPromptWriter",
        "GaliaisNodesAIConflictResolver",
        "GaliaisNodesAIStyleEnhancer",
        "GaliaisNodesAICharacterDetailExpander",
        "GaliaisNodesAINegativePromptBuilder",
    ]:
        assert node in package.NODE_CLASS_MAPPINGS
        assert node in package.NODE_DISPLAY_NAME_MAPPINGS


def test_project_config_reads_api_key_from_environment_and_masks_output():
    load_package()
    system = sys.modules["galiais_nodes_p0.nodes_galiais_prompt_system"]
    os.environ["GALIAIS_TEST_KEY"] = "sk-env-secret"
    node = system.GaliaisNodesProjectConfig()

    config, provider, config_json = node.run(
        "",
        "zh-CN",
        False,
        "Anima",
        True,
        "标准",
        "https://example.test",
        "env:GALIAIS_TEST_KEY",
        "gpt-test",
        None,
    )

    assert provider["api_key"] == "sk-env-secret"
    assert provider["api_key_source"] == "env:GALIAIS_TEST_KEY"
    assert provider["base_url"] == "https://example.test/v1"
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
    test_character_node_scope_accepts_new_and_legacy_position_args()
    test_prompt_builder_keeps_lighting_part()
    test_template_renders_dotted_slots_from_coarse_slots()
    test_all_taxonomy_tree_exposes_runtime_taxonomy()
    test_taxonomy_select_parses_selected_tags()
    test_taxonomy_select_can_randomize_tags_from_db()
    test_display_form_with_comma_label_is_parsed_as_one_tag()
    test_character_body_can_randomize_empty_fields_from_db()
    test_random_display_is_cleared_when_manual_fields_block_random_fill()
    test_taxonomy_random_display_is_cleared_when_random_has_no_output()
    test_frontend_random_execution_display_does_not_write_manual_widgets()
    test_frontend_field_enable_controls_are_inline_toggles()
    test_frontend_legacy_canvas_field_toggles_reserve_widget_space()
    test_runtime_random_nodes_only_force_refresh_for_auto_seed()
    test_character_body_field_switch_disables_selected_and_random_tags()
    test_character_fixed_fields_cover_all_runtime_taxonomy()
    test_prompt_viewer_returns_ui_preview_and_passthrough()
    test_ai_provider_masks_key_and_builds_config_without_network()
    test_ai_base_url_auto_normalizes_common_openai_endpoints()
    test_ai_http_request_uses_browser_compatible_headers()
    test_cloudflare_1010_error_is_explained_for_ai_provider()
    test_openai_compatible_client_parses_streaming_chat_completion()
    test_positive_prompt_ai_enricher_appends_natural_language_from_mock_client()
    test_positive_prompt_ai_enricher_marks_empty_ai_response()
    test_positive_prompt_ai_enricher_reports_fallback_error_when_enabled()
    test_positive_prompt_ai_enricher_passes_db_tag_context_to_ai()
    test_positive_prompt_ai_enricher_can_prune_conflicts_before_ai_call()
    test_positive_prompt_ai_context_accepts_display_form_tags()
    test_enterprise_nodes_are_registered()
    test_project_config_reads_api_key_from_environment_and_masks_output()
    test_typed_composer_v2_orders_artist_before_subject_and_scores()
    test_inspector_v2_and_quality_score_report_duplicates_and_conflicts()
    test_ai_task_nodes_use_mock_client()
    print("prompt P0 tests passed")
