#!/usr/bin/env python3
"""Measure how much of the physical identifier space PySlang can bind.

The probe is read-only: it never rewrites RTL, never produces a gate, and
never creates an output directory.  It answers one question about a real
project, in one run:

    Of every identifier token that physically exists in the SourceSet, how
    many can be attributed to exactly one PySlang semantic target, and what
    are the remaining tokens?

It attributes tokens with a single rule instead of a per-shape extractor:
every PySlang AST node that references a symbol already carries a
``sourceRange``, so a token belongs to the smallest enclosing reference whose
target name equals the token text.  Tokens that no reference claims are
reported as a residual histogram keyed by the smallest enclosing syntax node,
which is the grammatical list of positions that still need explicit rules.

The probe deliberately contains no renaming policy: it does not know about
categories, top boundaries, or preserve reasons.  It measures binding
capability only.
"""

from __future__ import annotations

import argparse
import bisect
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pyslang  # noqa: E402

from rtl_obfuscator.project_discovery import compile_pyslang_source_set  # noqa: E402
from rtl_obfuscator.source_set import (  # noqa: E402
    SourceSetError,
    from_filelist,
    from_project_root,
    from_single_file,
)


FORMAT = "rtl-obfuscation.binding-coverage"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PhysicalToken:
    file: str
    start: int
    end: int
    text: str
    escaped: bool


@dataclass(frozen=True)
class Reference:
    file: str
    start: int
    end: int
    name: str
    target_id: tuple[str, int]
    target_kind: str
    node_kind: str


def _fail(code: str, message: str) -> None:
    print(json.dumps({"error": code, "message": message}, ensure_ascii=False))
    raise SystemExit(2)


def _safe_attr(value: object, name: str, default: object = None) -> Any:
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _semantic_name(raw: str) -> str:
    """Return the semantic name a token spells.

    An escaped identifier is written ``\\name`` in source but PySlang reports
    its symbol name without the leading backslash.  Nothing else is
    normalized: the probe never guesses a name.
    """

    if raw.startswith("\\"):
        return raw[1:].rstrip()
    return raw


def _build_source_set(args: argparse.Namespace):
    modes = [
        args.filelist is not None,
        args.source_root is not None,
        args.input_file is not None,
    ]
    if sum(modes) != 1:
        _fail(
            "PROBE_INPUT_MODE_INVALID",
            "provide exactly one of --filelist, --source-root, --input",
        )
    if args.source_root is not None and args.top is None:
        _fail("PROBE_INPUT_MODE_INVALID", "--source-root requires --top")
    try:
        if args.filelist is not None:
            return from_filelist(
                filelist=Path(args.filelist).expanduser().resolve(),
                source_root=None,
                include_dirs=args.include_dirs,
                defines=args.defines,
                top=args.top,
            )
        if args.source_root is not None:
            return from_project_root(
                project_root=Path(args.source_root).expanduser().resolve(),
                top=args.top,
                include_dirs=args.include_dirs,
                defines=args.defines,
            )
        source_file = Path(args.input_file).expanduser().resolve()
        return from_single_file(
            source_file=source_file,
            source_root=source_file.parent,
            include_dirs=args.include_dirs,
            defines=args.defines,
            top=args.top,
        )
    except SourceSetError as error:
        _fail(getattr(error, "code", "PROBE_INPUT_INVALID"), error.message)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        _fail("PROBE_INPUT_INVALID", str(error))


class _FileResolver:
    """Map a PySlang buffer to a SourceSet-relative path, once per buffer."""

    def __init__(self, manager: Any, root: Path) -> None:
        self._manager = manager
        self._root = root.resolve()
        self._cache: dict[Any, str | None] = {}

    def resolve(self, buffer: Any) -> str | None:
        try:
            cached = self._cache[buffer]
        except (KeyError, TypeError):
            cached = "__miss__"
        if cached != "__miss__":
            return cached
        value: str | None
        try:
            absolute = Path(self._manager.getFullPath(buffer)).resolve()
            value = absolute.relative_to(self._root).as_posix()
        except (OSError, RuntimeError, TypeError, ValueError):
            value = None
        try:
            self._cache[buffer] = value
        except TypeError:
            pass
        return value


