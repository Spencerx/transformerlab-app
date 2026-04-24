"""Filesystem-safe cluster name fragments shared by launch and job resume flows."""

from typing import Optional


def sanitize_cluster_basename(base_name: Optional[str]) -> str:
    """Return a cluster base name that is safe across compute providers.

    Some providers have restrictions on resource names.
    Sanitize generated name so the result is lowercased, underscores are
    replaced with hyphens, and the name is guaranteed to start with a letter.
    """
    if not base_name:
        return "remote-template"
    lowered = base_name.strip().lower()
    normalized = "".join(ch if (ch.isalnum() and ch.isascii()) or ch == "-" else "-" for ch in lowered)
    normalized = normalized.strip("-")
    if not normalized:
        return "remote-template"
    if not normalized[0].isalpha():
        normalized = f"t-{normalized}"
    return normalized
