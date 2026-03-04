"""Compact and reindex the LanceDB tables for better query performance."""

from datetime import timedelta

import click

from ..config import Config
from ..db import open_db


@click.command()
@click.option("--index/--no-index", default=True, show_default=True,
              help="Create/update scalar indices on md5 columns after compaction.")
@click.pass_obj
def optimize(cfg: Config, index: bool) -> None:
    """Compact database fragments and rebuild indices.

    LanceDB appends each write as a new file fragment.  After thousands of
    scans the tables accumulate one fragment per photo/face, making every
    query open thousands of files.  This command merges them into large chunks
    and optionally creates scalar indices on the md5 column so per-photo
    look-ups are O(log n) instead of O(n).

    Safe to run at any time; the latest data is never touched.
    """
    db = open_db(cfg.database)

    for name, table in [("photos", db.photos), ("faces", db.faces),
                        ("clusters", db.clusters)]:
        before = table.stats()
        nf_before = before.get("fragment_stats", {}).get("num_fragments", "?")
        click.echo(f"{name}: {table.count_rows()} rows, {nf_before} fragments — optimizing…",
                   nl=False)
        table.optimize(cleanup_older_than=timedelta(0))
        after = table.stats()
        nf_after = after.get("fragment_stats", {}).get("num_fragments", "?")
        click.echo(f" → {nf_after} fragments")

        if index and name in ("photos", "faces"):
            existing = {idx["name"] for idx in table.list_indices()}
            if "md5_idx" not in existing:
                click.echo(f"  creating scalar index on {name}.md5…")
                table.create_scalar_index("md5", name="md5_idx")
