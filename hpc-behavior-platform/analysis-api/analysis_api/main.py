"""FastAPI app wiring: session store, Redis stage cache, ClickHouse client.

Test code overrides app.state.session_store / app.state.stage_cache /
app.state.clickhouse_client directly (or via dependency_overrides) rather
than requiring live Redis/ClickHouse instances.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis

from analysis_api.cache import RedisStageCache
from analysis_api.routers import inter, intra, jobs, raw, session
from analysis_api.session import SessionStore
from tensor_store.loader import get_client


def create_app() -> FastAPI:
    app = FastAPI(title="HPC Behavior Platform Analysis API")

    # behavior-ui (Phase 6) is a separate origin (Vite dev server / static
    # host) calling this API directly from the browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.session_store = SessionStore()
    app.state.stage_cache = RedisStageCache(
        Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", "6380")),  # 6379 conflicts with an unrelated host service
        )
    )
    app.state.clickhouse_client = get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        password=os.environ.get("CLICKHOUSE_PASSWORD", "devpass"),
    )

    app.include_router(session.router)
    app.include_router(inter.router)
    app.include_router(intra.router)
    app.include_router(raw.router)
    app.include_router(jobs.router)

    return app


app = create_app()
