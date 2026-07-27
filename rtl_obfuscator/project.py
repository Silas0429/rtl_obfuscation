"""Top-rooted SystemVerilog project discovery and inspection.

The tolerant portion of this module discovers declarations and preprocessor
dependencies.  Hierarchy identity and all inventory ranges are ultimately
validated against one strict PySlang compilation of the resulting closure.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Iterable

import pyslang

from . import category_profile, inventory


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_DEFINE_ARGUMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*(?:=.*)?\Z")
_IGNORED_DIRECTORIES = frozenset({".git", ".hg", ".svn", "__pycache__"})
_DIRECTIVES = frozenset(
    {
        "define",
        "else",
        "elsif",
        "endif",
        "ifdef",
        "ifndef",
        "include",
        "line",
        "pragma",
        "timescale",
        "undef",
    }
)
_GROUPS = {
    category: (category,) for category in category_profile.CANONICAL_CATEGORIES
}
_GROUPS.update(category_profile.ALIASES)
_GROUPS["all"] = category_profile.DEFAULT_CATEGORIES
_DEFAULT_GROUPS = category_profile.DEFAULT_CATEGORIES


from .project_discovery import (
    ProjectAnalysisError,
    ProjectSemanticContext,
    SourceSetDiscovery,
    _Definition,
    _Edge,
    _ProjectContext,
    _TypeDefinition,
    _discover_files,
    _discover_sourceset,
    _relative_path,
    _strip_comments,
)





def _validate_configuration(
    project_root: Path,
    top: str,
    include_dirs: Iterable[Path | str],
    defines: Iterable[str],
    categories: Iterable[str],
) -> tuple[Path, list[str], dict[str, str], list[str]]:
    root = project_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("--project-root must be an existing directory")
    if _IDENTIFIER.fullmatch(top) is None:
        raise ValueError("--top must be a SystemVerilog identifier")
    normalized_include_dirs: list[str] = []
    for include_dir in include_dirs:
        path = Path(include_dir)
        absolute = (root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("--include-dir must be inside --project-root") from error
        if not absolute.is_dir():
            raise ValueError("--include-dir must be an existing directory")
        if relative not in normalized_include_dirs:
            normalized_include_dirs.append(relative)
    normalized_defines: dict[str, str] = {}
    for item in defines:
        if _DEFINE_ARGUMENT.fullmatch(item) is None:
            raise ValueError("--define must be NAME or NAME=VALUE")
        name, separator, value = item.partition("=")
        normalized_defines[name] = value if separator else "1"
    try:
        selection = category_profile.resolve(
            categories, mode=category_profile.MODE_PROJECT_ROOT
        )
    except category_profile.ProfileResolutionError as error:
        raise ValueError(str(error)) from error
    return (
        root,
        normalized_include_dirs,
        normalized_defines,
        list(selection.selected_categories),
    )


def _empty_report(
    top: str,
    include_dirs: list[str],
    defines: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "error",
        "top": top,
        "compile": {
            "compilation_unit": "single",
            "include_dirs": include_dirs,
            "defines": [
                f"{name}={value}" for name, value in sorted(defines.items())
            ],
            "compile_order": [],
            "parse_errors": 0,
            "semantic_errors": 0,
        },
        "candidate_files": [],
        "definitions": [],
        "dependencies": {"includes": [], "macros": []},
        "reachable": {
            "modules": [],
            "interfaces": [],
            "files": [],
            "source_files": [],
            "header_files": [],
        },
        "inventory": {"eligible": [], "preserved": [], "unsupported": []},
        "diagnostics": [],
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    inventory_entries = report["inventory"]["eligible"]
    return {
        "candidate_files": len(report["candidate_files"]),
        "closure_files": len(report["reachable"]["files"]),
        "definitions": len(report["definitions"]),
        "eligible_occurrences": sum(entry["occurrences"] for entry in inventory_entries),
        "eligible_symbols": len(inventory_entries),
        "reachable_interfaces": len(report["reachable"]["interfaces"]),
        "reachable_modules": len(report["reachable"]["modules"]),
        "status": report["status"],
        "top": report["top"],
    }


def _error_summary(report: dict[str, Any]) -> dict[str, Any]:
    primary = report["diagnostics"][0]
    return {
        "candidate_files": len(report["candidate_files"]),
        "code": primary["code"],
        "status": "error",
        "top": report["top"],
    }


def _analyze_project_with_context(
    *,
    project_root: Path,
    top: str,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
    categories: Iterable[str] = (),
) -> tuple[
    dict[str, Any], dict[str, Any], bool, ProjectSemanticContext | None
]:
    """Analyze a project without writing any output artifacts.

    Invalid invocation values raise ``ValueError``. Project analysis failures
    are returned as ``success=False`` with the same schema used by the CLI.
    """
    root, normalized_dirs, normalized_defines, expanded_categories = (
        _validate_configuration(project_root, top, include_dirs, defines, categories)
    )
    selection = category_profile.resolve(
        categories, mode=category_profile.MODE_PROJECT_ROOT
    )
    report = _empty_report(top, normalized_dirs, normalized_defines)
    report["profile"] = selection.profile
    report["requested_categories"] = list(selection.requested_categories)
    report["selected_categories"] = list(selection.selected_categories)
    report["scope_policy"] = "project_discovered"
    try:
        context = _ProjectContext(
            root, top, normalized_dirs, normalized_defines, expanded_categories
        )
        report["candidate_files"] = context.candidates
        report["definitions"] = [
            definition.report_record() for definition in context.definitions
        ]
        top_definitions = context.definitions_by_name.get(top, [])
        if not top_definitions:
            raise ProjectAnalysisError(
                "TOP_NOT_FOUND", f"top definition not found: {top}"
            )
        if len(top_definitions) != 1:
            raise ProjectAnalysisError(
                "AMBIGUOUS_TOP",
                f"top definition is ambiguous: {top}",
                details=[definition.report_record() for definition in top_definitions],
            )
        if top_definitions[0].kind != "module":
            raise ProjectAnalysisError(
                "TOP_NOT_FOUND", f"top is not a module: {top}"
            )
        closure = {top_definitions[0].file}
        compilation, root_symbol, manager, parse_errors, semantic_errors = (
            context.expand_hierarchy(closure)
        )
        if parse_errors:
            relative, start = context._diagnostic_position(parse_errors[0], manager)
            raise ProjectAnalysisError(
                "PARSE_ERROR",
                "strict closure compilation contains parse errors",
                file=relative,
                start=start,
            )
        if semantic_errors:
            relative, start = context._diagnostic_position(semantic_errors[0], manager)
            raise ProjectAnalysisError(
                "SEMANTIC_ERROR",
                "strict closure compilation contains semantic errors",
                file=relative,
                start=start,
                details=[{"code": str(item.code)} for item in semantic_errors],
            )
        tops = [instance for instance in root_symbol.topInstances if instance.name == top]
        if len(tops) != 1:
            raise ProjectAnalysisError(
                "SEMANTIC_ERROR", "strict compilation did not select exactly one top"
            )
        top_instance = tops[0]
        if "parameters" in expanded_categories:
            for node in inventory._selected_nodes(top_instance):
                if getattr(node, "kind", None) != pyslang.ast.SymbolKind.TypeParameter:
                    continue
                definition = getattr(node, "declaringDefinition", None)
                if (
                    definition is not None
                    and definition.definitionKind
                    == pyslang.ast.DefinitionKind.Module
                ):
                    raise ProjectAnalysisError(
                        "UNSUPPORTED_PARAMETER_KIND",
                        f"type parameter is outside T031 scope: {node.name}",
                        file=_relative_path(
                            root,
                            Path(manager.getFullPath(node.location.buffer)),
                        ),
                        start=node.location.offset,
                    )
        inventory_report, modules, interfaces = inventory.build_top_project_inventory(
            compilation=compilation,
            top_instance=top_instance,
            source_root=root,
            categories=expanded_categories,
            reachable_files=set(closure),
        )
        classification = inventory_report.pop("classification", None)
        compile_order = context.compile_order(closure)
        report["status"] = "pass"
        report["compile"].update(
            {
                "compile_order": compile_order,
                "parse_errors": 0,
                "semantic_errors": 0,
            }
        )
        report["dependencies"] = {
            "includes": [
                edge.report_record()
                for edge in sorted(
                    context.include_edges,
                    key=lambda item: (item.provider, item.consumer, item.name),
                )
                if edge.consumer in closure
            ],
            "macros": [
                edge.report_record()
                for edge in sorted(
                    context.macro_edges,
                    key=lambda item: (item.provider, item.consumer, item.name),
                )
                if edge.consumer in closure
            ],
        }
        report["reachable"] = {
            "modules": sorted(modules),
            "interfaces": sorted(interfaces),
            "files": sorted(closure),
            "source_files": sorted(path for path in closure if path.endswith(".sv")),
            "header_files": sorted(path for path in closure if path.endswith(".svh")),
        }
        report["inventory"] = inventory_report
        if classification is not None:
            report["classification"] = classification
            # The default project profile has no rewrite authority over the
            # top ABI categories, but the ABI still belongs in the audit
            # inventory as preserved.  Keep module declarations in the
            # classification registry (their legacy raw inventory category
            # is intentionally absent) while exposing all other top ABI
            # objects here.
            if selection.profile == category_profile.PROFILE_SINGLE_MODULE:
                def inventory_item(item: dict[str, Any], reason: str | None) -> dict[str, Any]:
                    return {
                        field: item[field]
                        for field in (
                            "category", "scope", "name", "declaration",
                            "references", "occurrences",
                        )
                    } | {"reason": reason}

                default_eligible: list[dict[str, Any]] = []
                default_preserved: list[dict[str, Any]] = []
                selected = set(selection.selected_categories)
                for item in classification["default_profile"]["items"]:
                    if item["category"] not in selected:
                        continue
                    destination = default_preserved if item.get("reason") else default_eligible
                    destination.append(inventory_item(item, item.get("reason")))
                for item in classification["top_abi_preserved"]["items"]:
                    if item["category"] == "modules":
                        continue
                    default_preserved.append(
                        inventory_item(item, item.get("reason") or "top_abi")
                    )

                def inventory_key(item: dict[str, Any]) -> tuple[Any, ...]:
                    declaration = item["declaration"]
                    return (
                        item["category"], item["scope"],
                        declaration["file"] if declaration else "\uffff",
                        declaration["start"] if declaration else 2**63,
                        item["name"],
                    )

                default_eligible.sort(key=inventory_key)
                default_preserved.sort(key=inventory_key)
                inventory_report["eligible"] = default_eligible
                inventory_report["preserved"] = default_preserved
        report["diagnostics"] = []
        result_summary = _summary(report)
        semantic_context = ProjectSemanticContext(
            project_root=root,
            compilation=compilation,
            top_instance=top_instance,
            source_manager=manager,
            closure=tuple(sorted(closure)),
            compile_order=tuple(compile_order),
        )
        return report, result_summary, True, semantic_context
    except (ProjectAnalysisError, OSError, RuntimeError, ValueError) as error:
        if not isinstance(error, ProjectAnalysisError):
            error = ProjectAnalysisError(
                "SEMANTIC_ERROR",
                f"project analysis failed: {error}",
            )
        report["diagnostics"] = [error.diagnostic()]
        try:
            context
        except UnboundLocalError:
            pass
        else:
            report["candidate_files"] = context.candidates
            report["definitions"] = [
                definition.report_record() for definition in context.definitions
            ]
            report["dependencies"] = {
                "includes": [
                    edge.report_record()
                    for edge in sorted(
                        context.include_edges,
                        key=lambda item: (item.provider, item.consumer, item.name),
                    )
                ],
                "macros": [
                    edge.report_record()
                    for edge in sorted(
                        context.macro_edges,
                        key=lambda item: (item.provider, item.consumer, item.name),
                    )
                ],
            }
        return report, _error_summary(report), False, None


def analyze_project(
    *,
    project_root: Path,
    top: str,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
    categories: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Analyze a project without exposing the strict semantic objects."""
    report, summary, success, _ = _analyze_project_with_context(
        project_root=project_root,
        top=top,
        include_dirs=include_dirs,
        defines=defines,
        categories=categories,
    )
    return report, summary, success


