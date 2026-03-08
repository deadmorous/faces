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


def _get_cached_result(
    request: Request,
    db: Database,
    cfg: Config,
    threshold: Optional[float],
    min_size: int,
    since: Optional[str],
    until: Optional[str],
    algo: str,
) -> dict:
    """Return full classify result from cache or recompute."""
    if algo not in ALGORITHMS:
        raise HTTPException(status_code=422, detail=f"Unknown algorithm {algo!r}")
    effective_threshold = threshold if threshold is not None else cfg.cluster_threshold
    cache_key = (algo, effective_threshold, min_size, since, until)
    cached = request.app.state.classify_cache
    generation = request.app.state.data_generation

    if cached["generation"] == generation and cached["key"] == cache_key:
        return cached["result"]

    emb = request.app.state.embeddings_cache
    try:
        with timed(f"classify_candidates [{algo}]: cache miss"):
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
    return result


@router.get("/people", summary="List people who have classify candidates")
def classify_people(
    request: Request,
    threshold: Optional[float] = None,
    min_size: int = 3,
    since: Optional[str] = None,
    until: Optional[str] = None,
    algo: str = DEFAULT_ALGO,
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Return people with matching unlabeled candidates, sorted by avg_dist ascending."""
    result = _get_cached_result(request, db, cfg, threshold, min_size, since, until, algo)
    return [
        {"name": g["person"], "face_count": len(g["faces"]), "avg_dist": g["avg_dist"]}
        for g in result["groups"]
    ]


@router.get("/candidates", response_model=ClassifyCandidates,
            summary="Get unlabeled faces for a specific person")
def get_candidates(
    request: Request,
    person: Optional[str] = None,
    threshold: Optional[float] = None,
    min_size: int = 3,
    since: Optional[str] = None,
    until: Optional[str] = None,
    algo: str = DEFAULT_ALGO,
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Return all unlabeled faces matching the given person (from cache).

    When *person* is None, returns all groups (backward-compat, no pagination).
    """
    result = _get_cached_result(request, db, cfg, threshold, min_size, since, until, algo)

    path_cache: dict[str, str] = {}

    def _photo_path(md5: str) -> str:
        if md5 not in path_cache:
            path_cache[md5] = _photo_path_for_md5(db, md5)
        return path_cache[md5]

    def _enrich_group(g: dict) -> ClassifyGroup:
        return ClassifyGroup(
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

    if person is not None:
        raw = next((g for g in result["groups"] if g["person"] == person), None)
        groups = [_enrich_group(raw)] if raw else []
        return ClassifyCandidates(
            eps=result["eps"],
            total_groups=len(groups),
            groups=groups,
            unmatched=[],
        )

    # No person filter — return all groups
    groups = [_enrich_group(g) for g in result["groups"]]
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
        total_groups=len(groups),
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
