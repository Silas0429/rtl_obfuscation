"""PySlang-backed physical rename index.

The index is deliberately small: PySlang owns name, type, owner and target
resolution; this module only turns source-backed semantic objects into
validated physical identifier ranges.  It does not perform name lookup or
parse SystemVerilog text.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

import pyslang

from .category_registry_vnext import CANONICAL_CATEGORIES, CategoryRegistryError, normalize_categories
from .source_catalog import ModuleOwner, SourceCatalog, SourceRange


@dataclass(frozen=True)
class SymbolOccurrence:
    source_range: SourceRange
    provenance: str


@dataclass(frozen=True)
class SourceSymbol:
    symbol_id: str
    category: str
    kind: str
    semantic_kind: str
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
class RenameDecision:
    symbol_id: str
    category: str
    action: str
    reason: str | None


@dataclass(frozen=True)
class RenameIndex:
    schema_version: int
    source_catalog: SourceCatalog = field(repr=False, compare=False)
    selected_categories: tuple[str, ...]
    symbols: tuple[SourceSymbol, ...]
    decisions: tuple[RenameDecision, ...]
    category_outcomes: tuple[dict[str, object], ...]

    def to_report(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_catalog": self.source_catalog.to_report(),
            "categories": list(self.selected_categories),
            "symbols": [_symbol_report(symbol) for symbol in self.symbols],
            "category_outcomes": [dict(item) for item in self.category_outcomes],
            "range_audit": {
                "symbols": len(self.symbols),
                "declarations": len(self.symbols),
                "occurrences": sum(len(symbol.occurrences) for symbol in self.symbols),
                "total_ranges": sum(1 + len(symbol.occurrences) for symbol in self.symbols),
            },
        }


class RenameIndexError(ValueError):
    """Stable fail-closed error for PySlang-to-source binding."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        file: str | None = None,
        start: int | None = None,
        details: tuple[dict[str, object], ...] = (),
    ) -> None:
        self.code = code
        self.message = message
        self.file = file
        self.start = start
        self.details = details
        super().__init__(f"{code}: {message}")


@dataclass
class _WorkingSymbol:
    symbol_id: str
    category: str
    kind: str
    semantic_kind: str
    name: str
    declaration: SourceRange
    owner_module: str
    semantic_owner: str
    impact: str
    abi: str
    support: str = "eligible"
    reason: str | None = None
    targets: set[int] = field(default_factory=set)
    occurrences: dict[tuple[str, int, int], SymbolOccurrence] = field(default_factory=dict)


def _symbol_report(symbol: SourceSymbol) -> dict[str, object]:
    return {
        "symbol_id": symbol.symbol_id,
        "category": symbol.category,
        "kind": symbol.kind,
        "semantic_kind": symbol.semantic_kind,
        "name": symbol.name,
        "declaration": _range_report(symbol.declaration),
        "owner_module": symbol.owner_module,
        "semantic_owner": symbol.semantic_owner,
        "occurrences": [
            {"source_range": _range_report(item.source_range), "provenance": item.provenance}
            for item in symbol.occurrences
        ],
        "impact": symbol.impact,
        "abi": symbol.abi,
        "support": symbol.support,
        "reason": symbol.reason,
    }


def _range_report(value: SourceRange) -> dict[str, object]:
    return {"file": value.file, "start": value.start, "end": value.end}


def _kind_name(value: object) -> str:
    return str(value).rsplit(".", 1)[-1]


def _source_bytes(catalog: SourceCatalog, file: str) -> bytes:
    try:
        return (Path(catalog.source_catalog_root) / file).read_bytes()
    except AttributeError:
        return (Path(catalog.source_set.source_root) / file).read_bytes()
    except OSError as error:
        raise RenameIndexError("RENAME_INDEX_SOURCE_INVALID", f"cannot read source file {file}: {error}") from error


def _file_for_buffer(catalog: SourceCatalog, buffer: object) -> str:
    manager = catalog.catalog_source_manager
    try:
        absolute = Path(manager.getFullPath(buffer)).resolve()
        return absolute.relative_to(Path(catalog.source_set.source_root).resolve()).as_posix()
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise RenameIndexError("RENAME_INDEX_RANGE_INVALID", "semantic location is outside SourceSet") from error


def _range_for_location(catalog: SourceCatalog, location: object, name: str) -> SourceRange:
    if location is None or not name:
        raise RenameIndexError("RENAME_INDEX_SOURCE_INVALID", "source-backed semantic object has no identifier")
    try:
        file = _file_for_buffer(catalog, location.buffer)
        start = int(location.offset)
    except (AttributeError, TypeError, ValueError) as error:
        raise RenameIndexError("RENAME_INDEX_RANGE_INVALID", "semantic location is invalid") from error
    result = SourceRange(file, start, start + len(name.encode("utf-8")))
    data = _source_bytes(catalog, file)
    if not 0 <= result.start < result.end <= len(data) or data[result.start:result.end] != name.encode("utf-8"):
        raise RenameIndexError(
            "RENAME_INDEX_RANGE_INVALID",
            "semantic identifier location does not match source bytes",
            file=file,
            start=start,
        )
    return result


def _range_for_token(catalog: SourceCatalog, token: object, expected: str) -> SourceRange | None:
    if token is None or getattr(token, "isMissing", False):
        return None
    raw_value = getattr(token, "rawText", b"")
    raw = raw_value.encode("utf-8") if isinstance(raw_value, str) else bytes(raw_value)
    if raw != expected.encode("utf-8"):
        return None
    return _range_for_location(catalog, token.location, expected)


