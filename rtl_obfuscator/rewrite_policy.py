"""Pure category and ABI selection over an already-built SymbolGraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .symbol_graph import SourceSymbol, SymbolGraph


_CANONICAL_CATEGORIES = ("signals", "parameters", "genvars")
_KNOWN_SUPPORT = {"eligible", "preserved", "unsupported"}
_KNOWN_ABI = {"internal", "module_abi", "top_boundary"}


@dataclass(frozen=True)
class RewriteDecision:
    symbol_id: str
    category: str
    action: str
    reason: str | None


@dataclass(frozen=True)
class RewritePolicy:
    schema_version: int
    symbol_graph: SymbolGraph = field(repr=False, compare=False)
    selected_categories: tuple[str, ...]
    abi_categories: tuple[str, ...]
    decisions: tuple[RewriteDecision, ...]

    def to_report(self) -> dict[str, object]:
        counts = {"rename": 0, "preserve": 0, "unsupported": 0}
        decisions = []
        for decision in self.decisions:
            counts[decision.action] += 1
            decisions.append(
                {
                    "symbol_id": decision.symbol_id,
                    "category": decision.category,
                    "action": decision.action,
                    "reason": decision.reason,
                }
            )
        return {
            "schema_version": self.schema_version,
            "symbol_graph": self.symbol_graph.to_report(),
            "selected_categories": list(self.selected_categories),
            "abi_categories": list(self.abi_categories),
            "decisions": decisions,
            "summary": {
                "rename": counts["rename"],
                "preserve": counts["preserve"],
                "unsupported": counts["unsupported"],
                "total": len(self.decisions),
            },
        }


class RewritePolicyError(ValueError):
    """Stable fail-closed error for policy requests and graph validation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _iter_request(values: Iterable[str] | None, *, label: str) -> list[object]:
    if values is None or isinstance(values, (str, bytes)):
        raise RewritePolicyError(
            "REWRITE_POLICY_UNKNOWN_CATEGORY",
            f"{label} must be an iterable of canonical categories",
        )
    try:
        return list(values)
    except TypeError as error:
        raise RewritePolicyError(
            "REWRITE_POLICY_UNKNOWN_CATEGORY",
            f"{label} must be an iterable of canonical categories",
        ) from error


def _normalize_categories(categories: Iterable[str] | None) -> tuple[str, ...]:
    requested = _iter_request(categories, label="categories")
    if not requested:
        raise RewritePolicyError(
            "REWRITE_POLICY_EMPTY_SELECTION",
            "categories must contain at least one canonical category",
        )
    unknown = [
        item
        for item in requested
        if not isinstance(item, str) or item not in _CANONICAL_CATEGORIES
    ]
    if unknown:
        raise RewritePolicyError(
            "REWRITE_POLICY_UNKNOWN_CATEGORY",
            f"unknown category request: {unknown[0]!r}",
        )
    requested_set = set(requested)
    return tuple(category for category in _CANONICAL_CATEGORIES if category in requested_set)


def _normalize_abi_categories(
    abi_categories: Iterable[str] | None,
) -> tuple[str, ...]:
    requested = _iter_request(abi_categories, label="abi_categories")
    unknown = [
        item
        for item in requested
        if not isinstance(item, str) or item not in _CANONICAL_CATEGORIES
    ]
    if unknown:
        raise RewritePolicyError(
            "REWRITE_POLICY_UNKNOWN_CATEGORY",
            f"unknown ABI category request: {unknown[0]!r}",
        )
    requested_set = set(requested)
    return tuple(category for category in _CANONICAL_CATEGORIES if category in requested_set)


def _graph_invalid(message: str) -> RewritePolicyError:
    return RewritePolicyError("REWRITE_POLICY_GRAPH_INVALID", message)


def _validate_graph(symbol_graph: SymbolGraph) -> None:
    top = symbol_graph.source_catalog.source_set.top
    seen_symbol_ids: set[str] = set()
    for symbol in symbol_graph.symbols:
        if symbol.symbol_id in seen_symbol_ids:
            raise _graph_invalid("graph contains duplicate symbol_id")
        seen_symbol_ids.add(symbol.symbol_id)
        if symbol.category not in _CANONICAL_CATEGORIES:
            raise _graph_invalid("graph contains an unknown category")
        if symbol.support not in _KNOWN_SUPPORT:
            raise _graph_invalid("graph contains an unknown support value")
        if symbol.abi not in _KNOWN_ABI:
            raise _graph_invalid("graph contains an unknown ABI value")
        if symbol.support == "eligible" and symbol.reason is not None:
            raise _graph_invalid("eligible graph symbol must not have a reason")
        if symbol.support in {"preserved", "unsupported"} and (
            not isinstance(symbol.reason, str) or not symbol.reason
        ):
            raise _graph_invalid("preserved or unsupported graph symbol needs a reason")
        if symbol.support == "eligible" and symbol.abi == "top_boundary":
            raise _graph_invalid("eligible graph symbol cannot use top_boundary ABI")
        if symbol.support == "eligible" and symbol.abi == "module_abi" and top is None:
            raise _graph_invalid("eligible module_abi graph symbol requires top")


def _decision_for_symbol(
    symbol: SourceSymbol,
    selected_categories: tuple[str, ...],
    abi_categories: tuple[str, ...],
) -> RewriteDecision:
    if symbol.support == "unsupported":
        return RewriteDecision(symbol.symbol_id, symbol.category, "unsupported", symbol.reason)
    if symbol.support == "preserved":
        return RewriteDecision(symbol.symbol_id, symbol.category, "preserve", symbol.reason)
    if symbol.category not in selected_categories:
        return RewriteDecision(
            symbol.symbol_id,
            symbol.category,
            "preserve",
            "category_not_selected",
        )
    if symbol.abi == "internal":
        return RewriteDecision(symbol.symbol_id, symbol.category, "rename", None)
    if symbol.abi == "module_abi":
        if symbol.category in abi_categories:
            return RewriteDecision(symbol.symbol_id, symbol.category, "rename", None)
        return RewriteDecision(
            symbol.symbol_id,
            symbol.category,
            "preserve",
            "abi_not_selected",
        )
    raise _graph_invalid("eligible graph symbol has unsupported ABI decision")


def build_rewrite_policy(
    symbol_graph: SymbolGraph,
    *,
    categories: Iterable[str],
    abi_categories: Iterable[str] = (),
) -> RewritePolicy:
    selected_categories = _normalize_categories(categories)
    normalized_abi = _normalize_abi_categories(abi_categories)
    invalid_abi = [
        category
        for category in normalized_abi
        if category != "parameters" or category not in selected_categories
    ]
    if invalid_abi:
        raise RewritePolicyError(
            "REWRITE_POLICY_INVALID_ABI_CATEGORY",
            f"ABI category is not an eligible selected category: {invalid_abi[0]}",
        )
    if normalized_abi and symbol_graph.source_catalog.source_set.top is None:
        raise RewritePolicyError(
            "REWRITE_POLICY_TOP_REQUIRED",
            "ABI selection requires a selected top",
        )
    _validate_graph(symbol_graph)
    decisions = tuple(
        _decision_for_symbol(symbol, selected_categories, normalized_abi)
        for symbol in symbol_graph.symbols
    )
    return RewritePolicy(
        schema_version=1,
        symbol_graph=symbol_graph,
        selected_categories=selected_categories,
        abi_categories=normalized_abi,
        decisions=decisions,
    )
