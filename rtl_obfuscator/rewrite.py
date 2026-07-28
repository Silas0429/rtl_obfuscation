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
from typing import Any

from rtl_obfuscator import orchestration_vnext
from rtl_obfuscator import restore_vnext
from rtl_obfuscator.category_registry_vnext import (
    CANONICAL_CATEGORIES,
    MODULE_ABI_CATEGORIES,
    CategoryRegistryError,
    normalize_abi_categories,
    normalize_categories,
)
from rtl_obfuscator.source_set import (
    SourceSetError,
    from_filelist,
    from_project_root,
    from_single_file,
)
from rtl_obfuscator.symbol_graph import _semantic_scopes, _syntax_span



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

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


_CLI_VNEXT_DEFAULT_CATEGORIES = tuple(CANONICAL_CATEGORIES[:13])
_CLI_VNEXT_CATEGORIES = frozenset(CANONICAL_CATEGORIES)
_CLI_VNEXT_ABI_CATEGORIES = frozenset(MODULE_ABI_CATEGORIES)
_CLI_VNEXT_PATH_FIELDS = ("output_dir", "map_file", "metrics_file")


def _cli_vnext_fail(code: str, message: str = "") -> None:
    raise _CliVNextError(code, message)


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


def _cli_vnext_output_path(value: object, option: str) -> Path:
    try:
        path = Path(value).expanduser().resolve()
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
    public_project_mode = (
        public_cli
        and input_file is None
        and filelist is None
        and source_root_value is not None
        and args.top is not None
    )
    if public_cli:
        if project_root_arg is not None or sum(
            value is not None for value in (input_file, filelist)
        ) > 1:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
        if input_file is None and filelist is None and not public_project_mode:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    elif sum(
        value is not None for value in (input_file, filelist, project_root_arg)
    ) != 1:
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")

    if project_root_arg is not None:
        if getattr(args, "source_root", None) is not None or args.top is None:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
        source_root_arg = project_root_arg
    else:
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
                categories = (
                    tuple(CANONICAL_CATEGORIES)
                    if public_top_scope
                    else _CLI_VNEXT_DEFAULT_CATEGORIES
                )
            else:
                requested: list[str] = []
                for category in args.category:
                    requested.extend(
                        CANONICAL_CATEGORIES if category == "all" else (category,)
                    )
                categories = normalize_categories(requested, default=False)
            abi_categories = (
                tuple(
                    category
                    for category in MODULE_ABI_CATEGORIES
                    if category in categories
                )
                if public_top_scope
                else ()
            )
        else:
            categories = normalize_categories(args.category, default=True)
            abi_categories = normalize_abi_categories(args.abi_category or ())
    except CategoryRegistryError:
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    if any(category not in categories for category in abi_categories):
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    if abi_categories and args.top is None:
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
    if _cli_vnext_path_overlap(output_dir, source_root):
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
        if _cli_vnext_path_overlap(path, source_root) or _cli_vnext_path_overlap(
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
        abi_categories,
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
            return from_single_file(
                source_file=_cli_vnext_input_path(args.input_file, source_root),
                source_root=source_root,
                include_dirs=args.include_dirs,
                defines=args.defines,
                top=args.top,
            )
        return from_filelist(
            filelist=_cli_vnext_input_path(args.filelist, source_root),
            source_root=source_root,
            include_dirs=args.include_dirs,
            defines=args.defines,
            top=args.top,
        )
    except (OSError, RuntimeError, SourceSetError, TypeError, ValueError) as error:
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


def _cli_vnext_scope_spans(
    source_catalog: object,
) -> tuple[
    tuple[tuple[str, int, int, str], ...],
    tuple[tuple[str, int, int], ...],
]:
    try:
        nodes: list[object] = []
        source_catalog.catalog_root.visit(nodes.append)
        scopes = _semantic_scopes(source_catalog, nodes)
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID", str(error))
    module_spans = tuple(
        (scope.file, scope.start, scope.end, scope.name)
        for scope in scopes
        if scope.kind == "module"
    )
    generate_spans = tuple(
        sorted(
            {
                _syntax_span(source_catalog, node.syntax)
                for node in nodes
                if type(node).__name__
                in {"GenerateBlockArraySymbol", "GenerateBlockSymbol"}
                and getattr(node, "syntax", None) is not None
            },
            key=lambda span: (span[0], span[1], span[2]),
        )
    )
    return module_spans, generate_spans


def _cli_vnext_owner_details(
    owner: str,
    source_root: Path,
    source_cache: dict[str, bytes],
) -> tuple[str, str, int, int, bytes] | None:
    if owner == "$unit":
        return None
    try:
        owner_kind_file, start_text, end_text = owner.rsplit(":", 2)
        owner_kind, file = owner_kind_file.split(":", 1)
        start = int(start_text)
        end = int(end_text)
        if file not in source_cache:
            source_path = (source_root / file).resolve()
            source_path.relative_to(source_root)
            source_cache[file] = source_path.read_bytes()
        content = source_cache[file]
        if start < 0 or start >= end or end > len(content):
            raise ValueError("owner range is outside source bytes")
    except (OSError, UnicodeError, ValueError, TypeError):
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    if owner_kind not in {"module", "generate", "subroutine", "type", "interface"}:
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    return owner_kind, file, start, end, content


def _cli_vnext_module_name(
    declaration: dict[str, object],
    module_spans: tuple[tuple[str, int, int, str], ...],
) -> str:
    file = declaration.get("file")
    start = declaration.get("start")
    if not isinstance(file, str) or type(start) is not int:
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    matches = [
        scope
        for scope in module_spans
        if scope[0] == file and scope[1] <= start < scope[2]
    ]
    if not matches:
        return "global"
    return max(matches, key=lambda scope: (scope[2] - scope[1], -scope[1]))[3]


def _cli_vnext_scope_name(
    record: dict[str, object],
    source_root: Path,
    source_cache: dict[str, bytes],
    generate_spans: tuple[tuple[str, int, int], ...],
) -> str:
    declaration = record.get("declaration")
    if isinstance(declaration, dict):
        file = declaration.get("file")
        start = declaration.get("start")
        if isinstance(file, str) and type(start) is int:
            matches = [
                span
                for span in generate_spans
                if span[0] == file and span[1] <= start < span[2]
            ]
            if matches:
                _span_file, span_start, span_end = min(
                    matches,
                    key=lambda span: (span[2] - span[1], span[1]),
                )
                if file not in source_cache:
                    try:
                        source_path = (source_root / file).resolve()
                        source_path.relative_to(source_root)
                        source_cache[file] = source_path.read_bytes()
                    except (OSError, RuntimeError, ValueError) as error:
                        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID", str(error))
                content = source_cache[file]
                segment = content[span_start:span_end]
                begin = re.search(rb"\bbegin\b", segment)
                if begin is not None:
                    label = re.match(
                        rb"\s*:\s*([A-Za-z_][A-Za-z0-9_$]*)",
                        segment[begin.end() :],
                    )
                    if label is not None:
                        return f"generate:{label.group(1).decode('utf-8')}"
                line = content[:span_start].count(b"\n") + 1
                return f"generate:line {line}"
    owner = record.get("owner_module")
    if not isinstance(owner, str):
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    details = _cli_vnext_owner_details(owner, source_root, source_cache)
    if details is None:
        return "global"
    owner_kind, _file, start, end, content = details
    if owner_kind == "module":
        return "module"
    if owner_kind == "generate":
        segment = content[start:end]
        begin = re.search(rb"\bbegin\b", segment)
        if begin is not None:
            label = re.match(
                rb"\s*:\s*([A-Za-z_][A-Za-z0-9_$]*)",
                segment[begin.end() :],
            )
            if label is not None:
                return f"generate:{label.group(1).decode('utf-8')}"
        line = content[:start].count(b"\n") + 1
        return f"generate:line {line}"
    try:
        name = content[start:end].decode("utf-8")
    except UnicodeError as error:
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID", str(error))
    if not name:
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    if owner_kind == "subroutine":
        prefix = {
            "functions": "function",
            "tasks": "task",
        }.get(record.get("category"), "subroutine")
        return f"{prefix}:{name}"
    if owner_kind in {"type", "interface"}:
        return f"{owner_kind}:{name}"
    return f"{owner_kind}:{name}"


def _cli_vnext_mapping_table(
    report: dict[str, Any],
    source_root: Path,
    module_spans: tuple[tuple[str, int, int, str], ...],
    generate_spans: tuple[tuple[str, int, int], ...],
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
                _cli_vnext_module_name(declaration, module_spans),
                _cli_vnext_scope_name(
                    record,
                    source_root,
                    source_cache,
                    generate_spans,
                ),
                record["category"],
                record["original_name"],
                record["renamed_name"],
            )
        )
    return output.getvalue()


