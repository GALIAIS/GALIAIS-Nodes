try:
    from . import galiais_prompt_core as _galiais_prompt_core
except ImportError:  # direct test import
    import galiais_prompt_core as _galiais_prompt_core

globals().update(
    {
        name: getattr(_galiais_prompt_core, name)
        for name in dir(_galiais_prompt_core)
        if not (name.startswith("__") and name.endswith("__"))
    }
)


def _sync_core_mutable_paths() -> None:
    _galiais_prompt_core.TAG_BLACKLIST_PATH = TAG_BLACKLIST_PATH
    _galiais_prompt_core.RANDOM_TAXONOMY_BLACKLIST_PATH = RANDOM_TAXONOMY_BLACKLIST_PATH


def _default_runtime_output_path(source_path: str) -> str:
    path = Path(normalize_danbooru_db_path(source_path))
    return str(path.with_name(path.stem + ".runtime.db"))


def _read_global_tag_blacklist() -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core._read_global_tag_blacklist()


def _write_global_tag_blacklist(tags) -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core._write_global_tag_blacklist(tags)


def global_tag_blacklist(extra=None) -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core.global_tag_blacklist(extra)


def add_global_tag_blacklist(tags) -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core.add_global_tag_blacklist(tags)


def remove_global_tag_blacklist(tags) -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core.remove_global_tag_blacklist(tags)


def _read_global_random_taxonomy_blacklist() -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core._read_global_random_taxonomy_blacklist()


def _write_global_random_taxonomy_blacklist(items) -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core._write_global_random_taxonomy_blacklist(items)


def global_random_taxonomy_blacklist(extra=None) -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core.global_random_taxonomy_blacklist(extra)


def add_global_random_taxonomy_blacklist(items) -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core.add_global_random_taxonomy_blacklist(items)


def remove_global_random_taxonomy_blacklist(items) -> tuple[str, ...]:
    _sync_core_mutable_paths()
    return _galiais_prompt_core.remove_global_random_taxonomy_blacklist(items)


class GaliaisNodesTagBlacklist:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "黑名单Tags": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "galiais_nodes_danbooru_blacklist": True,
                    },
                ),
                "启用": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("GALIAIS_NODES_TAG_BLACKLIST", "STRING", "STRING", "INT")
    RETURN_NAMES = ("Tag黑名单", "规范化Tags", "元信息JSON", "数量")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/config"

    def run(self, 黑名单Tags, 启用):
        normalized = normalize_tag_blacklist({"text": 黑名单Tags, "enabled": bool(启用)})
        payload = galiais_metadata(
            {
                "enabled": bool(启用),
                "text": str(黑名单Tags or ""),
                "normalized_tags": list(normalized),
                "count": len(normalized),
            }
        )
        return (
            payload,
            ", ".join(normalized),
            _metadata_json(payload),
            len(normalized),
        )


class GaliaisNodesDanbooruDBLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "语言": (["zh-CN"], {"default": "zh-CN"}),
                "启动时验证": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "Tag黑名单": ("GALIAIS_NODES_TAG_BLACKLIST",),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_DANBOORU_DB", "STRING", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("DB", "DB路径", "词典信息JSON", "总词条", "已翻译", "模板数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, DB路径, 语言, 启动时验证, Tag黑名单=None):
        selected_db_path = resolve_danbooru_db_path(DB路径)
        db_path = preferred_danbooru_runtime_path(selected_db_path)
        blacklist_tags = global_tag_blacklist(Tag黑名单)
        payload = {
            "db_path": db_path,
            "selected_db_path": selected_db_path,
            "locale": 语言,
            "auto_runtime": db_path != selected_db_path,
            "tag_blacklist": {
                "enabled": bool(blacklist_tags),
                "normalized_tags": list(blacklist_tags),
                "count": len(blacklist_tags),
            },
        }
        total_tags = 0
        translated_tags = 0
        template_count = 0
        if 启动时验证:
            stats = DanbooruDictionary(db_path, locale=语言).stats()
            payload.update(stats)
            payload["db_path"] = db_path
            payload["selected_db_path"] = selected_db_path
            payload["source_db_path"] = selected_db_path
            payload["auto_runtime"] = db_path != selected_db_path
            total_tags = stats["total_tags"]
            translated_tags = stats["translated_tags"]
            template_count = stats["template_count"]
        return (
            payload,
            db_path,
            _metadata_json(payload),
            total_tags,
            translated_tags,
            template_count,
        )


