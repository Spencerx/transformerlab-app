"""Tests for interactive gallery command resolution (resolve_interactive_command, find_interactive_gallery_entry)."""

from transformerlab.shared.interactive_gallery_utils import (
    build_ngrok_tunnel_command,
    resolve_interactive_command,
    find_interactive_gallery_entry,
)


# ---- build_ngrok_tunnel_command ----
def test_build_ngrok_single_port_http():
    """Single http port produces YAML + ngrok start --all with correct config path."""
    cmd = build_ngrok_tunnel_command("jupyter", [{"port": 8888, "label": "Jupyter Lab", "protocol": "http"}])
    assert 'ngrok config add-authtoken "$NGROK_AUTH_TOKEN"' in cmd
    assert "~/ngrok-jupyter.yml" in cmd
    assert "ngrok start --all" in cmd
    assert "proto: http" in cmd
    assert "addr: 8888" in cmd


def test_build_ngrok_single_port_tcp():
    """Single tcp port produces proto tcp in YAML."""
    cmd = build_ngrok_tunnel_command("ssh", [{"port": 22, "label": "SSH", "protocol": "tcp"}])
    assert "~/ngrok-ssh.yml" in cmd
    assert "ngrok start --all" in cmd
    assert "proto: tcp" in cmd
    assert "addr: 22" in cmd


def test_build_ngrok_multiple_ports():
    """Multiple ports produce multiple tunnels in YAML."""
    cmd = build_ngrok_tunnel_command(
        "vllm",
        [
            {"port": 8000, "label": "vLLM API", "protocol": "http"},
            {"port": 8080, "label": "Open WebUI", "protocol": "http"},
        ],
    )
    assert "~/ngrok-vllm.yml" in cmd
    assert "ngrok start --all" in cmd
    assert "addr: 8000" in cmd
    assert "addr: 8080" in cmd


def test_build_ngrok_empty_ports_returns_empty():
    """Empty ports list returns empty string."""
    assert build_ngrok_tunnel_command("id", []) == ""


# ---- resolve_interactive_command: logic (preferred); tunnel "ngrok" built from ports ----
def test_resolve_logic_remote_tunnel_ngrok_uses_builder():
    """When tunnel is 'ngrok', remote command includes API-generated ngrok (YAML + start --all)."""
    entry = {
        "id": "jupyter",
        "interactive_type": "jupyter",
        "logic": {
            "core": "start-core",
            "tunnel": "ngrok",
            "tail_logs": "tail-logs",
        },
        "ports": [{"port": 8888, "label": "Jupyter Lab", "protocol": "http"}],
    }
    cmd, setup = resolve_interactive_command(entry, "remote")
    assert "start-core" in cmd
    assert "tail-logs" in cmd
    assert 'ngrok config add-authtoken "$NGROK_AUTH_TOKEN"' in cmd
    assert "~/ngrok-jupyter.yml" in cmd
    assert "ngrok start --all" in cmd
    assert setup is None


def test_resolve_fallback_local_appends_local_echo():
    """Fallback local path appends local URL echo for known interactive types."""
    entry = {"id": "ollama", "command": "python run.py"}
    cmd, setup = resolve_interactive_command(entry, "local")
    assert "python run.py" in cmd
    assert "Local Ollama API: http://localhost:11434" in cmd
    assert "Local Open WebUI: http://localhost:8080" in cmd
    assert "tee -a /tmp/ngrok.log" in cmd
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


def test_find_entry_empty_list_returns_none():
    """Empty gallery returns None."""
    assert find_interactive_gallery_entry([], interactive_gallery_id="jupyter") is None


def test_find_entry_no_id_returns_none():
    """No interactive_gallery_id returns None."""
    gallery = [
        {"id": "jupyter", "interactive_type": "jupyter"},
    ]
    assert find_interactive_gallery_entry(gallery) is None


def test_find_entry_not_found_returns_none():
    """When no entry matches, returns None."""
    gallery = [{"id": "jupyter", "interactive_type": "jupyter"}]
    assert find_interactive_gallery_entry(gallery, interactive_gallery_id="nonexistent") is None
