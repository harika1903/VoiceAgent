"""FastAPI dependency factories — one place to get shared objects from app.state."""

from fastapi import Request


def get_agent_repo(request: Request):
    return request.app.state.agent_repo


def get_dispatcher(request: Request):
    return request.app.state.dispatcher


def get_session_store(request: Request):
    return request.app.state.session_store


def get_settings(request: Request):
    return request.app.state.settings


def get_db_pool(request: Request):
    return request.app.state.db_pool


def get_redis(request: Request):
    return request.app.state.redis
