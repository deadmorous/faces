import json
from pathlib import Path

import click

from ..config import Config


JPEG_PATTERNS = ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG")


def scan_photo(cfg: Config, path: Path, force: bool,
               debug_crops_dir: Path | None = None) -> None:
    from ..scanner import detect_faces

    detections = detect_faces(path)
    print(path)
    for d in detections:
        preview = ", ".join(f"{v:.4f}" for v in d.embedding.tolist()[:3])
        print(f"  [{preview}, ...]")

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
@click.pass_obj
def scan(cfg: Config, photos_dir: str | None, recursive: bool, force: bool,
         debug_crops_dir: str | None) -> None:
    """Detect and index faces found in PHOTOS_DIR.

    When PHOTOS_DIR is omitted the value from the configuration file is used.
    New faces are appended to the index; existing entries are skipped unless
    --force is given.
    """
    target = Path(photos_dir) if photos_dir else cfg.photos_dir
    if target is None:
        raise click.UsageError(
            "Provide PHOTOS_DIR on the command line or set photos_dir in the config."
        )

    dbg = Path(debug_crops_dir) if debug_crops_dir else None
    if dbg is not None:
        dbg.mkdir(parents=True, exist_ok=True)

    glob = target.rglob if recursive else target.glob
    for pattern in JPEG_PATTERNS:
        for photo in sorted(glob(pattern)):
            scan_photo(cfg, photo, force, dbg)
