# GALIAIS-Nodes P0-P2 Refactor And Enterprise Roadmap

**Goal:** Split large files first, then implement P0, P1, and P2 improvements without changing existing ComfyUI node names or saved workflow compatibility unless explicitly required.

**Architecture:** Keep public node modules as stable ComfyUI entrypoints. Move reusable DB, AI, prompt, character composition, and frontend behaviors into focused modules. New features must build on those modules instead of adding more logic to the large entrypoint files.

**Execution Order**

1. Split large files.
2. Verify imports and existing tests after each split.
3. Implement P0 runtime DB, AI health, and image-detail blueprint features.
4. Implement P1 multi-character coordination and prompt quality gate.
5. Implement P2 frontend testing, template packs, docs, and publishing polish.

## Split Boundaries

- `galiais_prompt_core.py`: DB path resolution, tag parsing, blacklist persistence, AI HTTP client, prompt diagnostics, dictionary access, backend routes.
- `nodes_galiais_prompt_system.py`: ComfyUI node classes and registration for system/prompt/AI nodes.
- `galiais_character_core.py`: character section composition, random/AI field filling, composer template storage, scope helpers.
- `nodes_galiais_character_prompt.py`: ComfyUI character node classes and taxonomy field declarations.
- `web/js/galiais_nodes_danbooru_lazy_select.js`: browser extension entrypoint.
- Future frontend modules: selector, field toggles, random display, composer panel, prompt viewer, API helpers.

## P0

- Runtime DB builder integration and loader status showing whether a runtime DB is used.
- AI Provider health monitor with latency, model availability, stream health, fallback count, and last error.
- AI response validation and repair retry for structured JSON modes.
- Full image detail blueprint node and stronger scene/natural-language expansion.
- One-click orchestration node: tags -> conflict pruning -> full expansion -> negative prompt -> quality score -> final output.

## P1

- Multi-character coordinator for per-character identity, clothing, pose, expression, relation, and position.
- Scene director node for background, foreground/midground/depth, lighting, atmosphere, and composition.
- Prompt quality gate with actionable repair suggestions.
- AI request cache and duplicate suppression.

## P2

- Modular frontend files with clear APIs.
- Browser behavior tests for Vue DOM and legacy canvas.
- Template pack import/export and versioned template schema.
- Reference workflow JSON files and README usage matrix.
- Registry release metadata validation.
