"""FastAPI application.

Dev:  uv run uvicorn app.main:app --reload      (frontend: npm run dev in ../frontend)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api import documents, meta, projects, runs
from app.core.config import BACKEND_DIR, Settings
from app.core.db import run_migrations
from app.core.llm.gateway import ModelFactory
from app.core.services import Services
from app.pipeline.checkpointer import open_sqlite_checkpointer
from app.pipeline.executor import RunExecutor
from app.pipeline.graph import build_compile_graph

FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"


def create_app(settings: Settings | None = None, model_factory: ModelFactory | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        if settings.auto_migrate:
            run_migrations(settings.resolved_database_url)
        services = Services.build(settings, model_factory)
        checkpointer, checkpoint_conn = open_sqlite_checkpointer(settings.resolved_checkpoint_path)
        executor = RunExecutor(
            services, build_compile_graph(services, checkpointer), settings.executor_workers
        )
        app.state.services = services
        app.state.executor = executor
        executor.resume_incomplete()
        try:
            yield
        finally:
            executor.shutdown()
            checkpoint_conn.close()
            services.engine.dispose()

    app = FastAPI(title="Policy Compiler", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (meta, projects, documents, runs):
        app.include_router(module.router)

    @app.api_route("/api/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def api_not_found(path: str):
        # Keeps unknown /api URLs a JSON 404 instead of falling through to the SPA's index.html.
        raise HTTPException(404, "Not Found")

    if FRONTEND_DIST.is_dir():
        app.frontend("/", directory=FRONTEND_DIST)  # built UI; in dev, Vite serves it instead
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
