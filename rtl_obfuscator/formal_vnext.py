"""Generic, programmatic Yosys-compatible views for the vNext pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable

import pyslang

from .source_catalog import SourceCatalog, SourceCatalogError, SourceRange, build_source_catalog
from .source_set import SourceSet
from .restore_vnext import RestoreVNextError, audit_orchestration_gate_vnext


class FormalVNextError(ValueError):
    """Stable fail-closed error raised by the formal view service."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class _Edit:
    record: dict[str, Any]
    replacement: bytes


def _fail(code: str, message: str) -> None:
    raise FormalVNextError(code, message)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _physical_files(source_set: SourceSet) -> tuple[str, ...]:
    ordered: list[str] = []
    for relative in (*source_set.compile_order, *source_set.included_files):
        if relative not in ordered:
            ordered.append(relative)
    return tuple(ordered)


def _manifest(root: Path, files: Iterable[str]) -> str:
    payload = b"".join(
        _sha256((root / relative).read_bytes()).encode("ascii")
        + b"  " + relative.encode("utf-8") + b"\n"
        for relative in sorted(files)
    )
    return _sha256(payload)


def _source_range(catalog: SourceCatalog, location: Any, name: str) -> SourceRange:
    if location is None or catalog.catalog_source_manager.isMacroLoc(location):
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic range is macro-generated")
    try:
        path = Path(catalog.catalog_source_manager.getFullPath(location.buffer)).resolve()
        relative = path.relative_to(catalog.source_set.source_root).as_posix()
    except (OSError, RuntimeError, ValueError) as error:
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic range is outside SourceSet")
    if relative not in _physical_files(catalog.source_set):
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic range is not physical")
    start = int(location.offset)
    end = start + len(name.encode("utf-8"))
    source = (catalog.source_set.source_root / relative).read_bytes()
    if start < 0 or end > len(source) or source[start:end] != name.encode("utf-8"):
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic range bytes do not match")
    return SourceRange(relative, start, end)


def _location_source_range(catalog: SourceCatalog, location: Any) -> SourceRange:
    """Resolve a physical semantic location without guessing its token text."""
    if location is None or catalog.catalog_source_manager.isMacroLoc(location):
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic range is macro-generated")
    try:
        path = Path(catalog.catalog_source_manager.getFullPath(location.buffer)).resolve()
        relative = path.relative_to(catalog.source_set.source_root).as_posix()
    except (OSError, RuntimeError, ValueError):
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic range is outside SourceSet")
    if relative not in _physical_files(catalog.source_set):
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic range is not physical")
    offset = int(location.offset)
    source = (catalog.source_set.source_root / relative).read_bytes()
    if offset < 0 or offset > len(source):
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic range offset is invalid")
    return SourceRange(relative, offset, offset)


def _node_range(catalog: SourceCatalog, node: Any, name: str | None = None) -> SourceRange:
    value = str(name if name is not None else getattr(node, "name", ""))
    if not value:
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "semantic node has no source name")
    return _source_range(catalog, getattr(node, "location", None), value.rsplit(".", 1)[-1])


def _alias_key(catalog: SourceCatalog, alias: Any) -> tuple[str, int, int]:
    result = _node_range(catalog, alias)
    return result.file, result.start, result.end


def _packed_aliases(catalog: SourceCatalog, nodes: list[Any]) -> dict[tuple[str, int, int], Any]:
    aliases: dict[tuple[str, int, int], Any] = {}
    for node in nodes:
        if type(node).__name__ != "TypeAliasType":
            continue
        if not getattr(node, "isStruct", False) or getattr(node, "isUnpackedStruct", False):
            continue
        try:
            aliases[_alias_key(catalog, node)] = node
        except FormalVNextError:
            continue
    return aliases


def _alias_for_type(catalog: SourceCatalog, resolved: Any, aliases: dict[tuple[str, int, int], Any]) -> Any | None:
    if resolved is None:
        return None
    candidate = resolved
    if type(candidate).__name__ == "PackedArrayType":
        element = getattr(candidate, "elementType", None)
        if type(element).__name__ == "PackedArrayType":
            nested = getattr(element, "elementType", None)
            if type(nested).__name__ == "TypeAliasType" and _alias_key(catalog, nested) in aliases:
                _fail("FORMAL_VNEXT_UNSUPPORTED", "nested packed aggregate arrays are unsupported")
            return None
        candidate = element
    if type(candidate).__name__ != "TypeAliasType":
        return None
    return aliases.get(_alias_key(catalog, candidate))


