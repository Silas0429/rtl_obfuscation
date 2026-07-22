"""Strict semantic module catalog and source-owner registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyslang

from .source_set import SourceSet


@dataclass(frozen=True)
class SourceRange:
    file: str
    start: int
    end: int


@dataclass(frozen=True)
class ModuleOwner:
    owner_id: str
    name: str
    declaration: SourceRange
    in_top_closure: bool
    is_selected_top: bool


@dataclass(frozen=True)
class SourceCatalog:
    schema_version: int
    source_set: SourceSet
    modules: tuple[ModuleOwner, ...]
    top_closure_owner_ids: tuple[str, ...]
    catalog_compilation: object = field(repr=False, compare=False)
    catalog_root: object = field(repr=False, compare=False)
    catalog_source_manager: object = field(repr=False, compare=False)
    top_compilation: object | None = field(repr=False, compare=False)
    top_root: object | None = field(repr=False, compare=False)
    top_source_manager: object | None = field(repr=False, compare=False)

    def to_report(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_set": self.source_set.to_report(),
            "compile": {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": (
                    None
                    if self.top_compilation is None
                    else {"parse_errors": 0, "semantic_errors": 0}
                ),
            },
            "modules": [
                {
                    "owner_id": module.owner_id,
                    "name": module.name,
                    "declaration": {
                        "file": module.declaration.file,
                        "start": module.declaration.start,
                        "end": module.declaration.end,
                    },
                    "in_top_closure": module.in_top_closure,
                    "is_selected_top": module.is_selected_top,
                }
                for module in self.modules
            ],
            "top_closure_owner_ids": list(self.top_closure_owner_ids),
        }


class SourceCatalogError(ValueError):
    """Stable failure raised while building a semantic SourceCatalog."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        file: str | None = None,
        start: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.file = file
        self.start = start
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class _CompiledView:
    compilation: Any
    root: Any
    source_manager: Any
    syntax_tree: Any


@dataclass(frozen=True)
class _DefinitionRecord:
    definition: Any
    declaration: SourceRange


def _compile_view(source_set: SourceSet, *, top: str | None) -> _CompiledView:
    source_files = tuple(
        path for path in source_set.compile_order if path.endswith(".sv")
    )
    if not source_files:
        raise SourceCatalogError(
            "CATALOG_EMPTY_SOURCE_SET", "SourceSet has no .sv source unit"
        )

    manager = pyslang.SourceManager()
    directories: list[str] = []
    for directory in source_set.include_dirs:
        if directory not in directories:
            directories.append(directory)
    for relative in (*source_files, *source_set.included_files):
        parent = str(Path(relative).parent.as_posix())
        if parent not in directories:
            directories.append(parent)
    for directory in directories:
        manager.addUserDirectories(str(source_set.source_root / directory))

    bag = pyslang.Bag()
    preprocessor = pyslang.parsing.PreprocessorOptions()
    preprocessor.predefines = [
        f"{name}={value}" for name, value in source_set.defines
    ]
    bag.preprocessorOptions = preprocessor
    options = pyslang.ast.CompilationOptions()
    if top is not None:
        options.topModules = {top}
    bag.compilationOptions = options

    try:
        syntax_tree = pyslang.syntax.SyntaxTree.fromFiles(
            [str(source_set.source_root / path) for path in source_files],
            manager,
            bag,
        )
        compilation = pyslang.ast.Compilation(bag)
        compilation.addSyntaxTree(syntax_tree)
        root = compilation.getRoot()
    except (OSError, RuntimeError, ValueError) as error:
        raise SourceCatalogError("CATALOG_PARSE_FAILED", str(error)) from error
    return _CompiledView(compilation, root, manager, syntax_tree)


def _diagnostic_counts(view: _CompiledView) -> tuple[int, int]:
    parse_diagnostics = [
        diagnostic
        for diagnostic in view.syntax_tree.diagnostics
        if diagnostic.isError()
    ]
    parse_keys = {
        (str(diagnostic.code), diagnostic.location.buffer, diagnostic.location.offset)
        for diagnostic in parse_diagnostics
    }
    diagnostics = [
        diagnostic
        for diagnostic in view.compilation.getAllDiagnostics()
        if diagnostic.isError()
    ]
    semantic_diagnostics = [
        diagnostic
        for diagnostic in diagnostics
        if (
            str(diagnostic.code),
            diagnostic.location.buffer,
            diagnostic.location.offset,
        )
        not in parse_keys
    ]
    return len(parse_diagnostics), len(semantic_diagnostics)


