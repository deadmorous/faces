"""/api/classify — batch-by-person classify candidates and bulk label submission."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_cfg, get_db
from ..models import (
    ClassifyCandidates, ClassifyFace, ClassifyGroup,
    ClassifyLabelsResponse, FaceLabelItem, UnmatchedFace,
)
from ...algo import classify_candidates
from ...config import Config
from ...db import Database, stick_face

router = APIRouter(prefix="/api/classify", tags=["classify"])


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
    threshold: Optional[float] = None,
    min_size: int = 3,
    since: Optional[str] = None,
    until: Optional[str] = None,
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Run single-linkage classify logic and return candidates grouped by person.

    Groups are sorted by avg_dist ascending (most confident first).
    Unmatched faces (beyond eps) are included for foreign/non-face marking.
    """
    effective_threshold = threshold if threshold is not None else cfg.cluster_threshold

    try:
        result = classify_candidates(
            db=db,
            threshold=effective_threshold,
            min_size=min_size,
            since=since,
            until=until,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Enrich with URLs — build photo path cache to avoid repeated lookups
    path_cache: dict[str, str] = {}

    def _photo_path(md5: str) -> str:
        if md5 not in path_cache:
            path_cache[md5] = _photo_path_for_md5(db, md5)
        return path_cache[md5]

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
        for g in result["groups"]
    ]

    unmatched = [
        UnmatchedFace(
            md5=f["md5"],
            bbox=f["bbox"],
            img_url=_face_img_url(f["md5"], f["bbox"]),
            photo_url=f"/img/photo/{f['md5']}",
        )
        for f in result["unmatched"]
    ]

    return ClassifyCandidates(eps=result["eps"], groups=groups, unmatched=unmatched)


@router.post("/labels", response_model=ClassifyLabelsResponse,
             summary="Bulk submit face labels")
def submit_labels(
    items: list[FaceLabelItem],
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """Assign sticky labels to any number of faces in one request.

    Faces omitted from the request are left unlabeled and will reappear in
    future calls to ``/api/classify/candidates``.
    """
    labeled = 0
    for item in items:
        if item.name is None:
            x1, y1, x2, y2 = item.bbox
            db.faces.update(
                where=(
                    f"md5 = '{item.md5}' AND "
                    f"bbox[1] = {x1} AND bbox[2] = {y1} AND "
                    f"bbox[3] = {x2} AND bbox[4] = {y2}"
                ),
                values={"name": None},
            )
        else:
            stick_face(db, item.md5, item.bbox, item.name)
        labeled += 1

    return ClassifyLabelsResponse(labeled=labeled)
