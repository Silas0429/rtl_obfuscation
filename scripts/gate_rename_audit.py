#!/usr/bin/env python3
"""Audit a published gate for references that should have been renamed.

A rename is only correct when the declaration and every reference change
together.  The encryption flow already proves that every edit it *planned* was
applied, that the gate compiles under PySlang, and that decrypt reproduces the
original byte for byte.  None of those catch a reference the tool never
identified:

* ``metrics_vnext._validate_gate_edits`` iterates ``execution.edits`` only, so
  it cannot see a token it was never told about;
* ``restored_byte_identical`` holds anyway, because a missed spot carries the
  old name in both the original and the gate;
* strict compilation stays silent, because SystemVerilog's default
  ``default_nettype`` turns an undeclared identifier into an implicit wire.

The last point was measured: renaming a port to ``a_new`` while the parent still
writes ``.a_new(old_signal_name)`` produces zero diagnostics and one
``NetSymbol(isImplicit=True)``.  That symbol is the detector this auditor uses.

The auditor is read-only.  It never rewrites RTL, never produces a gate, and
never creates a directory; the only file it may write is the ``--json`` report.
"""

from __future__ import annotations

import argparse
import bisect
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pyslang  # noqa: E402

from rtl_obfuscator.project_discovery import compile_pyslang_source_set  # noqa: E402


FORMAT = "rtl-obfuscation.gate-rename-audit"
SCHEMA_VERSION = 1

_UNIT_KINDS = {
    "ModuleDeclaration",
    "InterfaceDeclaration",
    "PackageDeclaration",
    "ProgramDeclaration",
}


def _fail(code: str, message: str) -> None:
    print(json.dumps({"error": code, "message": message}, ensure_ascii=False))
    raise SystemExit(2)


def _safe_attr(value: object, name: str, default: object = None) -> Any:
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _kind_name(value: object) -> str:
    return str(value).rsplit(".", 1)[-1]


def _semantic_name(raw: str) -> str:
    """Return the name a token spells; an escaped identifier drops its slash."""

    if raw.startswith("\\"):
        return raw[1:].rstrip()
    return raw


