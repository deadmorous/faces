"""FastAPI application entry point.

Run with:
    uvicorn faces.web.main:app --reload

Set the FACES_CONFIG environment variable to point to a specific config file:
    FACES_CONFIG=~/work/faces.yaml uvicorn faces.web.main:app --reload
"""

import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..config import load
from ..db import load_all_embeddings, open_db
from .routers import classify, faces, images, people, photos
from .routers.people import build_people_cache


_perf_logger = logging.getLogger("faces.perf")
_perf_logger.setLevel(logging.INFO)
_perf_logger.propagate = False
_perf_handler = logging.StreamHandler()
_perf_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
_perf_logger.addHandler(_perf_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load(os.environ.get("FACES_CONFIG"))
    db = open_db(cfg.database)
    app.state.cfg = cfg
    app.state.db = db
    app.state.people_cache = build_people_cache(db)
    app.state.data_generation = 0
    app.state.classify_cache = {"generation": -1, "key": None, "result": None}
    rows, X = load_all_embeddings(db)
    t0 = time.perf_counter()
    max_perim: dict[str, float] = defaultdict(float)
    for r in rows:
        b = r["bbox"]
        p = (b[2] - b[0]) + (b[3] - b[1])
        if p > max_perim[r["md5"]]:
            max_perim[r["md5"]] = p
    for r in rows:
        b = r["bbox"]
        p = (b[2] - b[0]) + (b[3] - b[1])
        mp = max_perim[r["md5"]]
        r["rel_size"] = p / mp if mp > 0 else 1.0
    print(f"rel_size computed in {(time.perf_counter()-t0)*1000:.1f} ms for {len(rows)} faces",
          flush=True)
    index = {(r["md5"], tuple(r["bbox"])): i for i, r in enumerate(rows)}
    app.state.embeddings_cache = {"rows": rows, "X": X, "index": index}
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
app.include_router(people.router)
app.include_router(photos.router)
app.include_router(faces.router)
app.include_router(classify.router)
