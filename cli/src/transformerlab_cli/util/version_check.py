"""Check for CLI updates via PyPI and display a banner if outdated."""

from rich.console import Console
from rich.panel import Panel


def check_for_update(console: Console) -> None:
    """Check if a newer CLI version is available on PyPI and print a banner if so."""
    try:
        from transformerlab_cli.util.pypi import (
            describe_install_source,
            get_install_source,
            is_update_available,
        )

        installed, latest = is_update_available()
        if latest is None:
            return

        source = get_install_source()
        header = (
            f"[yellow]Update available![/yellow] "
            f"You are running [bold]v{installed}[/bold], but [bold]v{latest}[/bold] is available."
        )
        if source is None:
            body = f"{header}\nRun [bold]uv tool upgrade transformerlab-cli[/bold] to upgrade."
        else:
            body = (
                f"{header}\n"
                f"[dim]Installed from {describe_install_source(source)} — "
                f"`uv tool upgrade` won't fetch PyPI.\n"
                f"Run [bold]uv tool install --force transformerlab-cli[/bold] to switch to PyPI.[/dim]"
            )

        console.print(Panel(body, border_style="yellow", expand=False))
    except Exception:
        # Never let version check failures interrupt CLI usage
        pass
