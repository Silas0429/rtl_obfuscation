"""Source SymbolGraph built from one T040 SourceCatalog view."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pyslang

from .source_catalog import ModuleOwner, SourceCatalog, SourceRange
from .category_registry_vnext import CANONICAL_CATEGORIES


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
            for category in CANONICAL_CATEGORIES
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
class _NestedModuleSpan:
    owner_id: str
    source_range: SourceRange


@dataclass(frozen=True)
class _MacroOwnerEvidence:
    source_manager: Any
    module_spans: tuple[_NestedModuleSpan, ...]
    owner_ids: frozenset[str]
    target_owner_ids: set[str] = field(default_factory=set)


_active_macro_owner_evidence: ContextVar[_MacroOwnerEvidence | None] = ContextVar(
    "symbol_graph_macro_owner_evidence", default=None
)


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
) -> bool:
    if location is None:
        return False
    if source_catalog.catalog_source_manager.isMacroLoc(location):
        evidence = _active_macro_owner_evidence.get()
        owner_id = None
        if evidence is not None and evidence.source_manager is source_catalog.catalog_source_manager:
            try:
                expanded = source_catalog.catalog_source_manager.getFullyExpandedLoc(
                    location
                )
            except (AttributeError, RuntimeError, ValueError):
                expanded = None
            if expanded is not None:
                file, offset = _location_start(source_catalog, expanded)
                matches = [
                    span.owner_id
                    for span in evidence.module_spans
                    if span.source_range.file == file
                    and offset is not None
                    and span.source_range.start <= offset < span.source_range.end
                ]
                if len(matches) > 1:
                    raise SymbolGraphError(
                        "SYMBOL_GRAPH_RANGE_CONFLICT",
                        "macro expanded location maps to multiple physical module owners",
                        file=file,
                        start=offset,
                    )
                if matches:
                    owner_id = matches[0]
        if owner_id is not None:
            return True
        file, start = _location_start(source_catalog, location)
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic location is generated by a macro",
            file=file,
            start=start,
        )
    return False


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
) -> tuple[str, int, int] | None:
    name = str(getattr(symbol, "name", ""))
    if not name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic signal has no source identifier",
        )
    if _reject_macro_location(source_catalog, symbol.location):
        return None
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
) -> SourceRange | None:
    syntax = getattr(expression, "syntax", None)
    token = _direct_expression_identifier(syntax)
    if token is None or not token.rawText:
        # Some elaborated NamedValueExpression nodes retain the semantic
        # binding and an exact source span but lose the convenience
        # IdentifierNameSyntax token.  Accept only that span when it is a
        # physical, non-macro range whose bytes are exactly the bound name.
        # The expression itself is the already-bound semantic target; no
        # syntax-subtree search is permitted here.
        source_range = (
            getattr(syntax, "sourceRange", None)
            if syntax is not None
            else getattr(expression, "sourceRange", None)
        )
        start = getattr(source_range, "start", None)
        end = getattr(source_range, "end", None)
        if start is None or end is None or start.buffer != end.buffer:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "semantic expression has no direct source identifier token",
            )
        if _reject_macro_location(source_catalog, start):
            return None
        file, start_offset = _location_start(source_catalog, start)
        if file is None or start_offset is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "semantic expression source range is outside the SourceSet",
            )
        end_offset = int(end.offset)
        source = (source_catalog.source_set.source_root / file).read_bytes()
        if end_offset <= start_offset or source[start_offset:end_offset] != name.encode("utf-8"):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "semantic expression source range does not match bound name",
                file=file,
                start=start_offset,
            )
        return SourceRange(file=file, start=start_offset, end=end_offset)
    if token.rawText != name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic expression identifier does not match bound signal",
        )
    if _reject_macro_location(source_catalog, token.location):
        return None
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


def _direct_expression_identifier(syntax: Any) -> Any | None:
    """Return an identifier through a syntax-kind-specific direct path.

    This intentionally handles only fields whose meaning is fixed by the
    expression syntax. It must not walk a subtree or select a token by name.
    """

    if syntax is None:
        return None
    identifier = getattr(syntax, "identifier", None)
    if identifier is not None and getattr(identifier, "rawText", ""):
        return identifier
    if type(syntax).__name__ == "ParenthesizedExpressionSyntax":
        expression = getattr(syntax, "expression", None)
        identifier = getattr(expression, "identifier", None)
        if identifier is not None and getattr(identifier, "rawText", ""):
            return identifier
    return None


def _direct_member_identifier(syntax: Any) -> Any | None:
    """Return a member token through fixed scoped/parenthesized fields only."""

    if syntax is None:
        return None
    right = getattr(syntax, "right", None)
    identifier = getattr(right, "identifier", None)
    if identifier is not None and getattr(identifier, "rawText", ""):
        return identifier
    if type(syntax).__name__ == "ParenthesizedExpressionSyntax":
        return _direct_member_identifier(getattr(syntax, "expression", None))
    return None


def _declared_dimension_identifier_tokens(syntax: Any) -> tuple[Any, ...]:
    """Return only fixed-field identifiers in a declared type dimension.

    PySlang does not expose every ANSI-port/data-declaration dimension as a
    bound expression node.  The declaration owner is still semantic, so the
    missing source token can be recovered through the typed syntax fields of
    ``NamedTypeSyntax -> IdentifierSelectNameSyntax -> ElementSelectSyntax``.
    This helper deliberately follows those fields; it never walks a syntax
    subtree or chooses a token by spelling.
    """

    parent = getattr(syntax, "parent", None)
    header = getattr(parent, "header", None)
    data_type = getattr(header, "dataType", None)
    if data_type is None:
        data_type = getattr(parent, "type", None)
    if type(data_type).__name__ != "NamedTypeSyntax":
        return ()
    name = getattr(data_type, "name", None)
    if type(name).__name__ != "IdentifierSelectNameSyntax":
        return ()
    tokens: list[Any] = []
    for selector in getattr(name, "selectors", ()):
        if type(selector).__name__ != "ElementSelectSyntax":
            continue
        range_select = getattr(selector, "selector", None)
        if type(range_select).__name__ != "RangeSelectSyntax":
            continue
        for expression in (
            getattr(range_select, "left", None),
            getattr(range_select, "right", None),
        ):
            if type(expression).__name__ == "IdentifierNameSyntax":
                token = getattr(expression, "identifier", None)
                if token is not None:
                    tokens.append(token)
                continue
            if type(expression).__name__ != "BinaryExpressionSyntax":
                continue
            for operand in (
                getattr(expression, "left", None),
                getattr(expression, "right", None),
            ):
                if type(operand).__name__ != "IdentifierNameSyntax":
                    continue
                token = getattr(operand, "identifier", None)
                if token is not None:
                    tokens.append(token)
    return tuple(tokens)


def _packed_aggregate_member_dimension_identifier_tokens(alias: Any) -> tuple[Any, ...]:
    """Return identifiers from one alias member's bounded declared dimensions."""

    canonical = getattr(alias, "canonicalType", None)
    syntax = getattr(canonical, "syntax", None)
    if type(syntax).__name__ != "StructUnionTypeSyntax":
        return ()
    tokens: list[Any] = []
    for member in getattr(syntax, "members", ()):
        member_type = getattr(member, "type", None)
        for dimension in getattr(member_type, "dimensions", ()):
            if type(dimension).__name__ != "VariableDimensionSyntax":
                continue
            specifier = getattr(dimension, "specifier", None)
            if type(specifier).__name__ != "RangeDimensionSpecifierSyntax":
                continue
            selector = getattr(specifier, "selector", None)
            if type(selector).__name__ != "RangeSelectSyntax":
                continue
            for expression in (
                getattr(selector, "left", None),
                getattr(selector, "right", None),
            ):
                if type(expression).__name__ == "IdentifierNameSyntax":
                    token = getattr(expression, "identifier", None)
                    if token is not None:
                        tokens.append(token)
                    continue
                if type(expression).__name__ != "BinaryExpressionSyntax":
                    continue
                for operand in (
                    getattr(expression, "left", None),
                    getattr(expression, "right", None),
                ):
                    if type(operand).__name__ != "IdentifierNameSyntax":
                        continue
                    token = getattr(operand, "identifier", None)
                    if token is not None:
                        tokens.append(token)
    return tuple(tokens)


def _scope_lookup_target(scope: Any, token: Any) -> Any:
    """Resolve a fixed-field token in its already-known semantic scope."""

    name = str(getattr(token, "rawText", ""))
    lookup_name = getattr(scope, "lookupName", None)
    target = lookup_name(name) if lookup_name is not None and name else None
    if target is None:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
            "scope-bound identifier has no semantic target",
        )
    return target


def _sized_cast_identifier_token(syntax: Any) -> Any | None:
    """Return only the direct identifier of a typed cast syntax node."""

    if type(syntax).__name__ != "CastExpressionSyntax":
        return None
    left = getattr(syntax, "left", None)
    if type(left).__name__ != "IdentifierNameSyntax":
        return None
    token = getattr(left, "identifier", None)
    if token is None or not getattr(token, "rawText", ""):
        return None
    return token


def _is_builtin_keyword_cast_conversion(node: Any) -> bool:
    """Recognize only PySlang's typed built-in keyword-cast syntax."""

    syntax = getattr(node, "syntax", None)
    if type(syntax).__name__ == "SignedCastExpressionSyntax":
        return True
    if syntax is not None:
        return False
    operand = getattr(node, "operand", None)
    return (
        type(operand).__name__ == "ConversionExpression"
        and type(getattr(operand, "syntax", None)).__name__
        == "SignedCastExpressionSyntax"
    )


def _semantic_scope_span(
    source_catalog: SourceCatalog, node: Any
) -> tuple[str, int, int] | None:
    """Return a source-backed span for one semantic lexical-scope candidate."""

    syntax = getattr(node, "syntax", None)
    source_range = getattr(syntax, "sourceRange", None)
    start = getattr(source_range, "start", None)
    end = getattr(source_range, "end", None)
    if start is None or end is None or start.buffer != end.buffer:
        return None
    _reject_macro_location(source_catalog, start)
    try:
        absolute = Path(
            source_catalog.catalog_source_manager.getFullPath(start.buffer)
        ).resolve()
        file = absolute.relative_to(
            source_catalog.source_set.source_root
        ).as_posix()
    except (OSError, RuntimeError, ValueError) as error:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_RANGE_INVALID",
            "semantic scope is outside the SourceSet root",
        ) from error
    if file not in _physical_files(source_catalog):
        raise SymbolGraphError(
            "SYMBOL_GRAPH_RANGE_INVALID",
            "semantic scope is not in a SourceSet physical file",
            file=file,
            start=int(start.offset),
        )
    start_offset = int(start.offset)
    end_offset = int(end.offset)
    source = (source_catalog.source_set.source_root / file).read_bytes()
    if start_offset < 0 or start_offset >= end_offset or end_offset > len(source):
        raise SymbolGraphError(
            "SYMBOL_GRAPH_RANGE_INVALID",
            "semantic scope span is outside source bytes",
            file=file,
            start=start_offset,
        )
    return file, start_offset, end_offset


def _sized_cast_target_from_scopes(
    source_catalog: SourceCatalog,
    nodes: list[Any],
    token: Any,
) -> Any | None:
    """Resolve a cast token through the smallest source-backed semantic scope."""

    token_offset = int(token.location.offset)
    token_buffer = token.location.buffer
    candidates: list[tuple[int, tuple[str, int, int], Any]] = []
    name = str(token.rawText)
    for node in nodes:
        scope = getattr(node, "parentScope", None)
        lookup_name = getattr(scope, "lookupName", None)
        if lookup_name is None:
            continue
        syntax = getattr(node, "syntax", None)
        source_range = getattr(syntax, "sourceRange", None)
        start = getattr(source_range, "start", None)
        end = getattr(source_range, "end", None)
        if start is None or end is None or start.buffer != token_buffer:
            continue
        if not (int(start.offset) <= token_offset < int(end.offset)):
            continue
        span = _semantic_scope_span(source_catalog, node)
        if span is None:
            continue
        target = lookup_name(name)
        if target is None:
            continue
        candidates.append((span[2] - span[1], span, target))
    if not candidates:
        return None
    smallest = min(item[0] for item in candidates)
    selected = [item for item in candidates if item[0] == smallest]
    target_keys = {
        _parameter_source_key(source_catalog, item[2])
        for item in selected
    }
    target_keys.discard(None)
    if len(target_keys) > 1:
        file, start = _location_start(source_catalog, token.location)
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
            "sized cast lexical scope resolves to multiple parameter declarations",
            file=file,
            start=start,
        )
    return selected[0][2]


