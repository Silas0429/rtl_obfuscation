"""Unified input contracts for the supported SystemVerilog source modes."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path, PurePosixPath
from typing import Iterable

from .project import (
    ProjectAnalysisError,
    _discover_files,
    _discover_sourceset,
)


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")


@dataclass(frozen=True)
class SourceSet:
    schema_version: int
    origin: str
    source_root: Path
    ordered_source_files: tuple[str, ...]
    included_files: tuple[str, ...]
    include_dirs: tuple[str, ...]
    defines: tuple[tuple[str, str], ...]
    top: str | None
    top_closure_files: tuple[str, ...]
    compile_order: tuple[str, ...]

    def to_report(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "origin": self.origin,
            "source_root": self.source_root.as_posix(),
            "ordered_source_files": list(self.ordered_source_files),
            "included_files": list(self.included_files),
            "include_dirs": list(self.include_dirs),
            "defines": [
                {"name": name, "value": value} for name, value in self.defines
            ],
            "top": self.top,
            "top_closure_files": list(self.top_closure_files),
            "compile_order": list(self.compile_order),
        }


class SourceSetError(ValueError):
    """Stable input failure for a SourceSet adapter."""

    def __init__(self, code: str, message: str, path: str | None = None) -> None:
        self.code = code
        self.message = message
        self.path = path
        super().__init__(f"{code}: {message}")


def _normalize_root(source_root: Path) -> Path:
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise SourceSetError(
            "SOURCESET_FILE_NOT_FOUND",
            "source root does not exist or is not a directory",
            str(root),
        )
    return root


def _relative_to_root(root: Path, path: Path, *, label: str) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as error:
        raise SourceSetError(
            "SOURCESET_PATH_OUTSIDE_ROOT",
            f"{label} is outside source root",
            str(path),
        ) from error


def _normalize_include_dirs(
    *, root: Path, include_dirs: Iterable[Path | str]
) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in include_dirs:
        path = Path(item).expanduser()
        absolute = (root / path).resolve() if not path.is_absolute() else path.resolve()
        relative = _relative_to_root(root, absolute, label="include directory")
        if not absolute.is_dir():
            raise SourceSetError(
                "SOURCESET_FILE_NOT_FOUND",
                "include directory does not exist or is not a directory",
                relative,
            )
        if relative not in normalized:
            normalized.append(relative)
    return tuple(normalized)


def _normalize_defines(defines: Iterable[str]) -> tuple[tuple[str, str], ...]:
    normalized: dict[str, str] = {}
    for item in defines:
        if not isinstance(item, str):
            raise SourceSetError(
                "SOURCESET_INVALID_ARGUMENT", "define must be NAME or NAME=VALUE"
            )
        name, separator, value = item.partition("=")
        if _IDENTIFIER.fullmatch(name) is None:
            raise SourceSetError(
                "SOURCESET_INVALID_ARGUMENT",
                "define must be NAME or NAME=VALUE",
                item,
            )
        normalized[name] = value if separator else "1"
    return tuple(sorted(normalized.items()))


def _normalize_top(top: str | None, *, required: bool) -> str | None:
    if top is None or top == "":
        if required:
            raise SourceSetError(
                "SOURCESET_TOP_REQUIRED", "project-root requires a non-empty top"
            )
        if top == "":
            raise SourceSetError(
                "SOURCESET_INVALID_ARGUMENT", "top must be a SystemVerilog identifier"
            )
        return None
    if not isinstance(top, str) or _IDENTIFIER.fullmatch(top) is None:
        raise SourceSetError(
            "SOURCESET_INVALID_ARGUMENT", "top must be a SystemVerilog identifier"
        )
    return top


def _normalize_source_file(*, root: Path, source_file: Path) -> str:
    path = Path(source_file).expanduser()
    absolute = (root / path).resolve() if not path.is_absolute() else path.resolve()
    relative = _relative_to_root(root, absolute, label="source file")
    if absolute.suffix != ".sv":
        raise SourceSetError(
            "SOURCESET_UNSUPPORTED_FILE", "source unit must use the .sv suffix", relative
        )
    if not absolute.is_file():
        raise SourceSetError("SOURCESET_FILE_NOT_FOUND", "source file does not exist", relative)
    return relative


def _normalize_filelist_entry(*, root: Path, text: str) -> str:
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise SourceSetError(
            "SOURCESET_PATH_OUTSIDE_ROOT", "filelist entry is outside source root", text
        )
    relative = path.as_posix()
    absolute = (root / relative).resolve()
    try:
        absolute.relative_to(root)
    except ValueError as error:
        raise SourceSetError(
            "SOURCESET_PATH_OUTSIDE_ROOT", "filelist entry is outside source root", text
        ) from error
    if absolute.suffix not in (".sv", ".svh"):
        raise SourceSetError(
            "SOURCESET_UNSUPPORTED_FILE",
            "filelist entries must use .sv or .svh suffixes",
            relative,
        )
    if not absolute.is_file():
        raise SourceSetError(
            "SOURCESET_FILE_NOT_FOUND", "filelist entry does not exist", relative
        )
    return relative


def _read_filelist(
    *, filelist: Path, root: Path
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    path = Path(filelist).expanduser().resolve()
    if not path.is_file():
        raise SourceSetError("SOURCESET_FILE_NOT_FOUND", "filelist does not exist", str(path))
    source_files: list[str] = []
    header_files: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        relative = _normalize_filelist_entry(root=root, text=text)
        if relative in seen:
            raise SourceSetError(
                "SOURCESET_DUPLICATE_FILE",
                "filelist contains a duplicate normalized path",
                relative,
            )
        seen.add(relative)
        if relative.endswith(".sv"):
            source_files.append(relative)
        else:
            header_files.append(relative)
    if not source_files and not header_files:
        raise SourceSetError("SOURCESET_EMPTY_FILELIST", "filelist has no valid entries")
    return tuple(source_files), tuple(header_files)


def _map_discovery_error(error: ProjectAnalysisError) -> SourceSetError:
    if error.code == "TOP_NOT_FOUND":
        return SourceSetError("SOURCESET_TOP_NOT_FOUND", error.message, error.file)
    if error.code == "AMBIGUOUS_TOP":
        return SourceSetError("SOURCESET_TOP_AMBIGUOUS", error.message, error.file)
    if error.code == "MISSING_INCLUDE":
        if "outside project root" in error.message:
            return SourceSetError(
                "SOURCESET_PATH_OUTSIDE_ROOT", error.message, error.file
            )
        return SourceSetError("SOURCESET_FILE_NOT_FOUND", error.message, error.file)
    return SourceSetError("SOURCESET_DISCOVERY_FAILED", error.message, error.file)


def _discover(
    *,
    root: Path,
    origin: str,
    ordered_source_files: tuple[str, ...],
    explicit_header_files: tuple[str, ...],
    include_dirs: tuple[str, ...],
    defines: tuple[tuple[str, str], ...],
    top: str | None,
    candidate_files: tuple[str, ...],
    preserve_top_file_order: bool,
    discovery_source_files: tuple[str, ...] | None = None,
    include_all_sources: bool = True,
) -> SourceSet:
    try:
        result = _discover_sourceset(
            root=root,
            candidate_files=candidate_files,
            source_files=(
                ordered_source_files
                if discovery_source_files is None
                else discovery_source_files
            ),
            explicit_header_files=explicit_header_files,
            include_dirs=include_dirs,
            defines=dict(defines),
            top=top,
            preserve_top_file_order=preserve_top_file_order,
            include_all_sources=include_all_sources,
        )
    except ProjectAnalysisError as error:
        raise _map_discovery_error(error) from error
    except (OSError, RuntimeError, ValueError) as error:
        raise SourceSetError("SOURCESET_DISCOVERY_FAILED", str(error)) from error

    public_source_files = (
        result.compile_order if origin == "project-root" else ordered_source_files
    )
    return SourceSet(
        schema_version=1,
        origin=origin,
        source_root=root,
        ordered_source_files=public_source_files,
        included_files=result.included_files,
        include_dirs=include_dirs,
        defines=defines,
        top=top,
        top_closure_files=result.top_closure_files,
        compile_order=public_source_files,
    )


def from_single_file(
    *,
    source_file: Path,
    source_root: Path,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
    top: str | None = None,
) -> SourceSet:
    root = _normalize_root(source_root)
    normalized_source = _normalize_source_file(root=root, source_file=source_file)
    normalized_dirs = _normalize_include_dirs(root=root, include_dirs=include_dirs)
    normalized_defines = _normalize_defines(defines)
    normalized_top = _normalize_top(top, required=False)
    candidates = tuple(
        [normalized_source]
        + [path for path in _discover_files(root) if path.endswith(".svh")]
    )
    return _discover(
        root=root,
        origin="single-file",
        ordered_source_files=(normalized_source,),
        explicit_header_files=(),
        include_dirs=normalized_dirs,
        defines=normalized_defines,
        top=normalized_top,
        candidate_files=candidates,
        preserve_top_file_order=True,
    )


def from_filelist(
    *,
    filelist: Path,
    source_root: Path,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
    top: str | None = None,
) -> SourceSet:
    root = _normalize_root(source_root)
    source_files, explicit_headers = _read_filelist(filelist=filelist, root=root)
    normalized_dirs = _normalize_include_dirs(root=root, include_dirs=include_dirs)
    normalized_defines = _normalize_defines(defines)
    normalized_top = _normalize_top(top, required=False)
    all_headers = tuple(path for path in _discover_files(root) if path.endswith(".svh"))
    candidates = tuple(dict.fromkeys((*source_files, *explicit_headers, *all_headers)))
    return _discover(
        root=root,
        origin="filelist",
        ordered_source_files=source_files,
        explicit_header_files=explicit_headers,
        include_dirs=normalized_dirs,
        defines=normalized_defines,
        top=normalized_top,
        candidate_files=candidates,
        preserve_top_file_order=True,
    )


def from_project_root(
    *,
    project_root: Path,
    top: str | None = None,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
) -> SourceSet:
    root = _normalize_root(project_root)
    normalized_top = _normalize_top(top, required=True)
    normalized_dirs = _normalize_include_dirs(root=root, include_dirs=include_dirs)
    normalized_defines = _normalize_defines(defines)
    candidates = tuple(_discover_files(root))
    source_files = tuple(path for path in candidates if path.endswith(".sv"))
    return _discover(
        root=root,
        origin="project-root",
        ordered_source_files=(),
        explicit_header_files=(),
        include_dirs=normalized_dirs,
        defines=normalized_defines,
        top=normalized_top,
        candidate_files=candidates,
        preserve_top_file_order=False,
        discovery_source_files=source_files,
        include_all_sources=False,
    )
