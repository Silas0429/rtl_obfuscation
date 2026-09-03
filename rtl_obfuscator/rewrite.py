"""Rewrite and restore selected SystemVerilog identifiers."""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Any
import unicodedata

from rtl_obfuscator import orchestration_vnext
from rtl_obfuscator import restore_vnext
from rtl_obfuscator.category_registry_vnext import (
    CANONICAL_CATEGORIES,
    CategoryRegistryError,
    normalize_categories,
)
from rtl_obfuscator.performance_probe import (
    COMPILE_CATALOG_INVENTORY,
    COMPILE_DIAGNOSTICS,
    COMPILE_ELABORATE,
    COMPILE_OWNER_REGISTRY,
    COMPILE_PARSE,
    COMPILE_TOP_CLOSURE,
    RENAME_DECLARATIONS,
    RENAME_FINALIZE,
    RENAME_NAME_COMPLETENESS,
    RENAME_OCCURRENCES,
    RENAME_SEMANTIC_INVENTORY,
    RENAME_SYNTAX_INVENTORY,
    RENAME_UNELABORATED,
)
from rtl_obfuscator.source_set import (
    SourceSetError,
    _resolve_filelist_path,
    from_filelist,
    from_project_root,
    from_single_file,
    infer_filelist_root,
)
def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(content, stream, indent=2)
        stream.write("\n")


