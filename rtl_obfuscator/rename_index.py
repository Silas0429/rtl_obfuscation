"""PySlang-backed physical rename index.

The index is deliberately small: PySlang owns name, type, owner and target
resolution; this module only turns source-backed semantic objects into
validated physical identifier ranges.  It does not perform name lookup or
parse SystemVerilog text.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import pyslang

from .category_registry_vnext import CANONICAL_CATEGORIES, CategoryRegistryError, normalize_categories
from .performance_probe import (
    RENAME_DECLARATIONS,
    RENAME_FINALIZE,
    RENAME_NAME_COMPLETENESS,
    RENAME_OCCURRENCES,
    RENAME_SEMANTIC_INVENTORY,
    RENAME_SYNTAX_INVENTORY,
    RENAME_UNELABORATED,
    StageObserver,
    _observe,
)
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
class _RangePathContext:
    """Private, single-build memo for physical paths and byte ranges."""

    source_root: Path
    buffer_files: dict[object, str | None] = field(default_factory=dict)
    range_bytes: dict[tuple[str, int, int], bytes] = field(default_factory=dict)
    path_requests: int = 0
    path_resolutions: int = 0
    range_requests: int = 0
    range_reads: int = 0
    range_cache_hits: int = 0
    reference_candidate_checks: int = 0

    @classmethod
    def for_catalog(cls, catalog: SourceCatalog) -> _RangePathContext:
        # This is deliberately the only source-root normalization in one
        # build.  Every later physical read and buffer lookup reuses it.
        try:
            root = catalog.source_catalog_root
        except AttributeError:
            root = catalog.source_set.source_root
        return cls(Path(root).resolve())

    def file_for_buffer(self, catalog: SourceCatalog, buffer: object) -> str | None:
        """Resolve one hashable buffer once; unhashable wrappers stay uncached."""

        self.path_requests += 1
        try:
            cached = self.buffer_files.get(buffer)
        except TypeError:
            self.path_resolutions += 1
            try:
                return self._resolve_buffer(catalog, buffer)
            except RenameIndexError:
                return None
        if buffer in self.buffer_files:
            return cached
        self.path_resolutions += 1
        try:
            value = self._resolve_buffer(catalog, buffer)
        except RenameIndexError:
            value = None
        self.buffer_files[buffer] = value
        return value

    def _resolve_buffer(self, catalog: SourceCatalog, buffer: object) -> str:
        manager = catalog.catalog_source_manager
        try:
            absolute = Path(manager.getFullPath(buffer)).resolve()
            return absolute.relative_to(self.source_root).as_posix()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise RenameIndexError(
                "RENAME_INDEX_RANGE_INVALID", "semantic location is outside SourceSet"
            ) from error

    def read_range(self, catalog: SourceCatalog, file: str, start: int, end: int) -> bytes:
        """Read and memoize exactly one normalized physical byte interval."""

        normalized_file = PurePosixPath(file).as_posix()
        key = (normalized_file, int(start), int(end))
        self.range_requests += 1
        try:
            data = self.range_bytes[key]
        except KeyError:
            pass
        else:
            self.range_cache_hits += 1
            return data
        relative = PurePosixPath(normalized_file)
        if relative.is_absolute() or ".." in relative.parts:
            raise RenameIndexError(
                "RENAME_INDEX_RANGE_INVALID",
                "semantic identifier location does not match source bytes",
                file=file,
                start=start,
            )
        if start < 0 or end <= start:
            raise RenameIndexError(
                "RENAME_INDEX_RANGE_INVALID",
                "semantic identifier location does not match source bytes",
                file=file,
                start=start,
            )
        self.range_reads += 1
        path = self.source_root / normalized_file
        length = end - start
        try:
            with path.open("rb") as source:
                source.seek(start)
                data = source.read(length)
        except OSError as error:
            raise RenameIndexError(
                "RENAME_INDEX_SOURCE_INVALID", f"cannot read source file {file}: {error}"
            ) from error
        if len(data) != length:
            raise RenameIndexError(
                "RENAME_INDEX_RANGE_INVALID",
                "semantic identifier location does not match source bytes",
                file=file,
                start=start,
            )
        self.range_bytes[key] = data
        return data


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
    targets: set[object] = field(default_factory=set)
    occurrences: dict[tuple[str, int, int], SymbolOccurrence] = field(default_factory=dict)


@dataclass(frozen=True)
class _OrderedSemanticNode:
    """One semantic node together with the ordinal assigned by ``visit``."""

    ordinal: int
    node: Any


@dataclass(frozen=True)
class _SemanticWorkset:
    """The ordered semantic projections used by one RenameIndex build.

    PySlang semantic roots are intentionally visited here, once per distinct
    root.  Keeping the ordinal alongside each node makes it explicit that all
    later projections consume the compiler's visit order rather than the
    incidental order of a set or a dictionary.
    """

    catalog: tuple[_OrderedSemanticNode, ...]
    top: tuple[_OrderedSemanticNode, ...]
    instance_body_nodes: tuple[Any, ...] = field(init=False)
    struct_nodes: tuple[Any, ...] = field(init=False)
    declaration_nodes: tuple[Any, ...] = field(init=False)
    occurrence_nodes: tuple[Any, ...] = field(init=False)
    dead_source_nodes: tuple[Any, ...] = field(init=False)
    completeness_nodes: tuple[Any, ...] = field(init=False)
    top_interface_nodes: tuple[Any, ...] = field(init=False)
    top_type_nodes: tuple[Any, ...] = field(init=False)

    def __post_init__(self) -> None:
        catalog = self.catalog
        declaration_kinds = {
            "InstanceBodySymbol",
            "TypeAliasType",
            "PortSymbol",
            "VariableSymbol",
            "NetSymbol",
            "ModportSymbol",
            "InstanceSymbol",
            "InstanceArraySymbol",
        }
        occurrence_kinds = {
            "InstanceSymbol",
            "PortSymbol",
            "ModportPortSymbol",
            "NamedValueExpression",
            "HierarchicalValueExpression",
            "ArbitrarySymbolExpression",
            "MemberAccessExpression",
            "ConversionExpression",
            "InterfacePortSymbol",
            "InstanceArraySymbol",
        }
        instance_body: list[Any] = []
        struct: list[Any] = []
        declaration: list[Any] = []
        occurrence: list[Any] = []
        dead_source: list[Any] = []
        completeness: list[Any] = []
        # Build every catalog projection in one in-memory pass.  This pass is
        # intentionally after the single semantic root visit; it does not
        # inspect children or otherwise recreate a semantic collector.
        for ordered in catalog:
            node = ordered.node
            node_type = type(node).__name__
            declared_type = _safe_attr(_safe_attr(node, "declaredType"), "type")
            has_alias = type(declared_type).__name__ == "TypeAliasType"
            if (
                bool(_safe_attr(node, "name", ""))
                or _safe_attr(node, "symbol") is not None
                or _safe_attr(node, "member") is not None
                or node_type == "TypeAliasType"
                or declared_type is not None
            ):
                # A non-TypeAlias declared type may still carry an inline or
                # nested aggregate whose FieldSymbols are reached by the
                # canonical aggregate walk.  Keep it in the generic proof
                # projection rather than narrowing by known node shape.
                completeness.append(node)
            if node_type == "InstanceBodySymbol":
                instance_body.append(node)
            if node_type == "TypeAliasType":
                struct.append(node)
            if node_type in declaration_kinds:
                declaration.append(node)
            if node_type in occurrence_kinds or has_alias:
                occurrence.append(node)
            if node_type in {
                "InstanceBodySymbol",
                "PackageSymbol",
                "GenerateBlockSymbol",
            }:
                dead_source.append(node)

        top_interface: list[Any] = []
        top_type: list[Any] = []
        # The top root is distinct only for the explicit overlay view.  It is
        # visited at most once by ``collect`` and classified once here.
        for ordered in self.top:
            node = ordered.node
            node_type = type(node).__name__
            declared_type = _safe_attr(_safe_attr(node, "declaredType"), "type")
            if node_type == "InterfacePortSymbol" or (
                node_type == "InstanceSymbol"
                and bool(_safe_attr(node, "isInterface", False))
            ):
                top_interface.append(node)
            if type(declared_type).__name__ == "TypeAliasType" or (
                node_type == "ConversionExpression"
                and type(_safe_attr(node, "type")).__name__ == "TypeAliasType"
            ):
                top_type.append(node)

        object.__setattr__(self, "instance_body_nodes", tuple(instance_body))
        object.__setattr__(self, "struct_nodes", tuple(struct))
        object.__setattr__(self, "declaration_nodes", tuple(declaration))
        object.__setattr__(self, "occurrence_nodes", tuple(occurrence))
        object.__setattr__(self, "dead_source_nodes", tuple(dead_source))
        object.__setattr__(self, "completeness_nodes", tuple(completeness))
        object.__setattr__(self, "top_interface_nodes", tuple(top_interface))
        object.__setattr__(self, "top_type_nodes", tuple(top_type))

    @classmethod
    def collect(cls, source_catalog: SourceCatalog) -> _SemanticWorkset:
        catalog_nodes: list[Any] = []
        source_catalog.catalog_root.visit(catalog_nodes.append)
        catalog = tuple(
            _OrderedSemanticNode(ordinal, node)
            for ordinal, node in enumerate(catalog_nodes)
        )
        if source_catalog.top_root is None:
            top: tuple[_OrderedSemanticNode, ...] = ()
        elif source_catalog.top_root is source_catalog.catalog_root:
            top = catalog
        else:
            top_nodes: list[Any] = []
            source_catalog.top_root.visit(top_nodes.append)
            top = tuple(
                _OrderedSemanticNode(ordinal, node)
                for ordinal, node in enumerate(top_nodes)
            )
        return cls(catalog=catalog, top=top)

    @property
    def nodes(self) -> tuple[Any, ...]:
        return tuple(item.node for item in self.catalog)

    @property
    def top_nodes(self) -> tuple[Any, ...]:
        return tuple(item.node for item in self.top)


@dataclass
class _RecordPhysicalIndex:
    """Direct declaration-key index built after the ordered declaration pass."""

    by_key: dict[tuple[str, int, int], dict[str, tuple[str, ...]]] = field(
        default_factory=dict
    )

    @classmethod
    def from_records(
        cls, records: dict[str, _WorkingSymbol]
    ) -> _RecordPhysicalIndex:
        by_key: dict[tuple[str, int, int], dict[str, list[str]]] = {}
        for record in records.values():
            key = (
                record.declaration.file,
                record.declaration.start,
                record.declaration.end,
            )
            by_key.setdefault(key, {}).setdefault(record.category, []).append(
                record.symbol_id
            )
        return cls(
            by_key={
                key: {
                    category: tuple(dict.fromkeys(symbol_ids))
                    for category, symbol_ids in categories.items()
                }
                for key, categories in by_key.items()
            }
        )

    def resolve(
        self,
        declaration: SourceRange,
        *,
        category: str | None = None,
    ) -> str | None:
        key = (declaration.file, declaration.start, declaration.end)
        categories = self.by_key.get(key)
        if not categories:
            return None
        if category is not None:
            candidates = categories.get(category, ())
            return candidates[0] if len(candidates) == 1 else None
        for name in CANONICAL_CATEGORIES:
            candidates = categories.get(name, ())
            if len(candidates) > 1:
                return None
            if len(candidates) == 1:
                return candidates[0]
        return None


@dataclass
class _ReferenceQueryStats:
    """Observable count of range-index candidate probes for compact evidence."""

    candidate_checks: int = 0


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


def _safe_attr(value: object, name: str, default: object = None) -> object:
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _source_bytes(
    catalog: SourceCatalog, file: str, *, context: _RangePathContext | None = None
) -> bytes:
    try:
        root = context.source_root if context is not None else Path(catalog.source_catalog_root)
        return (root / file).read_bytes()
    except AttributeError:
        root = context.source_root if context is not None else Path(catalog.source_set.source_root)
        return (root / file).read_bytes()
    except OSError as error:
        raise RenameIndexError("RENAME_INDEX_SOURCE_INVALID", f"cannot read source file {file}: {error}") from error


def _file_for_buffer(
    catalog: SourceCatalog,
    buffer: object,
    *,
    context: _RangePathContext | None = None,
) -> str:
    if context is None:
        context = _RangePathContext.for_catalog(catalog)
    file = context.file_for_buffer(catalog, buffer)
    if file is None:
        raise RenameIndexError("RENAME_INDEX_RANGE_INVALID", "semantic location is outside SourceSet")
    return file


def _physical_location(catalog: SourceCatalog, location: object) -> object:
    """Map one PySlang location to its physical source location.

    Macro expansion is the only supported virtual-location case.  The
    SourceManager is the authority for the original token; no textual search
    is performed after this conversion.
    """

    if location is None:
        return None
    manager = catalog.catalog_source_manager
    if manager.isMacroLoc(location):
        return manager.getFullyOriginalLoc(location)
    return location


def _range_for_location(
    catalog: SourceCatalog,
    location: object,
    name: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange:
    if location is None or not name:
        raise RenameIndexError("RENAME_INDEX_SOURCE_INVALID", "source-backed semantic object has no identifier")
    if context is None:
        context = _RangePathContext.for_catalog(catalog)
    try:
        location = _physical_location(catalog, location)
        file = _file_for_buffer(catalog, location.buffer, context=context)
        start = int(location.offset)
    except Exception as error:
        raise RenameIndexError("RENAME_INDEX_RANGE_INVALID", "semantic location is invalid") from error
    result = SourceRange(file, start, start + len(name.encode("utf-8")))
    try:
        data = context.read_range(catalog, file, result.start, result.end)
    except RenameIndexError:
        raise
    if data != name.encode("utf-8"):
        raise RenameIndexError(
            "RENAME_INDEX_RANGE_INVALID",
            "semantic identifier location does not match source bytes",
            file=file,
            start=start,
        )
    return result


def _range_for_token(
    catalog: SourceCatalog,
    token: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    try:
        if token is None or _safe_attr(token, "isMissing", False):
            return None
        raw_value = _safe_attr(token, "rawText", b"")
        raw = raw_value.encode("utf-8") if isinstance(raw_value, str) else bytes(raw_value)
        location = _safe_attr(token, "location")
    except Exception as error:
        raise RenameIndexError("RENAME_INDEX_RANGE_INVALID", "typed token is invalid") from error
    if raw != expected.encode("utf-8"):
        return None
    return _range_for_location(catalog, location, expected, context=context)


def _typed_declaration_token(node_type: str, syntax: object) -> object:
    """Return the one typed syntax token for a semantic declaration shape."""

    if syntax is None:
        return None
    if type(syntax).__name__ == "Token":
        return syntax
    if node_type == "ModportSymbol":
        return _safe_attr(syntax, "name")
    if node_type in {"InstanceSymbol", "InstanceArraySymbol"}:
        return _safe_attr(_safe_attr(syntax, "decl"), "name")
    if node_type in {"InstanceBodySymbol", "DefinitionSymbol"}:
        return _safe_attr(_safe_attr(syntax, "header"), "name")
    return _safe_attr(syntax, "name")


def _declaration_tokens(node_type: str, semantic: object, syntax: object) -> tuple[object, ...]:
    """Collect only direct typed declaration tokens exposed by PySlang.

    ANSI ports can expose the same declarator through both PortSymbol.syntax
    and PortSymbol.internalSymbol.syntax.  These are equivalent semantic
    evidence, not two textual candidates.  No token walk or name lookup is
    performed here.
    """

    candidates: list[object] = []
    semantic_syntax = _safe_attr(semantic, "syntax")
    internal_syntax = _safe_attr(_safe_attr(semantic, "internalSymbol"), "syntax")
    syntax_candidates = (
        (internal_syntax, syntax, semantic_syntax)
        if node_type == "PortSymbol"
        else (syntax, semantic_syntax, internal_syntax)
    )
    for candidate_syntax in syntax_candidates:
        token = _typed_declaration_token(node_type, candidate_syntax)
        if token is not None and all(token is not previous for previous in candidates):
            candidates.append(token)
    return tuple(candidates)


def _declaration_range(
    catalog: SourceCatalog,
    semantic: object,
    syntax: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange:
    """Resolve a declaration from typed syntax, then direct semantic location.

    The typed token is preferred because it identifies the exact declaration
    token even when the semantic wrapper's location points into an expansion.
    A macro location is converted only by SourceManager and every candidate is
    checked against the original source bytes.  The semantic location is a
    second piece of direct evidence, never a name lookup fallback.
    """

    typed_errors: list[RenameIndexError] = []
    for token in _declaration_tokens(type(semantic).__name__, semantic, syntax):
        try:
            result = _range_for_token(catalog, token, expected, context=context)
        except RenameIndexError as error:
            typed_errors.append(error)
            continue
        if result is not None:
            # The token order is the semantic shape's declared priority:
            # PortSymbol.internalSymbol for non-ANSI declarations, then the
            # port syntax; all other records use their owning syntax first.
            # A second typed view is an elaboration alias, not a second
            # declaration candidate.
            return result
    try:
        return _range_for_location(
            catalog, _safe_attr(semantic, "location"), expected, context=context
        )
    except RenameIndexError as semantic_error:
        if typed_errors:
            raise typed_errors[0]
        raise semantic_error


def _try_declaration_range(
    catalog: SourceCatalog,
    binding_issues: dict[str, list[dict[str, object]]],
    category: str,
    semantic: object,
    syntax: object,
    name: str,
    *,
    candidates: tuple[object, ...] = (),
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    """Resolve one declaration and centralize fail-closed diagnostics."""

    try:
        return _declaration_range(catalog, semantic, syntax, name, context=context)
    except RenameIndexError as error:
        if name:
            _append_binding_issue(
                catalog,
                binding_issues,
                category,
                semantic_kind=type(semantic).__name__,
                name=name,
                candidates=candidates or (semantic, syntax),
                detail=error.message,
                context=context,
            )
        return None


def _diagnostic_location(
    catalog: SourceCatalog,
    *candidates: object,
    context: _RangePathContext | None = None,
) -> tuple[str, int] | None:
    """Return only directly exposed source evidence for a diagnostic.

    This is intentionally not an edit-range resolver.  It may use a direct
    semantic location, its direct syntax location, or a direct syntax source
    range start to explain a failed binding.  It never searches source text or
    chooses an identifier by name.
    """

    manager = catalog.catalog_source_manager
    for candidate in candidates:
        if candidate is None:
            continue
        locations: list[object] = [candidate]
        try:
            locations.append(getattr(candidate, "location", None))
        except Exception:
            pass
        try:
            source_range = getattr(candidate, "sourceRange", None)
            if source_range is not None:
                locations.append(getattr(source_range, "start", None))
        except Exception:
            pass
        for location in locations:
            if location is None:
                continue
            try:
                if manager.isMacroLoc(location):
                    location = manager.getFullyOriginalLoc(location)
                file = _file_for_buffer(catalog, location.buffer, context=context)
                return file, int(location.offset)
            except Exception:
                continue
    return None


def _append_binding_issue(
    catalog: SourceCatalog,
    binding_issues: dict[str, list[dict[str, object]]],
    category: str,
    *,
    semantic_kind: str,
    name: str,
    candidates: tuple[object, ...] = (),
    detail: str | None = None,
    context: _RangePathContext | None = None,
) -> None:
    """Record a source-backed binding failure without inventing a range."""

    issue: dict[str, object] = {
        "message": "source_binding_incomplete",
        "semantic_kind": semantic_kind,
        "name": name,
    }
    location = _diagnostic_location(catalog, *candidates, context=context)
    if location is not None:
        issue["file"], issue["start"] = location
    if detail:
        issue["detail"] = detail
    existing = binding_issues.setdefault(category, [])
    if issue not in existing:
        existing.append(issue)


def _safe_occurrence_range(
    catalog: SourceCatalog,
    binding_issues: dict[str, list[dict[str, object]]],
    record: _WorkingSymbol,
    node: object,
    resolver: Any,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    """Resolve one typed-token range or turn its failure into a group issue."""

    try:
        result = resolver()
    except Exception as error:
        _append_binding_issue(
            catalog,
            binding_issues,
            record.category,
            semantic_kind=record.semantic_kind,
            name=record.name,
            candidates=(node, _safe_attr(node, "syntax")),
            detail=getattr(error, "message", str(error)),
            context=context,
        )
        if record.support == "eligible":
            record.support = "preserved"
            record.reason = "source_binding_incomplete"
        return None
    if result is None and _diagnostic_location(catalog, node, context=context) is not None:
        _append_binding_issue(
            catalog,
            binding_issues,
            record.category,
            semantic_kind=record.semantic_kind,
            name=record.name,
            candidates=(node,),
            detail="semantic target has no unique physical typed token",
            context=context,
        )
        if record.support == "eligible":
            record.support = "preserved"
            record.reason = "source_binding_incomplete"
    return result


def _syntax_identifier_range(
    catalog: SourceCatalog,
    syntax: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    if syntax is None:
        return None
    try:
        # Only use a typed identifier property.  Walking all tokens and
        # choosing a matching name would lose the semantic target when a
        # syntax contains two equal identifiers (for example a scoped member
        # access).
        if type(syntax).__name__ == "Token":
            return _range_for_token(catalog, syntax, expected, context=context)
        identifier = _safe_attr(syntax, "identifier")
        direct = _range_for_token(catalog, identifier, expected, context=context)
        if direct is not None:
            return direct
        if _kind_name(_safe_attr(syntax, "kind")) == "ScopedName":
            right = _safe_attr(syntax, "right")
            return _syntax_identifier_range(catalog, right, expected, context=context)
        if _kind_name(_safe_attr(syntax, "kind")) == "ModportNamedPort":
            return _range_for_token(
                catalog, _safe_attr(syntax, "name"), expected, context=context
            )
        if _kind_name(_safe_attr(syntax, "kind")) == "NamedType":
            name = _safe_attr(syntax, "name")
            return _syntax_identifier_range(catalog, name, expected, context=context)
        return None
    except RenameIndexError:
        raise
    except Exception as error:
        raise RenameIndexError("RENAME_INDEX_RANGE_INVALID", "typed syntax is invalid") from error


def _expression_range(
    catalog: SourceCatalog,
    expression: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    syntax = getattr(expression, "syntax", None)
    result = _syntax_identifier_range(catalog, syntax, expected, context=context)
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
        if context is None:
            context = _RangePathContext.for_catalog(catalog)
        file = _file_for_buffer(catalog, start.buffer, context=context)
        candidate = SourceRange(file, int(start.offset), int(end.offset))
        data = context.read_range(catalog, file, candidate.start, candidate.end)
        if data == expected.encode("utf-8"):
            return candidate
    except (AttributeError, TypeError, ValueError, IndexError):
        return None
    return None


def _semantic_expression_range(
    catalog: SourceCatalog,
    expression: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
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
                return _range_for_location(
                    catalog, original, expected, context=context
                ), provenance
            except RenameIndexError:
                return None, provenance
    except Exception:
        return None, "semantic_reference"
    return _expression_range(
        catalog, expression, expected, context=context
    ), "semantic_reference"


def _definition_range(
    catalog: SourceCatalog,
    definition: object,
    syntax: object = None,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    if definition is None:
        return None
    name = str(_safe_attr(definition, "name", ""))
    try:
        syntax = syntax or _safe_attr(definition, "syntax")
        if syntax is not None:
            return _declaration_range(
                catalog, definition, syntax, name, context=context
            )
        return _range_for_location(
            catalog, _safe_attr(definition, "location"), name, context=context
        )
    except RenameIndexError:
        return None


def _definition_key(
    catalog: SourceCatalog,
    definition: object,
    *,
    context: _RangePathContext | None = None,
) -> tuple[str, int, int] | None:
    value = _definition_range(catalog, definition, context=context)
    return None if value is None else (value.file, value.start, value.end)


def _module_maps(
    catalog: SourceCatalog,
    nodes: Iterable[Any] | None = None,
    *,
    context: _RangePathContext | None = None,
) -> tuple[
    dict[tuple[str, int, int], ModuleOwner | None],
    dict[object, ModuleOwner | None],
]:
    """Build owner indexes from one already collected semantic node sequence."""

    by_range: dict[tuple[str, int, int], ModuleOwner | None] = {}
    for item in catalog.modules:
        key = (item.declaration.file, item.declaration.start, item.declaration.end)
        previous = by_range.get(key)
        if key in by_range and previous != item:
            by_range[key] = None
        elif key not in by_range:
            by_range[key] = item
    by_definition: dict[object, ModuleOwner | None] = {}
    if nodes is None:
        collected: list[Any] = []
        catalog.catalog_root.visit(collected.append)
        nodes = collected
    for node in nodes:
        if type(node).__name__ != "InstanceBodySymbol":
            continue
        definition = getattr(node, "definition", None)
        key = _definition_key(catalog, definition, context=context)
        if key is None or key not in by_range:
            continue
        owner = by_range[key]
        try:
            previous = by_definition.get(definition)
            if definition in by_definition and previous != owner:
                by_definition[definition] = None
            else:
                by_definition[definition] = owner
        except TypeError:
            # A semantic wrapper that cannot be hashed is resolved through its
            # own physical declaration key by ``_owner_info``.
            continue
    return by_range, by_definition


def _interface_ids(
    catalog: SourceCatalog,
    nodes: Iterable[Any],
    *,
    context: _RangePathContext | None = None,
    by_range: dict[tuple[str, int, int], str | None] | None = None,
) -> dict[object, str]:
    """Index interface definitions by wrapper and by physical declaration."""

    result: dict[object, str] = {}
    if by_range is None:
        by_range = {}
    for node in nodes:
        if type(node).__name__ != "InstanceBodySymbol":
            continue
        syntax = getattr(node, "syntax", None)
        if _kind_name(getattr(syntax, "kind", None)) != "InterfaceDeclaration":
            continue
        definition = getattr(node, "definition", None)
        value = _definition_range(catalog, definition, context=context)
        if value is not None:
            key = (value.file, value.start, value.end)
            identifier = f"interface:{value.file}:{value.start}:{value.end}"
            previous = by_range.get(key)
            if key in by_range and previous != identifier:
                by_range[key] = None
            elif key not in by_range:
                by_range[key] = identifier
            try:
                result[definition] = identifier
            except TypeError:
                pass
    return result


def _top_active_interfaces(
    catalog: SourceCatalog,
    *,
    nodes: Iterable[Any] | None = None,
    context: _RangePathContext | None = None,
) -> set[tuple[str, int, int]]:
    if catalog.top_root is None:
        return set()
    result: set[tuple[str, int, int]] = set()
    if nodes is None:
        collected: list[Any] = []
        catalog.top_root.visit(collected.append)
        nodes = collected
    for node in nodes:
        if type(node).__name__ == "InstanceSymbol" and getattr(node, "isInterface", False):
            key = _definition_key(
                catalog, getattr(node, "definition", None), context=context
            )
            if key is not None:
                result.add(key)
        elif type(node).__name__ == "InterfacePortSymbol":
            key = _definition_key(
                catalog, getattr(node, "interfaceDef", None), context=context
            )
            if key is not None:
                result.add(key)
    return result


def _top_active_types(
    catalog: SourceCatalog,
    *,
    nodes: Iterable[Any] | None = None,
    context: _RangePathContext | None = None,
) -> set[tuple[str, int, int]]:
    if catalog.top_root is None:
        return set()
    result: set[tuple[str, int, int]] = set()
    if nodes is None:
        collected: list[Any] = []
        catalog.top_root.visit(collected.append)
        nodes = collected
    for node in nodes:
        declared = getattr(node, "declaredType", None)
        target = getattr(declared, "type", None)
        if type(target).__name__ == "TypeAliasType":
            key = _definition_key(catalog, target, context=context)
            if key is not None:
                result.add(key)
        if type(node).__name__ == "ConversionExpression":
            target = getattr(node, "type", None)
            if type(target).__name__ == "TypeAliasType":
                key = _definition_key(catalog, target, context=context)
                if key is not None:
                    result.add(key)
    return result


def _owner_info(
    catalog: SourceCatalog,
    definition: object,
    modules_by_definition: dict[object, ModuleOwner | None],
    interfaces_by_definition: dict[object, str | None],
    modules_by_range: dict[tuple[str, int, int], ModuleOwner | None] | None = None,
    interfaces_by_range: dict[tuple[str, int, int], str | None] | None = None,
    *,
    context: _RangePathContext | None = None,
) -> tuple[str, str, ModuleOwner | None, str | None]:
    try:
        module = modules_by_definition.get(definition)
    except TypeError:
        module = None
    if module is not None:
        return module.name, module.owner_id, module, "module"
    try:
        interface = interfaces_by_definition.get(definition)
    except TypeError:
        interface = None
    if interface is not None:
        return interface, interface, None, "interface"
    # PySlang may expose distinct DefinitionSymbol wrappers for the same
    # source-backed declaration.  Resolve that wrapper by its own semantic
    # declaration location, never by a textual name search.
    key = _definition_key(catalog, definition, context=context)
    if key is not None:
        if modules_by_range is not None and key in modules_by_range:
            module = modules_by_range[key]
            if module is not None:
                return module.name, module.owner_id, module, "module"
            return "$unit", "$unit", None, None
        if interfaces_by_range is not None and key in interfaces_by_range:
            interface = interfaces_by_range[key]
            if interface is not None:
                return interface, interface, None, "interface"
            return "$unit", "$unit", None, None
    return "$unit", "$unit", None, None


def _add_working(
    records: dict[str, _WorkingSymbol],
    target_map: dict[object, str],
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
            target_map[target] = symbol_id
            current.targets.add(target)
    return current


def _record_id_for_declaration(
    records: dict[str, _WorkingSymbol],
    declaration: SourceRange,
    record_index: _RecordPhysicalIndex | None = None,
) -> str | None:
    """Identify one record by physical declaration position.

    Elaboration produces a distinct Python object per instance for the same
    physical declaration, so Python object identity is not a symbol identity:
    a module instantiated four times yields four target objects for one source
    token.  ``symbol_id`` already encodes the physical declaration range, so the
    range plus the canonical category order is a total, deterministic identity
    that never reports a false competing owner.
    """

    if record_index is not None:
        return record_index.resolve(declaration)
    # Keep this private helper usable by focused diagnostics.  The production
    # build always supplies its prebuilt physical index, so this fallback is a
    # single index construction rather than a per-target linear scan.
    return _RecordPhysicalIndex.from_records(records).resolve(declaration)


def _record_for_semantic_target(
    catalog: SourceCatalog,
    records: dict[str, _WorkingSymbol],
    target_map: dict[object, str],
    target: object,
    *,
    record_index: _RecordPhysicalIndex | None = None,
    context: _RangePathContext | None = None,
) -> str | None:
    """Resolve a PySlang target by its physical declaration position.

    PySlang returns one wrapper per elaborated instance for the same semantic
    declaration, so the object cannot be the identity.  The target's own
    declaration range is direct semantic evidence; it is not a name lookup or a
    textual occurrence search.  ``target_map`` is only a memo of already
    resolved wrappers.
    """

    if target is None:
        return None
    symbol_id = target_map.get(target)
    if symbol_id is not None:
        return symbol_id
    name = str(_safe_attr(target, "name", ""))
    if not name:
        return None
    try:
        target_range = _declaration_range(
            catalog,
            target,
            _safe_attr(target, "syntax"),
            name,
            context=context,
        )
    except RenameIndexError:
        return None
    symbol_id = _record_id_for_declaration(records, target_range, record_index)
    if symbol_id is not None:
        target_map[target] = symbol_id
    return symbol_id


def _interface_record_for_definition(
    catalog: SourceCatalog,
    records: dict[str, _WorkingSymbol],
    target_map: dict[object, str],
    definition: object,
    *,
    record_index: _RecordPhysicalIndex | None = None,
    context: _RangePathContext | None = None,
) -> str | None:
    """Alias a direct interface DefinitionSymbol to its physical type record."""

    symbol_id = _record_for_semantic_target(
        catalog, records, target_map, definition,
        record_index=record_index, context=context
    )
    if symbol_id is not None and records[symbol_id].kind == "interface_type":
        return symbol_id
    key = _definition_key(catalog, definition, context=context)
    if key is None:
        return None
    physical = SourceRange(*key)
    if record_index is None:
        record_index = _RecordPhysicalIndex.from_records(records)
    symbol_id = record_index.resolve(physical, category="interface")
    candidate = records.get(symbol_id) if symbol_id is not None else None
    if candidate is not None and candidate.kind == "interface_type":
        target_map[definition] = candidate.symbol_id
        return candidate.symbol_id
    return None


def _is_module_definition(definition: object, modules_by_definition: dict[object, ModuleOwner]) -> bool:
    return definition in modules_by_definition


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

    try:
        if getattr(node, "isInterface", False):
            return (node,)
        result: list[object] = []
        for element in tuple(getattr(node, "elements", ())):
            result.extend(_interface_leaf_elements(element))
        return tuple(result)
    except Exception:
        return ()


def _register_structs(
    catalog: SourceCatalog,
    selected: set[str],
    records: dict[str, _WorkingSymbol],
    target_map: dict[object, str],
    alias_map: dict[tuple[str, int, int], str],
    nodes: list[Any],
    modules_by_definition: dict[object, ModuleOwner],
    interfaces_by_definition: dict[object, str],
    modules_by_range: dict[tuple[str, int, int], ModuleOwner | None],
    interfaces_by_range: dict[tuple[str, int, int], str | None],
    active_types: set[tuple[str, int, int]],
    binding_issues: dict[str, list[dict[str, object]]],
    *,
    context: _RangePathContext | None = None,
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
        declaration = _try_declaration_range(
            catalog, binding_issues, "struct", node, syntax, name,
            candidates=(node, syntax), context=context,
        )
        if declaration is None:
            continue
        definition = getattr(node, "declaringDefinition", None)
        owner_module, semantic_owner, module, _ = _owner_info(
            catalog, definition, modules_by_definition, interfaces_by_definition,
            modules_by_range, interfaces_by_range,
            context=context,
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
        except Exception:
            semantic_fields = ()
            record.support = "preserved"
            record.reason = "source_binding_incomplete"
            _append_binding_issue(
                catalog,
                binding_issues,
                "struct",
                semantic_kind=type(node).__name__,
                name=name,
                candidates=(node, syntax),
                detail="aggregate FieldSymbol enumeration is unavailable",
                context=context,
            )

        field_bindings: list[tuple[object, SourceRange, str]] = []
        binding_incomplete = canonical is None
        for field in semantic_fields:
            if type(field).__name__ != "FieldSymbol":
                binding_incomplete = True
                _append_binding_issue(
                    catalog,
                    binding_issues,
                    "struct",
                    semantic_kind=type(field).__name__,
                    name=str(getattr(field, "name", "")),
                    candidates=(field, node, syntax),
                    detail="aggregate member is not a FieldSymbol",
                    context=context,
                )
                continue
            field_name = str(getattr(field, "name", ""))
            if not field_name:
                binding_incomplete = True
                _append_binding_issue(
                    catalog,
                    binding_issues,
                    "struct",
                    semantic_kind=type(field).__name__,
                    name=field_name,
                    candidates=(field, node, syntax),
                    detail="FieldSymbol has no semantic name",
                    context=context,
                )
                continue
            field_location = _safe_attr(field, "location")
            try:
                field_is_macro = (
                    field_location is not None
                    and catalog.catalog_source_manager.isMacroLoc(field_location)
                )
            except Exception:
                field_is_macro = True
            if field_is_macro:
                binding_incomplete = True
                _append_binding_issue(
                    catalog,
                    binding_issues,
                    "struct",
                    semantic_kind=type(field).__name__,
                    name=field_name,
                    candidates=(field, node, syntax),
                    detail="macro-generated aggregate field shape is not source-backed",
                    context=context,
                )
                continue
            field_range = _try_declaration_range(
                catalog, binding_issues, "struct", field,
                _safe_attr(field, "syntax"), field_name,
                candidates=(field, node, syntax), context=context,
            )
            if field_range is None:
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
    target_map: dict[object, str],
    nodes: list[Any],
    modules_by_definition: dict[object, ModuleOwner],
    interfaces_by_definition: dict[object, str],
    modules_by_range: dict[tuple[str, int, int], ModuleOwner | None],
    interfaces_by_range: dict[tuple[str, int, int], str | None],
    active_interfaces: set[tuple[str, int, int]],
    binding_issues: dict[str, list[dict[str, object]]],
    *,
    context: _RangePathContext | None = None,
) -> None:
    port_ranges: set[tuple[str, int, int]] = set()
    for node in nodes:
        if type(node).__name__ != "PortSymbol":
            continue
        name = str(getattr(node, "name", ""))
        declaration = _try_declaration_range(
            catalog,
            binding_issues,
            "ports",
            node,
            _safe_attr(node, "syntax"),
            name,
            candidates=(node, _safe_attr(node, "syntax"), _safe_attr(node, "internalSymbol")),
            context=context,
        )
        if declaration is None:
            continue
        port_ranges.add((declaration.file, declaration.start, declaration.end))
    for node in nodes:
        node_type = type(node).__name__
        name = str(getattr(node, "name", ""))
        if not name:
            continue
        if node_type in {"VariableSymbol", "NetSymbol"}:
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, module, owner_kind = _owner_info(
                catalog,
                definition,
                modules_by_definition,
                interfaces_by_definition,
                modules_by_range,
                interfaces_by_range,
                context=context,
            )
            category = "interface" if owner_kind == "interface" else "signals"
            declaration = _try_declaration_range(
                catalog, binding_issues, category, node,
                _safe_attr(node, "syntax"), name,
                candidates=(node, _safe_attr(node, "syntax")), context=context,
            )
            if declaration is None:
                continue
            key = (declaration.file, declaration.start, declaration.end)
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
                interface_range = _definition_key(catalog, definition, context=context)
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
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, module, owner_kind = _owner_info(
                catalog,
                definition,
                modules_by_definition,
                interfaces_by_definition,
                modules_by_range,
                interfaces_by_range,
                context=context,
            )
            category = "interface" if owner_kind == "interface" else "ports"
            declaration = _try_declaration_range(
                catalog, binding_issues, category, node,
                _safe_attr(node, "syntax"), name,
                candidates=(node, _safe_attr(node, "syntax")), context=context,
            )
            if declaration is None:
                continue
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
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, _module, _ = _owner_info(
                catalog,
                definition,
                modules_by_definition,
                interfaces_by_definition,
                modules_by_range,
                interfaces_by_range,
                context=context,
            )
            declaration = _try_declaration_range(
                catalog, binding_issues, "interface", node,
                _safe_attr(node, "syntax"), name,
                candidates=(node, _safe_attr(node, "syntax")), context=context,
            )
            if declaration is None:
                continue
            _add_working(
                records, target_map, catalog=catalog, category="interface",
                kind="modport" if node_type == "ModportSymbol" else "modport_member",
                semantic_kind=node_type, name=name, declaration=declaration,
                owner_module=owner_module, semantic_owner=semantic_owner,
                impact="interface_abi", abi="internal", targets=(node,),
            )
        elif node_type == "InstanceSymbol" and getattr(node, "isInterface", False) and "interface" in selected:
            # A hierarchical prefix (`if0.valid`) has no binding rule yet: the
            # semantic reference resolves to the member, so renaming the
            # instance would leave the old instance name in every prefix.  The
            # instance is preserved explicitly with its own reason instead of
            # relying on an unexplained group rollback.
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, module, _ = _owner_info(
                catalog,
                definition,
                modules_by_definition,
                interfaces_by_definition,
                modules_by_range,
                interfaces_by_range,
                context=context,
            )
            declaration = _try_declaration_range(
                catalog, binding_issues, "interface", node,
                _safe_attr(node, "syntax"), name,
                candidates=(node, _safe_attr(node, "syntax")), context=context,
            )
            if declaration is None:
                continue
            support, reason, abi = _category_support(
                "interface", module, top=catalog.source_set.top,
                interface_active=True, aggregate_active=True, interface_instance=True,
            )
            support, reason = "preserved", "hierarchical_prefix_unsupported"
            _add_working(
                records, target_map, catalog=catalog, category="interface", kind="interface_instance",
                semantic_kind=node_type, name=name, declaration=declaration,
                owner_module=owner_module, semantic_owner=semantic_owner,
                impact="interface_instance", abi=abi, targets=(node,), support=support, reason=reason,
            )
        elif node_type == "InstanceArraySymbol" and "interface" in selected:
            elements = _interface_leaf_elements(node)
            if not elements:
                if name:
                    _append_binding_issue(
                        catalog,
                        binding_issues,
                        "interface",
                        semantic_kind=node_type,
                        name=name,
                        candidates=(node, _safe_attr(node, "syntax")),
                        detail="source-backed interface array has no semantic elements",
                        context=context,
                    )
                continue
            definition = getattr(node, "declaringDefinition", None)
            owner_module, semantic_owner, module, _ = _owner_info(
                catalog,
                definition,
                modules_by_definition,
                interfaces_by_definition,
                modules_by_range,
                interfaces_by_range,
                context=context,
            )
            declaration = _try_declaration_range(
                catalog, binding_issues, "interface", node,
                _safe_attr(node, "syntax"), name,
                candidates=(node, _safe_attr(node, "syntax")), context=context,
            )
            if declaration is None:
                continue
            support, reason, abi = _category_support(
                "interface", module, top=catalog.source_set.top,
                interface_active=True, aggregate_active=True, interface_instance=True,
            )
            support, reason = "preserved", "hierarchical_prefix_unsupported"
            _add_working(
                records, target_map, catalog=catalog, category="interface",
                kind="interface_instance_array", semantic_kind=node_type,
                name=name, declaration=declaration, owner_module=owner_module,
                semantic_owner=semantic_owner, impact="interface_instance",
                abi=abi, targets=(node, *elements), support=support, reason=reason,
            )


def _type_occurrence_range(
    catalog: SourceCatalog,
    node: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    declared = getattr(node, "declaredType", None)
    syntax = getattr(declared, "typeSyntax", None)
    if _kind_name(getattr(syntax, "kind", None)) != "NamedType":
        return None
    return _syntax_identifier_range(
        catalog, getattr(syntax, "name", None), expected, context=context
    )


def _instance_type_occurrence(
    catalog: SourceCatalog,
    node: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    syntax = getattr(node, "syntax", None)
    parent = getattr(syntax, "parent", None)
    return _range_for_token(
        catalog, getattr(parent, "type", None), expected, context=context
    )


def _named_port_connection_syntax(node: object) -> tuple[object, ...]:
    """Return one instance's named connection syntax nodes in source order.

    ``syntax.connections`` interleaves comma tokens with connection syntax and
    is in source order, while ``portConnections`` is in port declaration order.
    Only a named connection carries a label token; ``.*`` wildcards and ordered
    connections have no label and therefore no physical occurrence.
    """

    connections = _safe_attr(_safe_attr(node, "syntax"), "connections", ()) or ()
    return tuple(
        item
        for item in connections
        if _kind_name(_safe_attr(item, "kind")) == "NamedPortConnection"
    )


def _instance_ports_by_name(node: object) -> dict[str, object]:
    """Map this instance's own port names to their semantic port symbols.

    ``PortConnection`` exposes only ``expression``, ``ifaceConn`` and ``port``:
    it has no ``syntax`` and no ``sourceRange``, so the semantic side cannot
    supply the connection site, and pairing the two lists by index is invalid
    because their orders differ.  A named port connection is bound by name in
    the language definition, so resolving the label token inside this instance's
    own port set executes that rule instead of searching the design.
    """

    result: dict[str, object] = {}
    ambiguous: set[str] = set()
    for connection in _safe_attr(node, "portConnections", ()) or ():
        port = _safe_attr(connection, "port")
        name = str(_safe_attr(port, "name", ""))
        if not name:
            continue
        if name in result:
            ambiguous.add(name)
            continue
        result[name] = port
    for name in ambiguous:
        result.pop(name, None)
    return result


def _interface_port_header(node: object) -> object:
    """Return the port header syntax of one module interface port."""

    return _safe_attr(_safe_attr(_safe_attr(node, "syntax"), "parent"), "header")


def _interface_port_type_range(
    catalog: SourceCatalog,
    node: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    """Bind the interface type token of one module interface port.

    A modport-qualified header (``If.Mp p``) is ``InterfacePortHeaderSyntax``,
    which has no ``dataType`` at all; its typed interface token is
    ``nameOrKeyword``.  A plain interface port (``If p``) uses
    ``VariablePortHeaderSyntax.dataType``.  The non-ANSI body declaration
    ``If.Mp p;`` also exposes ``InterfacePortHeaderSyntax``, so both modport
    forms use the same typed token.
    """

    header = _interface_port_header(node)
    if _kind_name(_safe_attr(header, "kind")) == "InterfacePortHeader":
        return _range_for_token(
            catalog, _safe_attr(header, "nameOrKeyword"), expected, context=context
        )
    type_syntax = _safe_attr(header, "dataType")
    if type_syntax is None:
        # Non-ANSI interface ports without a modport expose the typed
        # interface name on the declaration syntax rather than a header.
        type_syntax = _safe_attr(_safe_attr(_safe_attr(node, "syntax"), "parent"), "type")
    return _syntax_identifier_range(catalog, type_syntax, expected, context=context)


def _interface_port_modport_token(node: object) -> object:
    """Return the modport name token of ``If.Mp p``.

    ``header.modport`` is a ``DotMemberClauseSyntax`` whose ``member`` is the
    modport identifier token; ``InterfacePortSymbol.modport`` is only a string.
    """

    return _safe_attr(_safe_attr(_interface_port_header(node), "modport"), "member")


def _interface_port_modport_symbol(node: object) -> object:
    """Return the semantic ModportSymbol connected to one interface port.

    ``InterfacePortSymbol.connection`` is a ``(instance, modport)`` tuple, so
    the modport target comes from the elaborator and never from a name lookup.
    """

    connection = _safe_attr(node, "connection")
    try:
        if connection is None or len(connection) < 2:
            return None
        return connection[1]
    except TypeError:
        return None


def _member_access_range(
    catalog: SourceCatalog,
    node: object,
    expected: str,
    *,
    context: _RangePathContext | None = None,
) -> SourceRange | None:
    """Bind one aggregate member reference token.

    ``data.member`` exposes ``ScopedNameSyntax``, but the typed path does not
    always reach the member token.  ``data.member[3:0]`` exposes
    ``syntax = None`` because slang drops the syntax link, and a member access
    inside a sized cast such as ``(W)'(data.member)`` exposes
    ``ParenthesizedExpressionSyntax``.  Neither shape offers a typed structure to
    walk or a select expression to descend, so resolution is two stage: try the
    typed identifier path first, and when it yields no range -- for any reason,
    including ``None`` and any unhandled syntax kind -- fall back to the
    expression's own ``sourceRange``, which still ends exactly at the member
    token, so the member is the last ``len(name)`` bytes of that range.  The
    candidate is byte-verified against the original source and rejected when it
    would consume the whole range, because a member reference always has a
    prefix.

    A macro expansion range still cannot be used for offset arithmetic, but the
    member token of a macro argument does physically exist at the call site, so
    each end is first restored to its physical location by ``SourceManager`` and
    the arithmetic then runs on the restored locations instead of giving up.
    Restoring is not a relaxation of the proof: a restored candidate must pass
    the same buffer, prefix and source-byte checks as a directly physical one,
    and a restored range claimed by two records -- one macro body token expanded
    N times has one physical range and N semantic meanings -- stays subject to
    ``_resolve_range_claims``.
    """

    syntax = _safe_attr(node, "syntax")
    typed = _syntax_identifier_range(catalog, syntax, expected, context=context)
    if typed is not None:
        return typed
    source_range = _safe_attr(node, "sourceRange")
    if source_range is None:
        return None
    expected_bytes = expected.encode("utf-8")
    try:
        start = _physical_location(catalog, source_range.start)
        end = _physical_location(catalog, source_range.end)
        if start.buffer != end.buffer:
            return None
        if context is None:
            context = _RangePathContext.for_catalog(catalog)
        file = _file_for_buffer(catalog, end.buffer, context=context)
        stop = int(end.offset)
        begin = stop - len(expected_bytes)
    except RenameIndexError:
        raise
    except Exception as error:
        raise RenameIndexError(
            "RENAME_INDEX_RANGE_INVALID", "member access source range is invalid"
        ) from error
    if begin <= int(start.offset):
        return None
    data = context.read_range(catalog, file, begin, stop)
    if data != expected_bytes:
        return None
    return SourceRange(file, begin, stop)


def _member_access_provenance(catalog: SourceCatalog, node: object) -> str:
    """Report whether one member occurrence came out of a macro expansion.

    ``_resolve_range_claims`` tells an explained macro-origin collision apart
    from an unknown cross-record collision by provenance alone, so a member
    token whose expression lives in a macro expansion must declare that origin
    exactly as ``_semantic_expression_range`` already does for a value
    reference.  Without it a macro body member expanded with two different
    aggregate types would be reported as an unknown conflict and would roll back
    its whole core group.
    """

    start = _safe_attr(_safe_attr(node, "sourceRange"), "start")
    if start is None:
        return "semantic_member"
    try:
        manager = catalog.catalog_source_manager
        if not manager.isMacroLoc(start):
            return "semantic_member"
        return (
            "semantic_macro_argument"
            if manager.isMacroArgLoc(start)
            else "semantic_macro_body"
        )
    except Exception:
        return "semantic_member"


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
    binding_issues: dict[str, list[dict[str, object]]],
) -> dict[str, tuple[dict[str, object], ...]]:
    """Make every unknown binding issue transactional at single-record scope.

    Renaming is safe when a declaration and every reference of *one* record
    change together, and that constraint lives entirely inside that record.  So
    a record without complete binding evidence preserves itself and leaves the
    already-proven records of its core group renameable.  Escalating to the core
    group was a real hazard rather than extra caution: on one production design
    three unbound member tokens preserved 541 struct records, 538 of which were
    bound correctly, and no amount of shape coverage removes the next unknown
    shape.

    The two couplings that do cross record boundaries are handled elsewhere and
    are deliberately untouched here: a physical range claimed by two records is
    resolved by ``_resolve_range_claims`` (which keeps its own group-scope
    rollback for an unknown cross-record conflict), and the field completeness
    of one aggregate is resolved by ``_register_structs``.  Shrinking this
    propagation therefore adds no new unsafe surface.

    ``binding_issues`` stays an input because it is this function's diagnostic
    context, but it must never again turn one category's issue into a
    category-wide rollback; ``build_rename_index`` already merges it into the
    reported issues, so no locating information is lost.
    """

    known_per_record_reasons = {
        "selected_top_boundary",
        "outside_top_closure",
        "macro_origin_conflict",
        # An interface instance is preserved because the hierarchical prefix
        # rule does not exist yet.  That is a per-record language boundary with
        # a stated reason, not an unknown binding failure, so it must not roll
        # back the rest of the interface group.
        "hierarchical_prefix_unsupported",
    }
    unknown_by_category: dict[str, list[_WorkingSymbol]] = {}
    for record in records.values():
        if record.reason is not None and record.reason not in known_per_record_reasons:
            # Record scope: the record that lacks evidence preserves itself.
            # Every caller that raises an unknown reason already does this; the
            # assignment keeps the invariant true from this function alone.
            if record.support == "eligible":
                record.support = "preserved"
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
        issues[category] = tuple(
            {
                "file": record.declaration.file,
                "start": record.declaration.start,
                "message": record.reason,
            }
            for record in ordered
        )
    return issues


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


def _apply_readonly_firewall(
    catalog: SourceCatalog,
    records: dict[str, _WorkingSymbol],
) -> None:
    vendor_files = frozenset(catalog.readonly_vendor_files)
    include_files = frozenset(catalog.readonly_include_files)
    rewrite_roots = tuple(catalog.source_set.rewrite_roots)
    for record in records.values():
        if record.support != "eligible":
            continue
        files = {
            record.declaration.file,
            *(
                occurrence.source_range.file
                for occurrence in record.occurrences.values()
            ),
        }
        if files & vendor_files:
            record.support = "preserved"
            record.reason = "readonly_vendor_model"
        elif rewrite_roots and any(
            not _file_is_within_rewrite_roots(file, rewrite_roots)
            for file in files
        ):
            record.support = "preserved"
            record.reason = "outside_rewrite_root"
        elif files & include_files:
            record.support = "preserved"
            record.reason = "readonly_include_file"


# The four CST declaration shapes that can form a physical design unit.  A unit
# that never elaborates has no semantic body at all, so its span is dead source.
_DESIGN_UNIT_SYNTAX_KINDS = frozenset(
    {
        "ModuleDeclaration",
        "InterfaceDeclaration",
        "PackageDeclaration",
        "ProgramDeclaration",
    }
)


def _syntax_nodes(catalog: SourceCatalog) -> list[Any]:
    """Return every CST node of the compiled source.

    The semantic tree cannot answer where dead source is, because dead source
    produces no semantic node.  The CST is the only record that those bytes were
    ever compiled at all, so it is read directly from the same Compilation the
    semantic view came from; nothing is re-parsed and no text is scanned.
    """

    try:
        trees = catalog.catalog_compilation.getSyntaxTrees()
    except Exception as error:
        raise RenameIndexError(
            "RENAME_INDEX_SOURCE_INVALID",
            "compilation does not expose its syntax trees",
        ) from error
    nodes: list[Any] = []
    for tree in trees:
        try:
            tree.root.visit(nodes.append)
        except Exception as error:
            raise RenameIndexError(
                "RENAME_INDEX_SOURCE_INVALID", "syntax tree cannot be walked"
            ) from error
    return nodes


def _buffer_file(
    catalog: SourceCatalog,
    buffer: object,
    cache: _RangePathContext | dict[object, str | None],
) -> str | None:
    """Resolve one PySlang buffer to a SourceSet-relative file, once per buffer.

    A production design expands to hundreds of thousands of identifier tokens
    drawn from a few hundred buffers, so resolving the same buffer per token is
    pure cost.  This is the memo ``scripts/binding_coverage.py`` already keeps for
    the same walk; it changes no judgement.
    """

    if isinstance(cache, _RangePathContext):
        return cache.file_for_buffer(catalog, buffer)
    try:
        return cache[buffer]
    except KeyError:
        pass
    except TypeError:
        # An unhashable buffer cannot be memoised; resolve it directly.
        try:
            return _file_for_buffer(catalog, buffer)
        except (AttributeError, TypeError, ValueError):
            return None
    value: str | None
    try:
        value = _file_for_buffer(catalog, buffer)
    except (AttributeError, TypeError, ValueError):
        value = None
    cache[buffer] = value
    return value


def _resolved_span(
    catalog: SourceCatalog,
    source_range: object,
    cache: _RangePathContext | dict[object, str | None],
) -> tuple[str, int, int] | None:
    """Return one physical ``(file, start, end)`` span for a source range.

    Macro locations are restored through the SourceManager first, exactly as
    every other range in this module does.  A range that cannot be pinned to one
    physical file is not a usable region and is reported as absent.
    """

    if source_range is None:
        return None
    try:
        start_location = _physical_location(catalog, _safe_attr(source_range, "start"))
        end_location = _physical_location(catalog, _safe_attr(source_range, "end"))
        if start_location is None or end_location is None:
            return None
        file = _buffer_file(catalog, start_location.buffer, cache)
        if file is None or file != _buffer_file(catalog, end_location.buffer, cache):
            return None
        start = int(start_location.offset)
        end = int(end_location.offset)
    except (AttributeError, TypeError, ValueError):
        return None
    return None if end <= start else (file, start, end)


def _physical_declaration_key(
    catalog: SourceCatalog,
    location: object,
    cache: _RangePathContext | dict[object, str | None],
) -> tuple[str, int] | None:
    """Identify one declaration by the physical position of its name token."""

    try:
        physical = _physical_location(catalog, location)
        if physical is None:
            return None
        file = _buffer_file(catalog, physical.buffer, cache)
        if file is None:
            return None
        return (file, int(physical.offset))
    except (AttributeError, TypeError, ValueError):
        return None


def _elaborated_unit_keys(
    catalog: SourceCatalog,
    nodes: list[Any],
    cache: _RangePathContext | dict[object, str | None],
) -> set[tuple[str, int]]:
    """Return the name-token keys of the design units PySlang really elaborated.

    ``InstanceBodySymbol`` and ``PackageSymbol`` are the two semantic bodies a
    physical design unit can produce.  A unit with neither was never elaborated.
    """

    keys: set[tuple[str, int]] = set()
    for node in nodes:
        if type(node).__name__ not in {"InstanceBodySymbol", "PackageSymbol"}:
            continue
        target = _safe_attr(node, "definition") or node
        key = _physical_declaration_key(catalog, _safe_attr(target, "location"), cache)
        if key is not None:
            keys.add(key)
    return keys


def _dead_source_regions(
    catalog: SourceCatalog,
    nodes: list[Any],
    syntax_nodes: list[Any],
    cache: _RangePathContext | dict[object, str | None],
) -> tuple[tuple[str, int, int], ...]:
    """Return the physical source regions PySlang never elaborated.

    Two shapes produce identifiers that no semantic reference can ever reach,
    and they are the same two ``scripts/binding_coverage.py`` already detects and
    reports; this is that judgement applied to the rename decision, not a second
    detector:

    * a design unit that never elaborates, because the only instantiation of it
      sits in a generate branch that was not taken, so it has no
      ``InstanceBodySymbol`` at all;
    * an uninstantiated generate branch inside a unit that *was* elaborated,
      which PySlang marks with ``GenerateBlockSymbol.isUninstantiated``.

    Both compile without a single diagnostic, which is precisely why strict
    compilation cannot see them.
    """

    elaborated = _elaborated_unit_keys(catalog, nodes, cache)
    regions: list[tuple[str, int, int]] = []
    for node in syntax_nodes:
        if type(node).__name__ == "Token":
            continue
        if _kind_name(_safe_attr(node, "kind")) not in _DESIGN_UNIT_SYNTAX_KINDS:
            continue
        key = _physical_declaration_key(
            catalog,
            _safe_attr(_safe_attr(_safe_attr(node, "header"), "name"), "location"),
            cache,
        )
        if key is None or key in elaborated:
            continue
        span = _resolved_span(catalog, _safe_attr(node, "sourceRange"), cache)
        if span is not None:
            regions.append(span)
    for node in nodes:
        if type(node).__name__ != "GenerateBlockSymbol":
            continue
        if not _safe_attr(node, "isUninstantiated", False):
            continue
        span = _resolved_span(
            catalog, _safe_attr(_safe_attr(node, "syntax"), "sourceRange"), cache
        )
        if span is not None:
            regions.append(span)
    return tuple(regions)


def _merge_regions(
    regions: Iterable[tuple[str, int, int]]
) -> dict[str, tuple[list[int], list[int]]]:
    """Flatten possibly nested regions into per-file disjoint sorted intervals.

    A dead generate branch can sit inside a dead design unit, so the raw regions
    nest.  Merging them keeps containment a single ordered lookup while asking
    the identical question: is this token inside any dead region.
    """

    by_file: dict[str, list[tuple[int, int]]] = {}
    for file, start, end in regions:
        by_file.setdefault(file, []).append((start, end))
    merged: dict[str, tuple[list[int], list[int]]] = {}
    for file, spans in by_file.items():
        starts: list[int] = []
        ends: list[int] = []
        for start, end in sorted(spans):
            if starts and start <= ends[-1]:
                ends[-1] = max(ends[-1], end)
                continue
            starts.append(start)
            ends.append(end)
        merged[file] = (starts, ends)
    return merged


def _names_in_dead_source(
    catalog: SourceCatalog,
    syntax_nodes: list[Any],
    regions: tuple[tuple[str, int, int], ...],
    wanted: frozenset[str],
    cache: _RangePathContext | dict[object, str | None],
) -> frozenset[str]:
    """Return which of ``wanted`` spellings a dead source region really contains.

    Every candidate is an ``Identifier`` token taken from the CST, restored to
    its physical location and verified byte for byte against the file before it
    counts.  ``SystemIdentifier`` (``$clog2``) is a language built-in and never a
    rename target, so the token kind filter is the same one the rest of this
    module relies on.
    """

    merged = _merge_regions(regions)
    if not merged or not wanted:
        return frozenset()
    found: set[str] = set()
    file_bytes: dict[str, bytes] = {}
    identifier = pyslang.parsing.TokenKind.Identifier
    for node in syntax_nodes:
        if len(found) == len(wanted):
            break
        if type(node).__name__ != "Token":
            continue
        try:
            if node.kind != identifier:
                continue
            raw = str(node.rawText)
        except Exception:
            continue
        if raw not in wanted or raw in found:
            continue
        key = _physical_declaration_key(catalog, _safe_attr(node, "location"), cache)
        if key is None:
            continue
        file, start = key
        bounds = merged.get(file)
        if bounds is None:
            continue
        starts, ends = bounds
        index = bisect.bisect_right(starts, start) - 1
        encoded = raw.encode("utf-8")
        end = start + len(encoded)
        if index < 0 or end > ends[index]:
            continue
        data = file_bytes.get(file)
        if data is None:
            data = _source_bytes(
                catalog,
                file,
                context=cache if isinstance(cache, _RangePathContext) else None,
            )
            file_bytes[file] = data
        if not 0 <= start < end <= len(data) or data[start:end] != encoded:
            continue
        found.add(raw)
    return frozenset(found)


def _apply_unelaborated_references(
    catalog: SourceCatalog,
    nodes: list[Any],
    syntax_nodes: list[Any],
    records: dict[str, _WorkingSymbol],
    *,
    context: _RangePathContext | None = None,
) -> None:
    """Preserve every record whose spelling also exists in dead source.

    T112 section 14 measured the fail-open this closes.  A module that *is*
    defined but instantiated only inside an untaken generate branch becomes an
    ``UninstantiatedDefSymbol``: PySlang binds none of its connection actuals and
    reports no diagnostic, so those actuals are physically present and
    semantically invisible.  Renaming the declaration alone leaves the old name
    written in the gate, where it silently becomes an implicit net and the port
    it used to reach is left dangling -- 1514 times on one production design,
    with strict compilation, occurrence coverage and byte-identical restore all
    reporting success.

    T109 proved the reference itself is unrecoverable: an untaken branch produces
    no AST node, so PySlang cannot say what those tokens mean.  The rule is
    therefore detection plus conservative preservation, never rewriting: a dead
    token spelling ``n`` may even belong to a different symbol also spelled
    ``n``, which is exactly why a match preserves the record instead of moving
    it.  Preserving one record too many costs coverage; renaming one reference
    too few costs correctness.

    The preserve is per record, in the T111 sense: a record whose spelling is
    absent from dead source stays renameable even when a sibling of the same core
    group is preserved here.

    ``syntax_nodes`` is supplied by the caller only so that one CST walk serves
    both this rule and the name-completeness rule that follows it.  The judgement
    below is unchanged: it is still the dead-region detection of T113 applied to
    the same node list this function used to build for itself.
    """

    wanted = frozenset(
        record.name
        for record in records.values()
        if record.support == "eligible" and record.name
    )
    if not wanted:
        return
    if context is None:
        context = _RangePathContext.for_catalog(catalog)
    regions = _dead_source_regions(catalog, nodes, syntax_nodes, context)
    if not regions:
        return
    dead = _names_in_dead_source(
        catalog, syntax_nodes, regions, wanted, context
    )
    for record in records.values():
        if record.support == "eligible" and record.name in dead:
            record.support = "preserved"
            record.reason = "unelaborated_reference"


@dataclass(frozen=True)
class _NameToken:
    """One physical identifier token, byte-verified against the source file."""

    file: str
    start: int
    end: int
    name: str


@dataclass(frozen=True)
class _NameReference:
    """One semantic reference span, keyed later by ``(file, name)``."""

    start: int
    end: int
    target: tuple[str, int]


def _spelled_name(raw: str) -> str:
    """Return the semantic name one physical identifier token spells.

    An escaped identifier is written ``\\name`` in source while PySlang reports
    the symbol name without the leading backslash.  That is a lexical fact of the
    language, not a name guess, and ``scripts/binding_coverage.py`` normalizes it
    the same way.  Nothing else is rewritten here.
    """

    if raw.startswith("\\"):
        return raw[1:].rstrip()
    return raw


def _tokens_spelling(
    catalog: SourceCatalog,
    syntax_nodes: list[Any],
    wanted: frozenset[str],
    cache: _RangePathContext | dict[object, str | None],
) -> tuple[tuple[_NameToken, ...], frozenset[str]]:
    """Enumerate every physical identifier token that spells one of ``wanted``.

    The CST is the only complete record of what the source physically contains,
    so it is the only honest denominator for a completeness proof.  Macro
    locations are restored by ``SourceManager`` and every token is verified byte
    for byte against the original file before it counts, exactly as
    ``scripts/binding_coverage.py`` already does on 61659 tokens with
    ``byte_mismatch=0``.

    One token class is excluded, and only because the language says it can never
    be a rename target: ``SystemIdentifier`` (``$clog2``, ``$display``) is a
    built-in.  A token this module happens to have no binding rule for is
    deliberately *kept* in the denominator -- that token is precisely the one this
    criterion exists to catch, so excluding it would buy coverage by giving up the
    proof.

    A token that spells a wanted name but cannot be pinned to a verified physical
    position is not silently dropped either: its spelling is returned in the
    second value, because a name with an unlocatable token cannot be proven
    complete.
    """

    if not wanted:
        return (), frozenset()
    identifier = pyslang.parsing.TokenKind.Identifier
    file_bytes: dict[str, bytes] = {}
    seen: set[tuple[str, int, int]] = set()
    tokens: list[_NameToken] = []
    unverified: set[str] = set()
    for node in syntax_nodes:
        if type(node).__name__ != "Token":
            continue
        try:
            if node.kind != identifier:
                continue
            raw = str(node.rawText)
        except Exception:
            continue
        if not raw:
            continue
        name = _spelled_name(raw)
        if name not in wanted:
            continue
        key = _physical_declaration_key(catalog, _safe_attr(node, "location"), cache)
        if key is None:
            unverified.add(name)
            continue
        file, start = key
        encoded = raw.encode("utf-8")
        end = start + len(encoded)
        physical = (file, start, end)
        if physical in seen:
            # One macro body token expanded N times is still one physical token.
            continue
        data = file_bytes.get(file)
        if data is None:
            try:
                data = _source_bytes(
                    catalog,
                    file,
                    context=cache if isinstance(cache, _RangePathContext) else None,
                )
            except RenameIndexError:
                unverified.add(name)
                continue
            file_bytes[file] = data
        if not 0 <= start < end <= len(data) or data[start:end] != encoded:
            unverified.add(name)
            continue
        seen.add(physical)
        tokens.append(_NameToken(file, start, end, name))
    return tuple(tokens), frozenset(unverified)


def _aggregate_field_symbols(nodes: list[Any]) -> tuple[Any, ...]:
    """Return every ``FieldSymbol`` this design declares, nested ones included.

    ``Compilation.getRoot().visit`` does not reach aggregate members at all, and
    the outer type's own member list does not reach a nested aggregate's members
    either.  ``struct packed { struct packed { logic a; } a; }`` declares two
    different members spelled ``a``, and only the outer one belongs to the outer
    type.  The inner one is still a real declaration, so a token spelling it is
    attributed and must not be charged against a same-spelled symbol elsewhere.
    ``_register_structs`` already reaches the first level through
    ``canonicalType``; this follows the same access to its end, and through
    ``elementType`` for an array of aggregates.

    A non-aggregate canonical type simply is not iterable in PySlang, which is
    why no type-name allowlist is needed here: asking is the test.
    """

    result: list[Any] = []
    visited: set[int] = set()
    # `id()` is unique only among objects that are alive at the same moment, and
    # PySlang hands out a fresh Python wrapper on each attribute access.  Without
    # a strong reference the wrapper is collected, CPython reuses its address, and
    # the next unrelated type is mistaken for one already visited -- silently
    # dropping a whole aggregate's fields, so tokens spelling those fields become
    # unattributed and their records are preserved for no reason.  Measured: that
    # made the rename decision depend on allocation history, i.e. on whatever ran
    # earlier in the process, and the same source produced different preserve sets
    # across runs.  Holding every visited object for the length of the walk makes
    # the guard sound; if PySlang does return a fresh wrapper each time, the guard
    # merely stops matching and the walk repeats work, which costs time and never
    # correctness.
    alive: list[Any] = []

    def descend(candidate: object) -> None:
        if candidate is None:
            return
        canonical = _safe_attr(candidate, "canonicalType") or candidate
        marker = id(canonical)
        if marker in visited:
            return
        visited.add(marker)
        alive.append(canonical)
        try:
            members = tuple(canonical)
        except Exception:
            members = ()
        found = False
        for member in members:
            if type(member).__name__ != "FieldSymbol":
                continue
            found = True
            result.append(member)
            descend(_safe_attr(_safe_attr(member, "declaredType"), "type"))
        if not found:
            descend(_safe_attr(canonical, "elementType"))

    for node in nodes:
        if type(node).__name__ == "TypeAliasType":
            descend(node)
        descend(_safe_attr(_safe_attr(node, "declaredType"), "type"))
    return tuple(result)


def _declaration_attributions(
    catalog: SourceCatalog,
    nodes: list[Any],
    by_start: dict[tuple[str, int], _NameToken],
    wanted: frozenset[str],
    cache: _RangePathContext | dict[object, str | None],
) -> set[tuple[str, int, int]]:
    """Attribute the declaration token of every named semantic symbol.

    A symbol's own ``location`` is direct semantic evidence of where its
    declaration token begins.  The attribution counts only when a real identifier
    token starts exactly there and spells that symbol's name, so this is
    byte-verified evidence rather than a name lookup.

    Every named symbol is asked, not only the four core groups: a token that
    declares a parameter, a genvar, a module or a subroutine is attributed to
    *that* declaration, which is what proves it is not an unexplained occurrence
    of the name under judgement.
    """

    found: set[tuple[str, int, int]] = set()

    def attribute(symbol: object) -> None:
        try:
            name = str(_safe_attr(symbol, "name", "") or "")
        except Exception:
            return
        if not name or name not in wanted:
            return
        key = _physical_declaration_key(catalog, _safe_attr(symbol, "location"), cache)
        if key is None:
            return
        token = by_start.get(key)
        if token is not None and token.name == name:
            found.add((token.file, token.start, token.end))

    for node in nodes:
        attribute(node)
    for member in _aggregate_field_symbols(nodes):
        attribute(member)
    return found


def _reference_spans(
    catalog: SourceCatalog,
    nodes: list[Any],
    wanted: frozenset[str],
    cache: _RangePathContext | dict[object, str | None],
) -> dict[tuple[str, str], list[_NameReference]]:
    """Collect every AST node that references a symbol spelled in ``wanted``.

    Only ``sourceRange`` and the direct target symbol are read, so a node whose
    ``syntax`` link slang dropped -- a member access followed by a select, for
    example -- is handled identically to one that kept it.  The target identity is
    the physical declaration position and never ``id(target)``: elaboration
    produces one Python object per instance, and object identity reported 1294
    false ambiguities on a 19-file design (token_first_binding.md section 5.1).
    """

    buckets: dict[tuple[str, str], list[_NameReference]] = {}
    for node in nodes:
        target = None
        for attribute in ("symbol", "member"):
            candidate = _safe_attr(node, attribute)
            if candidate is None:
                continue
            try:
                if hasattr(candidate, "name"):
                    target = candidate
                    break
            except Exception:
                continue
        if target is None:
            continue
        try:
            name = str(_safe_attr(target, "name", "") or "")
        except Exception:
            continue
        if not name or name not in wanted:
            continue
        span = _resolved_span(catalog, _safe_attr(node, "sourceRange"), cache)
        if span is None:
            continue
        file, start, end = span
        identity = _physical_declaration_key(
            catalog, _safe_attr(target, "location"), cache
        )
        if identity is None:
            # The reference exists but its target cannot be pinned to a physical
            # declaration, so it proves nothing about which symbol the token
            # means.  An earlier version invented `("$unresolved", id(target))`
            # here; that is unsound for the same reason section 5.1 of
            # token_first_binding.md rejects `id()` as an identity: CPython
            # reuses an address once the wrapper is collected, so two genuinely
            # different declarations can collide into one identity, the
            # narrowest-span tie disappears, and the token is attributed to the
            # wrong owner -- a rename that should not have happened.  Dropping
            # the reference instead leaves the token unattributed, which
            # preserves the record.  Fewer renames, never a wrong one.
            continue
        buckets.setdefault((file, name), []).append(
            _NameReference(start, end, identity)
        )
    return buckets


def _reference_attributions(
    tokens: tuple[_NameToken, ...],
    buckets: dict[tuple[str, str], list[_NameReference]],
    rewritten_starts: frozenset[tuple[str, int]],
    stats: _ReferenceQueryStats | None = None,
) -> set[tuple[str, int, int]]:
    """Attribute each token to the smallest enclosing matching reference.

    This is the class-one rule of token_first_binding.md section 3: a token
    belongs to the narrowest reference that contains it and whose target carries
    the same name.  Measured on ``a.a.a`` -- a variable and two nested fields all
    spelled the same -- it yields three distinct symbols and no ambiguity.

    Two cases are deliberately refused rather than resolved:

    * when two different physical declarations tie for the narrowest span, the
      token is left unattributed.  An ambiguous token is exactly a token whose
      meaning is not proven;
    * when the token's target is declared at a position this run *rewrites*, the
      token is left unattributed even though a reference does claim it.  Knowing
      what a token means is not the same as leaving it correct: if the spelling of
      the declaration it points at changes and the token itself is not in the edit
      set, the reference breaks.  ``rtl_samples/example_fifo`` is the measured
      case -- ``ctrl.full`` through a ``fifo_if.consumer`` modport port resolves to
      a ``ModportPortSymbol`` whose own declaration token *is* rewritten as an
      occurrence of the interface member, while the ``ctrl.full`` token is bound to
      nothing, so renaming that member used to produce a gate with seven
      ``CouldNotResolveHierarchicalPath`` errors.

    ``rewritten_starts`` is taken from the records that are still eligible when
    this runs.  Preserving records afterwards only shrinks the real edit set, so a
    single pass errs towards preserving too much, never too little.
    """

    # A bucket is indexed offline by token ordinal.  Each reference updates a
    # logarithmic number of segment-tree nodes; a point query then inspects one
    # root-to-leaf path and reads only each node's minimum-width owners.  Thus a
    # common name with T tokens and R references performs O((T + R) log T)
    # probes instead of testing every token against every reference.
    found: set[tuple[str, int, int]] = set()
    token_buckets: dict[tuple[str, str], list[_NameToken]] = {}
    for token in tokens:
        token_buckets.setdefault((token.file, token.name), []).append(token)

    for bucket, bucket_tokens in token_buckets.items():
        references = buckets.get(bucket)
        if not references:
            continue
        ordered_tokens = sorted(
            bucket_tokens, key=lambda item: (item.start, item.end)
        )
        starts = [item.start for item in ordered_tokens]
        ends = [item.end for item in ordered_tokens]
        size = 1
        while size < len(ordered_tokens):
            size <<= 1
        minimum: list[int | None] = [None] * (size * 2)
        owners: list[set[tuple[str, int]]] = [set() for _ in range(size * 2)]

        def update(left: int, right: int, width: int, target: tuple[str, int]) -> None:
            left += size
            right += size
            while left < right:
                if left & 1:
                    previous = minimum[left]
                    if previous is None or width < previous:
                        minimum[left] = width
                        owners[left] = {target}
                    elif width == previous:
                        owners[left].add(target)
                    left += 1
                if right & 1:
                    right -= 1
                    previous = minimum[right]
                    if previous is None or width < previous:
                        minimum[right] = width
                        owners[right] = {target}
                    elif width == previous:
                        owners[right].add(target)
                left >>= 1
                right >>= 1

        for reference in references:
            left = bisect.bisect_left(starts, reference.start)
            right = bisect.bisect_right(ends, reference.end)
            if left < right:
                update(
                    left,
                    right,
                    reference.end - reference.start,
                    reference.target,
                )

        for index, token in enumerate(ordered_tokens):
            position = size + index
            width: int | None = None
            matching_owners: set[tuple[str, int]] = set()
            while position:
                if stats is not None:
                    stats.candidate_checks += 1
                candidate_width = minimum[position]
                if candidate_width is not None:
                    if width is None or candidate_width < width:
                        width = candidate_width
                        matching_owners = set(owners[position])
                    elif candidate_width == width:
                        matching_owners.update(owners[position])
                position >>= 1
            if width is None or len(matching_owners) != 1:
                continue
            if next(iter(matching_owners)) in rewritten_starts:
                continue
            found.add((token.file, token.start, token.end))
    return found


def _apply_name_completeness(
    catalog: SourceCatalog,
    nodes: list[Any],
    syntax_nodes: list[Any],
    records: dict[str, _WorkingSymbol],
    *,
    context: _RangePathContext | None = None,
) -> None:
    """Rename a name only when every token that spells it is accounted for.

    This is the criterion of token_first_binding.md section 2, and it exists
    because three consecutive rounds of per-shape compatibility did not converge:
    T110 fixed three shapes, T113 removed 190 of 1514 bad implicit nets on one
    production design, and a third, still uncharacterised shape accounted for the
    remaining 1324.  Every one of those rounds asked "which shapes do we know
    about"; this rule asks the shape-independent question instead.

        For a symbol whose old name is ``n``: let T be every physical identifier
        token spelling ``n`` in the source set.  Rename ``n`` only if no token in
        T is unattributed, attributed meaning bound to a semantic reference or to
        a declaration.

    One unattributed token spelled ``n`` therefore preserves every record spelled
    ``n``, and nothing else.  That is provable in a way the semantic direction
    never was: the token set is closed, so there is no thirteenth reference to
    miss.  It covers the three known fail-opens -- a dead generate branch actual,
    the uncharacterised production shape, and a typedef used as another
    aggregate's member type -- together with every shape nobody has met yet, and
    it pays for that in coverage: T109 measured only 28.46% of in-scope names
    fully accounted on that design.

    Three sources of attribution are combined, and all three are needed for the
    denominator to be honest rather than merely small:

    * this run's own records, whose declaration and occurrence ranges are the
      product's real binding rules -- named port connection labels, interface port
      types, aggregate member accesses, type references -- each already verified
      against the source bytes.  A token in that set is either rewritten together
      with its record or belongs to a record this run leaves alone; either way it
      stays correct;
    * the declaration token of every named symbol in the design, including the
      parameters, genvars, modules and subroutines that lie outside the four core
      groups, because a token that declares one of those is accounted for and must
      not be charged against a signal that happens to share its spelling.  A
      declaration token needs no further condition: a rename always rewrites the
      declaration, so a declaration token this run does not rewrite belongs to a
      symbol whose name does not change;
    * the generic smallest-enclosing-reference rule, which reaches references to
      symbols this module keeps no record for at all -- subject to the edited-target
      condition documented on ``_reference_attributions``.

    The rule runs last, after T113's dead-source preserve, because
    ``unelaborated_reference`` names the concrete cause and is the more useful
    diagnostic of the two; a record already preserved keeps its own reason.  The
    preserve is per record and never escalates to a core group, so the T111
    boundary is untouched.
    """

    eligible = tuple(
        record
        for record in records.values()
        if record.support == "eligible" and record.name
    )
    wanted = frozenset(record.name for record in eligible)
    if not wanted:
        return
    if context is None:
        context = _RangePathContext.for_catalog(catalog)
    tokens, unverified = _tokens_spelling(catalog, syntax_nodes, wanted, context)
    accounted: set[tuple[str, int, int]] = set()
    for record in records.values():
        if record.name not in wanted:
            continue
        accounted.add(
            (
                record.declaration.file,
                record.declaration.start,
                record.declaration.end,
            )
        )
        for occurrence in record.occurrences.values():
            source_range = occurrence.source_range
            accounted.add((source_range.file, source_range.start, source_range.end))
    # Every position whose spelling this run would change.  A reference whose
    # target is declared at one of these cannot be left alone.
    rewritten_starts = frozenset(
        (source_range.file, source_range.start)
        for record in eligible
        for source_range in (
            record.declaration,
            *[item.source_range for item in record.occurrences.values()],
        )
    )
    by_start = {(token.file, token.start): token for token in tokens}
    accounted |= _declaration_attributions(catalog, nodes, by_start, wanted, context)
    reference_stats = _ReferenceQueryStats()
    accounted |= _reference_attributions(
        tokens,
        _reference_spans(catalog, nodes, wanted, context),
        rewritten_starts,
        reference_stats,
    )
    context.reference_candidate_checks += reference_stats.candidate_checks
    incomplete = set(unverified)
    for token in tokens:
        if (token.file, token.start, token.end) not in accounted:
            incomplete.add(token.name)
    if not incomplete:
        return
    for record in records.values():
        if record.support == "eligible" and record.name in incomplete:
            record.support = "preserved"
            record.reason = "incomplete_name_coverage"


def _collect_occurrences(
    catalog: SourceCatalog,
    nodes: list[Any],
    target_map: dict[object, str],
    alias_map: dict[tuple[str, int, int], str],
    records: dict[str, _WorkingSymbol],
    binding_issues: dict[str, list[dict[str, object]]],
    *,
    record_index: _RecordPhysicalIndex | None = None,
    context: _RangePathContext | None = None,
) -> dict[str, tuple[dict[str, object], ...]]:
    range_claims: dict[tuple[str, int, int], dict[str, set[str]]] = {}
    for node in nodes:
        node_type = type(node).__name__
        if node_type == "InstanceSymbol" and not str(_safe_attr(node, "name", "")):
            # Array elements are elaboration-only aliases.  Their semantic
            # target is represented by the source-backed array root; an
            # element without its own name must never create a diagnostic or
            # physical edit.
            continue
        if node_type == "PortSymbol":
            symbol_id = _record_for_semantic_target(
                catalog, records, target_map, node,
                record_index=record_index, context=context
            )
            if symbol_id is None:
                symbol_id = _record_for_semantic_target(
                    catalog,
                    records,
                    target_map,
                    _safe_attr(node, "internalSymbol"),
                    record_index=record_index,
                    context=context,
                )
            if symbol_id is not None and records[symbol_id].category == "ports":
                record = records[symbol_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    node,
                    lambda: _range_for_token(
                        catalog,
                        _safe_attr(_safe_attr(node, "syntax"), "name"),
                        record.name,
                        context=context,
                    ),
                    context=context,
                )
                if source_range is not None:
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_port_declaration"),
                        range_claims,
                    )
        if node_type == "ModportPortSymbol":
            symbol_id = _record_for_semantic_target(
                catalog,
                records,
                target_map,
                getattr(node, "internalSymbol", None),
                record_index=record_index,
                context=context,
            )
            if symbol_id is not None:
                record = records[symbol_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    node,
                    lambda: _syntax_identifier_range(
                        catalog,
                        getattr(node, "syntax", None),
                        record.name,
                        context=context,
                    ),
                    context=context,
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
            symbol_id = _record_for_semantic_target(
                catalog, records, target_map, target,
                record_index=record_index, context=context
            )
            if symbol_id is None:
                continue
            record = records[symbol_id]
            value = record.name
            try:
                source_range, provenance = _semantic_expression_range(
                    catalog, node, value, context=context
                )
            except Exception as error:
                _append_binding_issue(
                    catalog,
                    binding_issues,
                    record.category,
                    semantic_kind=record.semantic_kind,
                    name=record.name,
                    candidates=(node, _safe_attr(node, "syntax")),
                    detail=getattr(error, "message", str(error)),
                    context=context,
                )
                if record.support == "eligible":
                    record.support = "preserved"
                    record.reason = "source_binding_incomplete"
                continue
            if source_range is None:
                continue
            occurrence = SymbolOccurrence(source_range, provenance)
            _claim_occurrence(record, occurrence, range_claims)
        elif node_type == "MemberAccessExpression":
            target = getattr(node, "member", None)
            symbol_id = _record_for_semantic_target(
                catalog, records, target_map, target,
                record_index=record_index, context=context
            )
            if symbol_id is None:
                continue
            record = records[symbol_id]
            source_range = _safe_occurrence_range(
                catalog,
                binding_issues,
                record,
                node,
                lambda: _member_access_range(
                    catalog, node, record.name, context=context
                ),
                context=context,
            )
            if source_range is None:
                continue
            occurrence = SymbolOccurrence(
                source_range, _member_access_provenance(catalog, node)
            )
            _claim_occurrence(record, occurrence, range_claims)
        declared = getattr(node, "declaredType", None)
        target = getattr(declared, "type", None)
        if type(target).__name__ == "TypeAliasType":
            alias_key = _definition_key(catalog, target, context=context)
            symbol_id = alias_map.get(alias_key) if alias_key is not None else None
            if symbol_id is not None:
                record = records[symbol_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    node,
                    lambda: _type_occurrence_range(
                        catalog, node, record.name, context=context
                    ),
                    context=context,
                )
                if source_range is not None:
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_type"),
                        range_claims,
                    )
        if node_type == "ConversionExpression" and not getattr(node, "isImplicit", False):
            target = getattr(node, "type", None)
            alias_key = (
                _definition_key(catalog, target, context=context)
                if type(target).__name__ == "TypeAliasType"
                else None
            )
            symbol_id = alias_map.get(alias_key) if alias_key is not None else None
            if symbol_id is not None:
                syntax = getattr(node, "syntax", None)
                record = records[symbol_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    node,
                    lambda: _syntax_identifier_range(
                        catalog,
                        getattr(syntax, "left", None),
                        record.name,
                        context=context,
                    ),
                    context=context,
                )
                if source_range is not None:
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_cast"),
                        range_claims,
                    )
        if node_type == "InstanceSymbol" and getattr(node, "isInterface", False):
            interface_id = _interface_record_for_definition(
                catalog,
                records,
                target_map,
                getattr(node, "definition", None),
                record_index=record_index,
                context=context,
            )
            if interface_id is not None:
                record = records[interface_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    node,
                    lambda: _instance_type_occurrence(
                        catalog, node, record.name, context=context
                    ),
                    context=context,
                )
                if source_range is not None:
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_interface_type"),
                        range_claims,
                    )
        if node_type == "InterfacePortSymbol":
            interface_id = _interface_record_for_definition(
                catalog,
                records,
                target_map,
                getattr(node, "interfaceDef", None),
                record_index=record_index,
                context=context,
            )
            if interface_id is not None:
                record = records[interface_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    node,
                    lambda: _interface_port_type_range(
                        catalog, node, record.name, context=context
                    ),
                    context=context,
                )
                if source_range is not None:
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_interface_port_type"),
                        range_claims,
                    )
            modport_id = _record_for_semantic_target(
                catalog,
                records,
                target_map,
                _interface_port_modport_symbol(node),
                record_index=record_index,
                context=context,
            )
            if modport_id is not None:
                record = records[modport_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    node,
                    lambda: _range_for_token(
                        catalog,
                        _interface_port_modport_token(node),
                        record.name,
                        context=context,
                    ),
                    context=context,
                )
                if source_range is not None:
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(
                            source_range, "semantic_interface_port_modport"
                        ),
                        range_claims,
                    )
        if node_type == "InstanceArraySymbol":
            elements = _interface_leaf_elements(node)
            if not elements:
                continue
            interface_id = _interface_record_for_definition(
                catalog,
                records,
                target_map,
                getattr(elements[0], "definition", None),
                record_index=record_index,
                context=context,
            )
            if interface_id is not None:
                parent = getattr(getattr(node, "syntax", None), "parent", None)
                record = records[interface_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    node,
                    lambda: _range_for_token(
                        catalog,
                        getattr(parent, "type", None),
                        record.name,
                        context=context,
                    ),
                    context=context,
                )
                if source_range is not None:
                    _claim_occurrence(
                        record,
                        SymbolOccurrence(source_range, "semantic_interface_array_type"),
                        range_claims,
                    )
        if node_type == "InstanceSymbol" and getattr(node, "isModule", False):
            ports_by_name = _instance_ports_by_name(node)
            for connection_syntax in _named_port_connection_syntax(node):
                label = _safe_attr(connection_syntax, "name")
                label_text = _safe_attr(label, "rawText", "")
                if not isinstance(label_text, str):
                    label_text = bytes(label_text).decode("utf-8", "replace")
                port = ports_by_name.get(label_text)
                if port is None:
                    continue
                symbol_id = _record_for_semantic_target(
                    catalog, records, target_map, port,
                    record_index=record_index, context=context
                )
                if symbol_id is None:
                    symbol_id = _record_for_semantic_target(
                        catalog,
                        records,
                        target_map,
                        _safe_attr(port, "internalSymbol"),
                        record_index=record_index,
                        context=context,
                    )
                if symbol_id is None:
                    continue
                record = records[symbol_id]
                source_range = _safe_occurrence_range(
                    catalog,
                    binding_issues,
                    record,
                    connection_syntax,
                    lambda: _range_for_token(
                        catalog, label, record.name, context=context
                    ),
                    context=context,
                )
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
    target_map: dict[object, str],
    nodes: list[Any],
    interfaces_by_definition: dict[object, str],
    active_interfaces: set[tuple[str, int, int]],
    binding_issues: dict[str, list[dict[str, object]]],
    *,
    context: _RangePathContext | None = None,
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
        name = str(getattr(definition, "name", ""))
        declaration = _try_declaration_range(
            catalog, binding_issues, "interface", definition, syntax, name,
            candidates=(definition, node, syntax), context=context,
        )
        if declaration is None:
            continue
        key = (declaration.file, declaration.start, declaration.end)
        support = "eligible"
        reason = None
        if catalog.source_set.top is not None and key not in active_interfaces:
            support, reason = "preserved", "outside_top_closure"
        record = _add_working(
            records, target_map, catalog=catalog, category="interface", kind="interface_type",
            semantic_kind=type(definition).__name__, name=name, declaration=declaration,
            owner_module=interfaces_by_definition.get(
                definition,
                f"interface:{declaration.file}:{declaration.start}:{declaration.end}",
            ),
            semantic_owner=interfaces_by_definition.get(
                definition,
                f"interface:{declaration.file}:{declaration.start}:{declaration.end}",
            ),
            impact="interface_type", abi="internal", targets=(definition,), support=support, reason=reason,
        )
        target_map[definition] = record.symbol_id


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
            status = "preserved" if range_issues.get(category) else "empty"
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


def build_rename_index(
    source_catalog: SourceCatalog,
    *,
    categories: Iterable[str],
    stage_observer: StageObserver | None = None,
) -> RenameIndex:
    """Build the four-group index from one already compiled PySlang catalog."""

    if not isinstance(source_catalog, SourceCatalog):
        raise RenameIndexError("RENAME_INDEX_INPUT_INVALID", "input is not SourceCatalog")
    try:
        selected = normalize_categories(categories, default=False)
    except CategoryRegistryError as error:
        raise RenameIndexError("RENAME_INDEX_CATEGORY_INVALID", error.message) from error
    context = _RangePathContext.for_catalog(source_catalog)
    _observe(stage_observer, RENAME_SEMANTIC_INVENTORY, "begin")
    workset = _SemanticWorkset.collect(source_catalog)
    _module_range_map, modules_by_definition = _module_maps(
        source_catalog, workset.instance_body_nodes, context=context
    )
    interfaces_by_range: dict[tuple[str, int, int], str | None] = {}
    interfaces_by_definition = _interface_ids(
        source_catalog,
        workset.instance_body_nodes,
        context=context,
        by_range=interfaces_by_range,
    )
    active_interfaces = _top_active_interfaces(
        source_catalog, nodes=workset.top_interface_nodes, context=context
    )
    active_types = _top_active_types(
        source_catalog, nodes=workset.top_type_nodes, context=context
    )
    _observe(stage_observer, RENAME_SEMANTIC_INVENTORY, "end")
    records: dict[str, _WorkingSymbol] = {}
    target_map: dict[object, str] = {}
    alias_map: dict[tuple[str, int, int], str] = {}
    binding_issues: dict[str, list[dict[str, object]]] = {}
    _observe(stage_observer, RENAME_DECLARATIONS, "begin")
    _register_interface_types(
        source_catalog, set(selected), records, target_map, workset.instance_body_nodes,
        interfaces_by_definition, active_interfaces, binding_issues,
        context=context,
    )
    _register_structs(
        source_catalog, set(selected), records, target_map, alias_map, workset.struct_nodes,
        modules_by_definition, interfaces_by_definition, _module_range_map,
        interfaces_by_range, active_types, binding_issues,
        context=context,
    )
    _register_core_declarations(
        source_catalog, set(selected), records, target_map, workset.declaration_nodes,
        modules_by_definition, interfaces_by_definition, _module_range_map,
        interfaces_by_range, active_interfaces, binding_issues,
        context=context,
    )
    _observe(stage_observer, RENAME_DECLARATIONS, "end")
    record_index = _RecordPhysicalIndex.from_records(records)
    _observe(stage_observer, RENAME_OCCURRENCES, "begin")
    range_issues = _collect_occurrences(
        source_catalog,
        workset.occurrence_nodes,
        target_map,
        alias_map,
        records,
        binding_issues,
        record_index=record_index,
        context=context,
    )
    group_issues = _apply_group_binding_issues(records, binding_issues)
    _apply_readonly_firewall(source_catalog, records)
    _observe(stage_observer, RENAME_OCCURRENCES, "end")
    # Last, and deliberately after every other rule has settled: a record that
    # is still eligible here is one this run would really rename, so it is the
    # only set the dead-source and name-completeness checks have to ask about.
    # Running them after `_apply_group_binding_issues` also keeps that function's
    # per-record transaction boundary untouched; both preserves report themselves
    # through `_category_outcomes` like any other stated per-record reason.  The
    # CST is walked once and shared, and `unelaborated_reference` runs first
    # because it names the concrete cause and is the better diagnostic.
    _observe(stage_observer, RENAME_SYNTAX_INVENTORY, "begin")
    syntax_nodes = _syntax_nodes(source_catalog)
    _observe(stage_observer, RENAME_SYNTAX_INVENTORY, "end")
    _observe(stage_observer, RENAME_UNELABORATED, "begin")
    _apply_unelaborated_references(
        source_catalog,
        workset.dead_source_nodes,
        syntax_nodes,
        records,
        context=context,
    )
    _observe(stage_observer, RENAME_UNELABORATED, "end")
    _observe(stage_observer, RENAME_NAME_COMPLETENESS, "begin")
    _apply_name_completeness(
        source_catalog,
        workset.completeness_nodes,
        syntax_nodes,
        records,
        context=context,
    )
    _observe(stage_observer, RENAME_NAME_COMPLETENESS, "end")
    _observe(stage_observer, RENAME_FINALIZE, "begin")
    for category, category_issues in binding_issues.items():
        existing = list(range_issues.get(category, ()))
        for issue in category_issues:
            if issue not in existing:
                existing.append(issue)
        range_issues[category] = tuple(existing)
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
    result = RenameIndex(
        schema_version=2,
        source_catalog=source_catalog,
        selected_categories=selected,
        symbols=symbols,
        decisions=decisions,
        category_outcomes=_category_outcomes(selected, symbols, range_issues),
    )
    _observe(stage_observer, RENAME_FINALIZE, "end")
    return result


__all__ = [
    "RenameDecision", "RenameIndex", "RenameIndexError", "SourceSymbol",
    "SymbolOccurrence", "build_rename_index",
]
