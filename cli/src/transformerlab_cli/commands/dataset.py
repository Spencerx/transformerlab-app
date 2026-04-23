import json
import os

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
def command_dataset_list(
    include_generated: bool = typer.Option(
        True, "--include-generated/--no-generated", help="Include generated datasets"
    ),
):
    """List all available datasets on the server."""
    check_configs(output_format=cli_state.output_format)

    if cli_state.output_format != "json":
        with console.status("[bold success]Fetching datasets...[/bold success]", spinner="dots"):
            response = api.get(f"/data/list?generated={str(include_generated).lower()}")
    else:
        response = api.get(f"/data/list?generated={str(include_generated).lower()}")

    if response.status_code == 200:
        datasets = response.json()
        table_columns = ["dataset_id", "location", "description", "size"]
        render_table(data=datasets, format_type=cli_state.output_format, table_columns=table_columns, title="Datasets")
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to fetch datasets. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to fetch datasets. Status code: {response.status_code}")
        raise typer.Exit(1)


# ──────────────────────────────────────────────
# info
# ──────────────────────────────────────────────

@app.command("info")
def command_dataset_info(
    dataset_id: str = typer.Argument(..., help="The dataset ID to inspect"),
):
    """Show detailed information about a dataset."""
    check_configs(output_format=cli_state.output_format)

    if cli_state.output_format != "json":
        with console.status(f"[bold success]Fetching info for '{dataset_id}'...[/bold success]", spinner="dots"):
            response = api.get(f"/data/info?dataset_id={dataset_id}")
    else:
        response = api.get(f"/data/info?dataset_id={dataset_id}")

    if response.status_code == 200:
        info = response.json()
        if not info:
            if cli_state.output_format == "json":
                print(json.dumps({"error": "Dataset not found."}))
            else:
                console.print(f"[error]Error:[/error] Dataset [bold]{dataset_id}[/bold] not found.")
            raise typer.Exit(1)
        if cli_state.output_format == "json":
            print(json.dumps(info, indent=2, default=str))
        else:
            render_object(info)
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to fetch dataset info. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to fetch dataset info. {_extract_error(response)}")
        raise typer.Exit(1)


# ──────────────────────────────────────────────
# delete
# ──────────────────────────────────────────────