def _syntax_identifier_range(catalog: SourceCatalog, syntax: object, expected: str) -> SourceRange | None:
    if syntax is None:
        return None
    # Only use a typed identifier property.  Walking all tokens and choosing a
    # matching name would lose the semantic target when a syntax contains two
    # equal identifiers (for example a scoped member access).
    if type(syntax).__name__ == "Token":
        return _range_for_token(catalog, syntax, expected)
    identifier = getattr(syntax, "identifier", None)
    direct = _range_for_token(catalog, identifier, expected)
    if direct is not None:
        return direct
    if _kind_name(getattr(syntax, "kind", None)) == "ScopedName":
        right = getattr(syntax, "right", None)
        return _syntax_identifier_range(catalog, right, expected)
    if _kind_name(getattr(syntax, "kind", None)) == "ModportNamedPort":
        return _range_for_token(catalog, getattr(syntax, "name", None), expected)
    if _kind_name(getattr(syntax, "kind", None)) == "NamedType":
        name = getattr(syntax, "name", None)
        return _syntax_identifier_range(catalog, name, expected)
    return None


def _expression_range(catalog: SourceCatalog, expression: object, expected: str) -> SourceRange | None:
    syntax = getattr(expression, "syntax", None)
    result = _syntax_identifier_range(catalog, syntax, expected)
    if result is not None:
        return result
    source_range = getattr(expression, "sourceRange", None)
    if source_range is None:
        return None
    try:
        start = source_range.start
        end = source_range.end
        if start.buffer != end.buffer:
            return None
        file = _file_for_buffer(catalog, start.buffer)
        candidate = SourceRange(file, int(start.offset), int(end.offset))
        data = _source_bytes(catalog, file)
        if data[candidate.start:candidate.end] == expected.encode("utf-8"):
            return candidate
    except (AttributeError, TypeError, ValueError, IndexError):
        return None
    return None


def _semantic_expression_range(
    catalog: SourceCatalog, expression: object, expected: str
) -> tuple[SourceRange | None, str]:
    """Return a physical range and PySlang provenance for an expression.

    PySlang represents macro-expanded expressions in virtual buffers.  The
    semantic target remains authoritative, but the virtual range is not an
    editable source range.  For a macro argument or body, PySlang's source
    manager provides the fully-original physical token; if that token cannot
    be proven, the occurrence is omitted and the declaration remains
    fail-closed.
    """

    source_range = getattr(expression, "sourceRange", None)
    if source_range is None:
        return None, "semantic_reference"
    try:
        start = source_range.start
        manager = catalog.catalog_source_manager
        if manager.isMacroLoc(start):
            provenance = (
                "semantic_macro_argument"
                if manager.isMacroArgLoc(start)
                else "semantic_macro_body"
            )
            original = manager.getFullyOriginalLoc(start)
            try:
                return _range_for_location(catalog, original, expected), provenance
            except RenameIndexError:
                return None, provenance
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None, "semantic_reference"
    return _expression_range(catalog, expression, expected), "semantic_reference"


def _definition_range(catalog: SourceCatalog, definition: object) -> SourceRange | None:
    if definition is None:
        return None
    name = str(getattr(definition, "name", ""))
    try:
        return _range_for_location(catalog, getattr(definition, "location", None), name)
    except RenameIndexError:
        return None


def _definition_key(catalog: SourceCatalog, definition: object) -> tuple[str, int, int] | None:
    value = _definition_range(catalog, definition)
    return None if value is None else (value.file, value.start, value.end)


def _module_maps(catalog: SourceCatalog) -> tuple[dict[tuple[str, int, int], ModuleOwner], dict[int, ModuleOwner]]:
    by_range = {
        (item.declaration.file, item.declaration.start, item.declaration.end): item
        for item in catalog.modules
    }
    by_definition: dict[int, ModuleOwner] = {}
    nodes: list[Any] = []
    catalog.catalog_root.visit(nodes.append)
    for node in nodes:
        if type(node).__name__ != "InstanceBodySymbol":
            continue
        definition = getattr(node, "definition", None)
        key = _definition_key(catalog, definition)
        owner = by_range.get(key) if key is not None else None
        if owner is not None:
            by_definition[id(definition)] = owner
    return by_range, by_definition


def _interface_ids(catalog: SourceCatalog, nodes: Iterable[Any]) -> dict[int, str]:
    result: dict[int, str] = {}
    for node in nodes:
        if type(node).__name__ != "InstanceBodySymbol":
            continue
        syntax = getattr(node, "syntax", None)
        if _kind_name(getattr(syntax, "kind", None)) != "InterfaceDeclaration":
            continue
        definition = getattr(node, "definition", None)
        value = _definition_range(catalog, definition)
        if value is not None:
            result[id(definition)] = f"interface:{value.file}:{value.start}:{value.end}"
    return result


def _top_active_interfaces(catalog: SourceCatalog) -> set[tuple[str, int, int]]:
    if catalog.top_root is None:
        return set()
    result: set[tuple[str, int, int]] = set()
    nodes: list[Any] = []
    catalog.top_root.visit(nodes.append)
    for node in nodes:
        if type(node).__name__ == "InstanceSymbol" and getattr(node, "isInterface", False):
            key = _definition_key(catalog, getattr(node, "definition", None))
            if key is not None:
                result.add(key)
        elif type(node).__name__ == "InterfacePortSymbol":
            key = _definition_key(catalog, getattr(node, "interfaceDef", None))
            if key is not None:
                result.add(key)
    return result


