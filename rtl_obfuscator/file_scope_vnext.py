"""Canonical physical-file scopes shared by vNext audit and metrics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .source_set import SourceSet


@dataclass(frozen=True)
class FileScopeVNext:
    """One ordered view of the physical files used by a pipeline stage.

    ``physical_files`` is the complete delivery set.  ``files`` is the
    accounting set.  Keeping both in one value prevents the reporting layer
    from accidentally treating the rewrite scope as the gate/manifest scope.
    """

    kind: str
    files: tuple[str, ...]
    physical_files: tuple[str, ...]

    def to_report(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "files": list(self.files),
            "physical_files": len(self.physical_files),
        }


def physical_files(source_set: SourceSet) -> tuple[str, ...]:
    """Return the canonical ordered source-plus-include physical set."""

    result: list[str] = []
    seen_files: set[str] = set()
    for file in (*source_set.ordered_source_files, *source_set.included_files):
        if file in seen_files:
            continue
        seen_files.add(file)
        result.append(file)
    return tuple(result)


def _within_root(file: str, root: str) -> bool:
    if root == ".":
        return True
    try:
        PurePosixPath(file).relative_to(PurePosixPath(root))
    except ValueError:
        return False
    return True


def metric_scope(source_set: SourceSet) -> FileScopeVNext:
    """Build the one accounting scope for both FAST and FULL.

    Rewrite roots are already normalized relative to ``source_root`` by the
    SourceSet adapter.  No directory walk is performed: only files that were
    registered by the authoritative SourceSet can enter the scope.
    """

    all_files = physical_files(source_set)
    roots = tuple(source_set.rewrite_roots)
    if not roots:
        return FileScopeVNext("all_physical", all_files, all_files)
    scoped = tuple(
        file
        for file in all_files
        if any(_within_root(file, root) for root in roots)
    )
    return FileScopeVNext("rewrite_roots", scoped, all_files)


__all__ = ["FileScopeVNext", "metric_scope", "physical_files"]
