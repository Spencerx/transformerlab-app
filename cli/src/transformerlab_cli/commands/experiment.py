import json
from urllib.parse import quote

import typer

import transformerlab_cli.util.api as api
from transformerlab_cli.state import cli_state
from transformerlab_cli.util.config import check_configs, get_config, set_config
from transformerlab_cli.util.ui import console, render_table

app = typer.Typer()


def _extract_error_detail(response) -> str:
    try:
        return response.json().get("detail", response.text)
    except (ValueError, KeyError):
        return response.text


@app.command("list")
def command_experiment_list():
    """List all experiments. Marks the current default with a *."""
    check_configs(output_format=cli_state.output_format)
    output_format = cli_state.output_format

    with console.status("[bold success]Fetching experiments...[/bold success]", spinner="dots"):
        response = api.get("/experiment/")

    if response.status_code != 200:
        console.print(f"[error]Error:[/error] Failed to fetch experiments. {_extract_error_detail(response)}")
        raise typer.Exit(1)

    experiments = response.json() or []
    current = get_config("current_experiment")

    if output_format == "json":
        print(json.dumps({"current_experiment": current, "experiments": experiments}))
        return

    rows = [
        {
            "default": "*" if str(exp.get("id")) == str(current) or exp.get("name") == current else "",
            "name": exp.get("name", ""),
        }
        for exp in experiments
    ]
    render_table(data=rows, format_type=output_format, table_columns=["default", "name"], title="Experiments")


@app.command("create")
def command_experiment_create(
    name: str = typer.Argument(..., help="Experiment name"),
    set_default: bool = typer.Option(False, "--set-default", help="Set the new experiment as the default"),
):
    """Create a new experiment."""
    check_configs(output_format=cli_state.output_format)

    with console.status(f"[bold success]Creating experiment {name}...[/bold success]", spinner="dots"):
        response = api.get(f"/experiment/create?name={quote(name)}")

    if response.status_code != 200:
        console.print(f"[error]Error:[/error] Failed to create experiment. {_extract_error_detail(response)}")
        raise typer.Exit(1)

    new_id = response.json()
    console.print(f"[success]✓[/success] Experiment created: [bold]{new_id}[/bold]")

    if set_default:
        set_config("current_experiment", str(new_id), cli_state.output_format)


@app.command("delete")
def command_experiment_delete(
    experiment_id: str = typer.Argument(..., help="Experiment ID to delete"),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Skip confirmation prompt"),
):
    """Delete an experiment."""
    check_configs(output_format=cli_state.output_format)

    if not no_interactive:
        typer.confirm(f"Delete experiment {experiment_id}?", abort=True)

    with console.status(f"[bold success]Deleting experiment {experiment_id}...[/bold success]", spinner="dots"):
        response = api.get(f"/experiment/{experiment_id}/delete")

    if response.status_code != 200:
        console.print(f"[error]Error:[/error] Failed to delete experiment. {_extract_error_detail(response)}")
        raise typer.Exit(1)

    console.print(f"[success]✓[/success] Experiment [bold]{experiment_id}[/bold] deleted.")

    if str(get_config("current_experiment")) == str(experiment_id):
        console.print(
            "[warning]Note:[/warning] This was your default experiment. "
            "Set a new default with [bold]lab experiment set-default <id>[/bold]."
        )


@app.command("set-default")
def command_experiment_set_default(
    experiment_id: str = typer.Argument(..., help="Experiment ID to set as the default"),
):
    """Set the default experiment (stored in ~/.lab/config.json)."""
    set_config("current_experiment", experiment_id, cli_state.output_format)