@app.command("delete")
def command_dataset_delete(
    dataset_id: str = typer.Argument(..., help="The dataset ID to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Delete a dataset from the server."""
    check_configs(output_format=cli_state.output_format)

    if not yes and cli_state.output_format != "json":
        confirmed = typer.confirm(
            f"Are you sure you want to delete dataset [bold]{dataset_id}[/bold]?", default=False
        )
        if not confirmed:
            console.print("[warning]Aborted.[/warning]")
            raise typer.Exit(0)

    if cli_state.output_format != "json":
        with console.status(f"[bold success]Deleting dataset '{dataset_id}'...[/bold success]", spinner="dots"):
            response = api.get(f"/data/delete?dataset_id={dataset_id}")
    else:
        response = api.get(f"/data/delete?dataset_id={dataset_id}")

    if response.status_code == 200:
        body = response.json()
        if body.get("status") == "success":
            if cli_state.output_format == "json":
                print(json.dumps({"status": "success", "dataset_id": dataset_id}))
            else:
                console.print(f"[success]✓[/success] Dataset [bold]{dataset_id}[/bold] deleted.")
        else:
            if cli_state.output_format == "json":
                print(json.dumps({"error": body.get("message", "Unknown error")}))
            else:
                console.print(f"[error]Error:[/error] {body.get('message', 'Unknown error')}")
            raise typer.Exit(1)
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to delete dataset. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to delete dataset. {_extract_error(response)}")
        raise typer.Exit(1)


# ──────────────────────────────────────────────
# upload
# ──────────────────────────────────────────────

@app.command("upload")
def command_dataset_upload(
    dataset_id: str = typer.Argument(..., help="The dataset ID (will be created if it does not exist)"),
    files: list[str] = typer.Argument(..., help="One or more local files to upload (.jsonl, .json, or .csv)"),
):
    """Upload local files to a dataset (creates the dataset if it does not exist).

    Example:
        lab dataset upload my-dataset train.jsonl eval.jsonl
    """
    check_configs(output_format=cli_state.output_format)

    # Validate all files exist before doing anything
    for filepath in files:
        if not os.path.isfile(filepath):
            console.print(f"[error]Error:[/error] File not found: {filepath}")
            raise typer.Exit(1)

    # ── Step 1: ensure the dataset exists on the server ──
    if cli_state.output_format != "json":
        with console.status(
            f"[bold success]Ensuring dataset '{dataset_id}' exists...[/bold success]", spinner="dots"
        ):
            check_response = api.get(f"/data/info?dataset_id={dataset_id}")
    else:
        check_response = api.get(f"/data/info?dataset_id={dataset_id}")

    if check_response.status_code == 200 and check_response.json():
        # Dataset already exists
        if cli_state.output_format != "json":
            console.print(f"[info]Dataset [bold]{dataset_id}[/bold] already exists — uploading files into it.[/info]")
    else:
        # Create a new dataset
        if cli_state.output_format != "json":
            with console.status(
                f"[bold success]Creating dataset '{dataset_id}'...[/bold success]", spinner="dots"
            ):
                create_response = api.get(f"/data/new?dataset_id={dataset_id}")
        else:
            create_response = api.get(f"/data/new?dataset_id={dataset_id}")

        if create_response.status_code != 200 or create_response.json().get("status") != "success":
            detail = _extract_error(create_response)
            if cli_state.output_format == "json":
                print(json.dumps({"error": f"Failed to create dataset: {detail}"}))
            else:
                console.print(f"[error]Error:[/error] Could not create dataset. {detail}")
            raise typer.Exit(1)

        if cli_state.output_format != "json":
            console.print(f"[success]✓[/success] Dataset [bold]{dataset_id}[/bold] created.")

    # ── Step 2: upload each file ──
    upload_files = []
    file_handles = []
    try:
        for filepath in files:
            filename = os.path.basename(filepath)
            fh = open(filepath, "rb")
            file_handles.append(fh)
            upload_files.append(("files", (filename, fh, "application/octet-stream")))

        if cli_state.output_format != "json":
            with console.status(
                f"[bold success]Uploading {len(files)} file(s)...[/bold success]", spinner="dots"
            ):
                response = api.post(
                    f"/data/fileupload?dataset_id={dataset_id}",
                    files=upload_files,
                    timeout=300.0,
                )
        else:
            response = api.post(
                f"/data/fileupload?dataset_id={dataset_id}",
                files=upload_files,
                timeout=300.0,
            )
    finally:
        for fh in file_handles:
            fh.close()

    if response.status_code == 200:
        body = response.json()
        if cli_state.output_format == "json":
            print(json.dumps(body))
        else:
            uploaded = body if isinstance(body, list) else body.get("uploaded_files", files)
            console.print(
                f"[success]✓[/success] Uploaded [bold]{len(uploaded)}[/bold] file(s) to dataset [bold]{dataset_id}[/bold]."
            )
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Upload failed. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Upload failed. {_extract_error(response)}")
        raise typer.Exit(1)


# ──────────────────────────────────────────────
# download (from HuggingFace Hub)
# ──────────────────────────────────────────────

@app.command("download")
def command_dataset_download(
    dataset_id: str = typer.Argument(..., help="HuggingFace dataset ID, e.g. 'Trelis/touch-rugby-rules'"),
    config_name: str = typer.Option(None, "--config", help="Dataset config/subset name (optional)"),
):
    """Download a dataset from the HuggingFace Hub to the server."""
    check_configs(output_format=cli_state.output_format)

    params = f"?dataset_id={dataset_id}"
    if config_name:
        params += f"&config_name={config_name}"

    if cli_state.output_format != "json":
        with console.status(
            f"[bold success]Downloading '{dataset_id}' from HuggingFace...[/bold success]", spinner="dots"
        ):
            response = api.get(f"/data/download{params}", timeout=300.0)
    else:
        response = api.get(f"/data/download{params}", timeout=300.0)

    if response.status_code == 200:
        body = response.json()
        if body.get("status") == "success":
            if cli_state.output_format == "json":
                print(json.dumps(body))
            else:
                console.print(f"[success]✓[/success] Dataset [bold]{dataset_id}[/bold] downloaded successfully.")
        else:
            msg = body.get("message", "Unknown error")
            if cli_state.output_format == "json":
                print(json.dumps({"error": msg}))
            else:
                console.print(f"[error]Error:[/error] {msg}")
            raise typer.Exit(1)
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to download dataset. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to download dataset. {_extract_error(response)}")
        raise typer.Exit(1)
