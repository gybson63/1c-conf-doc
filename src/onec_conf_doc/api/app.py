"""FastAPI application."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from onec_conf_doc import __version__
from onec_conf_doc.api.jobs import JobStore
from onec_conf_doc.api.logging_buffer import setup_logging
from onec_conf_doc.api.routes import create_router, create_ui_router
from onec_conf_doc.config import AppConfig
from onec_conf_doc.rag.pipeline import Pipeline

if TYPE_CHECKING:
    pass


def _static_dir() -> Path:
    return Path(str(importlib.resources.files("onec_conf_doc.web") / "static"))


def create_app(config: AppConfig, config_path: Path | None = None) -> FastAPI:
    setup_logging()
    pipeline = Pipeline(config)
    app = FastAPI(
        title="1c-conf-doc",
        description="Справочная информация конфигурации 1С и RAG-поиск",
        version=__version__,
    )
    app.state.config = config
    app.state.config_path = config_path
    app.state.pipeline = pipeline
    app.state.jobs = JobStore()

    static_dir = _static_dir()
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(create_router())
    app.include_router(create_ui_router(static_dir))

    return app
