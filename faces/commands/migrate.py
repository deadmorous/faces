from pathlib import Path

import click

from ..config import Config
from ..db import load_unstatted_photos, open_db, update_photo_stat


@click.command()
@click.pass_obj
def migrate(cfg: Config) -> None:
    """Backfill stat columns (filename, file_size, mtime) for pre-existing rows.

    Reads only filesystem metadata — no file content is read and no ML
    inference is performed.  After this command, 'faces scan' can skip all
    already-indexed photos without any file I/O.
    """
    if cfg.photos_dir is None:
        raise click.UsageError(
            "photos_dir must be set (via config or --photos-dir) to resolve paths."
        )

    db = open_db(cfg.database)
    rows = load_unstatted_photos(db)
    if not rows:
        click.echo("Nothing to migrate — all rows already have stat columns.")
        return

    updated = skipped = 0
    for row in rows:
        full_path = cfg.photos_dir / row["path"]
        try:
            s = full_path.stat()
        except OSError:
            skipped += 1
            continue
        update_photo_stat(db, row["md5"], full_path.name, s.st_size, s.st_mtime)
        updated += 1

    msg = f"Backfilled {updated} row(s)."
    if skipped:
        msg += f" {skipped} file(s) not found on disk — skipped."
    click.echo(msg)
