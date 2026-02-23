"""Tests for interactive gallery command resolution (resolve_interactive_command, find_interactive_gallery_entry)."""

from transformerlab.shared.interactive_gallery_utils import (
    resolve_interactive_command,
    find_interactive_gallery_entry,
)


# ---- resolve_interactive_command: legacy (no commands field) ----
def test_resolve_legacy_entry_remote():
    """Legacy entry without 'commands' uses top-level command and no setup override."""
    entry = {"id": "jupyter", "command": "jupyter lab --port=8888", "setup": "pip install jupyter"}
    cmd, setup = resolve_interactive_command(entry, "remote", None, None)
    assert cmd == "jupyter lab --port=8888"
    assert setup is None


def test_resolve_legacy_entry_local():
    """Legacy entry: local environment still gets legacy command when no commands.local."""
    entry = {"id": "jupyter", "command": "jupyter lab --port=8888"}
    cmd, setup = resolve_interactive_command(entry, "local", None, None)
    assert cmd == "jupyter lab --port=8888"
    assert setup is None


# ---- resolve_interactive_command: commands.remote / commands.local ----
def test_resolve_commands_remote_default():
    """commands.remote.default is used for remote when no accelerator match."""
    entry = {
        "command": "legacy",
        "commands": {
            "remote": {"default": "ngrok http 8888; jupyter lab"},
        },
    }
    cmd, setup = resolve_interactive_command(entry, "remote", None, None)
    assert cmd == "ngrok http 8888; jupyter lab"
    assert setup is None


def test_resolve_commands_local_default():
    """commands.local.default is used for local."""
    entry = {
        "command": "legacy",
        "commands": {
            "remote": {"default": "ngrok; jupyter"},
            "local": {"default": "jupyter lab; echo http://localhost:8888"},
        },
    }
    cmd, setup = resolve_interactive_command(entry, "local", None, None)
    assert cmd == "jupyter lab; echo http://localhost:8888"
    assert setup is None


def test_resolve_commands_local_falls_back_to_remote():
    """When commands.local is missing, fall back to commands.remote.default."""
    entry = {
        "command": "legacy",
        "commands": {"remote": {"default": "remote-cmd"}},
    }
    cmd, _ = resolve_interactive_command(entry, "local", None, None)
    assert cmd == "remote-cmd"


def test_resolve_commands_remote_falls_back_to_legacy():
    """When commands.remote is missing, use legacy command."""
    entry = {
        "command": "legacy-cmd",
        "setup": "legacy-setup",
        "commands": {"local": {"default": "local-cmd"}},
    }
    cmd, setup = resolve_interactive_command(entry, "remote", None, None)
    assert cmd == "legacy-cmd"
    assert setup is None


def test_resolve_commands_accelerator_from_supported_list():
    """When accelerator is None, supported_accelerators list can provide hint."""
    entry = {
        "command": "legacy",
        "commands": {
            "remote": {"default": "default-cmd", "AMD": "amd-cmd"},
        },
    }
    cmd, _ = resolve_interactive_command(entry, "remote", None, ["AMD"])
    assert cmd == "amd-cmd"


def test_resolve_commands_value_as_object_with_setup():
    """Value can be { command, setup? }; setup_override is returned when present."""
    entry = {
        "command": "legacy",
        "setup": "global-setup",
        "commands": {
            "local": {
                "default": {"command": "local-cmd", "setup": "local-setup"},
            },
        },
    }
    cmd, setup = resolve_interactive_command(entry, "local", None, None)
    assert cmd == "local-cmd"
    assert setup == "local-setup"


def test_resolve_commands_value_as_object_setup_optional():
    """Value { command } with no setup returns setup_override None."""
    entry = {
        "commands": {"remote": {"default": {"command": "run-only"}}},
    }
    cmd, setup = resolve_interactive_command(entry, "remote", None, None)
    assert cmd == "run-only"
    assert setup is None


# ---- find_interactive_gallery_entry ----
def test_find_entry_by_id():
    """find_interactive_gallery_entry returns entry matching interactive_gallery_id."""
    gallery = [
        {"id": "jupyter", "interactive_type": "jupyter"},
        {"id": "vllm", "interactive_type": "vllm"},
    ]
    found = find_interactive_gallery_entry(gallery, interactive_gallery_id="vllm")
    assert found is not None
    assert found["id"] == "vllm"


def test_find_entry_by_interactive_type():
    """find_interactive_gallery_entry falls back to interactive_type when id not found."""
    gallery = [
        {"id": "jupyter", "interactive_type": "jupyter"},
        {"id": "vllm", "interactive_type": "vllm"},
    ]
    found = find_interactive_gallery_entry(gallery, interactive_type="vllm")
    assert found is not None
    assert found["interactive_type"] == "vllm"


def test_find_entry_id_takes_precedence():
    """When both id and interactive_type are given, id is used first."""
    gallery = [
        {"id": "ollama", "interactive_type": "ollama"},
        {"id": "ollama-macos", "interactive_type": "ollama"},
    ]
    found = find_interactive_gallery_entry(gallery, interactive_gallery_id="ollama-macos", interactive_type="ollama")
    assert found is not None
    assert found["id"] == "ollama-macos"


def test_find_entry_empty_list_returns_none():
    """Empty gallery returns None."""
    assert find_interactive_gallery_entry([], interactive_gallery_id="jupyter") is None
    assert find_interactive_gallery_entry([], interactive_type="jupyter") is None


def test_find_entry_not_found_returns_none():
    """When no entry matches, returns None."""
    gallery = [{"id": "jupyter", "interactive_type": "jupyter"}]
    assert find_interactive_gallery_entry(gallery, interactive_gallery_id="nonexistent") is None
    assert find_interactive_gallery_entry(gallery, interactive_type="vllm") is None