def _token_range(
    source_catalog: SourceCatalog, token: Any, name: str
) -> SourceRange | None:
    raw_text = getattr(token, "rawText", "")
    if not raw_text or raw_text != name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "generate syntax identifier does not match bound genvar",
        )
    if _reject_macro_location(source_catalog, token.location):
        return None
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


def _nested_module_span(
    source_catalog: SourceCatalog,
    owner: ModuleOwner,
    definition: Any,
) -> _NestedModuleSpan:
    syntax = getattr(definition, "syntax", None)
    if not isinstance(syntax, pyslang.syntax.ModuleDeclarationSyntax):
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "nested generate definition is not a module declaration syntax",
            file=owner.declaration.file,
            start=owner.declaration.start,
        )
    source_range = getattr(syntax, "sourceRange", None)
    start = getattr(source_range, "start", None)
    end = getattr(source_range, "end", None)
    if start is None or end is None or start.buffer != end.buffer:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "nested generate module syntax span is not source-backed",
            file=owner.declaration.file,
            start=owner.declaration.start,
        )
    _reject_macro_location(source_catalog, start)
    _reject_macro_location(source_catalog, end)
    file, start_offset = _location_start(source_catalog, start)
    end_file, end_offset = _location_start(source_catalog, end)
    if (
        file is None
        or end_file != file
        or start_offset is None
        or end_offset is None
        or start_offset >= end_offset
    ):
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "nested generate module syntax span is not a precise physical range",
            file=file,
            start=start_offset,
        )
    if file not in _physical_files(source_catalog):
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "nested generate module syntax span is not in a physical source file",
            file=file,
            start=start_offset,
        )
    span = SourceRange(file=file, start=start_offset, end=end_offset)
    if not (
        span.file == owner.declaration.file
        and span.start <= owner.declaration.start
        and owner.declaration.end <= span.end
    ):
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "nested generate module syntax span does not contain its owner declaration",
            file=span.file,
            start=span.start,
        )
    contained_modules = [
        module
        for module in source_catalog.modules
        if module.declaration.file == span.file
        and span.start <= module.declaration.start
        and module.declaration.end <= span.end
    ]
    if len(contained_modules) != 1 or contained_modules[0].owner_id != owner.owner_id:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_RANGE_CONFLICT",
            "nested generate module syntax span contains multiple or different module owners",
            file=span.file,
            start=span.start,
        )
    return _NestedModuleSpan(owner.owner_id, span)


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
) -> tuple[list[SourceSymbol], tuple[_NestedModuleSpan, ...]]:
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
        if _reject_macro_location(source_catalog, node.location):
            continue
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
    nested_spans_by_owner: dict[str, SourceRange] = {}
    for record_key, record in records.items():
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
        nested_loops = [loop for loop in loops if _loop_has_nested_loop(loop)]
        definition_key = _module_definition_key(source_catalog, record.definition)
        if nested_loops:
            if definition_key is None:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "genvar declaring definition is not a physical module definition",
                    file=record.declaration.file,
                    start=record.declaration.start,
                )
            owner_key = (
                record.owner.declaration.file,
                record.owner.declaration.start,
                record.owner.declaration.end,
            )
            if definition_key != owner_key:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "genvar declaring definition does not match its physical module owner",
                    file=record.declaration.file,
                    start=record.declaration.start,
                )
            if definition_key in seen_definitions:
                continue
            seen_definitions.add(definition_key)
            for loop in nested_loops:
                nested_span = _nested_module_span(
                    source_catalog, record.owner, record.definition
                )
                previous_span = nested_spans_by_owner.get(record.owner.owner_id)
                if previous_span is not None and previous_span != nested_span.source_range:
                    raise SymbolGraphError(
                        "SYMBOL_GRAPH_RANGE_CONFLICT",
                        "nested generate owner was discovered with conflicting module spans",
                        file=record.declaration.file,
                        start=record.declaration.start,
                    )
                nested_spans_by_owner[record.owner.owner_id] = nested_span.source_range
            continue

        if definition_key is None:
            continue
        if definition_key in seen_definitions:
            continue
        seen_definitions.add(definition_key)

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
                if identifier_range is None:
                    continue
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
                if source_range is None:
                    continue
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
    return symbols, tuple(
        _NestedModuleSpan(owner_id, source_range)
        for owner_id, source_range in sorted(nested_spans_by_owner.items())
    )


def _expression_identifier_range(
    source_catalog: SourceCatalog,
    expression: Any,
    name: str,
) -> SourceRange | None:
    syntax = getattr(expression, "syntax", None)
    identifier = _direct_expression_identifier(syntax)
    if identifier is None or not getattr(identifier, "rawText", ""):
        source_range = (
            getattr(syntax, "sourceRange", None)
            if syntax is not None
            else getattr(expression, "sourceRange", None)
        )
        start = getattr(source_range, "start", None)
        end = getattr(source_range, "end", None)
        if start is None or end is None or start.buffer != end.buffer:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "semantic parameter expression has no direct source identifier token",
            )
        if _reject_macro_location(source_catalog, start):
            return None
        file, start_offset = _location_start(source_catalog, start)
        if file is None or start_offset is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "semantic parameter expression source range is outside the SourceSet",
            )
        end_offset = int(end.offset)
        source = (source_catalog.source_set.source_root / file).read_bytes()
        if end_offset <= start_offset or source[start_offset:end_offset] != name.encode("utf-8"):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "semantic parameter expression source range does not match bound name",
                file=file,
                start=start_offset,
            )
        return SourceRange(file=file, start=start_offset, end=end_offset)
    if identifier.rawText != name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "semantic parameter expression identifier does not match bound parameter",
        )
    if _reject_macro_location(source_catalog, identifier.location):
        return None
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
    if _reject_macro_location(source_catalog, getattr(symbol, "location", None)):
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
        if source_range is None:
            continue
        if (
            source_range.file,
            source_range.start,
            source_range.end,
        ) in genvar_keys:
            continue
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


def _collect_type_parameter_symbols(
    source_catalog: SourceCatalog,
    nodes: list[Any],
    owners: dict[tuple[str, int, int], ModuleOwner],
) -> tuple[list[SourceSymbol], set[str], set[str]]:
    type_parameter_kind = getattr(pyslang.ast.SymbolKind, "TypeParameter", None)
    symbols: list[SourceSymbol] = []
    owner_ids: set[str] = set()
    symbol_ids: set[str] = set()
    declarations: dict[tuple[str, int, int], tuple[str, ModuleOwner]] = {}
    for node in nodes:
        if getattr(node, "kind", None) != type_parameter_kind:
            continue
        name = str(getattr(node, "name", ""))
        location = getattr(node, "location", None)
        if not name or location is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "module type parameter has no physical declaration",
            )
        owner = _owner_for_module_symbol(
            source_catalog, node, owners, label="type parameter"
        )
        if owner is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "type parameter cannot map to a physical module owner",
            )
        if _reject_macro_location(source_catalog, location):
            continue
        declaration = _range_from_location(source_catalog, location, name)
        key = (declaration.file, declaration.start, declaration.end)
        previous = declarations.get(key)
        if previous is not None:
            if previous[0] != name or previous[1].owner_id != owner.owner_id:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "physical type parameter declaration maps to multiple owners",
                    file=declaration.file,
                    start=declaration.start,
                )
            continue
        symbol_id = (
            f"symbol:parameters:{declaration.file}:"
            f"{declaration.start}:{declaration.end}"
        )
        symbols.append(
            SourceSymbol(
                symbol_id=symbol_id,
                category="parameters",
                name=name,
                declaration=declaration,
                owner_module=owner.owner_id,
                semantic_owner=owner.owner_id,
                occurrences=(),
                impact="cross_module",
                abi="module_abi",
                support="unsupported",
                reason="type_parameter_not_renamed",
            )
        )
        declarations[key] = (name, owner)
        owner_ids.add(owner.owner_id)
        symbol_ids.add(symbol_id)
    return symbols, owner_ids, symbol_ids


def _defparam_final_identifier_token(node: Any) -> Any:
    syntax = getattr(node, "syntax", None)
    name_syntax = getattr(syntax, "name", None)
    if type(name_syntax).__name__ != "ScopedNameSyntax":
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
            "defparam binding has no typed scoped name",
        )
    final_identifier = getattr(name_syntax, "right", None)
    if type(final_identifier).__name__ != "IdentifierNameSyntax":
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
            "defparam binding has no typed final identifier",
        )
    token = getattr(final_identifier, "identifier", None)
    if not getattr(token, "rawText", "") or getattr(token, "location", None) is None:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
            "defparam binding final identifier has no physical token",
        )
    return token


