"""Product-only canonical category registry for the vNext pipeline.

This module deliberately contains no input-mode or legacy profile knowledge.
The registry is the single normalization point shared by the CLI and policy.
"""

from __future__ import annotations

from collections.abc import Iterable


CANONICAL_CATEGORIES = ("signals", "ports", "interface", "struct")

DEFAULT_CATEGORIES = CANONICAL_CATEGORIES
ALIASES: dict[str, tuple[str, ...]] = {}
GROUPS = {category: (category,) for category in CANONICAL_CATEGORIES}
GROUPS["all"] = CANONICAL_CATEGORIES


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


def category_is_known(value: object) -> bool:
    return isinstance(value, str) and value in CANONICAL_CATEGORIES
