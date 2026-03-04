"""/img/* — serve original photos and dynamically-cropped face thumbnails."""

import io
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from PIL import Image, ImageOps

from ..deps import get_cfg, get_db
from ...config import Config
from ...db import Database
from ...viz import PADDING_FRAC

router = APIRouter(prefix="/img", tags=["images"])


def _transform_bbox_for_display(
    bbox: list[int], orientation: int, raw_w: int, raw_h: int
) -> list[int]:
    """Map a bbox from raw (unrotated) pixel space into display (post-EXIF) space.

    ``orientation`` is the EXIF Orientation tag value (1–8).
    For orientations 5-8 the display image is transposed (width↔height swapped).
    """
    x1, y1, x2, y2 = bbox
    if orientation == 2:
        return [raw_w - x2, y1, raw_w - x1, y2]
    if orientation == 3:
        return [raw_w - x2, raw_h - y2, raw_w - x1, raw_h - y1]
    if orientation == 4:
        return [x1, raw_h - y2, x2, raw_h - y1]
    if orientation == 5:
        return [y1, x1, y2, x2]
    if orientation == 6:  # 90° CW — most common for phone portrait
        return [raw_h - y2, x1, raw_h - y1, x2]
    if orientation == 7:
        return [raw_h - y2, raw_w - x2, raw_h - y1, raw_w - x1]
    if orientation == 8:  # 90° CCW
        return [y1, raw_w - x2, y2, raw_w - x1]
    return list(bbox)  # orientation == 1: no transform


def _resolve_photo_path(db: Database, cfg: Config, md5: str) -> Path:
    """Look up the photo path for *md5* and return the absolute Path.

    Raises HTTPException 404 if not found or the file does not exist on disk.
    """
    rows = (
        db.photos.search()
        .where(f"md5 = '{md5}'", prefilter=True)
        .limit(1)
        .to_list()
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Photo {md5!r} not found in index")
    rel = rows[0]["path"]
    photo_path = (cfg.photos_dir / rel) if cfg.photos_dir else Path(rel)
    if not photo_path.exists():
        raise HTTPException(status_code=404, detail=f"Photo file not found on disk: {rel}")
    return photo_path


@router.get("/photo/{md5}", summary="Stream original JPEG photo")
def get_photo(
    md5: str,
    db: Annotated[Database, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_cfg)],
):
    """Return the original JPEG file for the photo identified by *md5*."""
    photo_path = _resolve_photo_path(db, cfg, md5)

    def _iter():
        with open(photo_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(_iter(), media_type="image/jpeg")


@router.get("/face", summary="Return a cropped face thumbnail as JPEG")
def get_face(
    md5: str,
    bbox: str = Query(..., description="x1,y1,x2,y2 in original image pixels"),
    padding: float = Query(PADDING_FRAC, description="Fractional padding around bbox"),
    size: int = Query(224, description="Output square size in pixels"),
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Dynamically crop a face and return it as a JPEG image."""
    try:
        parts = [int(v) for v in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        x1, y1, x2, y2 = parts
    except ValueError:
        raise HTTPException(status_code=422, detail="bbox must be x1,y1,x2,y2 integers")

    photo_path = _resolve_photo_path(db, cfg, md5)

    try:
        raw = Image.open(photo_path)
        orientation = raw.getexif().get(0x0112, 1)
        raw_w, raw_h = raw.size
        img = ImageOps.exif_transpose(raw.convert("RGB"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open image: {e}")

    dx1, dy1, dx2, dy2 = _transform_bbox_for_display(
        [x1, y1, x2, y2], orientation, raw_w, raw_h
    )
    w, h = dx2 - dx1, dy2 - dy1
    pad_x = int(w * padding)
    pad_y = int(h * padding)
    cx1 = max(0, dx1 - pad_x)
    cy1 = max(0, dy1 - pad_y)
    cx2 = min(img.width, dx2 + pad_x)
    cy2 = min(img.height, dy2 + pad_y)
    cropped = ImageOps.fit(img.crop((cx1, cy1, cx2, cy2)), (size, size), Image.LANCZOS)

    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")