def _collect_defparam_bindings(
    source_catalog: SourceCatalog,
    nodes: list[Any],
    owners: dict[tuple[str, int, int], ModuleOwner],
    records: dict[tuple[str, int, int], _ParameterRecord],
    occurrences: dict[
        tuple[str, int, int], dict[tuple[str, int, int, str], SymbolOccurrence]
    ],
) -> set[str]:
    defparam_kind = getattr(pyslang.ast.SymbolKind, "DefParam", None)
    binding_owners: set[str] = set()
    token_targets: dict[tuple[str, int, int], tuple[str, int, int]] = {}
    for node in nodes:
        if getattr(node, "kind", None) != defparam_kind:
            continue
        reference_owner = _owner_for_module_symbol(
            source_catalog, node, owners, label="defparam"
        )
        if reference_owner is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "defparam cannot map to a physical module owner",
            )
        target = getattr(node, "target", None)
        target_key = _parameter_source_key(source_catalog, target)
        target_record = records.get(target_key) if target_key is not None else None
        if target_key is None or target_record is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                "defparam target is not an exact module value parameter declaration",
            )
        target_owner = _owner_for_module_symbol(
            source_catalog, target, owners, label="defparam target"
        )
        if target_owner is None or target_owner.owner_id != target_record.owner.owner_id:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "defparam target declaration owner does not match its parameter record",
            )
        token = _defparam_final_identifier_token(node)
        token_name = str(getattr(token, "rawText", ""))
        if token_name != target_record.name or token_name != str(getattr(target, "name", "")):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                "defparam binding token does not match its semantic target",
            )
        if _reject_macro_location(source_catalog, token.location):
            continue
        source_range = _range_from_location(source_catalog, token.location, token_name)
        token_key = (source_range.file, source_range.start, source_range.end)
        previous_target = token_targets.get(token_key)
        if previous_target is not None and previous_target != target_key:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "physical defparam binding token maps to multiple parameters",
                file=source_range.file,
                start=source_range.start,
            )
        token_targets[token_key] = target_key
        occurrences[target_key][(*token_key, "defparam_binding")] = SymbolOccurrence(
            source_range, "defparam_binding"
        )
        binding_owners.update((reference_owner.owner_id, target_owner.owner_id))
    return binding_owners


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
) -> tuple[list[SourceSymbol], set[str]]:
    genvar_keys = {
        (source_range.file, source_range.start, source_range.end)
        for symbol in genvar_symbols
        for source_range in (
            symbol.declaration,
            *(occurrence.source_range for occurrence in symbol.occurrences),
        )
    }
    parameter_kind = pyslang.ast.SymbolKind.Parameter
    records: dict[tuple[str, int, int], _ParameterRecord] = {}
    for node in nodes:
        if getattr(node, "kind", None) != parameter_kind:
            continue
        name = str(getattr(node, "name", ""))
        if not name or name.startswith("$"):
            continue
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
        if _reject_macro_location(source_catalog, node.location):
            continue
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

    # Some declared type dimensions (notably packed ANSI-port dimensions)
    # have no corresponding resolved expression node in PySlang.  Recover
    # those bytes only from a known semantic declaration owner and its fixed
    # typed syntax path.  The scope lookup is the binding proof; a matching
    # spelling without the exact parameter declaration is never accepted.
    for node in nodes:
        if getattr(node, "kind", None) not in (
            pyslang.ast.SymbolKind.Variable,
            pyslang.ast.SymbolKind.Net,
        ) and type(node).__name__ not in {"PortSymbol", "InterfacePortSymbol"}:
            continue
        scope = getattr(node, "parentScope", None)
        lookup_name = getattr(scope, "lookupName", None)
        if lookup_name is None:
            continue
        syntax = getattr(node, "syntax", None)
        for token in _declared_dimension_identifier_tokens(syntax):
            name = str(getattr(token, "rawText", ""))
            if not name:
                continue
            target = _scope_lookup_target(scope, token)
            target_key = _parameter_source_key(source_catalog, target)
            if target_key is None or target_key in genvar_keys:
                continue
            record = records.get(target_key)
            if record is None:
                continue
            if _reject_macro_location(source_catalog, token.location):
                continue
            source_range = _range_from_location(source_catalog, token.location, name)
            if source_range == record.declaration:
                continue
            occurrence = SymbolOccurrence(source_range, "declaration_dimension")
            occurrence_key = (
                source_range.file,
                source_range.start,
                source_range.end,
                occurrence.provenance,
            )
            occurrences[target_key][occurrence_key] = occurrence

    # Packed aggregate member dimensions are owned by their TypeAliasType.
    # Resolve each bounded syntax token in that alias's lexical parent scope;
    # never infer a parameter record from spelling or owner text.
    for alias in nodes:
        if type(alias).__name__ != "TypeAliasType":
            continue
        scope = getattr(alias, "parentScope", None)
        for token in _packed_aggregate_member_dimension_identifier_tokens(alias):
            name = str(getattr(token, "rawText", ""))
            if not name:
                continue
            target = _scope_lookup_target(scope, token)
            target_key = _parameter_source_key(source_catalog, target)
            if target_key is None or target_key in genvar_keys:
                continue
            record = records.get(target_key)
            if record is None:
                continue
            if _reject_macro_location(source_catalog, token.location):
                continue
            source_range = _range_from_location(source_catalog, token.location, name)
            if source_range == record.declaration:
                continue
            if any(
                occurrence.source_range == source_range
                for occurrence in occurrences[target_key].values()
            ):
                continue
            occurrence = SymbolOccurrence(source_range, "declaration_dimension")
            occurrence_key = (
                source_range.file,
                source_range.start,
                source_range.end,
                occurrence.provenance,
            )
            occurrences[target_key][occurrence_key] = occurrence

    def add_sized_cast_occurrence(token: Any, target: Any) -> None:
        name = str(getattr(token, "rawText", ""))
        if not name:
            return
        target_key = _parameter_source_key(source_catalog, target)
        if target_key is None or target_key in genvar_keys:
            return
        record = records.get(target_key)
        if record is None:
            return
        if _reject_macro_location(source_catalog, token.location):
            return
        source_range = _range_from_location(source_catalog, token.location, name)
        if source_range == record.declaration:
            return
        range_key = (source_range.file, source_range.start, source_range.end)
        for other_key, other_occurrences in occurrences.items():
            if other_key == target_key:
                continue
            if any(
                occurrence.source_range == source_range
                for occurrence in other_occurrences.values()
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "physical sized cast range maps to multiple parameters",
                    file=source_range.file,
                    start=source_range.start,
                )
        for occurrence_key, occurrence in tuple(occurrences[target_key].items()):
            if occurrence.source_range != source_range:
                continue
            del occurrences[target_key][occurrence_key]
        occurrence = SymbolOccurrence(source_range, "sized_cast_type")
        occurrences[target_key][(*range_key, occurrence.provenance)] = occurrence
        special_ranges.add((target_key, range_key))

    # A parameter declaration's default initializer remains source-backed even
    # when elaboration replaces its semantic value with a named override.
    for node in nodes:
        if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Parameter:
            continue
        syntax = getattr(node, "syntax", None)
        syntax_nodes: list[Any] = []
        if syntax is not None and hasattr(syntax, "visit"):
            syntax.visit(syntax_nodes.append)
        for syntax_node in syntax_nodes:
            token = _sized_cast_identifier_token(syntax_node)
            if token is None:
                continue
            target = _scope_lookup_target(getattr(node, "parentScope", None), token)
            add_sized_cast_occurrence(token, target)

    # Body conversions expose a typed CastExpressionSyntax but not a direct
    # semantic target.  Bind their direct identifier through the smallest
    # source-backed semantic scope candidate, then require an existing module
    # parameter record.
    for node in nodes:
        if type(node).__name__ != "ConversionExpression":
            continue
        token = _sized_cast_identifier_token(getattr(node, "syntax", None))
        if token is None:
            continue
        target = _sized_cast_target_from_scopes(source_catalog, nodes, token)
        if target is None:
            continue
        add_sized_cast_occurrence(token, target)

    # An overridden parameter's elaborated value no longer exposes references
    # from its source default. Recover only direct typed identifier tokens from
    # the exact declarator initializer and bind them in that declaration's
    # semantic parent scope to an existing module parameter record.
    for node in nodes:
        if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Parameter:
            continue
        node_key = _parameter_source_key(source_catalog, node)
        if node_key not in records:
            continue
        syntax = getattr(node, "syntax", None)
        if type(syntax).__name__ != "DeclaratorSyntax":
            continue
        initializer = getattr(syntax, "initializer", None)
        if type(initializer).__name__ != "EqualsValueClauseSyntax":
            continue
        scope = getattr(node, "parentScope", None)
        if getattr(scope, "lookupName", None) is None:
            continue
        syntax_nodes: list[Any] = []
        initializer.visit(syntax_nodes.append)
        for syntax_node in syntax_nodes:
            if type(syntax_node).__name__ != "IdentifierNameSyntax":
                continue
            token = getattr(syntax_node, "identifier", None)
            name = str(getattr(token, "rawText", ""))
            location = getattr(token, "location", None)
            if not name or location is None:
                continue
            parent = getattr(syntax_node, "parent", None)
            parent_key = getattr(parent, "key", None)
            key_token = getattr(parent_key, "identifier", None)
            key_location = getattr(key_token, "location", None)
            if (
                type(parent).__name__ == "AssignmentPatternItemSyntax"
                and type(parent_key).__name__ == "IdentifierNameSyntax"
                and key_location is not None
                and key_location.buffer == location.buffer
                and int(key_location.offset) == int(location.offset)
                and str(getattr(key_token, "rawText", "")) == name
            ):
                continue
            target = _scope_lookup_target(scope, token)
            target_key = _parameter_source_key(source_catalog, target)
            if target_key is None or target_key in genvar_keys:
                continue
            record = records.get(target_key)
            if record is None:
                continue
            if _reject_macro_location(source_catalog, location):
                continue
            source_range = _range_from_location(source_catalog, location, name)
            if source_range == record.declaration:
                continue
            for other_key, other_record in records.items():
                if other_key == target_key:
                    continue
                if other_record.declaration == source_range or any(
                    occurrence.source_range == source_range
                    for occurrence in occurrences[other_key].values()
                ):
                    raise SymbolGraphError(
                        "SYMBOL_GRAPH_RANGE_CONFLICT",
                        "physical parameter default range maps to multiple parameters",
                        file=source_range.file,
                        start=source_range.start,
                    )
            if any(
                occurrence.source_range == source_range
                for occurrence in occurrences[target_key].values()
            ):
                continue
            occurrence = SymbolOccurrence(source_range, "parameter_default")
            occurrences[target_key][
                (
                    source_range.file,
                    source_range.start,
                    source_range.end,
                    occurrence.provenance,
                )
            ] = occurrence

    # Dimensions whose semantic expressions are not exposed by PySlang have
    # no bound target evidence. Do not recover them through syntax scanning or
    # owner/name lookup; they remain fail-closed and uncollected.

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
            if _reject_macro_location(source_catalog, name_token.location):
                continue
            target_key = candidate_keys[0]
            source_range = _range_from_location(
                source_catalog, name_token.location, name_token.rawText
            )
            if (
                source_range.file,
                source_range.start,
                source_range.end,
            ) in genvar_keys:
                continue
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

    defparam_owners = _collect_defparam_bindings(
        source_catalog, nodes, owners, records, occurrences
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
    return symbols, defparam_owners


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


@dataclass(frozen=True)
class _SemanticScope:
    file: str
    start: int
    end: int
    owner: str
    kind: str
    name: str
    in_top_closure: bool
    is_selected_top: bool


def _syntax_span(
    source_catalog: SourceCatalog,
    syntax: Any,
) -> tuple[str, int, int]:
    source_range = getattr(syntax, "sourceRange", None)
    start = getattr(source_range, "start", None)
    end = getattr(source_range, "end", None)
    file, start_offset = _location_start(source_catalog, start)
    end_file, end_offset = _location_start(source_catalog, end)
    if file is None or end_file != file or start_offset is None or end_offset is None:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "semantic scope source range is outside the SourceSet",
            file=file,
            start=start_offset,
        )
    if start_offset >= end_offset:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_RANGE_INVALID",
            "semantic scope source range is empty",
            file=file,
            start=start_offset,
        )
    return file, start_offset, end_offset


def _semantic_scopes(
    source_catalog: SourceCatalog,
    nodes: list[Any],
) -> tuple[_SemanticScope, ...]:
    module_by_key = {
        (
            module.declaration.file,
            module.declaration.start,
            module.declaration.end,
        ): module
        for module in source_catalog.modules
    }
    scopes: list[_SemanticScope] = []
    seen_scopes: dict[tuple[str, int, int], _SemanticScope] = {}

    def add_scope(scope: _SemanticScope) -> None:
        key = (scope.file, scope.start, scope.end)
        previous = seen_scopes.get(key)
        if previous is not None:
            if (previous.owner, previous.kind, previous.name) != (
                scope.owner,
                scope.kind,
                scope.name,
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "semantic source scope has multiple owners",
                    file=scope.file,
                    start=scope.start,
                )
            return
        seen_scopes[key] = scope
        scopes.append(scope)

    for node in nodes:
        if type(node).__name__ != "InstanceBodySymbol":
            continue
        definition = getattr(node, "definition", None)
        syntax = getattr(node, "syntax", None)
        if definition is None or syntax is None:
            continue
        declaration = _range_from_location(
            source_catalog,
            definition.location,
            str(definition.name),
            code="SYMBOL_GRAPH_OWNER_MISMATCH",
        )
        file, start, end = _syntax_span(source_catalog, syntax)
        syntax_kind = str(getattr(syntax, "kind", ""))
        if "ModuleDeclaration" in syntax_kind:
            module = module_by_key.get(
                (declaration.file, declaration.start, declaration.end)
            )
            if module is None:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "semantic module scope is not in SourceCatalog",
                    file=declaration.file,
                    start=declaration.start,
                )
            add_scope(
                _SemanticScope(
                    file,
                    start,
                    end,
                    module.owner_id,
                    "module",
                    str(definition.name),
                    module.in_top_closure,
                    module.is_selected_top,
                )
            )
        elif "InterfaceDeclaration" in syntax_kind:
            owner = f"interface:{declaration.file}:{declaration.start}:{declaration.end}"
            in_closure = declaration.file in source_catalog.source_set.top_closure_files
            add_scope(
                _SemanticScope(
                    file,
                    start,
                    end,
                    owner,
                    "interface",
                    str(definition.name),
                    in_closure,
                    False,
                )
            )
    return tuple(sorted(scopes, key=lambda item: (item.file, item.start, item.end, item.owner)))


def _macro_owner_evidence_for(
    source_catalog: SourceCatalog,
    nodes: list[Any],
) -> _MacroOwnerEvidence:
    """Prove ordinary physical owners for all macro-backed semantic locations."""

    scopes = _semantic_scopes(source_catalog, nodes)
    module_spans = tuple(
        _NestedModuleSpan(
            scope.owner,
            SourceRange(scope.file, scope.start, scope.end),
        )
        for scope in scopes
        if scope.kind == "module"
    )
    locations: list[Any] = []

    def collect(location: Any) -> None:
        if location is None:
            return
        if source_catalog.catalog_source_manager.isMacroLoc(location):
            locations.append(location)

    for node in nodes:
        collect(getattr(node, "location", None))
        syntax = getattr(node, "syntax", None)
        source_range = getattr(syntax, "sourceRange", None)
        collect(getattr(source_range, "start", None))
        collect(getattr(source_range, "end", None))
        if syntax is not None and hasattr(syntax, "visit"):
            syntax_nodes: list[Any] = []
            syntax.visit(syntax_nodes.append)
            for syntax_node in syntax_nodes:
                syntax_range = getattr(syntax_node, "sourceRange", None)
                collect(getattr(syntax_range, "start", None))
                collect(getattr(syntax_range, "end", None))
                if hasattr(syntax_node, "visit"):
                    for token in _syntax_identifier_tokens(syntax_node):
                        collect(getattr(token, "location", None))
        if type(node).__name__ == "InstanceSymbol":
            parent = getattr(syntax, "parent", None)
            collect(getattr(getattr(parent, "type", None), "location", None))

    macro_owner_ids: set[str] = set()
    for location in locations:
        try:
            expanded = source_catalog.catalog_source_manager.getFullyExpandedLoc(
                location
            )
        except (AttributeError, RuntimeError, ValueError) as error:
            file, start = _location_start(source_catalog, location)
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "macro location has no fully expanded physical location",
                file=file,
                start=start,
            ) from error
        file, offset = _location_start(source_catalog, expanded)
        matches = [
            span
            for span in module_spans
            if span.source_range.file == file
            and offset is not None
            and span.source_range.start <= offset < span.source_range.end
        ]
        if len(matches) != 1:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "macro expanded location does not map to one physical module owner",
                file=file,
                start=offset,
            )
        macro_owner_ids.add(matches[0].owner_id)

    return _MacroOwnerEvidence(
        source_catalog.catalog_source_manager,
        tuple(sorted(module_spans, key=lambda span: (span.source_range.file, span.source_range.start, span.source_range.end, span.owner_id))),
        frozenset(macro_owner_ids),
    )


