"""Check the latest CLI version on PyPI with local file-based caching."""

import json
import os
import time
from importlib.metadata import PackageNotFoundError, distribution
from importlib.metadata import version as pkg_version

import httpx

from transformerlab_cli.util.shared import CONFIG_DIR

PYPI_URL = "https://pypi.org/pypi/transformerlab-cli/json"
CACHE_FILE = os.path.join(CONFIG_DIR, ".version_cache.json")
CACHE_TTL_SECONDS = 4 * 60 * 60  # 4 hours
PACKAGE_NAME = "transformerlab-cli"


def get_installed_version() -> str:
    """Return the installed CLI version from package metadata, or 'unknown'."""
    try:
        return pkg_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "unknown"


def get_install_source() -> dict | None:
    """Return PEP 610 direct_url.json contents for non-PyPI installs, else None.

    PyPI installs have no direct_url.json. Local paths, editable installs, and
    VCS (git) installs do — so its presence means `uv tool upgrade` will resolve
    against that source rather than PyPI.
    """
    try:
        dist = distribution(PACKAGE_NAME)
        raw = dist.read_text("direct_url.json")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        return None


def describe_install_source(direct_url: dict) -> str:
    """Human-readable description of a direct_url.json entry."""
    url = direct_url.get("url", "") or ""
    dir_info = direct_url.get("dir_info") or {}
    vcs_info = direct_url.get("vcs_info") or {}

    if vcs_info:
        vcs = vcs_info.get("vcs", "vcs")
        commit = (vcs_info.get("commit_id") or "")[:7]
        suffix = f" @ {commit}" if commit else ""
        return f"{vcs}: {url}{suffix}"
    if url.startswith("file://"):
        path = url[len("file://") :]
        kind = "editable directory" if dir_info.get("editable") else "local directory"
        return f"{kind}: {path}"
    return url or "unknown source"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a PEP 440 version string into a tuple of ints for comparison.

    Handles pre-release suffixes like '1.0.0rc1' or '0.30.0a2' by stripping
    everything after the numeric release segments.
    """
    import re

    # Strip leading 'v', then extract only the numeric release segments (X.Y.Z)
    v = v.lstrip("v")
    match = re.match(r"^(\d+(?:\.\d+)*)", v)
    if not match:
        raise ValueError(f"Cannot parse version: {v!r}")
    return tuple(int(x) for x in match.group(1).split("."))


def _read_cache() -> dict | None:
    """Read the cache file. Returns parsed dict or None if missing/expired/corrupt."""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_SECONDS:
            return None
        if "latest_version" not in data:
            return None
        return data
    except Exception:
        return None


def _write_cache(latest_version: str) -> None:
    """Write version data + current timestamp to cache file."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"latest_version": latest_version, "timestamp": time.time()}, f)
    except Exception:
        pass


def fetch_latest_version() -> str | None:
    """Check cache first; if stale/missing, query PyPI. Returns latest version string or None."""
    try:
        cached = _read_cache()
        if cached is not None:
            return cached["latest_version"]

        response = httpx.get(PYPI_URL, timeout=3.0)
        if response.status_code != 200:
            return None

        latest = response.json()["info"]["version"]
        _write_cache(latest)
        return latest
    except Exception:
        return None


def is_update_available() -> tuple[str, str | None]:
    """Return (installed_version, latest_or_None).

    ``latest`` is the newer version string when an update is available,
    or ``None`` when the CLI is up-to-date or the check failed.
    """
    try:
        installed = get_installed_version()
        if installed == "unknown":
            return installed, None

        latest = fetch_latest_version()
        if latest is None:
            return installed, None

        if _parse_version(latest) > _parse_version(installed):
            return installed, latest

        return installed, None
    except Exception:
        return "unknown", None
