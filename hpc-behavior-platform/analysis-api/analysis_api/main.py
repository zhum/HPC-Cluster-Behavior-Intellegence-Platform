"""FastAPI app wiring: session store, Redis stage cache, ClickHouse client.

Test code overrides app.state.session_store / app.state.stage_cache /
app.state.clickhouse_client directly (or via dependency_overrides) rather
than requiring live Redis/ClickHouse instances.

clickhouse_connect.get_client connects (and pings) on construction, so the
client is built in the lifespan -- at server startup, not at import or in
create_app() -- and only if a test hasn't already put one on app.state.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis

from analysis_api.cache import RedisStageCache
from analysis_api.routers import analyses, inter, intra, jobs, raw, session
from analysis_api.saved_analyses import SavedAnalysesStore
from analysis_api.session import SessionStore
from tensor_store.loader import get_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "clickhouse_client", None) is None:
        app.state.clickhouse_client = get_client(
            host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
            port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
            password=os.environ.get("CLICKHOUSE_PASSWORD", "devpass"),
        )
        app.state.saved_analyses_store = SavedAnalysesStore(app.state.clickhouse_client)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="HPC Behavior Platform Analysis API", lifespan=lifespan)

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

    app.include_router(session.router)
    app.include_router(inter.router)
    app.include_router(intra.router)
    app.include_router(raw.router)
    app.include_router(jobs.router)
    app.include_router(analyses.router)

    return app


app = create_app()
