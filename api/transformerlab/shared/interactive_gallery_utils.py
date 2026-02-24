"""
Utilities for resolving interactive gallery commands by environment (local/remote)
and accelerator. See galleries.py for the interactive gallery schema documentation.
"""

from typing import Optional, Tuple

# Canonical accelerator keys used in interactive-gallery.json "commands" map
INTERACTIVE_ACCELERATOR_KEYS = ("default", "cpu", "NVIDIA", "AMD", "AppleSilicon")

# Normalize request/provider accelerator strings to gallery keys
_ACCELERATOR_ALIASES = {
    "cuda": "NVIDIA",
    "nvidia": "NVIDIA",
    "rtx": "NVIDIA",
    "a100": "NVIDIA",
    "h100": "NVIDIA",
    "v100": "NVIDIA",
    "rocm": "AMD",
    "amd": "AMD",
    "apple": "AppleSilicon",
    "applesilicon": "AppleSilicon",
    "mps": "AppleSilicon",
    "m1": "AppleSilicon",
    "m2": "AppleSilicon",
    "m3": "AppleSilicon",
}

# Prepended to interactive remote setup in the launch route so $SUDO is defined
# without putting that logic in the gallery JSON. Setup content stays in the gallery.
INTERACTIVE_SUDO_PREFIX = (
    'SUDO=""; if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi; export DEBIAN_FRONTEND=noninteractive;'
)


def _compose_command_from_logic(
    logic: dict,
    interactive_type: str,
    environment: str,
) -> Optional[str]:
    """
    Compose a command from the logic block:
      - core: required
      - tunnel: optional
      - tail_logs: optional

    The caller chooses environment:
      - local: tunnel is omitted
      - remote: tunnel is included if present
    """
    core = logic.get("core")
    if not isinstance(core, str) or not core.strip():
        return None

    tunnel = logic.get("tunnel")
    tail_logs = logic.get("tail_logs")

    parts: list[str] = []

    def _clean(fragment: Optional[str]) -> Optional[str]:
        if not isinstance(fragment, str):
            return None
        cleaned = fragment.strip().rstrip(";").strip()
        return cleaned or None

    def _local_url_echo(t: str) -> Optional[str]:
        # These echoed lines are parsed by tunnel_parser for local provider UX.
        if t == "jupyter":
            return "echo 'Local URL: http://localhost:8888'"
        if t == "vllm":
            return "echo 'Local vLLM API: http://localhost:8000'; echo 'Local Open WebUI: http://localhost:8080'"
        if t == "ollama":
            return "echo 'Local Ollama API: http://localhost:11434'; echo 'Local Open WebUI: http://localhost:8080'"
        return None

    def _strip_ngrok_log_from_tail(cmd: str) -> str:
        # Best-effort: if tail command includes /tmp/ngrok.log, remove it for local runs.
        stripped = cmd
        if stripped.startswith("tail -f ") or stripped.startswith("tail -F "):
            tokens = stripped.split()
            # tokens like: ["tail","-f","/tmp/a.log","/tmp/ngrok.log"]
            kept = [tok for tok in tokens if tok != "/tmp/ngrok.log"]
            stripped = " ".join(kept)
        return stripped

    core_clean = _clean(core)
    if not core_clean:
        return None
    parts.append(core_clean)

    if environment == "local":
        echo_cmd = _local_url_echo(interactive_type)
        if echo_cmd:
            parts.append(echo_cmd)

    # Only include tunnel logic for remote environments
    if environment == "remote":
        tunnel_clean = _clean(tunnel)
        if tunnel_clean:
            parts.append(tunnel_clean)

    tail_clean = _clean(tail_logs)
    if tail_clean:
        if environment == "local":
            tail_clean = _strip_ngrok_log_from_tail(tail_clean)
            if tail_clean.strip() in {"tail", "tail -f", "tail -F"}:
                tail_clean = ""
        parts.append(tail_clean)

    parts = [p for p in parts if isinstance(p, str) and p.strip()]
    if not parts:
        return None
    return "; ".join(parts)


