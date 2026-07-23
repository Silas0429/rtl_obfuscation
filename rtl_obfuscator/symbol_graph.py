"""Source SymbolGraph built from one T040 SourceCatalog view."""

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
        categories = [
            category
            for category in ("signals", "parameters", "genvars")
            if any(symbol.category == category for symbol in self.symbols)
        ]
        return {
            "schema_version": self.schema_version,
            "source_catalog": self.source_catalog.to_report(),
            "categories": categories,
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


@dataclass(frozen=True)
class _GenvarRecord:
    name: str
    declaration: SourceRange
    owner: ModuleOwner
    definition: Any


@dataclass(frozen=True)
class _ParameterRecord:
    name: str
    declaration: SourceRange
    owner: ModuleOwner
    definition: Any
    is_local: bool


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


def _owner_for_module_symbol(
    source_catalog: SourceCatalog,
    symbol: Any,
    owners: dict[tuple[str, int, int], ModuleOwner],
    *,
    label: str,
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
            f"{label} module definition cannot map to a catalog owner",
            file=error.file,
            start=error.start,
        ) from error
    owner = owners.get((declaration.file, declaration.start, declaration.end))
    if owner is None:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            f"{label} module definition cannot map to a catalog owner",
            file=declaration.file,
            start=declaration.start,
        )
    return owner


def _owner_for_signal(
    source_catalog: SourceCatalog,
    symbol: Any,
    owners: dict[tuple[str, int, int], ModuleOwner],
) -> ModuleOwner | None:
    return _owner_for_module_symbol(
        source_catalog, symbol, owners, label="signal"
    )


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


def _is_signal_target(symbol: Any) -> bool:
    return getattr(symbol, "kind", None) in (
        pyslang.ast.SymbolKind.Variable,
        pyslang.ast.SymbolKind.Net,
    )


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


def _syntax_node_start(
    source_catalog: SourceCatalog, syntax_node: Any
) -> tuple[str | None, int | None]:
    source_range = getattr(syntax_node, "sourceRange", None)
    return _location_start(source_catalog, getattr(source_range, "start", None))


def _syntax_identifier_tokens(syntax_node: Any) -> list[Any]:
    nodes: list[Any] = []
    syntax_node.visit(nodes.append)
    return [
        node.identifier
        for node in nodes
        if isinstance(node, pyslang.syntax.IdentifierNameSyntax)
        and getattr(node, "identifier", None) is not None
    ]


def _token_range(
    source_catalog: SourceCatalog, token: Any, name: str
) -> SourceRange:
    raw_text = getattr(token, "rawText", "")
    if not raw_text or raw_text != name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "generate syntax identifier does not match bound genvar",
        )
    _reject_macro_location(source_catalog, token.location)
    return _range_from_location(source_catalog, token.location, name)


def _module_definition_key(
    source_catalog: SourceCatalog, definition: Any
) -> tuple[str, int, int] | None:
    if getattr(definition, "definitionKind", None) != pyslang.ast.DefinitionKind.Module:
        return None
    declaration = _range_from_location(
        source_catalog,
        definition.location,
        str(definition.name),
        code="SYMBOL_GRAPH_OWNER_MISMATCH",
    )
    return declaration.file, declaration.start, declaration.end


def _has_iteration_evidence(
    source_catalog: SourceCatalog,
    nodes: list[Any],
    owner: ModuleOwner,
    name: str,
) -> bool:
    owner_key = (
        owner.declaration.file,
        owner.declaration.start,
        owner.declaration.end,
    )
    for node in nodes:
        if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Parameter:
            continue
        if str(getattr(node, "name", "")) != name:
            continue
        if not getattr(node, "isLocalParam", False) or not getattr(
            node, "isBodyParam", False
        ):
            continue
        definition = getattr(node, "declaringDefinition", None)
        if definition is None:
            continue
        if _module_definition_key(source_catalog, definition) == owner_key:
            return True
    return False


def _loop_has_nested_loop(loop: Any) -> bool:
    block = getattr(loop, "block", None)
    if block is None:
        return False
    nodes: list[Any] = []
    block.visit(nodes.append)
    return any(isinstance(node, pyslang.syntax.LoopGenerateSyntax) for node in nodes)


