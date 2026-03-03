"""/api/faces — set sticky label on individual faces."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from ..deps import get_db
from ..models import FaceLabelRequest
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

    *bbox* is dash-separated: ``x1-y1-x2-y2``.
    Set ``name`` to ``null`` to clear an existing label.
    """
    try:
        parts = [int(v) for v in bbox.split("-")]
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
