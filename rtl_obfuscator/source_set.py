"""Unified input contracts for the supported SystemVerilog source modes."""

from __future__ import annotations

from dataclasses import dataclass
import os
import posixpath
import re
from pathlib import Path
from pathlib import PurePosixPath
from typing import Iterable

from .project_discovery import (
    ProjectAnalysisError,
    _discover_files,
    _discover_sourceset,
)
from .rtl_files import (
    CONTEXT_SUFFIXES,
    HEADER_SUFFIXES,
    SOURCE_SUFFIXES,
    is_context_file,
    is_header_file,
    is_source_file,
)


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
_ENVIRONMENT_VARIABLE = re.compile(
    r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))"
)
_FILELIST_SUFFIXES = frozenset({".f", ".filelist"})
_FILELIST_SHELL_MARKERS = (
    "\\",
    "\"",
    "'",
    "`",
    "$(",
    ";",
    "&&",
    "||",
    "|",
    "<",
    ">",
    "*",
    "?",
    "[",
    "]",
)
_INCLUDE_DIRECTIVE = re.compile(r'^\s*`include\s+"([^"]+)"')


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
    if not is_source_file(absolute):
        raise SourceSetError(
            "SOURCESET_UNSUPPORTED_FILE",
            "source unit must use the .sv or .v suffix",
            relative,
        )
    if not absolute.is_file():
        raise SourceSetError("SOURCESET_FILE_NOT_FOUND", "source file does not exist", relative)
    return relative


def _raise_unsupported_filelist_directive(text: str) -> None:
    raise SourceSetError(
        "SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE",
        "filelist directive or shell syntax is unsupported",
        text,
    )


def _expand_filelist_environment(
    text: str, environment: dict[str, str]
) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain")
        if name not in environment:
            raise SourceSetError(
                "SOURCESET_ENV_UNDEFINED",
                f"filelist environment variable is undefined: {name}",
                name,
            )
        return environment[name]

    expanded = _ENVIRONMENT_VARIABLE.sub(replace, text)
    if "$" in expanded or any(
        marker in expanded for marker in _FILELIST_SHELL_MARKERS
    ):
        _raise_unsupported_filelist_directive(text)
    return expanded


def _resolve_filelist_path(
    *,
    root: Path | None,
    text: str,
    environment: dict[str, str],
    label: str,
    base: Path | None = None,
) -> tuple[Path, str]:
    expanded = _expand_filelist_environment(text, environment)
    path = Path(expanded)
    if path.is_absolute():
        absolute = path.resolve()
    else:
        absolute = ((base if base is not None else root) / path).resolve()
    relative = (
        absolute.as_posix()
        if root is None
        else _relative_to_root(root, absolute, label=label)
    )
    return absolute, relative


def _normalize_filelist_entry(
    *,
    root: Path | None,
    text: str,
    environment: dict[str, str],
    base: Path | None = None,
) -> str:
    absolute, relative = _resolve_filelist_path(
        root=root,
        text=text,
        environment=environment,
        label="filelist entry",
        base=base,
    )
    if absolute.suffix not in SOURCE_SUFFIXES | HEADER_SUFFIXES | CONTEXT_SUFFIXES:
        raise SourceSetError(
            "SOURCESET_UNSUPPORTED_FILE",
            "filelist entries must use .sv, .v, .svh, .vh, or explicit .h suffixes",
            relative,
        )
    if not absolute.is_file():
        raise SourceSetError(
            "SOURCESET_FILE_NOT_FOUND", "filelist entry does not exist", relative
        )
    return relative


