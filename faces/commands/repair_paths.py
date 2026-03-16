"""faces repair-paths — fix DB entries whose stored path is a bare filename.

These arise when a scan was run without photos_dir configured (so root=target),
making paths relative to a subdirectory rather than the collection root.
"""

import click

from ..config import Config
from ..db import compute_md5, open_db, update_photo_path

JPEG_PATTERNS = ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG")


@click.command("repair-paths")
@click.option("--apply", is_flag=True, default=False,
              help="Write the corrected paths to the database (default: dry-run).")
@click.pass_obj
def repair_paths(cfg: Config, apply: bool) -> None:
    """Find and fix DB photos whose stored path is a bare filename.

    Searches cfg.photos_dir recursively for each affected file, verifies by
    MD5, and (with --apply) updates the database path.
    """
    if cfg.photos_dir is None:
        raise click.UsageError("photos_dir must be set in config or via --photos-dir.")

    db = open_db(cfg.database)

    rows = (
        db.photos.search()
        .select(["md5", "path"])
        .limit(10_000_000)
        .to_list()
    )

    bare = [r for r in rows if "/" not in r["path"] and "\\" not in r["path"]]
    if not bare:
        click.echo("No bare-filename entries found — nothing to do.")
        return

    click.echo(f"Found {len(bare)} bare-filename entr{'y' if len(bare) == 1 else 'ies'}.")

    # Build a filename → list[Path] map once, to avoid repeated rglob per entry.
    click.echo(f"Indexing files under {cfg.photos_dir} …")
    filename_map: dict[str, list] = {}
    for pattern in JPEG_PATTERNS:
        for p in sorted(cfg.photos_dir.rglob(pattern)):
            filename_map.setdefault(p.name, []).append(p)

    fixed = 0
    ambiguous = 0
    not_found = 0

    for row in bare:
        md5 = row["md5"]
        filename = row["path"]
        candidates = filename_map.get(filename, [])

        matches = [p for p in candidates if compute_md5(p) == md5]

        if len(matches) == 1:
            rel = str(matches[0].relative_to(cfg.photos_dir))
            if apply:
                update_photo_path(db, md5, rel)
                click.echo(f"  FIXED  {filename}  →  {rel}")
            else:
                click.echo(f"  would fix  {filename}  →  {rel}")
            fixed += 1
        elif len(matches) > 1:
            click.echo(f"  AMBIGUOUS  {filename}  — {len(matches)} matching files:")
            for m in matches:
                click.echo(f"    {m.relative_to(cfg.photos_dir)}")
            ambiguous += 1
        else:
            click.echo(f"  NOT FOUND  {filename}  (md5={md5})")
            not_found += 1

    click.echo()
    action = "Fixed" if apply else "Would fix"
    click.echo(f"{action}: {fixed}  |  Ambiguous: {ambiguous}  |  Not found: {not_found}")
    if not apply and fixed:
        click.echo("Re-run with --apply to write changes.")