def _physical_location(manager: Any, location: Any) -> tuple[Any, bool]:
    try:
        if manager.isMacroLoc(location):
            return manager.getFullyOriginalLoc(location), True
    except Exception:
        return location, False
    return location, False


def _collect_tokens(
    tree: Any, resolver: _FileResolver, root: Path
) -> tuple[dict[tuple[str, int, int], PhysicalToken], dict[str, int]]:
    """Enumerate every identifier token that physically exists."""

    stats = {
        "identifier_tokens_visited": 0,
        "macro_expanded_tokens": 0,
        "outside_source_set": 0,
        "byte_mismatch": 0,
        "escaped_identifiers": 0,
    }
    expansions: dict[tuple[str, int, int], int] = defaultdict(int)
    tokens: dict[tuple[str, int, int], PhysicalToken] = {}
    file_bytes: dict[str, bytes] = {}

    nodes: list[Any] = []
    tree.root.visit(nodes.append)
    manager = resolver._manager
    for node in nodes:
        if type(node).__name__ != "Token":
            continue
        if node.kind != pyslang.parsing.TokenKind.Identifier:
            # SystemIdentifier ($clog2, $display) is a language built-in and
            # never a rename target.
            continue
        stats["identifier_tokens_visited"] += 1
        raw = str(node.rawText)
        if not raw:
            continue
        location, from_macro = _physical_location(manager, node.location)
        if from_macro:
            stats["macro_expanded_tokens"] += 1
        relative = resolver.resolve(location.buffer)
        if relative is None:
            stats["outside_source_set"] += 1
            continue
        start = int(location.offset)
        encoded = raw.encode("utf-8")
        end = start + len(encoded)
        data = file_bytes.get(relative)
        if data is None:
            try:
                data = (root / relative).read_bytes()
            except OSError:
                stats["outside_source_set"] += 1
                continue
            file_bytes[relative] = data
        if not 0 <= start < end <= len(data) or data[start:end] != encoded:
            stats["byte_mismatch"] += 1
            continue
        key = (relative, start, end)
        expansions[key] += 1
        if key not in tokens:
            escaped = raw.startswith("\\")
            if escaped:
                stats["escaped_identifiers"] += 1
            tokens[key] = PhysicalToken(relative, start, end, raw, escaped)

    stats["physical_identifier_tokens"] = len(tokens)
    repeated = {key: count for key, count in expansions.items() if count > 1}
    stats["physical_tokens_with_multiple_expansions"] = len(repeated)
    stats["max_expansions_of_one_physical_token"] = max(repeated.values(), default=1)
    return tokens, stats


def _declaration_identity(
    resolver: _FileResolver, target: Any
) -> tuple[str, int]:
    """Identify a semantic target by its physical declaration location.

    Elaboration produces one distinct Python object per instance, so a module
    instantiated four times yields four target objects for the same physical
    declaration.  Using object identity would report those as four competing
    owners of one source token.  The declaration location is the identity that
    matters for rewriting, which is also what the product's ``symbol_id`` uses.
    """

    try:
        physical, _ = _physical_location(resolver._manager, _safe_attr(target, "location"))
        file = resolver.resolve(_safe_attr(physical, "buffer"))
        if file is not None:
            return (file, int(physical.offset))
    except Exception:
        pass
    return ("$unresolved", id(target))


