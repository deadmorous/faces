import click

from . import config as _config
from .commands.classify import classify
from .commands.clusterize import clusterize
from .commands.label import label
from .commands.migrate import migrate
from .commands.list_clusters import list_clusters
from .commands.rename import rename
from .commands.scan import scan
from .commands.show import show
from .commands.stick import stick


@click.group()
@click.option("--config", "-c", "config_file", metavar="FILE",
              help="Path to a YAML configuration file.")
@click.option("--db", metavar="FILE",
              help="Path to the index database (overrides config).")
@click.option("--photos-dir", metavar="DIR",
              type=click.Path(file_okay=False, resolve_path=True),
              help="Default photos directory (overrides config).")
@click.version_option()
@click.pass_context
def cli(ctx: click.Context, config_file: str | None, db: str | None,
        photos_dir: str | None) -> None:
    """Find people in your personal photo collection.

    Common workflow:

    \b
        faces scan ~/Photos          # detect and index faces
        faces clusterize             # group faces into people
        faces rename 3 "Alice"       # label cluster 3 as Alice
        faces show Alice             # browse photos with Alice
    """
    ctx.ensure_object(dict)

    try:
        cfg = _config.load(config_file)
    except FileNotFoundError as exc:
        raise click.BadParameter(str(exc), param_hint="--config") from exc

    # CLI options override values from the config file.
    if db:
        from pathlib import Path
        cfg.database = Path(db).expanduser().resolve()
    if photos_dir:
        from pathlib import Path
        cfg.photos_dir = Path(photos_dir)

    ctx.obj = cfg


cli.add_command(migrate)
cli.add_command(scan)
cli.add_command(clusterize)
cli.add_command(classify)
cli.add_command(list_clusters)
cli.add_command(label)
cli.add_command(rename)
cli.add_command(stick)
cli.add_command(show)