def _genvar_occurrence_tokens(loop: Any, *, name: str, inline: bool) -> list[Any]:
    tokens: list[Any] = []
    identifier = getattr(loop, "identifier", None)
    if not inline and identifier is not None:
        tokens.append(identifier)
    for expression_name in ("stopExpr", "iterationExpr"):
        expression = getattr(loop, expression_name, None)
        if expression is None:
            continue
        tokens.extend(
            token
            for token in _syntax_identifier_tokens(expression)
            if getattr(token, "rawText", None) == name
        )
    block = getattr(loop, "block", None)
    if block is not None:
        tokens.extend(
            token
            for token in _syntax_identifier_tokens(block)
            if getattr(token, "rawText", None) == name
        )
    return tokens


def _collect_genvar_symbols(
    source_catalog: SourceCatalog,
    nodes: list[Any],
    owners: dict[tuple[str, int, int], ModuleOwner],
) -> list[SourceSymbol]:
    genvar_kind = pyslang.ast.SymbolKind.Genvar
    records: dict[tuple[str, int, int], _GenvarRecord] = {}
    for node in nodes:
        if getattr(node, "kind", None) != genvar_kind:
            continue
        name = str(getattr(node, "name", ""))
        if not name or name.startswith("$"):
            continue
        owner = _owner_for_signal(source_catalog, node, owners)
        if owner is None:
            continue
        _reject_macro_location(source_catalog, node.location)
        declaration = _range_from_location(source_catalog, node.location, name)
        key = (declaration.file, declaration.start, declaration.end)
        existing = records.get(key)
        definition = getattr(node, "declaringDefinition", None)
        if existing is not None:
            if existing.name != name or existing.owner.owner_id != owner.owner_id:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "physical genvar declaration maps to multiple owners",
                    file=declaration.file,
                    start=declaration.start,
                )
            continue
        records[key] = _GenvarRecord(name, declaration, owner, definition)

    occurrences: dict[
        tuple[str, int, int], dict[tuple[str, int, int, str], SymbolOccurrence]
    ] = {key: {} for key in records}
    records_by_owner_name: dict[tuple[str, str], list[tuple[str, int, int]]] = {}
    for key, record in records.items():
        records_by_owner_name.setdefault((record.owner.owner_id, record.name), []).append(
            key
        )

    seen_definitions: set[tuple[str, int, int]] = set()
    for record_key, record in records.items():
        definition_key = _module_definition_key(source_catalog, record.definition)
        if definition_key is None:
            continue
        if definition_key in seen_definitions:
            continue
        seen_definitions.add(definition_key)
        syntax = getattr(record.definition, "syntax", None)
        if syntax is None:
            continue
        syntax_nodes: list[Any] = []
        syntax.visit(syntax_nodes.append)
        loops = [
            node
            for node in syntax_nodes
            if isinstance(node, pyslang.syntax.LoopGenerateSyntax)
        ]
        for loop in loops:
            if _loop_has_nested_loop(loop):
                file, start = _syntax_node_start(source_catalog, loop)
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "nested generate-for is outside T042 scope",
                    file=file,
                    start=start,
                )

        for loop in loops:
            identifier = getattr(loop, "identifier", None)
            if identifier is None or not getattr(identifier, "rawText", ""):
                file, start = _syntax_node_start(source_catalog, loop)
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "generate-for has no direct identifier token",
                    file=file,
                    start=start,
                )
            name = identifier.rawText
            candidate_keys = records_by_owner_name.get((record.owner.owner_id, name), [])
            inline = bool(getattr(getattr(loop, "genvar", None), "rawText", ""))
            if inline:
                identifier_range = _token_range(source_catalog, identifier, name)
                candidate_keys = [
                    candidate_key
                    for candidate_key in candidate_keys
                    if candidate_key
                    == (
                        identifier_range.file,
                        identifier_range.start,
                        identifier_range.end,
                    )
                ]
            else:
                if not candidate_keys:
                    continue
                if len(candidate_keys) != 1 or not _has_iteration_evidence(
                    source_catalog, nodes, record.owner, name
                ):
                    file, start = _syntax_node_start(source_catalog, loop)
                    raise SymbolGraphError(
                        "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                        "generate-for genvar iteration owner evidence is incomplete",
                        file=file,
                        start=start,
                    )
            if len(candidate_keys) != 1:
                file, start = _syntax_node_start(source_catalog, loop)
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "generate-for genvar owner is ambiguous",
                    file=file,
                    start=start,
                )
            target_key = candidate_keys[0]
            target_record = records[target_key]
            for token in _genvar_occurrence_tokens(
                loop, name=name, inline=inline
            ):
                source_range = _token_range(source_catalog, token, name)
                occurrence = SymbolOccurrence(source_range, "generate_syntax")
                occurrence_key = (
                    source_range.file,
                    source_range.start,
                    source_range.end,
                    occurrence.provenance,
                )
                occurrences[target_key][occurrence_key] = occurrence

    symbols: list[SourceSymbol] = []
    for key, record in records.items():
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
        symbols.append(
            SourceSymbol(
                symbol_id=(
                    f"symbol:genvars:{record.declaration.file}:"
                    f"{record.declaration.start}:{record.declaration.end}"
                ),
                category="genvars",
                name=record.name,
                declaration=record.declaration,
                owner_module=record.owner.owner_id,
                semantic_owner=record.owner.owner_id,
                occurrences=ordered_occurrences,
                impact="local",
                abi="internal",
                support="eligible",
                reason=None,
            )
        )
    return symbols