class _CliVNextError(ValueError):
    """Stable user-facing failure for the explicit vNext CLI."""

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        detail: str | None = None,
        path: str | None = None,
        details: list[dict[str, Any]] | None = None,
        position: list[str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        self.path = path
        self.details = list(details or [])
        self.position = list(position or [])
        super().__init__(f"{code}: {message}" if message else code)


class _PublicArgumentParser(argparse.ArgumentParser):
    """Argparse surface that keeps public failures stable and actionable."""

    def __init__(self, *args: Any, error_code: str, error_hint: str, **kwargs: Any) -> None:
        self._error_code = error_code
        self._error_hint = error_hint
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:
        del message
        self.exit(
            2,
            f"error: {self._error_code}\nhint: {self._error_hint}\n",
        )


_CLI_VNEXT_CATEGORIES = frozenset(CANONICAL_CATEGORIES)
_CLI_VNEXT_PATH_FIELDS = ("output_dir", "map_file", "metrics_file")
_CLI_VNEXT_PUBLIC_INPUT_HINT = (
    "请检查三种输入模式；单文件只用 --input；filelist 模式不要提供 --source-root，"
    "推荐的 filelist 使用 --filelist [--top]；project-root 使用 --source-root + --top。"
)
#: ``--examples`` does not exist on this entry point, so section 3.3 of T116
#: fixes the number of listed diagnostics and requires the total to be stated.
_CLI_VNEXT_DIAGNOSTIC_EXAMPLES = 10


def _cli_vnext_fail(
    code: str,
    message: str = "",
    *,
    detail: str | None = None,
    path: str | None = None,
    details: list[dict[str, Any]] | None = None,
    position: list[str] | None = None,
) -> None:
    raise _CliVNextError(
        code,
        message,
        detail=detail,
        path=path,
        details=details,
        position=position,
    )


def _cli_vnext_relative_diagnostic_path(
    value: str | None, source_root: Path
) -> str | None:
    if value is None:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return value
    try:
        return candidate.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError:
        return candidate.name


def _cli_vnext_diagnostic_details(
    details: list[dict[str, Any]], source_root: Path
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for detail in details:
        item: dict[str, Any] = {}
        for key, value in detail.items():
            if isinstance(value, str):
                item[key] = _cli_vnext_relative_diagnostic_path(value, source_root)
            else:
                item[key] = value
        sanitized.append(item)
    return sanitized


def _cli_vnext_fail_source_set(
    error: SourceSetError,
    diagnostic_root: Path,
    *,
    filelist: Path | None = None,
    source_root: Path | None = None,
) -> None:
    _cli_vnext_fail(
        "CLI_VNEXT_INPUT_INVALID",
        error.message,
        detail=error.code,
        path=_cli_vnext_relative_diagnostic_path(error.path, diagnostic_root),
        details=_cli_vnext_diagnostic_details(error.details, diagnostic_root),
        position=_cli_vnext_failure_position(
            error,
            diagnostic_root,
            filelist=filelist,
            source_root=source_root,
        ),
    )


def _cli_vnext_absolute_diagnostic_path(value: object, root: Path) -> Path | None:
    """Resolve one reported diagnostic path back to a real absolute path."""

    if not isinstance(value, str) or not value:
        return None
    try:
        candidate = Path(value).expanduser()
        absolute = candidate if candidate.is_absolute() else root / candidate
        return Path(os.path.normpath(str(absolute)))
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _cli_vnext_line_column(path: Path, offset: int) -> tuple[int, int, str] | None:
    """Render one already-resolved diagnostic offset as ``line``, ``column``, text.

    The file and the byte offset are produced by
    ``project_discovery._diagnostic_position``; this only turns that offset into
    the ``line:column`` a person can jump to, and never resolves a position of
    its own.
    """

    try:
        data = path.read_bytes()
    except (OSError, ValueError):
        return None
    if offset < 0 or offset > len(data):
        return None
    begin = data.rfind(b"\n", 0, offset) + 1
    end = data.find(b"\n", offset)
    if end < 0:
        end = len(data)
    line = data.count(b"\n", 0, offset) + 1
    column = offset - begin + 1
    text = data[begin:end].decode("utf-8", errors="replace").strip()
    return line, column, text


def _cli_vnext_diagnostic_positions(
    details: list[dict[str, Any]], root: Path
) -> list[str]:
    """Report ``file:line:column`` plus the diagnostic for a parse/elaborate stop."""

    located = [
        detail
        for detail in details
        if isinstance(detail, dict)
        and isinstance(detail.get("path"), str)
        and type(detail.get("start")) is int
    ]
    if not located:
        return []
    shown = located[:_CLI_VNEXT_DIAGNOSTIC_EXAMPLES]
    lines = [
        f"diagnostics: 共 {len(details)} 条，以下列出前 {len(shown)} 条"
    ]
    for detail in shown:
        code = detail.get("code")
        code_text = code if isinstance(code, str) else ""
        absolute = _cli_vnext_absolute_diagnostic_path(detail["path"], root)
        position = (
            None if absolute is None else _cli_vnext_line_column(absolute, detail["start"])
        )
        if position is None:
            lines.append(f"  {detail['path']}:+{detail['start']}  {code_text}")
            continue
        line, column, text = position
        lines.append(f"  {detail['path']}:{line}:{column}  {code_text}")
        if text:
            lines.append(f"      源码: {text}")
    return lines


def _cli_vnext_filelist_origin(
    filelist: Path | None, target: Path, source_root: Path | None
) -> str | None:
    """Return ``<filelist>:<line>`` for the entry that names ``target``.

    The filelist grammar itself is not re-implemented here: every candidate line
    is resolved through the same ``source_set._resolve_filelist_path`` the reader
    uses, so an entry located by this walk is the entry the reader rejected.
    """

    if filelist is None:
        return None
    environment = dict(os.environ)
    visited: set[Path] = set()
    pending: list[Path] = [Path(filelist).expanduser()]
    while pending:
        current = pending.pop(0)
        try:
            canonical = current.resolve()
            if canonical in visited or not canonical.is_file():
                continue
            visited.add(canonical)
            content = canonical.read_text(encoding="utf-8")
        except (OSError, RuntimeError, UnicodeError, ValueError):
            continue
        for number, raw in enumerate(content.splitlines(), start=1):
            text = raw.strip()
            if not text or text.startswith("#") or text.startswith("//"):
                continue
            tokens = text.split()
            nested = tokens[0] == "-f" and len(tokens) == 2
            library_source = tokens[0] == "-v" and len(tokens) == 2
            if not nested and not library_source and (
                len(tokens) != 1 or text.startswith(("+", "-"))
            ):
                continue
            entry = tokens[1] if nested or library_source else tokens[0]
            resolved: list[Path] = []
            for base in (canonical.parent, source_root):
                if base is None:
                    continue
                try:
                    absolute, _relative = _resolve_filelist_path(
                        root=None,
                        text=entry,
                        environment=environment,
                        label="filelist entry",
                        base=base,
                    )
                except (SourceSetError, OSError, RuntimeError, ValueError):
                    continue
                resolved.append(absolute)
            if nested:
                pending.extend(resolved)
                continue
            if target in resolved:
                return f"{canonical.as_posix()}:{number}"
    return None


def _cli_vnext_failure_position(
    error: SourceSetError,
    diagnostic_root: Path,
    *,
    filelist: Path | None,
    source_root: Path | None,
) -> list[str]:
    """Locate one input failure: a byte position, or a missing file's origin."""

    positions = _cli_vnext_diagnostic_positions(error.details, diagnostic_root)
    if positions:
        return positions
    absolute = _cli_vnext_absolute_diagnostic_path(error.path, diagnostic_root)
    if absolute is None:
        return []
    try:
        resolved = absolute.resolve()
    except (OSError, RuntimeError):
        resolved = absolute
    if resolved.exists():
        return []
    lines = [f"position: {resolved.as_posix()}"]
    origin = _cli_vnext_filelist_origin(filelist, resolved, source_root)
    if origin is not None:
        lines.append(f"filelist: {origin}")
    return lines


def _cli_vnext_path_overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def _cli_vnext_filelist_physical_paths(source_set: object) -> tuple[Path, ...]:
    """Resolve a filelist SourceSet's physical inputs for output protection."""

    if getattr(source_set, "origin", None) != "filelist":
        return ()
    try:
        root = Path(source_set.source_root).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", f"source_root is invalid: {error}")
    if root != Path("/"):
        return ()
    paths: list[Path] = []
    for file in (
        *getattr(source_set, "ordered_source_files", ()),
        *getattr(source_set, "included_files", ()),
    ):
        try:
            path = (root / file).resolve()
            path.relative_to(root)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", f"physical input path is invalid: {error}")
        if path not in paths:
            paths.append(path)
    return tuple(paths)


def _cli_vnext_validate_filelist_outputs(
    source_set: object,
    *,
    output_dir: Path,
    map_file: Path,
    metrics_file: Path,
) -> None:
    protected = _cli_vnext_filelist_physical_paths(source_set)
    if not protected:
        return
    if any(
        _cli_vnext_path_overlap(target, physical)
        for target in (output_dir, map_file, metrics_file)
        for physical in protected
    ):
        _cli_vnext_fail("CLI_VNEXT_OUTPUT_INVALID")


def _cli_vnext_output_path(value: object, option: str) -> Path:
    try:
        candidate = Path(value).expanduser()
        if candidate.is_symlink():
            _cli_vnext_fail("CLI_VNEXT_OUTPUT_INVALID", option)
        path = candidate.resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _cli_vnext_fail("CLI_VNEXT_OUTPUT_INVALID", f"{option}: {error}")
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        _cli_vnext_fail("CLI_VNEXT_OUTPUT_INVALID", option)
    return path


def _cli_vnext_validate_rate(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _cli_vnext_fail("CLI_VNEXT_RATE_INVALID")
    try:
        rate = Decimal(value)
    except (InvalidOperation, ValueError):
        _cli_vnext_fail("CLI_VNEXT_RATE_INVALID")
    if not rate.is_finite() or rate <= 0 or rate > 1:
        _cli_vnext_fail("CLI_VNEXT_RATE_INVALID")
    return value


def _cli_vnext_validate_arguments(
    args: argparse.Namespace,
) -> tuple[
    Path,
    tuple[Path, Path, Path],
    tuple[str, ...],
    int,
    str | None,
    tuple[bool, bool],
]:
    input_file = getattr(args, "input_file", None)
    filelist = getattr(args, "filelist", None)
    project_root_arg = getattr(args, "project_root", None)
    public_cli = bool(getattr(args, "public_cli", False))
    source_root_value = getattr(args, "source_root", None)
    rewrite_roots = tuple(getattr(args, "rewrite_roots", ()) or ())
    if public_cli:
        if project_root_arg is not None:
            _cli_vnext_fail(
                "CLI_VNEXT_INPUT_INVALID",
                "--project-root is internal-only; choose --input, --filelist, or --source-root with --top",
                detail="CLI_VNEXT_INPUT_MODE_CONFLICT",
            )
        if input_file is not None and filelist is not None:
            _cli_vnext_fail(
                "CLI_VNEXT_INPUT_INVALID",
                "--input and --filelist select different public input modes; choose exactly one",
                detail="CLI_VNEXT_INPUT_MODE_CONFLICT",
            )
        if input_file is not None:
            illegal = []
            if source_root_value is not None:
                illegal.append("--source-root")
            if args.top is not None:
                illegal.append("--top")
            if rewrite_roots:
                illegal.append("--rewrite-root")
            if illegal:
                _cli_vnext_fail(
                    "CLI_VNEXT_INPUT_INVALID",
                    f"single-file mode accepts only --input; illegal arguments: {', '.join(illegal)}",
                    detail="CLI_VNEXT_INPUT_MODE_CONFLICT",
                )
            try:
                source_root = Path(input_file).expanduser().resolve().parent
            except (OSError, RuntimeError, TypeError) as error:
                _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", str(error))
        elif filelist is not None:
            if source_root_value is not None:
                _cli_vnext_fail(
                    "CLI_VNEXT_INPUT_INVALID",
                    "filelist mode does not accept --source-root; use --filelist [--top]",
                    detail="CLI_VNEXT_INPUT_MODE_CONFLICT",
                )
            filelist_path = Path(filelist).expanduser().resolve()
            try:
                source_root = infer_filelist_root(
                    filelist=filelist_path,
                    include_dirs=args.include_dirs,
                )
            except SourceSetError as error:
                _cli_vnext_fail_source_set(
                    error, filelist_path.parent, filelist=filelist_path
                )
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", str(error))
        elif source_root_value is not None or args.top is not None:
            if source_root_value is None or args.top is None:
                _cli_vnext_fail(
                    "CLI_VNEXT_INPUT_INVALID",
                    "project-root mode requires both --source-root and --top",
                    detail="CLI_VNEXT_INPUT_MODE_INCOMPLETE",
                )
            if rewrite_roots:
                _cli_vnext_fail(
                    "CLI_VNEXT_INPUT_INVALID",
                    "--rewrite-root is accepted only with --filelist",
                    detail="CLI_VNEXT_INPUT_MODE_CONFLICT",
                )
            try:
                source_root = Path(source_root_value).expanduser().resolve()
            except (OSError, RuntimeError, TypeError) as error:
                _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", str(error))
        else:
            _cli_vnext_fail(
                "CLI_VNEXT_INPUT_INVALID",
                "no public input mode selected; choose --input, --filelist, or --source-root with --top",
                detail="CLI_VNEXT_INPUT_MODE_INCOMPLETE",
            )
    elif sum(
        value is not None for value in (input_file, filelist, project_root_arg)
    ) != 1:
        _cli_vnext_fail(
            "CLI_VNEXT_INPUT_INVALID",
            "internal input modes are mutually exclusive; choose exactly one of --input, --filelist, or --project-root",
            detail="CLI_VNEXT_INPUT_INVALID",
        )

    public_project_mode = public_cli and input_file is None and filelist is None
    if not public_cli and project_root_arg is not None:
        if getattr(args, "source_root", None) is not None or args.top is None:
            _cli_vnext_fail(
                "CLI_VNEXT_INPUT_INVALID",
                "--project-root cannot be combined with --source-root and requires --top",
                detail="CLI_VNEXT_INPUT_INVALID",
            )
        source_root_arg = project_root_arg
        try:
            source_root = Path(source_root_arg).expanduser().resolve()
        except (OSError, RuntimeError, TypeError) as error:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", str(error))
    elif not public_cli:
        source_root_arg = source_root_value
        if source_root_arg is None:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
        try:
            source_root = Path(source_root_arg).expanduser().resolve()
        except (OSError, RuntimeError, TypeError) as error:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", str(error))
    if not source_root.is_dir():
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")

    public_top_scope = public_cli and (
        public_project_mode
        or (filelist is not None and args.top is not None)
    )
    try:
        if public_cli:
            if args.category is None:
                _cli_vnext_fail(
                    "CLI_VNEXT_CATEGORY_REQUIRED",
                    "--category must be provided at least once",
                    detail="allowed=signals,ports,interface,struct,all",
                )
            requested: list[str] = []
            for category in args.category:
                requested.extend(
                    CANONICAL_CATEGORIES if category == "all" else (category,)
                )
            try:
                categories = normalize_categories(requested, default=False)
            except CategoryRegistryError as error:
                _cli_vnext_fail(
                    "CLI_VNEXT_CATEGORY_INVALID",
                    error.message,
                    detail="allowed=signals,ports,interface,struct,all",
                )
        else:
            categories = normalize_categories(args.category, default=False)
    except CategoryRegistryError:
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    try:
        name_length = int(args.name_length)
    except (TypeError, ValueError):
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    if name_length < 4:
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    rate = _cli_vnext_validate_rate(args.encryption_rate)

    output_dir = _cli_vnext_output_path(args.output_dir, "--output-dir")
    map_default = public_cli and args.map_file is None
    metrics_default = public_cli and args.metrics_file is None
    map_file = (
        output_dir / "mapping.json"
        if map_default
        else _cli_vnext_output_path(args.map_file, "--map")
    )
    metrics_file = (
        output_dir / "metrics.json"
        if metrics_default
        else _cli_vnext_output_path(args.metrics_file, "--metrics")
    )
    filelist_global_root = filelist is not None and source_root == Path("/")
    if not filelist_global_root and _cli_vnext_path_overlap(output_dir, source_root):
        _cli_vnext_fail("CLI_VNEXT_OUTPUT_INVALID")
    explicit_reports = tuple(
        path
        for path, is_default in (
            (map_file, map_default),
            (metrics_file, metrics_default),
        )
        if not is_default
    )
    for path in explicit_reports:
        if (not filelist_global_root and _cli_vnext_path_overlap(path, source_root)) or _cli_vnext_path_overlap(
            path, output_dir
        ):
            _cli_vnext_fail("CLI_VNEXT_OUTPUT_INVALID")
    if len(explicit_reports) == 2 and _cli_vnext_path_overlap(
        explicit_reports[0], explicit_reports[1]
    ):
        _cli_vnext_fail("CLI_VNEXT_OUTPUT_INVALID")
    return (
        source_root,
        (output_dir, map_file, metrics_file),
        categories,
        name_length,
        rate,
        (map_default, metrics_default),
    )


def _cli_vnext_input_path(value: Path, source_root: Path) -> Path:
    if value.is_absolute():
        return value
    return source_root / value


def _cli_vnext_source_set(args: argparse.Namespace, source_root: Path):
    try:
        if getattr(args, "project_root", None) is not None or (
            bool(getattr(args, "public_cli", False))
            and getattr(args, "input_file", None) is None
            and getattr(args, "filelist", None) is None
        ):
            return from_project_root(
                project_root=source_root,
                top=args.top,
                include_dirs=args.include_dirs,
                defines=args.defines,
            )
        if args.input_file is not None:
            source_file = (
                Path(args.input_file).expanduser().resolve()
                if bool(getattr(args, "public_cli", False))
                else _cli_vnext_input_path(args.input_file, source_root)
            )
            return from_single_file(
                source_file=source_file,
                source_root=source_root,
                include_dirs=args.include_dirs,
                defines=args.defines,
                top=args.top,
            )
        if bool(getattr(args, "public_cli", False)):
            return from_filelist(
                filelist=Path(args.filelist).expanduser().resolve(),
                source_root=None,
                include_dirs=args.include_dirs,
                defines=args.defines,
                top=args.top,
                rewrite_roots=getattr(args, "rewrite_roots", ()) or (),
            )
        return from_filelist(
            filelist=_cli_vnext_input_path(args.filelist, source_root),
            source_root=source_root,
            include_dirs=args.include_dirs,
            defines=args.defines,
            top=args.top,
        )
    except SourceSetError as error:
        filelist = getattr(args, "filelist", None)
        _cli_vnext_fail_source_set(
            error,
            source_root,
            filelist=None if filelist is None else Path(filelist).expanduser(),
            source_root=source_root,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", str(error))


def _cli_vnext_portable_report(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source_root", "gate_dir", "restore_dir", "TemporaryDirectory"}:
                return False
            if not _cli_vnext_portable_report(item):
                return False
        return True
    if isinstance(value, list):
        return all(_cli_vnext_portable_report(item) for item in value)
    if isinstance(value, str):
        return not value.startswith("/") and not re.match(r"^[A-Za-z]:[\\/]", value)
    return True


def _cli_vnext_write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            if temporary.read_bytes() != payload or json.loads(payload.decode("utf-8")) != value:
                raise ValueError("JSON readback differs from report")
            temporary.replace(path)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
    except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        _cli_vnext_fail("CLI_VNEXT_IO_ERROR", str(error))


def _cli_vnext_write_text_atomic(path: Path, value: str) -> None:
    try:
        payload = value.encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            if temporary.read_bytes() != payload:
                raise ValueError("text readback differs from generated artifact")
            temporary.replace(path)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        _cli_vnext_fail("CLI_VNEXT_IO_ERROR", str(error))


def _cli_vnext_mapping_table(
    report: dict[str, Any],
) -> str:
    mapping = report.get("mapping")
    if not isinstance(mapping, dict) or not isinstance(mapping.get("records"), list):
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("文件名", "模块名", "作用域", "加密类型", "原名", "替换后名"))
    source_cache: dict[str, bytes] = {}
    for record in mapping["records"]:
        if not isinstance(record, dict):
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
        action = record.get("action")
        if action not in {"rename", "preserve", "unsupported"}:
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
        if action != "rename":
            continue
        declaration = record.get("declaration")
        if (
            not isinstance(declaration, dict)
            or not isinstance(declaration.get("file"), str)
            or not isinstance(record.get("owner_module"), str)
            or not isinstance(record.get("category"), str)
            or not isinstance(record.get("original_name"), str)
            or not isinstance(record.get("renamed_name"), str)
        ):
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
        writer.writerow(
            (
                declaration["file"],
                record["owner_module"],
                record["kind"],
                record["category"],
                record["original_name"],
                record["renamed_name"],
            )
        )
    return output.getvalue()


def _cli_vnext_action_counts(report: dict[str, Any]) -> dict[str, int]:
    mapping = report.get("mapping")
    records = mapping.get("records") if isinstance(mapping, dict) else None
    if not isinstance(records, list):
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    action_counts = {"rename": 0, "preserve": 0, "unsupported": 0}
    for record in records:
        if not isinstance(record, dict) or record.get("action") not in action_counts:
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
        action_counts[record["action"]] += 1
    return action_counts


def _cli_vnext_renamed_categories(records: list[dict[str, Any]]) -> tuple[str, ...]:
    """The one category set behind both the persisted and the terminal summary."""

    category_set = {
        record.get("category")
        for record in records
        if isinstance(record, dict)
        and record.get("action") == "rename"
        and isinstance(record.get("category"), str)
    }
    return tuple(
        category for category in CANONICAL_CATEGORIES if category in category_set
    )


def _cli_vnext_encryption_summary(
    report: dict[str, Any],
    metrics_report: dict[str, Any],
) -> str:
    mapping = report.get("mapping")
    records = mapping.get("records") if isinstance(mapping, dict) else None
    summary = report.get("summary")
    effective_lines = metrics_report.get("effective_lines")
    affected_lines = metrics_report.get("affected_lines")
    if (
        not isinstance(records, list)
        or not isinstance(summary, dict)
        or type(summary.get("modified_tokens")) is not int
        or not isinstance(effective_lines, dict)
        or not isinstance(affected_lines, dict)
        or type(effective_lines.get("total")) is not int
        or type(affected_lines.get("changed")) is not int
        or isinstance(affected_lines.get("rate"), bool)
        or not isinstance(affected_lines.get("rate"), (int, float))
    ):
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    action_counts = _cli_vnext_action_counts(report)
    categories = _cli_vnext_renamed_categories(records)
    return "\n".join(
        (
            f"改名对象（rename）：{action_counts['rename']}",
            f"保留对象（preserve）：{action_counts['preserve']}",
            f"不支持对象（unsupported）：{action_counts['unsupported']}",
            f"修改 token 数：{summary['modified_tokens']}",
            f"加密率：{affected_lines['rate']}",
            f"实际加密行数：{affected_lines['changed']}",
            f"总代码行数：{effective_lines['total']}",
            f"加密类型数：{len(categories)}",
            f"加密类型：{', '.join(categories)}",
        )
    ) + "\n"


class _CliVNextProgress:
    """The one stage clock and the one stderr writer of the encryption CLI.

    stdout keeps carrying exactly the single machine-readable JSON line it
    carried before; progress and the human summary belong to stderr, so a demo
    can show both streams and redirecting stdout to a file leaves only the
    report on the terminal.  Elapsed time is read from ``time.monotonic`` and is
    never allowed to go backwards, and the observer only reads the boundaries of
    stages that already ran in this order.
    """

    _STAGE_LABELS = {
        "source_set": "读取 filelist / 组装 SourceSet",
        orchestration_vnext._STAGE_COMPILE: "PySlang 编译与 elaborate",
        orchestration_vnext._STAGE_RENAME_INDEX: "构建改名索引",
        orchestration_vnext._STAGE_MAPPING: "生成映射",
        orchestration_vnext._STAGE_GATE: "写出加密结果",
        orchestration_vnext._STAGE_RESTORE: "逐字节回填校验",
        orchestration_vnext._STAGE_AUDIT_EXECUTION: "构建执行索引",
        orchestration_vnext._STAGE_AUDIT_METRICS: "计算加密指标",
        orchestration_vnext._STAGE_AUDIT_REPORT: "组装结果报告",
        "publish": "原子发布输出",
        "cleanup": "清理临时文件",
        COMPILE_PARSE: "PySlang 解析与预处理",
        COMPILE_ELABORATE: "PySlang 构建语义树 / elaborate",
        COMPILE_DIAGNOSTICS: "PySlang 收集与分类诊断",
        COMPILE_CATALOG_INVENTORY: "SourceCatalog 建立物理模块清单",
        COMPILE_TOP_CLOSURE: "SourceCatalog 计算 top 闭包",
        COMPILE_OWNER_REGISTRY: "SourceCatalog 建立 owner 注册表",
        RENAME_SEMANTIC_INVENTORY: "改名索引收集语义清单",
        RENAME_DECLARATIONS: "改名索引登记候选声明",
        RENAME_OCCURRENCES: "改名索引收集引用范围",
        RENAME_SYNTAX_INVENTORY: "改名索引收集 CST 清单",
        RENAME_UNELABORATED: "改名索引检查未展开源码",
        RENAME_NAME_COMPLETENESS: "改名索引检查名字完整性",
        RENAME_FINALIZE: "改名索引生成最终记录",
    }

    def __init__(self, *, quiet: bool, stream: Any = None) -> None:
        self._quiet = bool(quiet)
        self._stream = sys.stderr if stream is None else stream
        self._origin = time.monotonic()
        self._elapsed = 0.0
        self._begun: dict[str, float] = {}

    def elapsed(self) -> float:
        value = time.monotonic() - self._origin
        if value < self._elapsed:
            value = self._elapsed
        self._elapsed = value
        return value

    def write(self, text: str) -> None:
        if self._quiet:
            return
        try:
            self._stream.write(text)
            self._stream.flush()
        except (OSError, ValueError):
            pass

    def stage(self, stage: str, phase: str) -> None:
        label = self._STAGE_LABELS.get(stage, stage)
        now = self.elapsed()
        if phase == "begin":
            self._begun[stage] = now
            suffix = f" [{stage}]" if "." in stage else ""
            self.write(f"[{now:7.3f}s] 开始 {label}{suffix}\n")
            return
        started = self._begun.get(stage)
        spent = "" if started is None else f"（本阶段 {now - started:.3f}s）"
        suffix = f" [{stage}]" if "." in stage else ""
        self.write(f"[{now:7.3f}s] 完成 {label}{suffix}{spent}\n")


_CLI_VNEXT_REPORT_LABEL_WIDTH = 26
_CLI_VNEXT_REPORT_VALUE_WIDTH = 12


def _cli_vnext_display_width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in "WF" else 1
        for character in text
    )


def _cli_vnext_report_row(label: str, value: str) -> str:
    """One label with its value right-aligned on a fixed terminal column."""

    label_pad = max(1, _CLI_VNEXT_REPORT_LABEL_WIDTH - _cli_vnext_display_width(label))
    value_pad = max(0, _CLI_VNEXT_REPORT_VALUE_WIDTH - _cli_vnext_display_width(value))
    return "  " + label + " " * (label_pad + value_pad) + value


def _cli_vnext_report_text_row(label: str, value: str) -> str:
    """One label with a name list, which is text and so stays left-aligned."""

    label_pad = max(1, _CLI_VNEXT_REPORT_LABEL_WIDTH - _cli_vnext_display_width(label))
    return "  " + label + " " * label_pad + value


def _cli_vnext_report_ratio(numerator: object, denominator: object) -> str:
    """A percentage, or ``n/a`` when the denominator carries no information."""

    if type(numerator) is not int or type(denominator) is not int:
        return "n/a"
    if denominator <= 0:
        return "n/a"
    return f"{numerator * 100 / denominator:.2f}%"


def _cli_vnext_report_count(value: object) -> str:
    return str(value) if type(value) is int else "n/a"


def _cli_vnext_landed_edits(report: dict[str, Any]) -> tuple[int, int]:
    """Files and records that really carry a landed edit.

    Neither number exists in ``summary`` today, so T116 section 3.2 defines both
    against ``mapping_execution.per_file_mapping``: a landed edit is a projected
    range of a ``rename`` record, which is exactly the position ``write_gate``
    rewrote.  ``rename`` in the summary counts decisions instead, so the two are
    reported side by side rather than merged.
    """

    execution = report.get("mapping_execution")
    per_file = execution.get("per_file_mapping") if isinstance(execution, dict) else None
    if not isinstance(per_file, list):
        return 0, 0
    files = 0
    symbols: set[str] = set()
    for entry in per_file:
        if not isinstance(entry, dict) or not isinstance(entry.get("records"), list):
            continue
        landed = [
            record
            for record in entry["records"]
            if isinstance(record, dict)
            and record.get("action") == "rename"
            and isinstance(record.get("ranges"), list)
            and record["ranges"]
        ]
        if not landed:
            continue
        files += 1
        symbols.update(
            record["symbol_id"]
            for record in landed
            if isinstance(record.get("symbol_id"), str)
        )
    return files, len(symbols)


def _cli_vnext_terminal_report(report: dict[str, Any], *, elapsed: float) -> str:
    """The human summary of one encryption run, for stderr only.

    Every count is read back from the report the run already produced; this
    formats existing measurements and never recomputes a second set.
    """

    summary = report.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    mapping = report.get("mapping")
    records = mapping.get("records") if isinstance(mapping, dict) else None
    categories = _cli_vnext_renamed_categories(records if isinstance(records, list) else [])
    effective_lines = summary.get("effective_line_total")
    affected_lines = summary.get("affected_line_count")
    files = summary.get("files")
    encrypted_files, modified_records = _cli_vnext_landed_edits(report)
    groups = (
        (_cli_vnext_report_row("用时", f"{elapsed:.3f}s"),),
        (
            _cli_vnext_report_row("加密类型数", str(len(categories))),
            _cli_vnext_report_text_row(
                "加密类型", ", ".join(categories) if categories else "-"
            ),
        ),
        (
            _cli_vnext_report_row("总代码行数", _cli_vnext_report_count(effective_lines)),
            _cli_vnext_report_row("实际加密行数", _cli_vnext_report_count(affected_lines)),
            _cli_vnext_report_row(
                "加密率", _cli_vnext_report_ratio(affected_lines, effective_lines)
            ),
        ),
        (
            _cli_vnext_report_row("总文件数", _cli_vnext_report_count(files)),
            _cli_vnext_report_row(
                "交付物理文件数",
                _cli_vnext_report_count(summary.get("physical_files")),
            ),
            _cli_vnext_report_row("加密文件数", str(encrypted_files)),
            _cli_vnext_report_row(
                "文件覆盖率", _cli_vnext_report_ratio(encrypted_files, files)
            ),
        ),
        (
            _cli_vnext_report_row(
                "改名对象数(rename)", _cli_vnext_report_count(summary.get("rename"))
            ),
            _cli_vnext_report_row(
                "保留对象数(preserve)", _cli_vnext_report_count(summary.get("preserve"))
            ),
            _cli_vnext_report_row(
                "不支持对象数(unsupported)",
                _cli_vnext_report_count(summary.get("unsupported")),
            ),
            _cli_vnext_report_row("实际修改对象数", str(modified_records)),
        ),
    )
    footnote = (
        "  注：加密文件数与实际修改对象数取自 mapping_execution.per_file_mapping 中"
        "至少落地一处编辑的文件数与记录数；\n"
        "      rename 是决策数，实际修改对象数是真正改到字节的记录数。\n"
    )
    body = "\n\n".join("\n".join(group) for group in groups)
    return "加密总结\n\n" + body + "\n\n" + footnote


def _cli_vnext_remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _cli_vnext_publish(artifacts: list[tuple[Path, Path]]) -> None:
    prepared: list[tuple[Path, Path, bool]] = []
    success = False
    try:
        for source, target in artifacts:
            container = Path(tempfile.mkdtemp(prefix=".rtl-obfuscation-cli-vnext-", dir=target.parent))
            payload = container / "payload"
            if source.is_dir():
                shutil.copytree(source, payload)
            else:
                shutil.copy2(source, payload)
            prepared.append((container, target, False))
        for index, (container, target, _published) in enumerate(prepared):
            if target.exists() or target.is_symlink():
                _cli_vnext_fail("CLI_VNEXT_OUTPUT_INVALID")
            (container / "payload").replace(target)
            prepared[index] = (container, target, True)
        success = True
    except _CliVNextError:
        raise
    except (OSError, shutil.Error, ValueError) as error:
        _cli_vnext_fail("CLI_VNEXT_IO_ERROR", str(error))
    finally:
        for container, target, published in reversed(prepared):
            if published and not success:
                try:
                    _cli_vnext_remove(target)
                except OSError:
                    pass
            shutil.rmtree(container, ignore_errors=True)


def _encrypt_vnext(args: argparse.Namespace) -> dict[str, Any]:
    progress = _CliVNextProgress(quiet=bool(getattr(args, "quiet", False)))
    (
        source_root,
        (output_dir, map_file, metrics_file),
        categories,
        name_length,
        rate,
        (map_default, metrics_default),
    ) = _cli_vnext_validate_arguments(args)
    progress.stage("source_set", "begin")
    source_set = _cli_vnext_source_set(args, source_root)
    _cli_vnext_validate_filelist_outputs(
        source_set,
        output_dir=output_dir,
        map_file=map_file,
        metrics_file=metrics_file,
    )
    progress.stage("source_set", "end")
    try:
        staging_root = Path(tempfile.mkdtemp(prefix="rtl-obfuscation-cli-vnext-"))
    except OSError as error:
        _cli_vnext_fail("CLI_VNEXT_IO_ERROR", str(error))
    try:
        gate_dir = staging_root / "gate"
        restore_dir = staging_root / "restore"
        try:
            result = orchestration_vnext.run_vnext(
                source_set,
                categories=categories,
                name_length=name_length,
                encryption_rate=rate,
                gate_dir=gate_dir,
                restore_dir=restore_dir,
                stage_observer=progress.stage,
            )
            report = result.to_report()
        except orchestration_vnext.OrchestrationVNextError as error:
            code = (
                "CLI_VNEXT_RATE_INVALID"
                if error.code == "ORCHESTRATION_RATE_INVALID"
                else "CLI_VNEXT_ORCHESTRATION_INVALID"
            )
            _cli_vnext_fail(
                code,
                f"REFUSED_ATOMIC: {error.message}",
                detail=error.code,
            )
        except (OSError, RuntimeError, ValueError) as error:
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID", str(error))
        if not isinstance(report, dict) or report.get("format") != "rtl-obfuscation.orchestration-vnext":
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
        metrics_report = report.get("metrics")
        summary = report.get("summary")
        if not isinstance(metrics_report, dict) or metrics_report.get("format") != "rtl-obfuscation.metrics-vnext":
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
        if not isinstance(summary, dict) or not _cli_vnext_portable_report(report):
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
        action_counts = _cli_vnext_action_counts(report)
        staged_map = gate_dir / "mapping.json" if map_default else staging_root / "orchestration.json"
        staged_metrics = gate_dir / "metrics.json" if metrics_default else staging_root / "metrics.json"
        staged_mapping_table = gate_dir / "mapping_table.csv"
        staged_encryption_summary = gate_dir / "encryption_summary.txt"
        _cli_vnext_write_json_atomic(staged_map, report)
        _cli_vnext_write_json_atomic(staged_metrics, metrics_report)
        _cli_vnext_write_text_atomic(
            staged_mapping_table,
            _cli_vnext_mapping_table(report),
        )
        _cli_vnext_write_text_atomic(
            staged_encryption_summary,
            _cli_vnext_encryption_summary(report, metrics_report),
        )
        artifacts = [(gate_dir, output_dir)]
        if not map_default:
            artifacts.append((staged_map, map_file))
        if not metrics_default:
            artifacts.append((staged_metrics, metrics_file))
        progress.stage("publish", "begin")
        _cli_vnext_publish(artifacts)
        progress.stage("publish", "end")
        progress.write(_cli_vnext_terminal_report(report, elapsed=progress.elapsed()))
        return {
            "format": "rtl-obfuscation.cli-vnext",
            "schema_version": 2,
            "state": "restored",
            "action_counts": action_counts,
            "summary": summary,
        }
    finally:
        progress.stage("cleanup", "begin")
        shutil.rmtree(staging_root, ignore_errors=True)
        progress.stage("cleanup", "end")


def _decrypt_vnext(args: argparse.Namespace) -> dict[str, Any]:
    """Restore one persisted T053 orchestration envelope in a new process."""

    public_cli = bool(getattr(args, "public_cli", False))
    if getattr(args, "rewrite_roots", None):
        _cli_vnext_fail(
            "CLI_VNEXT_INPUT_INVALID",
            "--rewrite-root is accepted only by filelist encryption mode",
            detail="CLI_VNEXT_INPUT_MODE_CONFLICT",
        )
    if public_cli:
        map_path, gate_path, output_path, report_path = (
            restore_vnext.validate_direct_restore_paths_vnext(
                args.map_file,
                args.gate_dir,
                args.output_dir,
                args.report,
            )
        )
    else:
        map_path, gate_path, source_path, output_path, report_path = (
            restore_vnext._validate_paths(
                args.map_file,
                args.gate_dir,
                args.source_root,
                args.output_dir,
                args.report,
            )
        )
        if report_path is None:
            raise restore_vnext.RestoreVNextError(
                "RESTORE_VNEXT_OUTPUT_INVALID", "report is required"
            )
    try:
        staging_root = Path(tempfile.mkdtemp(prefix="rtl-obfuscation-restore-cli-vnext-"))
    except OSError as error:
        raise restore_vnext.RestoreVNextError("RESTORE_VNEXT_IO_ERROR", str(error)) from error
    staging_restore = staging_root / "restore"
    staging_report = staging_root / "restore.json"
    try:
        if public_cli:
            restored = restore_vnext.load_direct_restore_vnext(
                map_path,
                gate_dir=gate_path,
                output_dir=staging_restore,
            )
        else:
            restored = restore_vnext.load_restore_vnext(
                map_path,
                gate_dir=gate_path,
                source_root=source_path,
                output_dir=staging_restore,
            )
        artifacts = [(staging_restore, output_path)]
        if report_path is not None:
            restore_vnext.write_restore_report_vnext(restored, staging_report)
            artifacts.append((staging_report, report_path))
        restore_vnext.publish_restore_vnext(artifacts)
        return {
            "format": "rtl-obfuscation.restore-vnext-cli",
            "schema_version": 2,
            "state": "restored",
            "summary": restored.report["summary"],
        }
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)




def _register_encrypt_arguments(
    parser: argparse.ArgumentParser,
    *,
    public_cli: bool,
) -> None:
    public_help = {
        "input": "单文件模式：只提供要加密的 .sv 或 .v 文件路径",
        "filelist": "filelist 模式：按编译顺序列出源码的 .f 文件",
        "source_root": "project-root 模式的源码根目录；不能与 --input 或 --filelist 同用",
        "rewrite_root": "filelist 模式中允许改写的目录，可重复使用",
        "top": "顶层 module；project-root 模式必填，filelist 模式可选，单文件模式禁止",
        "include_dir": "额外 include 目录，可重复使用",
        "define": "预处理宏 NAME[=VALUE]，可重复使用",
        "category": "只处理指定名称类型，可重复使用；建议真实工程从少量类型开始",
        "encryption_rate": "加密率，范围为 0 < RATE <= 1",
        "name_length": "新名称长度，最小 4，默认 20",
        "output_dir": "加密输出目录；运行前必须不存在",
        "map": "mapping.json 的自定义路径；默认写入加密目录",
        "metrics": "metrics.json 的自定义路径；默认写入加密目录",
        "quiet": "不在 stderr 输出实时进度与加密总结；stdout 的 JSON 不受影响",
    }
    parser.add_argument(
        "--input",
        dest="input_file",
        type=Path,
        help=public_help["input"] if public_cli else None,
    )
    parser.add_argument(
        "--filelist",
        type=Path,
        help=public_help["filelist"] if public_cli else None,
    )
    if not public_cli:
        parser.add_argument("--project-root", type=Path)
    parser.add_argument(
        "--source-root",
        type=Path,
        help=public_help["source_root"] if public_cli else None,
    )
    if public_cli:
        parser.add_argument(
            "--rewrite-root",
            dest="rewrite_roots",
            action="append",
            type=Path,
            default=[],
            help=public_help["rewrite_root"],
        )
    parser.add_argument("--top", help=public_help["top"] if public_cli else None)
    parser.add_argument(
        "--include-dir",
        dest="include_dirs",
        action="append",
        default=[],
        help=public_help["include_dir"] if public_cli else None,
    )
    parser.add_argument(
        "--define",
        dest="defines",
        action="append",
        default=[],
        help=public_help["define"] if public_cli else None,
    )
    parser.add_argument(
        "--category",
        action="append",
        default=None,
        help=public_help["category"] if public_cli else None,
    )
    parser.add_argument(
        "--encryption-rate",
        help=public_help["encryption_rate"] if public_cli else None,
    )
    parser.add_argument(
        "--name-length",
        default=20,
        help=public_help["name_length"] if public_cli else None,
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help=public_help["output_dir"] if public_cli else None,
    )
    parser.add_argument(
        "--map",
        dest="map_file",
        required=not public_cli,
        type=Path,
        help=public_help["map"] if public_cli else None,
    )
    parser.add_argument(
        "--metrics",
        dest="metrics_file",
        required=not public_cli,
        type=Path,
        help=public_help["metrics"] if public_cli else None,
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=public_help["quiet"] if public_cli else None,
    )
    parser.set_defaults(public_cli=public_cli)


def _register_decrypt_arguments(
    parser: argparse.ArgumentParser,
    *,
    public_cli: bool,
) -> None:
    public_help = {
        "map": "加密时生成的 mapping.json",
        "gate_dir": "加密 RTL 所在目录",
        "output_dir": "恢复输出目录；运行前必须不存在",
        "report": "可选的恢复结果报告路径",
    }
    parser.add_argument(
        "--map",
        dest="map_file",
        required=True,
        type=Path,
        help=public_help["map"] if public_cli else None,
    )
    parser.add_argument(
        "--gate-dir",
        required=True,
        type=Path,
        help=public_help["gate_dir"] if public_cli else None,
    )
    if not public_cli:
        parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help=public_help["output_dir"] if public_cli else None,
    )
    parser.add_argument(
        "--report",
        type=Path,
        help=public_help["report"] if public_cli else None,
    )
    if public_cli:
        parser.add_argument(
            "--rewrite-root",
            dest="rewrite_roots",
            action="append",
            type=Path,
            default=[],
            help=argparse.SUPPRESS,
        )
    parser.set_defaults(public_cli=public_cli)


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="vNext SystemVerilog encryption and restore")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    _register_encrypt_arguments(
        subparsers.add_parser("encrypt-vnext"),
        public_cli=False,
    )
    _register_decrypt_arguments(
        subparsers.add_parser("decrypt-vnext"),
        public_cli=False,
    )
    return parser