def _cli_vnext_encryption_summary(
    report: dict[str, Any],
    metrics_report: dict[str, Any],
) -> str:
    mapping = report.get("mapping")
    records = mapping.get("records") if isinstance(mapping, dict) else None
    effective_lines = metrics_report.get("effective_lines")
    affected_lines = metrics_report.get("affected_lines")
    if (
        not isinstance(records, list)
        or not isinstance(effective_lines, dict)
        or not isinstance(affected_lines, dict)
        or type(effective_lines.get("total")) is not int
        or type(affected_lines.get("changed")) is not int
        or isinstance(affected_lines.get("rate"), bool)
        or not isinstance(affected_lines.get("rate"), (int, float))
    ):
        _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
    renamed_records = []
    for record in records:
        if not isinstance(record, dict):
            _cli_vnext_fail("CLI_VNEXT_ORCHESTRATION_INVALID")
        if record.get("action") == "rename":
            renamed_records.append(record)
    category_set = {
        record.get("category")
        for record in renamed_records
        if isinstance(record.get("category"), str)
    }
    categories = tuple(
        category for category in CANONICAL_CATEGORIES if category in category_set
    )
    return "\n".join(
        (
            f"加密率：{affected_lines['rate']}",
            f"实际加密行数：{affected_lines['changed']}",
            f"总代码行数：{effective_lines['total']}",
            f"加密类型数：{len(categories)}",
            f"加密类型：{', '.join(categories)}",
        )
    ) + "\n"


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
    (
        source_root,
        (output_dir, map_file, metrics_file),
        categories,
        abi_categories,
        name_length,
        rate,
        (map_default, metrics_default),
    ) = _cli_vnext_validate_arguments(args)
    source_set = _cli_vnext_source_set(args, source_root)
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
                abi_categories=abi_categories,
                name_length=name_length,
                encryption_rate=rate,
                gate_dir=gate_dir,
                restore_dir=restore_dir,
            )
            report = result.to_report()
        except orchestration_vnext.OrchestrationVNextError as error:
            code = (
                "CLI_VNEXT_RATE_INVALID"
                if error.code == "ORCHESTRATION_RATE_INVALID"
                else "CLI_VNEXT_ORCHESTRATION_INVALID"
            )
            _cli_vnext_fail(code)
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
        staged_map = gate_dir / "mapping.json" if map_default else staging_root / "orchestration.json"
        staged_metrics = gate_dir / "metrics.json" if metrics_default else staging_root / "metrics.json"
        staged_mapping_table = gate_dir / "mapping_table.csv"
        staged_encryption_summary = gate_dir / "encryption_summary.txt"
        module_spans, generate_spans = _cli_vnext_scope_spans(
            result.mapping_vnext.rewrite_policy.symbol_graph.source_catalog
        )
        _cli_vnext_write_json_atomic(staged_map, report)
        _cli_vnext_write_json_atomic(staged_metrics, metrics_report)
        _cli_vnext_write_text_atomic(
            staged_mapping_table,
            _cli_vnext_mapping_table(
                report,
                source_root,
                module_spans,
                generate_spans,
            ),
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
        _cli_vnext_publish(artifacts)
        return {
            "format": "rtl-obfuscation.cli-vnext",
            "schema_version": 1,
            "state": "restored",
            "summary": summary,
        }
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _decrypt_vnext(args: argparse.Namespace) -> dict[str, Any]:
    """Restore one persisted T053 orchestration envelope in a new process."""

    public_cli = bool(getattr(args, "public_cli", False))
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
            "schema_version": 1,
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
    parser.add_argument("--input", dest="input_file", type=Path)
    parser.add_argument("--filelist", type=Path)
    if not public_cli:
        parser.add_argument("--project-root", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--top")
    parser.add_argument("--include-dir", dest="include_dirs", action="append", default=[])
    parser.add_argument("--define", dest="defines", action="append", default=[])
    parser.add_argument("--category", action="append", default=None)
    if not public_cli:
        parser.add_argument("--abi-category", action="append", default=None)
    parser.add_argument("--encryption-rate")
    parser.add_argument("--name-length", default=20)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--map", dest="map_file", required=not public_cli, type=Path)
    parser.add_argument(
        "--metrics",
        dest="metrics_file",
        required=not public_cli,
        type=Path,
    )
    parser.set_defaults(public_cli=public_cli)


def _register_decrypt_arguments(
    parser: argparse.ArgumentParser,
    *,
    public_cli: bool,
) -> None:
    parser.add_argument("--map", dest="map_file", required=True, type=Path)
    parser.add_argument("--gate-dir", required=True, type=Path)
    if not public_cli:
        parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", type=Path)
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
    parser = argparse.ArgumentParser(
        prog="rtl_encrypt",
        description="Encrypt selected SystemVerilog identifiers.",
    )
    _register_encrypt_arguments(parser, public_cli=True)
    return parser


def _create_decrypt_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtl_decrypt",
        description="Restore SystemVerilog sources from an encryption report.",
    )
    _register_decrypt_arguments(parser, public_cli=True)
    return parser


def _run_cli_operation(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    operation: Any,
) -> int:
    try:
        summary = operation(args)
    except _CliVNextError as error:
        parser.exit(1, f"error: {error.code}\n")
    except restore_vnext.RestoreVNextError as error:
        parser.exit(1, f"error: {error.code}\n")
    except (OSError, RuntimeError, ValueError):
        parser.exit(1, "error: CLI_VNEXT_INPUT_INVALID\n")
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
