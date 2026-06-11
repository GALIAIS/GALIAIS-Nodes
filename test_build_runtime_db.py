import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BUILDER = ROOT / "build_runtime_db.py"


def create_source_db(path: Path) -> None:
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
                semantic_category_source text,
                semantic_category_confidence real,
                semantic_category_updated_at text,
                created_at text,
                updated_at text not null,
                last_synced_at text not null,
                taxonomy_id text,
                taxonomy_source text default 'unclassified',
                taxonomy_confidence real,
                is_nsfw integer not null default 0,
                taxonomy_domain text,
                taxonomy_facet text,
                taxonomy_group text,
                taxonomy_leaf text,
                safety_scope text not null default 'unknown',
                rule_candidate_taxonomy_id text,
                rule_candidate_is_nsfw integer,
                rule_candidate_confidence real,
                rule_candidate_reason text,
                rule_candidate_source text,
                rule_candidate_domain text,
                rule_candidate_facet text,
                rule_candidate_group text,
                rule_candidate_leaf text,
                rule_candidate_safety_scope text,
                rule_candidate_updated_at text
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
                created_at text not null,
                updated_at text not null,
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
                created_at text not null,
                updated_at text not null,
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
                created_at text not null,
                updated_at text not null
            );
            create table dictionary_metadata (
                key text primary key,
                value text not null default '',
                namespace text not null default 'shiro_taxonomy_refiner',
                source text not null default 'manual',
                created_at text not null,
                updated_at text not null
            );
            create table taxonomy_ai_memory (tag_name text primary key, payload text);
            create table taxonomy_refinement_audit (tag_name text, payload text);
            """
        )
        tags = [
            (1, "long_hair", "long_hair", 0, 5000, "appearance", "2026", "2026", "0.appearance.hair.length.hair_length", 0, "appearance", "hair", "length", "hair_length", "sfw"),
            (2, "short_hair", "short_hair", 0, 4500, "appearance", "2026", "2026", "0.appearance.hair.length.hair_length", 0, "appearance", "hair", "length", "hair_length", "sfw"),
            (3, "sex", "sex", 0, 4000, "nsfw", "2026", "2026", "0.nsfw.act.penetrative_sex", 1, "nsfw", "act", "act", "penetrative_sex", "explicit"),
        ]
        conn.executemany(
            """
            insert into danbooru_tags (
                id, name, normalized_name, category, post_count, semantic_category_key,
                updated_at, last_synced_at, taxonomy_id, is_nsfw, taxonomy_domain,
                taxonomy_facet, taxonomy_group, taxonomy_leaf, safety_scope
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tags,
        )
        conn.executemany(
            """
            insert into danbooru_tag_localizations (
                tag_name, locale, label, normalized_label, kind, source,
                confidence, manual, created_at, updated_at
            ) values (?, 'zh-CN', ?, ?, 'primary', 'test', 1.0, 1, '2026', '2026')
            """,
            [
                ("long_hair", "长发", "长发"),
                ("short_hair", "短发", "短发"),
                ("sex", "性交", "性交"),
            ],
        )
        conn.executemany(
            """
            insert into tag_taxonomy (
                id, danbooru_category, domain, facet, group_key, leaf_key,
                label_zh, label_en, description, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, '2026', '2026')
            """,
            [
                ("0.appearance.hair.length.hair_length", 0, "appearance", "hair", "length", "hair_length", "头发长度", "Hair Length", "",),
                ("0.nsfw.act.penetrative_sex", 0, "nsfw", "act", "act", "penetrative_sex", "插入性行为", "Penetrative Sex", "",),
            ],
        )
        conn.execute(
            """
            insert into prompt_templates (
                id, name, positive_template, negative_template, created_at, updated_at
            ) values ('anima', 'Anima', '{{core}}', 'bad', '2026', '2026')
            """
        )
        conn.execute(
            """
            insert into dictionary_metadata (key, value, created_at, updated_at)
            values ('整理者', 'GALIAIS', '2026', '2026')
            """
        )
        conn.execute("insert into taxonomy_ai_memory values ('long_hair', '{}')")
        conn.execute("insert into taxonomy_refinement_audit values ('long_hair', '{}')")
        conn.commit()
    finally:
        conn.close()


def test_builder_creates_runtime_only_database() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "source.db"
        output = temp / "runtime.db"
        create_source_db(source)

        subprocess.run(
            [
                sys.executable,
                str(BUILDER),
                "--source",
                str(source),
                "--output",
                str(output),
                "--option-cache-limit",
                "2",
            ],
            check=True,
        )

        conn = sqlite3.connect(output)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "select name from sqlite_master where type in ('table', 'virtual')"
                )
            }
            assert "danbooru_tags" in tables
            assert "danbooru_tag_localizations" in tables
            assert "tag_taxonomy" in tables
            assert "danbooru_tag_search_fts" in tables
            assert "taxonomy_option_cache" in tables
            assert "taxonomy_count_cache" in tables
            assert "taxonomy_ai_memory" not in tables
            assert "taxonomy_refinement_audit" not in tables

            metadata = dict(conn.execute("select key, value from dictionary_metadata"))
            assert metadata["runtime_db"] == "1"
            assert metadata["runtime_builder"] == "GALIAIS-Nodes"

            cached = conn.execute(
                """
                select tag_name
                from taxonomy_option_cache
                where taxonomy_id = '0.appearance.hair.length.hair_length'
                order by rank asc
                """
            ).fetchall()
            assert [row[0] for row in cached] == ["long_hair", "short_hair"]

            count_cache = conn.execute(
                """
                select total_count, sfw_count, nsfw_count
                from taxonomy_count_cache
                where taxonomy_id = '0.appearance.hair.length.hair_length'
                """
            ).fetchone()
            assert count_cache == (2, 2, 0)

            nsfw_count_cache = conn.execute(
                """
                select total_count, sfw_count, nsfw_count
                from taxonomy_count_cache
                where taxonomy_id = '0.nsfw.act.penetrative_sex'
                """
            ).fetchone()
            assert nsfw_count_cache == (1, 0, 1)

            fts = conn.execute(
                """
                select tag_name
                from danbooru_tag_search_fts
                where danbooru_tag_search_fts match ?
                """,
                ("长发",),
            ).fetchall()
            assert [row[0] for row in fts] == ["long_hair"]
        finally:
            conn.close()


if __name__ == "__main__":
    test_builder_creates_runtime_only_database()
    print("runtime db builder test passed")
