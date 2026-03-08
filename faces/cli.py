import click

from . import config as _config
from .commands.classify import classify
from .commands.info import info
from .commands.optimize import optimize
from .commands.scan import scan
from .commands.serve import serve
from .commands.show import show


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


cli.add_command(scan)
cli.add_command(classify)
cli.add_command(info)
cli.add_command(show)
cli.add_command(optimize)
cli.add_command(serve)