def _top_active_types(catalog: SourceCatalog) -> set[tuple[str, int, int]]:
    if catalog.top_root is None:
        return set()
    result: set[tuple[str, int, int]] = set()
    nodes: list[Any] = []
    catalog.top_root.visit(nodes.append)
    for node in nodes:
        declared = getattr(node, "declaredType", None)
        target = getattr(declared, "type", None)
        if type(target).__name__ == "TypeAliasType":
            key = _definition_key(catalog, target)
            if key is not None:
                result.add(key)
        if type(node).__name__ == "ConversionExpression":
            target = getattr(node, "type", None)
            if type(target).__name__ == "TypeAliasType":
                key = _definition_key(catalog, target)
                if key is not None:
                    result.add(key)
    return result


def _owner_info(
    catalog: SourceCatalog,
    definition: object,
    modules_by_definition: dict[int, ModuleOwner],
    interfaces_by_definition: dict[int, str],
) -> tuple[str, str, ModuleOwner | None, str | None]:
    module = modules_by_definition.get(id(definition))
    if module is not None:
        return module.name, module.owner_id, module, "module"
    interface = interfaces_by_definition.get(id(definition))
    if interface is not None:
        return interface, interface, None, "interface"
    # PySlang may expose distinct DefinitionSymbol wrappers for the same
    # source-backed declaration.  Resolve that wrapper by its own semantic
    # declaration location, never by a textual name search.
    key = _definition_key(catalog, definition)
    if key is not None:
        for candidate in catalog.modules:
            if candidate.declaration == SourceRange(*key):
                return candidate.name, candidate.owner_id, candidate, "module"
        interface_key = f"interface:{key[0]}:{key[1]}:{key[2]}"
        if interface_key in interfaces_by_definition.values():
            return interface_key, interface_key, None, "interface"
    return "$unit", "$unit", None, None


def _add_working(
    records: dict[str, _WorkingSymbol],
    target_map: dict[int, str],
    *,
    catalog: SourceCatalog,
    category: str,
    kind: str,
    semantic_kind: str,
    name: str,
    declaration: SourceRange,
    owner_module: str,
    semantic_owner: str,
    impact: str,
    abi: str,
    targets: Iterable[object],
    support: str = "eligible",
    reason: str | None = None,
) -> _WorkingSymbol:
    symbol_id = f"{category}:{declaration.file}:{declaration.start}:{declaration.end}"
    current = records.get(symbol_id)
    if current is None:
        current = _WorkingSymbol(
            symbol_id=symbol_id,
            category=category,
            kind=kind,
            semantic_kind=semantic_kind,
            name=name,
            declaration=declaration,
            owner_module=owner_module,
            semantic_owner=semantic_owner,
            impact=impact,
            abi=abi,
            support=support,
            reason=reason,
        )
        records[symbol_id] = current
    for target in targets:
        if target is not None:
            target_map[id(target)] = symbol_id
            current.targets.add(id(target))
    return current


def _record_for_semantic_target(
    catalog: SourceCatalog,
    records: dict[str, _WorkingSymbol],
    target_map: dict[int, str],
    target: object,
) -> str | None:
    """Resolve a PySlang target, including equivalent wrapper objects.

    PySlang can return a fresh Python wrapper for the same semantic symbol.
    The target's own source location is still direct semantic evidence; it is
    not a name lookup or a textual occurrence search.
    """

    if target is None:
        return None
    symbol_id = target_map.get(id(target))
    if symbol_id is not None:
        return symbol_id
    name = str(getattr(target, "name", ""))
    location = getattr(target, "location", None)
    if not name or location is None:
        return None
    try:
        target_range = _range_for_location(catalog, location, name)
    except RenameIndexError:
        return None
    for candidate in records.values():
        if candidate.declaration == target_range:
            target_map[id(target)] = candidate.symbol_id
            return candidate.symbol_id
    return None


def _is_module_definition(definition: object, modules_by_definition: dict[int, ModuleOwner]) -> bool:
    return id(definition) in modules_by_definition


def _category_support(
    category: str,
    module: ModuleOwner | None,
    *,
    top: str | None,
    interface_active: bool,
    aggregate_active: bool,
    interface_instance: bool = False,
) -> tuple[str, str | None, str]:
    if module is not None and top is not None:
        if not module.in_top_closure:
            return "preserved", "outside_top_closure", "internal"
        if category == "ports" and module.is_selected_top:
            return "preserved", "selected_top_boundary", "top_boundary"
        if category == "interface" and interface_instance and module.is_selected_top:
            return "preserved", "selected_top_boundary", "top_boundary"
    if category == "interface" and top is not None and not interface_active:
        return "preserved", "outside_top_closure", "internal"
    if category == "struct" and top is not None and not aggregate_active:
        return "preserved", "outside_top_closure", "internal"
    return "eligible", None, "module_abi" if category == "ports" else "internal"


def _interface_leaf_elements(node: object) -> tuple[object, ...]:
    """Flatten semantic interface arrays without creating element records."""

    if getattr(node, "isInterface", False):
        return (node,)
    result: list[object] = []
    for element in tuple(getattr(node, "elements", ())):
        result.extend(_interface_leaf_elements(element))
    return tuple(result)


