import json

import typer

import transformerlab_cli.util.api as api
from transformerlab_cli.state import cli_state
from transformerlab_cli.util.config import check_configs
from transformerlab_cli.util.ui import console, render_table, render_object

app = typer.Typer()


def _extract_error(response) -> str:
    try:
        return response.json().get("detail", response.text)
    except Exception:
        return response.text


# ──────────────────────────────────────────────
# list
# ──────────────────────────────────────────────

@app.command("list")
def command_model_list():
    """List all models installed on the server."""
    check_configs(output_format=cli_state.output_format)

    if cli_state.output_format != "json":
        with console.status("[bold success]Fetching models...[/bold success]", spinner="dots"):
            response = api.get("/model/list")
    else:
        response = api.get("/model/list")

    if response.status_code == 200:
        models = response.json()
        table_columns = ["model_id", "name", "architecture", "context_size", "params_billion"]
        render_table(data=models, format_type=cli_state.output_format, table_columns=table_columns, title="Models")
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to fetch models. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to fetch models. Status code: {response.status_code}")
        raise typer.Exit(1)


# ──────────────────────────────────────────────
# info
# ──────────────────────────────────────────────

@app.command("info")
def command_model_info(
    model_id: str = typer.Argument(..., help="The model ID to inspect"),
):
    """Show detailed information about a specific model."""
    check_configs(output_format=cli_state.output_format)

    if cli_state.output_format != "json":
        with console.status(f"[bold success]Fetching model list...[/bold success]", spinner="dots"):
            response = api.get("/model/list")
    else:
        response = api.get("/model/list")

    if response.status_code != 200:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to fetch models. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to fetch models. {_extract_error(response)}")
        raise typer.Exit(1)

    models = response.json()
    model = next((m for m in models if m.get("model_id") == model_id), None)

    if model is None:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Model '{model_id}' not found."}))
        else:
            console.print(f"[error]Error:[/error] Model [bold]{model_id}[/bold] not found.")
        raise typer.Exit(1)

    if cli_state.output_format == "json":
        print(json.dumps(model, indent=2, default=str))
    else:
        render_object(model)


# ──────────────────────────────────────────────
# delete
# ──────────────────────────────────────────────

@app.command("delete")
def command_model_delete(
    model_id: str = typer.Argument(..., help="The model ID to delete"),
    from_cache: bool = typer.Option(
        False, "--from-cache", help="Also delete the model from the HuggingFace local cache"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Delete a model from the server."""
    check_configs(output_format=cli_state.output_format)

    if not yes and cli_state.output_format != "json":
        confirmed = typer.confirm(
            f"Are you sure you want to delete model '{model_id}'?", default=False
        )
        if not confirmed:
            console.print("[warning]Aborted.[/warning]")
            raise typer.Exit(0)

    params = f"?model_id={model_id}&delete_from_cache={str(from_cache).lower()}"

    if cli_state.output_format != "json":
        with console.status(f"[bold success]Deleting model '{model_id}'...[/bold success]", spinner="dots"):
            response = api.get(f"/model/delete{params}")
    else:
        response = api.get(f"/model/delete{params}")

    if response.status_code == 200:
        body = response.json()
        if body.get("message") in ("model deleted", "OK"):
            if cli_state.output_format == "json":
                print(json.dumps({"status": "success", "model_id": model_id}))
            else:
                console.print(f"[success]✓[/success] Model [bold]{model_id}[/bold] deleted.")
        else:
            if cli_state.output_format == "json":
                print(json.dumps({"error": body.get("message", "Unknown error")}))
            else:
                console.print(f"[error]Error:[/error] {body.get('message', 'Unknown error')}")
            raise typer.Exit(1)
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to delete model. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to delete model. {_extract_error(response)}")
        raise typer.Exit(1)


# ──────────────────────────────────────────────
# create  (register a new blank model entry)
# ──────────────────────────────────────────────

@app.command("create")
def command_model_create(
    model_id: str = typer.Argument(..., help="Unique model ID (e.g. 'my-org/my-model')"),
    name: str = typer.Option(None, "--name", help="Human-readable name for the model"),
):
    """Create a new (blank) model entry on the server."""
    check_configs(output_format=cli_state.output_format)

    if not name:
        name = model_id

    params = f"?id={model_id}&name={name}"

    if cli_state.output_format != "json":
        with console.status(f"[bold success]Creating model '{model_id}'...[/bold success]", spinner="dots"):
            response = api.get(f"/model/create{params}")
    else:
        response = api.get(f"/model/create{params}")

    if response.status_code == 200:
        body = response.json()
        if body.get("status") == "error":
            if cli_state.output_format == "json":
                print(json.dumps({"error": body.get("message", "Unknown error")}))
            else:
                console.print(f"[error]Error:[/error] {body.get('message', 'Unknown error')}")
            raise typer.Exit(1)
        if cli_state.output_format == "json":
            print(json.dumps({"status": "success", "model_id": model_id, "name": name}))
        else:
            console.print(f"[success]✓[/success] Model [bold]{model_id}[/bold] created.")
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to create model. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to create model. {_extract_error(response)}")
        raise typer.Exit(1)
