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
