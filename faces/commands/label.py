import sys
from collections import defaultdict

import click
import matplotlib.pyplot as plt

from ..config import Config
from ..db import open_db, stick_faces

_STOP_WORDS = {"exit", "stop", "quit", "q"}


@click.command()
@click.option("--min-size", type=int, default=1, show_default=True,
              help="Only consider clusters with at least this many faces.")
@click.option("--max-size", type=int, default=None,
              help="Only consider clusters with at most this many faces.")
@click.option("--stick", "do_stick", is_flag=True,
              help="Stamp the label onto individual face records as well.")
@click.pass_obj
def label(cfg: Config, min_size: int, max_size: int | None, do_stick: bool) -> None:
    """Interactively label unnamed clusters.

    For each unnamed cluster (largest first) the face grid is shown.
    Type a name and press Enter to label it, or press Enter to skip.
    Type exit / stop / quit to finish early.
    """
    from ..viz import show_cluster

    db = open_db(cfg.database)
    photos_dir = cfg.photos_dir

    # Aggregate clusters: size and name per cluster_id.
    all_rows = db.clusters.search().limit(10_000_000).to_list()
    if not all_rows:
        click.echo("No clusters found. Run `faces clusterize` first.")
        return

    sizes: dict[int, int] = defaultdict(int)
    names: dict[int, str | None] = {}
    for row in all_rows:
        cid = row["cluster_id"]
        sizes[cid] += 1
        if names.get(cid) is None:
            names[cid] = row.get("name")

    # Filter to unnamed clusters in list-clusters order (size desc, id asc).
    clusters = [
        (cid, sizes[cid])
        for cid in sizes
        if names.get(cid) is None
        and sizes[cid] >= min_size
        and (max_size is None or sizes[cid] <= max_size)
    ]
    clusters.sort(key=lambda x: x[0])
    clusters.sort(key=lambda x: x[1], reverse=True)

    if not clusters:
        click.echo("No unnamed clusters match the given filters.")
        return

    click.echo(f"{len(clusters)} unnamed cluster(s) to review. "
               "Enter=skip, exit/stop/quit to finish.\n")

    labeled = 0
    for cid, size in clusters:
        n = show_cluster(cid, db.clusters, db.photos, photos_dir, block=False)
        if n == 0:
            click.echo(f"Cluster {cid} ({size} faces) — could not load images, skipping.")
            continue

        try:
            response = input(f"Cluster {cid} ({size} faces) name: ").strip()
        except EOFError:
            plt.close("all")
            break

        plt.close("all")

        if response.lower() in _STOP_WORDS:
            break
        if not response:
            continue

        db.clusters.update(where=f"cluster_id = {cid}", values={"name": response})
        if do_stick:
            stick_faces(db, cid, response)
        labeled += 1

    click.echo(f"\nDone. {labeled} cluster(s) labeled.")
