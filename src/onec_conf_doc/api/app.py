"""FastAPI application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from onec_conf_doc.api.routes import create_router
from onec_conf_doc.config import AppConfig
from onec_conf_doc.rag.pipeline import Pipeline

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(config: AppConfig) -> FastAPI:
    from fastapi import FastAPI

    pipeline = Pipeline(config)
    app = FastAPI(
        title="1c-conf-doc",
        description="Справочная информация конфигурации 1С и RAG-поиск",
        version="0.1.0",
    )
    app.state.config = config
    app.state.pipeline = pipeline
    app.include_router(create_router())
    return app
