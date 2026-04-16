from __future__ import annotations

from typer.testing import CliRunner

from transformerlab_cli.main import app


runner = CliRunner()


def test_task_init_creates_task_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["task", "init"],
        input="\n2\n4\n\n\npython train.py\n",
    )
    assert result.exit_code == 0
    assert (tmp_path / "task.yaml").exists()

    text = (tmp_path / "task.yaml").read_text()
    assert "name:" in text
    assert "resources:" in text
    assert "run:" in text


def test_task_init_prompts_before_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("name: old\nrun: echo old\n")

    result = runner.invoke(app, ["task", "init"], input="n\n")
    assert result.exit_code == 0
    assert (tmp_path / "task.yaml").read_text() == "name: old\nrun: echo old\n"


def test_task_init_json_mode_does_not_prompt_on_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("name: old\nrun: echo old\n")

    result = runner.invoke(app, ["--format", "json", "task", "init"])
    assert result.exit_code == 1
    assert "already exists" in result.stdout


def test_task_init_uses_editor_for_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("transformerlab_cli.commands.task.os.isatty", lambda _fd: True)
    monkeypatch.setattr(
        "transformerlab_cli.commands.task.typer.edit",
        lambda text: "setup: |\n  pip install -r requirements.txt\nrun: |\n  python train.py\n",
    )

    result = runner.invoke(app, ["task", "init"], input="\n2\n4\n\n")
    assert result.exit_code == 0
    text = (tmp_path / "task.yaml").read_text()
    assert "pip install -r requirements.txt" in text
    assert "python train.py" in text
