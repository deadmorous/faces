"""/api/clusters — list, detail, and rename face clusters."""

from collections import defaultdict
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_cfg, get_db
from ..models import (
    ClusterDetail, ClusterPatchRequest, ClusterPatchResponse,
    ClusterSummary, FaceDetail, FaceSample,
)
from ...config import Config
from ...db import Database, stick_faces

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


def _face_img_url(md5: str, bbox: list[int]) -> str:
    x1, y1, x2, y2 = bbox
    return f"/img/face?md5={md5}&bbox={x1},{y1},{x2},{y2}"


@router.get("", response_model=list[ClusterSummary], summary="List all clusters")
def list_clusters(
    min_size: int = 1,
    max_size: Optional[int] = None,
    named_only: bool = False,
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """List all clusters sorted by size descending."""
    rows = db.clusters.search().limit(10_000_000).to_list()
    if not rows:
        return []

    # Aggregate per cluster_id
    sizes: dict[int, int] = defaultdict(int)
    names: dict[int, Optional[str]] = {}
    samples: dict[int, list[dict]] = defaultdict(list)

    for row in rows:
        cid = row["cluster_id"]
        sizes[cid] += 1
        if names.get(cid) is None:
            names[cid] = row.get("name")
        if len(samples[cid]) < 4:
            samples[cid].append(row)

    results = []
    for cid, size in sizes.items():
        if size < min_size:
            continue
        if max_size is not None and size > max_size:
            continue
        name = names.get(cid)
        if named_only and not name:
            continue
        sample_faces = [
            FaceSample(img_url=_face_img_url(r["md5"], r["bbox"]))
            for r in samples[cid]
        ]
        results.append(ClusterSummary(
            id=cid,
            name=name,
            size=size,
            sample_faces=sample_faces,
        ))

    results.sort(key=lambda c: c.size, reverse=True)
    return results


@router.get("/{cluster_id}", response_model=ClusterDetail, summary="Cluster detail with all faces")
def get_cluster(
    cluster_id: int,
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Return full cluster detail including all face thumbnails and links."""
    cluster_rows = (
        db.clusters.search()
        .where(f"cluster_id = {cluster_id}", prefilter=True)
        .limit(10_000_000)
        .to_list()
    )
    if not cluster_rows:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    # Build md5 → photo row map
    needed_md5s = {r["md5"] for r in cluster_rows}
    photo_map: dict[str, dict] = {}
    for md5 in needed_md5s:
        photo_rows = (
            db.photos.search()
            .where(f"md5 = '{md5}'", prefilter=True)
            .limit(1)
            .to_list()
        )
        if photo_rows:
            photo_map[md5] = photo_rows[0]

    # Build md5 → face score map from faces table
    face_scores: dict[tuple, float] = {}
    for md5 in needed_md5s:
        face_rows = (
            db.faces.search()
            .where(f"md5 = '{md5}'", prefilter=True)
            .limit(10_000_000)
            .to_list()
        )
        for fr in face_rows:
            key = (fr["md5"], tuple(fr["bbox"]))
            face_scores[key] = float(fr.get("score", 0.0))

    cluster_name = cluster_rows[0].get("name")

    faces = []
    for row in cluster_rows:
        md5 = row["md5"]
        bbox = list(row["bbox"])
        photo_row = photo_map.get(md5)
        photo_path = photo_row["path"] if photo_row else ""
        score = face_scores.get((md5, tuple(bbox)), 0.0)
        faces.append(FaceDetail(
            md5=md5,
            bbox=bbox,
            score=score,
            sticky_name=row.get("name"),
            img_url=_face_img_url(md5, bbox),
            photo_url=f"/img/photo/{md5}",
            photo_path=photo_path,
            photo_detail_url=f"/api/photos/{md5}",
        ))

    return ClusterDetail(
        id=cluster_id,
        name=cluster_name,
        size=len(faces),
        faces=faces,
    )


@router.patch("/{cluster_id}", response_model=ClusterPatchResponse, summary="Rename a cluster")
def rename_cluster(
    cluster_id: int,
    body: ClusterPatchRequest,
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """Rename a cluster; optionally propagate as sticky label to face rows."""
    count = db.clusters.count_rows(f"cluster_id = {cluster_id}")
    if count == 0:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    db.clusters.update(
        where=f"cluster_id = {cluster_id}",
        values={"name": body.name},
    )

    faces_updated = 0
    if body.stick:
        faces_updated = stick_faces(db, cluster_id, body.name)

    return ClusterPatchResponse(
        cluster_id=cluster_id,
        name=body.name,
        faces_updated=faces_updated,
    )
