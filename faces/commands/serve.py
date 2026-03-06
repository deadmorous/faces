"""Start the web server."""

import click

from ..config import Config


@click.command()
@click.option("--port", "-p", default=8000, show_default=True,
              help="TCP port to listen on.")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Network interface to bind.")
@click.option("--reload", is_flag=True, default=False,
              help="Auto-reload on code changes (development mode).")
@click.pass_obj
def serve(cfg: Config, port: int, host: str, reload: bool) -> None:
    """Start the web UI and API server."""
    import uvicorn

    uvicorn.run(
        "faces.web.main:app",
        host=host,
        port=port,
        reload=reload,
    )