def _register_structs(
    catalog: SourceCatalog,
    selected: set[str],
    records: dict[str, _WorkingSymbol],
    target_map: dict[int, str],
    alias_map: dict[tuple[str, int, int], str],
    nodes: list[Any],
    modules_by_definition: dict[int, ModuleOwner],
    interfaces_by_definition: dict[int, str],
    active_types: set[tuple[str, int, int]],
) -> None:
    if "struct" not in selected:
        return
    for node in nodes:
        if type(node).__name__ != "TypeAliasType":
            continue
        syntax = getattr(node, "syntax", None)
        if _kind_name(getattr(syntax, "kind", None)) != "TypedefDeclaration":
            continue
        aggregate = getattr(syntax, "type", None)
        aggregate_kind = _kind_name(getattr(aggregate, "kind", None))
        if aggregate_kind not in {"StructType", "UnionType"}:
            continue
        name = str(getattr(node, "name", ""))
        declaration = _range_for_token(catalog, getattr(syntax, "name", None), name)
        if declaration is None:
            continue
        definition = getattr(node, "declaringDefinition", None)
        owner_module, semantic_owner, module, _ = _owner_info(
            catalog, definition, modules_by_definition, interfaces_by_definition
        )
        key = (declaration.file, declaration.start, declaration.end)
        support, reason, abi = _category_support(
            "struct", module, top=catalog.source_set.top,
            interface_active=True, aggregate_active=(catalog.source_set.top is None or key in active_types),
        )
        kind = "union_type" if aggregate_kind == "UnionType" else "struct_type"
        record = _add_working(
            records, target_map, catalog=catalog, category="struct", kind=kind,
            semantic_kind=type(node).__name__, name=name, declaration=declaration,
            owner_module=owner_module, semantic_owner=f"type:{declaration.file}:{declaration.start}:{declaration.end}",
            impact="type", abi=abi, targets=(node,), support=support, reason=reason,
        )
        alias_map[key] = record.symbol_id

        # FieldSymbol is the only authority for aggregate members.  The
        # syntax tree can contain multiple equal names and does not identify
        # the semantic field selected by a reference, so it must not be used
        # to discover or bind fields.
        canonical = getattr(node, "canonicalType", None)
        try:
            semantic_fields = tuple(canonical) if canonical is not None else ()
        except (TypeError, RuntimeError):
            semantic_fields = ()
            record.support = "preserved"
            record.reason = "source_binding_incomplete"

        field_bindings: list[tuple[object, SourceRange, str]] = []
        binding_incomplete = canonical is None
        for field in semantic_fields:
            if type(field).__name__ != "FieldSymbol":
                binding_incomplete = True
                continue
            field_name = str(getattr(field, "name", ""))
            if not field_name:
                binding_incomplete = True
                continue
            try:
                field_range = _range_for_location(
                    catalog, getattr(field, "location", None), field_name
                )
            except RenameIndexError:
                binding_incomplete = True
                continue
            field_bindings.append((field, field_range, field_name))

        field_records: list[_WorkingSymbol] = []
        for field, field_range, field_name in field_bindings:
            field_records.append(
                _add_working(
                    records, target_map, catalog=catalog, category="struct",
                    kind="union_field" if aggregate_kind == "UnionType" else "struct_field",
                    semantic_kind="FieldSymbol", name=field_name, declaration=field_range,
                    owner_module=owner_module,
                    semantic_owner=record.semantic_owner,
                    impact="aggregate_field", abi=abi, targets=(field,),
                    support=support, reason=reason,
                )
            )

        if binding_incomplete:
            # A source-backed aggregate without complete physical FieldSymbol
            # evidence is one indivisible unsafe group.  Preserve the alias
            # and every field already proven in this group; never guess a
            # missing declaration from syntax or by name.
            record.support = "preserved"
            record.reason = "source_binding_incomplete"
            for field_record in field_records:
                field_record.support = "preserved"
                field_record.reason = "source_binding_incomplete"