class _View:
    """One compiled SourceSet plus the lookups the audit needs from it."""

    def __init__(self, label: str, root: Path, source_set: dict[str, Any]) -> None:
        self.label = label
        self.root = root.resolve()
        try:
            view = compile_pyslang_source_set(
                root=self.root,
                compilation_files=tuple(source_set["compile_order"]),
                include_files=tuple(source_set.get("included_files", ())),
                include_dirs=tuple(source_set.get("include_dirs", ())),
                defines=dict(source_set.get("defines", ()) or ()),
                top=None,
            )
        except (OSError, RuntimeError, ValueError) as error:
            _fail("AUDIT_COMPILE_FAILED", f"{label}: {error}")
        self.parse_errors = len(view.parse_errors)
        self.semantic_errors = len(view.semantic_errors)
        self._manager = view.source_manager
        self._tree = view.syntax_tree
        self._root_symbol = view.root
        self._file_cache: dict[Any, str | None] = {}

    def file_of(self, buffer: Any) -> str | None:
        try:
            cached = self._file_cache[buffer]
        except (KeyError, TypeError):
            cached = "__miss__"
        if cached != "__miss__":
            return cached
        value: str | None
        try:
            absolute = Path(self._manager.getFullPath(buffer)).resolve()
            value = absolute.relative_to(self.root).as_posix()
        except (OSError, RuntimeError, TypeError, ValueError):
            value = None
        try:
            self._file_cache[buffer] = value
        except TypeError:
            pass
        return value

    def physical(self, location: Any) -> Any:
        try:
            if self._manager.isMacroLoc(location):
                return self._manager.getFullyOriginalLoc(location)
        except Exception:
            return location
        return location

    def implicit_nets(self) -> set[tuple[str, int, str]]:
        """Return (file, offset, name) of every implicitly created net.

        An implicit net is how SystemVerilog absorbs an undeclared identifier,
        so it is exactly the footprint a missed reference leaves behind.

        The physical offset is reported alongside the name because the gold
        side has to be translated into the spelling the gate should hold, and
        that translation is only decidable by position -- see
        ``_renamed_name_at``.  An offset of ``-1`` marks a net whose location
        could not be resolved to a file; it can never match a renamed range and
        so falls back to its old name, visibly.
        """

        result: set[tuple[str, int, str]] = set()
        nodes: list[Any] = []
        self._root_symbol.visit(nodes.append)
        for node in nodes:
            if type(node).__name__ != "NetSymbol":
                continue
            if not _safe_attr(node, "isImplicit", False):
                continue
            name = str(_safe_attr(node, "name", "") or "")
            if not name:
                continue
            file, offset = None, -1
            try:
                location = self.physical(_safe_attr(node, "location"))
                file = self.file_of(_safe_attr(location, "buffer"))
                if file is not None:
                    offset = int(location.offset)
            except Exception:
                file, offset = None, -1
            result.add((file or "$unknown", offset, name))
        return result

    def identifier_tokens(self) -> list[tuple[str, int, str]]:
        """Return every physical identifier token as (file, offset, text).

        Byte-verified against the source, so a token that cannot be proven to
        exist at the reported offset is dropped rather than reported.
        """

        seen: set[tuple[str, int, int]] = set()
        result: list[tuple[str, int, str]] = []
        data_cache: dict[str, bytes] = {}
        nodes: list[Any] = []
        self._tree.root.visit(nodes.append)
        for node in nodes:
            if type(node).__name__ != "Token":
                continue
            if node.kind != pyslang.parsing.TokenKind.Identifier:
                continue
            raw = str(node.rawText)
            if not raw:
                continue
            location = self.physical(node.location)
            file = self.file_of(_safe_attr(location, "buffer"))
            if file is None:
                continue
            start = int(location.offset)
            encoded = raw.encode("utf-8")
            end = start + len(encoded)
            data = data_cache.get(file)
            if data is None:
                try:
                    data = (self.root / file).read_bytes()
                except OSError:
                    continue
                data_cache[file] = data
            if not 0 <= start < end <= len(data) or data[start:end] != encoded:
                continue
            key = (file, start, end)
            if key in seen:
                continue
            seen.add(key)
            result.append((file, start, _semantic_name(raw)))
        return result

    def unit_spans(self) -> dict[str, list[tuple[int, int, str]]]:
        """Return per-file (start, end, unit name) spans of every design unit."""

        spans: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        nodes: list[Any] = []
        self._tree.root.visit(nodes.append)
        for node in nodes:
            if type(node).__name__ == "Token":
                continue
            if _kind_name(_safe_attr(node, "kind")) not in _UNIT_KINDS:
                continue
            try:
                source_range = _safe_attr(node, "sourceRange")
                start_loc = self.physical(source_range.start)
                end_loc = self.physical(source_range.end)
            except Exception:
                continue
            file = self.file_of(_safe_attr(start_loc, "buffer"))
            if file is None or file != self.file_of(_safe_attr(end_loc, "buffer")):
                continue
            try:
                start, end = int(start_loc.offset), int(end_loc.offset)
            except Exception:
                continue
            if end <= start:
                continue
            token = _safe_attr(_safe_attr(node, "header"), "name")
            name = str(_safe_attr(token, "rawText", "") or "") or "$anonymous"
            spans[file].append((start, end, name))
        for items in spans.values():
            items.sort()
        return dict(spans)

    def declared_names(self) -> set[tuple[str, str]]:
        """Return (file, name) for every explicitly declared named symbol.

        Used to tell a legitimate same-spelling declaration apart from a
        leftover reference to a symbol that was renamed.
        """

        result: set[tuple[str, str]] = set()
        nodes: list[Any] = []
        self._root_symbol.visit(nodes.append)
        for node in nodes:
            if type(node).__name__ == "NetSymbol" and _safe_attr(
                node, "isImplicit", False
            ):
                continue
            name = str(_safe_attr(node, "name", "") or "")
            location = _safe_attr(node, "location")
            if not name or location is None:
                continue
            try:
                physical = self.physical(location)
                file = self.file_of(_safe_attr(physical, "buffer"))
            except Exception:
                continue
            if file is not None:
                result.add((file, name))
        return result