def _scope_at(
    scopes: tuple[_SemanticScope, ...],
    file: str | None,
    offset: int | None,
) -> _SemanticScope | None:
    if file is None or offset is None:
        return None
    matches = [
        scope
        for scope in scopes
        if scope.file == file and scope.start <= offset < scope.end
    ]
    return min(matches, key=lambda item: (item.end - item.start, item.start, item.owner)) if matches else None


def _record_range(
    source_catalog: SourceCatalog,
    node: Any,
    name: str | None = None,
) -> SourceRange:
    value = str(name if name is not None else getattr(node, "name", ""))
    if not value:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_SOURCE_INVALID",
            "semantic symbol has no source identifier",
        )
    if _reject_macro_location(source_catalog, getattr(node, "location", None)):
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "macro-backed semantic symbol has no physical declaration token",
        )
    return _range_from_location(source_catalog, node.location, value)


def _token_source_range(
    source_catalog: SourceCatalog,
    token: Any,
    name: str,
) -> SourceRange | None:
    if token is None or getattr(token, "rawText", "") != name:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_SOURCE_INVALID",
            f"semantic token does not match bound symbol: token={getattr(token, 'rawText', None)!r} name={name!r} offset={getattr(getattr(token, 'location', None), 'offset', None)}",
        )
    if _reject_macro_location(source_catalog, token.location):
        return None
    return _range_from_location(source_catalog, token.location, name)


