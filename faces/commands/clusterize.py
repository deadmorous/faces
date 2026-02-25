import math
from collections import Counter

import click
from sklearn.cluster import AgglomerativeClustering

from ..config import Config
from ..db import load_all_embeddings, open_db, reset_clusters, store_clusters


@click.command()
@click.option("--threshold", "-t", type=float, metavar="FLOAT",
              help="Similarity threshold (0.0–1.0). Overrides the config value.")
@click.option("--reset", is_flag=True,
              help="Discard existing clusters and rebuild from scratch.")
@click.pass_obj
def clusterize(cfg: Config, threshold: float | None, reset: bool) -> None:
    """Group indexed faces into clusters representing distinct people.

    Faces whose embeddings are closer than THRESHOLD are merged into the same
    cluster.  Run this command after scanning new photos to assign them to
    existing people or create new clusters.
    """
    effective_threshold = threshold if threshold is not None else cfg.cluster_threshold
    eps = math.sqrt(2.0 * (1.0 - effective_threshold))

    db = open_db(cfg.database)

    existing = db.clusters.count_rows()
    if existing > 0 and not reset:
        click.echo(
            f"Clusters table already has {existing} rows. "
            "Use --reset to rebuild."
        )
        return

    if reset and existing > 0:
        reset_clusters(db)

    rows, X = load_all_embeddings(db)
    if len(rows) == 0:
        click.echo("No faces found. Run `faces scan` first.")
        return

    click.echo(f"Clustering {len(rows)} faces …")
    click.echo(f"  database  : {cfg.database}")
    click.echo(f"  threshold : {effective_threshold:.2f}  (eps {eps:.4f})")
    click.echo()

    labels = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=eps,
        metric="euclidean",
        linkage="complete",
    ).fit_predict(X)

    store_clusters(db, rows, labels)

    counts = Counter(labels)
    n_clusters = len(counts)
    click.echo(f"Done. {n_clusters} clusters found.")

    top = counts.most_common(10)
    if top:
        click.echo()
        click.echo("Largest clusters:")
        for cluster_id, count in top:
            click.echo(f"  cluster {cluster_id:3d} : {count:4d} faces")
        remaining = n_clusters - len(top)
        if remaining > 0:
            click.echo(f"  ({remaining} more …)")
