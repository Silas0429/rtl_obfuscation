"""Schema-2 mapping built from the PySlang RenameIndex."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path
from stat import S_ISREG
from typing import Any

from .source_catalog import SourceCatalog, SourceRange
from .source_set import SourceSet
from .rename_index import (
    RenameIndex,
    RenameDecision,
    SourceSymbol,
    SymbolOccurrence,
)
from .systemverilog_names import is_plain_identifier


NameFactory = Callable[[str, int, frozenset[str]], str]


@dataclass(frozen=True)
class InputFileDigest:
    file: str
    sha256: str


@dataclass(frozen=True)
class MappingRecord:
    symbol_id: str
    category: str
    kind: str
    semantic_kind: str
    action: str
    reason: str | None
    original_name: str
    renamed_name: str | None
    owner_module: str
    semantic_owner: str
    declaration: SourceRange
    occurrences: tuple[SymbolOccurrence, ...]
    impact: str
    abi: str


@dataclass(frozen=True)
class MappingVNext:
    format: str
    schema_version: int
    rename_index: RenameIndex = field(repr=False, compare=False)
    name_length: int
    input_manifest: tuple[InputFileDigest, ...]
    records: tuple[MappingRecord, ...]

    def to_report(self) -> dict[str, object]:
        source_set = self.rename_index.source_catalog.source_set
        return {
            "format": self.format,
            "schema_version": self.schema_version,
            "state": "planned",
            "source_set": _source_set_report(source_set),
            "selection": {
                "selected_categories": list(
                    self.rename_index.selected_categories
                ),
                "abi_categories": [],
                "preserve_top_boundary": True,
            },
            "name_length": self.name_length,
            "input_manifest": [
                {"file": digest.file, "sha256": digest.sha256}
                for digest in self.input_manifest
            ],
            "records": [_record_report(record) for record in self.records],
            "category_outcomes": [dict(item) for item in self.rename_index.category_outcomes],
            "summary": _summary(self.records),
            "range_audit": {
                "declarations": len(self.records),
                "occurrences": sum(
                    len(record.occurrences) for record in self.records
                ),
                "total_ranges": sum(
                    1 + len(record.occurrences) for record in self.records
                ),
            },
        }


class MappingVNextError(ValueError):
    """Stable fail-closed error for mapping vNext construction."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _raise(code: str, message: str) -> None:
    raise MappingVNextError(code, message)


def _source_set_report(source_set: SourceSet) -> dict[str, object]:
    return {
        "schema_version": source_set.schema_version,
        "ordered_source_files": list(source_set.ordered_source_files),
        "included_files": list(source_set.included_files),
        "include_dirs": list(source_set.include_dirs),
        "defines": [
            {"name": name, "value": value}
            for name, value in source_set.defines
        ],
        "top": source_set.top,
        "top_closure_files": list(source_set.top_closure_files),
        "compile_order": list(source_set.compile_order),
    }


def _range_report(source_range: SourceRange) -> dict[str, object]:
    return {
        "file": source_range.file,
        "start": source_range.start,
        "end": source_range.end,
    }


def _record_report(record: MappingRecord) -> dict[str, object]:
    return {
        "record_id": record.symbol_id,
        "symbol_id": record.symbol_id,
        "category": record.category,
        "kind": record.kind,
        "semantic_kind": record.semantic_kind,
        "action": record.action,
        "reason": record.reason,
        "original_name": record.original_name,
        "renamed_name": record.renamed_name,
        "owner_module": record.owner_module,
        "semantic_owner": record.semantic_owner,
        "declaration": _range_report(record.declaration),
        "occurrences": [
            {
                "source_range": _range_report(occurrence.source_range),
                "provenance": occurrence.provenance,
            }
            for occurrence in record.occurrences
        ],
        "impact": record.impact,
        "abi": record.abi,
    }