def _parse_filelist_context_directive(
    *,
    root: Path | None,
    text: str,
    environment: dict[str, str],
    base: Path | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    if text.startswith("+incdir+"):
        values = text[len("+incdir+") :].split("+")
        if not values or any(not value for value in values):
            raise SourceSetError(
                "SOURCESET_INVALID_ARGUMENT",
                "+incdir+ requires one or more directory paths",
                text,
            )
        directories: list[str] = []
        for value in values:
            absolute, relative = _resolve_filelist_path(
                root=root,
                text=value,
                environment=environment,
                label="include directory",
                base=base,
            )
            if not absolute.is_dir():
                raise SourceSetError(
                    "SOURCESET_FILE_NOT_FOUND",
                    "include directory does not exist or is not a directory",
                    relative,
                )
            if relative not in directories:
                directories.append(relative)
        return tuple(directories), ()

    if text.startswith("+define+"):
        values = text[len("+define+") :].split("+")
        if not values or any(not value for value in values):
            raise SourceSetError(
                "SOURCESET_INVALID_ARGUMENT",
                "+define+ requires one or more NAME[=VALUE] definitions",
                text,
            )
        defines: list[str] = []
        for value in values:
            expanded = _expand_filelist_environment(value, environment)
            _normalize_defines((expanded,))
            defines.append(expanded)
        return (), tuple(defines)

    return None


def _resolve_auto_include_dirs(
    *, filelist: Path, include_dirs: Iterable[Path | str], environment: dict[str, str]
) -> tuple[Path, ...]:
    resolved: list[Path] = []
    base = Path(filelist).expanduser().resolve().parent
    for item in include_dirs:
        path = Path(_expand_filelist_environment(str(item), environment))
        absolute = (path if path.is_absolute() else base / path).resolve()
        if not absolute.is_dir():
            raise SourceSetError(
                "SOURCESET_FILE_NOT_FOUND",
                "include directory does not exist or is not a directory",
                str(absolute),
            )
        if absolute not in resolved:
            resolved.append(absolute)
    return tuple(resolved)


def infer_filelist_root(
    *,
    filelist: Path,
    include_dirs: Iterable[Path | str] = (),
    environment: dict[str, str] | None = None,
) -> Path:
    """Infer the internal path boundary for a filelist-only input."""

    environment_snapshot = dict(os.environ if environment is None else environment)
    path = Path(filelist).expanduser().resolve()
    _, _, filelist_dirs, _, physical_paths = _read_filelist(
        filelist=path,
        root=None,
        environment=environment_snapshot,
        relative_entries_to_filelist=True,
    )
    command_include_dirs = _resolve_auto_include_dirs(
        filelist=path,
        include_dirs=include_dirs,
        environment=environment_snapshot,
    )
    directories = [path.parent]
    directories.extend(Path(item).parent for item in physical_paths)
    directories.extend(Path(item) for item in filelist_dirs)
    directories.extend(command_include_dirs)
    try:
        root = Path(os.path.commonpath([str(item) for item in directories])).resolve()
    except (OSError, ValueError) as error:
        raise SourceSetError(
            "SOURCESET_PATH_OUTSIDE_ROOT",
            "filelist paths do not share a common source root",
            str(path),
        ) from error
    if not root.is_dir():
        raise SourceSetError(
            "SOURCESET_FILE_NOT_FOUND",
            "inferred source root does not exist or is not a directory",
            str(root),
        )
    return root


def _read_filelist(
    *,
    filelist: Path,
    root: Path | None,
    environment: dict[str, str] | None = None,
    relative_entries_to_filelist: bool = False,
) -> tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]
]:
    path = Path(filelist).expanduser().resolve()
    if not path.is_file():
        raise SourceSetError(
            "SOURCESET_FILE_NOT_FOUND", "filelist does not exist", str(path)
        )
    environment_snapshot = dict(os.environ if environment is None else environment)
    source_files: list[str] = []
    header_files: list[str] = []
    include_dirs: list[str] = []
    defines: list[str] = []
    physical_paths: list[str] = []
    context_directives: list[str] = []
    seen: set[str] = set()

    def visit(current: Path, active: tuple[Path, ...]) -> None:
        canonical = current.resolve()
        if canonical in active:
            raise SourceSetError(
                "SOURCESET_FILELIST_CYCLE",
                "filelist includes itself through a recursive -f chain",
                str(canonical),
            )
        if not canonical.is_file():
            raise SourceSetError(
                "SOURCESET_FILE_NOT_FOUND", "filelist does not exist", str(canonical)
            )

        next_active = (*active, canonical)
        for line in canonical.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or text.startswith("//"):
                continue

            tokens = text.split()
            if tokens and tokens[0] == "-f":
                if len(tokens) != 2:
                    if len(tokens) == 1:
                        raise SourceSetError(
                            "SOURCESET_INVALID_ARGUMENT",
                            "-f requires a filelist path on the same line",
                            text,
                        )
                    _raise_unsupported_filelist_directive(text)
                child, child_relative = _resolve_filelist_path(
                    root=root,
                    text=tokens[1],
                    environment=environment_snapshot,
                    label="nested filelist",
                    base=canonical.parent if relative_entries_to_filelist else None,
                )
                if child.suffix not in _FILELIST_SUFFIXES:
                    _raise_unsupported_filelist_directive(child_relative)
                visit(child, next_active)
                continue

            context = _parse_filelist_context_directive(
                root=root,
                text=text,
                environment=environment_snapshot,
                base=canonical.parent if relative_entries_to_filelist else None,
            )
            if context is not None:
                directive_dirs, directive_defines = context
                context_directives.append(text)
                for directory in directive_dirs:
                    if directory not in include_dirs:
                        include_dirs.append(directory)
                defines.extend(directive_defines)
                continue

            if text.startswith(("+", "-")) or len(tokens) != 1:
                _raise_unsupported_filelist_directive(text)

            relative = _normalize_filelist_entry(
                root=root,
                text=tokens[0],
                environment=environment_snapshot,
                base=canonical.parent if relative_entries_to_filelist else None,
            )
            if relative in seen:
                raise SourceSetError(
                    "SOURCESET_DUPLICATE_FILE",
                    "filelist contains a duplicate normalized path",
                    relative,
                )
            seen.add(relative)
            absolute, _ = _resolve_filelist_path(
                root=root,
                text=tokens[0],
                environment=environment_snapshot,
                label="filelist entry",
                base=canonical.parent if relative_entries_to_filelist else None,
            )
            physical_paths.append(absolute.as_posix())
            if is_source_file(relative):
                source_files.append(relative)
            else:
                header_files.append(relative)

    visit(path, ())
    if not source_files and not header_files:
        if context_directives:
            _raise_unsupported_filelist_directive(context_directives[0])
        raise SourceSetError("SOURCESET_EMPTY_FILELIST", "filelist has no valid entries")
    return (
        tuple(source_files),
        tuple(header_files),
        tuple(include_dirs),
        tuple(defines),
        tuple(physical_paths),
    )


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


