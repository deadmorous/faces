"""/api/photos — paginated photo list and per-photo detail."""

from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image

from ..deps import get_cfg, get_db
from ..models import PhotoDetail, PhotoFaceDetail, PhotoList, PhotoSummary
from ...config import Config
from ...db import Database, load_photo_dates, parse_date, photo_date_coverage

router = APIRouter(prefix="/api/photos", tags=["photos"])


def _read_exif_orientation(path: Path) -> int:
    try:
        return Image.open(path).getexif().get(0x0112, 1)
    except Exception:
        return 1


@router.get("", response_model=PhotoList, summary="Paginated photo list")
def list_photos(
    since: Optional[str] = None,
    until: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """Return a paginated list of scanned photos."""
    try:
        since_ts = parse_date(since) if since else None
        until_ts = parse_date(until, end_of_period=True) if until else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    all_rows = db.photos.search().limit(10_000_000).to_list()

    # Time filter (photos without EXIF date always pass)
    if since_ts is not None or until_ts is not None:
        filtered = []
        for row in all_rows:
            date = row.get("exif_date")
            if date is None:
                filtered.append(row)   # no EXIF → always include
                continue
            if since_ts is not None and date < since_ts:
                continue
            if until_ts is not None and date >= until_ts:
                continue
            filtered.append(row)
        all_rows = filtered

    all_rows.sort(key=lambda r: r.get("exif_date") or 0, reverse=True)

    total = len(all_rows)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = all_rows[start:end]

    photos = [
        PhotoSummary(
            md5=row["md5"],
            path=row["path"],
            face_count=row.get("face_count", 0),
            exif_date=row.get("exif_date"),
            photo_url=f"/img/photo/{row['md5']}",
        )
        for row in page_rows
    ]
    return PhotoList(total=total, photos=photos)


@router.get("/date_coverage", summary="Min/max EXIF year in the database")
def date_coverage_endpoint(db: Annotated[Database, Depends(get_db)] = ...):
    """Return the min and max year from EXIF dates across all photos."""
    min_y, max_y = photo_date_coverage(db)
    return {"min_year": min_y, "max_year": max_y}


@router.get("/{md5}", response_model=PhotoDetail, summary="Photo detail with all detected faces")
def get_photo(
    md5: str,
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Return photo metadata plus every detected face with labels."""
    photo_rows = (
        db.photos.search()
        .where(f"md5 = '{md5}'", prefilter=True)
        .limit(1)
        .to_list()
    )
    if not photo_rows:
        raise HTTPException(status_code=404, detail=f"Photo {md5!r} not found")
    photo_row = photo_rows[0]

    # Get faces from faces table
    face_rows = (
        db.faces.search()
        .where(f"md5 = '{md5}'", prefilter=True)
        .limit(10_000_000)
        .to_list()
    )

    faces = []
    for fr in face_rows:
        bbox = list(fr["bbox"])
        x1, y1, x2, y2 = bbox
        faces.append(PhotoFaceDetail(
            md5=md5,
            bbox=bbox,
            score=float(fr.get("score", 0.0)),
            sticky_name=fr.get("name"),
            img_url=f"/img/face?md5={md5}&bbox={x1},{y1},{x2},{y2}",
        ))

    rel = photo_row["path"]
    photo_path = (cfg.photos_dir / rel) if cfg.photos_dir else Path(rel)
    exif_orientation = _read_exif_orientation(photo_path)

    return PhotoDetail(
        md5=md5,
        path=photo_row["path"],
        exif_date=photo_row.get("exif_date"),
        exif_orientation=exif_orientation,
        photo_url=f"/img/photo/{md5}",
        faces=faces,
    )