def _record(
    *, kind: str, file: str, start: int, end: int, syntax_kind: str,
    source: bytes, replacement: bytes, **variant: Any,
) -> dict[str, Any]:
    if start < 0 or end <= start or end > len(source):
        _fail("FORMAL_VNEXT_RANGE_INVALID", "transformation range is invalid")
    result = {
        "kind": kind,
        "file": file,
        "start": start,
        "end": end,
        "syntax_kind": syntax_kind,
        "structural_ordinal": -1,
        "source_sha256": _sha256(source[start:end]),
        "replacement_sha256": _sha256(replacement),
    }
    result.update(variant)
    return result


def _collect_type_edits(catalog: SourceCatalog, nodes: list[Any], sources: dict[str, bytes], aliases: dict[tuple[str, int, int], Any]) -> dict[tuple[str, int, int], _Edit]:
    edits: dict[tuple[str, int, int], _Edit] = {}
    for node in nodes:
        declared = getattr(node, "declaredType", None)
        resolved = getattr(declared, "type", None)
        alias = _alias_for_type(catalog, resolved, aliases)
        if alias is None:
            continue
        syntax = getattr(declared, "typeSyntax", None)
        source_range = getattr(getattr(syntax, "sourceRange", None), "start", None)
        end_location = getattr(getattr(syntax, "sourceRange", None), "end", None)
        if source_range is None or end_location is None:
            _fail("FORMAL_VNEXT_SOURCE_INVALID", "aggregate type has no source syntax")
        start_info = _location_source_range(catalog, source_range)
        start = start_info.start
        end = int(end_location.offset)
        file = start_info.file
        if end <= start or end > len(sources[file]):
            _fail("FORMAL_VNEXT_SOURCE_INVALID", "aggregate type range is invalid")
        width = getattr(resolved, "bitWidth", None)
        if not isinstance(width, int) or width < 1:
            _fail("FORMAL_VNEXT_SOURCE_INVALID", "aggregate type has invalid width")
        replacement = f"logic [{width - 1}:0]".encode("ascii")
        public = _record(
            kind="lower_packed_aggregate_type", file=file, start=start, end=end,
            syntax_kind=type(syntax).__name__, source=sources[file], replacement=replacement,
            bit_width=width,
        )
        key = (file, start, end)
        edit = _Edit(public, replacement)
        previous = edits.get(key)
        if previous is not None and previous != edit:
            _fail("FORMAL_VNEXT_RANGE_CONFLICT", "aggregate type range has multiple meanings")
        edits[key] = edit
    return edits


def _expression_bytes(catalog: SourceCatalog, sources: dict[str, bytes], expression: Any, expected_file: str) -> bytes:
    source_range = getattr(expression, "sourceRange", None)
    if source_range is None:
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "member base has no source range")
    start = _location_source_range(catalog, source_range.start)
    end = int(source_range.end.offset)
    if start.file != expected_file or end <= start.start:
        _fail("FORMAL_VNEXT_SOURCE_INVALID", "member expression crosses files")
    return sources[expected_file][start.start:end]


