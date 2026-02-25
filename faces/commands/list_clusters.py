from collections import defaultdict

import click

from ..config import Config
from ..db import open_db


@click.command("list-clusters")
@click.option("--min-size", type=int, default=1, show_default=True,
              help="Only show clusters with at least this many faces.")
@click.option("--max-size", type=int, default=None,
              help="Only show clusters with at most this many faces.")
@click.pass_obj
def list_clusters(cfg: Config, min_size: int, max_size: int | None) -> None:
    """List clusters with their size and assigned name."""
    db = open_db(cfg.database)

    rows = db.clusters.search().limit(10_000_000).to_list()
    if not rows:
        click.echo("No clusters found. Run `faces clusterize` first.")
        return

    # Aggregate per cluster_id: count faces and collect names.
    sizes: dict[int, int] = defaultdict(int)
    names: dict[int, str | None] = {}
    for row in rows:
        cid = row["cluster_id"]
        sizes[cid] += 1
        if names.get(cid) is None:
            names[cid] = row.get("name")

    # Filter and sort by size descending.
    clusters = [
        (cid, sizes[cid], names.get(cid))
        for cid in sizes
        if sizes[cid] >= min_size and (max_size is None or sizes[cid] <= max_size)
    ]
    clusters.sort(key=lambda x: x[0])           # primary: id ascending
    clusters.sort(key=lambda x: x[1], reverse=True)  # secondary: size descending (stable)

    if not clusters:
        click.echo("No clusters match the given filters.")
        return

    click.echo(f"{'ID':>6}  {'SIZE':>5}  NAME")
    click.echo(f"{'─' * 6}  {'─' * 5}  {'─' * 20}")
    for cid, size, name in clusters:
        label = name if name else ""
        click.echo(f"{cid:>6}  {size:>5}  {label}")
