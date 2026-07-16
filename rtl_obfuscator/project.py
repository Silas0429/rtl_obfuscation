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

from . import inventory


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
    "signals": ("signals",),
    "ports": ("ports",),
    "instances": ("instances",),
    "struct": ("struct_types", "struct_fields"),
    "interface": (
        "interfaces",
        "interface_instances",
        "interface_ports",
        "modports",
    ),
}


@dataclass(frozen=True)
class _Definition:
    kind: str
    name: str
    file: str
    start: int
    end: int

    def report_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "file": self.file,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class _TypeDefinition:
    name: str
    file: str


@dataclass(frozen=True)
class _Edge:
    provider: str
    consumer: str
    name: str

    def report_record(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "consumer": self.consumer,
            "name": self.name,
        }


class ProjectAnalysisError(Exception):
    """A stable project-analysis failure that belongs in the JSON report."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        file: str | None = None,
        start: int | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.file = file
        self.start = start
        self.details = details or []

    def diagnostic(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "file": self.file,
            "start": self.start,
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _discover_files(root: Path) -> list[str]:
    discovered: list[str] = []
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(
            name
            for name in names
            if name not in _IGNORED_DIRECTORIES
            and not (Path(directory) / name).is_symlink()
        )
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix not in (".sv", ".svh"):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            discovered.append(_relative_path(root, path))
    return sorted(discovered)


def _strip_comments(source: str) -> str:
    """Remove comments while keeping offsets and newlines stable."""
    result = list(source)
    index = 0
    in_block = False
    in_string = False
    escaped = False
    while index < len(source):
        if in_block:
            if source.startswith("*/", index):
                result[index] = result[index + 1] = " "
                index += 2
                in_block = False
            else:
                if source[index] != "\n":
                    result[index] = " "
                index += 1
            continue
        character = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            index += 1
        elif source.startswith("//", index):
            while index < len(source) and source[index] != "\n":
                result[index] = " "
                index += 1
        elif source.startswith("/*", index):
            result[index] = result[index + 1] = " "
            index += 2
            in_block = True
        else:
            index += 1
    return "".join(result)


class _ProjectContext:
    def __init__(
        self,
        root: Path,
        top: str,
        include_dirs: list[str],
        defines: dict[str, str],
        categories: list[str],
    ) -> None:
        self.root = root
        self.top = top
        self.include_dirs = include_dirs
        self.defines = defines
        self.categories = categories
        self.candidates = _discover_files(root)
        self.candidate_set = set(self.candidates)
        self.candidate_dirs = sorted(
            {str(PurePosixPath(path).parent) for path in self.candidates}
        )
        self.sources = {
            path: (root / path).read_text(encoding="utf-8")
            for path in self.candidates
        }
        self.clean_sources = {
            path: _strip_comments(source) for path, source in self.sources.items()
        }
        self.syntax_trees: list[Any] = []
        self.definitions: list[_Definition] = []
        self.definitions_by_name: dict[str, list[_Definition]] = {}
        self.types_by_name: dict[str, list[_TypeDefinition]] = {}
        self.source_dependencies: set[_Edge] = set()
        self.include_edges: set[_Edge] = set()
        self.macro_edges: set[_Edge] = set()
        self.global_macro_providers: dict[str, set[str]] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        syntax_kind = {
            pyslang.syntax.SyntaxKind.ModuleDeclaration: "module",
            pyslang.syntax.SyntaxKind.InterfaceDeclaration: "interface",
            pyslang.syntax.SyntaxKind.PackageDeclaration: "package",
        }
        for relative in self.candidates:
            tree = pyslang.syntax.SyntaxTree.fromFile(str(self.root / relative))
            self.syntax_trees.append(tree)
            nodes: list[Any] = []
            tree.root.visit(nodes.append)
            for node in nodes:
                node_type = type(node).__name__
                if getattr(node, "kind", None) in syntax_kind:
                    token = node.header.name
                    if not token.rawText:
                        raise ProjectAnalysisError(
                            "UNSUPPORTED_MACRO_IDENTIFIER",
                            "a definition name is produced by a macro expansion",
                            file=relative,
                            start=token.location.offset,
                        )
                    definition = _Definition(
                        syntax_kind[node.kind],
                        token.rawText,
                        relative,
                        token.location.offset,
                        token.location.offset + len(token.rawText.encode("utf-8")),
                    )
                    self.definitions.append(definition)
                    self.definitions_by_name.setdefault(definition.name, []).append(
                        definition
                    )
                elif node_type == "TypedefDeclarationSyntax":
                    token = node.name
                    if token.rawText:
                        self.types_by_name.setdefault(token.rawText, []).append(
                            _TypeDefinition(token.rawText, relative)
                        )
        self.definitions.sort(
            key=lambda item: (item.kind, item.name, item.file, item.start, item.end)
        )
        for definitions in self.definitions_by_name.values():
            definitions.sort(key=lambda item: (item.kind, item.file, item.start))
        for definitions in self.types_by_name.values():
            definitions.sort(key=lambda item: item.file)
        self._index_macro_providers()

    @staticmethod
    def _directive(line: str) -> tuple[str, str] | None:
        match = re.match(r"\s*`([A-Za-z_][A-Za-z0-9_$]*)(.*)", line)
        if match is None:
            return None
        return match.group(1), match.group(2).strip()

    def _index_macro_providers(self) -> None:
        for relative in self.candidates:
            env = dict(self.defines)
            active = True
            stack: list[tuple[bool, bool]] = []
            for line in self.clean_sources[relative].splitlines():
                directive = self._directive(line)
                if directive is None:
                    continue
                name, argument = directive
                macro_name = argument.split(None, 1)[0] if argument else ""
                if name in ("ifdef", "ifndef"):
                    condition = macro_name in env
                    if name == "ifndef":
                        condition = not condition
                    stack.append((active, condition))
                    active = active and condition
                elif name == "elsif" and stack:
                    parent, taken = stack[-1]
                    condition = macro_name in env
                    stack[-1] = (parent, taken or condition)
                    active = parent and not taken and condition
                elif name == "else" and stack:
                    parent, taken = stack[-1]
                    active = parent and not taken
                    stack[-1] = (parent, True)
                elif name == "endif" and stack:
                    parent, _ = stack.pop()
                    active = parent
                elif name == "define" and active:
                    match = re.match(r"([A-Za-z_][A-Za-z0-9_$]*)", argument)
                    if match is not None:
                        macro = match.group(1)
                        env[macro] = "1"
                        self.global_macro_providers.setdefault(macro, set()).add(
                            relative
                        )
                elif name == "undef" and active:
                    env.pop(macro_name, None)

    def _resolve_include(self, consumer: str, include_name: str) -> str:
        include_path = PurePosixPath(include_name)
        if include_path.is_absolute() or ".." in include_path.parts:
            raise ProjectAnalysisError(
                "MISSING_INCLUDE",
                f"include is outside project root: {include_name}",
                file=consumer,
            )
        local = str(PurePosixPath(consumer).parent / include_path)
        if local in self.candidate_set:
            return local
        for directory in self.include_dirs:
            candidate = str(PurePosixPath(directory) / include_path)
            if candidate in self.candidate_set:
                return candidate
        automatic = sorted(
            {
                str(PurePosixPath(directory) / include_path)
                for directory in self.candidate_dirs
                if str(PurePosixPath(directory) / include_path)
                in self.candidate_set
            }
        )
        if not automatic:
            raise ProjectAnalysisError(
                "MISSING_INCLUDE",
                f"include file not found: {include_name}",
                file=consumer,
            )
        if len(automatic) != 1:
            raise ProjectAnalysisError(
                "AMBIGUOUS_INCLUDE",
                f"include resolves to multiple project files: {include_name}",
                file=consumer,
                details=[{"candidate": path} for path in automatic],
            )
        return automatic[0]

    def _scan_preprocessed_file(
        self,
        relative: str,
        env: dict[str, str | None],
        closure: set[str],
        include_stack: tuple[str, ...],
    ) -> set[str]:
        added: set[str] = set()
        active = True
        stack: list[tuple[bool, bool]] = []
        for line_number, line in enumerate(
            self.clean_sources[relative].splitlines(keepends=True), 1
        ):
            directive = self._directive(line)
            if directive is not None:
                name, argument = directive
                macro_name = argument.split(None, 1)[0] if argument else ""
                if name in ("ifdef", "ifndef"):
                    condition = macro_name in env
                    if name == "ifndef":
                        condition = not condition
                    stack.append((active, condition))
                    active = active and condition
                    continue
                if name == "elsif":
                    if not stack:
                        raise ProjectAnalysisError(
                            "PREPROCESS_ERROR",
                            "`elsif without matching conditional",
                            file=relative,
                        )
                    parent, taken = stack[-1]
                    condition = macro_name in env
                    stack[-1] = (parent, taken or condition)
                    active = parent and not taken and condition
                    continue
                if name == "else":
                    if not stack:
                        raise ProjectAnalysisError(
                            "PREPROCESS_ERROR",
                            "`else without matching conditional",
                            file=relative,
                        )
                    parent, taken = stack[-1]
                    active = parent and not taken
                    stack[-1] = (parent, True)
                    continue
                if name == "endif":
                    if not stack:
                        raise ProjectAnalysisError(
                            "PREPROCESS_ERROR",
                            "`endif without matching conditional",
                            file=relative,
                        )
                    parent, _ = stack.pop()
                    active = parent
                    continue
                if not active:
                    continue
                if name == "include":
                    match = re.match(r'"([^"]+)"', argument)
                    if match is None:
                        raise ProjectAnalysisError(
                            "PREPROCESS_ERROR",
                            "only quoted include paths are supported",
                            file=relative,
                        )
                    provider = self._resolve_include(relative, match.group(1))
                    self.include_edges.add(_Edge(provider, relative, match.group(1)))
                    if provider in include_stack:
                        raise ProjectAnalysisError(
                            "PREPROCESS_ERROR",
                            "recursive include dependency",
                            file=relative,
                        )
                    if provider not in closure:
                        added.add(provider)
                    added.update(
                        self._scan_preprocessed_file(
                            provider,
                            env,
                            closure | added,
                            (*include_stack, provider),
                        )
                    )
                    continue
                if name == "define":
                    match = re.match(r"([A-Za-z_][A-Za-z0-9_$]*)", argument)
                    if match is not None:
                        env[match.group(1)] = relative
                    continue
                if name == "undef":
                    env.pop(macro_name, None)
                    continue
                if name in _DIRECTIVES:
                    continue
            if not active:
                continue
            for match in re.finditer(r"`([A-Za-z_][A-Za-z0-9_$]*)", line):
                macro = match.group(1)
                if macro in _DIRECTIVES:
                    continue
                if macro in self.defines:
                    continue
                local_provider = env.get(macro)
                if local_provider is not None:
                    if local_provider != relative:
                        self.macro_edges.add(
                            _Edge(local_provider, relative, macro)
                        )
                    continue
                providers = sorted(self.global_macro_providers.get(macro, set()))
                if not providers:
                    raise ProjectAnalysisError(
                        "UNRESOLVED_MACRO",
                        f"macro has no provider: {macro}",
                        file=relative,
                    )
                if len(providers) != 1:
                    raise ProjectAnalysisError(
                        "AMBIGUOUS_MACRO",
                        f"macro has multiple providers: {macro}",
                        file=relative,
                        details=[{"provider": provider} for provider in providers],
                    )
                provider = providers[0]
                env[macro] = provider
                self.macro_edges.add(_Edge(provider, relative, macro))
                if provider not in closure:
                    added.add(provider)
            if stack and line_number == len(self.clean_sources[relative].splitlines()):
                pass
        if stack:
            raise ProjectAnalysisError(
                "PREPROCESS_ERROR",
                "unterminated conditional directive",
                file=relative,
            )
        return added

    def add_preprocessor_dependencies(self, closure: set[str]) -> bool:
        additions: set[str] = set()
        for relative in sorted(closure):
            env: dict[str, str | None] = {
                name: None for name in self.defines
            }
            additions.update(
                self._scan_preprocessed_file(relative, env, closure, (relative,))
            )
        before = len(closure)
        closure.update(additions)
        return len(closure) != before

    def add_type_dependencies(self, closure: set[str]) -> bool:
        additions: set[str] = set()
        for consumer in sorted(closure):
            source = self.clean_sources[consumer]
            words = set(_IDENTIFIER.findall(source))
            for name in sorted(words & self.types_by_name.keys()):
                providers = self.types_by_name[name]
                provider_files = sorted({provider.file for provider in providers})
                if len(provider_files) > 1:
                    raise ProjectAnalysisError(
                        "SEMANTIC_ERROR",
                        f"type has multiple providers: {name}",
                        file=consumer,
                    )
                provider = provider_files[0]
                if provider == consumer:
                    continue
                self.source_dependencies.add(_Edge(provider, consumer, name))
                additions.add(provider)
        before = len(closure)
        closure.update(additions)
        return len(closure) != before

    def _bags(self) -> tuple[Any, Any]:
        bag = pyslang.Bag()
        preprocessor = pyslang.parsing.PreprocessorOptions()
        preprocessor.predefines = [
            f"{name}={value}" for name, value in sorted(self.defines.items())
        ]
        bag.preprocessorOptions = preprocessor
        options = pyslang.ast.CompilationOptions()
        options.topModules = {self.top}
        bag.compilationOptions = options
        return bag, options

    def compile(self, closure: set[str]) -> tuple[Any, Any, Any, list[Any], list[Any]]:
        source_manager = pyslang.SourceManager()
        for directory in [*self.include_dirs, *self.candidate_dirs]:
            source_manager.addUserDirectories(str(self.root / directory))
        bag, _ = self._bags()
        compile_order = self.compile_order(closure)
        source_paths = [str(self.root / path) for path in compile_order]
        syntax_tree = pyslang.syntax.SyntaxTree.fromFiles(
            source_paths, source_manager, bag
        )
        parse_diagnostics = [
            diagnostic
            for diagnostic in syntax_tree.diagnostics
            if diagnostic.isError()
        ]
        compilation = pyslang.ast.Compilation(bag)
        compilation.addSyntaxTree(syntax_tree)
        root = compilation.getRoot()
        all_errors = [
            diagnostic
            for diagnostic in compilation.getAllDiagnostics()
            if diagnostic.isError()
        ]
        parse_keys = {
            (str(diagnostic.code), diagnostic.location.buffer, diagnostic.location.offset)
            for diagnostic in parse_diagnostics
        }
        semantic_diagnostics = [
            diagnostic
            for diagnostic in all_errors
            if (
                str(diagnostic.code),
                diagnostic.location.buffer,
                diagnostic.location.offset,
            )
            not in parse_keys
        ]
        return (
            compilation,
            root,
            source_manager,
            parse_diagnostics,
            semantic_diagnostics,
        )

    def compile_order(self, closure: set[str]) -> list[str]:
        source_files = {path for path in closure if path.endswith(".sv")}
        incoming = {path: set() for path in source_files}
        outgoing = {path: set() for path in source_files}
        for edge in (
            self.source_dependencies | self.macro_edges | self.include_edges
        ):
            if edge.provider not in source_files or edge.consumer not in source_files:
                continue
            if edge.provider == edge.consumer:
                continue
            incoming[edge.consumer].add(edge.provider)
            outgoing[edge.provider].add(edge.consumer)
        ready = sorted(path for path, deps in incoming.items() if not deps)
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for consumer in sorted(outgoing[current]):
                incoming[consumer].discard(current)
                if not incoming[consumer] and consumer not in ordered and consumer not in ready:
                    ready.append(consumer)
                    ready.sort()
        if len(ordered) != len(source_files):
            ordered.extend(sorted(source_files - set(ordered)))
        return ordered

    def _diagnostic_position(self, diagnostic: Any, manager: Any) -> tuple[str | None, int | None]:
        try:
            absolute = Path(manager.getFullPath(diagnostic.location.buffer)).resolve()
            return _relative_path(self.root, absolute), diagnostic.location.offset
        except (OSError, ValueError, RuntimeError):
            return None, None

    def _identifier_at(self, relative: str, offset: int) -> str:
        source = self.sources[relative].encode("utf-8")
        start = max(0, offset)
        while start > 0 and (
            chr(source[start - 1]).isalnum()
            or chr(source[start - 1]) in "_$"
        ):
            start -= 1
        end = max(0, offset)
        while end < len(source) and (
            chr(source[end]).isalnum() or chr(source[end]) in "_$"
        ):
            end += 1
        return source[start:end].decode("utf-8")

    def expand_hierarchy(self, closure: set[str]) -> tuple[Any, Any, Any, list[Any], list[Any]]:
        while True:
            changed = True
            while changed:
                changed = self.add_type_dependencies(closure)
                changed = self.add_preprocessor_dependencies(closure) or changed
            compiled = self.compile(closure)
            _, _, manager, _, semantic = compiled
            unknown = [
                diagnostic
                for diagnostic in semantic
                if str(diagnostic.code) in (
                    "DiagCode(UnknownModule)",
                    "DiagCode(UnknownInterface)",
                )
            ]
            additions: set[str] = set()
            for diagnostic in unknown:
                relative, offset = self._diagnostic_position(diagnostic, manager)
                if relative is None or offset is None:
                    continue
                name = self._identifier_at(relative, offset)
                definitions = self.definitions_by_name.get(name, [])
                if not definitions:
                    code = (
                        "UNRESOLVED_INTERFACE"
                        if "Interface" in str(diagnostic.code)
                        else "UNRESOLVED_MODULE"
                    )
                    raise ProjectAnalysisError(
                        code,
                        f"reachable definition not found: {name}",
                        file=relative,
                        start=offset,
                    )
                if len(definitions) != 1:
                    raise ProjectAnalysisError(
                        "AMBIGUOUS_DEFINITION",
                        f"reachable definition is ambiguous: {name}",
                        file=relative,
                        start=offset,
                        details=[definition.report_record() for definition in definitions],
                    )
                provider = definitions[0].file
                self.source_dependencies.add(_Edge(provider, relative, name))
                additions.add(provider)
            before = len(closure)
            closure.update(additions)
            if len(closure) == before:
                return compiled


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
    normalized_categories = list(categories)
    if not normalized_categories:
        normalized_categories = list(_GROUPS)
    if any(category not in _GROUPS for category in normalized_categories):
        raise ValueError("unsupported inspect-project category")
    expanded: list[str] = []
    for category in normalized_categories:
        for concrete in _GROUPS[category]:
            if concrete not in expanded:
                expanded.append(concrete)
    return root, normalized_include_dirs, normalized_defines, expanded


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


def inspect_project(
    *,
    project_root: Path,
    top: str,
    report_path: Path,
    include_dirs: Iterable[Path | str] = (),
    defines: Iterable[str] = (),
    categories: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Inspect a project and atomically emit its schema-v1 report.

    Invalid invocation values raise ``ValueError``. Project analysis failures
    are returned as ``success=False`` after an error report is written.
    """
    root, normalized_dirs, normalized_defines, expanded_categories = (
        _validate_configuration(project_root, top, include_dirs, defines, categories)
    )
    report = _empty_report(top, normalized_dirs, normalized_defines)
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
        inventory_report, modules, interfaces = inventory.build_top_project_inventory(
            compilation=compilation,
            top_instance=top_instance,
            source_root=root,
            categories=expanded_categories,
        )
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
        report["diagnostics"] = []
        result_summary = _summary(report)
        _write_json_atomic(report_path, report)
        return report, result_summary, True
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
        _write_json_atomic(report_path, report)
        return report, _error_summary(report), False
