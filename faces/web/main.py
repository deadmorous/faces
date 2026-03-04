"""FastAPI application entry point.

Run with:
    uvicorn faces.web.main:app --reload

Set the FACES_CONFIG environment variable to point to a specific config file:
    FACES_CONFIG=~/work/faces.yaml uvicorn faces.web.main:app --reload
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..config import load
from ..db import open_db
from .routers import classify, clusterize, clusters, faces, images, people, photos


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load(os.environ.get("FACES_CONFIG"))
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

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="static")


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/ui/")


app.include_router(images.router)
app.include_router(clusters.router)
app.include_router(people.router)
app.include_router(photos.router)
app.include_router(faces.router)
app.include_router(classify.router)
app.include_router(clusterize.router)