def _summary(records: tuple[MappingRecord, ...]) -> dict[str, int]:
    counts = {"rename": 0, "preserve": 0, "unsupported": 0}
    for record in records:
        if record.action not in counts:
            _raise("MAPPING_POLICY_INVALID", "record action is not canonical")
        counts[record.action] += 1
    return {
        "rename": counts["rename"],
        "preserve": counts["preserve"],
        "unsupported": counts["unsupported"],
        "total": len(records),
    }


def _validate_index(
    rename_index: RenameIndex,
) -> tuple[RenameIndex, SourceCatalog, SourceSet]:
    if not isinstance(rename_index, RenameIndex):
        _raise("MAPPING_INDEX_INVALID", "input is not a RenameIndex")
    if type(rename_index.schema_version) is not int or rename_index.schema_version != 2:
        _raise("MAPPING_INDEX_INVALID", "RenameIndex schema_version is not 2")
    catalog = rename_index.source_catalog
    if not isinstance(catalog, SourceCatalog) or catalog.schema_version != 1:
        _raise("MAPPING_SOURCE_INVALID", "SourceCatalog schema_version is not 1")
    source_set = catalog.source_set
    if not isinstance(source_set, SourceSet) or source_set.schema_version != 1:
        _raise("MAPPING_SOURCE_INVALID", "SourceSet schema_version is not 1")
    if not isinstance(rename_index.selected_categories, tuple):
        _raise("MAPPING_INDEX_INVALID", "selected_categories is not canonical")
    if not isinstance(rename_index.symbols, tuple) or not isinstance(rename_index.decisions, tuple):
        _raise("MAPPING_INDEX_INVALID", "symbols and decisions are not canonical")
    if len(rename_index.symbols) != len(rename_index.decisions):
        _raise("MAPPING_INDEX_INVALID", "symbols and decisions are not one-to-one")
    for symbol, decision in zip(rename_index.symbols, rename_index.decisions):
        if not isinstance(symbol, SourceSymbol) or not isinstance(decision, RenameDecision):
            _raise("MAPPING_INDEX_INVALID", "RenameIndex contains an invalid symbol or decision")
        if decision.symbol_id != symbol.symbol_id or decision.category != symbol.category:
            _raise("MAPPING_INDEX_INVALID", "RenameIndex decision does not match symbol")
        if decision.action not in {"rename", "preserve", "unsupported"}:
            _raise("MAPPING_INDEX_INVALID", "RenameIndex action is not canonical")
    return rename_index, catalog, source_set


def _physical_files(source_set: SourceSet) -> tuple[str, ...]:
    result: list[str] = []
    for file in (*source_set.ordered_source_files, *source_set.included_files):
        if not isinstance(file, str) or not file or file in result:
            if not isinstance(file, str) or not file:
                _raise("MAPPING_SOURCE_INVALID", "physical file name is invalid")
            continue
        result.append(file)
    if not result:
        _raise("MAPPING_SOURCE_INVALID", "SourceSet has no physical files")
    try:
        root = Path(source_set.source_root).resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _raise("MAPPING_SOURCE_INVALID", f"source_root is invalid: {error}")
    if not root.is_dir():
        _raise("MAPPING_SOURCE_INVALID", "source_root is not a directory")
    for file in result:
        path = (root / file).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            _raise("MAPPING_SOURCE_INVALID", f"physical file is outside source_root: {file}")
        try:
            if not path.is_file() or not S_ISREG(path.stat().st_mode):
                _raise("MAPPING_SOURCE_INVALID", f"physical file is not a regular file: {file}")
        except OSError as error:
            _raise("MAPPING_SOURCE_INVALID", f"physical file cannot be read: {file}: {error}")
    return tuple(result)