def _collect_extended_symbols(
    source_catalog: SourceCatalog,
    existing: list[SourceSymbol],
) -> list[SourceSymbol]:
    """Collect the remaining categories from the compiled PySlang semantic tree."""

    nodes: list[Any] = []
    source_catalog.catalog_root.visit(nodes.append)
    nodes = [
        node
        for node in nodes
        if not _reject_macro_location(
            source_catalog, getattr(node, "location", None)
        )
    ]
    scopes = _semantic_scopes(source_catalog, nodes)
    physical_files = _physical_files(source_catalog)
    top_closure_files = set(source_catalog.source_set.top_closure_files)
    abi_categories = {
        "parameters",
        "typedefs",
        "struct_types",
        "struct_fields",
        "union_fields",
        "modules",
        "ports",
        "interfaces",
        "interface_instances",
        "interface_ports",
        "modports",
    }
    aggregate_categories = {
        "typedefs",
        "struct_types",
        "struct_fields",
        "union_fields",
    }

    occupied: dict[tuple[str, int, int], object] = {}
    for symbol in existing:
        for source_range in (
            symbol.declaration,
            *(occurrence.source_range for occurrence in symbol.occurrences),
        ):
            key = (source_range.file, source_range.start, source_range.end)
            if key in occupied:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    f"existing semantic symbols have a repeated physical range: {symbol.symbol_id} conflicts with {occupied[key]}",
                    file=source_range.file,
                    start=source_range.start,
                )
            occupied[key] = symbol.symbol_id

    records: list[dict[str, Any]] = []
    declaration_records: dict[tuple[str, int, int], dict[str, Any]] = {}
    target_records: dict[tuple[str, int, int], dict[str, Any]] = {}
    module_records: dict[str, dict[str, Any]] = {}
    module_records_by_declaration: dict[tuple[str, int, int], dict[str, Any]] = {}
    interface_records: dict[str, dict[str, Any]] = {}
    modport_records: dict[tuple[str, str], dict[str, Any]] = {}
    port_records: dict[tuple[str, str], dict[str, Any]] = {}
    field_records_by_alias: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    field_records_by_owner: dict[tuple[str, str], dict[str, Any]] = {}
    alias_records: list[tuple[Any, dict[str, Any]]] = []
    alias_contexts: dict[tuple[str, int, int], _SemanticScope | None] = {}
    existing_by_declaration = {
        (symbol.declaration.file, symbol.declaration.start, symbol.declaration.end): symbol
        for symbol in existing
    }

    def context_for(node: Any) -> _SemanticScope | None:
        file, offset = _location_start(
            source_catalog, getattr(node, "location", None)
        )
        return _scope_at(scopes, file, offset)

    def classify(
        category: str,
        context: _SemanticScope | None,
        declaration: SourceRange,
    ) -> tuple[str, str, str, str | None]:
        if category in aggregate_categories and context is not None and context.kind == "module":
            # A type/field declared inside one module is module-local even when
            # the module itself is in a selected top closure.  Only a
            # compilation-unit/shared aggregate or an interface-owned type is
            # part of the module ABI.
            return "local", "internal", "eligible", None
        if category not in abi_categories:
            return "local", "internal", "eligible", None
        if source_catalog.source_set.top is None:
            return "cross_module", "module_abi", "preserved", "module_abi_requires_top"
        if context is not None and context.is_selected_top:
            return "cross_module", "top_boundary", "preserved", "selected_top_boundary"
        if context is not None and context.in_top_closure:
            return "cross_module", "module_abi", "eligible", None
        if declaration.file in top_closure_files:
            return "cross_module", "module_abi", "eligible", None
        return "cross_module", "module_abi", "preserved", "outside_top_closure"

    def add_record(
        *,
        category: str,
        name: str,
        declaration: SourceRange,
        owner: str,
        context: _SemanticScope | None,
        field_scope: object | None = None,
    ) -> dict[str, Any]:
        key = (declaration.file, declaration.start, declaration.end)
        previous = declaration_records.get(key)
        if previous is not None:
            if (previous["category"], previous["name"], previous["owner"]) != (
                category,
                name,
                owner,
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "semantic declarations have multiple owners",
                    file=declaration.file,
                    start=declaration.start,
                )
            return previous
        if key in occupied:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "semantic declarations have an exact duplicate or multiple owners",
                file=declaration.file,
                start=declaration.start,
            )
        if any(
            file == declaration.file
            and start < declaration.end
            and declaration.start < end
            for file, start, end in occupied
        ):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "semantic declarations partially overlap another owner",
                file=declaration.file,
                start=declaration.start,
            )
        impact, abi, support, reason = classify(category, context, declaration)
        record: dict[str, Any] = {
            "category": category,
            "name": name,
            "declaration": declaration,
            "owner": owner,
            "impact": impact,
            "abi": abi,
            "support": support,
            "reason": reason,
            "occurrences": {},
            "occurrence_ranges": {},
            "ranges": {key},
        }
        records.append(record)
        declaration_records[key] = record
        occupied[key] = record
        if category == "modules":
            module_records[name] = record
            module_records_by_declaration[key] = record
        elif category == "interfaces":
            interface_records[name] = record
        elif category in {"ports", "interface_ports"} and context is not None:
            port_records[(context.name, name)] = record
        if field_scope is not None:
            field_records_by_owner[(str(owner), name)] = record
        return record

    def add_occurrence(
        record: dict[str, Any],
        source_range: SourceRange | None,
        provenance: str,
    ) -> None:
        if source_range is None:
            return
        key = (source_range.file, source_range.start, source_range.end)
        declaration_key = (
            record["declaration"].file,
            record["declaration"].start,
            record["declaration"].end,
        )
        if key == declaration_key:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "semantic occurrence overlaps its declaration range",
                file=source_range.file,
                start=source_range.start,
            )
        previous = record["occurrence_ranges"].get(key)
        if previous is not None:
            # Repeated elaboration may expose one source identity through
            # different semantic paths.  The record already proves the same
            # owner and physical range, so retain the first stable provenance
            # instead of manufacturing a duplicate occurrence.  A different
            # record is still rejected by the occupied-range audit below.
            return
        owner = occupied.get(key)
        if owner is not None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                f"semantic occurrence overlaps another symbol range {key}: {record['category']}:{record['name']} conflicts with {owner!r}",
                file=source_range.file,
                start=source_range.start,
            )
        if any(
            file == source_range.file
            and start < source_range.end
            and source_range.start < end
            for file, start, end in occupied
        ):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "semantic occurrence partially overlaps another symbol range",
                file=source_range.file,
                start=source_range.start,
            )
        occurrence = SymbolOccurrence(source_range, provenance)
        record["occurrences"][
            (source_range.file, source_range.start, source_range.end, provenance)
        ] = occurrence
        record["occurrence_ranges"][key] = occurrence
        record["ranges"].add(key)
        occupied[key] = record

    def target_key(target: Any) -> tuple[str, int, int] | None:
        if target is None:
            return None
        try:
            declaration = _record_range(source_catalog, target)
        except (AttributeError, SymbolGraphError):
            return None
        return declaration.file, declaration.start, declaration.end

    def add_target(target: Any, record: dict[str, Any]) -> None:
        key = target_key(target)
        if key is not None:
            target_records[key] = record

    def record_for_target(target: Any) -> dict[str, Any] | None:
        if target is None:
            return None
        key = target_key(target)
        record = target_records.get(key) if key is not None else None
        if record is not None:
            return record
        try:
            declaration = _record_range(source_catalog, target)
        except (AttributeError, SymbolGraphError):
            return None
        return declaration_records.get(
            (declaration.file, declaration.start, declaration.end)
        )

    # Definitions and scopes are semantic objects, not lexical declarations.
    for scope in scopes:
        declaration = SourceRange(
            scope.file,
            next(
                module.declaration.start
                for module in source_catalog.modules
                if module.owner_id == scope.owner
            )
            if scope.kind == "module"
            else _record_range(
                source_catalog,
                next(
                    node
                    for node in nodes
                    if type(node).__name__ == "InstanceBodySymbol"
                    and str(getattr(getattr(node, "definition", None), "name", ""))
                    == scope.name
                    and _scope_at(
                        scopes,
                        *_location_start(
                            source_catalog,
                            getattr(getattr(node, "definition", None), "location", None),
                        ),
                    )
                    == scope
                ).definition,
            ).start,
            0,
        )
        declaration = _record_range(
            source_catalog,
            next(
                node
                for node in nodes
                if type(node).__name__ == "InstanceBodySymbol"
                and str(getattr(getattr(node, "definition", None), "name", ""))
                == scope.name
                and _scope_at(
                    scopes,
                    *_location_start(
                        source_catalog,
                        getattr(getattr(node, "definition", None), "location", None),
                    ),
                )
                == scope
            ).definition,
        )
        record = add_record(
            category="modules" if scope.kind == "module" else "interfaces",
            name=scope.name,
            declaration=declaration,
            owner=scope.owner,
            context=scope,
        )
        if scope.kind == "module":
            module_records[scope.name] = record
        else:
            interface_records[scope.name] = record

    module_owners_by_declaration = _module_owner_map(source_catalog)
    for node in nodes:
        if type(node).__name__ != "InstanceBodySymbol":
            continue
        definition = getattr(node, "definition", None)
        definition_key = _module_definition_key(source_catalog, definition)
        if definition_key is None:
            continue
        syntax = getattr(definition, "syntax", None)
        if not isinstance(syntax, pyslang.syntax.ModuleDeclarationSyntax):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "semantic module definition is not a physical module declaration",
                file=definition_key[0],
                start=definition_key[1],
            )
        record = module_records_by_declaration.get(definition_key)
        physical_owner = module_owners_by_declaration.get(definition_key)
        if (
            record is None
            or physical_owner is None
            or record["category"] != "modules"
            or record["name"] != str(getattr(definition, "name", ""))
            or record["declaration"] != physical_owner.declaration
            or record["owner"] != physical_owner.owner_id
        ):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "semantic module definition does not match its catalog module record",
                file=definition_key[0],
                start=definition_key[1],
            )
        block_name = getattr(syntax, "blockName", None)
        if block_name is None:
            continue
        token = getattr(block_name, "name", None)
        if token is None or bool(getattr(token, "isMissing", False)):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_SOURCE_INVALID",
                "module closing label has no physical identifier token",
                file=definition_key[0],
                start=definition_key[1],
            )
        add_occurrence(
            record,
            _token_source_range(source_catalog, token, record["name"]),
            "semantic_module_end_label",
        )

    # Type aliases and aggregate fields are bound by TypeAliasType/canonicalType.
    alias_nodes: list[Any] = [
        node for node in nodes if type(node).__name__ == "TypeAliasType"
    ]
    for node in alias_nodes:
        declaration = _record_range(source_catalog, node)
        owner = f"type:{declaration.file}:{declaration.start}:{declaration.end}"
        context = context_for(node)
        category = "struct_types" if getattr(node, "isStruct", False) or getattr(node, "isPackedUnion", False) else "typedefs"
        record = add_record(
            category=category,
            name=str(node.name),
            declaration=declaration,
            owner=owner,
            context=context,
        )
        alias_records.append((node, record))
        alias_key = (
            record["declaration"].file,
            record["declaration"].start,
            record["declaration"].end,
        )
        alias_contexts[alias_key] = context
        add_target(node, record)
        add_target(getattr(node, "targetType", None), record)
        canonical = getattr(node, "canonicalType", None)
        syntax = getattr(canonical, "syntax", None)
        if syntax is None or not hasattr(syntax, "members"):
            continue
        field_category = "union_fields" if getattr(node, "isPackedUnion", False) else "struct_fields"
        field_scope = True
        for member in getattr(syntax, "members", ()):
            for declarator in getattr(member, "declarators", ()):
                token = getattr(declarator, "name", None)
                name = getattr(token, "rawText", "")
                if not name:
                    raise SymbolGraphError(
                        "SYMBOL_GRAPH_SOURCE_INVALID",
                        "aggregate field has no semantic declaration token",
                    )
                field_range = _token_source_range(source_catalog, token, name)
                if field_range is None:
                    continue
                field_record = add_record(
                    category=field_category,
                    name=name,
                    declaration=field_range,
                    owner=owner,
                    context=context,
                    field_scope=field_scope,
                )
                field_records_by_alias[(*alias_key, name)] = field_record

    aliases_by_name: dict[str, list[tuple[Any, dict[str, Any]]]] = {}
    for alias_node, alias_record in alias_records:
        aliases_by_name.setdefault(str(alias_node.name), []).append(
            (alias_node, alias_record)
        )

    def resolve_alias_token(token: Any) -> dict[str, Any] | None:
        name = str(getattr(token, "rawText", ""))
        candidates = aliases_by_name.get(name, [])
        if not candidates:
            return None
        file, offset = _location_start(source_catalog, getattr(token, "location", None))
        context = _scope_at(scopes, file, offset)
        if context is not None:
            scoped = [
                record
                for alias_node, record in candidates
                if alias_contexts.get(
                    (
                        record["declaration"].file,
                        record["declaration"].start,
                        record["declaration"].end,
                    )
                ) is not None
                and alias_contexts[
                    (
                        record["declaration"].file,
                        record["declaration"].start,
                        record["declaration"].end,
                    )
                ].owner == context.owner
            ]
            if len(scoped) == 1:
                return scoped[0]
        unit = [
            record
            for alias_node, record in candidates
            if alias_contexts.get(
                (
                    record["declaration"].file,
                    record["declaration"].start,
                    record["declaration"].end,
                )
            ) is None
        ]
        if len(unit) == 1:
            return unit[0]
        if len(candidates) == 1:
            return candidates[0][1]
        raise SymbolGraphError(
            "SYMBOL_GRAPH_OWNER_MISMATCH",
            "type reference resolves to multiple semantic aliases",
            file=file,
            start=offset,
        )

    def add_type_reference(token: Any, provenance: str) -> None:
        record = resolve_alias_token(token)
        if record is None:
            return
        name = str(record["name"])
        if getattr(token, "rawText", "") != name:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_SOURCE_INVALID",
                "semantic type reference does not match its bound alias",
            )
        add_occurrence(
            record,
            _token_source_range(source_catalog, token, name),
            provenance,
        )

    # Casts retain their semantic TypeAliasType. Only the direct type field
    # is accepted as source evidence; a missing field is fail-closed.
    for node in nodes:
        if type(node).__name__ != "ConversionExpression":
            continue
        semantic_type = getattr(node, "type", None)
        if type(semantic_type).__name__ != "TypeAliasType":
            continue
        alias_name = str(getattr(semantic_type, "name", "")).rsplit(".", 1)[-1]
        syntax = getattr(node, "syntax", None)
        if _is_builtin_keyword_cast_conversion(node):
            continue
        token = _direct_expression_identifier(getattr(syntax, "left", None))
        if token is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "semantic cast has no direct type identifier token",
                file=_syntax_start(source_catalog, node)[0],
                start=_syntax_start(source_catalog, node)[1],
            )
        if getattr(token, "rawText", "") != alias_name:
            file, offset = _location_start(source_catalog, token.location)
            raise SymbolGraphError(
                "SYMBOL_GRAPH_SOURCE_INVALID",
                "semantic cast type token does not match its bound alias",
                file=file,
                start=offset,
            )
        add_type_reference(token, "semantic_cast_type")

    def alias_record_for_declared(declared: Any) -> dict[str, Any] | None:
        if declared is not None:
            try:
                declared_range = _record_range(source_catalog, declared)
            except (AttributeError, SymbolGraphError):
                declared_range = None
            if declared_range is not None:
                for alias_node, record in alias_records:
                    try:
                        if _record_range(source_catalog, alias_node) == declared_range:
                            return record
                    except (AttributeError, SymbolGraphError):
                        continue
        return next(
            (
                record
                for alias_node, record in alias_records
                if declared is getattr(alias_node, "targetType", None)
                or (
                    declared is not None
                    and getattr(declared, "type", None)
                    is getattr(getattr(alias_node, "targetType", None), "type", None)
                )
            ),
            None,
        )

    # Named aggregate members are semantic syntax owned by the alias that
    # declares them.  Record their referenced alias type token before the
    # member declaration records consume the same syntax tree.
    for alias_node, alias_record in alias_records:
        canonical = getattr(alias_node, "canonicalType", None)
        syntax = getattr(canonical, "syntax", None)
        for member in getattr(syntax, "members", ()) if syntax is not None else ():
            data_type = getattr(member, "type", None)
            token = getattr(getattr(data_type, "name", None), "identifier", None)
            if token is not None:
                add_type_reference(token, "semantic_type")

    # Enum values are TransparentMemberSymbols wrapping semantic EnumValue symbols.
    for node in nodes:
        if type(node).__name__ != "TransparentMemberSymbol":
            continue
        wrapped = getattr(node, "wrapped", None)
        if getattr(wrapped, "kind", None) != getattr(pyslang.ast.SymbolKind, "EnumValue", None):
            continue
        name = str(getattr(node, "name", ""))
        record = add_record(
            category="enum_values",
            name=name,
            declaration=_record_range(source_catalog, node),
            owner=(context_for(node).owner if context_for(node) is not None else "$unit"),
            context=context_for(node),
        )
        add_target(node, record)
        add_target(wrapped, record)

    # Subroutines and formal arguments are semantic symbols with source syntax.
    for node in nodes:
        if type(node).__name__ != "SubroutineSymbol":
            continue
        declaration = _record_range(source_catalog, node)
        owner = f"subroutine:{declaration.file}:{declaration.start}:{declaration.end}"
        context = context_for(node)
        syntax_kind = str(getattr(getattr(node, "syntax", None), "kind", ""))
        category = "tasks" if "TaskDeclaration" in syntax_kind else "functions"
        function_record = add_record(
            category=category,
            name=str(node.name),
            declaration=declaration,
            owner=owner,
            context=context,
        )
        add_target(node, function_record)
        add_target(getattr(node, "returnValVar", None), function_record)
        prototype = getattr(getattr(node, "syntax", None), "prototype", None)
        return_type = getattr(prototype, "returnType", None)
        return_token = getattr(
            getattr(return_type, "name", None), "identifier", None
        )
        if return_token is not None:
            add_type_reference(return_token, "semantic_return_type")
        for argument in getattr(node, "arguments", ()):
            argument_record = add_record(
                category="arguments",
                name=str(argument.name),
                declaration=_record_range(source_catalog, argument),
                owner=owner,
                context=context,
            )
            add_target(argument, argument_record)

    # Elaborated generate arrays, ports, interface fields, modports, and instances.
    for node in nodes:
        node_type = type(node).__name__
        context = context_for(node)
        if node_type == "GenerateBlockArraySymbol":
            syntax = getattr(node, "syntax", None)
            file, start, end = _syntax_span(source_catalog, syntax)
            owner = f"generate:{file}:{start}:{end}"
            name = str(node.name)
            try:
                declaration = _record_range(source_catalog, node)
            except SymbolGraphError as error:
                if (
                    error.code == "SYMBOL_GRAPH_RANGE_INVALID"
                    and name.startswith("genblk")
                ):
                    # PySlang's generated genblkN has no declaration token.
                    # Keep its syntax span as semantic owner evidence, but do
                    # not create a fabricated rename record.
                    continue
                raise
            record = add_record(
                category="generate_blocks",
                name=name,
                declaration=declaration,
                owner=owner,
                context=context,
            )
            add_target(node, record)
            continue
        if node_type in {"PortSymbol", "InterfacePortSymbol"}:
            if context is None:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "semantic port has no enclosing source owner",
                    file=_location_start(source_catalog, node.location)[0],
                    start=_location_start(source_catalog, node.location)[1],
                )
            category = "interface_ports" if (
                context.kind == "interface" or node_type == "InterfacePortSymbol"
            ) else "ports"
            record = add_record(
                category=category,
                name=str(node.name),
                declaration=_record_range(source_catalog, node),
                owner=context.owner,
                context=context,
            )
            add_target(node, record)
            add_target(getattr(node, "internalSymbol", None), record)
            parent = getattr(getattr(node, "syntax", None), "parent", None)
            header = getattr(parent, "header", None)
            interface_token = getattr(header, "nameOrKeyword", None)
            interface_record = interface_records.get(
                getattr(interface_token, "rawText", "")
            )
            if interface_record is not None and interface_token is not None:
                add_occurrence(
                    interface_record,
                    _token_source_range(
                        source_catalog,
                        interface_token,
                        interface_record["name"],
                    ),
                    "semantic_interface_type",
                )
                modport_clause = getattr(header, "modport", None)
                modport_token = getattr(modport_clause, "member", None)
                modport_record = modport_records.get(
                    (interface_record["owner"], getattr(modport_token, "rawText", ""))
                )
                if modport_record is not None and modport_token is not None:
                    add_occurrence(
                        modport_record,
                        _token_source_range(
                            source_catalog,
                            modport_token,
                            modport_record["name"],
                        ),
                        "semantic_modport_type",
                    )
            data_type = getattr(header, "dataType", None)
            token = getattr(getattr(data_type, "name", None), "identifier", None)
            data_interface_record = interface_records.get(
                getattr(token, "rawText", "") if token is not None else ""
            )
            if data_interface_record is not None and token is not None:
                add_occurrence(
                    data_interface_record,
                    _token_source_range(source_catalog, token, data_interface_record["name"]),
                    "semantic_type",
                )
            if token is not None:
                add_type_reference(token, "semantic_port_type")
            continue
        if node_type in {"VariableSymbol", "NetSymbol"} and context is not None and context.kind == "interface":
            record = add_record(
                category="interface_ports",
                name=str(node.name),
                declaration=_record_range(source_catalog, node),
                owner=context.owner,
                context=context,
                field_scope=True,
            )
            add_target(node, record)
            continue
        if node_type == "ModportSymbol":
            if context is None or context.kind != "interface":
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "modport has no enclosing interface owner",
                )
            record = add_record(
                category="modports",
                name=str(node.name),
                declaration=_record_range(source_catalog, node),
                owner=context.owner,
                context=context,
            )
            add_target(node, record)
            modport_records[(str(context.owner), str(node.name))] = record
            continue
        if node_type == "ModportPortSymbol":
            if context is None:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "modport port has no enclosing interface owner",
                )
            target = getattr(node, "internalSymbol", None)
            target_record = record_for_target(target)
            if target_record is None:
                target_record = field_records_by_owner.get(
                    (str(context.owner), str(node.name))
                )
            if target_record is not None:
                add_target(node, target_record)
                add_occurrence(
                    target_record,
                    _record_range(source_catalog, node),
                    "semantic_modport",
                )
            continue
        if node_type == "InstanceSymbol" and getattr(node, "syntax", None) is not None:
            if not getattr(node, "isModule", False) and not getattr(node, "isInterface", False):
                continue
            category = "interface_instances" if getattr(node, "isInterface", False) else "instances"
            record = add_record(
                category=category,
                name=str(node.name),
                declaration=_record_range(source_catalog, node),
                owner=context.owner if context is not None else "$unit",
                context=context,
            )
            add_target(node, record)

    # Interface-port headers can be visited before their ModportSymbol
    # declarations.  Resolve the already-registered interface/modport owners
    # in a second semantic pass so the header binding is never guessed from
    # plain text.
    for node in nodes:
        if type(node).__name__ != "InterfacePortSymbol":
            continue
        parent = getattr(getattr(node, "syntax", None), "parent", None)
        header = getattr(parent, "header", None)
        interface_token = getattr(header, "nameOrKeyword", None)
        interface_record = interface_records.get(
            getattr(interface_token, "rawText", "")
        )
        modport_clause = getattr(header, "modport", None)
        modport_token = getattr(modport_clause, "member", None)
        if interface_record is None or modport_token is None:
            continue
        modport_record = modport_records.get(
            (interface_record["owner"], getattr(modport_token, "rawText", ""))
        )
        if modport_record is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "interface port modport is not in the semantic interface owner",
                file=_location_start(source_catalog, modport_token.location)[0],
                start=_location_start(source_catalog, modport_token.location)[1],
            )
        add_occurrence(
            modport_record,
            _token_source_range(
                source_catalog,
                modport_token,
                modport_record["name"],
            ),
            "semantic_modport_type",
        )

    def add_scoped_member_fields(access_node: Any, syntax: Any) -> None:
        if type(syntax).__name__ != "ScopedNameSyntax":
            return
        right = getattr(syntax, "right", None)
        token = getattr(right, "identifier", None)
        base_value = getattr(access_node, "value", None)
        declared = getattr(
            getattr(getattr(base_value, "type", None), "declaredType", None),
            "type",
            None,
        )
        if declared is None:
            declared = getattr(base_value, "type", None)
        alias_record = alias_record_for_declared(
            getattr(base_value, "type", None)
        )
        field_record = field_records_by_alias.get(
            (
                alias_record["declaration"].file,
                alias_record["declaration"].start,
                alias_record["declaration"].end,
                getattr(token, "rawText", ""),
            )
        ) if alias_record is not None else None
        if field_record is not None and token is not None:
            add_occurrence(
                field_record,
                _token_source_range(source_catalog, token, field_record["name"]),
                "semantic_member",
            )
        left = getattr(syntax, "left", None)
        if type(left).__name__ == "ScopedNameSyntax":
            add_scoped_member_fields(base_value, left)

    # Semantic references: named values, member access, type uses, and hierarchy names.
    for node in nodes:
        node_type = type(node).__name__
        target = getattr(node, "symbol", None)
        target_record = record_for_target(target)
        if node_type == "HierarchicalValueExpression":
            syntax = getattr(node, "syntax", None)
            left = getattr(syntax, "left", None)
            right = getattr(syntax, "right", None)
            right_token = getattr(right, "identifier", None)
            field_record = record_for_target(target)
            if field_record is not None and right_token is not None:
                add_occurrence(
                    field_record,
                    _token_source_range(
                        source_catalog, right_token, field_record["name"]
                    ),
                    "semantic_hierarchical_member",
                )
            member_file, member_start = _syntax_start(source_catalog, node)
            member_context = _scope_at(scopes, member_file, member_start)
            left_token = getattr(left, "identifier", None)
            port_record = port_records.get(
                (member_context.name, getattr(left_token, "rawText", ""))
            ) if member_context is not None else None
            if port_record is not None and left_token is not None:
                add_occurrence(
                    port_record,
                    _token_source_range(
                        source_catalog, left_token, port_record["name"]
                    ),
                    "semantic_hierarchical_base",
                )
        if node_type == "NamedValueExpression" and target_record is not None:
            token = getattr(getattr(node, "syntax", None), "identifier", None)
            if token is not None:
                if getattr(token, "rawText", "") != target_record["name"]:
                    file, offset = _location_start(source_catalog, token.location)
                    raise SymbolGraphError(
                        "SYMBOL_GRAPH_SOURCE_INVALID",
                        f"named value target/token mismatch: target={getattr(target, 'name', None)!r} record={target_record['name']!r} token={getattr(token, 'rawText', None)!r}",
                        file=file,
                        start=offset,
                    )
                source_range = _token_source_range(
                    source_catalog, token, target_record["name"]
                )
            else:
                source_range = _expression_range(
                    source_catalog, node, target_record["name"]
                )
            if source_range != target_record["declaration"]:
                add_occurrence(
                    target_record,
                    source_range,
                    "semantic_reference",
                )
        if node_type == "CallExpression":
            subroutine = getattr(node, "subroutine", None)
            call_record = record_for_target(subroutine)
            syntax = getattr(node, "syntax", None)
            token = getattr(syntax, "identifier", None)
            if token is None:
                token = getattr(getattr(syntax, "left", None), "identifier", None)
            if call_record is not None and token is not None:
                source_range = _token_source_range(
                    source_catalog, token, call_record["name"]
                )
                if source_range is None:
                    continue
                key = (source_range.file, source_range.start, source_range.end)
                if key not in call_record["occurrence_ranges"]:
                    add_occurrence(call_record, source_range, "semantic_call")
        if node_type == "MemberAccessExpression":
            member = getattr(node, "member", None)
            member_name = str(getattr(member, "name", ""))
            base_value = getattr(node, "value", None)
            base = getattr(base_value, "symbol", None)
            member_record = record_for_target(member)
            member_file, member_start = _syntax_start(source_catalog, node)
            member_context = _scope_at(scopes, member_file, member_start)
            declared_base = getattr(
                getattr(base, "type", None), "declaredType", None
            )
            if declared_base is None:
                declared_base = getattr(
                    getattr(base_value, "type", None), "declaredType", None
                )
            if declared_base is None:
                declared_base = getattr(base_value, "type", None)
            alias_record = alias_record_for_declared(declared_base)
            field_record = field_records_by_alias.get(
                (
                    alias_record["declaration"].file,
                    alias_record["declaration"].start,
                    alias_record["declaration"].end,
                    member_name,
                )
            ) if alias_record is not None else None
            if field_record is None:
                field_record = member_record
            if field_record is None and base is not None:
                definition = getattr(base, "definition", None)
                interface_name = str(getattr(definition, "name", ""))
                interface_record = interface_records.get(interface_name)
                if interface_record is not None:
                    field_record = field_records_by_owner.get(
                        (f"interface:{interface_record['declaration'].file}:"
                         f"{interface_record['declaration'].start}:"
                         f"{interface_record['declaration'].end}", member_name)
                    )
            if member_context is not None:
                left = getattr(getattr(node, "syntax", None), "left", None)
                left_token = getattr(left, "identifier", None)
                port_record = port_records.get(
                    (member_context.name, getattr(left_token, "rawText", ""))
                )
                if port_record is not None and left_token is not None:
                    add_occurrence(
                        port_record,
                        _token_source_range(
                            source_catalog,
                            left_token,
                            port_record["name"],
                        ),
                        "semantic_member_base",
                    )
            base_record = record_for_target(base)
            if base_record is not None:
                left = getattr(getattr(node, "syntax", None), "left", None)
                left_token = getattr(left, "identifier", None)
                if left_token is not None:
                    add_occurrence(
                        base_record,
                        _token_source_range(
                            source_catalog, left_token, base_record["name"]
                        ),
                        "semantic_member_base",
                    )
            token = _direct_member_identifier(getattr(node, "syntax", None))
            if (
                field_record is not None
                and token is not None
                and getattr(token, "rawText", "") == field_record["name"]
            ):
                add_occurrence(
                    field_record,
                    _token_source_range(source_catalog, token, field_record["name"]),
                    "semantic_member",
                )
            syntax = getattr(node, "syntax", None)
            if syntax is not None:
                add_scoped_member_fields(node, syntax)
        declared = getattr(getattr(node, "type", None), "declaredType", None)
        alias_record = alias_record_for_declared(declared)
        syntax_node = getattr(node, "syntax", None)
        syntax = getattr(syntax_node, "parent", None)
        data_type = getattr(syntax, "type", None)
        if data_type is None:
            data_type = getattr(syntax, "dataType", None)
        type_token = getattr(getattr(data_type, "name", None), "identifier", None)
        if type_token is not None:
            add_type_reference(type_token, "semantic_type")
        if alias_record is not None:
            # The semantic type token was already added above.  Keep the
            # declared-type binding as an explicit fail-closed check.
            if type_token is not None and getattr(type_token, "rawText", "") != alias_record["name"]:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_SOURCE_INVALID",
                    "declared type token does not match its semantic alias",
                )
        if node_type == "InstanceSymbol" and getattr(node, "syntax", None) is not None:
            parent = getattr(node.syntax, "parent", None)
            token = getattr(parent, "type", None)
            target_name = getattr(token, "rawText", "")
            target_definition = getattr(getattr(node, "definition", None), "name", target_name)
            target_record = (
                interface_records.get(str(target_definition))
                if getattr(node, "isInterface", False)
                else module_records.get(str(target_definition))
            )
            if token is not None:
                if _reject_macro_location(source_catalog, getattr(token, "location", None)):
                    evidence = _active_macro_owner_evidence.get()
                    if evidence is None:
                        raise SymbolGraphError(
                            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                            "macro hierarchy occurrence has no owner evidence",
                        )
                    definition = getattr(node, "definition", None)
                    definition_key = _module_definition_key(
                        source_catalog, definition
                    )
                    if getattr(node, "isInterface", False) or definition_key is None:
                        raise SymbolGraphError(
                            "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                            "macro hierarchy target is not an ordinary physical module",
                        )
                    target_record = module_records_by_declaration.get(definition_key)
                    physical_owner = _module_owner_map(source_catalog).get(definition_key)
                    if target_record is None or physical_owner is None:
                        raise SymbolGraphError(
                            "SYMBOL_GRAPH_OWNER_MISMATCH",
                            "macro hierarchy target cannot map to a catalog module owner",
                        )
                    if (
                        target_record["category"] != "modules"
                        or target_record["declaration"] != physical_owner.declaration
                        or target_record["owner"] != physical_owner.owner_id
                    ):
                        raise SymbolGraphError(
                            "SYMBOL_GRAPH_OWNER_MISMATCH",
                            "macro hierarchy target record does not match its catalog module owner",
                        )
                    evidence.target_owner_ids.add(physical_owner.owner_id)
                elif target_record is not None:
                    add_occurrence(
                        target_record,
                        _token_source_range(source_catalog, token, target_record["name"]),
                        "semantic_hierarchy",
                    )
            target_scope_name = str(target_definition)
            for connection in getattr(node.syntax, "connections", ()):
                if type(connection).__name__ != "NamedPortConnectionSyntax":
                    continue
                name_token = getattr(connection, "name", None)
                port_record = port_records.get(
                    (target_scope_name, getattr(name_token, "rawText", ""))
                )
                if port_record is not None and name_token is not None:
                    add_occurrence(
                        port_record,
                        _token_source_range(
                            source_catalog, name_token, port_record["name"]
                        ),
                        "semantic_named_connection",
                    )

    # A select expression can own a semantic MemberAccessExpression as its
    # value without exposing that nested expression as a separately visited
    # catalog node. Resolve the nested member through its semantic field and
    # alias source identities, then use only direct scoped-name fields.
    for node in nodes:
        if type(node).__name__ not in {"ElementSelectExpression", "RangeSelectExpression"}:
            continue
        access = getattr(node, "value", None)
        if type(access).__name__ != "MemberAccessExpression":
            continue
        member = getattr(access, "member", None)
        member_name = str(getattr(member, "name", ""))
        if not member_name:
            continue
        base_value = getattr(access, "value", None)
        base = getattr(base_value, "symbol", None)
        declared_base = getattr(getattr(base, "type", None), "declaredType", None)
        if declared_base is None:
            declared_base = getattr(getattr(base_value, "type", None), "declaredType", None)
        if declared_base is None:
            declared_base = getattr(base_value, "type", None)
        alias_record = alias_record_for_declared(declared_base)
        field_record = (
            field_records_by_alias.get(
                (
                    alias_record["declaration"].file,
                    alias_record["declaration"].start,
                    alias_record["declaration"].end,
                    member_name,
                )
            )
            if alias_record is not None
            else None
        )
        if field_record is None:
            field_record = record_for_target(member)
        if field_record is None:
            continue
        token = _direct_member_identifier(
            getattr(access, "syntax", None) or getattr(node, "syntax", None)
        )
        if token is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "selected member has no direct field identifier token",
                file=_syntax_start(source_catalog, node)[0],
                start=_syntax_start(source_catalog, node)[1],
            )
        add_occurrence(
            field_record,
            _token_source_range(source_catalog, token, field_record["name"]),
            "semantic_member",
        )

    result: list[SourceSymbol] = []
    for record in records:
        occurrences = tuple(
            sorted(
                record["occurrences"].values(),
                key=lambda occurrence: (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                ),
            )
        )
        declaration = record["declaration"]
        result.append(
            SourceSymbol(
                symbol_id=(
                    f"symbol:{record['category']}:{declaration.file}:"
                    f"{declaration.start}:{declaration.end}"
                ),
                category=record["category"],
                name=record["name"],
                declaration=declaration,
                owner_module=record["owner"],
                semantic_owner=record["owner"],
                occurrences=occurrences,
                impact=record["impact"],
                abi=record["abi"],
                support=record["support"],
                reason=record["reason"],
            )
        )
    return result


