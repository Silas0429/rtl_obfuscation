"""Fail-closed, definition-local CST mapping for filelist signal targets.

The fast path deliberately has a smaller semantic contract than the normal
vNext index. A complete filelist is parsed once for preprocessing and syntax
context, then each explicitly listed rewrite-root module is inspected only in
its own ``ModuleDeclarationSyntax``. No semantic ``Compilation`` or instance
hierarchy is needed to build the mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .category_registry_vnext import (
    CANONICAL_CATEGORIES,
    CategoryRegistryError,
    normalize_categories,
)
from .mapping_vnext import MappingVNext, build_mapping_vnext
from .performance_probe import StageObserver, _observe
from .project_discovery import (
    PySlangSyntaxView,
    compile_pyslang_source_set,
    parse_pyslang_source_set,
)
from .rename_index import RenameDecision, RenameIndex, SourceSymbol, SymbolOccurrence
from .source_catalog import ModuleOwner, SourceCatalog, SourceCatalogError, SourceRange
from .source_set import SourceSet
from .rewrite_vnext import CompileEvidence


class FastLocalSignalsError(ValueError):
    """Stable fail-closed error for the fast local-signals adapter."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


_PLAIN_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
_DIRECT_SIGNAL_TYPES = frozenset({"logic", "wire"})
_HIERARCHICAL_KINDS = frozenset(
    {"MemberAccessExpression", "HierarchicalValueExpression"}
)
_DECLARATOR_KIND = "Declarator"
_IDENTIFIER_NAME_KIND = "IdentifierName"
_BAD_CONTEXT_KINDS = frozenset(
    {
        "ModuleHeader",
        "FunctionPrototype",
        "TaskPrototype",
        "FunctionPort",
        "TaskPort",
        "ImplicitAnsiPort",
        "ExplicitAnsiPort",
        "NonAnsiPort",
    }
)
_AMBIGUOUS_REASON = "syntax_local_ambiguous"


@dataclass(frozen=True)
class _CstSignal:
    name: str
    semantic_kind: str
    token: Any
    declaration: SourceRange


@dataclass(frozen=True)
class _CstNode:
    node: Any
    kind: str
    source_range: SourceRange | None


@dataclass
class _PhysicalSourceCache:
    """Cache physical paths and bytes while collecting one CST inventory."""

    source_root: Path
    paths_by_buffer: dict[object, str]
    bytes_by_file: dict[str, bytes]

    @classmethod
    def for_source_set(cls, source_set: SourceSet) -> _PhysicalSourceCache:
        return cls(Path(source_set.source_root).resolve(), {}, {})

    def path_for(
        self, view: Any, buffer: object, source_set: SourceSet
    ) -> str:
        if buffer in self.paths_by_buffer:
            return self.paths_by_buffer[buffer]
        try:
            absolute = Path(view.source_manager.getFullPath(buffer)).resolve()
            relative = absolute.relative_to(self.source_root).as_posix()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise FastLocalSignalsError(
                "FAST_LOCAL_SOURCE_INVALID", "syntax location is outside SourceSet"
            ) from error
        self.paths_by_buffer[buffer] = relative
        return relative

    def bytes_for(self, file: str) -> bytes:
        if file not in self.bytes_by_file:
            try:
                self.bytes_by_file[file] = (self.source_root / file).read_bytes()
            except OSError as error:
                raise FastLocalSignalsError(
                    "FAST_LOCAL_SOURCE_INVALID", f"cannot read {file}"
                ) from error
        return self.bytes_by_file[file]


@dataclass(frozen=True)
class _IndexedToken:
    token: Any
    spelling: str
    source_range: SourceRange | None
    key: tuple[str, int, int] | None
    identifier_name_count: int
    ambiguous: bool