def _register_core_declarations(
    catalog: SourceCatalog,
    selected: set[str],
    records: dict[str, _WorkingSymbol],
    target_map: dict[int, str],
    nodes: list[Any],
    modules_by_definition: dict[int, ModuleOwner],
    interfaces_by_definition: dict[int, str],
    active_interfaces: set[tuple[str, int, int]],
) -> None:
    port_ranges: set[tuple[str, int, int]] = set()
    for node in nodes:
        if type(node).__name__ != "PortSymbol":
            continue
        name = str(getattr(node, "name", ""))
        try:
            declaration = _range_for_location(catalog, getattr(node, "location", None), name)
        except RenameIndexError:
            continue
        port_ranges.add((declaration.file, declaration.start, declaration.end))
    for node in nodes:
        node_type = type(node).__name__
        name = str(getattr(node, "name", ""))
        if not name:
            continue
        if node_type in {"VariableSymbol", "NetSymbol"}:
            try:
                declaration = _range_for_location(catalog, getattr(node, "location", None), name)
            except RenameIndexError:
                # A macro-generated declaration has no physical identifier
                # owned by this source unit.  It is semantic evidence only,
                # never a fabricated edit target.
                continue
            key = (declaration.file, declaration.start, declaration.end)
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, module, owner_kind = _owner_info(
                catalog, definition, modules_by_definition, interfaces_by_definition
            )
            if key in port_ranges:
                if "ports" not in selected and owner_kind != "interface":
                    continue
            if owner_kind == "module" and "signals" in selected and key not in port_ranges:
                support, reason, abi = _category_support(
                    "signals", module, top=catalog.source_set.top,
                    interface_active=True, aggregate_active=True,
                )
                _add_working(
                    records, target_map, catalog=catalog, category="signals", kind="signal",
                    semantic_kind=node_type, name=name, declaration=declaration,
                    owner_module=owner_module, semantic_owner=semantic_owner,
                    impact="internal_signal", abi=abi, targets=(node,), support=support, reason=reason,
                )
            elif owner_kind == "interface" and "interface" in selected:
                interface_range = _definition_key(catalog, definition)
                active = catalog.source_set.top is None or (interface_range in active_interfaces if interface_range else False)
                support, reason, abi = _category_support(
                    "interface", None, top=catalog.source_set.top,
                    interface_active=active, aggregate_active=True,
                )
                _add_working(
                    records, target_map, catalog=catalog, category="interface", kind="interface_member",
                    semantic_kind=node_type, name=name, declaration=declaration,
                    owner_module=owner_module, semantic_owner=semantic_owner,
                    impact="interface_member", abi=abi, targets=(node,), support=support, reason=reason,
                )
        elif node_type == "PortSymbol":
            try:
                declaration = _range_for_location(catalog, getattr(node, "location", None), name)
            except RenameIndexError:
                continue
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, module, owner_kind = _owner_info(
                catalog, definition, modules_by_definition, interfaces_by_definition
            )
            if owner_kind == "module" and "ports" in selected:
                support, reason, abi = _category_support(
                    "ports", module, top=catalog.source_set.top,
                    interface_active=True, aggregate_active=True,
                )
                targets = (node, getattr(node, "internalSymbol", None))
                _add_working(
                    records, target_map, catalog=catalog, category="ports", kind="module_port",
                    semantic_kind=node_type, name=name, declaration=declaration,
                    owner_module=owner_module, semantic_owner=semantic_owner,
                    impact="module_abi", abi=abi, targets=targets, support=support, reason=reason,
                )
            elif owner_kind == "interface" and "interface" in selected:
                _add_working(
                    records, target_map, catalog=catalog, category="interface", kind="interface_port",
                    semantic_kind=node_type, name=name, declaration=declaration,
                    owner_module=owner_module, semantic_owner=semantic_owner,
                    impact="interface_member", abi="internal", targets=(node,),
                )
        elif node_type == "ModportSymbol" and "interface" in selected:
            declaration = _range_for_location(catalog, getattr(node, "location", None), name)
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, _module, _ = _owner_info(
                catalog, definition, modules_by_definition, interfaces_by_definition
            )
            _add_working(
                records, target_map, catalog=catalog, category="interface",
                kind="modport" if node_type == "ModportSymbol" else "modport_member",
                semantic_kind=node_type, name=name, declaration=declaration,
                owner_module=owner_module, semantic_owner=semantic_owner,
                impact="interface_abi", abi="internal", targets=(node,),
            )
        elif node_type == "InstanceSymbol" and getattr(node, "isInterface", False) and "interface" in selected:
            declaration = _range_for_location(catalog, getattr(node, "location", None), name)
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, module, _ = _owner_info(
                catalog, definition, modules_by_definition, interfaces_by_definition
            )
            support, reason, abi = _category_support(
                "interface", module, top=catalog.source_set.top,
                interface_active=True, aggregate_active=True, interface_instance=True,
            )
            _add_working(
                records, target_map, catalog=catalog, category="interface", kind="interface_instance",
                semantic_kind=node_type, name=name, declaration=declaration,
                owner_module=owner_module, semantic_owner=semantic_owner,
                impact="interface_instance", abi=abi, targets=(node,), support=support, reason=reason,
            )
        elif node_type == "InstanceArraySymbol" and "interface" in selected:
            elements = _interface_leaf_elements(node)
            if not elements:
                continue
            declaration = _range_for_location(catalog, getattr(node, "location", None), name)
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, module, _ = _owner_info(
                catalog, definition, modules_by_definition, interfaces_by_definition
            )
            support, reason, abi = _category_support(
                "interface", module, top=catalog.source_set.top,
                interface_active=True, aggregate_active=True, interface_instance=True,
            )
            _add_working(
                records, target_map, catalog=catalog, category="interface",
                kind="interface_instance_array", semantic_kind=node_type,
                name=name, declaration=declaration, owner_module=owner_module,
                semantic_owner=semantic_owner, impact="interface_instance",
                abi=abi, targets=(node, *elements), support=support, reason=reason,
            )


def _type_occurrence_range(catalog: SourceCatalog, node: object, expected: str) -> SourceRange | None:
    declared = getattr(node, "declaredType", None)
    syntax = getattr(declared, "typeSyntax", None)
    if _kind_name(getattr(syntax, "kind", None)) != "NamedType":
        return None
    return _syntax_identifier_range(catalog, getattr(syntax, "name", None), expected)


def _instance_type_occurrence(catalog: SourceCatalog, node: object, expected: str) -> SourceRange | None:
    syntax = getattr(node, "syntax", None)
    parent = getattr(syntax, "parent", None)
    return _range_for_token(catalog, getattr(parent, "type", None), expected)