def _collect_references(
    ast_root: Any, resolver: _FileResolver
) -> tuple[list[Reference], dict[str, int]]:
    """Collect every AST node that references a named symbol.

    Only ``sourceRange`` and the direct target symbol are used.  No typed
    syntax attribute is consulted, so a node whose ``syntax`` is None (for
    example a member access followed by a select) is handled identically to
    one that keeps its syntax.
    """

    stats = {
        "ast_nodes_visited": 0,
        "reference_nodes": 0,
        "without_source_range": 0,
        "outside_source_set": 0,
        "cross_buffer_range": 0,
    }
    references: list[Reference] = []
    nodes: list[Any] = []
    ast_root.visit(nodes.append)
    manager = resolver._manager
    for node in nodes:
        stats["ast_nodes_visited"] += 1
        target = None
        for attribute in ("symbol", "member"):
            try:
                candidate = getattr(node, attribute, None)
            except Exception:
                candidate = None
            if candidate is not None and hasattr(candidate, "name"):
                target = candidate
                break
        if target is None:
            continue
        try:
            name = str(getattr(target, "name", ""))
        except Exception:
            continue
        if not name:
            continue
        stats["reference_nodes"] += 1
        try:
            source_range = getattr(node, "sourceRange", None)
        except Exception:
            source_range = None
        if source_range is None:
            stats["without_source_range"] += 1
            continue
        try:
            start_loc, _ = _physical_location(manager, source_range.start)
            end_loc, _ = _physical_location(manager, source_range.end)
        except Exception:
            stats["without_source_range"] += 1
            continue
        start_file = resolver.resolve(getattr(start_loc, "buffer", None))
        end_file = resolver.resolve(getattr(end_loc, "buffer", None))
        if start_file is None:
            stats["outside_source_set"] += 1
            continue
        if start_file != end_file:
            stats["cross_buffer_range"] += 1
            continue
        try:
            start = int(start_loc.offset)
            end = int(end_loc.offset)
        except Exception:
            stats["without_source_range"] += 1
            continue
        if end <= start:
            stats["without_source_range"] += 1
            continue
        references.append(
            Reference(
                file=start_file,
                start=start,
                end=end,
                name=name,
                target_id=_declaration_identity(resolver, target),
                target_kind=type(target).__name__,
                node_kind=type(node).__name__,
            )
        )
    return references, stats


def _kind_name(value: object) -> str:
    return str(value).rsplit(".", 1)[-1]


def _core_group(node: Any) -> str | None:
    """Return the core group whose rename target this declaration would be.

    The probe uses this only to choose a statistics denominator.  It makes no
    preserve or rename decision and does not consult top closure, ABI, or
    macro provenance.  Names outside the four groups (parameter, genvar,
    module name, subroutine) intentionally return None so they never inflate
    the in-scope coverage ratio.
    """

    kind = type(node).__name__
    if kind in {"VariableSymbol", "NetSymbol"}:
        # A module-owned signal or an interface member; both are in scope.
        return "signals_or_interface_member"
    if kind == "PortSymbol":
        return "ports_or_interface_port"
    if kind == "ModportSymbol":
        return "interface"
    if kind == "FieldSymbol":
        return "struct"
    if kind == "InstanceSymbol":
        return "interface" if _safe_attr(node, "isInterface", False) else None
    if kind == "InstanceArraySymbol":
        elements = tuple(_safe_attr(node, "elements", ()) or ())
        while elements and type(elements[0]).__name__ == "InstanceArraySymbol":
            elements = tuple(_safe_attr(elements[0], "elements", ()) or ())
        if elements and _safe_attr(elements[0], "isInterface", False):
            return "interface"
        return None
    if kind == "InstanceBodySymbol":
        syntax = _safe_attr(node, "syntax")
        if _kind_name(_safe_attr(syntax, "kind")) == "InterfaceDeclaration":
            return "interface"
        return None
    if kind == "TypeAliasType":
        syntax = _safe_attr(node, "syntax")
        if _kind_name(_safe_attr(syntax, "kind")) != "TypedefDeclaration":
            return None
        aggregate = _safe_attr(syntax, "type")
        if _kind_name(_safe_attr(aggregate, "kind")) in {"StructType", "UnionType"}:
            return "struct"
        return None
    return None


def _aggregate_fields(node: Any) -> tuple[Any, ...]:
    """Return the FieldSymbol members of a physical struct/union typedef.

    ``Compilation.getRoot().visit`` does not reach aggregate members, so the
    canonical type is the only route to them.  This mirrors what
    ``rename_index.py:_register_structs`` already does.
    """

    if _core_group(node) != "struct" or type(node).__name__ != "TypeAliasType":
        return ()
    canonical = _safe_attr(node, "canonicalType")
    if canonical is None:
        return ()
    try:
        members = tuple(canonical)
    except Exception:
        return ()
    return tuple(
        member for member in members if type(member).__name__ == "FieldSymbol"
    )


