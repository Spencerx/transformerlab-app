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
def command_dataset_list():
    """List all dataset groups on the server."""
    check_configs(output_format=cli_state.output_format)

    endpoint = "/asset_versions/groups?asset_type=dataset"
    if cli_state.output_format != "json":
        with console.status("[bold success]Fetching datasets...[/bold success]", spinner="dots"):
            response = api.get(endpoint)
    else:
        response = api.get(endpoint)

    if response.status_code == 200:
        datasets = response.json()
        table_columns = ["group_id", "group_name", "latest_version_label", "version_count", "tags"]
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
    group_id: str = typer.Argument(..., help="The dataset group_id or group_name to inspect"),
):
    """Show detailed information about a specific dataset group."""
    check_configs(output_format=cli_state.output_format)

    endpoint = "/asset_versions/groups?asset_type=dataset"
    if cli_state.output_format != "json":
        with console.status("[bold success]Fetching dataset info...[/bold success]", spinner="dots"):
            response = api.get(endpoint)
    else:
        response = api.get(endpoint)

    if response.status_code != 200:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to fetch datasets. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to fetch datasets. {_extract_error(response)}")
        raise typer.Exit(1)

    datasets = response.json()
    dataset = next(
        (d for d in datasets if d.get("group_id") == group_id or d.get("group_name") == group_id),
        None,
    )

    if dataset is None:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Dataset '{group_id}' not found."}))
        else:
            console.print(f"[error]Error:[/error] Dataset [bold]{group_id}[/bold] not found.")
        raise typer.Exit(1)

    if cli_state.output_format == "json":
        print(json.dumps(dataset, indent=2, default=str))
    else:
        render_object(dataset)


# ──────────────────────────────────────────────
# delete
# ──────────────────────────────────────────────


@app.command("delete")
def command_dataset_delete(
    group_id: str = typer.Argument(..., help="The dataset group_id to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Delete a dataset group and all its versions."""
    check_configs(output_format=cli_state.output_format)

    if not yes and cli_state.output_format != "json":
        confirmed = typer.confirm(
            f"Are you sure you want to delete dataset group '{group_id}' and ALL its versions?", default=False
        )
        if not confirmed:
            console.print("[warning]Aborted.[/warning]")
            raise typer.Exit(0)

    if cli_state.output_format != "json":
        with console.status(f"[bold success]Deleting dataset group '{group_id}'...[/bold success]", spinner="dots"):
            response = api.delete(f"/asset_versions/groups/dataset/{group_id}")
    else:
        response = api.delete(f"/asset_versions/groups/dataset/{group_id}")

    if response.status_code == 200:
        body = response.json()
        if cli_state.output_format == "json":
            print(json.dumps(body))
        else:
            count = body.get("deleted_count", "?")
            console.print(
                f"[success]✓[/success] Dataset group [bold]{group_id}[/bold] deleted ({count} version(s) removed)."
            )
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to delete dataset. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to delete dataset. {_extract_error(response)}")
        raise typer.Exit(1)


# ──────────────────────────────────────────────
# edit
# ──────────────────────────────────────────────


@app.command("edit")
def command_dataset_edit(
    group_id: str = typer.Argument(..., help="The dataset group_id to update"),
    name: str = typer.Option(None, "--name", help="New display name for the dataset group"),
    description: str = typer.Option(None, "--description", help="New description for the dataset group"),
):
    """Edit the name or description of a dataset group."""
    check_configs(output_format=cli_state.output_format)

    payload: dict = {}
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description

    if not payload:
        console.print("[warning]Nothing to update. Provide --name and/or --description.[/warning]")
        raise typer.Exit(0)

    if cli_state.output_format != "json":
        with console.status(f"[bold success]Updating dataset group '{group_id}'...[/bold success]", spinner="dots"):
            response = api.patch(f"/asset_versions/groups/dataset/{group_id}", json_data=payload)
    else:
        response = api.patch(f"/asset_versions/groups/dataset/{group_id}", json_data=payload)

    if response.status_code == 200:
        body = response.json()
        if cli_state.output_format == "json":
            print(json.dumps(body, indent=2, default=str))
        else:
            console.print(f"[success]✓[/success] Dataset group [bold]{group_id}[/bold] updated.")
    else:
        if cli_state.output_format == "json":
            print(json.dumps({"error": f"Failed to update dataset. Status code: {response.status_code}"}))
            raise typer.Exit(1)
        console.print(f"[error]Error:[/error] Failed to update dataset. {_extract_error(response)}")
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
        with console.status(f"[bold success]Ensuring dataset '{dataset_id}' exists...[/bold success]", spinner="dots"):
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
            with console.status(f"[bold success]Creating dataset '{dataset_id}'...[/bold success]", spinner="dots"):
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
            with console.status(f"[bold success]Uploading {len(files)} file(s)...[/bold success]", spinner="dots"):
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
