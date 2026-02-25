import click

from ..config import Config
from ..db import open_db, stick_faces


@click.command()
@click.argument("cluster_id", metavar="CLUSTER_ID", type=int)
@click.argument("name", metavar="NAME")
@click.option("--stick", "do_stick", is_flag=True,
              help="Also stamp the label onto every face in the cluster "
                   "so it survives re-clustering.")
@click.pass_obj
def rename(cfg: Config, cluster_id: int, name: str, do_stick: bool) -> None:
    """Assign a human-readable NAME to a face cluster.

    CLUSTER_ID is the numeric identifier shown by 'list-clusters'.
    NAME is a free-form label (e.g. "Alice").
    """
    db = open_db(cfg.database)

    count = db.clusters.count_rows(f"cluster_id = {cluster_id}")
    if count == 0:
        raise click.ClickException(f"Cluster {cluster_id} not found.")

    db.clusters.update(
        where=f"cluster_id = {cluster_id}",
        values={"name": name},
    )
    click.echo(f"Cluster {cluster_id} → {name!r}  ({count} faces updated)")

    if do_stick:
        stuck = stick_faces(db, cluster_id, name)
        click.echo(f"  Stuck label on {stuck} faces.")
