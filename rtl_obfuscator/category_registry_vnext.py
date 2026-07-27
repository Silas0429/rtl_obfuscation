"""Product-only canonical category registry for the vNext pipeline.

This module deliberately contains no input-mode or legacy profile knowledge.
The registry is the single normalization point shared by the CLI and policy.
"""

from __future__ import annotations

from collections.abc import Iterable


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
ALIASES = {
    "struct": ("struct_types", "struct_fields"),
    "interface": (
        "interfaces",
        "interface_instances",
        "interface_ports",
        "modports",
    ),
}
GROUPS = {category: (category,) for category in CANONICAL_CATEGORIES}
GROUPS.update(ALIASES)
GROUPS["all"] = DEFAULT_CATEGORIES
MODULE_ABI_CATEGORIES = (
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
)


class CategoryRegistryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _items(values: Iterable[str] | None, *, label: str) -> list[object]:
    if values is None or isinstance(values, (str, bytes)):
        raise CategoryRegistryError(
            "CATEGORY_REGISTRY_INVALID", f"{label} must be an iterable"
        )
    try:
        return list(values)
    except TypeError as error:
        raise CategoryRegistryError(
            "CATEGORY_REGISTRY_INVALID", f"{label} must be an iterable"
        ) from error


def normalize_categories(
    values: Iterable[str] | None, *, default: bool = True
) -> tuple[str, ...]:
    requested = list(DEFAULT_CATEGORIES if values is None and default else _items(values, label="categories"))
    if not requested:
        raise CategoryRegistryError("CATEGORY_REGISTRY_EMPTY", "categories cannot be empty")
    expanded: set[str] = set()
    for value in requested:
        if not isinstance(value, str) or not value or value not in GROUPS:
            raise CategoryRegistryError(
                "CATEGORY_REGISTRY_UNKNOWN", f"unknown category: {value!r}"
            )
        expanded.update(GROUPS[value])
    return tuple(category for category in CANONICAL_CATEGORIES if category in expanded)


def normalize_abi_categories(values: Iterable[str] | None) -> tuple[str, ...]:
    requested = _items(values, label="abi_categories")
    unknown = [
        value
        for value in requested
        if not isinstance(value, str) or value not in MODULE_ABI_CATEGORIES
    ]
    if unknown:
        raise CategoryRegistryError(
            "CATEGORY_REGISTRY_UNKNOWN_ABI", f"unknown ABI category: {unknown[0]!r}"
        )
    selected = set(requested)
    return tuple(category for category in MODULE_ABI_CATEGORIES if category in selected)


def category_is_known(value: object) -> bool:
    return isinstance(value, str) and value in CANONICAL_CATEGORIES