class GaliaisNodesDanbooruRuntimeDBBuilder:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "源DB路径": ("STRING", {"default": "", "multiline": False}),
                "输出DB路径": ("STRING", {"default": "", "multiline": False}),
                "执行构建": ("BOOLEAN", {"default": False}),
                "覆盖已有": ("BOOLEAN", {"default": False}),
                "复制模板": ("BOOLEAN", {"default": True}),
                "启用FTS搜索": ("BOOLEAN", {"default": True}),
                "每分类缓存Tag数": ("INT", {"default": 1000, "min": 0, "max": 10000}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("运行库DB路径", "源DB路径", "构建状态JSON", "已构建")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/config"

    def run(self, 源DB路径, 输出DB路径, 执行构建, 覆盖已有, 复制模板, 启用FTS搜索, 每分类缓存Tag数):
        source = Path(normalize_danbooru_db_path(源DB路径))
        output_text = str(输出DB路径 or "").strip().strip('"')
        output = Path(output_text) if output_text else Path(_default_runtime_output_path(str(source)))
        if not output.is_absolute():
            output = output.resolve()
        status = {
            "source": str(source),
            "output": str(output),
            "execute": bool(执行构建),
            "overwrite": bool(覆盖已有),
            "include_templates": bool(复制模板),
            "enable_fts": bool(启用FTS搜索),
            "option_cache_limit": max(0, int(每分类缓存Tag数 or 0)),
            "built": False,
        }
        if not 执行构建:
            status["message"] = "未执行构建。打开“执行构建”后运行节点。"
            status["exists"] = output.exists()
            return (str(output), str(source), _metadata_json(galiais_metadata(status)), False)
        if output.exists() and not 覆盖已有:
            status["exists"] = True
            status["message"] = "输出运行库已存在，未覆盖。打开“覆盖已有”后重新运行。"
            return (str(output), str(source), _metadata_json(galiais_metadata(status)), False)
        try:
            try:
                from .build_runtime_db import build_runtime_db
            except ImportError:
                from build_runtime_db import build_runtime_db

            result = build_runtime_db(
                source,
                output,
                include_templates=bool(复制模板),
                enable_fts=bool(启用FTS搜索),
                option_cache_limit=max(0, int(每分类缓存Tag数 or 0)),
            )
            _DANBOORU_RUNTIME_PATH_CACHE.clear()
            status.update(result)
            status["built"] = True
            status["message"] = "运行库构建完成。"
            return (str(output), str(source), _metadata_json(galiais_metadata(status)), True)
        except Exception as exc:
            status["error"] = str(exc)
            status["message"] = "运行库构建失败。"
            return (str(output), str(source), _metadata_json(galiais_metadata(status)), False)


class GaliaisNodesProjectConfig:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "默认语言": (["zh-CN"], {"default": "zh-CN"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "默认输出格式": (["Anima", "通用Danbooru"], {"default": "Anima"}),
                "默认去重": ("BOOLEAN", {"default": True}),
                "默认负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "标准"}),
                "AI服务商URL": ("STRING", {"default": "", "multiline": False}),
                "AI密钥或环境变量": ("STRING", {"default": "", "multiline": False}),
                "AI模型": ("STRING", {"default": "", "multiline": False}),
                "Embedding模型": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
                "Tag黑名单": ("GALIAIS_NODES_TAG_BLACKLIST",),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_PROJECT_CONFIG", "GALIAIS_NODES_AI_PROVIDER", "GALIAIS_NODES_EMBEDDING_PROVIDER", "STRING")
    RETURN_NAMES = ("项目配置", "AI服务商", "Embedding服务商", "配置JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/config"

    def run(self, DB路径, 默认语言, 允许NSFW, 默认输出格式, 默认去重, 默认负面预设, AI服务商URL, AI密钥或环境变量, AI模型, Embedding模型="", DB=None, Tag黑名单=None):
        db_path = optional_danbooru_db_path(DB路径, DB)
        blacklist_tags = normalize_tag_blacklist(Tag黑名单 or DB)
        api_key, key_source = _resolve_api_key(AI密钥或环境变量)
        provider = {
            "base_url": _normalize_openai_base_url(AI服务商URL, "自动"),
            "api_key": api_key,
            "model": str(AI模型 or "").strip(),
            "provider_kind": "llm",
            "api_mode": "自动",
            "timeout": 30,
            "temperature": 0.35,
            "max_tokens": 1200,
            "reasoning_mode": "关闭",
            "reasoning_effort": "medium",
            "service_tier": "auto",
            "stream": False,
            "api_key_source": key_source,
        }
        embedding_provider = {
            "base_url": provider["base_url"],
            "api_key": api_key,
            "model": str(Embedding模型 or "").strip(),
            "provider_kind": "embedding",
            "endpoint": "embeddings",
            "api_mode": "自动",
            "timeout": 30,
            "retry_count": 3,
            "retry_backoff": 0.75,
            "api_key_source": key_source,
        }
        config = galiais_metadata(
            {
                "db_path": db_path,
                "locale": 默认语言,
                "allow_nsfw": bool(允许NSFW),
                "output_format": 默认输出格式,
                "dedupe": bool(默认去重),
                "negative_preset": 默认负面预设,
                "tag_blacklist": {
                    "enabled": bool(blacklist_tags),
                    "normalized_tags": list(blacklist_tags),
                    "count": len(blacklist_tags),
                },
                "ai": {**provider, "api_key": _mask_secret(api_key)},
                "embedding": {**embedding_provider, "api_key": _mask_secret(api_key)},
            }
        )
        return (config, provider, embedding_provider, _metadata_json(config))


class GaliaisNodesDanbooruDictionaryInfo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "DB路径": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("词典信息JSON", "总词条", "已翻译", "模板数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, DB路径, DB=None):
        stats = DanbooruDictionary(resolve_danbooru_db_path(DB路径, DB)).stats()
        return (
            _metadata_json(stats),
            stats["total_tags"],
            stats["translated_tags"],
            stats["template_count"],
        )


class GaliaisNodesDanbooruTagResolver:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "词条": ("STRING", {"default": "", "multiline": True}),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "匹配模式": (["exact", "prefix", "contains"], {"default": "exact"}),
                "保留未匹配": ("BOOLEAN", {"default": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "最低热度": ("INT", {"default": 0, "min": 0, "max": 100000000}),
                "统一权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                "画师加At": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("英文Tags", "中文Labels", "解析JSON", "数量")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 词条, DB路径, 匹配模式, 保留未匹配, 允许NSFW, 最低热度, 统一权重, 画师加At, DB=None):
        dictionary = DanbooruDictionary(resolve_danbooru_db_path(DB路径, DB))
        terms = dictionary.resolve_terms(
            词条,
            match_mode=匹配模式,
            allow_nsfw=允许NSFW,
            keep_unresolved=保留未匹配,
            min_post_count=最低热度,
        )
        tags = []
        labels = []
        for term in terms:
            tag = term.tag
            if 画师加At and (term.category == 1 or term.semantic_category == "artist"):
                tag = "@" + tag.lstrip("@")
            tags.append(apply_tag_weight(tag, 统一权重))
            labels.append(term.label)
        tags = [tag for tag in tags if tag]
        return (
            join_prompt_parts(tags, dedupe=True),
            join_prompt_parts(labels, dedupe=True),
            _metadata_json([term.to_dict() for term in terms]),
            len(terms),
        )


class GaliaisNodesDanbooruQuerySelect:
    CANDIDATE_SLOTS = [f"第{i}项" for i in range(1, 21)]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "查询": ("STRING", {"default": "", "multiline": False}),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "查询语言": (["中英文", "中文", "英文"], {"default": "中英文"}),
                "匹配模式": (["smart", "exact", "prefix", "contains"], {"default": "smart"}),
                "候选序号": (cls.CANDIDATE_SLOTS, {"default": "第1项"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "最低热度": ("INT", {"default": 0, "min": 0, "max": 100000000}),
                "候选数量": ("INT", {"default": 20, "min": 1, "max": 20}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("英文Tag", "中文Label", "选中项", "候选JSON", "候选数量")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 查询, DB路径, 查询语言, 匹配模式, 候选序号, 允许NSFW, 最低热度, 候选数量, DB=None):
        dictionary = DanbooruDictionary(resolve_danbooru_db_path(DB路径, DB))
        terms = dictionary.query_search(
            查询,
            language=查询语言,
            match_mode=匹配模式,
            allow_nsfw=允许NSFW,
            min_post_count=最低热度,
            limit=候选数量,
        )
        if not terms:
            return ("", "", "none", "[]", 0)
        index = min(parse_candidate_index(候选序号), len(terms) - 1)
        selected = terms[index]
        return (
            selected.tag,
            selected.label,
            format_tag_option(selected),
            _metadata_json([term.to_dict() | {"option": format_tag_option(term)} for term in terms]),
            len(terms),
        )


class GaliaisNodesDanbooruTaxonomySelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "TaxonomyID": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "galiais_nodes_danbooru_field": "__taxonomy_id__",
                        "galiais_nodes_danbooru_lazy": True,
                    },
                ),
                "Tags": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "galiais_nodes_danbooru_field": "__selected_taxonomy_tags__",
                        "galiais_nodes_danbooru_lazy": True,
                    },
                ),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "去重": ("BOOLEAN", {"default": True}),
                "统一权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                "启用随机Tag": ("BOOLEAN", {"default": False}),
                "随机数量": ("INT", {"default": 1, "min": 0, "max": 50}),
                "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
                "Tag黑名单": ("GALIAIS_NODES_TAG_BLACKLIST",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return runtime_random_is_changed(
            kwargs.get("启用随机Tag", False),
            kwargs.get("随机数量", 0),
            kwargs.get("随机种子", 0),
        )

    def run(self, TaxonomyID, Tags, DB路径, 允许NSFW, 去重, 统一权重, 启用随机Tag, 随机数量, 随机种子, DB=None, Tag黑名单=None):
        db_path = optional_danbooru_db_path(DB路径, DB)
        blacklist_tags = normalize_tag_blacklist(Tag黑名单 or DB)
        original_tags = str(Tags or "")
        tags = []
        for token in split_tag_option_text(Tags):
            parsed = parse_tag_option(token, db_path=db_path)
            if parsed:
                tags.append(apply_tag_weight(parsed, 统一权重))
        random_items = []
        random_display = []
        if 启用随机Tag and db_path and str(TaxonomyID or "").strip() and int(随机数量 or 0) > 0:
            random_items = DanbooruDictionary(db_path).random_options_for_field(
                "__taxonomy_id__",
                taxonomy_id=str(TaxonomyID or "").strip(),
                count=int(随机数量),
                seed=int(随机种子),
                allow_nsfw=bool(允许NSFW),
                blacklist=blacklist_tags,
            )
            for item in random_items:
                random_display.append(format_tag_display_parts(item.get("tag", ""), item.get("label", "")))
                parsed = parse_tag_option(item.get("option") or item.get("tag") or "", db_path=db_path)
                if parsed:
                    tags.append(apply_tag_weight(parsed, 统一权重))
        text = join_prompt_parts(tags, dedupe=去重)
        random_field_value = join_tag_display_parts(random_display, dedupe=True)
        metadata = {
            "taxonomy_id": str(TaxonomyID or "").strip(),
            "count": len(split_tag_text(text)),
            "allow_nsfw": bool(允许NSFW),
            "dedupe": bool(去重),
            "weight": float(统一权重),
            "random_enabled": bool(启用随机Tag),
            "random_count": int(随机数量),
            "random_seed": int(随机种子),
            "blacklist_count": len(blacklist_tags),
            "random_items": random_items,
            "random_field_values": {"Tags": random_field_value} if random_field_value else {},
            "text": text,
        }
        result = (text, _metadata_json(metadata))
        if random_field_value:
            return {"ui": {"galiais_random_fields": [{"Tags": random_field_value}]}, "result": result}
        if 启用随机Tag:
            return {"ui": {"galiais_random_fields": []}, "result": result}
        return result


def _is_embedding_model_name(model: str) -> bool:
    text = str(model or "").strip().lower()
    if not text:
        return False
    markers = ("embedding", "embed", "bge-", "bge_", "e5-", "e5_", "jina-embeddings", "gte-", "text2vec")
    return any(marker in text for marker in markers)


def _embedding_model_candidates(models) -> list[str]:
    return [str(model) for model in models or [] if _is_embedding_model_name(str(model))]


def _llm_model_candidates(models) -> list[str]:
    return [str(model) for model in models or [] if not _is_embedding_model_name(str(model))]


class GaliaisNodesAIProvider:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "服务商URL": ("STRING", {"default": "", "multiline": False}),
                "API密钥": ("STRING", {"default": "", "multiline": False}),
                "模型": ("STRING", {"default": "", "multiline": False}),
                "Embedding模型": ("STRING", {"default": "", "multiline": False}),
                "接口模式": (["自动", "强制/v1", "保持原样"], {"default": "自动"}),
                "自动获取模型": ("BOOLEAN", {"default": False}),
                "超时秒": ("INT", {"default": 30, "min": 1, "max": 300}),
                "温度": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 2.0, "step": 0.05}),
                "最大Token": ("INT", {"default": 1200, "min": 64, "max": 32768}),
                "思考模式": (["关闭", "开启"], {"default": "关闭"}),
                "思考强度": (["minimal", "low", "medium", "high"], {"default": "medium"}),
                "服务层级": (["auto", "fast"], {"default": "auto"}),
                "流式响应": ("BOOLEAN", {"default": False}),
                "重试次数": ("INT", {"default": 3, "min": 1, "max": 8}),
                "重试退避秒": ("FLOAT", {"default": 0.75, "min": 0.0, "max": 10.0, "step": 0.05}),
                "流式失败降级": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_AI_PROVIDER", "STRING", "STRING", "STRING", "GALIAIS_NODES_EMBEDDING_PROVIDER")
    RETURN_NAMES = ("AI服务商", "模型", "可用模型JSON", "状态JSON", "Embedding服务商")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(
        self,
        服务商URL,
        API密钥,
        模型,
        Embedding模型,
        接口模式,
        自动获取模型,
        超时秒,
        温度,
        最大Token,
        思考模式,
        思考强度,
        服务层级,
        流式响应,
        重试次数=3,
        重试退避秒=0.75,
        流式失败降级=True,
    ):
        provider = {
            "base_url": _normalize_openai_base_url(服务商URL, 接口模式),
            "api_key": str(API密钥 or "").strip(),
            "model": str(模型 or "").strip(),
            "provider_kind": "llm",
            "api_mode": 接口模式,
            "timeout": int(超时秒),
            "temperature": float(温度),
            "max_tokens": int(最大Token),
            "reasoning_mode": 思考模式,
            "reasoning_effort": 思考强度,
            "service_tier": str(服务层级 or "auto").strip() or "auto",
            "stream": bool(流式响应),
            "retry_count": _safe_retry_count(重试次数),
            "retry_backoff": _safe_retry_backoff(重试退避秒),
            "stream_fallback": bool(流式失败降级),
        }
        embedding_provider = {
            "base_url": provider["base_url"],
            "api_key": provider["api_key"],
            "model": str(Embedding模型 or "").strip(),
            "provider_kind": "embedding",
            "endpoint": "embeddings",
            "api_mode": 接口模式,
            "timeout": int(超时秒),
            "retry_count": provider["retry_count"],
            "retry_backoff": provider["retry_backoff"],
        }
        models = []
        llm_models = []
        embedding_models = []
        error = ""
        if 自动获取模型:
            try:
                models = OpenAICompatibleClient().list_models(provider)
                embedding_models = _embedding_model_candidates(models)
                llm_models = _llm_model_candidates(models)
                if not provider["model"] and llm_models:
                    provider["model"] = llm_models[0]
                elif not provider["model"] and models:
                    provider["model"] = models[0]
                if not embedding_provider["model"] and embedding_models:
                    embedding_provider["model"] = embedding_models[0]
            except Exception as exc:
                error = str(exc)
        status = {
            "base_url": provider["base_url"],
            "model": provider["model"],
            "embedding_model": embedding_provider["model"],
            "available_model_count": len(models),
            "available_llm_models": llm_models,
            "available_embedding_models": embedding_models,
            "api_key": _mask_secret(provider["api_key"]),
            "reasoning_mode": provider["reasoning_mode"],
            "reasoning_effort": provider["reasoning_effort"],
            "service_tier": provider["service_tier"],
            "stream": provider["stream"],
            "retry_count": provider["retry_count"],
            "retry_backoff": provider["retry_backoff"],
            "stream_fallback": provider["stream_fallback"],
            "error": error,
        }
        return (provider, provider["model"], _metadata_json(models), _metadata_json(status), embedding_provider)


class GaliaisNodesAIProviderHealthCheck:
    def __init__(self, client=None):
        self.client = client or OpenAICompatibleClient()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "执行检测": ("BOOLEAN", {"default": False}),
                "检测模型列表": ("BOOLEAN", {"default": True}),
                "检测Chat": ("BOOLEAN", {"default": True}),
                "检测流式": ("BOOLEAN", {"default": False}),
                "测试提示词": ("STRING", {"default": "Reply with OK.", "multiline": False}),
            },
        }

    RETURN_TYPES = ("BOOLEAN", "INT", "STRING", "STRING")
    RETURN_NAMES = ("可用", "延迟毫秒", "健康状态JSON", "建议")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 执行检测, 检测模型列表, 检测Chat, 检测流式, 测试提示词):
        provider = dict(AI服务商) if isinstance(AI服务商, dict) else {}
        started = time.perf_counter()
        report = {
            "executed": bool(执行检测),
            "base_url": str(provider.get("base_url") or ""),
            "model": str(provider.get("model") or ""),
            "stream_configured": bool(provider.get("stream", False)),
            "checks": {},
            "errors": [],
            "recommendations": [],
        }
        if not 执行检测:
            report["recommendations"].append("未执行检测。打开“执行检测”后运行节点。")
            return (False, 0, _metadata_json(galiais_metadata(report)), "未执行检测")

        if not provider.get("base_url"):
            report["errors"].append("AI服务商URL为空")
        if not provider.get("model"):
            report["errors"].append("AI模型为空")
        if not provider.get("api_key"):
            report["errors"].append("API密钥为空")
        if report["errors"]:
            report["recommendations"].append("先在 AI Provider 节点填写 URL、密钥和模型。")
            elapsed = int((time.perf_counter() - started) * 1000)
            return (False, elapsed, _metadata_json(galiais_metadata(report)), "配置不完整")

        if 检测模型列表:
            model_start = time.perf_counter()
            try:
                models = self.client.list_models(provider)
                report["checks"]["models"] = {
                    "ok": True,
                    "count": len(models),
                    "latency_ms": int((time.perf_counter() - model_start) * 1000),
                    "current_model_listed": provider.get("model") in models,
                }
            except Exception as exc:
                report["checks"]["models"] = {
                    "ok": False,
                    "latency_ms": int((time.perf_counter() - model_start) * 1000),
                    "error": str(exc),
                }
                report["errors"].append(f"模型列表检测失败: {exc}")

        if 检测Chat:
            chat_start = time.perf_counter()
            try:
                test_provider = dict(provider)
                test_provider["stream"] = False
                response = self.client.chat_completion(
                    test_provider,
                    [
                        {"role": "system", "content": "You are a health check endpoint. Reply briefly."},
                        {"role": "user", "content": str(测试提示词 or "Reply with OK.")},
                    ],
                )
                content = str(response.get("content") or "").strip()
                report["checks"]["chat"] = {
                    "ok": bool(content),
                    "latency_ms": int((time.perf_counter() - chat_start) * 1000),
                    "content_preview": content[:120],
                    "retry": response.get("raw", {}).get("retry", {}),
                }
                if not content:
                    report["errors"].append("Chat 检测返回为空")
            except Exception as exc:
                report["checks"]["chat"] = {
                    "ok": False,
                    "latency_ms": int((time.perf_counter() - chat_start) * 1000),
                    "error": str(exc),
                }
                report["errors"].append(f"Chat 检测失败: {exc}")

        if 检测流式:
            stream_start = time.perf_counter()
            try:
                stream_provider = dict(provider)
                stream_provider["stream"] = True
                stream_provider["stream_fallback"] = False
                response = self.client.chat_completion(
                    stream_provider,
                    [
                        {"role": "system", "content": "You are a streaming health check endpoint. Reply briefly."},
                        {"role": "user", "content": str(测试提示词 or "Reply with OK.")},
                    ],
                )
                content = str(response.get("content") or "").strip()
                report["checks"]["stream"] = {
                    "ok": bool(content),
                    "latency_ms": int((time.perf_counter() - stream_start) * 1000),
                    "content_preview": content[:120],
                    "event_count": response.get("raw", {}).get("event_count", 0),
                }
                if not content:
                    report["errors"].append("流式检测返回为空")
            except Exception as exc:
                report["checks"]["stream"] = {
                    "ok": False,
                    "latency_ms": int((time.perf_counter() - stream_start) * 1000),
                    "error": str(exc),
                }
                report["errors"].append(f"流式检测失败: {exc}")
                report["recommendations"].append("关闭 AI Provider 的“流式响应”，或保持“流式失败降级”开启。")

        elapsed = int((time.perf_counter() - started) * 1000)
        report["latency_ms"] = elapsed
        report["ok"] = not report["errors"]
        if elapsed > 30000:
            report["recommendations"].append("接口延迟超过 30 秒，建议提高超时或切换 fast 服务层级。")
        if not report["recommendations"] and report["ok"]:
            report["recommendations"].append("AI 服务商当前可用。")
        suggestion = "；".join(report["recommendations"][:3])
        return (bool(report["ok"]), elapsed, _metadata_json(galiais_metadata(report)), suggestion)


class GaliaisNodesPositivePromptAIEnricher:
    def __init__(self, client=None):
        self.client = client or OpenAICompatibleClient()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "正面提示词": ("STRING", {"default": "", "multiline": True}),
                "上下文说明": ("STRING", {"default": "", "multiline": True}),
                "输出语言": (["中文", "英文", "中英混合"], {"default": "中文"}),
                "合并模式": (["追加到末尾", "前置自然语言", "仅自然语言", "仅分析不合并"], {"default": "追加到末尾"}),
                "细节强度": (["精炼", "标准", "详细"], {"default": "标准"}),
                "去重": ("BOOLEAN", {"default": True}),
                "失败时返回原文": ("BOOLEAN", {"default": False}),
                "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "启用冲突剔除": ("BOOLEAN", {"default": False}),
                "冲突剔除策略": (["自动", "保留前者", "保留后者"], {"default": "自动"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "扩写模式": (AI_ENRICHMENT_MODES, {"default": "自然语言补充"}),
                "最少句数": ("INT", {"default": 2, "min": 1, "max": 8}),
                "最多句数": ("INT", {"default": 4, "min": 1, "max": 12}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("增强正面提示词", "自然语言补充", "分析JSON", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 正面提示词, 上下文说明, 输出语言, 合并模式, 细节强度, 去重, 失败时返回原文, 随机种子, 启用冲突剔除=False, 冲突剔除策略="自动", 允许NSFW=False, DB=None, 扩写模式="自然语言补充", 最少句数=2, 最多句数=4):
        if isinstance(启用冲突剔除, dict) and DB is None:
            DB = 启用冲突剔除
            启用冲突剔除 = False
            冲突剔除策略 = "自动"
            允许NSFW = False
            扩写模式 = "自然语言补充"
            最少句数 = 2
            最多句数 = 4
        positive = str(正面提示词 or "").strip()
        provider = AI服务商 if isinstance(AI服务商, dict) else {}
        db_path = optional_danbooru_db_path(db=DB)
        selected_mode = str(扩写模式 or "自然语言补充")
        if selected_mode not in AI_ENRICHMENT_MODES:
            selected_mode = "自然语言补充"
        sentence_min, sentence_max = _safe_sentence_range(最少句数, 最多句数, 细节强度)
        diagnostics_before = _diagnose_prompt(positive, db_path=db_path, db=DB, allow_nsfw=bool(允许NSFW))
        prune_payload = {
            "enabled": bool(启用冲突剔除),
            "strategy": str(冲突剔除策略 or "自动"),
            "changed": False,
            "removed": [],
            "decisions": [],
            "prompt": positive,
        }
        ai_positive = positive
        if 启用冲突剔除:
            prune_payload = {
                "enabled": True,
                "strategy": str(冲突剔除策略 or "自动"),
                **_prune_prompt_conflicts(positive, mode=str(冲突剔除策略 or "自动"), db_path=db_path),
            }
            ai_positive = str(prune_payload.get("prompt") or positive).strip()
        generation_plan = _build_ai_generation_plan(
            ai_positive,
            conflict_mode=str(冲突剔除策略 or "自动"),
            db_path=db_path,
            allow_nsfw=bool(允许NSFW),
        )
        ai_generation_prompt = str(generation_plan.get("sanitized_prompt") or ai_positive).strip()
        tag_context = _build_positive_tag_context(ai_generation_prompt, DB)
        caption_blueprint = _build_caption_blueprint(
            generation_plan,
            tag_context,
            language=输出语言,
            detail_level=细节强度,
        )
        scene_design_blueprint = _build_scene_design_blueprint(
            generation_plan,
            tag_context,
            language=输出语言,
            detail_level=细节强度,
        )
        full_image_detail_blueprint = _build_full_image_detail_blueprint(
            generation_plan,
            tag_context,
            language=输出语言,
            detail_level=细节强度,
        )
        generation_plan["caption_blueprint"] = caption_blueprint
        generation_plan["scene_design_blueprint"] = scene_design_blueprint
        generation_plan["full_image_detail_blueprint"] = full_image_detail_blueprint
        if selected_mode == "Tag约束全面扩写":
            generation_plan["natural_language_fallback_blueprint"] = "full_image"
        elif selected_mode == "场景导演描述":
            generation_plan["natural_language_fallback_blueprint"] = "scene"
        else:
            generation_plan["natural_language_fallback_blueprint"] = "caption"
        tag_context["generation_plan"] = generation_plan
        tag_context["caption_blueprint"] = caption_blueprint
        tag_context["scene_design_blueprint"] = scene_design_blueprint
        tag_context["full_image_detail_blueprint"] = full_image_detail_blueprint
        messages = _build_positive_enrichment_messages(
            ai_generation_prompt,
            上下文说明,
            输出语言,
            细节强度,
            tag_context,
            selected_mode,
            sentence_min,
            sentence_max,
        )
        raw_payload = {}
        try:
            response = cached_ai_chat_completion(self.client, provider, messages)
            raw_payload = response.get("raw", {})
            parsed = _extract_json_object(response.get("content", ""))
            natural = str(parsed.get("natural_language") or "").strip()
            analysis = parsed.get("analysis") if isinstance(parsed.get("analysis"), dict) else {}
            if not natural:
                natural = str(response.get("content") or "").strip()
            natural, natural_repaired, natural_leaks = _repair_natural_language_with_plan(
                natural,
                generation_plan,
                输出语言,
            )
            natural, natural_quality_repaired = _strengthen_natural_language_with_blueprint(
                natural,
                generation_plan,
                细节强度,
                输出语言,
            )
            natural_empty = not bool(natural)
            if 合并模式 == "仅自然语言":
                enhanced = natural
            elif 合并模式 == "仅分析不合并":
                enhanced = ai_positive
            elif 合并模式 == "前置自然语言":
                enhanced = join_prompt_parts([natural, ai_positive], dedupe=去重)
            else:
                enhanced = join_prompt_parts([ai_positive, natural], dedupe=去重)
            analysis_payload = {
                "analysis": analysis,
                "added_focus": parsed.get("added_focus", []),
                "language": 输出语言,
                "detail_level": 细节强度,
                "enrichment_mode": selected_mode,
                "sentence_range": {"min": sentence_min, "max": sentence_max},
                "tag_lock": True,
                "seed": int(随机种子),
                "danbooru_context": tag_context,
                "diagnostics_before": diagnostics_before,
                "conflict_pruning_enabled": bool(启用冲突剔除),
                "conflict_pruning": prune_payload,
                "generation_plan": generation_plan,
                "tags_sent_to_ai": ai_generation_prompt,
                "ai_called": True,
                "model": str(provider.get("model") or ""),
                "base_url": str(provider.get("base_url") or ""),
                "locked_tags": ai_generation_prompt,
                "natural_language_empty": natural_empty,
                "natural_language_repaired": natural_repaired,
                "natural_language_leaks": natural_leaks,
                "natural_language_quality_repaired": natural_quality_repaired,
            }
            if natural_empty:
                analysis_payload["warning"] = "AI返回为空，未生成自然语言补充。"
            return (
                enhanced,
                natural,
                _metadata_json(analysis_payload),
                _metadata_json(raw_payload),
            )
        except Exception as exc:
            if not 失败时返回原文:
                raise
            error_payload = {
                "error": str(exc),
                "fallback": True,
                "ai_called": False,
                "model": str(provider.get("model") or ""),
                "base_url": str(provider.get("base_url") or ""),
                "enrichment_mode": selected_mode,
                "sentence_range": {"min": sentence_min, "max": sentence_max},
                "tag_lock": True,
                "locked_tags": ai_generation_prompt,
                "danbooru_context": tag_context,
                "diagnostics_before": diagnostics_before,
                "conflict_pruning_enabled": bool(启用冲突剔除),
                "conflict_pruning": prune_payload,
                "generation_plan": generation_plan,
            }
            return (
                ai_positive if 启用冲突剔除 else positive,
                "",
                _metadata_json(error_payload),
                _metadata_json({**raw_payload, "error": str(exc), "fallback": True}),
            )


class GaliaisNodesImageDetailBlueprint:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "正面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "输出语言": (["中文", "英文", "中英混合"], {"default": "中文"}),
                "细节强度": (["精炼", "标准", "详细"], {"default": "详细"}),
                "启用冲突剔除": ("BOOLEAN", {"default": True}),
                "冲突剔除策略": (["自动", "保留前者", "保留后者"], {"default": "自动"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("完整蓝图JSON", "场景导演描述", "完整自然语言草稿", "诊断JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, 正面提示词, 输出语言, 细节强度, 启用冲突剔除, 冲突剔除策略, 允许NSFW, DB=None):
        positive = str(正面提示词 or "").strip()
        db_path = optional_danbooru_db_path(db=DB)
        prune_payload = {
            "enabled": bool(启用冲突剔除),
            "strategy": str(冲突剔除策略 or "自动"),
            "changed": False,
            "removed": [],
            "decisions": [],
            "prompt": positive,
        }
        blueprint_prompt = positive
        if 启用冲突剔除:
            prune_payload = {
                "enabled": True,
                "strategy": str(冲突剔除策略 or "自动"),
                **_prune_prompt_conflicts(positive, mode=str(冲突剔除策略 or "自动"), db_path=db_path),
            }
            blueprint_prompt = str(prune_payload.get("prompt") or positive).strip()
        generation_plan = _build_ai_generation_plan(
            blueprint_prompt,
            conflict_mode=str(冲突剔除策略 or "自动"),
            db_path=db_path,
            allow_nsfw=bool(允许NSFW),
        )
        tag_context = _build_positive_tag_context(
            str(generation_plan.get("sanitized_prompt") or blueprint_prompt),
            DB,
        )
        caption_blueprint = _build_caption_blueprint(
            generation_plan,
            tag_context,
            language=输出语言,
            detail_level=细节强度,
        )
        scene_blueprint = _build_scene_design_blueprint(
            generation_plan,
            tag_context,
            language=输出语言,
            detail_level=细节强度,
        )
        full_blueprint = _build_full_image_detail_blueprint(
            generation_plan,
            tag_context,
            language=输出语言,
            detail_level=细节强度,
        )
        scene_text = _scene_design_sentence_from_blueprint(scene_blueprint, 输出语言)
        full_text = _full_image_sentence_from_blueprint(full_blueprint, 输出语言)
        diagnostics = _diagnose_prompt(blueprint_prompt, db_path=db_path, db=DB, allow_nsfw=bool(允许NSFW))
        payload = galiais_metadata(
            {
                "source_prompt": positive,
                "blueprint_prompt": blueprint_prompt,
                "language": 输出语言,
                "detail_level": 细节强度,
                "tag_lock": True,
                "conflict_pruning": prune_payload,
                "generation_plan": {
                    **generation_plan,
                    "caption_blueprint": caption_blueprint,
                    "scene_design_blueprint": scene_blueprint,
                    "full_image_detail_blueprint": full_blueprint,
                },
                "danbooru_context": tag_context,
                "caption_blueprint": caption_blueprint,
                "scene_design_blueprint": scene_blueprint,
                "full_image_detail_blueprint": full_blueprint,
            }
        )
        diagnostic_payload = galiais_metadata(
            {
                "diagnostics": diagnostics,
                "conflict_pruning": prune_payload,
                "scene_sentence_count": _natural_language_sentence_count(scene_text),
                "full_sentence_count": _natural_language_sentence_count(full_text),
            }
        )
        return (_metadata_json(payload), scene_text, full_text, _metadata_json(diagnostic_payload))


class GaliaisNodesSceneDirector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "正面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "输出语言": (["中文", "英文", "中英混合"], {"default": "英文"}),
                "细节强度": (["精炼", "标准", "详细"], {"default": "详细"}),
                "启用冲突剔除": ("BOOLEAN", {"default": True}),
                "冲突剔除策略": (["自动", "保留前者", "保留后者"], {"default": "自动"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("场景导演提示词", "场景蓝图JSON", "提示词段文本")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, 正面提示词, 输出语言, 细节强度, 启用冲突剔除, 冲突剔除策略, 允许NSFW, DB=None):
        positive = str(正面提示词 or "").strip()
        db_path = optional_danbooru_db_path(db=DB)
        prompt_for_scene = positive
        pruning = {
            "enabled": bool(启用冲突剔除),
            "strategy": str(冲突剔除策略 or "自动"),
            "changed": False,
            "removed": [],
            "decisions": [],
            "prompt": positive,
        }
        if 启用冲突剔除:
            pruning = {
                "enabled": True,
                "strategy": str(冲突剔除策略 or "自动"),
                **_prune_prompt_conflicts(positive, mode=str(冲突剔除策略 or "自动"), db_path=db_path),
            }
            prompt_for_scene = str(pruning.get("prompt") or positive).strip()
        plan = _build_ai_generation_plan(
            prompt_for_scene,
            conflict_mode=str(冲突剔除策略 or "自动"),
            db_path=db_path,
            allow_nsfw=bool(允许NSFW),
        )
        tag_context = _build_positive_tag_context(str(plan.get("sanitized_prompt") or prompt_for_scene), DB)
        scene_blueprint = _build_scene_design_blueprint(
            plan,
            tag_context,
            language=输出语言,
            detail_level=细节强度,
        )
        scene_prompt = _scene_design_sentence_from_blueprint(scene_blueprint, 输出语言)
        payload = galiais_metadata(
            {
                **scene_blueprint,
                "source_prompt": positive,
                "scene_prompt": scene_prompt,
                "tag_lock": True,
                "language": 输出语言,
                "detail_level": 细节强度,
                "conflict_pruning": pruning,
                "generation_plan": plan,
                "danbooru_context": tag_context,
            }
        )
        return (scene_prompt, _metadata_json(payload), scene_prompt)


class GaliaisNodesPromptOrchestrator:
    def __init__(self, client=None):
        self.client = client or OpenAICompatibleClient()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "正面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面追加": ("STRING", {"default": "", "multiline": True}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "标准"}),
                "输出语言": (["中文", "英文", "中英混合"], {"default": "英文"}),
                "细节强度": (["精炼", "标准", "详细"], {"default": "详细"}),
                "AI扩写模式": (AI_ENRICHMENT_MODES, {"default": "Tag约束全面扩写"}),
                "启用AI扩写": ("BOOLEAN", {"default": True}),
                "启用冲突剔除": ("BOOLEAN", {"default": True}),
                "冲突剔除策略": (["自动", "保留前者", "保留后者"], {"default": "自动"}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "失败时返回原文": ("BOOLEAN", {"default": True}),
                "去重": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("最终正面提示词", "最终负面提示词", "自然语言", "质量评分", "流程JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(
        self,
        AI服务商,
        正面提示词,
        负面追加,
        负面预设,
        输出语言,
        细节强度,
        AI扩写模式,
        启用AI扩写,
        启用冲突剔除,
        冲突剔除策略,
        允许NSFW,
        失败时返回原文,
        去重,
        DB=None,
    ):
        positive = str(正面提示词 or "").strip()
        db_path = optional_danbooru_db_path(db=DB)
        blueprint_node = GaliaisNodesImageDetailBlueprint()
        blueprint_json, scene_text, draft_text, blueprint_diagnostics_json = blueprint_node.run(
            positive,
            输出语言,
            细节强度,
            启用冲突剔除,
            冲突剔除策略,
            允许NSFW,
            DB,
        )
        blueprint_payload = _parse_json_object(blueprint_json, {})
        blueprint_prompt = str(blueprint_payload.get("blueprint_prompt") or positive).strip()
        natural = draft_text
        final_positive = join_prompt_parts([blueprint_prompt, natural], dedupe=去重)
        raw_ai_json = "{}"
        ai_analysis_json = "{}"
        ai_called = False
        if 启用AI扩写:
            enricher = GaliaisNodesPositivePromptAIEnricher(client=self.client)
            final_positive, natural, ai_analysis_json, raw_ai_json = enricher.run(
                AI服务商,
                blueprint_prompt,
                scene_text,
                输出语言,
                "追加到末尾",
                细节强度,
                去重,
                失败时返回原文,
                0,
                False,
                冲突剔除策略,
                允许NSFW,
                DB,
                AI扩写模式,
                3 if 细节强度 != "精炼" else 2,
                8 if 细节强度 == "详细" else 5,
            )
            ai_called = True
        negative = join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS.get(负面预设, ""), 负面追加], dedupe=去重)
        quality_report = _diagnose_prompt(final_positive, db_path=db_path, db=DB, allow_nsfw=bool(允许NSFW))
        score = int(quality_report.get("quality_score", 0))
        flow = galiais_metadata(
            {
                "source_positive": positive,
                "final_positive": final_positive,
                "final_negative": negative,
                "natural_language": natural,
                "ai_called": ai_called,
                "ai_mode": AI扩写模式,
                "language": 输出语言,
                "detail_level": 细节强度,
                "negative_preset": 负面预设,
                "tag_lock": True,
                "blueprint": blueprint_payload,
                "blueprint_diagnostics": _parse_json_object(blueprint_diagnostics_json, {}),
                "ai_analysis": _parse_json_object(ai_analysis_json, {}),
                "ai_raw": _parse_json_object(raw_ai_json, {}),
                "quality": quality_report,
            }
        )
        return (final_positive, negative, natural, score, _metadata_json(flow))


class GaliaisNodesAITagAnalyzer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("分析JSON", "分类摘要", "质量评分")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, 提示词, 允许NSFW, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        report = _diagnose_prompt(
            提示词,
            db_path=config.get("db_path", ""),
            db=DB,
            allow_nsfw=bool(允许NSFW or config.get("allow_nsfw", False)),
        )
        domains = {}
        for item in report.get("known", []):
            taxonomy_id = str(item.get("taxonomy_id") or "")
            parts = taxonomy_id.split(".")
            domain = parts[1] if len(parts) >= 5 else item.get("semantic_category") or "unknown"
            domains.setdefault(domain, []).append(item.get("tag"))
        return (_metadata_json(report), _metadata_json(domains), int(report.get("quality_score", 0)))


class _SimpleAITextNode:
    client_cls = OpenAICompatibleClient

    def __init__(self, client=None):
        self.client = client or self.client_cls()

    def _call(self, provider, task: str, payload: dict) -> tuple[str, str]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional anime image prompt assistant. "
                    "Return concise usable prompt text. Do not include explanations unless requested."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"task": task, **payload}, ensure_ascii=False),
            },
        ]
        response = cached_ai_chat_completion(self.client, provider if isinstance(provider, dict) else {}, messages)
        return (str(response.get("content") or "").strip(), _metadata_json(response.get("raw", {})))


class GaliaisNodesAINaturalPromptWriter(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "Tag分析JSON": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "输出语言": (["中文", "英文", "中英混合"], {"default": "英文"}),
                "细节强度": (["精炼", "标准", "详细"], {"default": "标准"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("自然语言提示词", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, Tag分析JSON, 输出语言, 细节强度):
        text, raw = self._call(
            AI服务商,
            "Write a natural-language positive prompt supplement from analyzed Danbooru tags.",
            {"analysis": _parse_json_object(Tag分析JSON), "language": 输出语言, "detail_level": 细节强度},
        )
        return (text, raw)


class GaliaisNodesAIConflictResolver(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "诊断JSON": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("修正建议", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 提示词, 诊断JSON):
        return self._call(
            AI服务商,
            "Resolve prompt conflicts and return corrected Danbooru tags only.",
            {"prompt": 提示词, "diagnostics": _parse_json_object(诊断JSON)},
        )


class GaliaisNodesAIStyleEnhancer(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "风格方向": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("风格增强提示词", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 提示词, 风格方向):
        return self._call(
            AI服务商,
            "Enhance visual style while preserving the original tags.",
            {"prompt": 提示词, "style_direction": 风格方向},
        )


class GaliaisNodesAICharacterDetailExpander(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "角色基础提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "扩写重点": ("STRING", {"default": "face, hair, body, outfit, pose", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("角色细节扩写", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 角色基础提示词, 扩写重点):
        return self._call(
            AI服务商,
            "Expand a character prompt with concrete visual details.",
            {"character_prompt": 角色基础提示词, "focus": 扩写重点},
        )


class GaliaisNodesAINegativePromptBuilder(_SimpleAITextNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AI服务商": ("GALIAIS_NODES_AI_PROVIDER",),
                "正面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "标准"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("负面提示词", "原始响应JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/ai"

    def run(self, AI服务商, 正面提示词, 负面预设):
        text, raw = self._call(
            AI服务商,
            "Build a negative prompt for this positive prompt. Return comma-separated negative tags.",
            {"positive_prompt": 正面提示词, "base_negative": GALIAIS_NODES_NEGATIVE_PRESETS.get(负面预设, "")},
        )
        return (join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS.get(负面预设, ""), text], dedupe=True), raw)


class GaliaisNodesPromptWeight:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "内容": ("STRING", {"default": "", "multiline": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("加权提示词",)
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 内容, 权重):
        weighted = [apply_tag_weight(tag, 权重) for tag in split_tag_text(内容)]
        return (join_prompt_parts(weighted, dedupe=False),)


class GaliaisNodesPromptSection:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "名称": ("STRING", {"default": "", "multiline": False}),
                "内容": ("STRING", {"default": "", "multiline": True}),
                "启用": ("BOOLEAN", {"default": True}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
            },
            "optional": {
                "前缀": ("STRING", {"default": "", "multiline": False}),
                "后缀": ("STRING", {"default": "", "multiline": False}),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_PROMPT_SECTION", "STRING", "STRING")
    RETURN_NAMES = ("提示词段", "文本", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 名称, 内容, 启用, 权重, 前缀="", 后缀=""):
        if not 启用:
            payload = {"name": 名称, "text": "", "enabled": False, "weight": 权重}
            return (payload, "", _metadata_json(payload))
        text = join_prompt_parts([前缀, 内容, 后缀], dedupe=True)
        if abs(权重 - 1.0) > 0.0001:
            text = join_prompt_parts(
                [apply_tag_weight(tag, 权重) for tag in split_tag_text(text)],
                dedupe=False,
            )
        payload = {"name": 名称, "text": text, "enabled": True, "weight": 权重}
        return (payload, text, _metadata_json(payload))


class GaliaisNodesPromptCombine:
    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            f"段{i}": ("STRING", {"default": "", "multiline": True, "forceInput": True})
            for i in range(1, 11)
        }
        return {
            "required": {
                "去重": ("BOOLEAN", {"default": True}),
                "分隔符": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 去重, 分隔符, **kwargs):
        ordered = [kwargs.get(f"段{i}", "") for i in range(1, 11)]
        prompt = join_prompt_parts(ordered, dedupe=去重, separator=分隔符)
        meta = {"parts": [p for p in ordered if str(p or "").strip()], "dedupe": 去重}
        return (prompt, _metadata_json(meta))


class GaliaisNodesPromptRandomPool:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "候选词条": ("STRING", {"default": "", "multiline": True}),
                "选择数量": ("INT", {"default": 1, "min": 0, "max": 100}),
                "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "允许重复": ("BOOLEAN", {"default": False}),
                "权重": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("随机提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 候选词条, 选择数量, 随机种子, 允许重复, 权重):
        pool = split_tag_text(候选词条)
        rng = random.Random(int(随机种子))
        count = max(0, int(选择数量))
        if not pool or count == 0:
            return ("", _metadata_json({"selected": [], "seed": 随机种子}))
        if 允许重复:
            selected = [rng.choice(pool) for _ in range(count)]
        else:
            selected = rng.sample(pool, min(count, len(pool)))
        weighted = [apply_tag_weight(tag, 权重) for tag in selected]
        return (
            join_prompt_parts(weighted, dedupe=not 允许重复),
            _metadata_json({"selected": selected, "seed": 随机种子}),
        )


class GaliaisNodesNegativePreset:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "无"}),
                "追加内容": ("STRING", {"default": "", "multiline": True}),
                "去重": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("负面提示词",)
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 预设, 追加内容, 去重):
        return (join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS[预设], 追加内容], dedupe=去重),)


class GaliaisNodesPromptTemplate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "模板来源": (["手写", "词典模板ID"], {"default": "手写"}),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "模板ID或名称": ("STRING", {"default": "", "multiline": False}),
                "正面模板": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                    },
                ),
                "负面模板": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "质量": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "主体": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "角色": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "外观": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "服装": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "姿势": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "表情": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "镜头": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "场景": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "光照": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "风格": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "细节": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "自然语言": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 模板来源, DB路径, 模板ID或名称, 正面模板, 负面模板, **slots):
        db = slots.pop("DB", None)
        template_meta = None
        if 模板来源 == "词典模板ID":
            template_meta = DanbooruDictionary(
                resolve_danbooru_db_path(DB路径, db)
            ).template(模板ID或名称)
            if template_meta:
                正面模板 = template_meta.get("positive_template") or 正面模板
                负面模板 = template_meta.get("negative_template") or 负面模板
        positive = join_anima_prompt_parts([render_prompt_template(正面模板, slots)], dedupe=True)
        negative = render_prompt_template(负面模板, slots)
        return (
            positive,
            negative,
            _metadata_json({"template": template_meta, "slots": slots}),
        )


class GaliaisNodesPromptProfile:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "名称": ("STRING", {"default": "", "multiline": False}),
                "角色": ("STRING", {"default": "", "multiline": True}),
                "作品": ("STRING", {"default": "", "multiline": True}),
                "画师": ("STRING", {"default": "", "multiline": False}),
                "主体": ("STRING", {"default": "", "multiline": True}),
                "身体": ("STRING", {"default": "", "multiline": True}),
                "脸发眼": ("STRING", {"default": "", "multiline": True}),
                "服装": ("STRING", {"default": "", "multiline": True}),
                "姿态": ("STRING", {"default": "", "multiline": True}),
                "场景": ("STRING", {"default": "", "multiline": True}),
                "风格": ("STRING", {"default": "", "multiline": True}),
                "自然语言": ("STRING", {"default": "", "multiline": True}),
                "负面": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("GALIAIS_NODES_PROMPT_PROFILE", "STRING")
    RETURN_NAMES = ("提示词档案", "档案JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/profile"

    def run(self, 名称, 角色, 作品, 画师, 主体, 身体, 脸发眼, 服装, 姿态, 场景, 风格, 自然语言, 负面, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        db_path = optional_danbooru_db_path(config.get("db_path", ""), DB)
        profile = galiais_metadata(
            {
                "name": str(名称 or "").strip(),
                "db_path": db_path,
                "sections": {
                    "artist": normalize_artist_tag(画师, db_path=db_path),
                    "subject": 主体,
                    "character": 角色,
                    "copyright": 作品,
                    "body": 身体,
                    "face_hair_eyes": 脸发眼,
                    "outfit": 服装,
                    "pose": 姿态,
                    "scene": 场景,
                    "style": 风格,
                    "natural_language": 自然语言,
                    "negative": 负面,
                },
                "config": config,
            }
        )
        return (profile, _metadata_json(profile))


class GaliaisNodesTypedComposerV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "主体": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "角色": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "作品": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "画师": ("STRING", {"default": "", "multiline": False}),
                "身体": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "脸发眼": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "服装": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "姿态动作": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "场景镜头": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "风格细节": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "自然语言": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "标准"}),
                "去重": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "提示词档案": ("GALIAIS_NODES_PROMPT_PROFILE",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("正面提示词", "负面提示词", "元信息JSON", "质量评分")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 主体, 角色, 作品, 画师, 身体, 脸发眼, 服装, 姿态动作, 场景镜头, 风格细节, 自然语言, 负面, 负面预设, 去重, 项目配置=None, 提示词档案=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        profile = 提示词档案 if isinstance(提示词档案, dict) else {}
        sections = profile.get("sections", {}) if isinstance(profile.get("sections"), dict) else {}
        db_path = optional_danbooru_db_path(config.get("db_path", profile.get("db_path", "")), DB)
        allow_nsfw = bool(config.get("allow_nsfw", False))
        dedupe = bool(去重 if 去重 is not None else config.get("dedupe", True))

        artist = normalize_artist_tag(画师 or sections.get("artist", ""), db_path=db_path)
        positive_parts = [
            artist,
            主体 or sections.get("subject", ""),
            角色 or sections.get("character", ""),
            作品 or sections.get("copyright", ""),
            身体 or sections.get("body", ""),
            脸发眼 or sections.get("face_hair_eyes", ""),
            服装 or sections.get("outfit", ""),
            姿态动作 or sections.get("pose", ""),
            场景镜头 or sections.get("scene", ""),
            风格细节 or sections.get("style", ""),
            自然语言 or sections.get("natural_language", ""),
        ]
        positive = join_anima_prompt_parts(positive_parts, dedupe=dedupe, allow_artist=True, db_path=db_path)
        negative = join_prompt_parts(
            [
                GALIAIS_NODES_NEGATIVE_PRESETS.get(负面预设, ""),
                负面 or sections.get("negative", ""),
            ],
            dedupe=dedupe,
        )
        report = _diagnose_prompt(positive, db_path=db_path, allow_nsfw=allow_nsfw)
        meta = galiais_metadata(
            {
                "ordered_sections": [
                    "artist",
                    "subject",
                    "character",
                    "copyright",
                    "body",
                    "face_hair_eyes",
                    "outfit",
                    "pose",
                    "scene",
                    "style",
                    "natural_language",
                ],
                "artist_before_subject": bool(artist),
                "negative_preset": 负面预设,
                "diagnostics": report,
                "profile_name": profile.get("name", ""),
                "db_path": db_path,
            }
        )
        return (positive, negative, _metadata_json(meta), int(report.get("quality_score", 0)))


class GaliaisNodesPromptBuilder:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "质量预设": (list(GALIAIS_NODES_QUALITY_PRESETS.keys()), {"default": "无"}),
                "主体": ("STRING", {"default": "", "multiline": True}),
                "角色": ("STRING", {"default": "", "multiline": True}),
                "画师": ("STRING", {"default": "", "multiline": False}),
                "外观": ("STRING", {"default": "", "multiline": True}),
                "服装": ("STRING", {"default": "", "multiline": True}),
                "姿势": ("STRING", {"default": "", "multiline": True}),
                "场景": ("STRING", {"default": "", "multiline": True}),
                "光照": ("STRING", {"default": "", "multiline": True}),
                "风格": ("STRING", {"default": "", "multiline": True}),
                "细节": ("STRING", {"default": "", "multiline": True}),
                "负面预设": (list(GALIAIS_NODES_NEGATIVE_PRESETS.keys()), {"default": "无"}),
                "去重": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "额外前缀": ("STRING", {"default": "", "multiline": True}),
                "额外后缀": ("STRING", {"default": "", "multiline": True}),
                "额外负面": ("STRING", {"default": "", "multiline": True}),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(
        self,
        质量预设,
        主体,
        角色,
        画师,
        外观,
        服装,
        姿势,
        场景,
        光照,
        风格,
        细节,
        负面预设,
        去重,
        额外前缀="",
        额外后缀="",
        额外负面="",
        DB=None,
    ):
        db_path = optional_danbooru_db_path(db=DB)
        parts = [
            额外前缀,
            主体,
            角色,
            外观,
            服装,
            姿势,
            场景,
            光照,
            风格,
            细节,
            额外后缀,
        ]
        artist = normalize_artist_tag(画师, db_path=db_path)
        parts = [artist, *parts]
        positive = join_anima_prompt_parts(parts, dedupe=去重, allow_artist=True, db_path=db_path)
        negative = join_prompt_parts([GALIAIS_NODES_NEGATIVE_PRESETS[负面预设], 额外负面], dedupe=去重)
        meta = {
            "quality_preset": 质量预设,
            "quality_omitted_by_anima_template": bool(GALIAIS_NODES_QUALITY_PRESETS[质量预设]),
            "negative_preset": 负面预设,
            "dedupe": 去重,
            "parts": {
                "subject": 主体,
                "character": 角色,
                "artist": artist,
                "artist_inserted_before_subject": bool(artist),
                "appearance": 外观,
                "clothing": 服装,
                "pose": 姿势,
                "scene": 场景,
                "lighting": 光照,
                "style": 风格,
                "detail": 细节,
            },
        }
        return (positive, negative, _metadata_json(meta))


class GaliaisNodesPromptInspector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True}),
                "DB路径": ("STRING", {"default": "", "multiline": False}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("已识别Tags", "未识别", "报告JSON", "已识别数", "未识别数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"

    def run(self, 提示词, DB路径, 允许NSFW, DB=None):
        dictionary = DanbooruDictionary(resolve_danbooru_db_path(DB路径, DB))
        known = []
        unknown = []
        records = []
        for token in split_tag_text(提示词):
            clean = token.strip()
            clean = re.sub(r"^\((.*):[0-9.]+\)$", r"\1", clean)
            clean = clean.lstrip("@")
            matches = dictionary.resolve_terms(
                clean,
                match_mode="exact",
                allow_nsfw=允许NSFW,
                keep_unresolved=False,
            )
            if matches:
                known.append(matches[0].tag)
                records.append(matches[0].to_dict())
            else:
                unknown.append(token)
        known_text = join_prompt_parts(known, dedupe=True)
        unknown_text = join_prompt_parts(unknown, dedupe=True)
        return (
            known_text,
            unknown_text,
            _metadata_json({"known": records, "unknown": unknown}),
            len(known),
            len(unknown),
        )


class GaliaisNodesPromptInspectorV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("已识别Tags", "未识别", "诊断JSON", "质量评分", "问题数", "NSFW数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/diagnostics"

    def run(self, 提示词, 允许NSFW, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        allow_nsfw = bool(允许NSFW or config.get("allow_nsfw", False))
        report = _diagnose_prompt(提示词, db_path=config.get("db_path", ""), db=DB, allow_nsfw=allow_nsfw)
        known = [item.get("tag", "") for item in report.get("known", []) if item.get("tag")]
        unknown = report.get("unknown", [])
        return (
            join_prompt_parts(known, dedupe=True),
            join_prompt_parts(unknown, dedupe=True),
            _metadata_json(report),
            int(report.get("quality_score", 0)),
            len(report.get("issues", [])),
            len(report.get("nsfw_tags", [])),
        )


class GaliaisNodesPromptQualityScore:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "STRING")
    RETURN_NAMES = ("质量评分", "评级", "评分JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/diagnostics"

    def run(self, 提示词, 允许NSFW, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        report = _diagnose_prompt(
            提示词,
            db_path=config.get("db_path", ""),
            db=DB,
            allow_nsfw=bool(允许NSFW or config.get("allow_nsfw", False)),
        )
        score = int(report.get("quality_score", 0))
        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
        payload = galiais_metadata({"score": score, "grade": grade, "diagnostics": report})
        return (score, grade, _metadata_json(payload))


class GaliaisNodesPromptQualityGate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "允许NSFW": ("BOOLEAN", {"default": False}),
                "最低通过分": ("INT", {"default": 80, "min": 0, "max": 100}),
            },
            "optional": {
                "项目配置": ("GALIAIS_NODES_PROJECT_CONFIG",),
                "DB": ("GALIAIS_NODES_DANBOORU_DB",),
            },
        }

    RETURN_TYPES = ("BOOLEAN", "INT", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("通过", "质量评分", "评级", "修复建议", "门禁JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/diagnostics"

    def run(self, 提示词, 允许NSFW, 最低通过分, 项目配置=None, DB=None):
        config = 项目配置 if isinstance(项目配置, dict) else {}
        db_path = config.get("db_path", "")
        allow_nsfw = bool(允许NSFW or config.get("allow_nsfw", False))
        report = _diagnose_prompt(提示词, db_path=db_path, db=DB, allow_nsfw=allow_nsfw)
        score = int(report.get("quality_score", 0))
        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
        suggestions = []
        for issue in report.get("issues", []):
            issue_type = str(issue.get("type") or "")
            if issue_type == "duplicate_tags":
                suggestions.append({
                    "type": "duplicate_tags",
                    "severity": issue.get("severity", "warning"),
                    "message": "删除重复 tag，避免权重和语义重复。",
                    "items": issue.get("items", []),
                })
            elif issue_type == "conflicts":
                suggestions.append({
                    "type": "conflicts",
                    "severity": issue.get("severity", "warning"),
                    "message": "存在互斥 tag，建议保留更符合画面目标的一侧后重新扩写。",
                    "items": issue.get("items", []),
                })
            elif issue_type == "nsfw_in_sfw_prompt":
                suggestions.append({
                    "type": "nsfw_in_sfw_prompt",
                    "severity": "error",
                    "message": "SFW 模式检测到 NSFW tag：开启允许 NSFW，或从正面提示词移除这些 tag。",
                    "items": issue.get("items", []),
                })
            elif issue_type == "unknown_tags":
                suggestions.append({
                    "type": "unknown_tags",
                    "severity": issue.get("severity", "info"),
                    "message": "存在词典未识别内容，建议确认是否是自然语言，或使用 DB 选择器换成标准 tag。",
                    "items": issue.get("items", []),
                })
        completeness = report.get("completeness") if isinstance(report.get("completeness"), dict) else {}
        if not completeness.get("subject") and "1girl" not in str(提示词) and "1boy" not in str(提示词):
            suggestions.append({
                "type": "subject",
                "severity": "warning",
                "message": "缺少明确主体或人数，建议添加 1girl、solo、角色名等主体 tag。",
                "items": [],
            })
        prompt_keys = {normalize_tag_name(token) for token in split_tag_text(提示词)}
        has_scene_depth = bool(prompt_keys & {"detailed_background", "scenery", "indoors", "outdoors"})
        has_simple_conflict = bool(prompt_keys & {"simple_background", "white_background"}) and bool(prompt_keys & {"detailed_background", "scenery"})
        if not completeness.get("scene") or not has_scene_depth or has_simple_conflict:
            suggestions.append({
                "type": "scene_depth",
                "severity": "warning",
                "message": "场景层次不足或背景密度冲突，建议明确地点、前景/中景/背景、光照和环境物件。",
                "items": sorted(prompt_keys & {"simple_background", "white_background", "detailed_background", "scenery", "indoors", "outdoors"}),
            })
        if not completeness.get("pose"):
            suggestions.append({
                "type": "pose_action",
                "severity": "info",
                "message": "动作信息偏弱，建议补充 standing、sitting、looking at viewer、hand pose 等姿态动作。",
                "items": [],
            })
        passed = score >= int(最低通过分 or 0) and not any(item.get("severity") == "error" for item in suggestions)
        suggestion_text = "\n".join(f"- [{item['type']}] {item['message']}" for item in suggestions)
        payload = galiais_metadata(
            {
                "passed": bool(passed),
                "score": score,
                "grade": grade,
                "threshold": int(最低通过分 or 0),
                "suggestions": suggestions,
                "diagnostics": report,
            }
        )
        return (bool(passed), score, grade, suggestion_text, _metadata_json(payload))


class GaliaisNodesDBCacheControl:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "操作": (["查看", "清空"], {"default": "查看"}),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("缓存JSON", "缓存项数")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/config"

    def run(self, 操作):
        if 操作 == "清空":
            _DANBOORU_OPTION_CACHE.clear()
            _DANBOORU_TREE_CACHE.clear()
            _DANBOORU_RUNTIME_PATH_CACHE.clear()
            _TAG_EXISTS_CACHE.clear()
            clear_ai_response_cache()
        counts = {
            "option_cache": len(_DANBOORU_OPTION_CACHE),
            "tree_cache": len(_DANBOORU_TREE_CACHE),
            "runtime_path_cache": len(_DANBOORU_RUNTIME_PATH_CACHE),
            "tag_exists_cache": len(_TAG_EXISTS_CACHE),
            **ai_response_cache_status(),
        }
        return (_metadata_json(galiais_metadata({"operation": 操作, "counts": counts})), sum(counts.values()))


class GaliaisNodesPromptViewer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "正面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "负面提示词": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "元信息JSON": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "标题": ("STRING", {"default": "GALIAIS-Nodes Prompt Output", "multiline": False}),
                "透传输出": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "元信息JSON")
    FUNCTION = "run"
    CATEGORY = "GALIAIS-Nodes/prompt"
    OUTPUT_NODE = True

    def run(self, 正面提示词, 负面提示词, 元信息JSON, 标题, 透传输出):
        positive = str(正面提示词 or "")
        negative = str(负面提示词 or "")
        metadata = str(元信息JSON or "")
        if not 透传输出:
            result = ("", "", "")
        else:
            result = (positive, negative, metadata)
        return {
            "ui": {
                "title": [str(标题 or "GALIAIS-Nodes Prompt Output")],
                "positive": [positive],
                "negative": [negative],
                "metadata": [metadata],
            },
            "result": result,
        }


NODE_CLASS_MAPPINGS = {
    "GaliaisNodesProjectConfig": GaliaisNodesProjectConfig,
    "GaliaisNodesTagBlacklist": GaliaisNodesTagBlacklist,
    "GaliaisNodesDanbooruDBLoader": GaliaisNodesDanbooruDBLoader,
    "GaliaisNodesDanbooruRuntimeDBBuilder": GaliaisNodesDanbooruRuntimeDBBuilder,
    "GaliaisNodesDanbooruDictionaryInfo": GaliaisNodesDanbooruDictionaryInfo,
    "GaliaisNodesDanbooruTagResolver": GaliaisNodesDanbooruTagResolver,
    "GaliaisNodesDanbooruQuerySelect": GaliaisNodesDanbooruQuerySelect,
    "GaliaisNodesDanbooruTaxonomySelect": GaliaisNodesDanbooruTaxonomySelect,
    "GaliaisNodesAIProvider": GaliaisNodesAIProvider,
    "GaliaisNodesAIProviderHealthCheck": GaliaisNodesAIProviderHealthCheck,
    "GaliaisNodesPositivePromptAIEnricher": GaliaisNodesPositivePromptAIEnricher,
    "GaliaisNodesImageDetailBlueprint": GaliaisNodesImageDetailBlueprint,
    "GaliaisNodesSceneDirector": GaliaisNodesSceneDirector,
    "GaliaisNodesPromptOrchestrator": GaliaisNodesPromptOrchestrator,
    "GaliaisNodesAITagAnalyzer": GaliaisNodesAITagAnalyzer,
    "GaliaisNodesAINaturalPromptWriter": GaliaisNodesAINaturalPromptWriter,
    "GaliaisNodesAIConflictResolver": GaliaisNodesAIConflictResolver,
    "GaliaisNodesAIStyleEnhancer": GaliaisNodesAIStyleEnhancer,
    "GaliaisNodesAICharacterDetailExpander": GaliaisNodesAICharacterDetailExpander,
    "GaliaisNodesAINegativePromptBuilder": GaliaisNodesAINegativePromptBuilder,
    "GaliaisNodesPromptWeight": GaliaisNodesPromptWeight,
    "GaliaisNodesPromptSection": GaliaisNodesPromptSection,
    "GaliaisNodesPromptCombine": GaliaisNodesPromptCombine,
    "GaliaisNodesPromptRandomPool": GaliaisNodesPromptRandomPool,
    "GaliaisNodesNegativePreset": GaliaisNodesNegativePreset,
    "GaliaisNodesPromptTemplate": GaliaisNodesPromptTemplate,
    "GaliaisNodesPromptProfile": GaliaisNodesPromptProfile,
    "GaliaisNodesTypedComposerV2": GaliaisNodesTypedComposerV2,
    "GaliaisNodesPromptBuilder": GaliaisNodesPromptBuilder,
    "GaliaisNodesPromptInspector": GaliaisNodesPromptInspector,
    "GaliaisNodesPromptInspectorV2": GaliaisNodesPromptInspectorV2,
    "GaliaisNodesPromptQualityScore": GaliaisNodesPromptQualityScore,
    "GaliaisNodesPromptQualityGate": GaliaisNodesPromptQualityGate,
    "GaliaisNodesDBCacheControl": GaliaisNodesDBCacheControl,
    "GaliaisNodesPromptViewer": GaliaisNodesPromptViewer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GaliaisNodesProjectConfig": "GALIAIS-Nodes Project Config",
    "GaliaisNodesTagBlacklist": "GALIAIS-Nodes Tag Blacklist",
    "GaliaisNodesDanbooruDBLoader": "GALIAIS-Nodes Danbooru DB Loader",
    "GaliaisNodesDanbooruRuntimeDBBuilder": "GALIAIS-Nodes Danbooru Runtime DB Builder",
    "GaliaisNodesDanbooruDictionaryInfo": "GALIAIS-Nodes Danbooru Dictionary Info",
    "GaliaisNodesDanbooruTagResolver": "GALIAIS-Nodes Danbooru Tag Resolver",
    "GaliaisNodesDanbooruQuerySelect": "GALIAIS-Nodes Danbooru Query Select",
    "GaliaisNodesDanbooruTaxonomySelect": "GALIAIS-Nodes Danbooru Taxonomy Select",
    "GaliaisNodesAIProvider": "GALIAIS-Nodes AI Provider",
    "GaliaisNodesAIProviderHealthCheck": "GALIAIS-Nodes AI Provider Health Check",
    "GaliaisNodesPositivePromptAIEnricher": "GALIAIS-Nodes Positive Prompt AI Enricher",
    "GaliaisNodesImageDetailBlueprint": "GALIAIS-Nodes Image Detail Blueprint",
    "GaliaisNodesSceneDirector": "GALIAIS-Nodes Scene Director",
    "GaliaisNodesPromptOrchestrator": "GALIAIS-Nodes Prompt Orchestrator",
    "GaliaisNodesAITagAnalyzer": "GALIAIS-Nodes AI Tag Analyzer",
    "GaliaisNodesAINaturalPromptWriter": "GALIAIS-Nodes AI Natural Prompt Writer",
    "GaliaisNodesAIConflictResolver": "GALIAIS-Nodes AI Conflict Resolver",
    "GaliaisNodesAIStyleEnhancer": "GALIAIS-Nodes AI Style Enhancer",
    "GaliaisNodesAICharacterDetailExpander": "GALIAIS-Nodes AI Character Detail Expander",
    "GaliaisNodesAINegativePromptBuilder": "GALIAIS-Nodes AI Negative Prompt Builder",
    "GaliaisNodesPromptWeight": "GALIAIS-Nodes Prompt Weight",
    "GaliaisNodesPromptSection": "GALIAIS-Nodes Prompt Section",
    "GaliaisNodesPromptCombine": "GALIAIS-Nodes Prompt Combine",
    "GaliaisNodesPromptRandomPool": "GALIAIS-Nodes Prompt Random Pool",
    "GaliaisNodesNegativePreset": "GALIAIS-Nodes Negative Preset",
    "GaliaisNodesPromptTemplate": "GALIAIS-Nodes Prompt Template",
    "GaliaisNodesPromptProfile": "GALIAIS-Nodes Prompt Profile",
    "GaliaisNodesTypedComposerV2": "GALIAIS-Nodes Typed Composer V2",
    "GaliaisNodesPromptBuilder": "GALIAIS-Nodes Prompt Builder",
    "GaliaisNodesPromptInspector": "GALIAIS-Nodes Prompt Inspector",
    "GaliaisNodesPromptInspectorV2": "GALIAIS-Nodes Prompt Inspector V2",
    "GaliaisNodesPromptQualityScore": "GALIAIS-Nodes Prompt Quality Score",
    "GaliaisNodesPromptQualityGate": "GALIAIS-Nodes Prompt Quality Gate",
    "GaliaisNodesDBCacheControl": "GALIAIS-Nodes DB Cache Control",
    "GaliaisNodesPromptViewer": "GALIAIS-Nodes Prompt Viewer",
}
