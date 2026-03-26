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
    request: Request,
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

    # Verify face exists (use Python-side match to avoid LanceDB array-index quirks)
    all_rows = (
        db.faces.search()
        .where(f"md5 = '{md5}'", prefilter=True)
        .limit(10_000_000)
        .to_list()
    )
    if not any(list(r["bbox"]) == bbox_list for r in all_rows):
        raise HTTPException(status_code=404, detail="Face not found")

    stick_face(db, md5, bbox_list, body.name)

    # Keep embeddings cache consistent (same pattern as classify/labels and people rename)
    emb_index = request.app.state.embeddings_cache["index"]
    emb_rows  = request.app.state.embeddings_cache["rows"]
    key = (md5, tuple(bbox_list))
    if key in emb_index:
        emb_rows[emb_index[key]]["name"] = body.name
    request.app.state.data_generation += 1

    return Response(status_code=204)


_TW_HALF_DAYS: dict[str, float] = {
    "day": 0.5, "3days": 1.5, "week": 3.5, "month": 15.0,
}


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
    time_window: Optional[str] = Query(None,
        description="Symmetric window around seed photo date: day, 3days, week, month"),
    rel_size_min: float = Query(0.0, ge=0.0, le=1.0),
    min_face_px: int = Query(0, ge=0,
        description="Minimum face size: min(width, height) in pixels"),
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

    # Compute time-window filter anchored to seed photo's EXIF date
    tw_since_ts = tw_until_ts = None
    if time_window and time_window in _TW_HALF_DAYS:
        photo_rows = (db.photos.search()
                      .where(f"md5 = '{md5}'", prefilter=True)
                      .limit(1).to_list())
        seed_exif = photo_rows[0].get("exif_date") if photo_rows else None
        if seed_exif:
            half = _TW_HALF_DAYS[time_window] * 86400
            tw_since_ts = seed_exif - half
            tw_until_ts = seed_exif + half

    # Merge explicit date bounds and time-window bounds (take tighter intersection)
    def _intersect(a, b, take_max: bool):
        if a is not None and b is not None:
            return max(a, b) if take_max else min(a, b)
        return a if a is not None else b

    eff_since = _intersect(since_ts, tw_since_ts, take_max=True)
    eff_until = _intersect(until_ts, tw_until_ts, take_max=False)

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

    # Fetch generously so Python-side filtering still yields up to `limit` results.
    # LanceDB returns _distance = squared L2.
    needs_date_filter = eff_since is not None or eff_until is not None
    needs_size_filter = rel_size_min > 0 or min_face_px > 0
    photo_dates_similar = load_photo_dates(db) if needs_date_filter else None
    fetch_n = limit * 5 + 1 if (unlabeled_only or needs_date_filter or needs_size_filter) else limit + 1
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
                if eff_since and mt < eff_since:
                    continue
                if eff_until and mt >= eff_until:
                    continue
        if rel_size_min > 0:
            key = (r["md5"], tuple(r["bbox"]))
            idx = emb_index.get(key)
            rs = emb_rows[idx].get("rel_size", 1.0) if idx is not None else 1.0
            if rs < rel_size_min:
                continue
        if min_face_px > 0:
            b = r["bbox"]
            if min(b[2] - b[0], b[3] - b[1]) < min_face_px:
                continue
        results.append(_make(r))
        if len(results) >= limit:
            break

    return SimilarFacesResponse(seed=seed_face, faces=results)