def _read_filelist_candidates(filelist: Path, source_root: Path) -> list[str]:
    """Read a bounded filelist without discovering files outside it."""

    candidates: list[str] = []
    seen: set[str] = set()
    for line in filelist.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        path = PurePosixPath(text)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("FILELIST_PATH_OUTSIDE_SOURCE_ROOT: " + text)
        relative = path.as_posix()
        if relative in seen:
            raise ValueError("DUPLICATE_FILELIST_ENTRY: " + relative)
        absolute = (source_root / relative).resolve()
        try:
            absolute.relative_to(source_root.resolve())
        except ValueError as error:
            raise ValueError("FILELIST_PATH_OUTSIDE_SOURCE_ROOT: " + relative) from error
        if not absolute.is_file():
            raise ValueError("MISSING_FILELIST_ENTRY: " + relative)
        if absolute.suffix not in (".sv", ".svh"):
            raise ValueError("UNSUPPORTED_FILELIST_ENTRY: " + relative)
        seen.add(relative)
        candidates.append(relative)
    if not candidates:
        raise ValueError("EMPTY_FILELIST")
    return candidates


def analyze_filelist_context(
    *,
    filelist: Path,
    source_root: Path,
    top: str,
    categories: Iterable[str] = (),
    bounded: bool,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
) -> tuple[
    dict[str, Any], dict[str, Any], bool, ProjectSemanticContext | None
]:
    """Analyze either all listed files or a strict top closure within a filelist."""

    root = source_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("--source-root must be an existing directory")
    if _IDENTIFIER.fullmatch(top) is None:
        raise ValueError("--top must be a SystemVerilog identifier")
    candidates = _read_filelist_candidates(filelist.expanduser().resolve(), root)
    normalized_dirs: list[str] = []
    for include_dir in include_dirs:
        path = Path(include_dir)
        absolute = (root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("--include-dir must be inside --source-root") from error
        if not absolute.is_dir():
            raise ValueError("--include-dir must be an existing directory")
        normalized_dirs.append(relative)
    normalized_defines: dict[str, str] = {}
    for item in defines:
        if _DEFINE_ARGUMENT.fullmatch(item) is None:
            raise ValueError("--define must be NAME or NAME=VALUE")
        name, separator, value = item.partition("=")
        normalized_defines[name] = value if separator else "1"
    try:
        selection = category_profile.resolve(
            categories, mode=category_profile.MODE_FILELIST
        )
    except category_profile.ProfileResolutionError as error:
        raise ValueError(str(error)) from error

    report = _empty_report(top, normalized_dirs, normalized_defines)
    report["candidate_files"] = list(candidates)
    context: _ProjectContext | None = None
    try:
        context = _ProjectContext(
            root,
            top,
            normalized_dirs,
            normalized_defines,
            list(selection.selected_categories),
            candidate_files=candidates,
        )
        report["definitions"] = [
            definition.report_record() for definition in context.definitions
        ]
        top_definitions = context.definitions_by_name.get(top, [])
        if not top_definitions:
            raise ProjectAnalysisError("TOP_NOT_FOUND", f"top definition not found: {top}")
        if len(top_definitions) != 1:
            raise ProjectAnalysisError(
                "AMBIGUOUS_TOP",
                f"top definition is ambiguous: {top}",
                details=[definition.report_record() for definition in top_definitions],
            )
        if top_definitions[0].kind != "module":
            raise ProjectAnalysisError("TOP_NOT_FOUND", f"top is not a module: {top}")

        closure = {top_definitions[0].file}
        if bounded:
            compilation, root_symbol, manager, parse_errors, semantic_errors = (
                context.expand_hierarchy(closure)
            )
        else:
            closure = set(candidates)
            compilation, root_symbol, manager, parse_errors, semantic_errors = (
                context.compile(closure)
            )
        if parse_errors:
            relative, start = context._diagnostic_position(parse_errors[0], manager)
            raise ProjectAnalysisError(
                "PARSE_ERROR", "strict filelist compilation contains parse errors", file=relative, start=start
            )
        if semantic_errors:
            relative, start = context._diagnostic_position(semantic_errors[0], manager)
            raise ProjectAnalysisError(
                "SEMANTIC_ERROR", "strict filelist compilation contains semantic errors", file=relative, start=start,
                details=[{"code": str(item.code)} for item in semantic_errors],
            )
        tops = [instance for instance in root_symbol.topInstances if instance.name == top]
        if len(tops) != 1:
            raise ProjectAnalysisError("SEMANTIC_ERROR", "strict compilation did not select exactly one top")
        top_instance = tops[0]
        compile_order = context.compile_order(closure)
        report["status"] = "pass"
        report["compile"].update(
            {"compile_order": compile_order, "parse_errors": 0, "semantic_errors": 0}
        )
        report["dependencies"] = {
            "includes": [
                edge.report_record()
                for edge in sorted(context.include_edges, key=lambda item: (item.provider, item.consumer, item.name))
                if not bounded or edge.consumer in closure
            ],
            "macros": [
                edge.report_record()
                for edge in sorted(context.macro_edges, key=lambda item: (item.provider, item.consumer, item.name))
                if not bounded or edge.consumer in closure
            ],
        }
        modules = sorted(
            definition.name
            for definition in context.definitions
            if definition.kind == "module" and definition.file in closure
        )
        interfaces = sorted(
            definition.name
            for definition in context.definitions
            if definition.kind == "interface" and definition.file in closure
        )
        report["reachable"] = {
            "modules": modules,
            "interfaces": interfaces,
            "files": sorted(closure),
            "source_files": sorted(path for path in closure if path.endswith(".sv")),
            "header_files": sorted(path for path in closure if path.endswith(".svh")),
        }
        report["profile"] = selection.profile
        report["requested_categories"] = list(selection.requested_categories)
        report["selected_categories"] = list(selection.selected_categories)
        report["scope_policy"] = "filelist_bounded" if bounded else "all_filelist_files"
        report["diagnostics"] = []
        result_summary = _summary(report)
        semantic_context = ProjectSemanticContext(
            project_root=root,
            compilation=compilation,
            top_instance=top_instance,
            source_manager=manager,
            closure=tuple(sorted(closure)),
            compile_order=tuple(compile_order),
            candidate_files=tuple(candidates),
            scope_policy="filelist_bounded" if bounded else "all_filelist_files",
        )
        return report, result_summary, True, semantic_context
    except (ProjectAnalysisError, OSError, RuntimeError, ValueError) as error:
        if not isinstance(error, ProjectAnalysisError):
            error = ProjectAnalysisError("SEMANTIC_ERROR", f"filelist analysis failed: {error}")
        report["diagnostics"] = [error.diagnostic()]
        if context is not None:
            report["definitions"] = [definition.report_record() for definition in context.definitions]
        return report, _error_summary(report), False, None


def analyze_project_context(
    *,
    project_root: Path,
    top: str,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
    categories: Iterable[str] = (),
) -> tuple[
    dict[str, Any], dict[str, Any], bool, ProjectSemanticContext | None
]:
    """Analyze once and return the selected strict semantic context."""
    return _analyze_project_with_context(
        project_root=project_root,
        top=top,
        include_dirs=include_dirs,
        defines=defines,
        categories=categories,
    )


def inspect_project(
    *,
    project_root: Path,
    top: str,
    report_path: Path,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
    categories: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Analyze a project and atomically emit its schema-v1 report."""
    report, summary, success = analyze_project(
        project_root=project_root,
        top=top,
        include_dirs=include_dirs,
        defines=defines,
        categories=categories,
    )
    _write_json_atomic(report_path, report)
    return report, summary, success
