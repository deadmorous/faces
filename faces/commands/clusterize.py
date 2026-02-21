import click

from ..config import Config


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

    click.echo("Clusterizing faces")
    click.echo(f"  database  : {cfg.database}")
    click.echo(f"  threshold : {effective_threshold}")
    click.echo(f"  reset     : {reset}")
    click.echo("[stub] clusterize is not yet implemented.")
