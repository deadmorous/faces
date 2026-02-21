import click

from ..config import Config


@click.command()
@click.argument("cluster_id", metavar="CLUSTER_ID")
@click.argument("name", metavar="NAME")
@click.pass_obj
def rename(cfg: Config, cluster_id: str, name: str) -> None:
    """Assign a human-readable NAME to a face cluster.

    CLUSTER_ID is the numeric or string identifier shown by the 'show' and
    'clusterize' commands.  NAME is a free-form label (e.g. "Alice").
    """
    click.echo(f"Renaming cluster {cluster_id!r} to {name!r}")
    click.echo(f"  database : {cfg.database}")
    click.echo("[stub] rename is not yet implemented.")