def _collect_member_edits(catalog: SourceCatalog, nodes: list[Any], sources: dict[str, bytes], aliases: dict[tuple[str, int, int], Any]) -> dict[tuple[str, int, int], _Edit]:
    field_alias: dict[tuple[str, int, int], tuple[Any, Any]] = {}
    for alias in aliases.values():
        resolved = getattr(getattr(alias, "targetType", None), "type", None)
        if resolved is None or not getattr(resolved, "isStruct", False) or getattr(resolved, "isUnpackedStruct", False):
            _fail("FORMAL_VNEXT_UNSUPPORTED", "aggregate alias is not a packed struct")
        for field in resolved:
            try:
                field_alias[_alias_key(catalog, field)] = (alias, field)
            except FormalVNextError:
                continue
    edits: dict[tuple[str, int, int], _Edit] = {}
    for node in nodes:
        if type(node).__name__ != "MemberAccessExpression":
            continue
        field = getattr(node, "member", None)
        try:
            field_info = field_alias.get(_alias_key(catalog, field))
        except FormalVNextError:
            field_info = None
        if field_info is None:
            continue
        alias, field = field_info
        source_range = getattr(node, "sourceRange", None)
        if source_range is None:
            _fail("FORMAL_VNEXT_SOURCE_INVALID", "packed member has no source range")
        start = _location_source_range(catalog, source_range.start)
        end = int(source_range.end.offset)
        file = start.file
        base = getattr(node, "value", None)
        if type(base).__name__ == "NamedValueExpression":
            base_bytes = _expression_bytes(catalog, sources, base, file)
            base_shape = "NamedValueExpression"
            replacement = base_bytes
        elif type(base).__name__ == "ElementSelectExpression":
            if type(getattr(base, "value", None)).__name__ != "NamedValueExpression":
                _fail("FORMAL_VNEXT_UNSUPPORTED", "nested aggregate member base is unsupported")
            base_bytes = _expression_bytes(catalog, sources, base.value, file)
            selector_bytes = _expression_bytes(catalog, sources, base.selector, file)
            replacement = base_bytes
            base_shape = "ElementSelectExpression"
            struct_width = getattr(getattr(alias, "targetType", None).type, "bitWidth", None)
            field_width = getattr(field.type, "bitWidth", None)
            field_offset = getattr(field, "bitOffset", None)
            if not all(isinstance(value, int) and value >= 0 for value in (struct_width, field_width, field_offset)):
                _fail("FORMAL_VNEXT_SOURCE_INVALID", "packed member layout is invalid")
            replacement += b"[(" + selector_bytes + f")*{struct_width}+{field_offset} +: {field_width}]".encode("ascii")
        else:
            _fail("FORMAL_VNEXT_UNSUPPORTED", "packed member base shape is unsupported")
        if base_shape == "NamedValueExpression":
            struct_width = getattr(getattr(alias, "targetType", None).type, "bitWidth", None)
            field_width = getattr(field.type, "bitWidth", None)
            field_offset = getattr(field, "bitOffset", None)
            if not all(isinstance(value, int) and value >= 0 for value in (struct_width, field_width, field_offset)):
                _fail("FORMAL_VNEXT_SOURCE_INVALID", "packed member layout is invalid")
            replacement += f"[{field_offset} +: {field_width}]".encode("ascii")
        public = _record(
            kind="lower_packed_struct_member", file=file, start=start.start, end=end,
            syntax_kind=type(node).__name__, source=sources[file], replacement=replacement,
            struct_width=struct_width, field_offset=field_offset, field_width=field_width,
            base_shape=base_shape,
        )
        key = (file, start.start, end)
        edit = _Edit(public, replacement)
        previous = edits.get(key)
        if previous is not None and previous != edit:
            _fail("FORMAL_VNEXT_RANGE_CONFLICT", "packed member range has multiple meanings")
        edits[key] = edit
    return edits


def _collect_assertion_edits(catalog: SourceCatalog, nodes: list[Any], sources: dict[str, bytes]) -> dict[tuple[str, int, int], _Edit]:
    edits: dict[tuple[str, int, int], _Edit] = {}
    for node in nodes:
        if type(node).__name__ != "ConcurrentAssertionStatement":
            continue
        syntax = getattr(node, "syntax", None)
        source_range = getattr(syntax, "sourceRange", None)
        if source_range is None:
            _fail("FORMAL_VNEXT_SOURCE_INVALID", "assertion has no source range")
        start = _location_source_range(catalog, source_range.start)
        end = int(source_range.end.offset)
        source = sources[start.file][start.start:end]
        replacement = bytes(byte if byte == 10 else 32 for byte in source)
        public = _record(
            kind="remove_concurrent_assertion", file=start.file, start=start.start, end=end,
            syntax_kind=type(syntax).__name__, source=sources[start.file], replacement=replacement,
        )
        key = (start.file, start.start, end)
        edits[key] = _Edit(public, replacement)
    return edits