def _unit_at(
    spans: dict[str, list[tuple[int, int, str]]], file: str, offset: int
) -> str | None:
    """Return the name of the innermost design unit containing an offset."""

    items = spans.get(file)
    if not items:
        return None
    best: tuple[int, str] | None = None
    index = bisect.bisect_right([item[0] for item in items], offset)
    for start, end, name in items[:index]:
        if offset < end and (best is None or (end - start) < best[0]):
            best = (end - start, name)
    return None if best is None else best[1]


def _load_mapping(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _fail("AUDIT_MAP_INVALID", f"cannot read mapping: {error}")
    if payload.get("format") != "rtl-obfuscation.cli-vnext" and "mapping" not in payload:
        _fail("AUDIT_MAP_INVALID", "mapping is not an rtl-obfuscation report")
    mapping = payload.get("mapping", payload)
    if int(mapping.get("schema_version", 0)) != 2:
        _fail(
            "AUDIT_MAP_VERSION_UNSUPPORTED",
            "only mapping schema_version 2 is supported",
        )
    source_set = mapping.get("source_set") or payload.get("source_set")
    if not source_set or "compile_order" not in source_set:
        _fail("AUDIT_MAP_INVALID", "mapping has no SourceSet compile order")
    records = [
        record
        for record in mapping.get("records", ())
        if record.get("action") == "rename"
    ]
    return payload, source_set, records


def _renamed_name_at(records: list[dict[str, Any]]) -> dict[tuple[str, int], str]:
    """Index the new name of every renamed range by its exact gold position.

    Check 1 has to translate each gold implicit net into the spelling the gate
    should hold for it.  Translating by name is wrong: a real design holds
    several distinct symbols spelling the same identifier and each is renamed
    independently, so a global ``old name -> new name`` dictionary silently keeps
    only one of them.  The gold net then translates to a spelling the gate does
    not hold, and a correct gate is reported ``suspect``.

    Measured on ``rtl_samples/RISC-V-Vector`` (project root, top ``vector_top``):
    169 old names are renamed to more than one new name, ``i`` to 27 of them.
    T113 measured 206 on the same sample before its own fix landed, when ``clk``
    reached 15 and ``valid`` 5; both of those spellings are now preserved
    outright as ``unelaborated_reference``, so they no longer collide.  The
    mechanism is unchanged -- only which spellings take part in it moved.

    Position is decidable where the name is not -- the same reason
    ``_renamed_range_bytes`` verifies by position.  An implicit net has no
    declaration of its own, so the mapping stores its first occurrence as the
    record's ``declaration`` range; measured, the gold ``NetSymbol.location``
    offset equals that range's start.  Both the declaration range and every
    occurrence range are therefore indexed.
    """

    index: dict[tuple[str, int], str] = {}
    for record in records:
        renamed = str(record.get("renamed_name") or "")
        if not renamed:
            continue
        ranges: list[Any] = [record.get("declaration")]
        ranges += [
            item.get("source_range")
            for item in record.get("occurrences", ()) or ()
            if isinstance(item, dict)
        ]
        for item in ranges:
            if not isinstance(item, dict):
                continue
            file, start = item.get("file"), item.get("start")
            if file is None or start is None:
                continue
            try:
                index[(str(file), int(start))] = renamed
            except (TypeError, ValueError):
                continue
    return index


def _renamed_range_bytes(
    payload: dict[str, Any], gate_dir: Path, limit: int
) -> dict[str, Any]:
    """Verify each renamed range independently from the published gate files.

    ``per_file_mapping`` persists both ``source_range`` and ``gate_range`` for
    every edit, so the gate bytes can be checked by exact position rather than
    by name.  Position beats name here: a design routinely holds several
    distinct symbols spelling the same identifier, and a name-based scan cannot
    tell a missed rename apart from a different symbol that legitimately keeps
    that spelling.

    This is not a duplicate of ``metrics_vnext._validate_gate_edits``.  That
    check runs inside the encryption process against its in-memory edit list;
    this one recomputes from the published gate and the persisted mapping, so it
    also catches a gate mutated after publication or a mapping that disagrees
    with the gate.
    """

    checked = 0
    leaked: list[dict[str, Any]] = []
    misplaced: list[dict[str, Any]] = []
    data_cache: dict[str, bytes] = {}

    for entry in payload.get("mapping_execution", {}).get("per_file_mapping", ()):
        for record in entry.get("records", ()):
            if record.get("action") != "rename":
                continue
            original = str(record.get("original_name") or "")
            renamed = str(record.get("renamed_name") or "")
            if not original or not renamed:
                continue
            for item in record.get("ranges", ()):
                gate_range = item.get("gate_range") or {}
                file = gate_range.get("file")
                start, end = gate_range.get("start"), gate_range.get("end")
                if file is None or start is None or end is None:
                    misplaced.append(
                        {
                            "original_name": original,
                            "provenance": item.get("provenance"),
                            "reason": "gate_range_missing",
                        }
                    )
                    continue
                data = data_cache.get(file)
                if data is None:
                    try:
                        data = (gate_dir / file).read_bytes()
                    except OSError as error:
                        _fail(
                            "AUDIT_GATE_FILE_INVALID",
                            f"cannot read gate file {file}: {error}",
                        )
                    data_cache[file] = data
                checked += 1
                if not 0 <= start < end <= len(data):
                    misplaced.append(
                        {
                            "original_name": original,
                            "file": file,
                            "start": start,
                            "provenance": item.get("provenance"),
                            "reason": "gate_range_out_of_bounds",
                        }
                    )
                    continue
                actual = data[start:end].decode("utf-8", "replace")
                if actual == renamed:
                    continue
                finding = {
                    "original_name": original,
                    "renamed_name": renamed,
                    "category": record.get("category"),
                    "owner_module": record.get("owner_module"),
                    "provenance": item.get("provenance"),
                    "file": file,
                    "start": start,
                    "gate_bytes": actual,
                }
                if actual == original:
                    leaked.append(finding)
                else:
                    misplaced.append({**finding, "reason": "gate_range_mismatch"})

    return {
        "checked": checked,
        "leaked_old_name": len(leaked),
        "misplaced": len(misplaced),
        "mismatched": len(leaked) + len(misplaced),
        "leaked_detail": leaked[:limit],
        "misplaced_detail": misplaced[:limit],
    }


def _resolve_gold_root(args: argparse.Namespace, source_set: dict[str, Any]) -> Path:
    """Recover the original source root that ``compile_order`` is relative to.

    The mapping deliberately stores only relative paths so a report stays
    portable, which means the root is not in the file.  A filelist commonly
    sits deep inside the tree it describes -- StCache's is at
    ``<root>/aic_ss/src/stcache/StCache.f`` while its entries are relative to
    ``<root>`` -- so the filelist's own directory is usually the wrong answer.
    Walk up from it and take the first ancestor where the recorded compile
    order actually resolves.
    """

    if args.gold_root:
        return Path(args.gold_root).expanduser().resolve()

    order = list(source_set.get("compile_order") or ())
    if not order:
        _fail("AUDIT_MAP_INVALID", "mapping has no SourceSet compile order")
    if not args.gold_filelist:
        _fail(
            "AUDIT_GOLD_ROOT_INVALID",
            "pass --gold-root, or --gold-filelist so the root can be derived",
        )

    start = Path(args.gold_filelist).expanduser().resolve().parent
    tried: list[str] = []
    for candidate in (start, *start.parents):
        tried.append(str(candidate))
        if all((candidate / relative).is_file() for relative in order):
            return candidate
    _fail(
        "AUDIT_GOLD_ROOT_INVALID",
        "cannot locate a source root where the recorded compile order resolves; "
        f"pass --gold-root explicitly. Tried: {', '.join(tried[:6])}",
    )
    raise AssertionError("unreachable")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    map_path = Path(args.map).expanduser().resolve()
    gate_dir = Path(args.gate_dir).expanduser().resolve()
    payload, source_set, renamed = _load_mapping(map_path)

    gold_root = _resolve_gold_root(args, source_set)
    if not gold_root.is_dir():
        _fail("AUDIT_GOLD_ROOT_INVALID", f"gold root is not a directory: {gold_root}")
    if not gate_dir.is_dir():
        _fail("AUDIT_GATE_DIR_INVALID", f"gate dir is not a directory: {gate_dir}")

    gold = _View("gold", gold_root, source_set)
    gate = _View("gate", gate_dir, source_set)
    for view in (gold, gate):
        if view.parse_errors or view.semantic_errors:
            _fail(
                "AUDIT_COMPILE_FAILED",
                f"{view.label} has {view.parse_errors} parse and "
                f"{view.semantic_errors} semantic errors; auditing a design that "
                "does not compile is meaningless",
            )

    # Check 1: implicit nets the rewrite introduced.  Differenced against gold,
    # because the original design may legitimately rely on implicit nets.
    #
    # Each gold name must first be translated into the spelling the gate should
    # hold: an implicit net has no declaration but its occurrences are still
    # renamed, so the same net reappears in the gate under the new spelling.
    # Comparing raw names would report every renamed implicit net as newly
    # introduced.
    #
    # The translation is decided by the net's physical position, not by its
    # name -- see ``_renamed_name_at`` for the measurement that forced this.
    # The rule is stated by its result, not by the one cause that exposed it:
    # look the position up, and fall back to the unchanged old name when the
    # lookup misses.  Every fallback is counted in the report, because that is
    # the only way this check can go blind.
    renamed_at = _renamed_name_at(renamed)
    gold_implicit = gold.implicit_nets()
    gate_implicit = gate.implicit_nets()

    expected_gate: set[tuple[str, str]] = set()
    fallback: list[dict[str, Any]] = []
    for file, offset, name in sorted(gold_implicit):
        translated = renamed_at.get((file, offset))
        if translated is None:
            fallback.append({"name": name, "file": file, "start": offset})
            translated = name
        expected_gate.add((file, translated))

    gold_names = {(file, name) for file, _, name in gold_implicit}
    gate_names = {(file, name) for file, _, name in gate_implicit}
    gate_only = sorted(gate_names - expected_gate)
    gate_spans = gate.unit_spans()

    # Check 2: an old name still spelled inside its owner unit in the gate.
    by_old_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in renamed:
        original = str(record.get("original_name") or "")
        if original:
            by_old_name[original].append(record)
    gate_declared = gate.declared_names()

    residual: list[dict[str, Any]] = []
    for file, offset, text in gate.identifier_tokens():
        candidates = by_old_name.get(text)
        if not candidates:
            continue
        unit = _unit_at(gate_spans, file, offset)
        for record in candidates:
            declaration = record.get("declaration") or {}
            if declaration.get("file") != file:
                continue
            residual.append(
                {
                    "original_name": text,
                    "renamed_name": record.get("renamed_name"),
                    "category": record.get("category"),
                    "owner_module": record.get("owner_module"),
                    "file": file,
                    "start": offset,
                    "unit": unit,
                    "shadowed_by_other_declaration": (file, text) in gate_declared,
                }
            )
            break

    range_bytes = _renamed_range_bytes(payload, gate_dir, args.examples)

    verdict = (
        "clean"
        if not gate_only and range_bytes["mismatched"] == 0
        else "suspect"
    )
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "input": {
            "map": str(map_path),
            "gate_dir": str(gate_dir),
            "gold_root": str(gold_root.resolve()),
            "source_units": len(source_set["compile_order"]),
            "included_files": len(source_set.get("included_files", ())),
        },
        "compile": {
            "gold": {
                "parse_errors": gold.parse_errors,
                "semantic_errors": gold.semantic_errors,
            },
            "gate": {
                "parse_errors": gate.parse_errors,
                "semantic_errors": gate.semantic_errors,
            },
        },
        "renamed_records": {
            "records": len(renamed),
            "distinct_old_names": len(by_old_name),
        },
        "implicit_nets": {
            "gold": len(gold_names),
            "gate": len(gate_names),
            "gate_only": len(gate_only),
            "gate_only_detail": [
                {"name": name, "file": file}
                for file, name in gate_only[: args.examples]
            ],
            "gold_fallback_to_old_name": len(fallback),
            "gold_fallback_note": (
                "report only, not part of the verdict: a gold implicit net whose "
                "physical position matches no renamed range is expected in the "
                "gate under its unchanged old name. That is correct when the net "
                "was never renamed, and it is the one way this check can go "
                "blind, so the count is published instead of swallowed"
            ),
            "gold_fallback_detail": fallback[: args.examples],
        },
        "renamed_range_bytes": range_bytes,
        "residual_old_names": {
            "count": len(residual),
            "note": (
                "report only, not part of the verdict: a design may legitimately "
                "hold another symbol spelling the same name, so a hit here needs "
                "human judgement"
            ),
            "detail": residual[: args.examples],
        },
        "verdict": verdict,
    }


