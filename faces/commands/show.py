import sys

import click

from ..config import Config
from ..db import open_db, parse_date


@click.command()
@click.argument("person", required=False, metavar="PERSON")
@click.option("--all-people", "all_people", is_flag=True,
              help="List all named people in the index instead of photos.")
@click.option("--output", "-o", "output_file", metavar="FILE",
              help="Write paths to FILE instead of stdout.")
@click.option("--absolute", "absolute", is_flag=True,
              help="Print absolute paths. Requires photos_dir in config.")
@click.option("--since", metavar="DATE",
              help="Only include photos with mtime >= DATE (YYYY, YYYY-MM, or YYYY-MM-DD).")
@click.option("--until", metavar="DATE",
              help="Only include photos with mtime < DATE (exclusive; same format as --since).")
@click.pass_obj
def show(cfg: Config, person: str | None, all_people: bool,
         output_file: str | None, absolute: bool,
         since: str | None, until: str | None) -> None:
    """Show photos that contain PERSON.

    PERSON may be a name assigned with 'rename' or a raw cluster ID.
    When --all-people is given, lists every named person instead.
    """
    try:
        since_ts = parse_date(since) if since else None
        until_ts = parse_date(until, end_of_period=True) if until else None
    except ValueError as e:
        raise click.BadParameter(str(e))

    db = open_db(cfg.database)

    if all_people:
        rows = db.clusters.search().limit(10_000_000).to_list()
        names: dict[str, int] = {}
        for row in rows:
            n = row.get("name")
            if n:
                names[n] = names.get(n, 0) + 1
        if not names:
            click.echo("No named people found. Use `rename` to label clusters.")
            return
        for name, count in sorted(names.items()):
            click.echo(f"{name}  ({count} faces)")
        return

    if person is None:
        raise click.UsageError("Provide PERSON or use --all-people.")

    if absolute and cfg.photos_dir is None:
        raise click.UsageError(
            "--absolute requires photos_dir to be set in the config.")

    # Resolve PERSON: try as cluster_id integer, else treat as name.
    try:
        cluster_id = int(person)
        where = f"cluster_id = {cluster_id}"
    except ValueError:
        where = f"name = '{person}'"

    cluster_rows = (
        db.clusters.search()
        .where(where, prefilter=True)
        .to_list()
    )
    if not cluster_rows:
        raise click.ClickException(f"No cluster found for {person!r}.")

    # Collect unique md5s, then look up photo paths.
    md5s = {r["md5"] for r in cluster_rows}
    paths: list[str] = []
    for md5 in md5s:
        where_parts = [f"md5 = '{md5}'"]
        if since_ts is not None:
            where_parts.append(f"mtime >= {since_ts}")
        if until_ts is not None:
            where_parts.append(f"mtime < {until_ts}")
        photo_rows = (
            db.photos.search()
            .where(" AND ".join(where_parts), prefilter=True)
            .limit(1)
            .to_list()
        )
        if not photo_rows:
            continue
        rel = photo_rows[0]["path"]
        if absolute:
            paths.append(str(cfg.photos_dir / rel))
        else:
            paths.append(rel)

    paths.sort()

    out = "\n".join(paths)
    if output_file:
        with open(output_file, "w") as f:
            f.write(out + "\n")
        click.echo(f"Wrote {len(paths)} path(s) to {output_file}.")
    else:
        click.echo(out)