def _ordered_edits(collections: Iterable[dict[tuple[str, int, int], _Edit]]) -> list[_Edit]:
    by_range: dict[tuple[str, int, int], _Edit] = {}
    for collection in collections:
        for key, edit in collection.items():
            if key in by_range and by_range[key] != edit:
                _fail("FORMAL_VNEXT_RANGE_CONFLICT", "formal transformations overlap")
            by_range[key] = edit
    ordered = sorted(by_range.values(), key=lambda item: (item.record["file"], item.record["start"], item.record["end"], item.record["kind"]))
    previous: dict[str, int] = {}
    ordinals: dict[tuple[str, str], int] = {}
    result: list[_Edit] = []
    for edit in ordered:
        record = dict(edit.record)
        if record["file"] in previous and record["start"] < previous[record["file"]]:
            _fail("FORMAL_VNEXT_RANGE_CONFLICT", "formal transformations overlap")
        previous[record["file"]] = record["end"]
        key = (record["file"], record["kind"])
        record["structural_ordinal"] = ordinals.get(key, 0)
        ordinals[key] = record["structural_ordinal"] + 1
        result.append(_Edit(record, edit.replacement))
    return result


def _apply(source: bytes, edits: list[_Edit]) -> bytes:
    result = source
    for edit in reversed(edits):
        record = edit.record
        if _sha256(source[record["start"]:record["end"]]) != record["source_sha256"]:
            _fail("FORMAL_VNEXT_SOURCE_INVALID", "transformation source hash changed")
        result = result[:record["start"]] + edit.replacement + result[record["end"]:]
    return result


def _compile_context(source_set: SourceSet) -> dict[str, Any]:
    return {
        "compile_order": list(source_set.compile_order),
        "include_dirs": list(source_set.include_dirs),
        "defines": [{"name": name, "value": value} for name, value in source_set.defines],
    }


def _read_sources(source_set: SourceSet) -> dict[str, bytes]:
    try:
        return {relative: (source_set.source_root / relative).read_bytes() for relative in _physical_files(source_set)}
    except OSError as error:
        _fail("FORMAL_VNEXT_IO_ERROR", str(error))


def _compute(source_set: SourceSet) -> tuple[dict[str, bytes], list[_Edit], dict[str, Any], str]:
    if source_set.top is None:
        _fail("FORMAL_VNEXT_INPUT_INVALID", "formal view requires a selected top")
    try:
        catalog = build_source_catalog(source_set)
    except (SourceCatalogError, OSError, RuntimeError, ValueError) as error:
        _fail("FORMAL_VNEXT_INPUT_INVALID", str(error))
    nodes: list[Any] = []
    semantic_root = catalog.top_root if source_set.top is not None else catalog.catalog_root
    if semantic_root is None:
        _fail("FORMAL_VNEXT_INPUT_INVALID", "selected top has no semantic overlay")
    semantic_root.visit(nodes.append)
    sources = _read_sources(source_set)
    aliases = _packed_aliases(catalog, nodes)
    edits = _ordered_edits(
        (
            _collect_type_edits(catalog, nodes, sources, aliases),
            _collect_member_edits(catalog, nodes, sources, aliases),
            _collect_assertion_edits(catalog, nodes, sources),
        )
    )
    return sources, edits, _compile_context(source_set), _manifest(source_set.source_root, _physical_files(source_set))


def _yosys_atom(value: str) -> str:
    if any(character.isspace() or character in {'"', "'", ";"} for character in value):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "Yosys path or define is not a simple atom")
    return value


def _validate_yosys(root: Path, source_set: SourceSet) -> None:
    files = [_yosys_atom(str(root / relative)) for relative in source_set.compile_order]
    includes = [f"-I{_yosys_atom(str(root / relative))}" for relative in source_set.include_dirs]
    defines = [f"-D{_yosys_atom(name + '=' + value)}" for name, value in source_set.defines]
    script = "read_verilog -sv -formal -defer " + " ".join([*includes, *defines, *files]) + f"; hierarchy -check -top {_yosys_atom(source_set.top or '')}"
    process = subprocess.run(["yosys", "-Q", "-p", script], capture_output=True, text=True, check=False)
    if process.returncode != 0:
        _fail("FORMAL_VNEXT_YOSYS_FAILED", process.stdout + process.stderr)


