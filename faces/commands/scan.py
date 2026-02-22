from pathlib import Path

import click

from ..config import Config


JPEG_PATTERNS = ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG")


def scan_photo(cfg: Config, path: Path, force: bool) -> None:
    from ..scanner import get_face_embeddings

    print(path)
    for emb in get_face_embeddings(path):
        values = emb.tolist()
        preview = ", ".join(f"{v:.4f}" for v in values[:3])
        print(f"  [{preview}, ...]")


@click.command()
@click.argument("photos_dir", required=False, metavar="PHOTOS_DIR",
                type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--recursive/--no-recursive", "-r/ ", default=True, show_default=True,
              help="Descend into subdirectories.")
@click.option("--force", is_flag=True,
              help="Re-index photos that are already in the database.")
@click.pass_obj
def scan(cfg: Config, photos_dir: str | None, recursive: bool, force: bool) -> None:
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

    glob = target.rglob if recursive else target.glob
    for pattern in JPEG_PATTERNS:
        for photo in sorted(glob(pattern)):
            scan_photo(cfg, photo, force)