def _create_encrypt_argument_parser() -> argparse.ArgumentParser:
    parser = _PublicArgumentParser(
        prog="rtl_encrypt",
        description="加密 SystemVerilog RTL 名称。",
        epilog=(
            "输入模式（三选一）：\n"
            "  单文件：--input FILE\n"
            "  filelist：--filelist DESIGN.F [--top TOP]\n"
            "  project-root：--source-root DIR --top TOP"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        error_code="CLI_VNEXT_INPUT_INVALID",
        error_hint=_CLI_VNEXT_PUBLIC_INPUT_HINT,
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    _register_encrypt_arguments(parser, public_cli=True)
    return parser


def _create_decrypt_argument_parser() -> argparse.ArgumentParser:
    parser = _PublicArgumentParser(
        prog="rtl_decrypt",
        description="使用 mapping.json 从加密目录恢复 SystemVerilog 源码。",
        add_help=False,
        error_code="RESTORE_VNEXT_INPUT_INVALID",
        error_hint="请同时提供 --map、--gate-dir 和尚不存在的 --output-dir。",
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    _register_decrypt_arguments(parser, public_cli=True)
    return parser


def _run_cli_operation(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    operation: Any,
) -> int:
    def fail(error: _CliVNextError) -> None:
        hints = {
            "CLI_VNEXT_INPUT_INVALID": _CLI_VNEXT_PUBLIC_INPUT_HINT,
            "CLI_VNEXT_OUTPUT_INVALID": "请改用尚不存在且不与源码重叠的输出目录或报告路径。",
            "CLI_VNEXT_RATE_INVALID": "请把 --encryption-rate 设置为大于 0 且不大于 1 的数值。",
            "CLI_VNEXT_ORCHESTRATION_INVALID": "请检查 filelist 编译顺序、include 目录、宏定义及严格编译诊断。",
            "CLI_VNEXT_IO_ERROR": "请检查目标目录权限和可用磁盘空间后重试。",
            "RESTORE_VNEXT_INPUT_INVALID": "请检查 --map 是否指向本次加密生成的 mapping.json。",
            "RESTORE_VNEXT_GATE_INVALID": "请检查 --gate-dir 是否为 mapping.json 对应且未被改动的加密目录。",
            "RESTORE_VNEXT_OUTPUT_INVALID": "请改用尚不存在且不与输入重叠的恢复目录或报告路径。",
            "RESTORE_VNEXT_REPORT_INVALID": "mapping.json 与加密目录不匹配或已损坏，请使用同一次加密的原始产物。",
            "RESTORE_VNEXT_IO_ERROR": "请检查目标目录权限和可用磁盘空间后重试。",
        }
        hint = hints.get(error.code, "请检查命令参数、输入文件和输出路径后重试。")
        lines = [f"error: {error.code}"]
        if error.detail:
            lines.append(f"detail: {error.detail}")
        if error.path:
            lines.append(f"path: {error.path}")
        if error.message:
            lines.append(f"message: {error.message}")
        if error.details:
            lines.append(
                "details: "
                + json.dumps(error.details, ensure_ascii=False, separators=(",", ":"))
            )
        lines.extend(error.position)
        lines.append(f"hint: {hint}")
        parser.exit(1, "\n".join(lines) + "\n")

    try:
        summary = operation(args)
    except _CliVNextError as error:
        fail(error)
    except restore_vnext.RestoreVNextError as error:
        fail(_CliVNextError(error.code, str(error)))
    except (OSError, RuntimeError, ValueError) as error:
        fail(_CliVNextError("CLI_VNEXT_INPUT_INVALID", str(error)))
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    return 0


def rtl_encrypt_main() -> int:
    parser = _create_encrypt_argument_parser()
    return _run_cli_operation(parser, parser.parse_args(), _encrypt_vnext)


def rtl_decrypt_main() -> int:
    parser = _create_decrypt_argument_parser()
    return _run_cli_operation(parser, parser.parse_args(), _decrypt_vnext)


def main() -> int:
    parser = _create_argument_parser()
    args = parser.parse_args()
    if args.operation == "encrypt-vnext":
        operation = _encrypt_vnext
    elif args.operation == "decrypt-vnext":
        operation = _decrypt_vnext
    else:
        operation = lambda _args: _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    return _run_cli_operation(parser, args, operation)


if __name__ == "__main__":
    raise SystemExit(main())
