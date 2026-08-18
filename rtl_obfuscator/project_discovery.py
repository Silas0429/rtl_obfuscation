"""Inventory-free SystemVerilog source discovery for the vNext product path.

The tolerant portion of this module discovers declarations and preprocessor
dependencies.  Hierarchy identity and all inventory ranges are ultimately
validated against one strict PySlang compilation of the resulting closure.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import posixpath
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Iterable

import pyslang

from .rtl_files import (
    is_context_file,
    is_header_file,
    is_physical_rtl_file,
    is_source_file,
)


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_DEFINE_ARGUMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*(?:=.*)?\Z")
_IGNORED_DIRECTORIES = frozenset({".git", ".hg", ".svn", "__pycache__"})
_BUILTIN_PREPROCESSOR_MACROS = frozenset(
    {"__FILE__", "__LINE__", "__DATE__", "__TIME__", "__TIMESTAMP__"}
)
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
class _MacroDefinition:
    name: str
    formal_names: frozenset[str]
    formal_text: str
    body_lines: tuple[str, ...]


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


@dataclass(frozen=True)
class ProjectSemanticContext:
    """Strict semantic objects selected by the shared project resolver."""

    project_root: Path
    compilation: Any
    top_instance: Any
    source_manager: Any
    closure: tuple[str, ...]
    compile_order: tuple[str, ...]
    candidate_files: tuple[str, ...] = ()
    scope_policy: str = "project_discovered"


@dataclass(frozen=True)
class SourceSetDiscovery:
    """Discovery-only result used by the SourceSet input adapters."""

    included_files: tuple[str, ...]
    top_closure_files: tuple[str, ...]
    compile_order: tuple[str, ...]


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
            if not is_physical_rtl_file(path):
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


def _continuation_piece(line: str) -> tuple[str, bool]:
    text = line.rstrip("\r\n")
    match = re.search(r"\\[ \t]*$", text)
    if match is None:
        return text, False
    return text[: match.start()], True


def _split_macro_formals(text: str) -> frozenset[str]:
    names: set[str] = set()
    current: list[str] = []
    depth = 0
    parts: list[str] = []
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        if character == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
    if current or text.strip():
        parts.append("".join(current))
    for part in parts:
        match = _IDENTIFIER.match(part.strip())
        if match is not None:
            names.add(match.group(0))
    return frozenset(names)


def _parse_macro_definition(argument: str) -> _MacroDefinition | None:
    match = _IDENTIFIER.match(argument.strip())
    if match is None:
        return None
    name = match.group(0)
    rest = argument[argument.find(name) + len(name) :]
    formal_text = ""
    body = rest
    if rest.startswith("("):
        depth = 0
        closing = None
        for index, character in enumerate(rest):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            return _MacroDefinition(name, frozenset(), "", (rest,))
        formal_text = rest[1:closing]
        body = rest[closing + 1 :]
    return _MacroDefinition(
        name=name,
        formal_names=_split_macro_formals(formal_text),
        formal_text=formal_text,
        body_lines=tuple(body.splitlines()),
    )


def _iter_preprocessor_units(source: str) -> Iterable[str | _MacroDefinition]:
    lines = source.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        directive = _ProjectContext._directive(line)
        if directive is None or directive[0] != "define":
            yield line
            index += 1
            continue
        first_piece, continued = _continuation_piece(line)
        first_directive = _ProjectContext._directive(first_piece)
        if first_directive is None:
            yield line
            index += 1
            continue
        parts = [first_directive[1]]
        index += 1
        while continued and index < len(lines):
            piece, continued = _continuation_piece(lines[index])
            parts.append(piece)
            index += 1
        macro = _parse_macro_definition("\n".join(parts))
        if macro is None:
            yield first_piece
        else:
            yield macro


class _ProjectContext:
    def __init__(
        self,
        root: Path,
        top: str,
        include_dirs: list[str],
        defines: dict[str, str],
        categories: list[str],
        candidate_files: Iterable[str] | None = None,
    ) -> None:
        self.root = root
        self.top = top
        self.include_dirs = include_dirs
        self.defines = defines
        conflicting_defines = sorted(
            set(defines) & _BUILTIN_PREPROCESSOR_MACROS
        )
        if conflicting_defines:
            macro = conflicting_defines[0]
            raise ProjectAnalysisError(
                "AMBIGUOUS_MACRO",
                f"built-in macro cannot be supplied as a project define: {macro}",
                details=[
                    {"provider": "<builtin>"},
                    {"provider": "<project-define>"},
                ],
            )
        self.categories = categories
        self.candidates = sorted(
            candidate_files if candidate_files is not None else _discover_files(root)
        )
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
        self.global_macro_fallback_providers: dict[str, set[str]] = {}
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
            env = {
                **self.defines,
                **{name: None for name in _BUILTIN_PREPROCESSOR_MACROS},
            }
            active = True
            stack: list[tuple[bool, bool, str | None, str]] = []
            for unit in _iter_preprocessor_units(self.clean_sources[relative]):
                if isinstance(unit, _MacroDefinition):
                    if not active:
                        continue
                    macro = unit.name
                    if macro in _BUILTIN_PREPROCESSOR_MACROS:
                        raise ProjectAnalysisError(
                            "AMBIGUOUS_MACRO",
                            f"built-in macro cannot be redefined: {macro}",
                            file=relative,
                            details=[
                                {"provider": "<builtin>"},
                                {"provider": relative},
                            ],
                        )
                    env[macro] = "1"
                    fallback = any(
                        branch == "ifndef" and guarded_macro == macro
                        for _, _, branch, guarded_macro in stack
                    )
                    providers = (
                        self.global_macro_fallback_providers
                        if fallback
                        else self.global_macro_providers
                    )
                    providers.setdefault(macro, set()).add(relative)
                    continue
                line = unit
                directive = self._directive(line)
                if directive is None:
                    continue
                name, argument = directive
                macro_name = argument.split(None, 1)[0] if argument else ""
                if name in ("ifdef", "ifndef"):
                    condition = macro_name in env
                    if name == "ifndef":
                        condition = not condition
                    stack.append((active, condition, name, macro_name))
                    active = active and condition
                elif name == "elsif" and stack:
                    parent, taken, _, _ = stack[-1]
                    condition = macro_name in env
                    stack[-1] = (parent, taken or condition, None, "")
                    active = parent and not taken and condition
                elif name == "else" and stack:
                    parent, taken, _, _ = stack[-1]
                    active = parent and not taken
                    stack[-1] = (parent, True, None, "")
                elif name == "endif" and stack:
                    parent, _, _, _ = stack.pop()
                    active = parent
                elif name == "undef" and active:
                    env.pop(macro_name, None)

    def _resolve_include(self, consumer: str, include_name: str) -> str:
        include_path = PurePosixPath(include_name)
        if include_path.is_absolute():
            raise ProjectAnalysisError(
                "MISSING_INCLUDE",
                f"include is outside project root: {include_name}",
                file=consumer,
            )
        local = posixpath.normpath(
            str(PurePosixPath(consumer).parent / include_path)
        )
        if local == ".." or local.startswith("../"):
            raise ProjectAnalysisError(
                "MISSING_INCLUDE",
                f"include is outside project root: {include_name}",
                file=consumer,
            )
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

    def _scan_preprocessed_units(
        self,
        relative: str,
        units: Iterable[str | _MacroDefinition],
        env: dict[str, str | None],
        closure: set[str],
        include_stack: tuple[str, ...],
        formal_parameters: frozenset[str] = frozenset(),
    ) -> set[str]:
        added: set[str] = set()
        active = True
        stack: list[tuple[bool, bool]] = []
        for unit in units:
            if isinstance(unit, _MacroDefinition):
                if not active:
                    continue
                macro = unit.name
                if macro in _BUILTIN_PREPROCESSOR_MACROS:
                    raise ProjectAnalysisError(
                        "AMBIGUOUS_MACRO",
                        f"built-in macro cannot be redefined: {macro}",
                        file=relative,
                        details=[
                            {"provider": "<builtin>"},
                            {"provider": relative},
                        ],
                    )
                env[macro] = relative
                body_units: list[str | _MacroDefinition] = []
                if unit.formal_text:
                    body_units.append(unit.formal_text)
                body_units.extend(unit.body_lines)
                added.update(
                    self._scan_preprocessed_units(
                        relative,
                        body_units,
                        env,
                        closure | added,
                        include_stack,
                        unit.formal_names,
                    )
                )
                continue
            line = unit
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
                        macro = match.group(1)
                        if macro in _BUILTIN_PREPROCESSOR_MACROS:
                            raise ProjectAnalysisError(
                                "AMBIGUOUS_MACRO",
                                f"built-in macro cannot be redefined: {macro}",
                                file=relative,
                                details=[
                                    {"provider": "<builtin>"},
                                    {"provider": relative},
                                ],
                            )
                        env[macro] = relative
                    continue
                if name == "undef":
                    env.pop(macro_name, None)
                    continue
                if name in _DIRECTIVES:
                    continue
            if not active:
                continue
            for match in re.finditer(r"`([A-Za-z_][A-Za-z0-9_$]*)", line):
                if match.start() > 0 and line[match.start() - 1] == "`":
                    continue
                macro = match.group(1)
                if macro in _DIRECTIVES:
                    continue
                if macro in formal_parameters:
                    continue
                if macro in _BUILTIN_PREPROCESSOR_MACROS:
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
                    providers = sorted(
                        self.global_macro_fallback_providers.get(macro, set())
                    )
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
        if stack:
            raise ProjectAnalysisError(
                "PREPROCESS_ERROR",
                "unterminated conditional directive",
                file=relative,
            )
        return added

    def _scan_preprocessed_file(
        self,
        relative: str,
        env: dict[str, str | None],
        closure: set[str],
        include_stack: tuple[str, ...],
    ) -> set[str]:
        return self._scan_preprocessed_units(
            relative,
            _iter_preprocessor_units(self.clean_sources[relative]),
            env,
            closure,
            include_stack,
        )

    def add_preprocessor_dependencies(self, closure: set[str]) -> bool:
        additions: set[str] = set()
        for relative in sorted(closure):
            env: dict[str, str | None] = {
                name: None
                for name in (*self.defines, *_BUILTIN_PREPROCESSOR_MACROS)
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
        context_paths = sorted(
            path for path in closure if is_context_file(path)
        )
        source_paths = [
            str(self.root / path) for path in (*context_paths, *compile_order)
        ]
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
        source_files = {path for path in closure if is_source_file(path)}
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


def _discover_sourceset(
    *,
    root: Path,
    candidate_files: Iterable[str],
    source_files: Iterable[str],
    explicit_header_files: Iterable[str] = (),
    include_dirs: Iterable[str] = (),
    defines: dict[str, str] | None = None,
    top: str | None = None,
    preserve_top_file_order: bool = False,
    include_all_sources: bool = True,
) -> SourceSetDiscovery:
    """Resolve SourceSet dependencies without inventory or report generation.

    ``candidate_files`` is the bounded discovery universe.  The helper keeps
    the existing include, macro, type, and hierarchy algorithms in one place;
    callers decide which source files are part of the public SourceSet.
    """

    source_order = tuple(source_files)
    candidate_order = tuple(candidate_files)
    context = _ProjectContext(
        root,
        top or "",
        list(include_dirs),
        dict(defines or {}),
        [],
        candidate_files=candidate_order,
    )

    if include_all_sources:
        include_closure = set(source_order)
        changed = True
        while changed:
            changed = context.add_preprocessor_dependencies(include_closure)

    if top is None:
        for edge in context.include_edges:
            if not (is_physical_rtl_file(edge.provider) or is_context_file(edge.provider)):
                raise ProjectAnalysisError(
                    "UNSUPPORTED_INCLUDE",
                    f"include dependency is not a supported RTL provider: {edge.provider}",
                    file=edge.consumer,
                )
        included_files = {
            edge.provider for edge in context.include_edges
            if is_header_file(edge.provider) or is_context_file(edge.provider)
        }
        included_files.update(explicit_header_files)
        return SourceSetDiscovery(
            included_files=tuple(sorted(included_files)),
            top_closure_files=(),
            compile_order=source_order,
        )

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
        raise ProjectAnalysisError("TOP_NOT_FOUND", f"top is not a module: {top}")

    closure = {top_definitions[0].file}
    compilation, _, manager, parse_errors, semantic_errors = context.expand_hierarchy(
        closure
    )
    del compilation
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

    for edge in context.include_edges:
        if not (is_physical_rtl_file(edge.provider) or is_context_file(edge.provider)):
            raise ProjectAnalysisError(
                "UNSUPPORTED_INCLUDE",
                f"include dependency is not a supported RTL provider: {edge.provider}",
                file=edge.consumer,
            )
    included_files = {
        edge.provider for edge in context.include_edges
        if is_header_file(edge.provider) or is_context_file(edge.provider)
    }
    included_files.update(explicit_header_files)

    closure_sources = set(path for path in closure if is_source_file(path))
    if preserve_top_file_order:
        top_closure_files = tuple(
            path for path in source_order if path in closure_sources
        )
    else:
        top_closure_files = tuple(
            path
            for path in context.compile_order(closure)
            if path in closure_sources
        )
    return SourceSetDiscovery(
        included_files=tuple(sorted(included_files)),
        top_closure_files=top_closure_files,
        compile_order=tuple(context.compile_order(closure)),
    )
