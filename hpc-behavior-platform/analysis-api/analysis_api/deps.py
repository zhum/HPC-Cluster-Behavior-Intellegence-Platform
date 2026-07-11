from __future__ import annotations

from fastapi import Request
from clickhouse_connect.driver.client import Client

from analysis_api.cache import RedisStageCache
from analysis_api.session import SessionStore


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


def get_stage_cache(request: Request) -> RedisStageCache:
    return request.app.state.stage_cache


def get_clickhouse_client(request: Request) -> Client:
    return request.app.state.clickhouse_client
