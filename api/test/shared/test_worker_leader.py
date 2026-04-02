"""Test suite for worker_leader module with mocked flock."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def reset_worker_leader_state():
    """Reset the worker_leader module state before and after each test."""
    import transformerlab.shared.worker_leader as wl

    # Save original state
    original_leader = wl._leader
    original_lock_fd = wl._lock_fd

    # Reset state
    wl._leader = False
    wl._lock_fd = None

    yield

    # Restore state
    wl._leader = original_leader
    wl._lock_fd = original_lock_fd


@pytest.fixture
def mock_lock_path(tmp_path, monkeypatch):
    """Mock the lock path to use a temporary directory."""
    lock_dir = tmp_path / ".transformerlab"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / ".worker_leader.lock"

    import transformerlab.shared.worker_leader as wl

    monkeypatch.setattr(wl, "_lock_path", lambda: lock_file)
    return lock_file


def test_try_acquire_leadership_success(reset_worker_leader_state, mock_lock_path):
    """Test successful leadership acquisition."""
    import transformerlab.shared.worker_leader as wl

    with patch("fcntl.flock") as mock_flock:
        result = wl.try_acquire_leadership()

        assert result is True
        assert wl.is_leader() is True
        mock_flock.assert_called_once()


def test_try_acquire_leadership_already_leader(reset_worker_leader_state, mock_lock_path):
    """Test that acquiring leadership when already leader returns True immediately."""
    import transformerlab.shared.worker_leader as wl

    with patch("fcntl.flock") as mock_flock:
        # First call acquires leadership
        assert wl.try_acquire_leadership() is True
        mock_flock.reset_mock()

        # Second call should return True without trying flock again
        assert wl.try_acquire_leadership() is True
        mock_flock.assert_not_called()


def test_try_acquire_leadership_failure_pid_in_message(reset_worker_leader_state, mock_lock_path, caplog):
    """Test that failed leadership acquisition includes PID in log message."""
    import transformerlab.shared.worker_leader as wl
    import logging

    caplog.set_level(logging.INFO)

    with patch("fcntl.flock") as mock_flock:
        mock_flock.side_effect = BlockingIOError("Resource temporarily unavailable")

        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_open.return_value = mock_file

            result = wl.try_acquire_leadership()

            assert result is False
            assert wl.is_leader() is False

            # Check that fd.close() was called
            mock_file.close.assert_called_once()

            # Check that PID is in the log message
            pid_str = str(os.getpid())
            assert any(pid_str in record.message for record in caplog.records)
            assert any("not the leader" in record.message for record in caplog.records)


def test_try_acquire_leadership_catches_blocking_io_error(reset_worker_leader_state, mock_lock_path):
    """Test that BlockingIOError is caught (not generic OSError)."""
    import transformerlab.shared.worker_leader as wl

    with patch("fcntl.flock") as mock_flock:
        mock_flock.side_effect = BlockingIOError("Resource temporarily unavailable")

        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_open.return_value = mock_file

            result = wl.try_acquire_leadership()

            assert result is False
            assert wl.is_leader() is False


def test_lock_file_created_on_success(reset_worker_leader_state, mock_lock_path):
    """Test that lock file is created when leadership is acquired."""
    import transformerlab.shared.worker_leader as wl

    with patch("fcntl.flock"):
        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_open.return_value = mock_file

            wl.try_acquire_leadership()

            # Verify file was opened and PID was written
            mock_open.assert_called_once()
            mock_file.write.assert_called_once()
            call_args = mock_file.write.call_args[0][0]
            assert str(os.getpid()) == call_args
            mock_file.flush.assert_called_once()


def test_is_leader_initial_state(reset_worker_leader_state):
    """Test that is_leader returns False initially."""
    import transformerlab.shared.worker_leader as wl

    assert wl.is_leader() is False


def test_fcntl_unavailable_fallback(reset_worker_leader_state, mock_lock_path, caplog):
    """Test fallback behavior when fcntl is unavailable (e.g., Windows)."""
    import transformerlab.shared.worker_leader as wl
    import logging

    caplog.set_level(logging.INFO)

    with patch.dict("sys.modules", {"fcntl": None}):
        # This will trigger the ImportError path
        with patch("builtins.__import__", side_effect=ImportError("No module named 'fcntl'")):
            result = wl.try_acquire_leadership()

            assert result is True
            assert wl.is_leader() is True
            assert any("fcntl unavailable" in record.message for record in caplog.records)