def _collect_declarations(
    ast_root: Any,
    resolver: _FileResolver,
    by_start: dict[tuple[str, int], PhysicalToken],
) -> tuple[dict[tuple[str, int, int], str], dict[str, set[str]], dict[str, int]]:
    """Attribute the declaration token of every named semantic symbol.

    A symbol's own ``location`` is direct semantic evidence of where its
    declaration token starts.  The attribution is accepted only when a real
    identifier token starts exactly there and spells the symbol name, so this
    is byte-verified evidence rather than a name lookup.
    """

    stats = {
        "named_symbols": 0,
        "attributed_declarations": 0,
        "aggregate_fields_seen": 0,
        "location_not_on_matching_token": 0,
        "outside_source_set": 0,
    }
    declared: dict[tuple[str, int, int], str] = {}
    in_scope_names: dict[str, set[str]] = defaultdict(set)

    def attribute(node: Any) -> None:
        try:
            name = str(_safe_attr(node, "name", "") or "")
            location = _safe_attr(node, "location")
        except Exception:
            return
        if not name or location is None:
            return
        stats["named_symbols"] += 1
        group = _core_group(node)
        try:
            physical, _ = _physical_location(resolver._manager, location)
            file = resolver.resolve(_safe_attr(physical, "buffer"))
            if file is None:
                stats["outside_source_set"] += 1
                return
            start = int(physical.offset)
        except Exception:
            stats["location_not_on_matching_token"] += 1
            return
        token = by_start.get((file, start))
        if token is None or _semantic_name(token.text) != name:
            stats["location_not_on_matching_token"] += 1
            return
        if group is not None:
            in_scope_names[name].add(group)
        key = (token.file, token.start, token.end)
        if key not in declared:
            stats["attributed_declarations"] += 1
            declared[key] = type(node).__name__

    nodes: list[Any] = []
    ast_root.visit(nodes.append)
    for node in nodes:
        attribute(node)
        for member in _aggregate_fields(node):
            stats["aggregate_fields_seen"] += 1
            attribute(member)
    return declared, dict(in_scope_names), stats


def _join(
    tokens: dict[tuple[str, int, int], PhysicalToken],
    references: list[Reference],
) -> tuple[dict[tuple[str, int, int], Reference], list[dict[str, object]]]:
    """Attribute each token to the smallest enclosing matching reference."""

    buckets: dict[tuple[str, str], list[Reference]] = defaultdict(list)
    for reference in references:
        buckets[(reference.file, reference.name)].append(reference)

    assigned: dict[tuple[str, int, int], Reference] = {}
    ambiguous: list[dict[str, object]] = []
    for key, token in tokens.items():
        candidates = buckets.get((token.file, _semantic_name(token.text)))
        if not candidates:
            continue
        enclosing = [
            reference
            for reference in candidates
            if reference.start <= token.start and token.end <= reference.end
        ]
        if not enclosing:
            continue
        best = min(enclosing, key=lambda item: item.end - item.start)
        width = best.end - best.start
        tied = {
            reference.target_id
            for reference in enclosing
            if (reference.end - reference.start) == width
        }
        if len(tied) > 1:
            ambiguous.append(
                {
                    "file": token.file,
                    "start": token.start,
                    "text": token.text,
                    "competing_targets": len(tied),
                    "node_kinds": sorted(
                        {
                            reference.node_kind
                            for reference in enclosing
                            if (reference.end - reference.start) == width
                        }
                    ),
                }
            )
            continue
        assigned[key] = best
    return assigned, ambiguous


