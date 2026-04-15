"""Best-effort Segment telemetry for the CLI installer.

Events are sent to Segment, which fans out to Mixpanel (and any other
destinations configured in the Segment workspace). All public functions
silently swallow exceptions so telemetry never interferes with the
installer's normal operation.
"""

import os
import platform
import sys
import uuid
from pathlib import Path

_initialized = False
_anonymous_id: str | None = None
_context: dict[str, str] = {}
_breadcrumbs: list[dict] = []

# Segment write key for the CLI installer source. Write keys are not
# secrets — the Electron app ships its own write key in the client bundle.
_SEGMENT_WRITE_KEY = "Fsc2l1NSR6T2r4ulQp6XSehXRPIkDeEb"

_ANON_ID_PATH = Path.home() / ".transformerlab" / "installer_id"


def _get_cli_version() -> str:
    try:
        from importlib.metadata import version

        return version("transformerlab-cli")
    except Exception:
        return "unknown"


def _get_or_create_anonymous_id() -> str:
    try:
        if _ANON_ID_PATH.exists():
            existing = _ANON_ID_PATH.read_text().strip()
            if existing:
                return existing
        _ANON_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        new_id = str(uuid.uuid4())
        _ANON_ID_PATH.write_text(new_id)
        return new_id
    except Exception:
        return str(uuid.uuid4())


def _user_opted_out() -> bool:
    val = os.environ.get("DO_NOT_TRACK", "").strip().lower()
    return val in ("1", "true", "yes")


def init(app_version: str | None = None) -> None:
    """Initialise Segment for installer telemetry.

    Call once at the start of the install command. *app_version* is the
    currently-installed Transformer Lab server version (may be ``None``
    if the server has not been installed yet).
    """
    global _initialized, _anonymous_id, _context, _breadcrumbs
    if not _SEGMENT_WRITE_KEY:
        return
    if _user_opted_out():
        return
    try:
        from segment import analytics

        analytics.write_key = _SEGMENT_WRITE_KEY
        analytics.max_retries = 1
        analytics.sync_mode = False

        _anonymous_id = _get_or_create_anonymous_id()
        _context = {
            "source": "cli_installer",
            "cli_version": _get_cli_version(),
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "app_version": app_version or "not_installed",
        }
        _breadcrumbs = []
        _initialized = True
    except Exception:
        pass


def incr(key: str, value: int = 1, **tags: str) -> None:
    """Track an event."""
    if not _initialized:
        return
    try:
        from segment import analytics

        properties = {**_context, "value": value, **tags}
        analytics.track(
            anonymous_id=_anonymous_id,
            event=key,
            properties=properties,
        )
    except Exception:
        pass


def breadcrumb(message: str, **data: str) -> None:
    """Record a breadcrumb. Buffered locally and attached as a property
    on the next error captured via :func:`capture_error`. Segment has no
    native breadcrumb concept, so breadcrumbs are not sent as their own
    events.
    """
    if not _initialized:
        return
    try:
        _breadcrumbs.append({"message": message, "data": data})
        # Keep the buffer bounded.
        if len(_breadcrumbs) > 50:
            del _breadcrumbs[:-50]
    except Exception:
        pass


def capture_error(exc: Exception) -> None:
    """Track an error event with recent breadcrumbs attached."""
    if not _initialized:
        return
    try:
        from segment import analytics

        properties = {
            **_context,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "breadcrumbs": list(_breadcrumbs),
        }
        analytics.track(
            anonymous_id=_anonymous_id,
            event="installer.exception",
            properties=properties,
        )
    except Exception:
        pass


def flush() -> None:
    """Flush pending telemetry. Call before the CLI process exits."""
    if not _initialized:
        return
    try:
        from segment import analytics

        analytics.flush()
    except Exception:
        pass
