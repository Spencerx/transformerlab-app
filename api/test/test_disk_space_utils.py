"""Tests for disk_space_utils.parse_disk_space_gb."""

import pytest

from transformerlab.shared.disk_space_utils import parse_disk_space_gb


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        (0, None),
        (-1, None),
        (50, 50),
        ("50", 50),
        ("100GB", 100),
        ("100gb", 100),
        ("100 g", 100),
        ("  200 GB  ", 200),
        ("100G", 100),
        ("not-a-number", None),
        ("12.5", None),
        (True, None),
    ],
)
def test_parse_disk_space_gb(raw, expected):
    assert parse_disk_space_gb(raw) == expected
