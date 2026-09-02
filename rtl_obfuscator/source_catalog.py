"""Strict semantic module catalog and source-owner registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import pyslang

from .performance_probe import (
    COMPILE_CATALOG_INVENTORY,
    COMPILE_OWNER_REGISTRY,
    COMPILE_TOP_CLOSURE,
    StageObserver,
    _observe,
)
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
class ReadonlyDuplicate:
    """A duplicate module retained only as readonly library inventory."""

    name: str
    declarations: tuple[SourceRange, ...]


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
    readonly_vendor_files: tuple[str, ...] = field(default=(), repr=False, compare=False)
    readonly_include_files: tuple[str, ...] = field(default=(), repr=False, compare=False)
    readonly_duplicate_inventory: tuple[ReadonlyDuplicate, ...] = field(
        default=(), repr=False, compare=False
    )

    @property
    def readonly_duplicates(self) -> tuple[ReadonlyDuplicate, ...]:
        """Compatibility alias for the live readonly duplicate inventory."""

        return self.readonly_duplicate_inventory

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
    vendor_compatibility_errors: tuple[Any, ...]
    vendor_compatibility_files: tuple[str, ...]


@dataclass(frozen=True)
class _DefinitionRecord:
    definition: Any
    declaration: SourceRange


@dataclass(frozen=True)
class _PhysicalModuleDeclaration:
    name: str
    declaration: SourceRange


def _read_physical_token(
    source_set: SourceSet, file: str, start: int, length: int
) -> bytes:
    """Read only one source token while validating its physical bounds."""

    path = source_set.source_root / file
    try:
        size = path.stat().st_size
    except OSError as error:
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "cannot stat module declaration source",
            file=file,
            start=start,
        ) from error
    end = start + length
    if start < 0 or length <= 0 or end > size:
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "module declaration range is outside source bytes",
            file=file,
            start=start,
        )
    try:
        with path.open("rb") as source:
            source.seek(start)
            data = source.read(length)
    except OSError as error:
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "cannot read module declaration source",
            file=file,
            start=start,
        ) from error
    if len(data) != length:
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "module declaration range is outside source bytes",
            file=file,
            start=start,
        )
    return data


def _compile_view(
    source_set: SourceSet,
    *,
    top: str | None,
    stage_observer: StageObserver | None = None,
) -> _CompiledView:
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
            stage_observer=stage_observer,
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
        view.vendor_compatibility_errors,
        view.vendor_compatibility_files,
    )


def _diagnostic_counts(view: _CompiledView) -> tuple[int, int]:
    return len(view.parse_errors), len(view.semantic_errors)


_SOURCE_BACKED_BUFFER_KINDS = frozenset(
    {
        pyslang.BufferKind.DesignFile,
        pyslang.BufferKind.LibraryFile,
        pyslang.BufferKind.IncludeFile,
    }
)


def _known_physical_files(source_set: SourceSet) -> frozenset[str]:
    """Return the physical files this SourceSet makes available to PySlang."""

    return frozenset(
        (*source_set.compile_order, *source_set.included_files)
    )


def _relative_file(source_set: SourceSet, manager: Any, buffer: Any) -> str:
    try:
        buffer_kind = manager.getBufferKind(buffer)
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "semantic location has no physical buffer kind",
        ) from error
    if buffer_kind not in _SOURCE_BACKED_BUFFER_KINDS:
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "semantic location is not a source-backed physical buffer",
        )
    try:
        root = Path(source_set.source_root).resolve()
        absolute = Path(manager.getFullPath(buffer)).resolve()
        relative = absolute.relative_to(root).as_posix()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID", "declaration is outside the SourceSet root"
        ) from error
    if relative not in _known_physical_files(source_set):
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "semantic location is not a SourceSet physical file",
            file=relative,
        )
    if not absolute.is_file():
        raise SourceCatalogError(
            "CATALOG_RANGE_INVALID",
            "semantic location is not a regular physical file",
            file=relative,
        )
    return relative


def _has_source_backed_semantic_location(
    manager: Any, node: Any, location: Any
) -> bool:
    """Distinguish source-less semantic wrappers from physical declarations."""

    if getattr(node, "syntax", None) is None or location is None:
        return False
    try:
        return manager.getBufferKind(location.buffer) in _SOURCE_BACKED_BUFFER_KINDS
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        raise SourceCatalogError(
            "CATALOG_OWNER_INVALID",
            "semantic owner has no physical buffer kind",
        ) from error


def _definition_range(
    source_set: SourceSet, manager: Any, definition: Any
) -> SourceRange:
    name = str(definition.name)
    start = int(definition.location.offset)
    file = _relative_file(source_set, manager, definition.location.buffer)
    expected = name.encode("utf-8")
    end = start + len(expected)
    source = _read_physical_token(source_set, file, start, len(expected))
    if source != expected:
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


def _physical_module_declarations(
    source_set: SourceSet, view: _CompiledView
) -> tuple[_PhysicalModuleDeclaration, ...]:
    """Inventory every module declaration in the supplied syntax tree.

    An explicit-top semantic root may omit unelaborated definitions.  The CST
    remains the physical source of truth for the module inventory, while the
    semantic root is consulted separately for top reachability.
    """

    source_files = frozenset(
        path for path in source_set.compile_order if is_source_file(path)
    )
    declarations: list[_PhysicalModuleDeclaration] = []

    def collect(node: Any) -> None:
        if getattr(node, "kind", None) != pyslang.syntax.SyntaxKind.ModuleDeclaration:
            return
        token = getattr(getattr(node, "header", None), "name", None)
        if token is None or not token.rawText:
            return
        file = _relative_file(source_set, view.source_manager, token.location.buffer)
        if file not in source_files:
            return
        name = str(token.rawText)
        start = int(token.location.offset)
        expected = name.encode("utf-8")
        end = start + len(expected)
        source = _read_physical_token(source_set, file, start, len(expected))
        if source != expected:
            raise SourceCatalogError(
                "CATALOG_RANGE_INVALID",
                "module declaration range does not match source bytes",
                file=file,
                start=start,
            )
        declarations.append(
            _PhysicalModuleDeclaration(
                name=name,
                declaration=SourceRange(file=file, start=start, end=end),
            )
        )

    view.syntax_tree.root.visit(collect)
    return tuple(
        sorted(
            declarations,
            key=lambda item: (
                item.declaration.file,
                item.declaration.start,
                item.declaration.end,
                item.name,
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
    expected = value.encode("utf-8")
    end = start + len(expected)
    source = _read_physical_token(source_set, file, start, len(expected))
    if source != expected:
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
    module_owner_by_range = {
        (
            module.declaration.file,
            module.declaration.start,
            module.declaration.end,
        ): module.owner_id
        for module in modules
    }

    def collect(node: Any) -> None:
        node_type = type(node).__name__
        if node_type == "InstanceBodySymbol":
            definition = getattr(node, "definition", None)
            syntax = getattr(node, "syntax", None)
            if definition is None or syntax is None:
                return
            if not _has_source_backed_semantic_location(
                view.source_manager, node, getattr(definition, "location", None)
            ):
                return
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
            if not _has_source_backed_semantic_location(
                view.source_manager, node, getattr(node, "location", None)
            ):
                return
            declaration = _semantic_name_range(source_set, view.source_manager, node)
            owners.add(f"type:{declaration.file}:{declaration.start}:{declaration.end}")

    view.root.visit(collect)
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
        expected = name.encode("utf-8")
        end = start + len(expected)
        source = _read_physical_token(source_set, file, start, len(expected))
        if source != expected:
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


def _file_is_within_rewrite_roots(file: str, roots: tuple[str, ...]) -> bool:
    path = PurePosixPath(file)
    for root in roots:
        if root == ".":
            return True
        try:
            path.relative_to(PurePosixPath(root))
            return True
        except ValueError:
            continue
    return False


def _duplicate_declarations(
    declarations: tuple[_PhysicalModuleDeclaration, ...],
) -> tuple[tuple[str, tuple[SourceRange, ...]], ...]:
    grouped: dict[str, list[SourceRange]] = {}
    for item in declarations:
        grouped.setdefault(item.name, []).append(item.declaration)
    return tuple(
        (name, tuple(sorted(ranges, key=lambda item: (item.file, item.start, item.end))))
        for name, ranges in sorted(grouped.items())
        if len(ranges) > 1
    )


def _duplicate_error(name: str, declaration: SourceRange, reason: str) -> SourceCatalogError:
    return SourceCatalogError(
        "CATALOG_DUPLICATE_MODULE",
        f"module has multiple physical declarations: {name} ({reason})",
        file=declaration.file,
        start=declaration.start,
    )


def _readonly_duplicate_inventory(
    source_set: SourceSet,
    declarations: tuple[_PhysicalModuleDeclaration, ...],
    *,
    top_closure_names: frozenset[str],
) -> tuple[ReadonlyDuplicate, ...]:
    """Validate duplicate providers and retain only allowed readonly entries."""

    if source_set.origin != "filelist" or not source_set.rewrite_roots:
        _check_duplicate_syntax_modules_from_inventory(declarations)
        return ()

    entries_by_value: dict[str, list[Any]] = {}
    for entry in getattr(source_set, "filelist_entries", ()):
        entries_by_value.setdefault(entry.value, []).append(entry)

    inventory: list[ReadonlyDuplicate] = []
    for name, ranges in _duplicate_declarations(declarations):
        first = ranges[0]
        if name == source_set.top:
            raise _duplicate_error(name, first, "selected top is duplicated")
        if any(
            _file_is_within_rewrite_roots(item.file, source_set.rewrite_roots)
            for item in ranges
        ):
            raise _duplicate_error(name, first, "declaration is inside rewrite root")
        if name in top_closure_names:
            raise _duplicate_error(name, first, "module is reachable from selected top")
        if len({item.file for item in ranges}) != len(ranges):
            raise _duplicate_error(name, first, "same physical file declares module twice")

        providers: list[Any] = []
        for declaration in ranges:
            candidates = entries_by_value.get(declaration.file, [])
            if len(candidates) != 1:
                raise _duplicate_error(
                    name,
                    declaration,
                    "module declaration has no unique filelist provenance",
                )
            entry = candidates[0]
            if entry.kind not in {"source", "library_source"}:
                raise _duplicate_error(
                    name,
                    declaration,
                    "module declaration provenance is not a source entry",
                )
            providers.append(entry)

        source_count = sum(entry.kind == "source" for entry in providers)
        if source_count > 1 or (
            source_count == 0
            and not all(entry.kind == "library_source" for entry in providers)
        ):
            raise _duplicate_error(
                name,
                first,
                "duplicate providers are not readonly library entries",
            )
        if source_count == 1 and not all(
            entry.kind in {"source", "library_source"} for entry in providers
        ):
            raise _duplicate_error(name, first, "duplicate provider kind is invalid")
        inventory.append(ReadonlyDuplicate(name=name, declarations=ranges))

    return tuple(sorted(inventory, key=lambda item: (item.name, item.declarations)))


def _check_duplicate_syntax_modules_from_inventory(
    declarations: tuple[_PhysicalModuleDeclaration, ...],
) -> None:
    for name, ranges in _duplicate_declarations(declarations):
        first = ranges[0]
        raise _duplicate_error(name, first, "duplicate providers are not allowed")


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

    def collect(node: Any) -> None:
        if not getattr(node, "isModule", False):
            return
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

    tops[0].visit(collect)
    return tuple(reachable.values())


def _module_owners_from_inventory(
    declarations: tuple[_PhysicalModuleDeclaration, ...],
    *,
    reachable_ranges: set[tuple[str, int, int]],
    selected_range: tuple[str, int, int] | None,
) -> tuple[ModuleOwner, ...]:
    modules: list[ModuleOwner] = []
    for item in declarations:
        declaration = item.declaration
        key = (declaration.file, declaration.start, declaration.end)
        modules.append(
            ModuleOwner(
                owner_id=f"module:{declaration.file}:{declaration.start}:{declaration.end}",
                name=item.name,
                declaration=declaration,
                in_top_closure=key in reachable_ranges,
                is_selected_top=key == selected_range,
            )
        )
    return tuple(modules)


def _build_single_explicit_top_catalog(
    source_set: SourceSet,
    *,
    stage_observer: StageObserver | None = None,
) -> SourceCatalog:
    """Build a rewrite-root filelist catalog from one explicit-top view."""

    assert source_set.top is not None
    view = _compile_view(
        source_set, top=source_set.top, stage_observer=stage_observer
    )
    parse_errors, _ = _diagnostic_counts(view)
    _observe(stage_observer, COMPILE_CATALOG_INVENTORY, "begin")
    declarations = _physical_module_declarations(source_set, view)
    # Apply all duplicate checks that do not require top reachability first.
    _readonly_duplicate_inventory(
        source_set,
        declarations,
        top_closure_names=frozenset(),
    )
    _observe(stage_observer, COMPILE_CATALOG_INVENTORY, "end")

    # A duplicate library module that is instantiated by the selected top may
    # make PySlang report a parse/semantic diagnostic before exposing the
    # reachable definition.  Walk the root before surfacing that diagnostic so
    # the finite duplicate policy remains fail-closed for reachable providers.
    _observe(stage_observer, COMPILE_TOP_CLOSURE, "begin")
    try:
        reachable = _walk_reachable_modules(view.root, source_set.top)
    except SourceCatalogError:
        if parse_errors:
            raise SourceCatalogError(
                "CATALOG_PARSE_FAILED", "explicit-top view contains parse errors"
            )
        raise
    reachable_ranges: set[tuple[str, int, int]] = set()
    reachable_names = frozenset(str(definition.name) for definition in reachable)
    for definition in reachable:
        declaration = _definition_range(source_set, view.source_manager, definition)
        key = (declaration.file, declaration.start, declaration.end)
        if not any(item.declaration == declaration for item in declarations):
            raise SourceCatalogError(
                "CATALOG_TOP_MISMATCH",
                "top view definition cannot map to physical module inventory",
                file=declaration.file,
                start=declaration.start,
            )
        reachable_ranges.add(key)

    tops = [
        instance
        for instance in view.root.topInstances
        if instance.name == source_set.top
        and getattr(instance, "isModule", False)
    ]
    if len(tops) != 1:
        raise SourceCatalogError(
            "CATALOG_TOP_MISMATCH", "selected top is not unique"
        )
    selected_declaration = _definition_range(
        source_set, view.source_manager, tops[0].definition
    )
    selected_range = (
        selected_declaration.file,
        selected_declaration.start,
        selected_declaration.end,
    )
    if not any(item.declaration == selected_declaration for item in declarations):
        raise SourceCatalogError(
            "CATALOG_TOP_MISMATCH",
            "selected top cannot map to physical module inventory",
            file=selected_declaration.file,
            start=selected_declaration.start,
        )
    _observe(stage_observer, COMPILE_TOP_CLOSURE, "end")

    _observe(stage_observer, COMPILE_OWNER_REGISTRY, "begin")
    readonly_duplicates = _readonly_duplicate_inventory(
        source_set,
        declarations,
        top_closure_names=reachable_names,
    )
    if parse_errors:
        raise SourceCatalogError(
            "CATALOG_PARSE_FAILED", "explicit-top view contains parse errors"
        )
    _, semantic_errors = _diagnostic_counts(view)
    if semantic_errors:
        raise SourceCatalogError(
            "CATALOG_SEMANTIC_FAILED", "explicit-top view contains semantic errors"
        )

    modules = _module_owners_from_inventory(
        declarations,
        reachable_ranges=reachable_ranges,
        selected_range=selected_range,
    )
    top_closure_owner_ids = tuple(
        module.owner_id for module in modules if module.in_top_closure
    )
    result = SourceCatalog(
        schema_version=1,
        source_set=source_set,
        modules=modules,
        top_closure_owner_ids=top_closure_owner_ids,
        catalog_compilation=view.compilation,
        catalog_root=view.root,
        catalog_source_manager=view.source_manager,
        top_compilation=view.compilation,
        top_root=view.root,
        top_source_manager=view.source_manager,
        semantic_owner_ids=_semantic_owner_ids(source_set, view, modules),
        readonly_vendor_files=tuple(view.vendor_compatibility_files),
        readonly_include_files=tuple(source_set.included_files),
        readonly_duplicate_inventory=readonly_duplicates,
    )
    _observe(stage_observer, COMPILE_OWNER_REGISTRY, "end")
    return result


def build_source_catalog(
    source_set: SourceSet,
    *,
    stage_observer: StageObserver | None = None,
) -> SourceCatalog:
    """Build the catalog view and optional selected-top overlay."""

    if (
        source_set.origin == "filelist"
        and source_set.top
        and source_set.rewrite_roots
    ):
        return _build_single_explicit_top_catalog(
            source_set, stage_observer=stage_observer
        )

    catalog_view = _compile_view(
        source_set, top=None, stage_observer=stage_observer
    )
    catalog_parse_errors, _ = _diagnostic_counts(catalog_view)
    if catalog_parse_errors:
        raise SourceCatalogError(
            "CATALOG_PARSE_FAILED", "catalog view contains parse errors"
        )
    _observe(stage_observer, COMPILE_CATALOG_INVENTORY, "begin")
    catalog_records = _module_definitions_for(source_set, catalog_view)
    _check_duplicate_syntax_modules(source_set, catalog_view)
    _observe(stage_observer, COMPILE_CATALOG_INVENTORY, "end")
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
        top_view = _compile_view(
            source_set, top=source_set.top, stage_observer=stage_observer
        )
        top_parse_errors, _ = _diagnostic_counts(top_view)
        if top_parse_errors:
            raise SourceCatalogError(
                "CATALOG_PARSE_FAILED", "top overlay contains parse errors"
            )
        _observe(stage_observer, COMPILE_TOP_CLOSURE, "begin")
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
        _observe(stage_observer, COMPILE_TOP_CLOSURE, "end")

    _observe(stage_observer, COMPILE_OWNER_REGISTRY, "begin")
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
    readonly_vendor_files = list(catalog_view.vendor_compatibility_files)
    if top_view is not None:
        for file in top_view.vendor_compatibility_files:
            if file not in readonly_vendor_files:
                readonly_vendor_files.append(file)
    result = SourceCatalog(
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
        readonly_vendor_files=tuple(readonly_vendor_files),
        readonly_include_files=tuple(source_set.included_files),
        readonly_duplicate_inventory=(),
    )
    _observe(stage_observer, COMPILE_OWNER_REGISTRY, "end")
    return result
