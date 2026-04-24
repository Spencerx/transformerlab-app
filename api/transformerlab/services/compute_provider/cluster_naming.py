"""Filesystem-safe cluster name fragments shared by launch and job resume flows."""

from typing import Optional


# Cap cluster names to 41 characters to stay withing the limit of
# the strictest provider (dstack).
# This means capping the basename portion to 28 characters (use 25 to be safe)
# to leave room for a ``-job-<short_id>`` suffix (13 chars).
_MAX_BASENAME_LENGTH = 25


def sanitize_cluster_basename(base_name: Optional[str]) -> str:
    """Return a cluster base name that is safe across compute providers.

    Some providers have restrictions on resource names.
    Sanitize generated name so the result is:
     - lowercased
     - underscores are replaced with hyphens
     - name is guaranteed to start with a letter
     - no longer than 41 characters
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
    if len(normalized) > _MAX_BASENAME_LENGTH:
        normalized = normalized[:_MAX_BASENAME_LENGTH].rstrip("-")
    return normalized
