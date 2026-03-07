"""LanceDB storage for face detections."""

import datetime
import hashlib
from dataclasses import dataclass
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa

from .scanner import FaceDetection
from .timing import timed

# Sentinel labels that mark faces as irrelevant.  They are stored like normal
# sticky labels so they survive re-scans and re-clusters, but commands treat
# them as opaque rejects rather than real person identities.
LABEL_NONFACE = "__nonface__"   # false-positive detection (foot, object, …)
LABEL_FOREIGN = "__foreign__"   # real face but not a person of interest
SPECIAL_LABELS: frozenset[str] = frozenset({LABEL_NONFACE, LABEL_FOREIGN})

_PHOTOS_SCHEMA = pa.schema([
    pa.field("path", pa.utf8()),       # relative to the configured photos root
    pa.field("md5", pa.utf8()),
    pa.field("scanned_at", pa.timestamp("us", tz="UTC")),
    pa.field("face_count", pa.int32()),
    pa.field("filename",  pa.utf8()),
    pa.field("file_size", pa.int64()),
    pa.field("mtime",     pa.float64()),   # st_mtime: seconds since epoch
    pa.field("exif_date", pa.float64()),  # EXIF DateTimeOriginal as local Unix ts (nullable)
])

_FACES_SCHEMA = pa.schema([
    pa.field("md5", pa.utf8()),        # references photos.md5
    pa.field("bbox", pa.list_(pa.int32(), 4)),
    pa.field("score", pa.float32()),
    pa.field("embedding", pa.list_(pa.float32(), 512)),
    pa.field("name", pa.utf8()),       # nullable; sticky label set by `rename --stick`
])

@dataclass
class Database:
    photos: lancedb.table.Table
    faces: lancedb.table.Table


def _open_or_create(conn, name: str, schema):
    """Open an existing table by name, or create it if it doesn't exist."""
    if name in conn.table_names():
        return conn.open_table(name)
    return conn.create_table(name, schema=schema)


def open_db(db_path: Path) -> Database:
    db_path.mkdir(parents=True, exist_ok=True)
    conn = lancedb.connect(db_path)
    faces_table = _open_or_create(conn, "faces", _FACES_SCHEMA)
    # Migrate: add sticky name column if the table pre-dates this feature.
    if "name" not in faces_table.schema.names:
        faces_table.add_columns({"name": "CAST(NULL AS string)"})
    photos_table = _open_or_create(conn, "photos", _PHOTOS_SCHEMA)
    if "filename" not in photos_table.schema.names:
        photos_table.add_columns({
            "filename":  "CAST(NULL AS string)",
            "file_size": "CAST(NULL AS bigint)",
            "mtime":     "CAST(NULL AS double)",
        })
    if "exif_date" not in photos_table.schema.names:
        photos_table.add_columns({"exif_date": "CAST(NULL AS double)"})
    return Database(
        photos=photos_table,
        faces=faces_table,
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


def load_stat_index(db: Database) -> dict[tuple[str, int, float], dict]:
    """Return a dict keyed by (filename, file_size, mtime) for all fully-statted rows.

    Values are {"md5": str, "path": str}. Callers can do O(1) membership tests
    and path-staleness checks without any per-file DB queries.
    """
    rows = (
        db.photos.search()
        .where("filename IS NOT NULL", prefilter=True)
        .limit(10_000_000)
        .to_list()
    )
    return {
        (r["filename"], r["file_size"], r["mtime"]): {
            "md5": r["md5"],
            "path": r["path"],
            "exif_date": r.get("exif_date"),
        }
        for r in rows
    }


def store_photo(db: Database, relative_path: Path, md5: str, face_count: int,
                filename: str, file_size: int, mtime: float,
                exif_date: float | None = None) -> None:
    db.photos.add([{
        "path": str(relative_path),
        "md5": md5,
        "scanned_at": datetime.datetime.now(datetime.timezone.utc),
        "face_count": face_count,
        "filename": filename,
        "file_size": file_size,
        "mtime": mtime,
        "exif_date": exif_date,
    }])


def update_photo_stat(db: Database, md5: str,
                      filename: str, file_size: int, mtime: float,
                      exif_date: float | None = None) -> None:
    safe_name = filename.replace("'", "''")
    values: dict = {"filename": safe_name, "file_size": file_size, "mtime": mtime}
    if exif_date is not None:
        values["exif_date"] = exif_date
    db.photos.update(where=f"md5 = '{md5}'", values=values)


def update_photo_path(db: Database, md5: str, new_path: str) -> None:
    db.photos.update(where=f"md5 = '{md5}'", values={"path": new_path})


def update_photo_exif(db: Database, md5: str, exif_date: float) -> None:
    db.photos.update(where=f"md5 = '{md5}'", values={"exif_date": exif_date})


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


def load_unstatted_photos(db: Database) -> list[dict]:
    """Return all photos rows where filename IS NULL (pre-migration rows)."""
    return (
        db.photos.search()
        .where("filename IS NULL", prefilter=True)
        .limit(10_000_000)
        .to_list()
    )


def parse_date(s: str, end_of_period: bool = False) -> float:
    """Parse YYYY, YYYY-MM, or YYYY-MM-DD to a UTC Unix timestamp.

    With *end_of_period=False* (default) returns the first moment of the
    given period.  With *end_of_period=True* returns the first moment of the
    *next* period — a convenient exclusive upper bound for range queries.

    Raises ValueError on unrecognised input.
    """
    parts = s.split("-")
    try:
        if len(parts) == 1:
            year = int(parts[0])
            if end_of_period:
                dt = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.timezone.utc)
            else:
                dt = datetime.datetime(year, 1, 1, tzinfo=datetime.timezone.utc)
        elif len(parts) == 2:
            year, month = int(parts[0]), int(parts[1])
            if end_of_period:
                month += 1
                if month > 12:
                    year, month = year + 1, 1
            dt = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
        elif len(parts) == 3:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            dt = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
            if end_of_period:
                dt += datetime.timedelta(days=1)
        else:
            raise ValueError
    except (ValueError, OverflowError):
        raise ValueError(f"expected YYYY, YYYY-MM, or YYYY-MM-DD, got {s!r}")
    return dt.timestamp()


def load_photo_dates(db: Database) -> dict[str, float]:
    """Return {md5: date} using exif_date when available, falling back to mtime.

    exif_date (EXIF DateTimeOriginal) reflects when the photo was taken;
    mtime is the filesystem modification time and is used only as a fallback
    for photos that have no EXIF data or were scanned before exif_date was
    added.
    """
    with timed("load_photo_dates: DB scan"):
        rows = db.photos.search().limit(10_000_000).to_list()
    result: dict[str, float] = {}
    for r in rows:
        date = r.get("exif_date") or r.get("mtime")
        if date:
            result[r["md5"]] = date
    return result


def load_all_embeddings(db: Database) -> tuple[list[dict], np.ndarray]:
    """Return (rows, X) where rows has md5, bbox, name; X is shape (N, 512) float32."""
    with timed("load_all_embeddings: DB scan"):
        all_rows = db.faces.search().limit(10_000_000).to_list()
    if not all_rows:
        return [], np.empty((0, 512), dtype=np.float32)
    with timed(f"load_all_embeddings: build numpy array ({len(all_rows)} faces)"):
        rows = [{"md5": r["md5"], "bbox": r["bbox"], "name": r.get("name")}
                for r in all_rows]
        X = np.array([r["embedding"] for r in all_rows], dtype=np.float32)
    return rows, X


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
