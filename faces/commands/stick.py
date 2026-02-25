import click

from ..config import Config
from ..db import open_db, stick_faces, unstick_faces


@click.command()
@click.argument("name", metavar="NAME")
@click.option("--unstick", "do_unstick", is_flag=True,
              help="Remove the sticky label from faces instead of adding it.")
@click.pass_obj
def stick(cfg: Config, name: str, do_unstick: bool) -> None:
    """Propagate a cluster label to (or from) individual face records.

    Without --unstick: stamps NAME onto every face that belongs to a cluster
    currently labeled NAME, so the label survives re-clustering.

    With --unstick: clears the sticky NAME label from all face records,
    making those faces anonymous again for the next clustering run.
    """
    db = open_db(cfg.database)

    if do_unstick:
        count = unstick_faces(db, name)
        click.echo(f"Unstuck {name!r} from {count} faces.")
        return

    # Find all cluster_ids currently labeled NAME.
    rows = (
        db.clusters.search()
        .where(f"name = '{name}'", prefilter=True)
        .to_list()
    )
    cluster_ids = {r["cluster_id"] for r in rows}
    if not cluster_ids:
        raise click.ClickException(
            f"No clusters labeled {name!r}. "
            "Use `rename` to label a cluster first."
        )

    total = 0
    for cid in sorted(cluster_ids):
        n = stick_faces(db, cid, name)
        total += n

    click.echo(f"Stuck {name!r} onto {total} faces "
               f"across {len(cluster_ids)} cluster(s).")
