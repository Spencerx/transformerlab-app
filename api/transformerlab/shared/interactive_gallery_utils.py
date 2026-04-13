"""
Utilities for resolving interactive gallery commands by environment (local/remote).
See galleries.py for the interactive gallery schema documentation.

Run/setup text comes from the task (e.g. task.yaml from the GitHub example repo).
Gallery entries supply metadata (ports, interactive_type) for ngrok and local URL hints only.
"""

import re
from typing import Any, Optional, Tuple

# Prepended to interactive remote setup in the launch route so $SUDO is defined
# without putting that logic in the gallery JSON. Setup content stays on the task.
INTERACTIVE_SUDO_PREFIX = (
    'SUDO=""; if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi; export DEBIAN_FRONTEND=noninteractive;'
)

# Shell command to install ngrok (Debian/Bookworm). Uses $SUDO from INTERACTIVE_SUDO_PREFIX.
NGROK_INSTALL_CMD = (
    "command -v ngrok >/dev/null 2>&1 || (curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | $SUDO tee "
    '/etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | '
    "$SUDO tee /etc/apt/sources.list.d/ngrok.list && $SUDO apt-get update && $SUDO apt-get install -y ngrok)"
)


def _sanitize_tunnel_name(label: Optional[str], port: int) -> str:
    """Return a safe YAML key for a tunnel: from label or port_<port>."""
    if label and isinstance(label, str) and label.strip():
        # Lowercase, replace non-alphanumeric with underscore
        safe = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
        if safe:
            return safe
    return f"port_{port}"


def _build_local_url_echo_command(interactive_type: str) -> Optional[str]:
    """Return shell command that prints local URLs and appends them to /tmp/ngrok.log."""
    # These echoed lines are parsed by tunnel_parser for local provider UX.
    if interactive_type == "jupyter":
        return "echo 'Local URL: http://localhost:8888' | tee -a /tmp/ngrok.log"
    if interactive_type == "vllm":
        return (
            "echo 'Local vLLM API: http://localhost:8000' | tee -a /tmp/ngrok.log; "
            "echo 'Local Open WebUI: http://localhost:8080' | tee -a /tmp/ngrok.log"
        )
    if interactive_type == "ollama":
        return (
            "echo 'Local Ollama API: http://localhost:11434' | tee -a /tmp/ngrok.log; "
            "echo 'Local Open WebUI: http://localhost:8080' | tee -a /tmp/ngrok.log"
        )
    return None


def build_ngrok_tunnel_command(entry_id: str, ports: list[dict[str, Any]]) -> str:
    """
    Build the full ngrok tunnel shell command (install + auth + YAML + start).
    Uses ngrok v2 config with one tunnel per port; supports single or multiple ports.
    """
    if not ports:
        return ""

    install_and_auth = (
        f"{NGROK_INSTALL_CMD}; "
        'if [ -z "${NGROK_AUTH_TOKEN:-}" ]; then '
        "echo 'ERROR: NGROK_AUTH_TOKEN is required for remote interactive tunnels.'; "
        "exit 1; "
        'fi; ngrok config add-authtoken "$NGROK_AUTH_TOKEN"'
    )

    config_path = f"~/ngrok-{entry_id}.yml"
    yaml_lines = ["version: 2", "authtoken: $NGROK_AUTH_TOKEN", "tunnels:"]

    for p in ports:
        port_val = p.get("port") if isinstance(p, dict) else None
        if port_val is None:
            continue
        try:
            port_num = int(port_val)
        except (TypeError, ValueError):
            continue
        protocol = "http"
        if isinstance(p, dict) and isinstance(p.get("protocol"), str):
            protocol = p.get("protocol", "http").strip().lower() or "http"
        if protocol != "tcp":
            protocol = "http"
        label = p.get("label") if isinstance(p, dict) else None
        name = _sanitize_tunnel_name(label, port_num)
        yaml_lines.append(f"  {name}:")
        yaml_lines.append(f"    proto: {protocol}")
        yaml_lines.append(f"    addr: {port_num}")

    # Build printf args: each line single-quoted; authtoken line must expand $NGROK_AUTH_TOKEN
    printf_parts = ["printf '%s\\n'"]
    for line in yaml_lines:
        if line == "authtoken: $NGROK_AUTH_TOKEN":
            printf_parts.append("'authtoken: '\"$NGROK_AUTH_TOKEN\"")
        else:
            escaped = line.replace("'", "'\"'\"'")
            printf_parts.append(f"'{escaped}'")
    printf_cmd = " ".join(printf_parts) + f" > {config_path}"
    # Run ngrok in the background so task-level run commands can continue uninterrupted.
    # Wrap in a subshell so callers can safely append `; <next command>` without producing `&;`.
    start_cmd = f"(ngrok start --all --config {config_path} --log=stdout > /tmp/ngrok.log 2>&1 &)"

    return f"{install_and_auth}; {printf_cmd} && {start_cmd}"


def resolve_interactive_command(
    template_entry: dict,
    environment: str,
    base_command: str = "",
) -> Tuple[str, Optional[str]]:
    """
    Augment the task run command for an interactive template based on environment (local/remote).

    The run command itself always comes from ``base_command`` (task.yaml / stored task run),
    not from the gallery entry.

    Args:
        template_entry: One entry from the interactive gallery (e.g. from get_interactive_gallery).
        environment: "local" or "remote".
        base_command: Run command from the task (e.g. task.yaml ``run``).

    Returns:
        (command, setup_override). ``setup_override`` is always None; setup is not taken from
        gallery entries.
    """
    env = "local" if environment == "local" else "remote"
    interactive_type = str(template_entry.get("interactive_type") or template_entry.get("id") or "").strip()

    resolved_base = (base_command or "").strip()

    if env == "remote":
        entry_id = template_entry.get("id") or "default"
        ports = template_entry.get("ports") or []
        if isinstance(ports, list) and ports:
            ngrok_cmd = build_ngrok_tunnel_command(entry_id, ports)
            if ngrok_cmd:
                if resolved_base:
                    return (f"{ngrok_cmd}; {resolved_base}", None)
                return (ngrok_cmd, None)
    elif env == "local":
        echo_cmd = _build_local_url_echo_command(interactive_type)
        if echo_cmd:
            if resolved_base:
                return (f"{echo_cmd}; {resolved_base}", None)
            return (echo_cmd, None)

    return (resolved_base, None)


def find_interactive_gallery_entry(
    gallery_list: list,
    interactive_gallery_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Find one interactive gallery entry by its unique id.

    Args:
        gallery_list: Result of get_interactive_gallery().
        interactive_gallery_id: Entry id (e.g. "jupyter", "ollama_gradio").

    Returns:
        The gallery entry dict or None if not found.
    """
    if not gallery_list or not interactive_gallery_id:
        return None
    for entry in gallery_list:
        if entry.get("id") == interactive_gallery_id:
            return entry
    return None
