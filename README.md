# GALIAIS-Nodes

GALIAIS-Nodes is a ComfyUI custom node pack for detailed prompt construction.
It focuses on Danbooru tag selection, structured character prompt composition,
AI-assisted prompt refinement, and prompt inspection.

## Features

- Structured character prompt nodes for identity, face, body, outfit, pose, scene, narrative, object, meta, and NSFW layers.
- Danbooru dictionary loader and lazy searchable tag selector.
- Vue DOM and legacy canvas frontend support for per-field enable toggles.
- Optional random tag filling with manual and random selections kept separate.
- OpenAI-compatible AI provider nodes for tag analysis, conflict pruning, natural prompt writing, style enhancement, and negative prompt building.
- Prompt viewer and inspector nodes for checking final output.
- Runtime DB builder, AI health check, scene director, prompt orchestrator, quality gate, multi-character coordinator, and versioned composer template packs.

## Recommended Prompt Flow

| Step | Node | Purpose |
| --- | --- | --- |
| 1 | `GALIAIS-Nodes Danbooru Runtime DB Builder` | Build a compact runtime DB from the full dictionary when the dictionary changes. |
| 2 | `GALIAIS-Nodes Danbooru DB Loader` | Load the DB once and connect its `DB` output into tag/character nodes. |
| 3 | `GALIAIS-Nodes AI Provider` + `AI Provider Health Check` | Configure URL/key/model, optional fast service tier, retries, stream fallback, and verify latency. |
| 4 | `01-10` character nodes | Build identity, face/hair/eyes, body, outfit, pose, scene, narrative, object, meta, and NSFW sections. |
| 5 | `GALIAIS-Nodes Multi Character Coordinator` | Optional: combine per-role sections into a coherent multi-character relation/layout section. |
| 6 | `GALIAIS-Nodes Final Composer` | Compose quality, artist, character sections, custom templates, and negatives. |
| 7 | `GALIAIS-Nodes Scene Director` | Convert selected scene tags into layered foreground/midground/background natural language. |
| 8 | `GALIAIS-Nodes Prompt Orchestrator` | Run conflict pruning, blueprint generation, optional AI expansion, negative prompt merge, and quality score. |
| 9 | `GALIAIS-Nodes Prompt Quality Gate` + `Prompt Viewer` | Review actionable issues and inspect the final positive/negative prompt. |

Reference workflow plan:

```text
docs/workflows/enterprise-character-prompt-workflow.json
```

For chained AI-assisted field selection, connect both outputs from the previous character node:

```text
文本 -> 上游上下文
角色段 -> 上游提示词段
```

## Installation

### Comfy Registry

After the package is published:

```bash
comfy node install galiais-nodes
```

### Manual Install

Clone this repository into your ComfyUI `custom_nodes` directory:

```bash
git clone https://github.com/GALIAIS/GALIAIS-Nodes.git ComfyUI/custom_nodes/GALIAIS-Nodes
```

Restart ComfyUI after installation.

## Danbooru Dictionary

The Danbooru database is not bundled with this node package because it can be very large.
Use the `GALIAIS-Nodes Danbooru DB Loader` node and select your local runtime database.

The text-first database source is maintained separately:

https://github.com/GALIAIS/Danbooru-Tag-Database

## Publishing

This repository contains Comfy Registry metadata in `pyproject.toml`.
Before first publication, verify:

- `project.name` is the final immutable registry node id.
- `[tool.comfy].PublisherId` exactly matches the publisher id shown after `@` on the Comfy Registry profile.
- `[project.urls].Repository` points to the public GitHub repository.
- Optional registry artwork fields such as `Icon` and `Banner` should only be added after stable public image URLs are available.
- Optional license metadata should be added after the project license is decided.

Manual publish:

```bash
comfy node publish
```

GitHub Actions publish:

1. Create a repository secret named `REGISTRY_ACCESS_TOKEN`.
2. Run the `Publish to Comfy registry` workflow manually or push a version tag such as `v1.0.1`.

The workflow intentionally publishes only on `v*` tags, so ordinary commits to
`main` will not push a new registry release.
