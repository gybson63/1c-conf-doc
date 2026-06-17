"""CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, cast

import typer
import uvicorn

from onec_conf_doc.config import AppConfig, load_config
from onec_conf_doc.rag.pipeline import IndexStats, Pipeline

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(help="Документация из конфигурации 1С")
configurations_app = typer.Typer(help="Конфигурации в базе данных")
app.add_typer(configurations_app, name="configurations")


def _apply_configuration(cfg: AppConfig, configuration: str | None) -> None:
    if configuration:
        cfg.configuration = configuration


@configurations_app.callback(invoke_without_command=True)
def configurations_list_cmd(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option(help="Путь к config.yaml")] = None,
) -> None:
    """Список конфигураций в базе данных."""
    if ctx.invoked_subcommand is not None:
        return
    cfg = load_config(config)
    pipeline = Pipeline(cfg)
    rows = pipeline.indexer.list_configurations()
    if not rows:
        typer.echo("База пуста. Выполните conf-doc index.")
        raise typer.Exit(code=1)
    for row in rows:
        label = row.synonym or row.name
        active = " *" if cfg.configuration == row.name else ""
        typer.echo(
            f"{row.name}{active}  ({label}, v{row.version}, "
            f"объектов: {row.objects_count}, {row.indexed_at})"
        )
        typer.echo(f"  export: {row.export_path}")


@configurations_app.command("delete")
def configurations_delete_cmd(
    name: str = typer.Argument(..., help="Имя конфигурации"),
    config: Annotated[Path | None, typer.Option(help="Путь к config.yaml")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Без подтверждения")] = False,
    keep_files: Annotated[bool, typer.Option(help="Оставить markdown и FAISS на диске")] = False,
) -> None:
    """Удалить конфигурацию из базы (и с диска, если не указан --keep-files)."""
    cfg = load_config(config)
    pipeline = Pipeline(cfg)
    resolved = pipeline.indexer.resolve_configuration(name)
    if resolved is None:
        from onec_conf_doc.config_names import configuration_not_found_message

        candidates = [c.name for c in pipeline.indexer.list_configurations()]
        typer.echo(configuration_not_found_message(name, candidates), err=True)
        raise typer.Exit(code=1)
    if not yes and not typer.confirm(
        f"Удалить конфигурацию «{resolved.name}» ({resolved.objects_count} объектов)?"
    ):
        raise typer.Abort()
    result = pipeline.delete_configuration(resolved.name, remove_files=not keep_files)
    typer.echo(f"Удалено: {result.name}")
    if not keep_files:
        if result.docs_removed:
            typer.echo("  markdown: удалён")
        if result.vectors_removed:
            typer.echo("  FAISS: удалён")


@app.command("index")
def index_cmd(
    source: Annotated[Path | None, typer.Option(help="Путь к выгрузке конфигурации")] = None,
    output: Annotated[Path | None, typer.Option(help="Каталог результатов")] = None,
    config: Annotated[Path | None, typer.Option(help="Путь к config.yaml")] = None,
    configuration: Annotated[
        str | None, typer.Option(help="Имя конфигурации (обычно берётся из Configuration.xml)")
    ] = None,
    skip_embeddings: Annotated[
        bool, typer.Option(help="Пропустить построение эмбеддингов")
    ] = False,
    force: Annotated[bool, typer.Option(help="Полная пересборка чанков и эмбеддингов")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Без индикатора прогресса")] = False,
) -> None:
    """Индексировать выгрузку конфигурации."""
    cfg = load_config(config)
    if source:
        cfg.source = source
    if output:
        cfg.output = output
    _apply_configuration(cfg, configuration)

    pipeline = Pipeline(cfg)
    stats = pipeline.index_export(
        skip_embeddings=skip_embeddings,
        force=force,
        show_progress=False if quiet else None,
    )
    typer.echo(f"Конфигурация: {stats.configuration_name}")
    if stats.configuration_synonym:
        typer.echo(f"Синоним: {stats.configuration_synonym}")
    typer.echo(f"Объектов обработано: {stats.objects_total}")
    typer.echo(f"Обновлено: {stats.objects_updated}, пропущено: {stats.objects_skipped}")
    if stats.objects_deleted:
        typer.echo(f"Удалено из выгрузки: {stats.objects_deleted}")
    typer.echo(f"Чанков: {stats.chunks_total}")
    if stats.chunks_rebuilt:
        typer.echo(f"Пересобрано объектов (чанки): {stats.chunks_rebuilt}")
    if stats.embeddings_cached or stats.embeddings_computed:
        typer.echo(
            f"Эмбеддинги: из кэша {stats.embeddings_cached}, вычислено {stats.embeddings_computed}"
        )


@app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Поисковый запрос"),
    top_k: int = typer.Option(5, help="Количество результатов"),
    full: bool = typer.Option(False, help="Показать полный текст чанка"),
    configuration: Annotated[str | None, typer.Option(help="Имя конфигурации")] = None,
    config: Annotated[Path | None, typer.Option(help="Путь к config.yaml")] = None,
) -> None:
    """Семантический поиск по индексу."""
    cfg = load_config(config)
    _apply_configuration(cfg, configuration)
    pipeline = Pipeline(cfg)
    active = pipeline.active_configuration
    typer.echo(f"Конфигурация: {active.name} ({active.synonym or active.name})")
    results = pipeline.search(query, top_k=top_k)
    if not results:
        hint = pipeline.embedding_status()
        if hint:
            typer.echo(hint)
        else:
            typer.echo("Результаты не найдены по запросу.")
        raise typer.Exit(code=1)

    for i, hit in enumerate(results, start=1):
        obj_type = hit.get("object_type")
        name = hit.get("name")
        score = hit.get("score")
        typer.echo(f"\n--- {i}. [{obj_type}: {name}] score={score:.4f}")
        text = str(hit.get("text", ""))
        output = text if full else text[:800] + ("..." if len(text) > 800 else "")
        typer.echo(_safe_echo(output))


@app.command("embed")
def embed_cmd(
    configuration: Annotated[str | None, typer.Option(help="Имя конфигурации")] = None,
    config: Annotated[Path | None, typer.Option(help="Путь к config.yaml")] = None,
    force: Annotated[bool, typer.Option(help="Игнорировать кэш, пересчитать все векторы")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Без индикатора прогресса")] = False,
) -> None:
    """Пересобрать эмбеддинги и FAISS-индекс (без повторного парсинга XML)."""
    cfg = load_config(config)
    _apply_configuration(cfg, configuration)
    pipeline = Pipeline(cfg)
    active = pipeline.active_configuration
    typer.echo(f"Конфигурация: {active.name} ({active.synonym or active.name})")
    stats = IndexStats()
    count = pipeline.rebuild_embeddings(
        show_progress=False if quiet else None,
        force=force,
        stats=stats,
    )
    typer.echo(f"Готово: {count} векторов → {cfg.vectors_dir_for(active.name)}")
    if stats.embeddings_cached or stats.embeddings_computed:
        typer.echo(
            f"Эмбеддинги: из кэша {stats.embeddings_cached}, вычислено {stats.embeddings_computed}"
        )


@app.command("show")
def show_cmd(
    name: str = typer.Argument(..., help="Имя объекта метаданных"),
    object_type: str = typer.Option("Document", "--type", "-t", help="Тип объекта"),
    chunk: int | None = typer.Option(None, help="Показать текст чанка по индексу"),
    configuration: Annotated[str | None, typer.Option(help="Имя конфигурации")] = None,
    config: Annotated[Path | None, typer.Option(help="Путь к config.yaml")] = None,
) -> None:
    """Показать записи объекта в SQLite и пути к файлам."""
    cfg = load_config(config)
    _apply_configuration(cfg, configuration)
    pipeline = Pipeline(cfg)
    active = pipeline.active_configuration
    detail = pipeline.indexer.get_object_detail(
        object_type,
        name,
        config_id=active.id,
    )
    if detail is None:
        typer.echo(f"Объект не найден: {active.name} / {object_type}.{name}")
        raise typer.Exit(code=1)

    obj = cast(dict[str, Any], detail["object"])
    typer.echo(f"=== [{obj['configuration_name']}] {obj['object_type']}: {obj['name']} ===")
    typer.echo(f"Синоним: {obj['synonym']}")
    typer.echo(f"UUID: {obj['uuid']}")
    typer.echo(f"XML: {obj['source_xml']}")
    typer.echo(f"Markdown: {obj['md_path']}")
    typer.echo(f"Реквизитов: {detail['attributes_count']}, ТЧ: {detail['tabular_sections_count']}")

    typer.echo("\n--- help_pages ---")
    for page in cast(list[dict[str, Any]], detail["help_pages"]):
        typer.echo(f"  [{page['id']}] {page['title']} ({page['content_len']} симв.)")
        typer.echo(f"       {page['source_path']}")

    typer.echo("\n--- chunks ---")
    for ch in cast(list[dict[str, Any]], detail["chunks"]):
        typer.echo(
            f"  [{ch['chunk_index']}] id={ch['id']} tokens={ch['token_count']} "
            f"len={ch['text_len']} vector_id={ch['vector_id']}"
        )

    if chunk is not None:
        text = pipeline.indexer.get_chunk_text(
            object_type,
            name,
            chunk,
            config_id=active.id,
        )
        if text:
            typer.echo(f"\n--- chunk {chunk} ---")
            typer.echo(_safe_echo(text))


def _safe_echo(text: str) -> str:
    return text.replace("\ufeff", "").strip()


@app.command("mcp")
def mcp_cmd() -> None:
    """Запустить MCP-сервер (stdio) для подключения из Cursor и других MCP-клиентов."""
    try:
        from onec_conf_doc.mcp.server import run_stdio_server
    except ImportError as exc:
        typer.echo(
            'Для MCP установите опциональную зависимость: pip install -e ".[mcp]"',
            err=True,
        )
        raise typer.Exit(code=1) from exc
    run_stdio_server()


@app.command("serve")
def serve_cmd(
    host: Annotated[str | None, typer.Option(help="Host")] = None,
    port: Annotated[int | None, typer.Option(help="Port")] = None,
    config: Annotated[Path | None, typer.Option(help="Путь к config.yaml")] = None,
) -> None:
    """Запустить HTTP API."""
    cfg = load_config(config)
    bind_host = host or cfg.api.host
    bind_port = port or cfg.api.port

    from onec_conf_doc.api.app import create_app

    api_app = create_app(cfg)
    uvicorn.run(api_app, host=bind_host, port=bind_port)


if __name__ == "__main__":
    app()
