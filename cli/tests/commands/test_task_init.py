from __future__ import annotations

from typer.testing import CliRunner

from transformerlab_cli.main import app


runner = CliRunner()


def test_task_init_default_creates_task_yaml_and_main_py(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["task", "init"])
    assert result.exit_code == 0

    assert (tmp_path / "task.yaml").exists()
    assert (tmp_path / "main.py").exists()

    yaml_text = (tmp_path / "task.yaml").read_text()
    assert f"name: {tmp_path.name}" in yaml_text
    assert "resources:" in yaml_text
    assert "run: python main.py" in yaml_text

    main_text = (tmp_path / "main.py").read_text()
    assert "lab.init()" in main_text
    assert "lab.log" in main_text
    assert "lab.update_progress" in main_text
    assert "lab.save_artifact" in main_text


def test_task_init_default_errors_when_task_yaml_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("name: old\nrun: echo old\n")

    result = runner.invoke(app, ["task", "init"])
    assert result.exit_code == 1
    assert "already exists" in result.stdout
    assert (tmp_path / "task.yaml").read_text() == "name: old\nrun: echo old\n"
    assert not (tmp_path / "main.py").exists()


def test_task_init_default_skips_existing_main_py(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.py").write_text("print('existing')\n")

    result = runner.invoke(app, ["task", "init"])
    assert result.exit_code == 0
    assert (tmp_path / "task.yaml").exists()
    assert (tmp_path / "main.py").read_text() == "print('existing')\n"
    assert "Skipped" in result.stdout


def test_task_init_interactive_creates_task_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["task", "init", "--interactive"],
        input="\n2\n4\n\n\npython train.py\n",
    )
    assert result.exit_code == 0
    assert (tmp_path / "task.yaml").exists()
    assert not (tmp_path / "main.py").exists()

    text = (tmp_path / "task.yaml").read_text()
    assert "name:" in text
    assert "resources:" in text
    assert "run:" in text


def test_task_init_interactive_prompts_before_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("name: old\nrun: echo old\n")

    result = runner.invoke(app, ["task", "init", "--interactive"], input="n\n")
    assert result.exit_code == 0
    assert (tmp_path / "task.yaml").read_text() == "name: old\nrun: echo old\n"


def test_task_init_interactive_json_mode_does_not_prompt_on_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("name: old\nrun: echo old\n")

    result = runner.invoke(app, ["--format", "json", "task", "init", "--interactive"])
    assert result.exit_code == 1
    assert "already exists" in result.stdout


def test_task_init_default_force_overwrites_task_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("name: old\nrun: echo old\n")

    result = runner.invoke(app, ["task", "init", "--force"])
    assert result.exit_code == 0
    yaml_text = (tmp_path / "task.yaml").read_text()
    assert "name: old" not in yaml_text
    assert "resources:" in yaml_text


def test_task_init_interactive_force_overwrites_task_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("name: old\nrun: echo old\n")

    result = runner.invoke(app, ["task", "init", "--interactive", "--force"], input="\n2\n4\n\n\npython train.py\n")
    assert result.exit_code == 0
    yaml_text = (tmp_path / "task.yaml").read_text()
    assert "name: old" not in yaml_text
    assert "run:" in yaml_text


def test_task_init_interactive_uses_editor_for_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("transformerlab_cli.commands.task.os.isatty", lambda _fd: True)
    monkeypatch.setattr(
        "transformerlab_cli.commands.task.typer.edit",
        lambda text: "setup: |\n  pip install -r requirements.txt\nrun: |\n  python train.py\n",
    )

    result = runner.invoke(app, ["task", "init", "--interactive"], input="\n2\n4\n\n")
    assert result.exit_code == 0
    text = (tmp_path / "task.yaml").read_text()
    assert "pip install -r requirements.txt" in text
    assert "python train.py" in text
