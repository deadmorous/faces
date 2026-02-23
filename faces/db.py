"""LanceDB storage for face detections."""

import datetime
import hashlib
from dataclasses import dataclass
from pathlib import Path

import lancedb
import pyarrow as pa

from .scanner import FaceDetection

_PHOTOS_SCHEMA = pa.schema([
    pa.field("path", pa.utf8()),       # relative to the configured photos root
    pa.field("md5", pa.utf8()),
    pa.field("scanned_at", pa.timestamp("us", tz="UTC")),
    pa.field("face_count", pa.int32()),
])

_FACES_SCHEMA = pa.schema([
    pa.field("md5", pa.utf8()),        # references photos.md5
    pa.field("bbox", pa.list_(pa.int32(), 4)),
    pa.field("score", pa.float32()),
    pa.field("embedding", pa.list_(pa.float32(), 512)),
])


@dataclass
class Database:
    photos: lancedb.table.Table
    faces: lancedb.table.Table


def open_db(db_path: Path) -> Database:
    db_path.mkdir(parents=True, exist_ok=True)
    conn = lancedb.connect(db_path)
    return Database(
        photos=conn.create_table("photos", schema=_PHOTOS_SCHEMA, exist_ok=True),
        faces=conn.create_table("faces", schema=_FACES_SCHEMA, exist_ok=True),
    )


def compute_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def photo_is_indexed(db: Database, md5: str) -> bool:
    """Return True if a photo with this *md5* is already in the database."""
    hits = (
        db.photos.search()
        .where(f"md5 = '{md5}'", prefilter=True)
        .limit(1)
        .to_list()
    )
    return len(hits) > 0


def store_photo(db: Database, relative_path: Path, md5: str, face_count: int) -> None:
    db.photos.add([{
        "path": str(relative_path),
        "md5": md5,
        "scanned_at": datetime.datetime.now(datetime.timezone.utc),
        "face_count": face_count,
    }])


def store_detections(db: Database, md5: str,
                     detections: list[FaceDetection]) -> None:
    if not detections:
        return
    db.faces.add([
        {
            "md5": md5,
            "bbox": d.bbox,
            "score": d.score,
            "embedding": d.embedding.tolist(),
        }
        for d in detections
    ])
