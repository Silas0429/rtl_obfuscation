"""Signals-only SymbolGraph built from one T040 SourceCatalog view."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyslang

from .source_catalog import ModuleOwner, SourceCatalog, SourceRange


@dataclass(frozen=True)
class SymbolOccurrence:
    source_range: SourceRange
    provenance: str


@dataclass(frozen=True)
class SourceSymbol:
    symbol_id: str
    category: str
    name: str
    declaration: SourceRange
    owner_module: str
    semantic_owner: str
    occurrences: tuple[SymbolOccurrence, ...]
    impact: str
    abi: str
    support: str
    reason: str | None


@dataclass(frozen=True)
class SymbolGraph:
    schema_version: int
    source_catalog: SourceCatalog = field(repr=False, compare=False)
    symbols: tuple[SourceSymbol, ...]

    def to_report(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_catalog": self.source_catalog.to_report(),
            "categories": ["signals"],
            "symbols": [
                {
                    "symbol_id": symbol.symbol_id,
                    "category": symbol.category,
                    "name": symbol.name,
                    "declaration": _range_report(symbol.declaration),
                    "owner_module": symbol.owner_module,
                    "semantic_owner": symbol.semantic_owner,
                    "occurrences": [
                        {
                            "source_range": _range_report(occurrence.source_range),
                            "provenance": occurrence.provenance,
                        }
                        for occurrence in symbol.occurrences
                    ],
                    "impact": symbol.impact,
                    "abi": symbol.abi,
                    "support": symbol.support,
                    "reason": symbol.reason,
                }
                for symbol in self.symbols
            ],
            "range_audit": {
                "symbols": len(self.symbols),
                "declarations": len(self.symbols),
                "occurrences": sum(len(symbol.occurrences) for symbol in self.symbols),
                "total_ranges": sum(
                    1 + len(symbol.occurrences) for symbol in self.symbols
                ),
            },
        }


class SymbolGraphError(ValueError):
    """Stable fail-closed error for signals-only SymbolGraph construction."""

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


def _range_report(source_range: SourceRange) -> dict[str, object]:
    return {
        "file": source_range.file,
        "start": source_range.start,
        "end": source_range.end,
    }


def _physical_files(source_catalog: SourceCatalog) -> set[str]:
    source_set = source_catalog.source_set
    return set(source_set.ordered_source_files) | set(source_set.included_files)


def _range_from_location(
    source_catalog: SourceCatalog,
    location: Any,
    name: str,
    *,
    code: str = "SYMBOL_GRAPH_RANGE_INVALID",
) -> SourceRange:
    source_set = source_catalog.source_set
    try:
        absolute = Path(
            source_catalog.catalog_source_manager.getFullPath(location.buffer)
        ).resolve()
        file = absolute.relative_to(source_set.source_root).as_posix()
    except (OSError, ValueError, RuntimeError) as error:
        raise SymbolGraphError(
            code, "semantic location is outside the SourceSet root"
        ) from error
    if file not in _physical_files(source_catalog):
        raise SymbolGraphError(
            code,
            "semantic location is not in a SourceSet physical file",
            file=file,
            start=int(location.offset),
        )
    start = int(location.offset)
    end = start + len(name.encode("utf-8"))
    source = (source_set.source_root / file).read_bytes()
    if start < 0 or start >= end or end > len(source):
        raise SymbolGraphError(
            code,
            "semantic range is outside source bytes",
            file=file,
            start=start,
        )
    if source[start:end] != name.encode("utf-8"):
        raise SymbolGraphError(
            code,
            "semantic range does not match source bytes",
            file=file,
            start=start,
        )
    return SourceRange(file=file, start=start, end=end)


def _reject_macro_location(
    source_catalog: SourceCatalog, location: Any
) -> None:
    if location is None:
        return
    if source_catalog.catalog_source_manager.isMacroLoc(location):
        file, start = _location_start(source_catalog, location)
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic location is generated by a macro",
            file=file,
            start=start,
        )


def _module_owner_map(source_catalog: SourceCatalog) -> dict[tuple[str, int, int], ModuleOwner]:
    return {
        (
            module.declaration.file,
            module.declaration.start,
            module.declaration.end,
        ): module
        for module in source_catalog.modules
    }


def _owner_for_signal(
    source_catalog: SourceCatalog,
    symbol: Any,
    owners: dict[tuple[str, int, int], ModuleOwner],
) -> ModuleOwner | None:
    definition = getattr(symbol, "declaringDefinition", None)
    if definition is None:
        return None
    if getattr(definition, "definitionKind", None) != pyslang.ast.DefinitionKind.Module:
        return None
    name = str(definition.name)
    try:
        declaration = _range_from_location(
            source_catalog,
            definition.location,
            name,
            code="SYMBOL_GRAPH_OWNER_MISMATCH",
        )
    except SymbolGraphError as error:
        if error.code == "SYMBOL_GRAPH_OWNER_MISMATCH":
            raise
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "signal module definition cannot map to a catalog owner",
            file=error.file,
            start=error.start,
        ) from error
    owner = owners.get((declaration.file, declaration.start, declaration.end))
    if owner is None:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "signal module definition cannot map to a catalog owner",
            file=declaration.file,
            start=declaration.start,
        )
    return owner


def _signal_range_key(
    source_catalog: SourceCatalog, symbol: Any
) -> tuple[str, int, int]:
    name = str(getattr(symbol, "name", ""))
    if not name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic signal has no source identifier",
        )
    _reject_macro_location(source_catalog, symbol.location)
    declaration = _range_from_location(
        source_catalog, symbol.location, name
    )
    return declaration.file, declaration.start, declaration.end


def _expression_range(
    source_catalog: SourceCatalog, expression: Any, name: str
) -> SourceRange:
    syntax = getattr(expression, "syntax", None)
    token = getattr(syntax, "identifier", None)
    if token is None or not token.rawText:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic expression has no direct source identifier token",
        )
    if token.rawText != name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic expression identifier does not match bound signal",
        )
    _reject_macro_location(source_catalog, token.location)
    return _range_from_location(source_catalog, token.location, name)


def _syntax_start(source_catalog: SourceCatalog, node: Any) -> tuple[str | None, int | None]:
    syntax = getattr(node, "syntax", None)
    source_range = getattr(syntax, "sourceRange", None)
    location = getattr(source_range, "start", None)
    return _location_start(source_catalog, location)


def _location_start(
    source_catalog: SourceCatalog, location: Any
) -> tuple[str | None, int | None]:
    if location is None:
        return None, None
    try:
        absolute = Path(
            source_catalog.catalog_source_manager.getFullPath(location.buffer)
        ).resolve()
        file = absolute.relative_to(source_catalog.source_set.source_root).as_posix()
        return file, int(location.offset)
    except (OSError, ValueError, RuntimeError):
        return None, int(location.offset)


def _audit_ranges(symbols: tuple[SourceSymbol, ...]) -> None:
    ranges: list[tuple[str, int, int, str]] = []
    for symbol in symbols:
        ranges.append(
            (
                symbol.declaration.file,
                symbol.declaration.start,
                symbol.declaration.end,
                symbol.symbol_id,
            )
        )
        for occurrence in symbol.occurrences:
            ranges.append(
                (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    symbol.symbol_id,
                )
            )
    seen: dict[tuple[str, int, int], str] = {}
    for file, start, end, symbol_id in ranges:
        key = (file, start, end)
        if key in seen:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "physical range belongs to multiple or repeated symbols",
                file=file,
                start=start,
            )
        seen[key] = symbol_id
    for file in sorted({item[0] for item in ranges}):
        ordered = sorted(item for item in ranges if item[0] == file)
        for previous, current in zip(ordered, ordered[1:]):
            if previous[2] > current[1]:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "physical ranges overlap",
                    file=file,
                    start=current[1],
                )


def build_symbol_graph(source_catalog: SourceCatalog) -> SymbolGraph:
    """Build the signals-only graph from the already compiled catalog view."""

    nodes: list[Any] = []
    source_catalog.catalog_root.visit(nodes.append)
    for node in nodes:
        if isinstance(node, pyslang.ast.UninstantiatedDefSymbol):
            file, start = _location_start(
                source_catalog, getattr(node, "location", None)
            )
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                "uninstantiated definition is outside T041 scope",
                file=file,
                start=start,
            )
    owners = _module_owner_map(source_catalog)
    variable_kind = pyslang.ast.SymbolKind.Variable
    net_kind = pyslang.ast.SymbolKind.Net

    excluded_ids: set[int] = set()
    for node in nodes:
        for attribute in ("internalSymbol", "returnValVar"):
            excluded = getattr(node, attribute, None)
            if excluded is not None:
                excluded_ids.add(id(excluded))

    declarations: dict[tuple[str, int, int], tuple[str, SourceRange, ModuleOwner]] = {}
    for node in nodes:
        if getattr(node, "kind", None) not in (variable_kind, net_kind):
            continue
        if id(node) in excluded_ids:
            continue
        name = str(getattr(node, "name", ""))
        if not name or name.startswith("$"):
            continue
        owner = _owner_for_signal(source_catalog, node, owners)
        if owner is None:
            continue
        _reject_macro_location(source_catalog, node.location)
        declaration = _range_from_location(
            source_catalog, node.location, name
        )
        key = (declaration.file, declaration.start, declaration.end)
        existing = declarations.get(key)
        if existing is not None:
            if existing[0] != name or existing[2].owner_id != owner.owner_id:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "physical declaration maps to multiple signals",
                    file=declaration.file,
                    start=declaration.start,
                )
            continue
        declarations[key] = (name, declaration, owner)

    occurrences: dict[tuple[str, int, int], dict[tuple[str, int, int, str], SymbolOccurrence]] = {
        key: {} for key in declarations
    }
    element_select_kind = getattr(pyslang.ast.ExpressionKind, "ElementSelect", None)
    element_value_ids = {
        id(getattr(node, "value", None))
        for node in nodes
        if getattr(node, "kind", None) == element_select_kind
        and getattr(node, "value", None) is not None
    }
    for node in nodes:
        node_kind = getattr(node, "kind", None)
        if node_kind == pyslang.ast.ExpressionKind.HierarchicalValue:
            target = getattr(node, "symbol", None)
            if target is None:
                file, start = _syntax_start(source_catalog, node)
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "hierarchical reference has no semantic target",
                    file=file,
                    start=start,
                )
            target_key = _signal_range_key(source_catalog, target)
            if target_key in declarations:
                file, start = _syntax_start(source_catalog, node)
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "hierarchical signal reference is outside T041 scope",
                    file=file,
                    start=start,
                )
            continue
        if node_kind == element_select_kind:
            value = getattr(node, "value", None)
            target = getattr(value, "symbol", None)
            if target is None:
                file, start = _syntax_start(source_catalog, node)
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "element-select reference has no semantic target",
                    file=file,
                    start=start,
                )
        elif node_kind == pyslang.ast.ExpressionKind.NamedValue:
            target = getattr(node, "symbol", None)
            if target is None and id(node) not in element_value_ids:
                file, start = _syntax_start(source_catalog, node)
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "syntax-only reference has no semantic target",
                    file=file,
                    start=start,
                )
            if target is not None and getattr(node, "syntax", None) is None:
                if id(node) in element_value_ids:
                    continue
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                    "semantic expression has no direct source identifier token",
                )
        else:
            target = None
        if target is None:
            continue
        target_key = _signal_range_key(source_catalog, target)
        declaration = declarations.get(target_key)
        if declaration is None:
            continue
        name = declaration[0]
        source_range = _expression_range(source_catalog, node, name)
        occurrence = SymbolOccurrence(source_range, "semantic_expression")
        occurrence_key = (
            source_range.file,
            source_range.start,
            source_range.end,
            occurrence.provenance,
        )
        occurrences[target_key][occurrence_key] = occurrence

    symbols_list: list[SourceSymbol] = []
    for key, (name, declaration, owner) in declarations.items():
        ordered_occurrences = tuple(
            sorted(
                occurrences[key].values(),
                key=lambda occurrence: (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                ),
            )
        )
        symbols_list.append(
            SourceSymbol(
                symbol_id=(
                    f"symbol:signals:{declaration.file}:"
                    f"{declaration.start}:{declaration.end}"
                ),
                category="signals",
                name=name,
                declaration=declaration,
                owner_module=owner.owner_id,
                semantic_owner=owner.owner_id,
                occurrences=ordered_occurrences,
                impact="local",
                abi="internal",
                support="eligible",
                reason=None,
            )
        )

    symbols = tuple(
        sorted(
            symbols_list,
            key=lambda symbol: (
                symbol.declaration.file,
                symbol.declaration.start,
                symbol.declaration.end,
                symbol.category,
                symbol.name,
            ),
        )
    )
    _audit_ranges(symbols)
    return SymbolGraph(schema_version=1, source_catalog=source_catalog, symbols=symbols)
