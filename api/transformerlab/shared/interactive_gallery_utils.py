"""
Utilities for resolving interactive gallery commands by environment (local/remote)
and accelerator. See galleries.py for the interactive gallery schema documentation.
"""

from typing import Any, Optional, Tuple

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


def _extract_command_and_setup(value: Any, legacy_setup: Optional[str]) -> Tuple[str, Optional[str]]:
    """Return (command, setup_override). setup_override is None to use legacy_setup."""
    if isinstance(value, str):
        return (value, None)
    if isinstance(value, dict):
        cmd = value.get("command")
        if cmd is not None:
            return (str(cmd), value.get("setup"))
    return ("", None)


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

    commands = template_entry.get("commands")
    legacy_command = template_entry.get("command", "")
    legacy_setup = template_entry.get("setup")

    if not isinstance(commands, dict):
        return (legacy_command or "", None)

    # 1) commands[environment][accelerator]
    env_map = commands.get(env)
    if isinstance(env_map, dict):
        val = env_map.get(acc)
        if val is not None:
            cmd, setup = _extract_command_and_setup(val, legacy_setup)
            if cmd:
                return (cmd, setup)
        val = env_map.get("default")
        if val is not None:
            cmd, setup = _extract_command_and_setup(val, legacy_setup)
            if cmd:
                return (cmd, setup)

    # 2) commands.remote[accelerator] then commands.remote.default
    remote_map = commands.get("remote")
    if isinstance(remote_map, dict):
        val = remote_map.get(acc) or remote_map.get("default")
        if val is not None:
            cmd, setup = _extract_command_and_setup(val, legacy_setup)
            if cmd:
                return (cmd, setup)

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
