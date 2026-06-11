import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


RUNTIME_SCHEMA_VERSION = "1"
RUNTIME_BUILDER = "GALIAIS-Nodes"


def normalize_path(value: str) -> Path:
    path = Path(str(value or "").strip().strip('"')).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    return path


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode = off")
    conn.execute("pragma synchronous = off")
    conn.execute("pragma temp_store = memory")
    conn.execute("pragma cache_size = -262144")
    return conn


def quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def table_exists(conn: sqlite3.Connection, table: str, schema: str = "main") -> bool:
    row = conn.execute(
        f"select 1 from {quote_identifier(schema)}.sqlite_master where type = 'table' and name = ? limit 1",
        (table,),
    ).fetchone()
    return bool(row)


def source_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"pragma src.table_info({quote_identifier(table)})")}


def require_source_tables(conn: sqlite3.Connection) -> None:
    required = ["danbooru_tags", "danbooru_tag_localizations", "tag_taxonomy"]
    missing = [table for table in required if not table_exists(conn, table, "src")]
    if missing:
        raise RuntimeError(f"源数据库缺少必要表: {', '.join(missing)}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def execute_script(conn: sqlite3.Connection, script: str) -> None:
    conn.executescript(script)


def create_core_schema(conn: sqlite3.Connection) -> None:
    execute_script(
        conn,
        """
        create table danbooru_tags (
            id integer primary key,
            name text not null unique,
            normalized_name text not null default '',
            category integer,
            post_count integer not null default 0,
            semantic_category_key text,
            updated_at text not null default '',
            last_synced_at text not null default '',
            taxonomy_id text,
            taxonomy_confidence real,
            is_nsfw integer not null default 0,
            taxonomy_domain text,
            taxonomy_facet text,
            taxonomy_group text,
            taxonomy_leaf text,
            safety_scope text not null default 'unknown'
        );

        create table danbooru_tag_localizations (
            id integer primary key autoincrement,
            tag_name text not null,
            locale text not null default 'zh-CN',
            label text not null,
            normalized_label text not null,
            kind text not null default 'primary',
            source text not null default 'ai',
            confidence real,
            manual integer not null default 0,
            updated_at text not null default '',
            unique(tag_name, locale, normalized_label, kind)
        );

        create table tag_taxonomy (
            id text primary key,
            danbooru_category integer not null,
            domain text not null,
            facet text not null,
            group_key text not null,
            leaf_key text not null,
            label_zh text not null default '',
            label_en text not null default '',
            description text not null default '',
            safety_scope text not null default 'sfw',
            prompt_role text not null default 'positive',
            is_selectable integer not null default 1,
            multi_select integer not null default 0,
            max_select integer not null default 1,
            sort_order integer not null default 0,
            updated_at text not null default '',
            unique(danbooru_category, domain, facet, group_key, leaf_key)
        );

        create table prompt_templates (
            id text primary key,
            name text not null,
            description text not null default '',
            platform text not null default 'a1111',
            positive_template text not null default '',
            negative_template text not null default '',
            is_preset integer not null default 0,
            category text not null default 'general',
            tags text not null default '[]',
            updated_at text not null default ''
        );

        create table dictionary_metadata (
            key text primary key,
            value text not null default '',
            namespace text not null default 'galiais_runtime',
            source text not null default 'runtime_builder',
            created_at text not null,
            updated_at text not null
        );

        create table taxonomy_option_cache (
            taxonomy_id text not null,
            tag_name text not null,
            rank integer not null,
            post_count integer not null default 0,
            is_nsfw integer not null default 0,
            primary key (taxonomy_id, tag_name)
        );

        create table taxonomy_count_cache (
            taxonomy_id text primary key,
            total_count integer not null default 0,
            sfw_count integer not null default 0,
            nsfw_count integer not null default 0
        );
        """,
    )


def create_runtime_indexes(conn: sqlite3.Connection) -> None:
    execute_script(
        conn,
        """
        create index idx_danbooru_tags_normalized_name
            on danbooru_tags(normalized_name);
        create index idx_danbooru_tags_post_count
            on danbooru_tags(post_count desc, name collate nocase asc);
        create index idx_danbooru_tags_taxonomy
            on danbooru_tags(taxonomy_id);
        create index idx_danbooru_tags_taxonomy_post
            on danbooru_tags(taxonomy_id, post_count desc, name collate nocase asc);
        create index idx_danbooru_tags_category_post_count
            on danbooru_tags(category, post_count desc, name collate nocase asc);
        create index idx_danbooru_tags_category_nsfw_post
            on danbooru_tags(category, is_nsfw, post_count desc);
        create index idx_danbooru_tags_semantic_post
            on danbooru_tags(semantic_category_key, is_nsfw, post_count desc);
        create index idx_danbooru_tags_nsfw
            on danbooru_tags(is_nsfw);
        create index idx_danbooru_tags_taxonomy_parts
            on danbooru_tags(taxonomy_domain, taxonomy_facet, taxonomy_group, taxonomy_leaf);

        create index idx_danbooru_tag_localizations_lookup
            on danbooru_tag_localizations(locale, normalized_label, tag_name);
        create index idx_danbooru_tag_localizations_by_tag_locale
            on danbooru_tag_localizations(locale, tag_name, manual, kind, updated_at desc);

        create index idx_dictionary_metadata_namespace
            on dictionary_metadata(namespace, key);
        create index idx_taxonomy_option_cache_rank
            on taxonomy_option_cache(taxonomy_id, rank);
        create index idx_taxonomy_count_cache_total
            on taxonomy_count_cache(total_count desc);
        """,
    )


def copy_core_tables(conn: sqlite3.Connection, include_templates: bool = True) -> dict[str, int]:
    tag_columns = [
        "id",
        "name",
        "normalized_name",
        "category",
        "post_count",
        "semantic_category_key",
        "updated_at",
        "last_synced_at",
        "taxonomy_id",
        "taxonomy_confidence",
        "is_nsfw",
        "taxonomy_domain",
        "taxonomy_facet",
        "taxonomy_group",
        "taxonomy_leaf",
        "safety_scope",
    ]
    source_tag_columns = source_columns(conn, "danbooru_tags")
    select_tag_columns = []
    for column in tag_columns:
        if column in source_tag_columns:
            select_tag_columns.append(column)
        elif column in {"updated_at", "last_synced_at", "safety_scope"}:
            select_tag_columns.append(f"'' as {column}")
        elif column in {"post_count", "is_nsfw"}:
            select_tag_columns.append(f"0 as {column}")
        else:
            select_tag_columns.append(f"null as {column}")
    conn.execute(
        f"""
        insert into danbooru_tags ({", ".join(tag_columns)})
        select {", ".join(select_tag_columns)}
        from src.danbooru_tags
        """
    )

    localization_columns = [
        "tag_name",
        "locale",
        "label",
        "normalized_label",
        "kind",
        "source",
        "confidence",
        "manual",
        "updated_at",
    ]
    source_localization_columns = source_columns(conn, "danbooru_tag_localizations")
    select_localization_columns = []
    for column in localization_columns:
        if column in source_localization_columns:
            select_localization_columns.append(column)
        elif column == "updated_at":
            select_localization_columns.append("'' as updated_at")
        elif column == "manual":
            select_localization_columns.append("0 as manual")
        elif column == "confidence":
            select_localization_columns.append("null as confidence")
        else:
            select_localization_columns.append(f"'' as {column}")
    conn.execute(
        f"""
        insert or ignore into danbooru_tag_localizations ({", ".join(localization_columns)})
        select {", ".join(select_localization_columns)}
        from src.danbooru_tag_localizations
        where tag_name in (select name from danbooru_tags)
        """
    )

    taxonomy_columns = [
        "id",
        "danbooru_category",
        "domain",
        "facet",
        "group_key",
        "leaf_key",
        "label_zh",
        "label_en",
        "description",
        "safety_scope",
        "prompt_role",
        "is_selectable",
        "multi_select",
        "max_select",
        "sort_order",
        "updated_at",
    ]
    source_taxonomy_columns = source_columns(conn, "tag_taxonomy")
    select_taxonomy_columns = []
    for column in taxonomy_columns:
        if column in source_taxonomy_columns:
            select_taxonomy_columns.append(column)
        elif column in {"label_zh", "label_en", "description", "updated_at"}:
            select_taxonomy_columns.append(f"'' as {column}")
        elif column in {"is_selectable", "max_select"}:
            select_taxonomy_columns.append(f"1 as {column}")
        elif column in {"multi_select", "sort_order"}:
            select_taxonomy_columns.append(f"0 as {column}")
        elif column == "safety_scope":
            select_taxonomy_columns.append("'sfw' as safety_scope")
        elif column == "prompt_role":
            select_taxonomy_columns.append("'positive' as prompt_role")
        else:
            select_taxonomy_columns.append(f"'' as {column}")
    conn.execute(
        f"""
        insert or ignore into tag_taxonomy ({", ".join(taxonomy_columns)})
        select {", ".join(select_taxonomy_columns)}
        from src.tag_taxonomy
        """
    )

    if include_templates and table_exists(conn, "prompt_templates", "src"):
        source_template_columns = source_columns(conn, "prompt_templates")
        template_columns = [
            "id",
            "name",
            "description",
            "platform",
            "positive_template",
            "negative_template",
            "is_preset",
            "category",
            "tags",
            "updated_at",
        ]
        select_template_columns = []
        for column in template_columns:
            if column in source_template_columns:
                select_template_columns.append(column)
            elif column == "is_preset":
                select_template_columns.append("0 as is_preset")
            elif column == "tags":
                select_template_columns.append("'[]' as tags")
            else:
                select_template_columns.append(f"'' as {column}")
        conn.execute(
            f"""
            insert or ignore into prompt_templates ({", ".join(template_columns)})
            select {", ".join(select_template_columns)}
            from src.prompt_templates
            """
        )

    if table_exists(conn, "dictionary_metadata", "src"):
        conn.execute(
            """
            insert or ignore into dictionary_metadata (key, value, namespace, source, created_at, updated_at)
            select key, value, namespace, source, created_at, updated_at
            from src.dictionary_metadata
            """
        )

    return {
        "tags": conn.execute("select count(*) from danbooru_tags").fetchone()[0],
        "localizations": conn.execute("select count(*) from danbooru_tag_localizations").fetchone()[0],
        "taxonomy": conn.execute("select count(*) from tag_taxonomy").fetchone()[0],
        "templates": conn.execute("select count(*) from prompt_templates").fetchone()[0],
    }


def create_fts(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            """
            create virtual table danbooru_tag_search_fts using fts5(
                tag_name unindexed,
                normalized_name,
                label,
                normalized_label,
                tokenize='unicode61'
            )
            """
        )
        conn.execute(
            """
            insert into danbooru_tag_search_fts (
                tag_name, normalized_name, label, normalized_label
            )
            select
                t.name,
                t.normalized_name,
                coalesce(group_concat(l.label, ' '), ''),
                coalesce(group_concat(l.normalized_label, ' '), '')
            from danbooru_tags t
            left join danbooru_tag_localizations l
                on l.tag_name = t.name
                and l.kind in ('primary', 'alias')
            group by t.name
            """
        )
        return True
    except sqlite3.DatabaseError:
        conn.execute("drop table if exists danbooru_tag_search_fts")
        return False


def build_option_cache(conn: sqlite3.Connection, limit_per_taxonomy: int) -> int:
    if limit_per_taxonomy <= 0:
        return 0
    taxonomy_ids = [
        row["id"]
        for row in conn.execute(
            """
            select id from tag_taxonomy
            where is_selectable = 1
            order by sort_order asc, id asc
            """
        )
    ]
    inserted = 0
    for taxonomy_id in taxonomy_ids:
        rows = conn.execute(
            """
            select name, post_count, is_nsfw
            from danbooru_tags indexed by idx_danbooru_tags_taxonomy_post
            where taxonomy_id = ?
            order by post_count desc, name collate nocase asc
            limit ?
            """,
            (taxonomy_id, limit_per_taxonomy),
        ).fetchall()
        conn.executemany(
            """
            insert or replace into taxonomy_option_cache (
                taxonomy_id, tag_name, rank, post_count, is_nsfw
            ) values (?, ?, ?, ?, ?)
            """,
            [
                (taxonomy_id, row["name"], index, row["post_count"], row["is_nsfw"])
                for index, row in enumerate(rows)
            ],
        )
        inserted += len(rows)
    return inserted


def build_count_cache(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        insert or replace into taxonomy_count_cache (
            taxonomy_id, total_count, sfw_count, nsfw_count
        )
        select
            tx.id,
            count(t.name) as total_count,
            coalesce(sum(case when coalesce(t.is_nsfw, 0) = 0 then 1 else 0 end), 0) as sfw_count,
            coalesce(sum(case when coalesce(t.is_nsfw, 0) != 0 then 1 else 0 end), 0) as nsfw_count
        from tag_taxonomy tx
        left join danbooru_tags t on t.taxonomy_id = tx.id
        where coalesce(tx.is_selectable, 1) != 0
        group by tx.id
        """
    )
    return conn.execute("select count(*) from taxonomy_count_cache").fetchone()[0]


def write_runtime_metadata(
    conn: sqlite3.Connection,
    *,
    source: Path,
    counts: dict[str, int],
    fts_enabled: bool,
    option_cache_rows: int,
    count_cache_rows: int,
) -> None:
    created = now_iso()
    source_stat = source.stat()
    metadata = {
        "runtime_db": "1",
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "runtime_builder": RUNTIME_BUILDER,
        "runtime_source_path": str(source),
        "runtime_source_size": str(source_stat.st_size),
        "runtime_source_mtime_ns": str(source_stat.st_mtime_ns),
        "runtime_created_at": created,
        "runtime_fts": "1" if fts_enabled else "0",
        "runtime_option_cache_rows": str(option_cache_rows),
        "runtime_count_cache_rows": str(count_cache_rows),
        "runtime_counts_json": json.dumps(counts, ensure_ascii=False, sort_keys=True),
    }
    conn.executemany(
        """
        insert or replace into dictionary_metadata (
            key, value, namespace, source, created_at, updated_at
        ) values (?, ?, 'galiais_runtime', 'runtime_builder', ?, ?)
        """,
        [(key, value, created, created) for key, value in metadata.items()],
    )


def build_runtime_db(
    source: Path,
    output: Path,
    *,
    include_templates: bool = True,
    enable_fts: bool = True,
    option_cache_limit: int = 1000,
) -> dict[str, object]:
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"源数据库不存在: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".building")
    if temp_output.exists():
        temp_output.unlink()

    conn = connect(temp_output)
    try:
        conn.execute(f"attach database ? as src", (str(source),))
        require_source_tables(conn)
        create_core_schema(conn)
        counts = copy_core_tables(conn, include_templates=include_templates)
        create_runtime_indexes(conn)
        option_cache_rows = build_option_cache(conn, option_cache_limit)
        count_cache_rows = build_count_cache(conn)
        fts_enabled = enable_fts and create_fts(conn)
        write_runtime_metadata(
            conn,
            source=source,
            counts=counts,
            fts_enabled=fts_enabled,
            option_cache_rows=option_cache_rows,
            count_cache_rows=count_cache_rows,
        )
        conn.execute("pragma optimize")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if output.exists():
        output.unlink()
    temp_output.replace(output)
    return {
        "source": str(source),
        "output": str(output),
        "output_size": output.stat().st_size,
        "counts": counts,
        "fts_enabled": fts_enabled,
        "option_cache_rows": option_cache_rows,
        "count_cache_rows": count_cache_rows,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a lightweight GALIAIS-Nodes Danbooru runtime database.")
    parser.add_argument("--source", required=True, help="源维护库，例如 danbooru-dictionary.next.db")
    parser.add_argument("--output", required=True, help="输出运行库，例如 danbooru-dictionary.runtime.db")
    parser.add_argument("--no-templates", action="store_true", help="不复制 prompt_templates")
    parser.add_argument("--no-fts", action="store_true", help="不创建 FTS5 搜索表")
    parser.add_argument(
        "--option-cache-limit",
        type=int,
        default=1000,
        help="每个 taxonomy 预计算热门 tag 数量，0 表示关闭",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    result = build_runtime_db(
        normalize_path(args.source),
        normalize_path(args.output),
        include_templates=not args.no_templates,
        enable_fts=not args.no_fts,
        option_cache_limit=max(0, int(args.option_cache_limit)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