def _print_summary(report: dict[str, Any]) -> None:
    implicit = report["implicit_nets"]
    ranges = report["renamed_range_bytes"]
    residual = report["residual_old_names"]
    lines = [
        "gate rename audit",
        f"  gate       : {report['input']['gate_dir']}",
        f"  gold       : {report['input']['gold_root']}",
        f"  source units: {report['input']['source_units']}"
        f"  renamed records: {report['renamed_records']['records']}"
        f" ({report['renamed_records']['distinct_old_names']} distinct old names)",
        "",
        "  [gate] implicit nets -- a missed reference becomes one",
        f"    gold {implicit['gold']}   gate {implicit['gate']}"
        f"   gate-only {implicit['gate_only']}",
        "    gold nets expected under their old name because no renamed range"
        f" covers their position: {implicit['gold_fallback_to_old_name']}",
    ]
    for item in implicit["gate_only_detail"]:
        lines.append(f"      !! {item['name']}  {item['file']}")
    lines += [
        "",
        "  [gate] renamed range bytes -- recomputed from the published gate",
        f"    checked {ranges['checked']}   leaked old name {ranges['leaked_old_name']}"
        f"   misplaced {ranges['misplaced']}",
    ]
    for item in ranges["leaked_detail"]:
        lines.append(
            f"      !! {item['original_name']} still at {item['file']}:{item['start']}"
            f"  ({item['provenance']})"
        )
    for item in ranges["misplaced_detail"]:
        lines.append(
            f"      !! {item.get('original_name')} {item.get('reason')}"
            f"  {item.get('file')}:{item.get('start')}"
        )
    lines += [
        "",
        f"  [report only] old names still spelled in their file: {residual['count']}",
    ]
    for item in residual["detail"][:5]:
        lines.append(
            f"      -- {item['original_name']} {item['file']}:{item['start']}"
            f"  shadowed={item['shadowed_by_other_declaration']}"
        )
    lines += ["", f"  VERDICT: {report['verdict']}"]
    print("\n".join(lines), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only audit of a published gate for missed renames",
    )
    parser.add_argument("--map", required=True, help="<gate>/mapping.json")
    parser.add_argument("--gate-dir", required=True, help="published gate directory")
    parser.add_argument("--gold-filelist", help="original filelist, used for its root")
    parser.add_argument("--gold-root", help="explicit original source root")
    parser.add_argument(
        "--include-dir", dest="include_dirs", action="append", default=[]
    )
    parser.add_argument("--define", dest="defines", action="append", default=[])
    parser.add_argument("--json", help="also write the report to this path")
    parser.add_argument("--examples", type=int, default=20)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args)
    if not args.quiet:
        _print_summary(report)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)
    if args.json:
        Path(args.json).expanduser().write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["verdict"] == "clean" else 1


if __name__ == "__main__":
    raise SystemExit(main())
