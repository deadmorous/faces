import json
from pathlib import Path

import click

from ..config import Config
from ..db import (Database, compute_md5, load_stat_index, open_db,
                  parse_date, photo_is_indexed, store_detections, store_photo,
                  update_photo_path, update_photo_stat)


JPEG_PATTERNS = ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG")


def scan_photo(db: Database, root: Path, path: Path, force: bool,
               stat_index: dict,
               debug_crops_dir: Path | None = None,
               since_ts: float | None = None,
               until_ts: float | None = None) -> None:
    from ..scanner import detect_faces

    stat = path.stat()
    filename  = path.name
    file_size = stat.st_size
    mtime     = stat.st_mtime

    if since_ts is not None and mtime < since_ts:
        return
    if until_ts is not None and mtime >= until_ts:
        return

    if not force:
        entry = stat_index.get((filename, file_size, mtime))
        if entry is not None:
            rel_path = str(path.relative_to(root))
            if entry["path"] != rel_path:
                update_photo_path(db, entry["md5"], rel_path)
            return                               # fast path — in-memory lookup

    md5 = compute_md5(path)
    if not force and photo_is_indexed(db, md5):
        update_photo_stat(db, md5, filename, file_size, mtime)  # backfill
        return

    detections = detect_faces(path)
    print(path)
    for d in detections:
        preview = ", ".join(f"{v:.4f}" for v in d.embedding.tolist()[:3])
        print(f"  [{preview}, ...]")

    store_photo(db, path.relative_to(root), md5, len(detections),
                filename, file_size, mtime)
    store_detections(db, md5, detections)

    if debug_crops_dir is not None:
        img_w, img_h = detections[0].image_size if detections else _image_size(path)
        data = {
            "photo": str(path),
            "width": img_w,
            "height": img_h,
            "faces": [
                {"bbox": d.bbox, "score": round(d.score, 4)}
                for d in detections
            ],
        }
        out = debug_crops_dir / (path.stem + ".json")
        out.write_text(json.dumps(data, indent=2))


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as img:
        return img.size  # (width, height)


@click.command()
@click.argument("photos_dir", required=False, metavar="PHOTOS_DIR",
                type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--recursive/--no-recursive", "-r/ ", default=True, show_default=True,
              help="Descend into subdirectories.")
@click.option("--force", is_flag=True,
              help="Re-index photos that are already in the database.")
@click.option("--debug-crops", "debug_crops_dir", metavar="DIR",
              type=click.Path(file_okay=False, writable=True, resolve_path=True),
              help="Write a JSON file with face bounding boxes for each photo to DIR.")
@click.option("--since", metavar="DATE",
              help="Only process files with mtime >= DATE (YYYY, YYYY-MM, or YYYY-MM-DD).")
@click.option("--until", metavar="DATE",
              help="Only process files with mtime < DATE (exclusive; same format as --since).")
@click.pass_obj
def scan(cfg: Config, photos_dir: str | None, recursive: bool, force: bool,
         debug_crops_dir: str | None, since: str | None, until: str | None) -> None:
    """Detect and index faces found in PHOTOS_DIR.

    When PHOTOS_DIR is omitted the value from the configuration file is used.
    New faces are appended to the index; existing entries are skipped unless
    --force is given.
    """
    try:
        since_ts = parse_date(since) if since else None
        until_ts = parse_date(until, end_of_period=True) if until else None
    except ValueError as e:
        raise click.BadParameter(str(e))
    target = Path(photos_dir) if photos_dir else cfg.photos_dir
    if target is None:
        raise click.UsageError(
            "Provide PHOTOS_DIR on the command line or set photos_dir in the config."
        )

    # Root is the reference point for relative paths stored in the database.
    # cfg.photos_dir is preferred so that scanning a subdirectory still produces
    # paths like "2024/IMG_001.JPG" rather than bare filenames.
    root = cfg.photos_dir if cfg.photos_dir else target

    db = open_db(cfg.database)
    stat_index = load_stat_index(db)

    dbg = Path(debug_crops_dir) if debug_crops_dir else None
    if dbg is not None:
        dbg.mkdir(parents=True, exist_ok=True)

    glob = target.rglob if recursive else target.glob
    for pattern in JPEG_PATTERNS:
        for photo in sorted(glob(pattern)):
            scan_photo(db, root, photo, force, stat_index, dbg, since_ts, until_ts)
