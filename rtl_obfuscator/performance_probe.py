"""Stable, low-overhead stage notifications for the vNext CLI.

The observer is deliberately only a callback type and a forwarding helper.  It
does not own a clock, retain samples, or influence the pipeline it observes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias


StageObserver: TypeAlias = Callable[[str, str], None]


COMPILE_PARSE = "compile.parse"
COMPILE_ELABORATE = "compile.elaborate"
COMPILE_DIAGNOSTICS = "compile.diagnostics"
COMPILE_CATALOG_INVENTORY = "compile.catalog_inventory"
COMPILE_TOP_CLOSURE = "compile.top_closure"
COMPILE_OWNER_REGISTRY = "compile.owner_registry"
RENAME_SEMANTIC_INVENTORY = "rename_index.semantic_inventory"
RENAME_DECLARATIONS = "rename_index.declarations"
RENAME_OCCURRENCES = "rename_index.occurrences"
RENAME_SYNTAX_INVENTORY = "rename_index.syntax_inventory"
RENAME_UNELABORATED = "rename_index.unelaborated"
RENAME_NAME_COMPLETENESS = "rename_index.name_completeness"
RENAME_FINALIZE = "rename_index.finalize"


def _observe(observer: StageObserver | None, stage: str, phase: str) -> None:
    """Notify one optional observer without adding pipeline control flow."""

    if observer is not None:
        observer(stage, phase)


__all__ = [
    "StageObserver",
    "COMPILE_PARSE",
    "COMPILE_ELABORATE",
    "COMPILE_DIAGNOSTICS",
    "COMPILE_CATALOG_INVENTORY",
    "COMPILE_TOP_CLOSURE",
    "COMPILE_OWNER_REGISTRY",
    "RENAME_SEMANTIC_INVENTORY",
    "RENAME_DECLARATIONS",
    "RENAME_OCCURRENCES",
    "RENAME_SYNTAX_INVENTORY",
    "RENAME_UNELABORATED",
    "RENAME_NAME_COMPLETENESS",
    "RENAME_FINALIZE",
    "_observe",
]
