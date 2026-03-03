"""FastAPI dependency providers for DB and Config."""

from fastapi import Request

from ..config import Config
from ..db import Database


def get_cfg(request: Request) -> Config:
    return request.app.state.cfg


def get_db(request: Request) -> Database:
    return request.app.state.db
