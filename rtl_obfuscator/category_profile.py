"""Canonical category registry and profile resolution for multi-file inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


CANONICAL_CATEGORIES = (
    "signals",
    "parameters",
    "enum_values",
    "genvars",
    "functions",
    "tasks",
    "arguments",
    "instances",
    "generate_blocks",
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
)

DEFAULT_CATEGORIES = CANONICAL_CATEGORIES[:13]
MANUAL_CATEGORIES = CANONICAL_CATEGORIES[13:]
ALIASES = {
    "struct": ("struct_types", "struct_fields"),
    "interface": (
        "interfaces",
        "interface_instances",
        "interface_ports",
        "modports",
    ),
}

PROFILE_SINGLE_MODULE = "single_module"
PROFILE_MANUAL = "manual"
MODE_SINGLE_FILE = "single-file"
MODE_FILELIST = "filelist"
MODE_PROJECT_ROOT = "project-root"

CATEGORY_INVALID = "CATEGORY_INVALID"
CATEGORY_REQUIRES_PROJECT_ROOT = "CATEGORY_REQUIRES_PROJECT_ROOT"
CATEGORY_RANGE_OVERLAP = "CATEGORY_RANGE_OVERLAP"


class ProfileResolutionError(ValueError):
    """Stable CLI-facing error raised while resolving a category profile."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProfileSelection:
    """Canonical category selection shared by every multi-file entry point."""

    requested_categories: tuple[str, ...]
    selected_categories: tuple[str, ...]
    profile: str

    @property
    def is_manual(self) -> bool:
        return self.profile == PROFILE_MANUAL

    @property
    def scope_policy(self) -> str:
        return "top_closure" if self.is_manual else "all_filelist_files"


def resolve(
    requested: Iterable[str] | None,
    *,
    mode: str,
) -> ProfileSelection:
    """Resolve aliases and profile policy in canonical registry order.

    An omitted category request is represented as an empty requested tuple but
    resolves to the same 13-category default as ``all``.  The single-file
    entry point remains intentionally unable to establish a multi-file
    semantic context.
    """

    requested_categories = tuple(requested or ())
    raw = list(requested_categories) if requested_categories else ["all"]
    expanded: set[str] = set()
    alias_manual = False
    for item in raw:
        if item == "all":
            expanded.update(DEFAULT_CATEGORIES)
            continue
        if item in ALIASES:
            alias_manual = True
            expanded.update(ALIASES[item])
            continue
        if item not in CANONICAL_CATEGORIES:
            raise ProfileResolutionError(CATEGORY_INVALID, item)
        expanded.add(item)

    selected = tuple(category for category in CANONICAL_CATEGORIES if category in expanded)
    manual = alias_manual or bool(expanded.intersection(MANUAL_CATEGORIES))
    if manual and mode == MODE_SINGLE_FILE:
        requested_text = ", ".join(requested_categories or ("all",))
        raise ProfileResolutionError(
            CATEGORY_REQUIRES_PROJECT_ROOT,
            f"single-file manual profile is unavailable: {requested_text}",
        )
    return ProfileSelection(
        requested_categories=requested_categories,
        selected_categories=selected,
        profile=PROFILE_MANUAL if manual else PROFILE_SINGLE_MODULE,
    )


def expand(requested: Iterable[str] | None, *, mode: str) -> tuple[str, ...]:
    """Convenience wrapper returning only canonical selected categories."""

    return resolve(requested, mode=mode).selected_categories