def _claim_occurrence(
    record: _WorkingSymbol,
    occurrence: SymbolOccurrence,
    range_claims: dict[tuple[str, int, int], dict[str, set[str]]],
) -> None:
    """Add one occurrence while retaining every cross-record claim."""

    source_range = occurrence.source_range
    key = (source_range.file, source_range.start, source_range.end)
    # A declaration and an occurrence with the same physical range are the
    # same edit.  Keep the declaration as the canonical range, but retain the
    # claim below so a different semantic record cannot be silently merged.
    declaration_key = (
        record.declaration.file,
        record.declaration.start,
        record.declaration.end,
    )
    if key != declaration_key:
        # A repeated semantic walk of one target is the same edit, not a new
        # claim.  Claims by different semantic records remain visible below.
        record.occurrences.setdefault(key, occurrence)
    range_claims.setdefault(key, {}).setdefault(record.symbol_id, set()).add(
        occurrence.provenance
    )


def _resolve_range_claims(
    records: dict[str, _WorkingSymbol],
    range_claims: dict[tuple[str, int, int], dict[str, set[str]]],
) -> dict[str, tuple[dict[str, object], ...]]:
    """Resolve duplicate physical claims without weakening range validation."""

    issues: dict[str, list[dict[str, object]]] = {}
    macro_provenance = {"semantic_macro_argument", "semantic_macro_body"}
    for source_key, claims in sorted(range_claims.items()):
        owners = set(claims)
        if len(owners) < 2:
            continue
        categories = {records[symbol_id].category for symbol_id in owners}
        is_macro_conflict = any(
            provenance in macro_provenance
            for provenances in claims.values()
            for provenance in provenances
        )
        reason = (
            "macro_origin_conflict"
            if is_macro_conflict
            else "cross_record_range_conflict"
        )
        issue = {
            "file": source_key[0],
            "start": source_key[1],
            "end": source_key[2],
            "message": reason,
        }
        for category in sorted(categories):
            issues.setdefault(category, []).append(issue)
        for symbol_id in owners:
            record = records[symbol_id]
            # A shared range can never be emitted as two edits.  The
            # declaration-level record remains as the diagnostic anchor.
            record.occurrences.pop(source_key, None)
            if is_macro_conflict:
                if record.support == "eligible":
                    record.support = "unsupported"
                    record.reason = reason
            elif record.support == "eligible":
                record.support = "preserved"
                record.reason = reason
        if not is_macro_conflict:
            # Unknown cross-record ownership is not safely resolvable.  Keep
            # the entire affected core group fail-closed, not just the claim.
            for record in records.values():
                if record.category in categories and record.support == "eligible":
                    record.support = "preserved"
                    record.reason = reason
    return {
        category: tuple(
            sorted(
                category_issues,
                key=lambda item: (
                    item["file"], item["start"], item["end"], item["message"]
                ),
            )
        )
        for category, category_issues in issues.items()
    }


def _apply_group_binding_issues(
    records: dict[str, _WorkingSymbol],
) -> dict[str, tuple[dict[str, object], ...]]:
    """Make every unknown binding issue transactional at core-group scope."""

    known_per_record_reasons = {
        "selected_top_boundary",
        "outside_top_closure",
        "macro_origin_conflict",
    }
    unknown_by_category: dict[str, list[_WorkingSymbol]] = {}
    for record in records.values():
        if record.reason is not None and record.reason not in known_per_record_reasons:
            unknown_by_category.setdefault(record.category, []).append(record)

    issues: dict[str, tuple[dict[str, object], ...]] = {}
    for category, unknown in unknown_by_category.items():
        ordered = sorted(
            unknown,
            key=lambda item: (
                item.declaration.file,
                item.declaration.start,
                item.declaration.end,
                item.reason or "",
            ),
        )
        primary_reason = ordered[0].reason or "unknown_binding_issue"
        for record in records.values():
            if record.category == category and record.support == "eligible":
                record.support = "preserved"
                record.reason = primary_reason
        issues[category] = tuple(
            {
                "file": record.declaration.file,
                "start": record.declaration.start,
                "message": record.reason,
            }
            for record in ordered
        )
    return issues


