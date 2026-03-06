"""/api/faces — set sticky label on individual faces; find similar faces."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..deps import get_db
from ..models import FaceLabelRequest, SimilarFace, SimilarFacesResponse
from ...db import Database, stick_face

router = APIRouter(prefix="/api/faces", tags=["faces"])


@router.patch("/{md5}/{bbox}", status_code=204, summary="Set sticky label on a single face")
def label_face(
    md5: str,
    bbox: str,
    body: FaceLabelRequest,
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """Set (or clear) the sticky label for a single face.

    *bbox* is underscore-separated: ``x1_y1_x2_y2``.
    Set ``name`` to ``null`` to clear an existing label.
    """
    try:
        parts = [int(v) for v in bbox.split("_")]
        if len(parts) != 4:
            raise ValueError
        bbox_list = parts
    except ValueError:
        raise HTTPException(status_code=422, detail="bbox must be x1-y1-x2-y2 integers")

    # Verify face exists
    x1, y1, x2, y2 = bbox_list
    existing = (
        db.faces.search()
        .where(
            f"md5 = '{md5}' AND "
            f"bbox[1] = {x1} AND bbox[2] = {y1} AND "
            f"bbox[3] = {x2} AND bbox[4] = {y2}",
            prefilter=True,
        )
        .limit(1)
        .to_list()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Face not found")

    if body.name is None:
        db.faces.update(
            where=(
                f"md5 = '{md5}' AND "
                f"bbox[1] = {x1} AND bbox[2] = {y1} AND "
                f"bbox[3] = {x2} AND bbox[4] = {y2}"
            ),
            values={"name": None},
        )
    else:
        stick_face(db, md5, bbox_list, body.name)

    return Response(status_code=204)


@router.get("/similar", response_model=SimilarFacesResponse,
            summary="Find faces with similar embeddings")
def get_similar_faces(
    md5: str,
    bbox: str = Query(..., description="x1,y1,x2,y2 in original image pixels"),
    limit: int = 100,
    unlabeled_only: bool = False,
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """Return up to *limit* faces sorted by embedding distance to the seed face."""
    try:
        parts = [int(v) for v in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        x1, y1, x2, y2 = parts
    except ValueError:
        raise HTTPException(status_code=422, detail="bbox must be x1,y1,x2,y2 integers")

    # Look up seed face — query by md5 only, match bbox in Python to avoid
    # any LanceDB SQL array-indexing edge cases.
    photo_faces = (
        db.faces.search()
        .where(f"md5 = '{md5}'", prefilter=True)
        .limit(1000)
        .to_list()
    )
    target_bbox = [x1, y1, x2, y2]
    seed_row = next(
        (r for r in photo_faces if list(r["bbox"]) == target_bbox),
        None,
    )
    if seed_row is None:
        raise HTTPException(status_code=404, detail="Face not found")
    seed_embedding = seed_row["embedding"]

    # Photo path cache
    path_cache: dict[str, str] = {}

    def _photo_path(fmd5: str) -> str:
        if fmd5 not in path_cache:
            prows = (db.photos.search()
                     .where(f"md5 = '{fmd5}'", prefilter=True)
                     .limit(1).to_list())
            path_cache[fmd5] = prows[0]["path"] if prows else ""
        return path_cache[fmd5]

    def _make(r: dict) -> SimilarFace:
        bx1, by1, bx2, by2 = r["bbox"]
        return SimilarFace(
            md5=r["md5"],
            bbox=list(r["bbox"]),
            dist=float(r.get("_distance", 0.0)) ** 0.5,
            name=r.get("name"),
            img_url=f"/img/face?md5={r['md5']}&bbox={bx1},{by1},{bx2},{by2}",
            photo_path=_photo_path(r["md5"]),
        )

    # Fetch generously so Python-side filtering (seed + unlabeled_only) still
    # yields up to `limit` results. LanceDB returns _distance = squared L2.
    fetch_n = limit * 3 + 1 if unlabeled_only else limit + 1
    candidates = db.faces.search(seed_embedding).limit(fetch_n).to_list()

    seed_face = _make(seed_row)
    seed_face.dist = 0.0

    results: list[SimilarFace] = []
    for r in candidates:
        if r["md5"] == md5 and list(r["bbox"]) == [x1, y1, x2, y2]:
            continue  # skip seed
        if unlabeled_only and r.get("name"):
            continue
        results.append(_make(r))
        if len(results) >= limit:
            break

    return SimilarFacesResponse(seed=seed_face, faces=results)