def _relative_file(source_set: SourceSet, manager: Any, buffer: Any) -> str:
    try:
        absolute = Path(manager.getFullPath(buffer)).resolve()
        return absolute.relative_to(source_set.source_root).as_posix()
    except (OSError, ValueError, RuntimeError) as error:
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID", "declaration is outside the SourceSet root"
        ) from error


def _definition_range(
    source_set: SourceSet, manager: Any, definition: Any
) -> SourceRange:
    name = str(definition.name)
    start = int(definition.location.offset)
    file = _relative_file(source_set, manager, definition.location.buffer)
    source = (source_set.source_root / file).read_bytes()
    end = start + len(name.encode("utf-8"))
    if start < 0 or start >= end or end > len(source):
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "module declaration range is outside source bytes",
            file=file,
            start=start,
        )
    if source[start:end] != name.encode("utf-8"):
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "module declaration range does not match source bytes",
            file=file,
            start=start,
        )
    return SourceRange(file=file, start=start, end=end)


def _module_definitions_for(
    source_set: SourceSet, view: _CompiledView
) -> tuple[_DefinitionRecord, ...]:
    nodes: list[Any] = []
    view.root.visit(nodes.append)
    records: dict[tuple[str, int, int], _DefinitionRecord] = {}
    for node in nodes:
        definition = getattr(node, "definition", None)
        if definition is None:
            continue
        if getattr(definition, "definitionKind", None) != pyslang.ast.DefinitionKind.Module:
            continue
        declaration = _definition_range(source_set, view.source_manager, definition)
        key = (declaration.file, declaration.start, declaration.end)
        records[key] = _DefinitionRecord(definition, declaration)
    return tuple(
        sorted(
            records.values(),
            key=lambda item: (
                item.declaration.file,
                item.declaration.start,
                item.declaration.end,
                str(item.definition.name),
            ),
        )
    )


def _check_duplicate_syntax_modules(
    source_set: SourceSet, view: _CompiledView
) -> None:
    nodes: list[Any] = []
    view.syntax_tree.root.visit(nodes.append)
    declarations: dict[str, list[SourceRange]] = {}
    for node in nodes:
        if getattr(node, "kind", None) != pyslang.syntax.SyntaxKind.ModuleDeclaration:
            continue
        token = node.header.name
        if not token.rawText:
            continue
        file = _relative_file(source_set, view.source_manager, token.location.buffer)
        name = token.rawText
        start = int(token.location.offset)
        end = start + len(name.encode("utf-8"))
        source = (source_set.source_root / file).read_bytes()
        if start < 0 or start >= end or end > len(source):
            raise SourceCatalogError(
                "CATALOG_RANGE_INVALID",
                "module declaration range is outside source bytes",
                file=file,
                start=start,
            )
        if source[start:end] != name.encode("utf-8"):
            raise SourceCatalogError(
                "CATALOG_RANGE_INVALID",
                "module declaration range does not match source bytes",
                file=file,
                start=start,
            )
        declarations.setdefault(name, []).append(
            SourceRange(file=file, start=start, end=end)
        )
    for name, ranges in sorted(declarations.items()):
        if len(ranges) > 1:
            first = sorted(ranges, key=lambda item: (item.file, item.start, item.end))[0]
            raise SourceCatalogError(
                "CATALOG_DUPLICATE_MODULE",
                f"module has multiple physical declarations: {name}",
                file=first.file,
                start=first.start,
            )


def _walk_reachable_modules(root: Any, top: str) -> tuple[Any, ...]:
    tops = [
        instance
        for instance in root.topInstances
        if instance.name == top and getattr(instance, "isModule", False)
    ]
    if len(tops) != 1:
        raise SourceCatalogError(
            "CATALOG_TOP_MISMATCH",
            "selected top does not resolve to exactly one module instance",
        )

    reachable: dict[tuple[Any, int, str], Any] = {}
    semantic_nodes: list[Any] = []
    tops[0].visit(semantic_nodes.append)
    for node in semantic_nodes:
        if not getattr(node, "isModule", False):
            continue
        definition = getattr(node, "definition", None)
        if definition is None:
            raise SourceCatalogError(
                "CATALOG_TOP_MISMATCH",
                "selected module instance has no definition",
            )
        key = (
            definition.location.buffer,
            int(definition.location.offset),
            str(definition.name),
        )
        reachable[key] = definition
    return tuple(reachable.values())


