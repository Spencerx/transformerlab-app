import json

import typer

from transformerlab_cli.state import cli_state
from transformerlab_cli.util.ui import console

app = typer.Typer()


@app.command()
def version() -> None:
    """Display the CLI version and check for updates."""
    from transformerlab_cli.util.pypi import (
        _parse_version,
        describe_install_source,
        fetch_latest_version,
        get_install_source,
        get_installed_version,
    )

    installed = get_installed_version()
    latest = fetch_latest_version()
    source = get_install_source()

    # Determine state: update available, up to date, or check failed
    update_available = False
    check_succeeded = latest is not None and installed != "unknown"
    if check_succeeded and latest is not None:
        try:
            update_available = _parse_version(latest) > _parse_version(installed)
        except ValueError:
            check_succeeded = False

    if cli_state.output_format == "json":
        data: dict[str, object] = {"installed_version": installed, "update_available": update_available}
        if update_available:
            data["latest_version"] = latest
            data["upgrade_command"] = (
                "uv tool install --force transformerlab-cli"
                if source is not None
                else "uv tool upgrade transformerlab-cli"
            )
        if source is not None:
            data["install_source"] = source
        if not check_succeeded:
            data["check_succeeded"] = False
        print(json.dumps(data))
    else:
        console.print(f"v{installed}", highlight=False)
        if update_available:
            console.print(f"[yellow]Update available:[/yellow] v{latest}")
            if source is None:
                console.print("Run [bold]uv tool upgrade transformerlab-cli[/bold] to upgrade.")
            else:
                console.print(
                    f"[yellow]Installed from {describe_install_source(source)}[/yellow]\n"
                    f"[dim]`uv tool upgrade` resolves against this source, not PyPI — "
                    f"it won't fetch v{latest}.\n"
                    f"Pull source updates, or run "
                    f"[bold]uv tool install --force transformerlab-cli[/bold] to switch to PyPI.[/dim]"
                )
        elif check_succeeded:
            console.print("[green]You are up to date.[/green]")
            if source is not None:
                console.print(f"[dim]Installed from {describe_install_source(source)}[/dim]")
        else:
            console.print("[dim]Could not check for updates.[/dim]")
