"""/api/classify — batch-by-person classify candidates and bulk label submission."""

from collections import defaultdict
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import get_cfg, get_db
from ..models import (
    ClassifyCandidates, ClassifyFace, ClassifyGroup,
    ClassifyLabelsResponse, FaceLabelItem, UnmatchedFace,
)
from ...algo import ALGORITHMS, DEFAULT_ALGO, classify_candidates
from ...config import Config
from ...db import Database
from ...timing import timed
from .people import people_cache_to_list

router = APIRouter(prefix="/api/classify", tags=["classify"])


@router.get("/algorithms", summary="List available classification algorithms")
def list_algorithms():
    """Return algorithm names and display labels in registry order."""
    return [{"name": n, "label": lbl} for n, (lbl, _) in ALGORITHMS.items()]


def _face_img_url(md5: str, bbox: list[int]) -> str:
    x1, y1, x2, y2 = bbox
    return f"/img/face?md5={md5}&bbox={x1},{y1},{x2},{y2}"


def _photo_path_for_md5(db: Database, md5: str) -> str:
    rows = (
        db.photos.search()
        .where(f"md5 = '{md5}'", prefilter=True)
        .limit(1)
        .to_list()
    )
    return rows[0]["path"] if rows else ""


@router.get("/candidates", response_model=ClassifyCandidates,
            summary="Get unlabeled faces grouped by predicted person")
def get_candidates(
    request: Request,
    threshold: Optional[float] = None,
    min_size: int = 3,
    page: int = 1,
    page_size: int = 10,
    since: Optional[str] = None,
    until: Optional[str] = None,
    algo: str = DEFAULT_ALGO,
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Run classification and return candidates grouped by person.

    Groups are sorted by avg_dist ascending (most confident first).
    Unmatched faces (beyond eps) are included for foreign/non-face marking.
    The full candidate list is cached keyed by (algo, threshold, min_size, since, until)
    and a data_generation counter; page navigation is served from cache.
    """
    if algo not in ALGORITHMS:
        raise HTTPException(status_code=422, detail=f"Unknown algorithm {algo!r}")
    effective_threshold = threshold if threshold is not None else cfg.cluster_threshold
    cache_key = (algo, effective_threshold, min_size, since, until)
    cached = request.app.state.classify_cache
    generation = request.app.state.data_generation

    if cached["generation"] == generation and cached["key"] == cache_key:
        result = cached["result"]
    else:
        emb = request.app.state.embeddings_cache
        try:
            with timed(f"GET /api/classify/candidates [{algo}]: classify_candidates (cache miss)"):
                result = classify_candidates(
                    db=db,
                    threshold=effective_threshold,
                    min_size=min_size,
                    since=since,
                    until=until,
                    rows=emb["rows"],
                    X=emb["X"],
                    algo=algo,
                )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        request.app.state.classify_cache = {"generation": generation, "key": cache_key, "result": result}

    # Enrich with URLs — build photo path cache to avoid repeated lookups
    path_cache: dict[str, str] = {}

    def _photo_path(md5: str) -> str:
        if md5 not in path_cache:
            path_cache[md5] = _photo_path_for_md5(db, md5)
        return path_cache[md5]

    all_groups = result["groups"]
    total_groups = len(all_groups)
    start = (page - 1) * page_size
    page_groups = all_groups[start:start + page_size]

    groups = [
        ClassifyGroup(
            person=g["person"],
            avg_dist=g["avg_dist"],
            faces=[
                ClassifyFace(
                    md5=f["md5"],
                    bbox=f["bbox"],
                    dist=f["dist"],
                    img_url=_face_img_url(f["md5"], f["bbox"]),
                    photo_url=f"/img/photo/{f['md5']}",
                    photo_path=_photo_path(f["md5"]),
                )
                for f in g["faces"]
            ],
        )
        for g in page_groups
    ]

    # Unmatched only on page 1 to avoid re-rendering on every page navigation
    unmatched = []
    if page == 1:
        unmatched = [
            UnmatchedFace(
                md5=f["md5"],
                bbox=f["bbox"],
                img_url=_face_img_url(f["md5"], f["bbox"]),
                photo_url=f"/img/photo/{f['md5']}",
            )
            for f in result["unmatched"]
        ]

    return ClassifyCandidates(
        eps=result["eps"],
        total_groups=total_groups,
        groups=groups,
        unmatched=unmatched,
    )


@router.post("/labels", response_model=ClassifyLabelsResponse,
             summary="Bulk submit face labels")
def submit_labels(
    request: Request,
    items: list[FaceLabelItem],
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """Assign sticky labels to any number of faces in one request.

    Faces omitted from the request are left unlabeled and will reappear in
    future calls to ``/api/classify/candidates``.
    """
    def _face_condition(item: FaceLabelItem) -> str:
        x1, y1, x2, y2 = item.bbox
        return (f"(md5 = '{item.md5}' AND "
                f"bbox[1] = {x1} AND bbox[2] = {y1} AND "
                f"bbox[3] = {x2} AND bbox[4] = {y2})")

    # Group by name so each unique label is one DB round-trip
    by_name: dict[str | None, list[FaceLabelItem]] = defaultdict(list)
    for item in items:
        by_name[item.name].append(item)

    for name, group_items in by_name.items():
        where = " OR ".join(_face_condition(i) for i in group_items)
        db.faces.update(where=where, values={"name": name})

    # Update people cache incrementally
    people_cache = request.app.state.people_cache
    for name, group_items in by_name.items():
        if name is None:
            continue  # faces were unlabeled before, still unlabeled — no entry to add
        md5s = {item.md5 for item in group_items}
        if name in people_cache:
            people_cache[name]["face_count"] += len(group_items)
            people_cache[name]["photo_md5s"] |= md5s
        else:
            people_cache[name] = {"face_count": len(group_items), "photo_md5s": md5s}

    # Update embeddings cache: set new name on each affected row
    emb_index = request.app.state.embeddings_cache["index"]
    emb_rows = request.app.state.embeddings_cache["rows"]
    for item in items:
        key = (item.md5, tuple(item.bbox))
        if key in emb_index:
            emb_rows[emb_index[key]]["name"] = item.name

    request.app.state.data_generation += 1
    return ClassifyLabelsResponse(labeled=len(items))