def _expression_identifier_range(
    source_catalog: SourceCatalog,
    expression: Any,
    name: str,
) -> SourceRange:
    syntax = getattr(expression, "syntax", None)
    identifier = getattr(syntax, "identifier", None)
    if identifier is None or not getattr(identifier, "rawText", ""):
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic parameter expression has no direct source identifier token",
        )
    if identifier.rawText != name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic parameter expression identifier does not match bound parameter",
        )
    _reject_macro_location(source_catalog, identifier.location)
    return _range_from_location(source_catalog, identifier.location, name)


def _parameter_source_key(
    source_catalog: SourceCatalog, symbol: Any
) -> tuple[str, int, int] | None:
    if getattr(symbol, "kind", None) != pyslang.ast.SymbolKind.Parameter:
        return None
    definition = getattr(symbol, "declaringDefinition", None)
    if getattr(definition, "definitionKind", None) != pyslang.ast.DefinitionKind.Module:
        return None
    name = str(getattr(symbol, "name", ""))
    if not name:
        return None
    declaration = _range_from_location(source_catalog, symbol.location, name)
    return declaration.file, declaration.start, declaration.end


def _append_bound_parameter_references(
    source_catalog: SourceCatalog,
    expression: Any,
    provenance: str,
    records: dict[tuple[str, int, int], _ParameterRecord],
    genvar_keys: set[tuple[str, int, int]],
    occurrences: dict[
        tuple[str, int, int], dict[tuple[str, int, int, str], SymbolOccurrence]
    ],
    special_ranges: set[tuple[tuple[str, int, int], tuple[str, int, int]]],
) -> None:
    if expression is None or not hasattr(expression, "visit"):
        return
    expression_nodes: list[Any] = []
    expression.visit(expression_nodes.append)
    for node in expression_nodes:
        if getattr(node, "kind", None) != pyslang.ast.ExpressionKind.NamedValue:
            continue
        target = getattr(node, "symbol", None)
        target_key = _parameter_source_key(source_catalog, target)
        if target_key is None or target_key in genvar_keys:
            continue
        record = records.get(target_key)
        if record is None:
            continue
        source_range = _expression_identifier_range(
            source_catalog, node, record.name
        )
        occurrence = SymbolOccurrence(source_range, provenance)
        occurrence_key = (
            source_range.file,
            source_range.start,
            source_range.end,
            provenance,
        )
        occurrences[target_key][occurrence_key] = occurrence
        if provenance != "semantic_expression":
            special_ranges.add(
                (
                    target_key,
                    (
                        source_range.file,
                        source_range.start,
                        source_range.end,
                    ),
                )
            )


def _reject_parameter_unsupported_nodes(
    source_catalog: SourceCatalog,
    nodes: list[Any],
    owners: dict[tuple[str, int, int], ModuleOwner],
) -> None:
    type_parameter_kind = getattr(pyslang.ast.SymbolKind, "TypeParameter", None)
    defparam_kind = getattr(pyslang.ast.SymbolKind, "DefParam", None)
    for node in nodes:
        definition = getattr(node, "declaringDefinition", None)
        if definition is None:
            continue
        if getattr(node, "kind", None) == type_parameter_kind:
            owner = _owner_for_module_symbol(
                source_catalog, node, owners, label="parameter"
            )
            if owner is not None:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                    "module type parameter is outside T043 scope",
                    file=owner.declaration.file,
                    start=owner.declaration.start,
                )
        elif getattr(node, "kind", None) == defparam_kind:
            owner = _owner_for_module_symbol(
                source_catalog, node, owners, label="defparam"
            )
            if owner is not None:
                file, start = _location_start(
                    source_catalog, getattr(node, "location", None)
                )
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "defparam is outside T043 scope",
                    file=file,
                    start=start,
                )


