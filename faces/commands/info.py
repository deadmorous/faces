import datetime
import click
from ..config import Config
from ..db import open_db


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _fmt_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d")


@click.group()
def info():
    """Show information about the database and configuration."""
    pass


@info.command()
@click.pass_obj
def dates(cfg: Config) -> None:
    """Print date ranges covered by scanned photos."""
    db = open_db(cfg.database)
    rows = db.photos.search().select(["mtime", "exif_date"]).limit(10_000_000).to_list()
    mtimes = [r["mtime"] for r in rows if r.get("mtime")]
    exif_dates = [r["exif_date"] for r in rows if r.get("exif_date")]
    if mtimes:
        click.echo(f"mtime:     {_fmt_ts(min(mtimes))}  –  {_fmt_ts(max(mtimes))}  ({len(mtimes)} photos)")
    else:
        click.echo("mtime:     no data")
    if exif_dates:
        click.echo(f"EXIF date: {_fmt_ts(min(exif_dates))}  –  {_fmt_ts(max(exif_dates))}  ({len(exif_dates)} photos)")
    else:
        click.echo("EXIF date: no data")


@info.command("db")
@click.pass_obj
def db_info(cfg: Config) -> None:
    """Print database size and row counts."""
    db = open_db(cfg.database)
    total = sum(f.stat().st_size for f in cfg.database.rglob("*") if f.is_file())
    photos = db.photos.count_rows()
    faces = db.faces.count_rows()
    click.echo(f"Path:   {cfg.database}")
    click.echo(f"Size:   {_fmt_size(total)}")
    click.echo(f"Photos: {photos}")
    click.echo(f"Faces:  {faces}")


@info.command()
@click.pass_obj
def paths(cfg: Config) -> None:
    """Print paths to the config file and database."""
    if cfg.config_path:
        click.echo(f"Config:   {cfg.config_path}")
    else:
        click.echo("Config:   (no file found; using defaults)")
    click.echo(f"Database: {cfg.database}")
