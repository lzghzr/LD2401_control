"""Auditor-local paths; the format parser is a pinned local snapshot."""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def project_root(_start=None):
    return HERE.parents[1]


def lib_dir(_root=None):
    return HERE


def resolve_input(path, _root=None):
    """Input arguments follow the caller's cwd, without searching other trees."""
    return Path(path).expanduser().resolve()
