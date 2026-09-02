"""Fast, fail-closed mapping adapter for module-local signals.

The ordinary vNext index intentionally builds a complete semantic workset.
This adapter is narrower: the filelist is compiled once for context, then
only explicit modules below ``rewrite_roots`` are projected into the mapping.
No SourceCatalog or RenameIndex builder is called from this module.
"""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

import pyslang

from .category_registry_vnext import (
    CANONICAL_CATEGORIES,
    CategoryRegistryError,
    normalize_categories,
)
from .mapping_vnext import MappingVNext, build_mapping_vnext
from .performance_probe import StageObserver, _observe
from .project_discovery import compile_pyslang_source_set
from .rename_index import (
    RenameDecision,
    RenameIndex,
    SourceSymbol,
    SymbolOccurrence,
    _RangePathContext,
    _semantic_expression_range,
    _tokens_spelling,
)
from .source_catalog import (
    ModuleOwner,
    SourceCatalog,
    SourceCatalogError,
    SourceRange,
    _compile_view,
)
from .source_set import SourceSet
from .rewrite_vnext import CompileEvidence


class FastLocalSignalsError(ValueError):
    """Stable fail-closed error for the fast local-signals adapter."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _within_rewrite_root(file: str, roots: tuple[str, ...]) -> bool:
    path = PurePosixPath(file)
    for root in roots:
        try:
            path.relative_to(PurePosixPath(root))
            return True
        except ValueError:
            continue
    return False


def _buffer_file(view: Any, buffer: object, source_set: SourceSet) -> str:
    try:
        path = Path(view.source_manager.getFullPath(buffer)).resolve()
        return path.relative_to(Path(source_set.source_root).resolve()).as_posix()
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise FastLocalSignalsError(
            "FAST_LOCAL_SOURCE_INVALID", "semantic location is outside SourceSet"
        ) from error


def _token_range(
    view: Any, source_set: SourceSet, token: Any, expected: str
) -> SourceRange:
    if token is None or getattr(token, "isMissing", False):
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "missing identifier token")
    raw = token.rawText
    raw_text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    if raw_text != expected:
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "identifier token mismatch")
    file = _buffer_file(view, token.location.buffer, source_set)
    start = int(token.location.offset)
    encoded = expected.encode("utf-8")
    path = Path(source_set.source_root) / file
    try:
        data = path.read_bytes()
    except OSError as error:
        raise FastLocalSignalsError("FAST_LOCAL_SOURCE_INVALID", f"cannot read {file}") from error
    if not 0 <= start < start + len(encoded) <= len(data) or data[start : start + len(encoded)] != encoded:
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "identifier range does not match source bytes")
    return SourceRange(file, start, start + len(encoded))


def _module_csts(view: Any, source_set: SourceSet) -> tuple[tuple[Any, SourceRange], ...]:
    """Read only direct compilation-unit members for target source files."""

    result: list[tuple[Any, SourceRange]] = []
    source_files = frozenset(source_set.ordered_source_files)
    for member in tuple(getattr(view.syntax_tree.root, "members", ())):
        if getattr(member, "kind", None) != pyslang.syntax.SyntaxKind.ModuleDeclaration:
            continue
        token = getattr(getattr(member, "header", None), "name", None)
        if token is None:
            continue
        declaration = _token_range(view, source_set, token, str(token.rawText))
        if declaration.file not in source_files or not _within_rewrite_root(
            declaration.file, source_set.rewrite_roots
        ):
            continue
        result.append((member, declaration))
    result.sort(key=lambda item: (item[1].file, item[1].start, item[1].end))
    return tuple(result)


def _module_span(view: Any, source_set: SourceSet, syntax: Any, declaration: SourceRange) -> SourceRange:
    """Resolve the physical CST span without walking the compilation root."""

    first = syntax.getFirstToken()
    last = syntax.getLastToken()
    first_file = _buffer_file(view, first.location.buffer, source_set)
    last_file = _buffer_file(view, last.location.buffer, source_set)
    if first_file != last_file or first_file != declaration.file:
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "module CST spans multiple physical files")
    start = int(first.location.offset)
    raw_last = last.rawText
    last_bytes = raw_last.encode("utf-8") if isinstance(raw_last, str) else bytes(raw_last)
    end = int(last.location.offset) + len(last_bytes)
    if end <= start:
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "module CST span is empty")
    return SourceRange(first_file, start, end)


def _definition_key(
    view: Any, source_set: SourceSet, definition: Any
) -> tuple[str, int, int]:
    name = str(getattr(definition, "name", ""))
    location = getattr(definition, "location", None)
    if not name or location is None:
        raise FastLocalSignalsError("FAST_LOCAL_OWNER_INVALID", "module definition lacks source identity")
    return (
        _buffer_file(view, location.buffer, source_set),
        int(location.offset),
        int(location.offset) + len(name.encode("utf-8")),
    )


_HIERARCHY_SCOPE_CONTAINERS = frozenset(
    {"GenerateBlockSymbol", "GenerateBlockArraySymbol", "InstanceArraySymbol"}
)


def _direct_module_instances(scope: Any) -> tuple[Any, ...]:
    """Return module instances from direct hierarchy-scope members only.

    ``Symbol`` scopes expose their direct children through ``__iter__``.  A
    generate block or an instance array is a hierarchy container, so those
    three API shapes are the only objects recursively opened here.  An
    ``InstanceSymbol`` is collected but its body is never opened; this keeps
    discovery on the parent hierarchy edge and leaves body traversal to the
    target-module semantic range pass.
    """

    pending: deque[Any] = deque((scope,))
    seen_scopes: set[int] = set()
    result: list[Any] = []
    while pending:
        current = pending.popleft()
        identity = id(current)
        if identity in seen_scopes:
            continue
        seen_scopes.add(identity)
        try:
            members = tuple(current)
        except (AttributeError, TypeError) as error:
            raise FastLocalSignalsError(
                "FAST_LOCAL_HIERARCHY_INVALID",
                "semantic hierarchy scope does not expose direct members",
            ) from error
        for member in members:
            node_type = type(member).__name__
            if node_type == "InstanceSymbol":
                if getattr(member, "isModule", False) and getattr(member, "body", None) is not None:
                    result.append(member)
            elif node_type in _HIERARCHY_SCOPE_CONTAINERS:
                pending.append(member)
    return tuple(result)


def _module_bodies(view: Any, source_set: SourceSet, targets: tuple[tuple[Any, SourceRange], ...]) -> tuple[tuple[Any, Any, SourceRange], ...]:
    """Find target semantic bodies through direct semantic instance edges."""

    target_by_name_and_range = {
        (str(getattr(syntax.header.name, "rawText", "")), declaration.file, declaration.start): (
            syntax,
            declaration,
        )
        for syntax, declaration in targets
    }
    queue: deque[Any] = deque(tuple(getattr(view.root, "topInstances", ())))
    seen_bodies: set[tuple[str, int, int]] = set()
    found: dict[tuple[str, int, int], tuple[Any, Any, SourceRange]] = {}
    while queue:
        instance = queue.popleft()
        body = getattr(instance, "body", None)
        if body is None:
            continue
        definition = getattr(body, "definition", None)
        try:
            key = _definition_key(view, source_set, definition)
        except FastLocalSignalsError:
            continue
        if key in seen_bodies:
            continue
        seen_bodies.add(key)
        target = target_by_name_and_range.get((str(getattr(definition, "name", "")), key[0], key[1]))
        if target is not None:
            syntax, declaration = target
            found[key] = (body, syntax, _module_span(view, source_set, syntax, declaration))
        # A hierarchy declaration can be nested below one or more generate
        # blocks.  Direct semantic scope members handle those containers while
        # never opening an InstanceSymbol's body during hierarchy discovery.
        queue.extend(_direct_module_instances(body))
    missing = [declaration for _syntax, declaration in targets if (declaration.file, declaration.start, declaration.end) not in found]
    if missing:
        raise FastLocalSignalsError("FAST_LOCAL_OWNER_INVALID", "target module has no semantic body")
    return tuple(found[key] for key in sorted(found))


def _catalog(
    source_set: SourceSet,
    view: Any,
    modules: tuple[ModuleOwner, ...],
    unavailable_names: tuple[str, ...],
) -> SourceCatalog:
    owners = tuple(sorted(("$unit", *(module.owner_id for module in modules))))
    return SourceCatalog(
        schema_version=1,
        source_set=source_set,
        modules=modules,
        top_closure_owner_ids=(),
        catalog_compilation=view.compilation,
        catalog_root=view.root,
        catalog_source_manager=view.source_manager,
        top_compilation=None,
        top_root=None,
        top_source_manager=None,
        semantic_owner_ids=owners,
        readonly_vendor_files=(),
        readonly_include_files=tuple(source_set.included_files),
        fast_unavailable_names=unavailable_names,
    )


def _direct_signal_declarations(
    body: Any,
    syntax: Any,
    view: Any,
    source_set: SourceSet,
    module_span: SourceRange,
) -> tuple[Any, ...]:
    ports = {str(getattr(port, "name", "")) for port in tuple(getattr(body, "portList", ())) }
    result: list[Any] = []
    for member in tuple(getattr(syntax, "members", ())):
        if getattr(member, "kind", None) not in {
            pyslang.syntax.SyntaxKind.DataDeclaration,
            pyslang.syntax.SyntaxKind.NetDeclaration,
        }:
            continue
        for declarator in tuple(getattr(member, "declarators", ())):
            token = getattr(declarator, "name", None)
            if token is None:
                continue
            name = str(getattr(token, "rawText", ""))
            if not name or name in ports:
                continue
            try:
                symbol = body.lookupName(name)
            except Exception as error:
                raise FastLocalSignalsError("FAST_LOCAL_BINDING_INVALID", f"cannot resolve direct signal {name}") from error
            if type(symbol).__name__ not in {"VariableSymbol", "NetSymbol"}:
                raise FastLocalSignalsError("FAST_LOCAL_BINDING_INVALID", f"direct signal {name} is not VariableSymbol or NetSymbol")
            declaration = _token_range(view, source_set, token, name)
            if declaration.file != module_span.file or not module_span.start <= declaration.start < declaration.end <= module_span.end:
                raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", f"signal {name} is outside its module")
            result.append(symbol)
    return tuple(result)


def _semantic_ranges(
    catalog: SourceCatalog,
    body: Any,
    module_span: SourceRange,
) -> tuple[dict[tuple[str, int, int], Any], dict[tuple[str, int, int], list[SymbolOccurrence]]]:
    """Collect direct semantic declarations and references for one body.

    ``body.visit`` is scoped to one target InstanceBodySymbol.  Child module
    bodies are discarded by the physical declaration owner/range checks, so
    they cannot become part of this module's candidate set.
    """

    nodes: list[Any] = []

    def collect(node: Any) -> object:
        nodes.append(node)
        if node is not body and type(node).__name__ == "InstanceBodySymbol":
            return pyslang.ast.VisitAction.Skip
        return pyslang.ast.VisitAction.Advance

    # Skip child module/interface bodies at their boundary.  The target body
    # still includes its procedural scopes, including function-local symbols.
    body.visit(collect)
    context = _RangePathContext.for_catalog(catalog)
    declarations: dict[tuple[str, int, int], Any] = {}
    occurrences: dict[tuple[str, int, int], list[SymbolOccurrence]] = {}
    for node in nodes:
        location = getattr(node, "location", None)
        name = str(getattr(node, "name", ""))
        if location is None or not name:
            continue
        try:
            file = Path(catalog.catalog_source_manager.getFullPath(location.buffer)).resolve().relative_to(Path(catalog.source_set.source_root).resolve()).as_posix()
            key = (file, int(location.offset), int(location.offset) + len(name.encode("utf-8")))
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if key[0] != module_span.file or not module_span.start <= key[1] < key[2] <= module_span.end:
            continue
        definition = getattr(node, "declaringDefinition", None)
        if definition is None or str(getattr(definition, "name", "")) != str(getattr(body, "name", "")):
            continue
        declarations.setdefault(key, node)
    declaration_by_object = {id(symbol): key for key, symbol in declarations.items()}
    for node in nodes:
        if type(node).__name__ not in {"NamedValueExpression", "HierarchicalValueExpression", "ArbitrarySymbolExpression", "MemberAccessExpression"}:
            continue
        target = getattr(node, "symbol", None) or getattr(node, "member", None)
        if target is None:
            continue
        target_key = declaration_by_object.get(id(target))
        if target_key is None:
            # PySlang may hand out an equivalent wrapper; use its direct
            # declaration location, never a spelling lookup.
            location = getattr(target, "location", None)
            name = str(getattr(target, "name", ""))
            if location is None or not name:
                continue
            try:
                file = Path(catalog.catalog_source_manager.getFullPath(location.buffer)).resolve().relative_to(Path(catalog.source_set.source_root).resolve()).as_posix()
                target_key = (file, int(location.offset), int(location.offset) + len(name.encode("utf-8")))
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
        if target_key not in declarations:
            continue
        try:
            if type(node).__name__ == "MemberAccessExpression":
                # Signals are not members in this fast mode; retaining no
                # guessed member range is safer than broadening the scope.
                continue
            source_range, provenance = _semantic_expression_range(
                catalog, node, str(getattr(target, "name", "")), context=context
            )
        except Exception:
            source_range = None
            provenance = "semantic_reference"
        if source_range is None:
            continue
        if source_range.file != module_span.file or not module_span.start <= source_range.start < source_range.end <= module_span.end:
            continue
        occurrences.setdefault(target_key, []).append(SymbolOccurrence(source_range, provenance))
    return declarations, occurrences


def _category_outcomes(
    selected: tuple[str, ...], symbols: tuple[SourceSymbol, ...]
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for category in CANONICAL_CATEGORIES:
        if category != "signals" or category not in selected:
            result.append({"category": category, "status": "empty", "candidate": 0, "rename": 0, "preserve": 0, "unsupported": 0, "issues": []})
            continue
        items = [item for item in symbols if item.category == category]
        issues = [
            {"file": item.declaration.file, "start": item.declaration.start, "message": item.reason}
            for item in items
            if item.reason is not None
        ]
        result.append({
            "category": category,
            "status": "preserved" if any(item.support == "preserved" for item in items) else ("renamed" if items else "empty"),
            "candidate": len(items),
            "rename": sum(item.support == "eligible" for item in items),
            "preserve": sum(item.support == "preserved" for item in items),
            "unsupported": 0,
            "issues": issues,
        })
    return tuple(result)


def build_fast_local_signals_mapping(
    source_set: SourceSet,
    *,
    name_length: int,
    name_factory: Any,
    stage_observer: StageObserver | None = None,
) -> MappingVNext:
    """Compile one filelist and build a signals-only MappingVNext."""

    try:
        selected = normalize_categories(("signals",), default=False)
    except CategoryRegistryError as error:
        raise FastLocalSignalsError("FAST_LOCAL_CATEGORY_INVALID", error.message) from error
    if source_set.origin != "filelist" or not source_set.rewrite_roots or source_set.top is not None:
        raise FastLocalSignalsError("FAST_LOCAL_INPUT_INVALID", "fast path requires filelist rewrite-root with no top")
    _observe(stage_observer, "compile", "begin")
    try:
        view = _compile_view(source_set, top=None, stage_observer=stage_observer)
    except SourceCatalogError as error:
        raise FastLocalSignalsError("FAST_LOCAL_COMPILE_FAILED", error.message) from error
    if view.parse_errors or view.semantic_errors:
        raise FastLocalSignalsError("FAST_LOCAL_COMPILE_FAILED", "filelist compilation has diagnostics")
    _observe(stage_observer, "compile", "end")
    targets = _module_csts(view, source_set)
    if not targets:
        raise FastLocalSignalsError("FAST_LOCAL_OWNER_INVALID", "rewrite-root has no explicit module source unit")
    _observe(stage_observer, "rename_index", "begin")
    bodies = _module_bodies(view, source_set, targets)
    modules: list[ModuleOwner] = []
    all_names: set[str] = set()
    body_by_key = {
        (declaration.file, declaration.start, declaration.end): (body, syntax, span)
        for body, syntax, span in bodies
        for declaration in (
            _token_range(view, source_set, syntax.header.name, str(syntax.header.name.rawText)),
        )
    }
    for syntax, declaration in targets:
        name = str(syntax.header.name.rawText)
        owner_id = f"module:{declaration.file}:{declaration.start}:{declaration.end}"
        modules.append(ModuleOwner(owner_id, name, declaration, False, False))
        all_names.add(name)
    catalog = _catalog(source_set, view, tuple(modules), ())
    direct_symbols: list[SourceSymbol] = []
    all_accounted: dict[str, set[tuple[str, int, int]]] = {}
    for syntax, declaration in targets:
        key = (declaration.file, declaration.start, declaration.end)
        body, _same_syntax, module_span = body_by_key[key]
        direct = _direct_signal_declarations(body, syntax, view, source_set, module_span)
        semantic_declarations, semantic_occurrences = _semantic_ranges(catalog, body, module_span)
        module = next(item for item in modules if item.declaration == declaration)
        all_accounted.setdefault(str(syntax.header.name.rawText), set()).add(
            (declaration.file, declaration.start, declaration.end)
        )
        for semantic_key, symbol in semantic_declarations.items():
            all_names.add(str(getattr(symbol, "name", "")))
            all_accounted.setdefault(str(getattr(symbol, "name", "")), set()).add(semantic_key)
            all_accounted[str(getattr(symbol, "name", ""))].update(
                (item.source_range.file, item.source_range.start, item.source_range.end)
                for item in semantic_occurrences.get(semantic_key, ())
            )
        syntax_nodes: list[Any] = []
        syntax.visit(syntax_nodes.append)
        wanted = frozenset(str(getattr(symbol, "name", "")) for symbol in direct)
        token_records_by_name: dict[str, tuple[Any, ...]] = {}
        unverified_names: set[str] = set()
        for name in wanted:
            token_records, unverified = _tokens_spelling(
                catalog,
                syntax_nodes,
                frozenset((name,)),
                _RangePathContext.for_catalog(catalog),
            )
            token_records_by_name[name] = token_records
            unverified_names.update(unverified)
        for symbol in direct:
            location = symbol.location
            file = Path(catalog.catalog_source_manager.getFullPath(location.buffer)).resolve().relative_to(Path(source_set.source_root).resolve()).as_posix()
            declaration_range = SourceRange(file, int(location.offset), int(location.offset) + len(str(symbol.name).encode("utf-8")))
            symbol_key = (declaration_range.file, declaration_range.start, declaration_range.end)
            occurrences = tuple(dict.fromkeys(semantic_occurrences.get(symbol_key, ())))
            accounted = all_accounted.get(str(symbol.name), set())
            token_records = token_records_by_name.get(str(symbol.name), ())
            incomplete = str(symbol.name) in unverified_names or any(
                item.file == declaration_range.file
                and module_span.start <= item.start < item.end <= module_span.end
                and item.name == str(symbol.name)
                and (item.file, item.start, item.end) not in accounted
                for item in token_records
            )
            support = "preserved" if incomplete else "eligible"
            reason = "incomplete_name_coverage" if incomplete else None
            source_symbol = SourceSymbol(
                symbol_id=f"signals:{declaration_range.file}:{declaration_range.start}:{declaration_range.end}",
                category="signals",
                kind="signal",
                semantic_kind=type(symbol).__name__,
                name=str(symbol.name),
                declaration=declaration_range,
                owner_module=module.name,
                semantic_owner=module.owner_id,
                occurrences=occurrences,
                impact="internal_signal",
                abi="internal",
                support=support,
                reason=reason,
            )
            direct_symbols.append(source_symbol)
    direct_symbols.sort(key=lambda item: (item.declaration.file, item.declaration.start, item.declaration.end))
    symbols = tuple(direct_symbols)
    decisions = tuple(
        RenameDecision(item.symbol_id, item.category, "rename" if item.support == "eligible" else "preserve", item.reason)
        for item in symbols
    )
    fast_catalog = replace(catalog, fast_unavailable_names=tuple(sorted(name for name in all_names if name)))
    _observe(stage_observer, "rename_index", "end")
    _observe(stage_observer, "mapping", "begin")
    index = RenameIndex(2, fast_catalog, selected, symbols, decisions, _category_outcomes(selected, symbols))
    mapping = build_mapping_vnext(index, name_length=name_length, name_factory=name_factory)
    _observe(stage_observer, "mapping", "end")
    return mapping


def compile_fast_gate(source_set: SourceSet) -> CompileEvidence:
    """Compile a staged gate for diagnostics only; no catalog inventory."""

    view = compile_pyslang_source_set(
        root=Path(source_set.source_root),
        compilation_files=source_set.compile_order,
        include_files=source_set.included_files,
        include_dirs=source_set.include_dirs,
        defines=dict(source_set.defines),
        top=None,
    )
    return CompileEvidence(
        catalog_parse_errors=len(view.parse_errors),
        catalog_semantic_errors=len(view.semantic_errors),
        top_overlay_parse_errors=None,
        top_overlay_semantic_errors=None,
    )


__all__ = [
    "FastLocalSignalsError",
    "build_fast_local_signals_mapping",
    "compile_fast_gate",
]