def _residual_histogram(
    tree: Any,
    resolver: _FileResolver,
    residual: list[PhysicalToken],
    example_limit: int,
) -> list[dict[str, object]]:
    """Group unattributed tokens by their two tightest enclosing syntax nodes.

    The immediate kind alone lumps unrelated positions together: an
    ``IdentifierName`` inside a packed dimension and one inside a cast are
    different grammar problems.  Recording the enclosing pair keeps the
    histogram actionable as a list of grammar productions.
    """

    by_file: dict[str, list[PhysicalToken]] = defaultdict(list)
    for token in residual:
        by_file[token.file].append(token)
    offsets: dict[str, list[int]] = {}
    for file, items in by_file.items():
        items.sort(key=lambda item: item.start)
        offsets[file] = [item.start for item in items]

    # Two tightest enclosing syntax kinds per token, smallest first.
    best: dict[tuple[str, int, int], list[tuple[int, str]]] = defaultdict(list)
    nodes: list[Any] = []
    tree.root.visit(nodes.append)
    manager = resolver._manager
    for node in nodes:
        if type(node).__name__ == "Token":
            continue
        try:
            source_range = _safe_attr(node, "sourceRange")
            if source_range is None:
                continue
            start_loc, _ = _physical_location(manager, source_range.start)
            end_loc, _ = _physical_location(manager, source_range.end)
        except Exception:
            continue
        file = resolver.resolve(_safe_attr(start_loc, "buffer"))
        if file is None or file != resolver.resolve(_safe_attr(end_loc, "buffer")):
            continue
        candidates = by_file.get(file)
        if not candidates:
            continue
        try:
            start = int(start_loc.offset)
            end = int(end_loc.offset)
        except Exception:
            continue
        if end <= start:
            continue
        width = end - start
        kind = _kind_name(_safe_attr(node, "kind", type(node).__name__))
        index = bisect.bisect_left(offsets[file], start)
        while index < len(candidates) and candidates[index].start < end:
            token = candidates[index]
            index += 1
            if token.end > end:
                continue
            entry = best[(token.file, token.start, token.end)]
            entry.append((width, kind))
            entry.sort(key=lambda item: item[0])
            del entry[2:]

    grouped: dict[tuple[str, str], list[PhysicalToken]] = defaultdict(list)
    for token in residual:
        entry = best.get((token.file, token.start, token.end), [])
        kind = entry[0][1] if entry else "$no_enclosing_syntax"
        parent = entry[1][1] if len(entry) > 1 else "$none"
        grouped[(kind, parent)].append(token)

    histogram = []
    for (kind, parent), items in grouped.items():
        items.sort(key=lambda item: (item.file, item.start))
        histogram.append(
            {
                "syntax_kind": kind,
                "parent_syntax_kind": parent,
                "tokens": len(items),
                "distinct_names": len({_semantic_name(item.text) for item in items}),
                "examples": [
                    {"file": item.file, "start": item.start, "text": item.text}
                    for item in items[:example_limit]
                ],
            }
        )
    histogram.sort(
        key=lambda item: (
            -int(item["tokens"]),
            str(item["syntax_kind"]),
            str(item["parent_syntax_kind"]),
        )
    )
    return histogram


