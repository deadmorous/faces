import click

from ..config import Config
from ..db import SPECIAL_LABELS, load_photo_dates, open_db, parse_date


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

    PERSON is a name assigned via the Classify or Similarity views.
    When --all-people is given, lists every named person instead.
    """
    try:
        since_ts = parse_date(since) if since else None
        until_ts = parse_date(until, end_of_period=True) if until else None
    except ValueError as e:
        raise click.BadParameter(str(e))

    db = open_db(cfg.database)

    if all_people:
        face_rows = db.faces.search().limit(10_000_000).to_list()
        names: dict[str, int] = {}
        for row in face_rows:
            n = row.get("name")
            if n and n not in SPECIAL_LABELS:
                names[n] = names.get(n, 0) + 1
        if not names:
            click.echo("No named people found. Use Classify or Similarity views to add labels.")
            return
        for name, count in sorted(names.items()):
            click.echo(f"{name}  ({count} faces)")
        return

    if person is None:
        raise click.UsageError("Provide PERSON or use --all-people.")

    if absolute and cfg.photos_dir is None:
        raise click.UsageError(
            "--absolute requires photos_dir to be set in the config.")

    safe_person = person.replace("'", "''")
    face_rows = (
        db.faces.search()
        .where(f"name = '{safe_person}'", prefilter=True)
        .limit(10_000_000)
        .to_list()
    )
    if not face_rows:
        raise click.ClickException(f"No labeled faces found for {person!r}.")

    # Collect unique md5s, then apply time filter and look up photo paths.
    md5s = {r["md5"] for r in face_rows}

    if since_ts is not None or until_ts is not None:
        photo_dates = load_photo_dates(db)
        filtered: set[str] = set()
        for md5 in md5s:
            date = photo_dates.get(md5)
            if date is None:
                continue
            if since_ts is not None and date < since_ts:
                continue
            if until_ts is not None and date >= until_ts:
                continue
            filtered.add(md5)
        md5s = filtered

    paths: list[str] = []
    for md5 in md5s:
        photo_rows = (
            db.photos.search()
            .where(f"md5 = '{md5}'", prefilter=True)
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