@dataclass(frozen=True)
class _ModuleInventory:
    """Compact, once-per-module CST indexes used by all local signals."""

    syntax_nodes: tuple[_CstNode, ...]
    tokens_by_spelling: dict[str, tuple[_IndexedToken, ...]]
    declarator_keys_by_spelling: dict[str, frozenset[tuple[str, int, int]]]
    scopes_by_declarator_key: dict[
        tuple[str, int, int], tuple[SourceRange, ...]
    ]
    authorized_selection_root_keys: frozenset[tuple[str, int, int]]


def _kind(value: Any) -> str:
    """Return the final enum/class component for a PySlang syntax kind."""

    return str(value).rsplit(".", 1)[-1]


def _raw_text(token: Any) -> str:
    raw = getattr(token, "rawText", "")
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def _token_kind(token: Any) -> str:
    return _kind(getattr(token, "kind", ""))


def _is_token(node: Any) -> bool:
    return type(node).__name__ == "Token"


def _within_rewrite_root(file: str, roots: tuple[str, ...]) -> bool:
    path = PurePosixPath(file)
    for root in roots:
        try:
            path.relative_to(PurePosixPath(root))
            return True
        except ValueError:
            continue
    return False


def _buffer_file(
    view: Any,
    buffer: object,
    source_set: SourceSet,
    source_cache: _PhysicalSourceCache | None = None,
) -> str:
    if source_cache is not None:
        return source_cache.path_for(view, buffer, source_set)
    try:
        path = Path(view.source_manager.getFullPath(buffer)).resolve()
        return path.relative_to(Path(source_set.source_root).resolve()).as_posix()
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise FastLocalSignalsError(
            "FAST_LOCAL_SOURCE_INVALID", "syntax location is outside SourceSet"
        ) from error


def _token_range(
    view: Any,
    source_set: SourceSet,
    token: Any,
    expected: str | None = None,
    source_cache: _PhysicalSourceCache | None = None,
) -> SourceRange:
    if token is None or getattr(token, "isMissing", False):
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "missing identifier token")
    location = getattr(token, "location", None)
    if location is None:
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "identifier token has no location")
    manager = view.source_manager
    try:
        if hasattr(manager, "isFileLoc") and not manager.isFileLoc(location):
            raise FastLocalSignalsError(
                "FAST_LOCAL_RANGE_INVALID", "identifier token is not file-backed"
            )
        if hasattr(manager, "isMacroLoc") and manager.isMacroLoc(location):
            raise FastLocalSignalsError(
                "FAST_LOCAL_RANGE_INVALID", "identifier token comes from a macro"
            )
    except FastLocalSignalsError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise FastLocalSignalsError(
            "FAST_LOCAL_RANGE_INVALID", "identifier token location is invalid"
        ) from error
    raw_text = _raw_text(token)
    if expected is not None and raw_text != expected:
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "identifier token mismatch")
    file = _buffer_file(view, location.buffer, source_set, source_cache)
    start = int(location.offset)
    encoded = raw_text.encode("utf-8")
    data = (
        source_cache.bytes_for(file)
        if source_cache is not None
        else (Path(source_set.source_root) / file).read_bytes()
    )
    if (
        not 0 <= start < start + len(encoded) <= len(data)
        or data[start : start + len(encoded)] != encoded
    ):
        raise FastLocalSignalsError(
            "FAST_LOCAL_RANGE_INVALID", "identifier range does not match source bytes"
        )
    return SourceRange(file, start, start + len(encoded))


def _module_span(
    view: Any,
    source_set: SourceSet,
    syntax: Any,
    declaration: SourceRange,
    source_cache: _PhysicalSourceCache | None = None,
) -> SourceRange:
    """Resolve one physical module CST span without semantic elaboration."""

    first = syntax.getFirstToken()
    last = syntax.getLastToken()
    first_file = _buffer_file(view, first.location.buffer, source_set, source_cache)
    last_file = _buffer_file(view, last.location.buffer, source_set, source_cache)
    if first_file != last_file or first_file != declaration.file:
        raise FastLocalSignalsError(
            "FAST_LOCAL_RANGE_INVALID", "module CST spans multiple physical files"
        )
    start = int(first.location.offset)
    end = int(last.location.offset) + len(_raw_text(last).encode("utf-8"))
    if end <= start:
        raise FastLocalSignalsError("FAST_LOCAL_RANGE_INVALID", "module CST span is empty")
    return SourceRange(first_file, start, end)