def _augment_signal_member_occurrences(
    source_catalog: SourceCatalog,
    symbols: list[SourceSymbol],
) -> list[SourceSymbol]:
    """Add semantic member-base occurrences omitted by direct AST expressions."""

    nodes: list[Any] = []
    source_catalog.catalog_root.visit(nodes.append)
    by_declaration = {
        (
            symbol.declaration.file,
            symbol.declaration.start,
            symbol.declaration.end,
        ): symbol
        for symbol in symbols
        if symbol.category == "signals"
    }
    additions: dict[str, list[SymbolOccurrence]] = {
        symbol.symbol_id: list(symbol.occurrences) for symbol in symbols
    }
    for node in nodes:
        if type(node).__name__ != "MemberAccessExpression":
            continue
        value = getattr(node, "value", None)
        base = None
        while value is not None:
            base = getattr(value, "symbol", None)
            if base is not None:
                break
            value = getattr(value, "value", None)
        if base is None:
            continue
        try:
            base_range = _record_range(source_catalog, base)
        except SymbolGraphError:
            continue
        symbol = by_declaration.get(
            (base_range.file, base_range.start, base_range.end)
        )
        if symbol is None:
            continue
        left = getattr(getattr(node, "syntax", None), "left", None)
        token = getattr(left, "identifier", None)
        if token is None and left is not None:
            token = _direct_expression_identifier(left)
        if token is None:
            continue
        source_range = _token_source_range(source_catalog, token, symbol.name)
        if source_range is None:
            continue
        if any(
            occurrence.source_range == source_range
            for occurrence in additions[symbol.symbol_id]
        ):
            continue
        additions[symbol.symbol_id].append(
            SymbolOccurrence(source_range, "semantic_member_base")
        )
    return [
        replace(
            symbol,
            occurrences=tuple(
                sorted(
                    additions[symbol.symbol_id],
                    key=lambda occurrence: (
                        occurrence.source_range.file,
                        occurrence.source_range.start,
                        occurrence.source_range.end,
                        occurrence.provenance,
                    ),
                )
            ),
        )
        for symbol in symbols
    ]