def _validate_output(path: Path, *, protected: Path) -> Path:
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("FORMAL_VNEXT_OUTPUT_INVALID", str(error))
    if resolved.exists() or not resolved.parent.is_dir():
        _fail("FORMAL_VNEXT_OUTPUT_INVALID", "output must be absent and parent must exist")
    if resolved == protected or resolved.is_relative_to(protected):
        _fail("FORMAL_VNEXT_OUTPUT_INVALID", "output overlaps source")
    return resolved


def _validate_targets(
    output_dir: Path,
    manifest_path: Path,
    *,
    protected: tuple[Path, ...],
) -> tuple[Path, Path]:
    output = _validate_output(output_dir, protected=protected[0])
    try:
        manifest = Path(manifest_path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("FORMAL_VNEXT_OUTPUT_INVALID", str(error))
    if manifest.exists() or manifest.is_symlink() or not manifest.parent.is_dir():
        _fail("FORMAL_VNEXT_OUTPUT_INVALID", "manifest must be absent and parent must exist")
    if any(_overlap_path(target, protected_path) for target in (output, manifest) for protected_path in protected):
        _fail("FORMAL_VNEXT_OUTPUT_INVALID", "output overlaps an input")
    if _overlap_path(output, manifest):
        _fail("FORMAL_VNEXT_OUTPUT_INVALID", "output and manifest overlap")
    return output, manifest


def _overlap_path(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def _publish(staged_view: Path, staged_manifest: Path, output_dir: Path, manifest_path: Path) -> None:
    try:
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if output_dir.exists() or manifest_path.exists():
            _fail("FORMAL_VNEXT_OUTPUT_INVALID", "publish target exists")
        staged_view.rename(output_dir)
        staged_manifest.rename(manifest_path)
    except FormalVNextError:
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        if manifest_path.exists():
            manifest_path.unlink(missing_ok=True)
        raise
    except OSError as error:
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        if manifest_path.exists():
            manifest_path.unlink(missing_ok=True)
        _fail("FORMAL_VNEXT_IO_ERROR", str(error))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    path.write_bytes(payload)


def build_formal_view_vnext(source_set: SourceSet, *, output_dir: Path, manifest_path: Path) -> dict[str, Any]:
    """Build one deterministic Yosys compatibility view from a SourceSet."""
    if not isinstance(source_set, SourceSet):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "source_set is not SourceSet")
    output, manifest = _validate_targets(
        Path(output_dir),
        Path(manifest_path),
        protected=(source_set.source_root.resolve(),),
    )
    sources, edits, context, source_manifest = _compute(source_set)
    physical = _physical_files(source_set)
    temporary = Path(tempfile.mkdtemp(prefix=".formal-vnext-", dir=str(output.parent)))
    try:
        view = temporary / "view"
        for relative in physical:
            target = view / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_apply(sources[relative], [edit for edit in edits if edit.record["file"] == relative]))
        (view / "design.f").write_text("".join(f"{relative}\n" for relative in source_set.compile_order), encoding="utf-8")
        view_manifest = _manifest(view, physical)
        report = {
            "format": "rtl-obfuscation.formal-view-vnext",
            "schema_version": 1,
            "state": "verified",
            "source_set": {
                "origin": source_set.origin,
                "top": source_set.top,
                "compile_order": list(source_set.compile_order),
                "physical_files": list(physical),
                "include_dirs": list(source_set.include_dirs),
                "defines": [{"name": name, "value": value} for name, value in source_set.defines],
            },
            "source_manifest_sha256": source_manifest,
            "view_manifest_sha256": view_manifest,
            "design_file": "design.f",
            "transformations": [edit.record for edit in edits],
        }
        _validate_yosys(view, source_set)
        staged_manifest = temporary / "manifest.json"
        _write_json(staged_manifest, report)
        _publish(view, staged_manifest, output, manifest)
    except FormalVNextError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        _fail("FORMAL_VNEXT_IO_ERROR", str(error))
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {"files": len(physical), "top": source_set.top, "transformations": len(edits), "view_manifest_sha256": view_manifest}