def _normalize_accelerator(
    accelerator: Optional[str],
    supported_list: Optional[list] = None,
    environment: Optional[str] = None,
) -> str:
    """
    Map provider/request accelerator to a gallery key: default, cpu, NVIDIA, AMD, AppleSilicon.

    For local environments we prefer the provider's supported_accelerators (actual machine
    capabilities) over any string parsed from request.accelerators.
    """
    # Prefer explicit capabilities for local environments
    if environment == "local" and supported_list:
        # supported_list usually comes from ProviderConfigBase.supported_accelerators
        if "AppleSilicon" in supported_list:
            return "AppleSilicon"
        if "NVIDIA" in supported_list:
            return "NVIDIA"
        if "AMD" in supported_list:
            return "AMD"
        if "cpu" in supported_list:
            return "cpu"
        return "default"

    if supported_list and len(supported_list) > 0:
        # Use first supported as hint if we can't parse request.accelerators
        first = supported_list[0]
        if isinstance(first, str):
            key = first.strip()
            if key in INTERACTIVE_ACCELERATOR_KEYS:
                return key
            lower = key.lower()
            return _ACCELERATOR_ALIASES.get(lower, "default")

    if not accelerator or not str(accelerator).strip():
        return "default"

    raw = str(accelerator).strip().lower()
    # e.g. "RTX3090:1" -> take part before ":"
    if ":" in raw:
        raw = raw.split(":")[0].strip()
    if not raw:
        return "default"

    return _ACCELERATOR_ALIASES.get(raw, "default")


def resolve_interactive_command(
    template_entry: dict,
    environment: str,
    accelerator: Optional[str] = None,
    supported_accelerators: Optional[list] = None,
) -> Tuple[str, Optional[str]]:
    """
    Resolve the run command and optional setup override for an interactive template
    based on environment (local/remote) and accelerator.

    Args:
        template_entry: One entry from the interactive gallery (e.g. from get_interactive_gallery).
        environment: "local" or "remote".
        accelerator: Optional accelerator string from the request (e.g. "RTX3090:1").
        supported_accelerators: Optional list from provider config (e.g. ["NVIDIA", "cpu"]).

    Returns:
        (command, setup_override). setup_override is None if the entry-level "setup"
        should be used; otherwise the caller should use setup_override for this run.
    """
    env = "local" if environment == "local" else "remote"
    acc = _normalize_accelerator(accelerator, supported_accelerators, environment=env)
    interactive_type = str(template_entry.get("interactive_type") or template_entry.get("id") or "").strip()

    # Prefer per-accelerator logic overrides via commands[accelerator_type].logic
    commands = template_entry.get("commands")
    if isinstance(commands, dict):
        # Legacy commands.local/commands.remote are no longer supported.
        if "local" not in commands and "remote" not in commands:
            candidate = commands.get(acc) or commands.get("default")
            if isinstance(candidate, dict) and isinstance(candidate.get("logic"), dict):
                composed = _compose_command_from_logic(candidate["logic"], interactive_type, env)
                if composed:
                    return (composed, None)

    logic = template_entry.get("logic")
    if isinstance(logic, dict):
        composed = _compose_command_from_logic(logic, interactive_type, env)
        if composed:
            return (composed, None)

    # Final fallback: legacy top-level command only (no setup override)
    legacy_command = template_entry.get("command", "")
    return (legacy_command or "", None)


def find_interactive_gallery_entry(
    gallery_list: list,
    interactive_gallery_id: Optional[str] = None,
    interactive_type: Optional[str] = None,
) -> Optional[dict]:
    """
    Find one interactive gallery entry by id or by interactive_type.
    Used at launch time to re-resolve the template for command resolution.

    Args:
        gallery_list: Result of get_interactive_gallery().
        interactive_gallery_id: Preferred: entry id (e.g. "jupyter", "ollama-macos").
        interactive_type: Fallback: first entry with this interactive_type.

    Returns:
        The gallery entry dict or None if not found.
    """
    if not gallery_list:
        return None
    if interactive_gallery_id:
        for entry in gallery_list:
            if entry.get("id") == interactive_gallery_id:
                return entry
    if interactive_type:
        for entry in gallery_list:
            if entry.get("interactive_type") == interactive_type:
                return entry
    return None