def _module_csts(
    view: PySlangSyntaxView,
    source_set: SourceSet,
    source_cache: _PhysicalSourceCache | None = None,
) -> tuple[tuple[Any, SourceRange], ...]:
    """Return direct module declarations in rewrite-root source units only."""

    result: list[tuple[Any, SourceRange]] = []
    source_files = frozenset(source_set.ordered_source_files)
    for member in tuple(getattr(view.syntax_tree.root, "members", ())):
        if _kind(getattr(member, "kind", None)) != "ModuleDeclaration":
            continue
        token = getattr(getattr(member, "header", None), "name", None)
        if token is None:
            continue
        declaration = _token_range(
            view, source_set, token, _raw_text(token), source_cache
        )
        if declaration.file not in source_files or not _within_rewrite_root(
            declaration.file, source_set.rewrite_roots
        ):
            continue
        result.append((member, declaration))
    result.sort(key=lambda item: (item[1].file, item[1].start, item[1].end))
    return tuple(result)


def _syntax_nodes(syntax: Any) -> tuple[_CstNode, ...]:
    nodes: list[Any] = []
    syntax.visit(nodes.append)
    return tuple(
        _CstNode(node, _kind(getattr(node, "kind", None)), None)
        for node in nodes
        if not _is_token(node)
    )


def _node_ranges(
    view: Any,
    source_set: SourceSet,
    nodes: tuple[_CstNode, ...],
    source_cache: _PhysicalSourceCache | None = None,
) -> tuple[_CstNode, ...]:
    result: list[_CstNode] = []
    for item in nodes:
        try:
            first = item.node.getFirstToken()
            last = item.node.getLastToken()
            first_file = _buffer_file(
                view, first.location.buffer, source_set, source_cache
            )
            last_file = _buffer_file(
                view, last.location.buffer, source_set, source_cache
            )
            if first_file != last_file:
                continue
            start = int(first.location.offset)
            end = int(last.location.offset) + len(_raw_text(last).encode("utf-8"))
            if end <= start:
                continue
            result.append(_CstNode(item.node, item.kind, SourceRange(first_file, start, end)))
        except (AttributeError, FastLocalSignalsError, OSError, RuntimeError, TypeError, ValueError):
            # A node without a trustworthy physical range cannot authorize an
            # edit. Matching tokens will turn this into object-level preserve.
            result.append(item)
    return tuple(result)


def _tokens(syntax: Any) -> tuple[Any, ...]:
    nodes: list[Any] = []
    syntax.visit(nodes.append)
    return tuple(node for node in nodes if _is_token(node))


def _contains(source_range: SourceRange | None, token_range: SourceRange) -> bool:
    return (
        source_range is not None
        and source_range.file == token_range.file
        and source_range.start <= token_range.start
        and token_range.end <= source_range.end
    )


