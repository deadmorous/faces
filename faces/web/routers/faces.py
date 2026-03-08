"""/api/faces — set sticky label on individual faces; find similar faces."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..deps import get_db
from ..models import FaceLabelRequest, SimilarFace, SimilarFacesResponse
from ...db import Database, load_photo_dates, parse_date, stick_face

router = APIRouter(prefix="/api/faces", tags=["faces"])


@router.get("/unlabeled", summary="Paginated unlabeled faces sorted by bbox perimeter")
def list_unlabeled_faces(
    request: Request,
    page: int = 1,
    page_size: int = 100,
    rel_size_min: float = 0.0,
    since: Optional[str] = None,
    until: Optional[str] = None,
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """Return unlabeled faces sorted by bounding-box perimeter descending (largest first)."""
    try:
        since_ts = parse_date(since) if since else None
        until_ts = parse_date(until, end_of_period=True) if until else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    photo_dates = load_photo_dates(db) if (since_ts or until_ts) else None

    all_rows = request.app.state.embeddings_cache["rows"]
    unlabeled = [r for r in all_rows if not r.get("name")]
    if rel_size_min > 0.0:
        unlabeled = [r for r in unlabeled if r.get("rel_size", 1.0) >= rel_size_min]
    if photo_dates is not None:
        def _in_range(r):
            mt = photo_dates.get(r["md5"])
            if mt is None: return True   # no EXIF → include
            if since_ts and mt < since_ts: return False
            if until_ts and mt >= until_ts: return False
            return True
        unlabeled = [r for r in unlabeled if _in_range(r)]
    unlabeled.sort(
        key=lambda r: (r["bbox"][2] - r["bbox"][0]) + (r["bbox"][3] - r["bbox"][1]),
        reverse=True,
    )
    total = len(unlabeled)
    start = (page - 1) * page_size
    page_rows = unlabeled[start:start + page_size]
    faces = []
    for r in page_rows:
        x1, y1, x2, y2 = r["bbox"]
        faces.append({
            "md5": r["md5"],
            "bbox": list(r["bbox"]),
            "rel_size": round(r.get("rel_size", 1.0), 3),
            "img_url": f"/img/face?md5={r['md5']}&bbox={x1},{y1},{x2},{y2}",
            "photo_url": f"/img/photo/{r['md5']}",
        })
    return {"total": total, "page": page, "page_size": page_size, "faces": faces}


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
    request: Request,
    md5: str,
    bbox: str = Query(..., description="x1,y1,x2,y2 in original image pixels"),
    limit: int = 100,
    unlabeled_only: bool = False,
    since: Optional[str] = None,
    until: Optional[str] = None,
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

    try:
        since_ts = parse_date(since) if since else None
        until_ts = parse_date(until, end_of_period=True) if until else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

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

    emb_index = request.app.state.embeddings_cache["index"]
    emb_rows  = request.app.state.embeddings_cache["rows"]

    def _rel_size(fmd5: str, fbbox: list) -> float:
        key = (fmd5, tuple(fbbox))
        idx = emb_index.get(key)
        return emb_rows[idx].get("rel_size", 1.0) if idx is not None else 1.0

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
        bbox_list = list(r["bbox"])
        return SimilarFace(
            md5=r["md5"],
            bbox=bbox_list,
            dist=float(r.get("_distance", 0.0)) ** 0.5,
            name=r.get("name"),
            img_url=f"/img/face?md5={r['md5']}&bbox={bx1},{by1},{bx2},{by2}",
            photo_path=_photo_path(r["md5"]),
            rel_size=round(_rel_size(r["md5"], bbox_list), 3),
        )

    # Fetch generously so Python-side filtering (seed + unlabeled_only + date) still
    # yields up to `limit` results. LanceDB returns _distance = squared L2.
    needs_date_filter = since_ts is not None or until_ts is not None
    photo_dates_similar = load_photo_dates(db) if needs_date_filter else None
    fetch_n = limit * 5 + 1 if (unlabeled_only or needs_date_filter) else limit + 1
    candidates = db.faces.search(seed_embedding).limit(fetch_n).to_list()

    seed_face = _make(seed_row)
    seed_face.dist = 0.0

    results: list[SimilarFace] = []
    for r in candidates:
        if r["md5"] == md5 and list(r["bbox"]) == [x1, y1, x2, y2]:
            continue  # skip seed
        if unlabeled_only and r.get("name"):
            continue
        if photo_dates_similar is not None:
            mt = photo_dates_similar.get(r["md5"])
            if mt is not None:
                if since_ts and mt < since_ts:
                    continue
                if until_ts and mt >= until_ts:
                    continue
        results.append(_make(r))
        if len(results) >= limit:
            break

    return SimilarFacesResponse(seed=seed_face, faces=results)
