"""Canonical RTL filename suffix classification for all input adapters."""

from __future__ import annotations

from pathlib import Path


SOURCE_SUFFIXES = frozenset({".sv", ".v"})
HEADER_SUFFIXES = frozenset({".svh", ".vh"})
PHYSICAL_SUFFIXES = SOURCE_SUFFIXES | HEADER_SUFFIXES


def _suffix(path: Path | str) -> str:
    return Path(path).suffix


def is_source_file(path: Path | str) -> bool:
    """Return whether *path* is a supported, lower-case source-unit suffix."""

    return _suffix(path) in SOURCE_SUFFIXES


def is_header_file(path: Path | str) -> bool:
    """Return whether *path* is a supported, lower-case included-header suffix."""

    return _suffix(path) in HEADER_SUFFIXES


def is_physical_rtl_file(path: Path | str) -> bool:
    """Return whether *path* is a supported source or included-header file."""

    return _suffix(path) in PHYSICAL_SUFFIXES