def _completeness(
    tokens: dict[tuple[str, int, int], PhysicalToken],
    accounted: set[tuple[str, int, int]],
    worst_limit: int,
    *,
    only_names: set[str] | None = None,
) -> dict[str, object]:
    """Quantify the per-symbol completeness proof this model makes possible.

    A symbol spelled ``n`` can be renamed with a completeness proof only when
    every physical token spelling ``n`` is accounted for, as a declaration or
    as a reference.  One unaccounted token puts exactly the symbols spelled
    ``n`` at risk, and nothing else: this is what would replace a
    category-wide blast radius with a per-symbol decision.

    ``only_names`` restricts the denominator to names an in-scope declaration
    actually introduces, so out-of-scope spellings (parameter, genvar, module
    name) cannot distort the ratio.
    """

    per_name: dict[str, dict[str, int]] = defaultdict(
        lambda: {"accounted": 0, "unaccounted": 0}
    )
    for key, token in tokens.items():
        name = _semantic_name(token.text)
        if only_names is not None and name not in only_names:
            continue
        bucket = per_name[name]
        if key in accounted:
            bucket["accounted"] += 1
        else:
            bucket["unaccounted"] += 1

    clean = [name for name, counts in per_name.items() if counts["unaccounted"] == 0]
    dirty = [
        (name, counts)
        for name, counts in per_name.items()
        if counts["unaccounted"] > 0
    ]
    dirty.sort(key=lambda item: (-item[1]["unaccounted"], item[0]))
    return {
        "distinct_names": len(per_name),
        "names_fully_accounted": len(clean),
        "names_with_unaccounted_tokens": len(dirty),
        "renameable_name_ratio": _ratio(len(clean), len(per_name)),
        "worst_names": [
            {
                "name": name,
                "accounted": counts["accounted"],
                "unaccounted": counts["unaccounted"],
            }
            for name, counts in dirty[:worst_limit]
        ],
    }


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def build_report(args: argparse.Namespace) -> dict[str, object]:
    source_set = _build_source_set(args)
    root = Path(source_set.source_root)
    try:
        view = compile_pyslang_source_set(
            root=root,
            compilation_files=source_set.compile_order,
            include_files=source_set.included_files,
            include_dirs=source_set.include_dirs,
            defines=dict(source_set.defines),
            top=None,
        )
    except (OSError, RuntimeError, ValueError) as error:
        _fail("PROBE_COMPILE_FAILED", str(error))

    if view.parse_errors:
        _fail(
            "PROBE_COMPILE_FAILED",
            f"catalog view has {len(view.parse_errors)} parse errors",
        )

    resolver = _FileResolver(view.source_manager, root)
    tokens, token_stats = _collect_tokens(view.syntax_tree, resolver, root)
    by_start = {(token.file, token.start): token for token in tokens.values()}
    references, reference_stats = _collect_references(view.root, resolver)
    assigned, ambiguous = _join(tokens, references)
    declared, in_scope_names, declaration_stats = _collect_declarations(
        view.root, resolver, by_start
    )

    accounted = set(assigned) | set(declared)
    residual = [token for key, token in tokens.items() if key not in accounted]
    in_scope = set(in_scope_names)
    in_scope_tokens = {
        key: token
        for key, token in tokens.items()
        if _semantic_name(token.text) in in_scope
    }
    in_scope_residual = [
        token
        for key, token in in_scope_tokens.items()
        if key not in accounted
    ]

    histogram = _residual_histogram(
        view.syntax_tree, resolver, residual, args.examples
    )
    in_scope_histogram = _residual_histogram(
        view.syntax_tree, resolver, in_scope_residual, args.examples
    )

    by_node_kind: dict[str, int] = defaultdict(int)
    by_target_kind: dict[str, int] = defaultdict(int)
    for reference in assigned.values():
        by_node_kind[reference.node_kind] += 1
        by_target_kind[reference.target_kind] += 1
    by_declaration_kind: dict[str, int] = defaultdict(int)
    for semantic_kind in declared.values():
        by_declaration_kind[semantic_kind] += 1
    by_group: dict[str, int] = defaultdict(int)
    for groups in in_scope_names.values():
        for group in groups:
            by_group[group] += 1

    total = token_stats["physical_identifier_tokens"]
    in_scope_accounted = sum(1 for key in in_scope_tokens if key in accounted)
    in_scope_ambiguous = sum(
        1
        for item in ambiguous
        if _semantic_name(str(item["text"])) in in_scope
    )
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "input": {
            "origin": source_set.origin,
            "source_root": str(root),
            "top": source_set.top,
            "source_units": len(source_set.compile_order),
            "included_files": len(source_set.included_files),
            "include_dirs": len(source_set.include_dirs),
            "defines": len(source_set.defines),
        },
        "compile": {
            "parse_errors": len(view.parse_errors),
            "semantic_errors": len(view.semantic_errors),
            "nonblocking_errors": len(view.nonblocking_errors),
        },
        "tokens": token_stats,
        "semantic_references": {
            **reference_stats,
            "usable_references": len(references),
            "distinct_target_symbols": len({item.target_id for item in references}),
        },
        "declarations": {
            **declaration_stats,
            "in_scope_names": len(in_scope_names),
            "in_scope_names_by_group": dict(
                sorted(by_group.items(), key=lambda item: (-item[1], item[0]))
            ),
            "attributed_by_semantic_kind": dict(
                sorted(
                    by_declaration_kind.items(), key=lambda item: (-item[1], item[0])
                )
            ),
        },
        "join": {
            "overall": {
                "identifier_tokens": total,
                "accounted": len(accounted),
                "by_reference": len(assigned),
                "by_declaration": len(declared),
                "unaccounted": len(residual),
                "ambiguous": len(ambiguous),
                "coverage_ratio": _ratio(len(accounted), total),
            },
            "in_scope": {
                "identifier_tokens": len(in_scope_tokens),
                "accounted": in_scope_accounted,
                "unaccounted": len(in_scope_residual),
                "ambiguous": in_scope_ambiguous,
                "coverage_ratio": _ratio(in_scope_accounted, len(in_scope_tokens)),
            },
            "reference_coverage_ratio": _ratio(len(assigned), len(references)),
            "attributed_by_ast_node_kind": dict(
                sorted(by_node_kind.items(), key=lambda item: (-item[1], item[0]))
            ),
            "attributed_by_target_kind": dict(
                sorted(by_target_kind.items(), key=lambda item: (-item[1], item[0]))
            ),
            "ambiguous_examples": ambiguous[: args.examples],
        },
        "residual_by_syntax_kind": histogram,
        "residual_in_scope_by_syntax_kind": in_scope_histogram,
        "completeness": {
            "overall": _completeness(tokens, accounted, args.worst_names),
            "in_scope": _completeness(
                tokens, accounted, args.worst_names, only_names=in_scope
            ),
        },
    }


