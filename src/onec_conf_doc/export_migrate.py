"""Migrate legacy export paths into per-configuration slots."""

from __future__ import annotations

from dataclasses import dataclass

from onec_conf_doc.config import AppConfig
from onec_conf_doc.export_slot import (
    export_dir_for,
    migrate_export_to_slot,
    needs_export_migration,
)
from onec_conf_doc.rag.pipeline import Pipeline


@dataclass
class ExportMigrationResult:
    name: str
    old_path: str
    new_path: str | None
    migrated: bool
    message: str


def migrate_configuration_exports(
    config: AppConfig,
    pipeline: Pipeline,
) -> list[ExportMigrationResult]:
    results: list[ExportMigrationResult] = []
    for row in pipeline.indexer.list_configurations():
        canonical = export_dir_for(config, row.name)
        if not needs_export_migration(row.export_path, canonical):
            results.append(
                ExportMigrationResult(
                    name=row.name,
                    old_path=row.export_path,
                    new_path=str(canonical),
                    migrated=False,
                    message="already in slot",
                )
            )
            continue
        new_path = migrate_export_to_slot(config, row.name, row.export_path)
        if new_path is None:
            results.append(
                ExportMigrationResult(
                    name=row.name,
                    old_path=row.export_path,
                    new_path=None,
                    migrated=False,
                    message="source missing or empty",
                )
            )
            continue
        pipeline.indexer.update_export_path(row.id, str(new_path))
        results.append(
            ExportMigrationResult(
                name=row.name,
                old_path=row.export_path,
                new_path=str(new_path),
                migrated=True,
                message="copied to slot",
            )
        )
    return results
