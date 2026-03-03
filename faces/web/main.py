"""FastAPI application entry point.

Run with:
    uvicorn faces.web.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..config import load
from ..db import open_db
from .routers import classify, clusterize, clusters, faces, images, people, photos


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load()
    db = open_db(cfg.database)
    app.state.cfg = cfg
    app.state.db = db
    yield


app = FastAPI(
    title="faces API",
    description="Web API for the faces face-recognition tool.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(images.router)
app.include_router(clusters.router)
app.include_router(people.router)
app.include_router(photos.router)
app.include_router(faces.router)
app.include_router(classify.router)
app.include_router(clusterize.router)