def _print_summary(report: dict[str, object]) -> None:
    tokens = report["tokens"]
    join = report["join"]
    overall = join["overall"]
    scoped = join["in_scope"]
    completeness = report["completeness"]
    inputs = report["input"]
    lines = [
        "binding coverage probe",
        f"  origin={inputs['origin']} top={inputs['top']} "
        f"source_units={inputs['source_units']} headers={inputs['included_files']}",
        f"  physical identifier tokens : {tokens['physical_identifier_tokens']}"
        f"  (macro views {tokens['macro_expanded_tokens']},"
        f" byte_mismatch {tokens['byte_mismatch']})",
        "",
        "  OVERALL (reference only, includes out-of-scope spellings)",
        f"    accounted   : {overall['accounted']} / {overall['identifier_tokens']}"
        f"  ({overall['coverage_ratio']:.2%})",
        f"      reference : {overall['by_reference']}",
        f"      declaration: {overall['by_declaration']}",
        f"    residual    : {overall['unaccounted']}"
        f"   ambiguous: {overall['ambiguous']}",
        f"    names fully accounted: "
        f"{completeness['overall']['names_fully_accounted']}"
        f" / {completeness['overall']['distinct_names']}",
        "",
        "  IN SCOPE (four core groups -- this is the decision number)",
        f"    accounted   : {scoped['accounted']} / {scoped['identifier_tokens']}"
        f"  ({scoped['coverage_ratio']:.2%})",
        f"    residual    : {scoped['unaccounted']}"
        f"   ambiguous: {scoped['ambiguous']}",
        f"    renameable name ratio: "
        f"{completeness['in_scope']['names_fully_accounted']}"
        f" / {completeness['in_scope']['distinct_names']}"
        f"  ({completeness['in_scope']['renameable_name_ratio']:.2%})",
        "",
        "  in-scope residual by syntax kind (the grammar rules still missing):",
    ]
    for entry in report["residual_in_scope_by_syntax_kind"][:15]:
        lines.append(
            f"    {entry['tokens']:>8}  {entry['syntax_kind']}"
            f" < {entry['parent_syntax_kind']}"
            f"  (names={entry['distinct_names']})"
        )
    if not report["residual_in_scope_by_syntax_kind"]:
        lines.append("    (none)")
    print("\n".join(lines), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only PySlang identifier binding coverage probe",
    )
    parser.add_argument("--filelist", help="explicit filelist (top optional)")
    parser.add_argument("--source-root", help="project root; requires --top")
    parser.add_argument("--input", dest="input_file", help="single source unit")
    parser.add_argument("--top", help="selected top module")
    parser.add_argument(
        "--include-dir",
        dest="include_dirs",
        action="append",
        default=[],
        help="include directory, repeatable",
    )
    parser.add_argument(
        "--define",
        dest="defines",
        action="append",
        default=[],
        help="NAME[=VALUE] preprocessor define, repeatable",
    )
    parser.add_argument("--json", help="also write the report to this path")
    parser.add_argument(
        "--examples", type=int, default=3, help="residual examples per syntax kind"
    )
    parser.add_argument(
        "--worst-names", type=int, default=20, help="worst unattributed names to list"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="suppress the human summary on stderr"
    )
    args = parser.parse_args(argv)

    report = build_report(args)
    if not args.quiet:
        _print_summary(report)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)
    if args.json:
        Path(args.json).expanduser().write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
