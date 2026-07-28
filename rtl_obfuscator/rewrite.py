"""Rewrite and restore selected SystemVerilog identifiers."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
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
    modes = sum(value is not None for value in (input_file, filelist, project_root_arg))
    if modes != 1:
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    if project_root_arg is not None:
        if getattr(args, "source_root", None) is not None or args.top is None:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
        source_root_arg = project_root_arg
    else:
        source_root_arg = getattr(args, "source_root", None)
        if source_root_arg is None:
            _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")
    try:
        source_root = Path(source_root_arg).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID", str(error))
    if not source_root.is_dir():
        _cli_vnext_fail("CLI_VNEXT_INPUT_INVALID")

    public_cli = bool(getattr(args, "public_cli", False))
    public_top_scope = public_cli and (
        project_root_arg is not None
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
        if getattr(args, "project_root", None) is not None:
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
        _cli_vnext_write_json_atomic(staged_map, report)
        _cli_vnext_write_json_atomic(staged_metrics, metrics_report)
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

    try:
        map_path, gate_path, source_path, output_path, report_path = restore_vnext._validate_paths(
            args.map_file,
            args.gate_dir,
            args.source_root,
            args.output_dir,
            args.report,
        )
    except restore_vnext.RestoreVNextError:
        raise
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
        restored = restore_vnext.load_restore_vnext(
            map_path,
            gate_dir=gate_path,
            source_root=source_path,
            output_dir=staging_restore,
        )
        restore_vnext.write_restore_report_vnext(restored, staging_report)
        restore_vnext.publish_restore_vnext(
            [(staging_restore, output_path), (staging_report, report_path)]
        )
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
    report_required: bool,
) -> None:
    parser.add_argument("--map", dest="map_file", required=True, type=Path)
    parser.add_argument("--gate-dir", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", required=report_required, type=Path)


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="vNext SystemVerilog encryption and restore")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    _register_encrypt_arguments(
        subparsers.add_parser("encrypt-vnext"),
        public_cli=False,
    )
    _register_decrypt_arguments(
        subparsers.add_parser("decrypt-vnext"),
        report_required=False,
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
    _register_decrypt_arguments(parser, report_required=True)
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
