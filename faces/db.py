"""LanceDB storage for face detections."""

import datetime
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import lancedb
import numpy as np
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
    pa.field("name", pa.utf8()),       # nullable; sticky label set by `rename --stick`
])

_CLUSTERS_SCHEMA = pa.schema([
    pa.field("md5",          pa.utf8()),
    pa.field("bbox",         pa.list_(pa.int32(), 4)),
    pa.field("cluster_id",   pa.int32()),
    pa.field("name",         pa.utf8()),
    pa.field("clustered_at", pa.timestamp("us", tz="UTC")),
])


@dataclass
class Database:
    photos: lancedb.table.Table
    faces: lancedb.table.Table
    clusters: lancedb.table.Table


def open_db(db_path: Path) -> Database:
    db_path.mkdir(parents=True, exist_ok=True)
    conn = lancedb.connect(db_path)
    faces_table = conn.create_table("faces", schema=_FACES_SCHEMA, exist_ok=True)
    # Migrate: add sticky name column if the table pre-dates this feature.
    if "name" not in faces_table.schema.names:
        faces_table.add_columns({"name": "CAST(NULL AS VARCHAR)"})
    return Database(
        photos=conn.create_table("photos", schema=_PHOTOS_SCHEMA, exist_ok=True),
        faces=faces_table,
        clusters=conn.create_table("clusters", schema=_CLUSTERS_SCHEMA, exist_ok=True),
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
            "name": None,
        }
        for d in detections
    ])


def load_all_embeddings(db: Database) -> tuple[list[dict], np.ndarray]:
    """Return (rows, X) where rows has md5, bbox, name; X is shape (N, 512) float32."""
    all_rows = db.faces.search().limit(10_000_000).to_list()
    if not all_rows:
        return [], np.empty((0, 512), dtype=np.float32)
    rows = [{"md5": r["md5"], "bbox": r["bbox"], "name": r.get("name")}
            for r in all_rows]
    X = np.array([r["embedding"] for r in all_rows], dtype=np.float32)
    return rows, X


def store_clusters(db: Database, rows: list[dict], labels: np.ndarray) -> int:
    """Write one cluster row per face. Returns number of auto-named clusters."""
    # Derive cluster name: all named faces in a cluster must agree; unnamed are neutral.
    named_sets: dict[int, set] = defaultdict(set)
    for row, label in zip(rows, labels):
        if row.get("name"):
            named_sets[int(label)].add(row["name"])
    cluster_name: dict[int, str | None] = {
        cid: (names.pop() if len(names) == 1 else None)
        for cid, names in named_sets.items()
    }

    now = datetime.datetime.now(datetime.timezone.utc)
    db.clusters.add([
        {
            "md5": row["md5"],
            "bbox": row["bbox"],
            "cluster_id": int(label),
            "name": cluster_name.get(int(label)),
            "clustered_at": now,
        }
        for row, label in zip(rows, labels)
    ])
    return sum(1 for n in cluster_name.values() if n is not None)


def reset_clusters(db: Database) -> None:
    db.clusters.delete("1=1")


def stick_faces(db: Database, cluster_id: int, name: str) -> int:
    """Stamp *name* onto every face row belonging to *cluster_id*. Returns count."""
    cluster_rows = (
        db.clusters.search()
        .where(f"cluster_id = {cluster_id}", prefilter=True)
        .to_list()
    )
    for row in cluster_rows:
        x1, y1, x2, y2 = row["bbox"]
        db.faces.update(
            where=(f"md5 = '{row['md5']}' AND "
                   f"bbox[1] = {x1} AND bbox[2] = {y1} AND "
                   f"bbox[3] = {x2} AND bbox[4] = {y2}"),
            values={"name": name},
        )
    return len(cluster_rows)


def stick_face(db: Database, md5: str, bbox: list[int], name: str) -> None:
    """Stamp name onto a single face row identified by (md5, bbox)."""
    x1, y1, x2, y2 = bbox
    db.faces.update(
        where=(f"md5 = '{md5}' AND "
               f"bbox[1] = {x1} AND bbox[2] = {y1} AND "
               f"bbox[3] = {x2} AND bbox[4] = {y2}"),
        values={"name": name},
    )


def unstick_faces(db: Database, name: str) -> int:
    """Clear the sticky label *name* from all face rows. Returns count cleared."""
    count = db.faces.count_rows(f"name = '{name}'")
    if count:
        db.faces.update(where=f"name = '{name}'", values={"name": None})
    return count
