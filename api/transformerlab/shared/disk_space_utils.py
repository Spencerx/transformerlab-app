"""Parse user-provided disk size strings (e.g. from the queue modal) into whole GB."""

import re
from typing import Optional

_DISK_SPACE_GB_PATTERN = re.compile(r"^\s*(\d+)\s*(?:gb|g)?\s*$", re.IGNORECASE)


def parse_disk_space_gb(value: object) -> Optional[int]:
    """
    Parse a disk size to a positive integer gigabyte value.

    Accepts bare integers, numeric strings, and common suffixes such as ``100GB`` or ``50 g``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    s = str(value).strip()
    if not s:
        return None
    m = _DISK_SPACE_GB_PATTERN.fullmatch(s)
    if m:
        n = int(m.group(1))
        return n if n > 0 else None
    try:
        n = int(s)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None