def _collect_occurrences(
    catalog: SourceCatalog,
    nodes: list[Any],
    target_map: dict[int, str],
    alias_map: dict[tuple[str, int, int], str],
    records: dict[str, _WorkingSymbol],
) -> dict[str, tuple[dict[str, object], ...]]:
    range_claims: dict[tuple[str, int, int], dict[str, set[str]]] = {}
    for node in nodes:
        node_type = type(node).__name__
        if node_type == "ModportPortSymbol":
            symbol_id = _record_for_semantic_target(
                catalog, records, target_map, getattr(node, "internalSymbol", None)
            )
            if symbol_id is not None:
                record = records[symbol_id]
                source_range = _syntax_identifier_range(
                    catalog, getattr(node, "syntax", None), record.name
                )
                if source_range is not None:
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_modport_member"),
                        range_claims,
                    )
            continue
        if node_type in {"NamedValueExpression", "HierarchicalValueExpression", "ArbitrarySymbolExpression"}:
            target = getattr(node, "symbol", None)
            symbol_id = _record_for_semantic_target(catalog, records, target_map, target)
            if symbol_id is None:
                continue
            record = records[symbol_id]
            value = record.name
            source_range, provenance = _semantic_expression_range(catalog, node, value)
            if source_range is None:
                continue
            occurrence = SymbolOccurrence(source_range, provenance)
            _claim_occurrence(record, occurrence, range_claims)
        elif node_type == "MemberAccessExpression":
            target = getattr(node, "member", None)
            symbol_id = _record_for_semantic_target(catalog, records, target_map, target)
            if symbol_id is None:
                continue
            record = records[symbol_id]
            syntax = getattr(node, "syntax", None)
            source_range = _syntax_identifier_range(catalog, syntax, record.name)
            if source_range is None:
                continue
            occurrence = SymbolOccurrence(source_range, "semantic_member")
            _claim_occurrence(record, occurrence, range_claims)
        declared = getattr(node, "declaredType", None)
        target = getattr(declared, "type", None)
        if type(target).__name__ == "TypeAliasType":
            alias_key = _definition_key(catalog, target)
            symbol_id = alias_map.get(alias_key) if alias_key is not None else None
            if symbol_id is not None:
                source_range = _type_occurrence_range(catalog, node, records[symbol_id].name)
                if source_range is not None:
                    record = records[symbol_id]
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_type"),
                        range_claims,
                    )
        if node_type == "ConversionExpression" and not getattr(node, "isImplicit", False):
            target = getattr(node, "type", None)
            alias_key = _definition_key(catalog, target) if type(target).__name__ == "TypeAliasType" else None
            symbol_id = alias_map.get(alias_key) if alias_key is not None else None
            if symbol_id is not None:
                syntax = getattr(node, "syntax", None)
                source_range = _syntax_identifier_range(catalog, getattr(syntax, "left", None), records[symbol_id].name)
                if source_range is not None:
                    record = records[symbol_id]
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_cast"),
                        range_claims,
                    )
        if node_type == "InstanceSymbol" and getattr(node, "isInterface", False):
            definition = getattr(node, "definition", None)
            definition_key = _definition_key(catalog, definition)
            interface_id = None
            if definition_key is not None:
                for candidate in records.values():
                    if candidate.kind == "interface_type" and candidate.declaration == SourceRange(*definition_key):
                        interface_id = candidate.symbol_id
                        break
            if interface_id is not None:
                source_range = _instance_type_occurrence(catalog, node, records[interface_id].name)
                if source_range is not None:
                    _claim_occurrence(
                        records[interface_id],
                        SymbolOccurrence(source_range, "semantic_interface_type"),
                        range_claims,
                    )
        if node_type == "InterfacePortSymbol":
            interface_def = getattr(node, "interfaceDef", None)
            definition_key = _definition_key(catalog, interface_def)
            interface_id = None
            if definition_key is not None:
                for candidate in records.values():
                    if candidate.kind == "interface_type" and candidate.declaration == SourceRange(*definition_key):
                        interface_id = candidate.symbol_id
                        break
            if interface_id is not None:
                syntax = getattr(node, "syntax", None)
                header = getattr(getattr(syntax, "parent", None), "header", None)
                type_syntax = getattr(header, "dataType", None)
                source_range = _syntax_identifier_range(
                    catalog, type_syntax, records[interface_id].name
                )
                if source_range is not None:
                    _claim_occurrence(
                        records[interface_id],
                        SymbolOccurrence(source_range, "semantic_interface_port_type"),
                        range_claims,
                    )
        if node_type == "InstanceArraySymbol":
            elements = _interface_leaf_elements(node)
            if not elements:
                continue
            definition_key = _definition_key(catalog, getattr(elements[0], "definition", None))
            interface_id = None
            if definition_key is not None:
                for candidate in records.values():
                    if candidate.kind == "interface_type" and candidate.declaration == SourceRange(*definition_key):
                        interface_id = candidate.symbol_id
                        break
            if interface_id is not None:
                parent = getattr(getattr(node, "syntax", None), "parent", None)
                source_range = _range_for_token(
                    catalog, getattr(parent, "type", None), records[interface_id].name
                )
                if source_range is not None:
                    _claim_occurrence(
                        records[interface_id],
                        SymbolOccurrence(source_range, "semantic_interface_array_type"),
                        range_claims,
                    )
        if node_type == "InstanceSymbol" and getattr(node, "isModule", False):
            syntax = getattr(node, "syntax", None)
            syntax_connections = [
                item for item in getattr(syntax, "connections", ())
                if type(item).__name__ != "Token"
            ]
            for connection_syntax, connection in zip(syntax_connections, getattr(node, "portConnections", ())):
                port = getattr(connection, "port", None)
                symbol_id = target_map.get(id(port))
                if symbol_id is None:
                    symbol_id = target_map.get(id(getattr(port, "internalSymbol", None)))
                if symbol_id is None:
                    continue
                label = getattr(connection_syntax, "name", None)
                record = records[symbol_id]
                source_range = _range_for_token(catalog, label, record.name)
                if source_range is None:
                    continue
                _claim_occurrence(
                    record,
                    SymbolOccurrence(source_range, "semantic_port_connection"),
                    range_claims,
                )
    return _resolve_range_claims(records, range_claims)


