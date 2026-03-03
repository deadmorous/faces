"""/api/people — list named people and show their photos."""

from collections import defaultdict
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_cfg, get_db
from ..models import Person, PersonDetail, PersonPhoto
from ...config import Config
from ...db import Database, load_photo_dates, parse_date

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("", response_model=list[Person], summary="List all named people")
def list_people(
    db: Annotated[Database, Depends(get_db)] = ...,
):
    """List every distinct sticky name with face and photo counts."""
    rows = db.clusters.search().limit(10_000_000).to_list()

    face_counts: dict[str, int] = defaultdict(int)
    photo_sets: dict[str, set] = defaultdict(set)

    for row in rows:
        name = row.get("name")
        if name:
            face_counts[name] += 1
            photo_sets[name].add(row["md5"])

    result = [
        Person(name=name, face_count=face_counts[name], photo_count=len(photo_sets[name]))
        for name in sorted(face_counts)
    ]
    return result


@router.get("/{name}", response_model=PersonDetail, summary="All photos containing a person")
def get_person(
    name: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    absolute: bool = False,
    db: Annotated[Database, Depends(get_db)] = ...,
    cfg: Annotated[Config, Depends(get_cfg)] = ...,
):
    """Return all photos that contain the named person, with their face bboxes."""
    if absolute and cfg.photos_dir is None:
        raise HTTPException(status_code=400, detail="absolute=true requires photos_dir in config")

    try:
        since_ts = parse_date(since) if since else None
        until_ts = parse_date(until, end_of_period=True) if until else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    cluster_rows = (
        db.clusters.search()
        .where(f"name = '{name}'", prefilter=True)
        .limit(10_000_000)
        .to_list()
    )
    if not cluster_rows:
        raise HTTPException(status_code=404, detail=f"Person {name!r} not found")

    # Group bboxes by md5
    md5_bboxes: dict[str, list[list[int]]] = defaultdict(list)
    for row in cluster_rows:
        md5_bboxes[row["md5"]].append(list(row["bbox"]))

    md5s = set(md5_bboxes.keys())

    # Time filter
    if since_ts is not None or until_ts is not None:
        photo_dates = load_photo_dates(db)
        filtered: set[str] = set()
        for md5 in md5s:
            date = photo_dates.get(md5)
            if date is None:
                continue
            if since_ts is not None and date < since_ts:
                continue
            if until_ts is not None and date >= until_ts:
                continue
            filtered.add(md5)
        md5s = filtered

    photos = []
    for md5 in sorted(md5s):
        photo_rows = (
            db.photos.search()
            .where(f"md5 = '{md5}'", prefilter=True)
            .limit(1)
            .to_list()
        )
        if not photo_rows:
            continue
        pr = photo_rows[0]
        rel = pr["path"]
        photos.append(PersonPhoto(
            md5=md5,
            path=rel,
            exif_date=pr.get("exif_date"),
            photo_url=f"/img/photo/{md5}",
            photo_detail_url=f"/api/photos/{md5}",
            face_bboxes=md5_bboxes[md5],
        ))

    return PersonDetail(name=name, photos=photos)
