"""Strict semantic module catalog and source-owner registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyslang

from .project_discovery import compile_pyslang_source_set
from .source_set import SourceSet
from .rtl_files import is_source_file


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
    semantic_owner_ids: tuple[str, ...] = field(default=(), repr=False, compare=False)

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
    parse_errors: tuple[Any, ...]
    semantic_errors: tuple[Any, ...]
    nonblocking_errors: tuple[Any, ...]


@dataclass(frozen=True)
class _DefinitionRecord:
    definition: Any
    declaration: SourceRange


def _compile_view(source_set: SourceSet, *, top: str | None) -> _CompiledView:
    if not any(is_source_file(path) for path in source_set.compile_order):
        raise SourceCatalogError(
            "CATALOG_EMPTY_SOURCE_SET", "SourceSet has no .sv or .v source unit"
        )

    try:
        view = compile_pyslang_source_set(
            root=source_set.source_root,
            compilation_files=source_set.compile_order,
            include_files=source_set.included_files,
            include_dirs=source_set.include_dirs,
            defines=dict(source_set.defines),
            top=top,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise SourceCatalogError("CATALOG_PARSE_FAILED", str(error)) from error
    return _CompiledView(
        view.compilation,
        view.root,
        view.source_manager,
        view.syntax_tree,
        view.parse_errors,
        view.semantic_errors,
        view.nonblocking_errors,
    )


def _diagnostic_counts(view: _CompiledView) -> tuple[int, int]:
    return len(view.parse_errors), len(view.semantic_errors)


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


def _semantic_name_range(
    source_set: SourceSet,
    manager: Any,
    node: Any,
    *,
    name: str | None = None,
) -> SourceRange:
    value = str(name if name is not None else getattr(node, "name", ""))
    if not value:
        raise SourceCatalogError(
            "CATALOG_OWNER_INVALID", "semantic owner has no source name"
        )
    location = getattr(node, "location", None)
    if location is None:
        raise SourceCatalogError(
            "CATALOG_OWNER_INVALID", "semantic owner has no source location"
        )
    file = _relative_file(source_set, manager, location.buffer)
    start = int(location.offset)
    end = start + len(value.encode("utf-8"))
    source = (source_set.source_root / file).read_bytes()
    if start < 0 or start >= end or end > len(source):
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "semantic owner range is outside source bytes",
            file=file,
            start=start,
        )
    if source[start:end] != value.encode("utf-8"):
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "semantic owner range does not match source bytes",
            file=file,
            start=start,
        )
    return SourceRange(file=file, start=start, end=end)


def _semantic_owner_ids(
    source_set: SourceSet,
    view: _CompiledView,
    modules: tuple[ModuleOwner, ...],
) -> tuple[str, ...]:
    """Return the registry of semantic owners consumed by RenameIndex.

    The registry is derived from the already compiled PySlang tree.  It is
    intentionally not part of the portable catalog report; it is an internal
    identity boundary used to validate graph owners before mapping.
    """

    owners: set[str] = {"$unit"}
    owners.update(module.owner_id for module in modules)
    nodes: list[Any] = []
    view.root.visit(nodes.append)
    module_owner_by_range = {
        (
            module.declaration.file,
            module.declaration.start,
            module.declaration.end,
        ): module.owner_id
        for module in modules
    }
    for node in nodes:
        node_type = type(node).__name__
        if node_type == "InstanceBodySymbol":
            definition = getattr(node, "definition", None)
            syntax = getattr(node, "syntax", None)
            if definition is None or syntax is None:
                continue
            declaration = _definition_range(source_set, view.source_manager, definition)
            syntax_kind = str(getattr(syntax, "kind", ""))
            if "ModuleDeclaration" in syntax_kind:
                owner_id = module_owner_by_range.get(
                    (declaration.file, declaration.start, declaration.end)
                )
                if owner_id is not None:
                    owners.add(owner_id)
            elif "InterfaceDeclaration" in syntax_kind:
                owners.add(
                    f"interface:{declaration.file}:{declaration.start}:{declaration.end}"
                )
        elif node_type == "TypeAliasType":
            declaration = _semantic_name_range(source_set, view.source_manager, node)
            owners.add(f"type:{declaration.file}:{declaration.start}:{declaration.end}")
        elif node_type == "SubroutineSymbol":
            declaration = _semantic_name_range(source_set, view.source_manager, node)
            owners.add(
                f"subroutine:{declaration.file}:{declaration.start}:{declaration.end}"
            )
        elif node_type == "GenerateBlockArraySymbol":
            syntax = getattr(node, "syntax", None)
            source_range = getattr(syntax, "sourceRange", None)
            start = getattr(source_range, "start", None)
            end = getattr(source_range, "end", None)
            if start is None or end is None:
                raise SourceCatalogError(
                    "CATALOG_OWNER_INVALID",
                    "generate block owner has no semantic source range",
                )
            file = _relative_file(source_set, view.source_manager, start.buffer)
            end_file = _relative_file(source_set, view.source_manager, end.buffer)
            end_offset = int(end.offset)
            if file != end_file or int(start.offset) >= end_offset:
                raise SourceCatalogError(
                    "CATALOG_RANGE_INVALID",
                    "generate block source range is invalid",
                    file=file,
                    start=int(start.offset),
                )
            owners.add(
                f"generate:{file}:{int(start.offset)}:{end_offset}"
            )
    return tuple(sorted(owners))


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
        semantic_owner_ids=_semantic_owner_ids(source_set, catalog_view, tuple(modules)),
    )