def _augment_signal_generate_connection_occurrences(
    source_catalog: SourceCatalog,
    symbols: list[SourceSymbol],
) -> list[SourceSymbol]:
    """Recover named-port signal references owned by a generate scope."""

    nodes: list[Any] = []
    source_catalog.catalog_root.visit(nodes.append)
    by_declaration = {
        (
            symbol.declaration.file,
            symbol.declaration.start,
            symbol.declaration.end,
        ): symbol
        for symbol in symbols
        if symbol.category == "signals"
    }
    signal_nodes: list[tuple[tuple[str, int, int], Any]] = []
    for node in nodes:
        if getattr(node, "kind", None) not in (
            pyslang.ast.SymbolKind.Variable,
            pyslang.ast.SymbolKind.Net,
        ):
            continue
        try:
            key = _signal_range_key(source_catalog, node)
        except SymbolGraphError:
            continue
        if key in by_declaration:
            signal_nodes.append((key, node))

    additions: dict[str, list[SymbolOccurrence]] = {
        symbol.symbol_id: list(symbol.occurrences) for symbol in symbols
    }
    for generate in nodes:
        if type(generate).__name__ != "GenerateBlockSymbol":
            continue
        syntax = getattr(generate, "syntax", None)
        if syntax is None:
            continue
        source_span = getattr(syntax, "sourceRange", None)
        span_start = getattr(getattr(source_span, "start", None), "offset", None)
        span_end = getattr(getattr(source_span, "end", None), "offset", None)
        if span_start is None or span_end is None:
            continue
        file, _ = _syntax_node_start(source_catalog, syntax)
        if file is None:
            continue
        scoped_signals = [
            (key, node)
            for key, node in signal_nodes
            if key[0] == file and span_start <= key[1] < span_end
        ]
        if not scoped_signals:
            continue
        for member in getattr(syntax, "members", ()):
            if type(member).__name__ != "HierarchyInstantiationSyntax":
                continue
            for instance in getattr(member, "instances", ()):
                for connection in getattr(instance, "connections", ()):
                    if type(connection).__name__ != "NamedPortConnectionSyntax":
                        continue
                    expression = getattr(connection, "expr", None)
                    sequence = getattr(expression, "expr", None)
                    identifier_name = getattr(sequence, "expr", None)
                    token = getattr(identifier_name, "identifier", None)
                    if token is None or not getattr(token, "rawText", ""):
                        continue
                    scope = getattr(scoped_signals[0][1], "parentScope", None)
                    target = _scope_lookup_target(scope, token)
                    try:
                        target_key = _signal_range_key(source_catalog, target)
                    except (AttributeError, SymbolGraphError):
                        continue
                    scoped_keys = {key for key, _ in scoped_signals}
                    if target_key not in scoped_keys:
                        continue
                    symbol = by_declaration[target_key]
                    source_range = _token_source_range(
                        source_catalog, token, symbol.name
                    )
                    if source_range is None:
                        continue
                    if source_range == symbol.declaration:
                        continue
                    if any(
                        occurrence.source_range == source_range
                        for occurrence in additions[symbol.symbol_id]
                    ):
                        continue
                    additions[symbol.symbol_id].append(
                        SymbolOccurrence(
                            source_range, "semantic_generate_syntax"
                        )
                    )

    return [
        replace(
            symbol,
            occurrences=tuple(
                sorted(
                    additions[symbol.symbol_id],
                    key=lambda occurrence: (
                        occurrence.source_range.file,
                        occurrence.source_range.start,
                        occurrence.source_range.end,
                        occurrence.provenance,
                    ),
                )
            ),
        )
        for symbol in symbols
    ]


def _apply_owner_quarantine(
    symbols: list[SourceSymbol],
    *,
    type_parameter_owner_ids: set[str],
    type_parameter_symbol_ids: set[str],
    defparam_owner_ids: set[str],
    nested_module_spans: tuple[_NestedModuleSpan, ...],
    macro_module_spans: tuple[_NestedModuleSpan, ...],
    ordinary_module_spans: tuple[_NestedModuleSpan, ...],
) -> list[SourceSymbol]:
    known_owner_reasons = frozenset(
        {
            "owner_contains_type_parameter",
            "defparam_binding_not_renamed",
            "owner_contains_nested_generate",
            "owner_contains_macro_source",
        }
    )
    reasons_by_owner: dict[str, set[str]] = {}

    def add_reason(owner_id: str, reason: str) -> None:
        if reason not in known_owner_reasons:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "physical module owner has an unknown quarantine reason",
            )
        reasons_by_owner.setdefault(owner_id, set()).add(reason)

    for owner_id in sorted(type_parameter_owner_ids):
        add_reason(owner_id, "owner_contains_type_parameter")
    for owner_id in sorted(defparam_owner_ids):
        add_reason(owner_id, "defparam_binding_not_renamed")

    macro_spans_by_owner: dict[str, SourceRange] = {}
    for macro_span in macro_module_spans:
        previous = macro_spans_by_owner.get(macro_span.owner_id)
        if previous is not None and previous != macro_span.source_range:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "macro owner has conflicting module spans",
                file=macro_span.source_range.file,
                start=macro_span.source_range.start,
            )
        macro_spans_by_owner[macro_span.owner_id] = macro_span.source_range
        add_reason(macro_span.owner_id, "owner_contains_macro_source")

    ordered_macro_spans = tuple(
        sorted(
            macro_spans_by_owner.items(),
            key=lambda item: (
                item[1].file,
                item[1].start,
                item[1].end,
                item[0],
            ),
        )
    )
    for index, (_owner_id, left) in enumerate(ordered_macro_spans):
        for _other_owner_id, right in ordered_macro_spans[index + 1 :]:
            if (
                left.file == right.file
                and left.start < right.end
                and right.start < left.end
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "macro owner module spans overlap",
                    file=left.file,
                    start=left.start,
                )

    spans_by_owner: dict[str, SourceRange] = {}
    for nested_span in nested_module_spans:
        previous = spans_by_owner.get(nested_span.owner_id)
        if previous is not None and previous != nested_span.source_range:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "nested generate owner has conflicting module spans",
                file=nested_span.source_range.file,
                start=nested_span.source_range.start,
            )
        spans_by_owner[nested_span.owner_id] = nested_span.source_range
        add_reason(nested_span.owner_id, "owner_contains_nested_generate")
    ordered_spans = tuple(
        sorted(
            spans_by_owner.items(),
            key=lambda item: (
                item[1].file,
                item[1].start,
                item[1].end,
                item[0],
            ),
        )
    )
    for index, (_owner_id, left) in enumerate(ordered_spans):
        for _other_owner_id, right in ordered_spans[index + 1 :]:
            if (
                left.file == right.file
                and left.start < right.end
                and right.start < left.end
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "nested generate module spans overlap",
                    file=left.file,
                    start=left.start,
                )

    ordinary_spans_by_owner: dict[str, SourceRange] = {}
    for module_span in ordinary_module_spans:
        previous = ordinary_spans_by_owner.get(module_span.owner_id)
        if previous is not None and previous != module_span.source_range:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "physical module owner has multiple semantic module spans",
                file=module_span.source_range.file,
                start=module_span.source_range.start,
            )
        ordinary_spans_by_owner[module_span.owner_id] = module_span.source_range

    protected_owner_ids = set(reasons_by_owner)
    protected_spans_by_owner: dict[str, SourceRange] = {}
    for owner_id in sorted(protected_owner_ids):
        source_range = ordinary_spans_by_owner.get(owner_id)
        if source_range is None:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "quarantine owner has no unique physical module span",
            )
        nested_range = spans_by_owner.get(owner_id)
        macro_range = macro_spans_by_owner.get(owner_id)
        if (
            nested_range is not None
            and nested_range != source_range
            or macro_range is not None
            and macro_range != source_range
        ):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_OWNER_MISMATCH",
                "quarantine owner semantic module spans disagree",
                file=source_range.file,
                start=source_range.start,
            )
        protected_spans_by_owner[owner_id] = source_range

    ordered_protected_spans = tuple(
        sorted(
            protected_spans_by_owner.items(),
            key=lambda item: (
                item[1].file,
                item[1].start,
                item[1].end,
                item[0],
            ),
        )
    )
    for index, (_owner_id, left) in enumerate(ordered_protected_spans):
        for _other_owner_id, right in ordered_protected_spans[index + 1 :]:
            if (
                left.file == right.file
                and left.start < right.end
                and right.start < left.end
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "quarantined physical module spans overlap",
                    file=left.file,
                    start=max(left.start, right.start),
                )

    multiple_owner_ids = {
        owner_id
        for owner_id, owner_reasons in reasons_by_owner.items()
        if len(owner_reasons) > 1
    }
    quarantine_reason_by_symbol: dict[str, str] = {}
    for symbol in symbols:
        nested_containing = [
            owner_id
            for owner_id, source_range in ordered_spans
            if (
                symbol.declaration.file == source_range.file
                and source_range.start <= symbol.declaration.start
                and symbol.declaration.end <= source_range.end
            )
        ]
        if len(nested_containing) > 1:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "symbol declaration is contained in multiple nested module spans",
                file=symbol.declaration.file,
                start=symbol.declaration.start,
            )
        macro_containing = [
            owner_id
            for owner_id, source_range in ordered_macro_spans
            if (
                symbol.declaration.file == source_range.file
                and source_range.start <= symbol.declaration.start
                and symbol.declaration.end <= source_range.end
            )
        ]
        if len(macro_containing) > 1:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "symbol declaration is contained in multiple macro module spans",
                file=symbol.declaration.file,
                start=symbol.declaration.start,
            )
        multiple_containing = [
            owner_id
            for owner_id in sorted(multiple_owner_ids)
            if (
                symbol.declaration.file
                == protected_spans_by_owner[owner_id].file
                and protected_spans_by_owner[owner_id].start
                <= symbol.declaration.start
                and symbol.declaration.end
                <= protected_spans_by_owner[owner_id].end
            )
        ]
        containing_owner_ids = set(
            (*nested_containing, *macro_containing, *multiple_containing)
        )
        if len(containing_owner_ids) > 1:
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "symbol declaration is contained in multiple quarantined module spans",
                file=symbol.declaration.file,
                start=symbol.declaration.start,
            )
        containing_owner_id = next(iter(containing_owner_ids), None)
        own_reasons = reasons_by_owner.get(symbol.owner_module)
        if own_reasons is not None:
            own_span = protected_spans_by_owner[symbol.owner_module]
            if not (
                symbol.declaration.file == own_span.file
                and own_span.start <= symbol.declaration.start
                and symbol.declaration.end <= own_span.end
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "quarantine owner does not contain its physical declaration",
                    file=symbol.declaration.file,
                    start=symbol.declaration.start,
                )
            if (
                len(own_reasons) > 1
                and containing_owner_id != symbol.owner_module
            ):
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "multiple-reason quarantine owner does not contain its physical declaration",
                    file=symbol.declaration.file,
                    start=symbol.declaration.start,
                )
        if (
            containing_owner_id is not None
            and symbol.owner_module in protected_owner_ids
            and symbol.owner_module != containing_owner_id
        ):
            raise SymbolGraphError(
                "SYMBOL_GRAPH_RANGE_CONFLICT",
                "physical symbol owner disagrees with its quarantine span owner",
                file=symbol.declaration.file,
                start=symbol.declaration.start,
            )

        if containing_owner_id in multiple_owner_ids:
            quarantine_reason_by_symbol[symbol.symbol_id] = (
                "owner_contains_multiple_unsupported_constructs"
            )
        elif macro_containing:
            quarantine_reason_by_symbol[symbol.symbol_id] = (
                "owner_contains_macro_source"
            )
        elif nested_containing:
            quarantine_reason_by_symbol[symbol.symbol_id] = (
                "owner_contains_nested_generate"
            )
        elif own_reasons is not None:
            if len(own_reasons) > 1:
                quarantine_reason_by_symbol[symbol.symbol_id] = (
                    "owner_contains_multiple_unsupported_constructs"
                )
            elif symbol.symbol_id in type_parameter_symbol_ids:
                quarantine_reason_by_symbol[symbol.symbol_id] = (
                    "type_parameter_not_renamed"
                )
            else:
                quarantine_reason_by_symbol[symbol.symbol_id] = sorted(
                    own_reasons
                )[0]
        elif symbol.symbol_id in type_parameter_symbol_ids:
            quarantine_reason_by_symbol[symbol.symbol_id] = (
                "type_parameter_not_renamed"
            )

    quarantined_symbols = [
        replace(
            symbol,
            support="unsupported",
            reason=quarantine_reason_by_symbol[symbol.symbol_id],
        )
        if symbol.symbol_id in quarantine_reason_by_symbol
        else symbol
        for symbol in symbols
    ]

    firewall_symbol_ids: set[str] = set()
    for symbol in quarantined_symbols:
        ranges = (
            symbol.declaration,
            *(occurrence.source_range for occurrence in symbol.occurrences),
        )
        for source_range in ranges:
            containing_owner_ids: list[str] = []
            for owner_id, protected_span in ordered_protected_spans:
                if source_range.file != protected_span.file:
                    continue
                overlaps = (
                    source_range.start < protected_span.end
                    and protected_span.start < source_range.end
                )
                if not overlaps:
                    continue
                if not (
                    protected_span.start <= source_range.start
                    and source_range.end <= protected_span.end
                ):
                    raise SymbolGraphError(
                        "SYMBOL_GRAPH_RANGE_CONFLICT",
                        "symbol range partially overlaps a quarantined module span",
                        file=source_range.file,
                        start=source_range.start,
                    )
                containing_owner_ids.append(owner_id)
            if len(containing_owner_ids) > 1:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                    "symbol range is contained in multiple quarantined module spans",
                    file=source_range.file,
                    start=source_range.start,
                )
            if not containing_owner_ids or symbol.support != "eligible":
                continue
            if containing_owner_ids[0] == symbol.owner_module:
                raise SymbolGraphError(
                    "SYMBOL_GRAPH_OWNER_MISMATCH",
                    "eligible symbol belongs to a quarantined physical module owner",
                    file=source_range.file,
                    start=source_range.start,
                )
            firewall_symbol_ids.add(symbol.symbol_id)

    return [
        replace(
            symbol,
            support="unsupported",
            reason="occurrence_in_quarantined_owner",
        )
        if symbol.symbol_id in firewall_symbol_ids
        else symbol
        for symbol in quarantined_symbols
    ]