def _register_interface_types(
    catalog: SourceCatalog,
    selected: set[str],
    records: dict[str, _WorkingSymbol],
    target_map: dict[int, str],
    nodes: list[Any],
    interfaces_by_definition: dict[int, str],
    active_interfaces: set[tuple[str, int, int]],
) -> None:
    if "interface" not in selected:
        return
    for node in nodes:
        if type(node).__name__ != "InstanceBodySymbol":
            continue
        syntax = getattr(node, "syntax", None)
        if _kind_name(getattr(syntax, "kind", None)) != "InterfaceDeclaration":
            continue
        definition = getattr(node, "definition", None)
        declaration = _definition_range(catalog, definition)
        if declaration is None:
            continue
        name = str(getattr(definition, "name", ""))
        key = (declaration.file, declaration.start, declaration.end)
        support = "eligible"
        reason = None
        if catalog.source_set.top is not None and key not in active_interfaces:
            support, reason = "preserved", "outside_top_closure"
        record = _add_working(
            records, target_map, catalog=catalog, category="interface", kind="interface_type",
            semantic_kind=type(definition).__name__, name=name, declaration=declaration,
            owner_module=interfaces_by_definition.get(
                id(definition),
                f"interface:{declaration.file}:{declaration.start}:{declaration.end}",
            ),
            semantic_owner=interfaces_by_definition.get(
                id(definition),
                f"interface:{declaration.file}:{declaration.start}:{declaration.end}",
            ),
            impact="interface_type", abi="internal", targets=(definition,), support=support, reason=reason,
        )
        target_map[id(definition)] = record.symbol_id


def _category_outcomes(
    selected: tuple[str, ...],
    records: tuple[SourceSymbol, ...],
    range_issues: dict[str, tuple[dict[str, object], ...]],
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    selected_set = set(selected)
    by_category = {
        category: [item for item in records if item.category == category]
        for category in CANONICAL_CATEGORIES
    }
    for category in CANONICAL_CATEGORIES:
        if category not in selected_set:
            result.append({
                "category": category,
                "status": "empty",
                "candidate": 0,
                "rename": 0,
                "preserve": 0,
                "unsupported": 0,
                "issues": [],
            })
            continue
        items = by_category[category]
        if not items:
            status = "empty"
        elif any(item.support == "unsupported" for item in items):
            status = "preserved"
        elif any(item.support == "preserved" for item in items):
            status = "preserved"
        else:
            status = "renamed"
        issues = list(range_issues.get(category, ()))
        for item in items:
            if item.reason is not None:
                issue = {
                    "file": item.declaration.file,
                    "start": item.declaration.start,
                    "message": item.reason,
                }
                if issue not in issues:
                    issues.append(issue)
        result.append({
            "category": category,
            "status": status,
            "candidate": len(items),
            "rename": sum(item.support == "eligible" for item in items),
            "preserve": sum(item.support == "preserved" for item in items),
            "unsupported": sum(item.support == "unsupported" for item in items),
            "issues": issues,
        })
    return tuple(result)


def build_rename_index(source_catalog: SourceCatalog, *, categories: Iterable[str]) -> RenameIndex:
    """Build the four-group index from one already compiled PySlang catalog."""

    if not isinstance(source_catalog, SourceCatalog):
        raise RenameIndexError("RENAME_INDEX_INPUT_INVALID", "input is not SourceCatalog")
    try:
        selected = normalize_categories(categories, default=False)
    except CategoryRegistryError as error:
        raise RenameIndexError("RENAME_INDEX_CATEGORY_INVALID", error.message) from error
    nodes: list[Any] = []
    source_catalog.catalog_root.visit(nodes.append)
    _module_range_map, modules_by_definition = _module_maps(source_catalog)
    interfaces_by_definition = _interface_ids(source_catalog, nodes)
    active_interfaces = _top_active_interfaces(source_catalog)
    active_types = _top_active_types(source_catalog)
    records: dict[str, _WorkingSymbol] = {}
    target_map: dict[int, str] = {}
    alias_map: dict[tuple[str, int, int], str] = {}
    _register_interface_types(
        source_catalog, set(selected), records, target_map, nodes,
        interfaces_by_definition, active_interfaces,
    )
    _register_structs(
        source_catalog, set(selected), records, target_map, alias_map, nodes,
        modules_by_definition, interfaces_by_definition, active_types,
    )
    _register_core_declarations(
        source_catalog, set(selected), records, target_map, nodes,
        modules_by_definition, interfaces_by_definition, active_interfaces,
    )
    range_issues = _collect_occurrences(
        source_catalog, nodes, target_map, alias_map, records
    )
    group_issues = _apply_group_binding_issues(records)
    for category, category_issues in group_issues.items():
        existing = list(range_issues.get(category, ()))
        for issue in category_issues:
            if issue not in existing:
                existing.append(issue)
        range_issues[category] = tuple(existing)
    symbols = tuple(
        SourceSymbol(
            symbol_id=item.symbol_id, category=item.category, kind=item.kind,
            semantic_kind=item.semantic_kind, name=item.name, declaration=item.declaration,
            owner_module=item.owner_module, semantic_owner=item.semantic_owner,
            occurrences=tuple(item.occurrences[key] for key in sorted(item.occurrences)),
            impact=item.impact, abi=item.abi, support=item.support, reason=item.reason,
        )
        for item in sorted(records.values(), key=lambda value: (value.declaration.file, value.declaration.start, value.category, value.name))
    )
    decisions = tuple(
        RenameDecision(
            symbol_id=symbol.symbol_id, category=symbol.category,
            action=("unsupported" if symbol.support == "unsupported" else "preserve" if symbol.support == "preserved" else "rename"),
            reason=symbol.reason,
        )
        for symbol in symbols
    )
    return RenameIndex(
        schema_version=2,
        source_catalog=source_catalog,
        selected_categories=selected,
        symbols=symbols,
        decisions=decisions,
        category_outcomes=_category_outcomes(selected, symbols, range_issues),
    )


__all__ = [
    "RenameDecision", "RenameIndex", "RenameIndexError", "SourceSymbol",
    "SymbolOccurrence", "build_rename_index",
]
