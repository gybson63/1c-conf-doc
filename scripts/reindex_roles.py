"""Reindex only Role objects (markdown, chunks, embeddings)."""

from __future__ import annotations

import sys

from onec_conf_doc.config import load_config
from onec_conf_doc.markdown.generator import write_markdown
from onec_conf_doc.parser.scanner import scan_export
from onec_conf_doc.parser.xml_parser import parse_metadata_file
from onec_conf_doc.rag.pipeline import Pipeline


def main() -> int:
    cfg = load_config()
    pipeline = Pipeline(cfg)
    stored = pipeline.resolve_active_configuration()
    config_id = stored.id
    source = cfg.source
    docs_dir = cfg.docs_dir_for(stored.name)

    updated_object_ids: list[int] = []
    refs = [ref for ref in scan_export(source) if ref.object_type == "Role"]
    print(f"Roles to process: {len(refs)}", flush=True)

    for ref in refs:
        obj = parse_metadata_file(ref.path, ref.object_type, source_root=source)
        md_path = write_markdown(
            obj,
            docs_dir,
            configuration_name=stored.name,
            configuration_synonym=stored.synonym,
        )
        object_id = pipeline.indexer.upsert_object(config_id, obj, md_path)
        updated_object_ids.append(object_id)

    chunks_rebuilt = pipeline._build_chunks_incremental(  # noqa: SLF001
        config_id,
        updated_object_ids,
        show_progress=True,
        full=False,
    )
    print(
        f"Done: roles={len(updated_object_ids)}, chunks_rebuilt={chunks_rebuilt} "
        "(embeddings skipped for Role)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
