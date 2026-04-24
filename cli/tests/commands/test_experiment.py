"""Tests for experiment commands."""

from unittest.mock import patch, MagicMock

from typer.testing import CliRunner
from transformerlab_cli.main import app

runner = CliRunner()

SAMPLE_EXPERIMENTS = [
    {"id": "alpha", "name": "alpha"},
    {"id": "beta", "name": "beta"},
]


def _mock_response(status_code: int = 200, json_data=None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data if json_data is not None else {}
    mock.text = ""
    return mock


def test_experiment_help():
    result = runner.invoke(app, ["experiment", "--help"])
    assert result.exit_code == 0
    assert "Experiment management commands" in result.output


@patch("transformerlab_cli.commands.experiment.get_config", return_value="alpha")
@patch("transformerlab_cli.commands.experiment.api.get", return_value=_mock_response(200, SAMPLE_EXPERIMENTS))
@patch("transformerlab_cli.commands.experiment.check_configs")
def test_experiment_list_marks_default(_mock_check, _mock_api, _mock_get_config):
    result = runner.invoke(app, ["experiment", "list"])
    assert result.exit_code == 0
    assert "alpha" in result.output
    assert "beta" in result.output
    assert "*" in result.output


@patch("transformerlab_cli.commands.experiment.set_config")
@patch("transformerlab_cli.commands.experiment.api.get", return_value=_mock_response(200, "my-exp"))
@patch("transformerlab_cli.commands.experiment.check_configs")
def test_experiment_create(_mock_check, mock_api, mock_set_config):
    result = runner.invoke(app, ["experiment", "create", "my-exp"])
    assert result.exit_code == 0
    assert "my-exp" in result.output
    mock_api.assert_called_once()
    assert "name=my-exp" in mock_api.call_args[0][0]
    mock_set_config.assert_not_called()


@patch("transformerlab_cli.commands.experiment.set_config")
@patch("transformerlab_cli.commands.experiment.api.get", return_value=_mock_response(200, "my-exp"))
@patch("transformerlab_cli.commands.experiment.check_configs")
def test_experiment_create_with_set_default(_mock_check, _mock_api, mock_set_config):
    result = runner.invoke(app, ["experiment", "create", "my-exp", "--set-default"])
    assert result.exit_code == 0
    mock_set_config.assert_called_once_with("current_experiment", "my-exp", "pretty")


@patch("transformerlab_cli.commands.experiment.get_config", return_value="other")
@patch(
    "transformerlab_cli.commands.experiment.api.get",
    return_value=_mock_response(200, {"message": "Experiment beta deleted"}),
)
@patch("transformerlab_cli.commands.experiment.check_configs")
def test_experiment_delete(_mock_check, _mock_api, _mock_get_config):
    result = runner.invoke(app, ["experiment", "delete", "beta", "--no-interactive"])
    assert result.exit_code == 0
    assert "deleted" in result.output.lower()


@patch("transformerlab_cli.commands.experiment.get_config", return_value="beta")
@patch(
    "transformerlab_cli.commands.experiment.api.get",
    return_value=_mock_response(200, {"message": "Experiment beta deleted"}),
)
@patch("transformerlab_cli.commands.experiment.check_configs")
def test_experiment_delete_current_warns(_mock_check, _mock_api, _mock_get_config):
    result = runner.invoke(app, ["experiment", "delete", "beta", "--no-interactive"])
    assert result.exit_code == 0
    assert "default experiment" in result.output


@patch("transformerlab_cli.commands.experiment.set_config")
@patch("transformerlab_cli.commands.experiment.check_configs")
def test_experiment_set_default(_mock_check, mock_set_config):
    result = runner.invoke(app, ["experiment", "set-default", "beta"])
    assert result.exit_code == 0
    mock_set_config.assert_called_once_with("current_experiment", "beta", "pretty")