def _build_symbol_graph_impl(source_catalog: SourceCatalog) -> SymbolGraph:
    """Build the complete vNext semantic graph from the compiled catalog view."""

    nodes: list[Any] = []
    source_catalog.catalog_root.visit(nodes.append)
    _active_macro_owner_evidence.set(
        _macro_owner_evidence_for(source_catalog, nodes)
    )
    # Uninstantiated definitions are semantic placeholders without a
    # byte-backed source identifier.  They are not source symbols and must
    # not make an otherwise closed selected-top graph fail globally.  All
    # source-backed nodes continue through the normal owner/range checks
    # below; the placeholder itself is intentionally ignored.
    owners = _module_owner_map(source_catalog)
    variable_kind = pyslang.ast.SymbolKind.Variable
    net_kind = pyslang.ast.SymbolKind.Net

    def semantic_range_key(node: Any) -> tuple[str, int, int] | None:
        source_range = getattr(node, "sourceRange", None)
        start = getattr(source_range, "start", None)
        end = getattr(source_range, "end", None)
        if start is None or end is None:
            name = str(getattr(node, "name", ""))
            location = getattr(node, "location", None)
            if not name or location is None:
                return None
            try:
                declaration = _range_from_location(source_catalog, location, name)
            except SymbolGraphError:
                return None
            return declaration.file, declaration.start, declaration.end
        if start.buffer != end.buffer:
            return None
        if source_catalog.catalog_source_manager.isMacroLoc(start):
            return None
        try:
            absolute = Path(
                source_catalog.catalog_source_manager.getFullPath(start.buffer)
            ).resolve()
            file = absolute.relative_to(source_catalog.source_set.source_root).as_posix()
        except (OSError, RuntimeError, ValueError):
            return None
        return file, int(start.offset), int(end.offset)

    excluded_ranges: set[tuple[str, int, int]] = set()
    for node in nodes:
        for attribute in ("internalSymbol", "returnValVar"):
            excluded = getattr(node, attribute, None)
            if excluded is not None:
                key = semantic_range_key(excluded)
                if key is not None:
                    excluded_ranges.add(key)

    declarations: dict[tuple[str, int, int], tuple[str, SourceRange, ModuleOwner]] = {}
    for node in nodes:
        if getattr(node, "kind", None) not in (variable_kind, net_kind):
            continue
        name = str(getattr(node, "name", ""))
        if not name or name.startswith("$"):
            continue
        owner = _owner_for_signal(source_catalog, node, owners)
        if owner is None:
            continue
        if _reject_macro_location(source_catalog, node.location):
            continue
        declaration = _range_from_location(
            source_catalog, node.location, name
        )
        key = (declaration.file, declaration.start, declaration.end)
        if key in excluded_ranges:
            continue
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
    range_select_kind = getattr(pyslang.ast.ExpressionKind, "RangeSelect", None)
    element_value_ranges = {
        semantic_range_key(getattr(node, "value", None))
        for node in nodes
        if getattr(node, "kind", None) in (element_select_kind, range_select_kind)
        and getattr(node, "value", None) is not None
    } - {None}
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
            if target_key is None:
                continue
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
        if node_kind in (element_select_kind, range_select_kind):
            value = getattr(node, "value", None)
            target = getattr(value, "symbol", None)
            if target is None:
                continue
            if _is_signal_target(target):
                target_key = _signal_range_key(source_catalog, target)
                if target_key is None:
                    continue
                declaration = declarations.get(target_key)
                if declaration is not None:
                    syntax = getattr(value, "syntax", None)
                    token = getattr(syntax, "identifier", None)
                    if token is None:
                        token = getattr(getattr(node, "syntax", None), "identifier", None)
                    if token is None:
                        source_range = _expression_range(
                            source_catalog, value, declaration[0]
                        )
                    else:
                        source_range = _token_source_range(
                            source_catalog, token, declaration[0]
                        )
                    if source_range is None:
                        continue
                    if source_range == declaration[1]:
                        continue
                    occurrence = SymbolOccurrence(source_range, "semantic_expression")
                    occurrence_key = (
                        source_range.file,
                        source_range.start,
                        source_range.end,
                        occurrence.provenance,
                    )
                    occurrences[target_key][occurrence_key] = occurrence
            continue
        elif node_kind == pyslang.ast.ExpressionKind.NamedValue:
            target = getattr(node, "symbol", None)
            if target is None and semantic_range_key(node) not in element_value_ranges:
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
        target_key = _signal_range_key(source_catalog, target)
        if target_key is None:
            continue
        declaration = declarations.get(target_key)
        if declaration is None:
            continue
        if getattr(node, "syntax", None) is None:
            if semantic_range_key(node) in element_value_ranges:
                continue
            source_range = _expression_range(source_catalog, node, declaration[0])
            if source_range is None:
                continue
            if source_range == declaration[1]:
                continue
            occurrence = SymbolOccurrence(source_range, "semantic_expression")
            occurrence_key = (
                source_range.file,
                source_range.start,
                source_range.end,
                occurrence.provenance,
            )
            occurrences[target_key][occurrence_key] = occurrence
            continue
        name = declaration[0]
        source_range = _expression_range(source_catalog, node, name)
        if source_range is None:
            continue
        if source_range == declaration[1]:
            continue
        occurrence = SymbolOccurrence(source_range, "semantic_expression")
        occurrence_key = (
            source_range.file,
            source_range.start,
            source_range.end,
            occurrence.provenance,
        )
        occurrences[target_key][occurrence_key] = occurrence

    genvar_symbols, nested_module_spans = _collect_genvar_symbols(
        source_catalog, nodes, owners
    )
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

    type_parameter_symbols, type_parameter_owner_ids, type_parameter_symbol_ids = (
        _collect_type_parameter_symbols(source_catalog, nodes, owners)
    )
    parameter_symbols, defparam_owner_ids = _collect_parameter_symbols(
        source_catalog, nodes, owners, genvar_symbols
    )
    symbols_list.extend(parameter_symbols)
    symbols_list.extend(type_parameter_symbols)
    symbols_list.extend(genvar_symbols)
    symbols_list = _augment_signal_member_occurrences(source_catalog, symbols_list)
    symbols_list = _augment_signal_generate_connection_occurrences(
        source_catalog, symbols_list
    )
    symbols_list.extend(_collect_extended_symbols(source_catalog, symbols_list))
    macro_evidence = _active_macro_owner_evidence.get()
    if macro_evidence is None:
        raise SymbolGraphError(
            "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
            "macro owner evidence is unavailable",
        )
    macro_owner_ids = macro_evidence.owner_ids | frozenset(
        macro_evidence.target_owner_ids
    )
    macro_module_spans = tuple(
        span
        for span in macro_evidence.module_spans
        if span.owner_id in macro_owner_ids
    )
    symbols_list = _apply_owner_quarantine(
        symbols_list,
        type_parameter_owner_ids=type_parameter_owner_ids,
        type_parameter_symbol_ids=type_parameter_symbol_ids,
        defparam_owner_ids=defparam_owner_ids,
        nested_module_spans=nested_module_spans,
        macro_module_spans=macro_module_spans,
        ordinary_module_spans=macro_evidence.module_spans,
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
    result = SymbolGraph(schema_version=1, source_catalog=source_catalog, symbols=symbols)
    return result


def build_symbol_graph(source_catalog: SourceCatalog) -> SymbolGraph:
    """Build a SymbolGraph and clear private macro evidence on every exit."""

    try:
        return _build_symbol_graph_impl(source_catalog)
    finally:
        _active_macro_owner_evidence.set(None)
