"""/api/clusterize — trigger agglomerative clustering."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_cfg, get_db
from ..models import ClusterizeRequest, ClusterizeResponse
from ...algo import run_clusterize
from ...config import Config
from ...db import Database

router = APIRouter(prefix="/api/clusterize", tags=["clusterize"])


@router.post("", response_model=ClusterizeResponse, summary="Run clusterize algorithm")
def clusterize(
    body: ClusterizeRequest,
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Trigger agglomerative clustering of all indexed faces.

    Returns ``409 Conflict`` if clusters already exist and ``reset`` is false.
    """
    effective_threshold = body.threshold if body.threshold is not None else cfg.cluster_threshold

    try:
        result = run_clusterize(db=db, threshold=effective_threshold, reset=body.reset)
    except ValueError as e:
        if str(e) == "clusters_exist":
            existing = db.clusters.count_rows()
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Clusters table already has {existing} rows. "
                    "Set reset=true to rebuild."
                ),
            )
        raise HTTPException(status_code=500, detail=str(e))

    return ClusterizeResponse(**result)