def _parameter_classification(
    source_catalog: SourceCatalog, record: _ParameterRecord
) -> tuple[str, str, str, str | None]:
    if record.is_local:
        return "local", "internal", "eligible", None
    if source_catalog.source_set.top is None:
        return "cross_module", "module_abi", "preserved", "module_abi_requires_top"
    if record.owner.is_selected_top:
        return "cross_module", "top_boundary", "preserved", "selected_top_boundary"
    if record.owner.in_top_closure:
        return "cross_module", "module_abi", "eligible", None
    return "cross_module", "module_abi", "preserved", "outside_top_closure"


def _collect_parameter_symbols(
    source_catalog: SourceCatalog,
    nodes: list[Any],
    owners: dict[tuple[str, int, int], ModuleOwner],
    genvar_symbols: list[SourceSymbol],
) -> list[SourceSymbol]:
    _reject_parameter_unsupported_nodes(source_catalog, nodes, owners)
    genvar_keys = {
        (
            symbol.declaration.file,
            symbol.declaration.start,
            symbol.declaration.end,
        )
        for symbol in genvar_symbols
    }
    parameter_kind = pyslang.ast.SymbolKind.Parameter
    records: dict[tuple[str, int, int], _ParameterRecord] = {}
    for node in nodes:
        if getattr(node, "kind", None) != parameter_kind:
            continue
        name = str(getattr(node, "name", ""))
        if not name or name.startswith("$"):
            continue
        if getattr(node, "isType", False):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "type parameter is outside T043 scope",
            )
        if (
            getattr(node, "isLocalParam", False)
            and getattr(node, "isBodyParam", False)
            and type(getattr(node, "syntax", None)).__name__
            == "IdentifierNameSyntax"
        ):
            continue
        owner = _owner_for_module_symbol(
            source_catalog, node, owners, label="parameter"
        )
        if owner is None:
            continue
        _reject_macro_location(source_catalog, node.location)
        if _parameter_source_key(source_catalog, node) in genvar_keys:
            continue
        declaration = _range_from_location(
            source_catalog, node.location, name
        )
        key = (declaration.file, declaration.start, declaration.end)
        definition = getattr(node, "declaringDefinition", None)
        existing = records.get(key)
        is_local = bool(getattr(node, "isLocalParam", False))
        if existing is not None:
            if (
                existing.name != name
                or existing.owner.owner_id != owner.owner_id
                or existing.is_local != is_local
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "physical parameter declaration maps to multiple owners",
                    file=declaration.file,
                    start=declaration.start,
                )
            continue
        records[key] = _ParameterRecord(
            name=name,
            declaration=declaration,
            owner=owner,
            definition=definition,
            is_local=is_local,
        )

    occurrences: dict[
        tuple[str, int, int], dict[tuple[str, int, int, str], SymbolOccurrence]
    ] = {key: {} for key in records}
    special_ranges: set[tuple[tuple[str, int, int], tuple[str, int, int]]] = set()

    for node in nodes:
        if getattr(node, "kind", None) != pyslang.ast.ExpressionKind.NamedValue:
            continue
        _append_bound_parameter_references(
            source_catalog,
            node,
            "semantic_expression",
            records,
            genvar_keys,
            occurrences,
            special_ranges,
        )

    for node in nodes:
        declared_type = getattr(node, "declaredType", None)
        for dimension in getattr(declared_type, "resolvedDimensions", ()):
            for expression in (
                getattr(dimension, "leftExpr", None),
                getattr(dimension, "rightExpr", None),
                getattr(dimension, "queueMaxSize", None),
            ):
                _append_bound_parameter_references(
                    source_catalog,
                    expression,
                    "declaration_dimension",
                    records,
                    genvar_keys,
                    occurrences,
                    special_ranges,
                )

    generate_block_kind = getattr(pyslang.ast.SymbolKind, "GenerateBlock", None)
    generate_array_kind = getattr(
        pyslang.ast.SymbolKind, "GenerateBlockArray", None
    )
    for node in nodes:
        node_kind = getattr(node, "kind", None)
        if node_kind == generate_block_kind:
            expressions = (getattr(node, "conditionExpression", None),)
        elif node_kind == generate_array_kind:
            expressions = (
                getattr(node, "initialExpression", None),
                getattr(node, "stopExpression", None),
                getattr(node, "iterExpression", None),
            )
        else:
            continue
        for expression in expressions:
            _append_bound_parameter_references(
                source_catalog,
                expression,
                "generate_syntax",
                records,
                genvar_keys,
                occurrences,
                special_ranges,
            )

    records_by_definition_name: dict[
        tuple[str, int, int, str], list[tuple[str, int, int]]
    ] = {}
    for key, record in records.items():
        if record.is_local:
            continue
        definition_key = _module_definition_key(source_catalog, record.definition)
        if definition_key is None:
            continue
        records_by_definition_name.setdefault(
            (*definition_key, record.name), []
        ).append(key)

    instance_kind = pyslang.ast.SymbolKind.Instance
    for node in nodes:
        if getattr(node, "kind", None) != instance_kind:
            continue
        definition = getattr(node, "definition", None)
        syntax = getattr(node, "syntax", None)
        hierarchy = getattr(syntax, "parent", None)
        definition_key = _module_definition_key(source_catalog, definition)
        if hierarchy is None or definition_key is None:
            continue
        syntax_nodes: list[Any] = []
        hierarchy.visit(syntax_nodes.append)
        for syntax_node in syntax_nodes:
            if type(syntax_node).__name__ != "NamedParamAssignmentSyntax":
                continue
            name_token = getattr(syntax_node, "name", None)
            if name_token is None or not getattr(name_token, "rawText", ""):
                continue
            candidate_keys = records_by_definition_name.get(
                (*definition_key, name_token.rawText), []
            )
            if len(candidate_keys) > 1:
                file, start = _location_start(
                    source_catalog, name_token.location
                )
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "named parameter override owner is ambiguous",
                    file=file,
                    start=start,
                )
            if not candidate_keys:
                continue
            _reject_macro_location(source_catalog, name_token.location)
            target_key = candidate_keys[0]
            source_range = _range_from_location(
                source_catalog, name_token.location, name_token.rawText
            )
            occurrence = SymbolOccurrence(source_range, "named_override")
            occurrence_key = (
                source_range.file,
                source_range.start,
                source_range.end,
                occurrence.provenance,
            )
            occurrences[target_key][occurrence_key] = occurrence

    for target_key, source_range_key in special_ranges:
        occurrences[target_key].pop(
            (*source_range_key, "semantic_expression"), None
        )

    symbols: list[SourceSymbol] = []
    for key, record in records.items():
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
        impact, abi, support, reason = _parameter_classification(
            source_catalog, record
        )
        symbols.append(
            SourceSymbol(
                symbol_id=(
                    f"symbol:parameters:{record.declaration.file}:"
                    f"{record.declaration.start}:{record.declaration.end}"
                ),
                category="parameters",
                name=record.name,
                declaration=record.declaration,
                owner_module=record.owner.owner_id,
                semantic_owner=record.owner.owner_id,
                occurrences=ordered_occurrences,
                impact=impact,
                abi=abi,
                support=support,
                reason=reason,
            )
        )
    return symbols


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
            if not _is_signal_target(target):
                continue
            target_key = _signal_range_key(source_catalog, target)
            if target_key not in declarations:
                continue
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
                if getattr(node, "syntax", None) is None:
                    continue
                file, start = _syntax_start(source_catalog, node)
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                    "syntax-only reference has no semantic target",
                    file=file,
                    start=start,
                )
        else:
            target = None
        if target is None:
            continue
        if not _is_signal_target(target):
            continue
        if getattr(node, "syntax", None) is None:
            if id(node) in element_value_ids:
                continue
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "semantic expression has no direct source identifier token",
            )
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

    genvar_symbols = _collect_genvar_symbols(source_catalog, nodes, owners)
    symbols_list.extend(
        _collect_parameter_symbols(source_catalog, nodes, owners, genvar_symbols)
    )
    symbols_list.extend(genvar_symbols)

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