def _token_is_in_node(token: Any, node: Any) -> bool:
    """Compare token locations without depending on wrapper identity."""

    try:
        location = token.location
        first = node.getFirstToken().location
        last = node.getLastToken().location
        return (
            location.buffer == first.buffer
            and location.buffer == last.buffer
            and int(first.offset) <= int(location.offset)
            and int(location.offset) <= int(last.offset)
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _same_physical_token(left: Any, right: Any) -> bool:
    """Compare CST token wrappers by their physical source location."""

    if left is right:
        return True
    try:
        left_location = left.location
        right_location = right.location
        return (
            left_location.buffer == right_location.buffer
            and int(left_location.offset) == int(right_location.offset)
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _ambiguous_context(item: _CstNode, token: Any) -> bool:
    kind = item.kind
    if kind in _BAD_CONTEXT_KINDS:
        return True
    if kind == "IdentifierSelectName":
        # PySlang represents element/bit/part/indexed selections as one node
        # whose ``identifier`` is the root token. Only that token belongs to
        # the selected module signal; names in the selector expression do not.
        return not _same_physical_token(
            getattr(item.node, "identifier", None), token
        )
    if kind == "ScopedName":
        # A direct ``signal.field`` is the one member-selection form this
        # definition-local path can prove. Scope separators and tokens on the
        # right side remain ambiguous, including any hierarchy represented by
        # another CST shape.
        left = getattr(item.node, "left", None)
        left_identifier = getattr(left, "identifier", None)
        separator = getattr(item.node, "separator", None)
        return not (
            _raw_text(separator) == "."
            and _same_physical_token(left_identifier, token)
        )
    if kind in _HIERARCHICAL_KINDS:
        return True
    if (
        (kind.startswith("Hierarchical") and kind != "HierarchicalInstance")
        or "MemberAccess" in kind
    ):
        return True
    if "Scope" in kind:
        return True
    if kind == "InvocationExpression":
        # Only the callee identifier is a non-value position. Arguments are
        # ordinary value expressions and remain eligible when independently
        # proven by the surrounding CST.
        return _token_is_in_node(token, getattr(item.node, "left", None))
    if "Named" in kind:
        # A named port/parameter/argument has two syntactic roles. The label
        # itself is ambiguous, while its value expression remains a valid
        # value-reference position (for example ``.data_o(left_value)``).
        label = getattr(item.node, "name", None)
        if label is None:
            return True
        if label is token:
            return True
        try:
            return (
                label.location.buffer == token.location.buffer
                and int(label.location.offset) == int(token.location.offset)
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return True
    if "Parameter" in kind or "Port" in kind:
        return True
    # A type-bearing node can contain an identifier that happens to have the
    # same spelling as a signal. It is not a value-reference allowlist entry.
    if "Type" in kind:
        return True
    return False


_NESTED_SCOPE_KINDS = frozenset(
    {
        "FunctionDeclaration",
        "TaskDeclaration",
        "BlockStatement",
        "NamedBlockClause",
        "GenerateBlock",
        "ConditionalGenerate",
        "LoopGenerate",
    }
)


def _range_key(source_range: SourceRange) -> tuple[str, int, int]:
    return (source_range.file, source_range.start, source_range.end)


def _context_index(
    tokens: tuple[_IndexedToken, ...],
    syntax_nodes: tuple[_CstNode, ...],
) -> dict[tuple[str, int, int], tuple[_CstNode, ...]]:
    """Build token-to-containing-node contexts with a range sweep."""

    nodes_by_file: dict[str, list[_CstNode]] = {}
    for item in syntax_nodes:
        if item.source_range is None:
            continue
        nodes_by_file.setdefault(item.source_range.file, []).append(item)
    tokens_by_file: dict[str, list[_IndexedToken]] = {}
    for indexed in tokens:
        if indexed.source_range is None:
            continue
        tokens_by_file.setdefault(indexed.source_range.file, []).append(indexed)

    contexts_by_key: dict[tuple[str, int, int], tuple[_CstNode, ...]] = {}
    for file, file_tokens in tokens_by_file.items():
        ordered_nodes = sorted(
            nodes_by_file.get(file, ()),
            key=lambda item: (
                item.source_range.start,
                -item.source_range.end,
            ),
        )
        ordered_tokens = sorted(
            file_tokens,
            key=lambda item: (
                item.source_range.start,
                item.source_range.end,
            ),
        )
        active: list[_CstNode] = []
        next_node = 0
        for indexed in ordered_tokens:
            token_range = indexed.source_range
            while (
                next_node < len(ordered_nodes)
                and ordered_nodes[next_node].source_range.start <= token_range.start
            ):
                active.append(ordered_nodes[next_node])
                next_node += 1
            active = [
                item
                for item in active
                if item.source_range.end >= token_range.end
            ]
            contexts_by_key[indexed.key] = tuple(active)
    return contexts_by_key


def _module_inventory(
    syntax: Any,
    *,
    view: PySlangSyntaxView,
    source_set: SourceSet,
    module_span: SourceRange,
    source_cache: _PhysicalSourceCache,
) -> _ModuleInventory:
    """Collect all local CST evidence once, before analyzing any signal."""

    syntax_nodes = _node_ranges(
        view, source_set, _syntax_nodes(syntax), source_cache
    )
    raw_tokens = _tokens(syntax)
    identifier_nodes_by_key: dict[tuple[str, int, int], list[_CstNode]] = {}
    for item in syntax_nodes:
        if item.kind != _IDENTIFIER_NAME_KIND or item.source_range is None:
            continue
        identifier_nodes_by_key.setdefault(_range_key(item.source_range), []).append(item)

    authorized_selection_root_keys: set[tuple[str, int, int]] = set()
    for item in syntax_nodes:
        if item.kind != "IdentifierSelectName":
            continue
        identifier = getattr(item.node, "identifier", None)
        if identifier is None:
            continue
        try:
            identifier_range = _token_range(
                view,
                source_set,
                identifier,
                _raw_text(identifier),
                source_cache,
            )
        except FastLocalSignalsError:
            continue
        if _contains(module_span, identifier_range):
            authorized_selection_root_keys.add(_range_key(identifier_range))

    tokens_by_spelling: dict[str, list[_IndexedToken]] = {}
    valid_tokens: list[_IndexedToken] = []
    for token in raw_tokens:
        spelling = _raw_text(token)
        if not spelling or _token_kind(token) not in {"Identifier", "EscapedIdentifier"}:
            continue
        try:
            token_range = _token_range(
                view, source_set, token, spelling, source_cache
            )
        except FastLocalSignalsError:
            # Keep an unlocatable same-spelling token in its bucket so it can
            # force object-level preserve without authorizing an edit.
            indexed = _IndexedToken(token, spelling, None, None, 0, True)
            tokens_by_spelling.setdefault(spelling, []).append(indexed)
            continue
        if not _contains(module_span, token_range):
            continue
        key = _range_key(token_range)
        indexed = _IndexedToken(
            token,
            spelling,
            token_range,
            key,
            len(identifier_nodes_by_key.get(key, ())),
            False,
        )
        valid_tokens.append(indexed)

    contexts_by_key = _context_index(tuple(valid_tokens), syntax_nodes)
    for indexed in valid_tokens:
        contexts = contexts_by_key.get(indexed.key, ())
        tokens_by_spelling.setdefault(indexed.spelling, []).append(
            replace(
                indexed,
                ambiguous=any(
                    _ambiguous_context(item, indexed.token) for item in contexts
                ),
            )
        )

    declarator_keys_by_spelling: dict[str, set[tuple[str, int, int]]] = {}
    for item in syntax_nodes:
        if item.kind != _DECLARATOR_KIND:
            continue
        token = getattr(item.node, "name", None)
        spelling = _raw_text(token)
        if not spelling:
            continue
        try:
            declaration = _token_range(
                view, source_set, token, spelling, source_cache
            )
        except (FastLocalSignalsError, TypeError, ValueError):
            continue
        if _contains(module_span, declaration):
            declarator_keys_by_spelling.setdefault(spelling, set()).add(
                _range_key(declaration)
            )

    scopes_by_declarator_key: dict[
        tuple[str, int, int], tuple[SourceRange, ...]
    ] = {}
    for keys in declarator_keys_by_spelling.values():
        for key in keys:
            scopes_by_declarator_key[key] = tuple(
                item.source_range
                for item in contexts_by_key.get(key, ())
                if item.kind in _NESTED_SCOPE_KINDS and item.source_range is not None
            )
    return _ModuleInventory(
        syntax_nodes,
        {name: tuple(items) for name, items in tokens_by_spelling.items()},
        {name: frozenset(keys) for name, keys in declarator_keys_by_spelling.items()},
        scopes_by_declarator_key,
        frozenset(authorized_selection_root_keys),
    )


def _direct_signal_declarations(
    syntax: Any,
    view: PySlangSyntaxView,
    source_set: SourceSet,
    module_span: SourceRange,
    source_cache: _PhysicalSourceCache | None = None,
) -> tuple[_CstSignal, ...]:
    """Collect direct logic/wire and named-type declarators of one module."""

    result: list[_CstSignal] = []
    for member in tuple(getattr(syntax, "members", ())):
        member_kind = _kind(getattr(member, "kind", None))
        if member_kind not in {"DataDeclaration", "NetDeclaration"}:
            continue
        declaration_type = getattr(member, "type", None)
        type_kind = _kind(getattr(declaration_type, "kind", None))
        if type_kind == "LogicType":
            keyword = _raw_text(getattr(declaration_type, "keyword", None))
            supported_type = keyword in _DIRECT_SIGNAL_TYPES
        elif type_kind == "ImplicitType":
            supported_type = (
                _raw_text(member.getFirstToken()) in _DIRECT_SIGNAL_TYPES
            )
        elif type_kind == "NamedType":
            type_name = getattr(declaration_type, "name", None)
            type_identifier = getattr(type_name, "identifier", None)
            supported_type = (
                _kind(getattr(type_name, "kind", None)) == _IDENTIFIER_NAME_KIND
                and _token_kind(type_identifier) == "Identifier"
                and _PLAIN_IDENTIFIER.fullmatch(_raw_text(type_identifier))
                is not None
            )
        else:
            supported_type = False
        if not supported_type:
            continue
        semantic_kind = "NetSymbol" if member_kind == "NetDeclaration" else "VariableSymbol"
        for declarator in tuple(getattr(member, "declarators", ())):
            if _kind(getattr(declarator, "kind", None)) != _DECLARATOR_KIND:
                continue
            token = getattr(declarator, "name", None)
            if token is None:
                raise FastLocalSignalsError(
                    "FAST_LOCAL_BINDING_INVALID", "direct signal declarator has no name"
                )
            name = _raw_text(token)
            if not name:
                raise FastLocalSignalsError(
                    "FAST_LOCAL_BINDING_INVALID", "direct signal declarator has empty name"
                )
            declaration = _token_range(
                view, source_set, token, name, source_cache
            )
            if not _contains(module_span, declaration):
                raise FastLocalSignalsError(
                    "FAST_LOCAL_RANGE_INVALID", f"signal {name} is outside its module"
                )
            result.append(_CstSignal(name, semantic_kind, token, declaration))
    return tuple(result)


def _analyze_signal(
    signal: _CstSignal,
    *,
    inventory: _ModuleInventory,
) -> tuple[tuple[SymbolOccurrence, ...], str | None]:
    """Authorize only bare value-expression identifier occurrences."""

    declaration_key = _range_key(signal.declaration)
    declarator_keys = inventory.declarator_keys_by_spelling.get(signal.name, frozenset())
    nested_declaration_keys = declarator_keys - {declaration_key}
    ambiguous = bool(nested_declaration_keys)
    if _token_kind(signal.token) != "Identifier" or _PLAIN_IDENTIFIER.fullmatch(signal.name) is None:
        ambiguous = True
    occurrences: list[SymbolOccurrence] = []
    accounted: set[tuple[str, int, int]] = {declaration_key}
    matching_keys: set[tuple[str, int, int] | None] = set()
    for indexed in inventory.tokens_by_spelling.get(signal.name, ()):
        matching_keys.add(indexed.key)
        if indexed.source_range is None or indexed.key is None:
            ambiguous = True
            continue
        key = indexed.key
        if key == declaration_key:
            continue
        if key in nested_declaration_keys:
            ambiguous = True
            continue
        # A same-spelled token in a shadowing scope is intentionally not
        # attributed to the module signal. The declaration above already
        # makes this object preserve-only.
        if any(
            _contains(scope, indexed.source_range)
            for nested_key in nested_declaration_keys
            for scope in inventory.scopes_by_declarator_key.get(nested_key, ())
        ):
            ambiguous = True
            continue
        if _token_kind(indexed.token) != "Identifier":
            ambiguous = True
            continue
        if (
            indexed.identifier_name_count != 1
            and key not in inventory.authorized_selection_root_keys
        ) or indexed.ambiguous:
            ambiguous = True
            continue
        if key in accounted:
            ambiguous = True
            continue
        accounted.add(key)
        occurrences.append(
            SymbolOccurrence(indexed.source_range, "syntax_value_reference")
        )

    # The CST spelling scan is evidence for completeness only. Every same
    # spelling token outside the declaration or approved value-reference
    # allowlist makes this object preserve-only with the fixed T131 reason.
    if matching_keys != accounted:
        ambiguous = True
    return tuple(occurrences), (_AMBIGUOUS_REASON if ambiguous else None)


def _syntax_identifier_names(syntax: Any) -> tuple[str, ...]:
    names: set[str] = set()
    for token in _tokens(syntax):
        if _token_kind(token) != "Identifier":
            continue
        name = _raw_text(token)
        if name:
            names.add(name)
    return tuple(sorted(names))


def _category_outcomes(
    selected: tuple[str, ...], symbols: tuple[SourceSymbol, ...]
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for category in CANONICAL_CATEGORIES:
        if category != "signals" or category not in selected:
            result.append(
                {
                    "category": category,
                    "status": "empty",
                    "candidate": 0,
                    "rename": 0,
                    "preserve": 0,
                    "unsupported": 0,
                    "issues": [],
                }
            )
            continue
        items = [item for item in symbols if item.category == category]
        issues = [
            {"file": item.declaration.file, "start": item.declaration.start, "message": item.reason}
            for item in items
            if item.reason is not None
        ]
        result.append(
            {
                "category": category,
                "status": (
                    "preserved"
                    if any(item.support == "preserved" for item in items)
                    else ("renamed" if items else "empty")
                ),
                "candidate": len(items),
                "rename": sum(item.support == "eligible" for item in items),
                "preserve": sum(item.support == "preserved" for item in items),
                "unsupported": 0,
                "issues": issues,
            }
        )
    return tuple(result)


def _catalog(
    source_set: SourceSet,
    view: PySlangSyntaxView,
    modules: tuple[ModuleOwner, ...],
    unavailable_names: tuple[str, ...],
) -> SourceCatalog:
    owners = tuple(sorted(("$unit", *(module.owner_id for module in modules))))
    return SourceCatalog(
        schema_version=1,
        source_set=source_set,
        modules=modules,
        top_closure_owner_ids=(),
        catalog_compilation=None,
        catalog_root=None,
        catalog_source_manager=view.source_manager,
        top_compilation=None,
        top_root=None,
        top_source_manager=None,
        semantic_owner_ids=owners,
        readonly_vendor_files=tuple(view.vendor_compatibility_files),
        readonly_include_files=tuple(source_set.included_files),
        fast_unavailable_names=unavailable_names or ("__fast_local_no_name__",),
    )


def build_fast_local_signals_mapping(
    source_set: SourceSet,
    *,
    name_length: int,
    name_factory: Any,
    stage_observer: StageObserver | None = None,
) -> MappingVNext:
    """Parse one complete filelist and map direct module-local signals."""

    try:
        selected = normalize_categories(("signals",), default=False)
    except CategoryRegistryError as error:
        raise FastLocalSignalsError("FAST_LOCAL_CATEGORY_INVALID", error.message) from error
    if source_set.origin != "filelist" or not source_set.rewrite_roots or source_set.top is not None:
        raise FastLocalSignalsError(
            "FAST_LOCAL_INPUT_INVALID", "fast path requires filelist rewrite-root with no top"
        )
    _observe(stage_observer, "compile", "begin")
    try:
        view = parse_pyslang_source_set(
            root=Path(source_set.source_root),
            compilation_files=source_set.compile_order,
            include_files=source_set.included_files,
            include_dirs=source_set.include_dirs,
            defines=dict(source_set.defines),
            stage_observer=stage_observer,
        )
    except SourceCatalogError as error:
        raise FastLocalSignalsError("FAST_LOCAL_COMPILE_FAILED", error.message) from error
    except (OSError, RuntimeError, ValueError) as error:
        raise FastLocalSignalsError("FAST_LOCAL_COMPILE_FAILED", str(error)) from error
    if view.parse_errors:
        raise FastLocalSignalsError(
            "FAST_LOCAL_COMPILE_FAILED", "filelist parsing has diagnostics"
        )
    _observe(stage_observer, "compile", "end")

    source_cache = _PhysicalSourceCache.for_source_set(source_set)
    targets = _module_csts(view, source_set, source_cache)
    if not targets:
        raise FastLocalSignalsError(
            "FAST_LOCAL_OWNER_INVALID", "rewrite-root has no explicit module source unit"
        )
    _observe(stage_observer, "rename_index", "begin")
    modules: list[ModuleOwner] = []
    for syntax, declaration in targets:
        name = _raw_text(syntax.header.name)
        owner_id = f"module:{declaration.file}:{declaration.start}:{declaration.end}"
        modules.append(ModuleOwner(owner_id, name, declaration, False, False))
    unavailable_names = _syntax_identifier_names(view.syntax_tree.root)
    catalog = _catalog(source_set, view, tuple(modules), unavailable_names)
    symbols: list[SourceSymbol] = []
    for syntax, declaration in targets:
        module_span = _module_span(view, source_set, syntax, declaration, source_cache)
        inventory = _module_inventory(
            syntax,
            view=view,
            source_set=source_set,
            module_span=module_span,
            source_cache=source_cache,
        )
        module_name = _raw_text(syntax.header.name)
        owner_id = f"module:{declaration.file}:{declaration.start}:{declaration.end}"
        direct = _direct_signal_declarations(
            syntax, view, source_set, module_span, source_cache
        )
        for signal in direct:
            occurrences, reason = _analyze_signal(
                signal,
                inventory=inventory,
            )
            support = "preserved" if reason is not None else "eligible"
            symbols.append(
                SourceSymbol(
                    symbol_id=(
                        f"signals:{signal.declaration.file}:"
                        f"{signal.declaration.start}:{signal.declaration.end}"
                    ),
                    category="signals",
                    kind="signal",
                    semantic_kind=signal.semantic_kind,
                    name=signal.name,
                    declaration=signal.declaration,
                    owner_module=module_name,
                    semantic_owner=owner_id,
                    occurrences=occurrences,
                    impact="internal_signal",
                    abi="internal",
                    support=support,
                    reason=reason,
                )
            )
    symbols.sort(key=lambda item: (item.declaration.file, item.declaration.start, item.declaration.end))
    source_symbols = tuple(symbols)
    decisions = tuple(
        RenameDecision(
            item.symbol_id,
            item.category,
            "rename" if item.support == "eligible" else "preserve",
            item.reason,
        )
        for item in source_symbols
    )
    _observe(stage_observer, "rename_index", "end")
    _observe(stage_observer, "mapping", "begin")
    index = RenameIndex(
        2,
        catalog,
        selected,
        source_symbols,
        decisions,
        _category_outcomes(selected, source_symbols),
    )
    try:
        mapping = build_mapping_vnext(
            index, name_length=name_length, name_factory=name_factory
        )
    except Exception as error:
        raise FastLocalSignalsError("FAST_LOCAL_MAPPING_INVALID", str(error)) from error
    _observe(stage_observer, "mapping", "end")
    return mapping


def compile_fast_gate(source_set: SourceSet) -> CompileEvidence:
    """Compile a staged gate for strict diagnostics only."""

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