def _validate_owners(
    catalog: SourceCatalog,
    rename_index: RenameIndex,
    physical_files: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(catalog.modules, tuple):
        _raise("MAPPING_SOURCE_INVALID", "catalog modules are not canonical")
    owners: dict[str, Any] = {}
    names: set[str] = set()
    for module in catalog.modules:
        owner_id = getattr(module, "owner_id", None)
        name = getattr(module, "name", None)
        if not isinstance(owner_id, str) or not owner_id:
            _raise("MAPPING_SOURCE_INVALID", "catalog module owner_id is invalid")
        if not isinstance(name, str) or not name:
            _raise("MAPPING_SOURCE_INVALID", "catalog module name is invalid")
        if owner_id in owners or name in names:
            _raise("MAPPING_SOURCE_INVALID", "catalog module owner is not unique")
        owners[owner_id] = module
        names.add(name)

    semantic_owner_ids = getattr(catalog, "semantic_owner_ids", ())
    if not isinstance(semantic_owner_ids, tuple) or not all(
        isinstance(owner_id, str) and owner_id for owner_id in semantic_owner_ids
    ):
        _raise("MAPPING_SOURCE_INVALID", "SourceCatalog semantic owner registry is invalid")
    registered = set(semantic_owner_ids)
    if not registered or "$unit" not in registered:
        _raise("MAPPING_SOURCE_INVALID", "SourceCatalog semantic owner registry is incomplete")
    if any(owner_id not in registered for owner_id in owners):
        _raise("MAPPING_SOURCE_INVALID", "module owner is absent from semantic owner registry")
    module_names = {getattr(module, "name", "") for module in catalog.modules}

    physical = set(physical_files)
    for symbol in rename_index.symbols:
        if not isinstance(symbol, SourceSymbol):
            _raise("MAPPING_SOURCE_INVALID", "RenameIndex contains a non-source symbol")
        if symbol.owner_module not in module_names and not symbol.owner_module.startswith("interface:") and symbol.owner_module != "$unit":
            _raise("MAPPING_SOURCE_INVALID", "symbol owner_module is not in SourceCatalog")
        if symbol.semantic_owner not in registered:
            _raise("MAPPING_SOURCE_INVALID", "symbol semantic_owner is not in SourceCatalog")
        for source_range in (
            symbol.declaration,
            *(occurrence.source_range for occurrence in symbol.occurrences),
        ):
            if not isinstance(source_range, SourceRange):
                _raise("MAPPING_SOURCE_INVALID", "symbol range is not a SourceRange")
            if not isinstance(source_range.file, str) or source_range.file not in physical:
                _raise("MAPPING_SOURCE_INVALID", "symbol range is not a physical file")
    return owners


def _read_sources(
    source_set: SourceSet, physical_files: tuple[str, ...]
) -> tuple[dict[str, bytes], tuple[InputFileDigest, ...]]:
    root = Path(source_set.source_root).resolve()
    sources: dict[str, bytes] = {}
    manifest: list[InputFileDigest] = []
    for file in physical_files:
        try:
            data = (root / file).read_bytes()
        except OSError as error:
            _raise("MAPPING_SOURCE_INVALID", f"cannot read physical file {file}: {error}")
        sources[file] = data
        manifest.append(
            InputFileDigest(file=file, sha256=hashlib.sha256(data).hexdigest())
        )
    return sources, tuple(manifest)


def _validate_ranges(
    rename_index: RenameIndex,
    physical_files: tuple[str, ...],
    sources: dict[str, bytes],
) -> None:
    ranges: list[tuple[str, int, int]] = []
    physical = set(physical_files)
    for symbol in rename_index.symbols:
        if not isinstance(symbol.name, str) or not symbol.name:
            _raise("MAPPING_RANGE_INVALID", "symbol original name is invalid")
        for source_range in (
            symbol.declaration,
            *(occurrence.source_range for occurrence in symbol.occurrences),
        ):
            if source_range.file not in physical:
                _raise("MAPPING_SOURCE_INVALID", "range file is not physical")
            if (
                type(source_range.start) is not int
                or type(source_range.end) is not int
            ):
                _raise("MAPPING_RANGE_INVALID", "range bounds must be non-bool integers")
            data = sources[source_range.file]
            if not 0 <= source_range.start < source_range.end <= len(data):
                _raise("MAPPING_RANGE_INVALID", "range is outside source bytes")
            expected = symbol.name.encode("utf-8")
            if data[source_range.start : source_range.end] != expected:
                _raise("MAPPING_RANGE_INVALID", "range bytes do not match original_name")
            ranges.append((source_range.file, source_range.start, source_range.end))

    seen: set[tuple[str, int, int]] = set()
    for item in ranges:
        if item in seen:
            _raise("MAPPING_RANGE_OVERLAP", "ranges contain an exact duplicate")
        seen.add(item)
    ordered = sorted(ranges)
    for previous, current in zip(ordered, ordered[1:]):
        if previous[0] == current[0] and previous[2] > current[1]:
            _raise("MAPPING_RANGE_OVERLAP", "ranges overlap")


def _semantic_names(catalog: SourceCatalog) -> set[str]:
    names: set[str] = set()
    try:
        nodes: list[Any] = []
        catalog.catalog_root.visit(nodes.append)
    except Exception as error:
        _raise("MAPPING_SOURCE_INVALID", f"catalog semantic root is unavailable: {error}")
    for node in nodes:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _unavailable_names(
    catalog: SourceCatalog,
    sources: dict[str, bytes],
    rename_index: RenameIndex,
) -> set[str]:
    unavailable: set[str] = set()
    unavailable.update(_semantic_names(catalog))
    unavailable.update(symbol.name for symbol in rename_index.symbols)
    return unavailable


def build_mapping_vnext(
    rename_index: RenameIndex,
    *,
    name_length: int,
    name_factory: NameFactory,
) -> MappingVNext:
    """Build one canonical planned mapping from an established policy."""

    if type(name_length) is not int or name_length < 4:
        _raise("MAPPING_NAME_LENGTH_INVALID", "name_length must be an integer >= 4")
    if not callable(name_factory):
        _raise("MAPPING_NAME_FACTORY_INVALID", "name_factory must be callable")

    rename_index, catalog, source_set = _validate_index(rename_index)
    physical_files = _physical_files(source_set)
    _validate_owners(catalog, rename_index, physical_files)
    sources, manifest = _read_sources(source_set, physical_files)
    _validate_ranges(rename_index, physical_files, sources)

    records = tuple(
        MappingRecord(
            symbol_id=symbol.symbol_id,
            category=decision.category,
            kind=symbol.kind,
            semantic_kind=symbol.semantic_kind,
            action=decision.action,
            reason=decision.reason,
            original_name=symbol.name,
            renamed_name=None,
            owner_module=symbol.owner_module,
            semantic_owner=symbol.semantic_owner,
            declaration=symbol.declaration,
            occurrences=symbol.occurrences,
            impact=symbol.impact,
            abi=symbol.abi,
        )
        for symbol, decision in zip(rename_index.symbols, rename_index.decisions)
    )

    unavailable = _unavailable_names(catalog, sources, rename_index)
    renamed_records: list[MappingRecord] = []
    for record in records:
        if record.action != "rename":
            renamed_records.append(record)
            continue
        try:
            candidate = name_factory(
                record.symbol_id,
                name_length,
                frozenset(unavailable),
            )
        except Exception as error:
            _raise("MAPPING_NAME_FACTORY_FAILED", f"name factory failed: {error}")
        if (
            not isinstance(candidate, str)
            or len(candidate) != name_length
            or not is_plain_identifier(candidate)
        ):
            _raise("MAPPING_NAME_INVALID", "name factory returned an invalid name")
        if candidate in unavailable:
            _raise("MAPPING_NAME_COLLISION", "name factory returned a colliding name")
        unavailable.add(candidate)
        renamed_records.append(replace(record, renamed_name=candidate))

    return MappingVNext(
        format="rtl-obfuscation.mapping",
        schema_version=2,
        rename_index=rename_index,
        name_length=name_length,
        input_manifest=manifest,
        records=tuple(renamed_records),
    )