def build_source_catalog(source_set: SourceSet) -> SourceCatalog:
    """Build the catalog view and optional selected-top overlay."""

    catalog_view = _compile_view(source_set, top=None)
    catalog_parse_errors, _ = _diagnostic_counts(catalog_view)
    if catalog_parse_errors:
        raise SourceCatalogError(
            "CATALOG_PARSE_FAILED", "catalog view contains parse errors"
        )
    catalog_records = _module_definitions_for(source_set, catalog_view)
    _check_duplicate_syntax_modules(source_set, catalog_view)
    _, catalog_semantic_errors = _diagnostic_counts(catalog_view)
    if catalog_semantic_errors:
        raise SourceCatalogError(
            "CATALOG_SEMANTIC_FAILED", "catalog view contains semantic errors"
        )

    owner_by_range: dict[tuple[str, int, int], ModuleOwner] = {}
    for record in catalog_records:
        declaration = record.declaration
        key = (declaration.file, declaration.start, declaration.end)
        owner_by_range[key] = ModuleOwner(
            owner_id=f"module:{declaration.file}:{declaration.start}:{declaration.end}",
            name=str(record.definition.name),
            declaration=declaration,
            in_top_closure=False,
            is_selected_top=False,
        )

    top_view: _CompiledView | None = None
    reachable_ranges: set[tuple[str, int, int]] = set()
    selected_range: tuple[str, int, int] | None = None
    if source_set.top is not None:
        top_view = _compile_view(source_set, top=source_set.top)
        top_parse_errors, _ = _diagnostic_counts(top_view)
        if top_parse_errors:
            raise SourceCatalogError(
                "CATALOG_PARSE_FAILED", "top overlay contains parse errors"
            )
        reachable = _walk_reachable_modules(top_view.root, source_set.top)
        _, top_semantic_errors = _diagnostic_counts(top_view)
        if top_semantic_errors:
            raise SourceCatalogError(
                "CATALOG_SEMANTIC_FAILED", "top overlay contains semantic errors"
            )
        for definition in reachable:
            declaration = _definition_range(
                source_set, top_view.source_manager, definition
            )
            key = (declaration.file, declaration.start, declaration.end)
            if key not in owner_by_range:
                raise SourceCatalogError(
                    "CATALOG_TOP_MISMATCH",
                    "top overlay definition cannot map to catalog owner",
                    file=declaration.file,
                    start=declaration.start,
                )
            reachable_ranges.add(key)
        tops = [
            instance
            for instance in top_view.root.topInstances
            if instance.name == source_set.top
            and getattr(instance, "isModule", False)
        ]
        if len(tops) != 1:
            raise SourceCatalogError(
                "CATALOG_TOP_MISMATCH",
                "selected top is not unique",
            )
        selected_definition = tops[0].definition
        selected_declaration = _definition_range(
            source_set, top_view.source_manager, selected_definition
        )
        selected_range = (
            selected_declaration.file,
            selected_declaration.start,
            selected_declaration.end,
        )
        if selected_range not in owner_by_range:
            raise SourceCatalogError(
                "CATALOG_TOP_MISMATCH",
                "selected top cannot map to catalog owner",
                file=selected_declaration.file,
                start=selected_declaration.start,
            )

    modules: list[ModuleOwner] = []
    for owner in sorted(
        owner_by_range.values(),
        key=lambda item: (
            item.declaration.file,
            item.declaration.start,
            item.declaration.end,
            item.name,
        ),
    ):
        key = (
            owner.declaration.file,
            owner.declaration.start,
            owner.declaration.end,
        )
        modules.append(
            ModuleOwner(
                owner_id=owner.owner_id,
                name=owner.name,
                declaration=owner.declaration,
                in_top_closure=key in reachable_ranges,
                is_selected_top=key == selected_range,
            )
        )

    top_closure_owner_ids = tuple(
        module.owner_id for module in modules if module.in_top_closure
    )
    return SourceCatalog(
        schema_version=1,
        source_set=source_set,
        modules=tuple(modules),
        top_closure_owner_ids=top_closure_owner_ids,
        catalog_compilation=catalog_view.compilation,
        catalog_root=catalog_view.root,
        catalog_source_manager=catalog_view.source_manager,
        top_compilation=None if top_view is None else top_view.compilation,
        top_root=None if top_view is None else top_view.root,
        top_source_manager=None if top_view is None else top_view.source_manager,
    )
