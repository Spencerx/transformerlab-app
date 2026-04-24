"""Tests for GitHub clone setup script generation."""

from transformerlab.shared.github_utils import generate_github_clone_setup


def test_generate_github_clone_setup_sparse_checkout_targets_current_dir():
    """Sparse checkout should copy into current working directory, not $HOME."""
    script = generate_github_clone_setup(
        repo_url="https://github.com/example/repo.git",
        directory="subdir/task",
    )

    assert "CURRENT_DIR=$PWD" in script
    assert "CURRENT_DIR=$HOME" not in script
    assert "cp -r subdir/task $CURRENT_DIR/" in script


def test_generate_github_clone_setup_full_repo_still_copies_into_cwd():
    """Full-repo clone path should continue copying into CWD."""
    script = generate_github_clone_setup(
        repo_url="https://github.com/example/repo.git",
    )

    assert "cp -r " in script
    assert "/* .; rm -rf " in script