def _load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _fail("FORMAL_VNEXT_INPUT_INVALID", f"invalid report: {error}")
    if not isinstance(value, dict) or value.get("format") != "rtl-obfuscation.orchestration-vnext" or value.get("state") != "restored":
        _fail("FORMAL_VNEXT_INPUT_INVALID", "orchestration report is not verified")
    return value


def _source_set_from_report(report: dict[str, Any], root: Path) -> SourceSet:
    source = report.get("source_set")
    if not isinstance(source, dict):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "report source_set is invalid")
    try:
        defines = tuple((str(item["name"]), str(item["value"])) for item in source["defines"])
        result = SourceSet(
            schema_version=int(source["schema_version"]), origin=str(source["origin"]), source_root=root.resolve(),
            ordered_source_files=tuple(str(item) for item in source["ordered_source_files"]),
            included_files=tuple(str(item) for item in source["included_files"]),
            include_dirs=tuple(str(item) for item in source["include_dirs"]), defines=defines,
            top=None if source.get("top") is None else str(source["top"]),
            top_closure_files=tuple(str(item) for item in source["top_closure_files"]),
            compile_order=tuple(str(item) for item in source["compile_order"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        _fail("FORMAL_VNEXT_INPUT_INVALID", f"report SourceSet is invalid: {error}")
    if result.schema_version != 1 or not result.compile_order or not result.top:
        _fail("FORMAL_VNEXT_INPUT_INVALID", "report SourceSet is incomplete")
    return result


def _lexer_identifier_tokens(path: Path, source: bytes, replacements: dict[str, str]) -> list[tuple[int, int, str]]:
    manager = pyslang.SourceManager()
    buffer = manager.readSource(path)
    allocator = pyslang.BumpAllocator()
    diagnostics = pyslang.Diagnostics()
    lexer = pyslang.parsing.Lexer(buffer, allocator, diagnostics, manager)
    tokens: list[tuple[int, int, str]] = []
    previous_end = -1
    while True:
        token = lexer.lex()
        if token.kind == pyslang.parsing.TokenKind.Identifier and token.rawText in replacements:
            start = int(token.location.offset)
            end = start + len(token.rawText.encode("utf-8"))
            token_bytes = token.rawText.encode("utf-8")
            if start < 0 or end > len(source) or source[start:end] != token_bytes:
                _fail("FORMAL_VNEXT_INPUT_INVALID", "gate identifier bytes do not match lexer")
            if start < previous_end:
                _fail("FORMAL_VNEXT_INPUT_INVALID", "lexer identifier ranges overlap")
            tokens.append((start, end, token.rawText))
            previous_end = end
        if token.kind == pyslang.parsing.TokenKind.EndOfFile:
            break
    if any(diagnostic.isError() for diagnostic in diagnostics):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "gate lexer reported errors")
    return tokens


def _lexer_replacements(path: Path, source: bytes, replacements: dict[str, str]) -> list[tuple[int, int, bytes]]:
    return [
        (start, end, replacements[raw_text].encode("utf-8"))
        for start, end, raw_text in _lexer_identifier_tokens(path, source, replacements)
    ]


def _audited_rename_dictionary(records: tuple[object, ...]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for record in records:
        if getattr(record, "action", None) != "rename":
            continue
        original = getattr(record, "original_name", None)
        renamed = getattr(record, "renamed_name", None)
        if not isinstance(original, str) or not original or not isinstance(renamed, str) or not renamed:
            _fail("FORMAL_VNEXT_INPUT_INVALID", "audited effective rename is invalid")
        previous = replacements.get(renamed)
        if previous is not None and previous != original:
            _fail("FORMAL_VNEXT_INPUT_INVALID", "audited renamed identifier is ambiguous")
        replacements[renamed] = original
    return replacements


def _effective_gate_ranges(records: tuple[object, ...]) -> list[tuple[str, int, int, bytes, bytes]]:
    source_ranges: list[tuple[str, int, int, bytes, bytes]] = []
    for record in records:
        if getattr(record, "action", None) != "rename":
            continue
        original = getattr(record, "original_name", "").encode("utf-8")
        renamed_value = getattr(record, "renamed_name", None)
        if not original or not isinstance(renamed_value, str) or not renamed_value:
            _fail("FORMAL_VNEXT_INPUT_INVALID", "audited effective rename is invalid")
        renamed = renamed_value.encode("utf-8")
        ranges = (getattr(record, "declaration"), *(item.source_range for item in getattr(record, "occurrences")))
        for source_range in ranges:
            if source_range.end - source_range.start != len(original):
                _fail("FORMAL_VNEXT_INPUT_INVALID", "audited effective range length is invalid")
            source_ranges.append((source_range.file, source_range.start, source_range.end, original, renamed))
    result: list[tuple[str, int, int, bytes, bytes]] = []
    for file, start, end, original, renamed in source_ranges:
        delta = sum(
            len(previous_renamed) - len(previous_original)
            for previous_file, previous_start, _previous_end, previous_original, previous_renamed in source_ranges
            if previous_file == file and previous_start < start
        )
        result.append((file, start + delta, start + delta + len(renamed), original, renamed))
    return result


def align_formal_view_vnext(*, gate_dir: Path, gate_view_dir: Path, gate_view_manifest_path: Path, orchestration_report_path: Path, output_dir: Path, manifest_path: Path) -> dict[str, Any]:
    """Reverse only audited effective mapping identifiers in an actual gate view."""
    gate = Path(gate_dir).expanduser().resolve()
    gate_view = Path(gate_view_dir).expanduser().resolve()
    view_manifest_path = Path(gate_view_manifest_path).expanduser().resolve()
    report_path = Path(orchestration_report_path).expanduser().resolve()
    try:
        audit = audit_orchestration_gate_vnext(report_path, gate_dir=gate)
    except RestoreVNextError as error:
        _fail("FORMAL_VNEXT_INPUT_INVALID", f"orchestration gate audit failed: {error.code}")
    if not gate.is_dir() or not gate_view.is_dir() or not view_manifest_path.is_file() or not report_path.is_file():
        _fail("FORMAL_VNEXT_INPUT_INVALID", "alignment input is missing")
    output, manifest = _validate_targets(
        Path(output_dir),
        Path(manifest_path),
        protected=(gate, gate_view, view_manifest_path, report_path),
    )
    source_set = audit.source_set
    physical = _physical_files(source_set)
    records = audit.effective_records
    replacements = _audited_rename_dictionary(records)
    expected_ranges: dict[tuple[str, int, int], bytes] = {}
    expected_by_file: dict[str, list[tuple[int, int]]] = {relative: [] for relative in physical}
    for file, start, end, _original, renamed in _effective_gate_ranges(records):
        if file not in expected_by_file:
            _fail("FORMAL_VNEXT_INPUT_INVALID", "audited mapping file is not physical")
        key = (file, start, end)
        if key in expected_ranges:
            _fail("FORMAL_VNEXT_INPUT_INVALID", "audited gate identifier ranges duplicate")
        expected_ranges[key] = renamed
        expected_by_file[file].append((start, end))
    for ranges in expected_by_file.values():
        previous_end = -1
        for start, end in sorted(ranges):
            if start < previous_end:
                _fail("FORMAL_VNEXT_INPUT_INVALID", "audited gate identifier ranges overlap")
            previous_end = end
    actual_ranges: dict[tuple[str, int, int], bytes] = {}
    for relative in physical:
        source = (gate / relative).read_bytes()
        for start, end, raw_text in _lexer_identifier_tokens(gate / relative, source, replacements):
            key = (relative, start, end)
            if key in actual_ranges:
                _fail("FORMAL_VNEXT_INPUT_INVALID", "gate identifier ranges duplicate")
            actual_ranges[key] = raw_text.encode("utf-8")
    if set(actual_ranges) != set(expected_ranges):
        _fail(
            "FORMAL_VNEXT_INPUT_INVALID",
            f"gate identifier token ranges differ: missing={len(set(expected_ranges) - set(actual_ranges))}, extra={len(set(actual_ranges) - set(expected_ranges))}",
        )
    if any(actual_ranges[key] != expected_ranges[key] for key in expected_ranges):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "gate identifier token bytes differ from audited ranges")
    try:
        view_report = json.loads(view_manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _fail("FORMAL_VNEXT_INPUT_INVALID", str(error))
    expected_view_keys = {
        "format", "schema_version", "state", "source_set", "source_manifest_sha256",
        "view_manifest_sha256", "design_file", "transformations",
    }
    expected_view_source_set = {
        "origin": source_set.origin,
        "top": source_set.top,
        "compile_order": list(source_set.compile_order),
        "physical_files": list(physical),
        "include_dirs": list(source_set.include_dirs),
        "defines": [{"name": name, "value": value} for name, value in source_set.defines],
    }
    if (
        not isinstance(view_report, dict)
        or set(view_report) != expected_view_keys
        or view_report.get("format") != "rtl-obfuscation.formal-view-vnext"
        or view_report.get("schema_version") != 1
        or view_report.get("state") != "verified"
        or view_report.get("source_set") != expected_view_source_set
    ):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "formal view manifest is invalid")
    if view_report.get("source_manifest_sha256") != _manifest(gate, physical):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "formal view source manifest does not match gate")
    design = gate_view / "design.f"
    if view_report.get("design_file") != "design.f" or not design.is_file() or design.read_bytes() != "".join(f"{relative}\n" for relative in source_set.compile_order).encode("utf-8"):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "formal view design file does not match report")
    transformations = view_report.get("transformations")
    if not isinstance(transformations, list):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "formal transformations are missing")
    actual_files = {path.relative_to(gate_view).as_posix() for path in gate_view.rglob("*") if path.is_file()}
    if actual_files != {*physical, "design.f"}:
        _fail("FORMAL_VNEXT_INPUT_INVALID", "formal view file set is invalid")
    gate_view_manifest = _manifest(gate_view, physical)
    if gate_view_manifest != view_report.get("view_manifest_sha256"):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "formal view manifest hash mismatch")
    # Recompute generic gate-side transformations only after the shared gate audit.
    gate_sources, gate_edits, _context, gate_source_manifest = _compute(source_set)
    expected_transformations = [edit.record for edit in gate_edits]
    if transformations != expected_transformations or gate_source_manifest != view_report.get("source_manifest_sha256"):
        _fail("FORMAL_VNEXT_INPUT_INVALID", "formal transformation chain mismatch")
    for relative in physical:
        expected = _apply(gate_sources[relative], [edit for edit in gate_edits if edit.record["file"] == relative])
        if (gate_view / relative).read_bytes() != expected:
            _fail("FORMAL_VNEXT_INPUT_INVALID", "formal view bytes do not match gate")
    identifier_edits: dict[str, list[tuple[int, int, bytes]]] = {relative: [] for relative in physical}
    count = 0
    for file in physical:
        view_bytes = (gate_view / file).read_bytes()
        identifier_edits[file] = _lexer_replacements(gate_view / file, view_bytes, replacements)
        count += len(identifier_edits[file])
    temporary = Path(tempfile.mkdtemp(prefix=".formal-align-vnext-", dir=str(output.parent)))
    try:
        aligned = temporary / "aligned"
        for relative in physical:
            source = (gate_view / relative).read_bytes()
            for start, end, replacement in sorted(identifier_edits[relative], key=lambda item: item[0], reverse=True):
                source = source[:start] + replacement + source[end:]
            target = aligned / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source)
        (aligned / "design.f").write_bytes(design.read_bytes())
        aligned_manifest = _manifest(aligned, physical)
        result = {
            "format": "rtl-obfuscation.formal-alignment-vnext",
            "schema_version": 1,
            "state": "verified",
            "top": source_set.top,
            "source_gate_manifest_sha256": _manifest(gate, physical),
            "source_view_manifest_sha256": gate_view_manifest,
            "mapping_records": len(records),
            "renamed_records": sum(record.action == "rename" for record in records),
            "identifier_replacements": count,
            "aligned_view_manifest_sha256": aligned_manifest,
            "design_file": "design.f",
        }
        _validate_yosys(aligned, source_set)
        staged_manifest = temporary / "manifest.json"
        _write_json(staged_manifest, result)
        _publish(aligned, staged_manifest, output, manifest)
    except FormalVNextError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        _fail("FORMAL_VNEXT_IO_ERROR", str(error))
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {"files": len(physical), "top": source_set.top, "identifier_replacements": count, "aligned_view_manifest_sha256": aligned_manifest}
