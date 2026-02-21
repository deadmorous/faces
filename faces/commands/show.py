import click

from ..config import Config


@click.command()
@click.argument("person", required=False, metavar="PERSON")
@click.option("--limit", "-n", type=int, default=20, show_default=True,
              help="Maximum number of photos to display.")
@click.option("--all-people", "all_people", is_flag=True,
              help="List all known people instead of photos for one person.")
@click.pass_obj
def show(cfg: Config, person: str | None, limit: int, all_people: bool) -> None:
    """Show photos that contain PERSON.

    PERSON may be a name assigned with the 'rename' command or a raw cluster
    ID.  When PERSON is omitted and --all-people is given, a summary of every
    known person in the index is printed instead.
    """
    if all_people:
        click.echo("All known people:")
        click.echo(f"  database : {cfg.database}")
        click.echo("[stub] show --all-people is not yet implemented.")
        return

    if person is None:
        raise click.UsageError("Provide PERSON or use --all-people to list everyone.")

    click.echo(f"Photos containing {person!r} (limit {limit})")
    click.echo(f"  database : {cfg.database}")
    click.echo("[stub] show is not yet implemented.")