def _discover_explicit_include_headers(
    *, root: Path, seed_files: Iterable[str], include_dirs: Iterable[str]
) -> tuple[str, ...]:
    """Add only headers named by the bounded filelist/include closure."""

    discovered: list[str] = []
    pending = list(dict.fromkeys(seed_files))
    seen: set[str] = set()
    include_directories = tuple(include_dirs)
    while pending:
        relative = pending.pop(0)
        if relative in seen:
            continue
        seen.add(relative)
        absolute = root / relative
        if not absolute.is_file() or not (
            is_header_file(absolute) or is_context_file(absolute)
        ):
            continue
        for line in absolute.read_text(encoding="utf-8").splitlines():
            match = _INCLUDE_DIRECTIVE.match(line)
            if match is None:
                continue
            include_name = match.group(1)
            include_path = PurePosixPath(include_name)
            candidates: list[str] = []
            local = PurePosixPath(relative).parent / include_path
            if not include_path.is_absolute():
                normalized_local = posixpath.normpath(str(local))
                if normalized_local != ".." and not normalized_local.startswith("../"):
                    candidates.append(normalized_local)
                candidates.extend(
                    str(PurePosixPath(directory) / include_path)
                    for directory in include_directories
                )
            for candidate in candidates:
                candidate_path = root / candidate
                if not candidate_path.is_file():
                    continue
                if not (is_header_file(candidate_path) or is_context_file(candidate_path)):
                    continue
                normalized = _relative_to_root(
                    root, candidate_path, label="include file"
                )
                if normalized not in discovered:
                    discovered.append(normalized)
                if normalized not in seen:
                    pending.append(normalized)
    return tuple(discovered)


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
        + [path for path in _discover_files(root) if is_header_file(path)]
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
    source_root: Path | None = None,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
    top: str | None = None,
) -> SourceSet:
    filelist_path = Path(filelist).expanduser().resolve()
    include_dir_values = tuple(include_dirs)
    auto_root = source_root is None
    root = (
        infer_filelist_root(filelist=filelist_path, include_dirs=include_dir_values)
        if auto_root
        else _normalize_root(source_root)
    )
    resolved_cli_include_dirs = (
        _resolve_auto_include_dirs(
            filelist=filelist_path,
            include_dirs=include_dir_values,
            environment=dict(os.environ),
        )
        if auto_root
        else include_dir_values
    )
    source_files, explicit_headers, filelist_dirs, filelist_defines, _ = _read_filelist(
        filelist=filelist_path,
        root=root,
        environment=dict(os.environ),
        relative_entries_to_filelist=auto_root,
    )
    normalized_dirs = _normalize_include_dirs(
        root=root, include_dirs=(*resolved_cli_include_dirs, *filelist_dirs)
    )
    normalized_defines = _normalize_defines((*filelist_defines, *defines))
    normalized_top = _normalize_top(top, required=False)
    if auto_root:
        include_headers = list(
            _discover_explicit_include_headers(
                root=root,
                seed_files=(*source_files, *explicit_headers),
                include_dirs=normalized_dirs,
            )
        )
    else:
        include_headers = [
            path for path in _discover_files(root) if is_header_file(path)
        ]
    candidates = tuple(
        dict.fromkeys((*source_files, *explicit_headers, *include_headers))
    )
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
    source_files = tuple(path for path in candidates if is_source_file(path))
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
