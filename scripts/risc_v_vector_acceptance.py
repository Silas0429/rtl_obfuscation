"""T057-only release driver for the RISC-V-Vector vNext path."""

from __future__ import annotations

import hashlib
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rtl_obfuscator.formal_vnext import (
    align_formal_view_vnext,
    build_formal_view_vnext,
)
from rtl_obfuscator.source_set import SourceSet, from_project_root

RISC_ROOT = ROOT / "rtl_samples" / "RISC-V-Vector"
TOP = "vector_top"
SEQ = "1"
COMPILE_ORDER = (
    "rtl/shared/and_or_mux.sv",
    "rtl/shared/eb_one_slot.sv",
    "rtl/shared/eb_buff_generic.sv",
    "rtl/shared/fifo_duth.sv",
    "rtl/vector/v_fp_alu.sv",
    "rtl/vector/vmacros.sv",
    "rtl/vector/v_int_alu.sv",
    "rtl/vector/vex_pipe.sv",
    "rtl/vector/vrat.sv",
    "rtl/vector/vrf.sv",
    "rtl/vector/vstructs.sv",
    "rtl/vector/vex.sv",
    "rtl/vector/vis.sv",
    "rtl/vector/vmu_ld_eng.sv",
    "rtl/vector/vmu_st_eng.sv",
    "rtl/vector/vmu_tp_eng.sv",
    "rtl/vector/vmu.sv",
    "rtl/vector/vrrm.sv",
    "rtl/vector/vector_top.sv",
)
CATEGORIES = (
    "signals", "parameters", "enum_values", "genvars", "functions", "tasks",
    "arguments", "instances", "generate_blocks", "typedefs", "struct_types",
    "struct_fields", "union_fields", "modules", "ports", "interfaces",
    "interface_instances", "interface_ports", "modports",
)
ABI_CATEGORIES = (
    "parameters", "typedefs", "struct_types", "struct_fields", "union_fields",
    "modules", "ports", "interfaces", "interface_instances", "interface_ports",
    "modports",
)
INPUT_MANIFEST = "a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d"
SOURCE_SET_DIGEST = "b359a1340ba461ce941ab68c6dcd34f33b365935e239af4e606710204f477fc7"
MAPPING_RANGE_DIGEST = "217cce2e28c5c81280653fd233ba87d2a70a4a284417a3492182da2520da46fd"
FORMAL_SIGNATURE_DIGEST = "63a9ef753fdb55f735359b4e65ec8e5c6d61a9b0626ceec21486d9786ac0a925"
ALIGNED_VIEW_MANIFEST = "7c93970509f6844c6fb7902de6ded6878e8fae6753578a5b862e6fc3c18deae9"
FORMAL_TRANSFORMATIONS = 260
FORMAL_KIND_COUNTS = {
    "lower_packed_aggregate_type": 25,
    "lower_packed_struct_member": 233,
    "remove_concurrent_assertion": 2,
}
PER_CATEGORY_COUNTS = {
    "arguments": {"rename": 0, "preserve": 0, "unsupported": 0},
    "enum_values": {"rename": 33, "preserve": 0, "unsupported": 0},
    "functions": {"rename": 0, "preserve": 0, "unsupported": 0},
    "generate_blocks": {"rename": 8, "preserve": 0, "unsupported": 0},
    "genvars": {"rename": 7, "preserve": 0, "unsupported": 0},
    "instances": {"rename": 19, "preserve": 0, "unsupported": 0},
    "interface_instances": {"rename": 0, "preserve": 0, "unsupported": 0},
    "interface_ports": {"rename": 0, "preserve": 0, "unsupported": 0},
    "interfaces": {"rename": 0, "preserve": 0, "unsupported": 0},
    "modports": {"rename": 0, "preserve": 0, "unsupported": 0},
    "modules": {"rename": 16, "preserve": 1, "unsupported": 0},
    "parameters": {"rename": 120, "preserve": 14, "unsupported": 0},
    "ports": {"rename": 348, "preserve": 11, "unsupported": 0},
    "signals": {"rename": 675, "preserve": 0, "unsupported": 0},
    "struct_fields": {"rename": 66, "preserve": 0, "unsupported": 0},
    "struct_types": {"rename": 7, "preserve": 0, "unsupported": 0},
    "tasks": {"rename": 0, "preserve": 0, "unsupported": 0},
    "typedefs": {"rename": 2, "preserve": 0, "unsupported": 0},
    "union_fields": {"rename": 0, "preserve": 0, "unsupported": 0},
}


class AcceptanceError(RuntimeError):
    pass


def canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def manifest(root: Path, files: Iterable[str]) -> str:
    payload = b"".join(
        hashlib.sha256((root / relative).read_bytes()).hexdigest().encode("ascii")
        + b"  " + relative.encode("utf-8") + b"\n"
        for relative in sorted(files)
    )
    return hashlib.sha256(payload).hexdigest()


def normalized_source_set(report: dict[str, Any]) -> dict[str, Any]:
    source = report.get("source_set")
    if not isinstance(source, dict):
        raise AcceptanceError("source_set report is missing")
    return {
        key: source[key]
        for key in (
            "schema_version", "origin", "ordered_source_files", "included_files",
            "include_dirs", "defines", "top", "top_closure_files", "compile_order",
        )
    }


def normalized_mapping_ranges(report: dict[str, Any]) -> list[dict[str, Any]]:
    records = report.get("mapping", {}).get("records")
    if not isinstance(records, list):
        raise AcceptanceError("mapping records are missing")
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise AcceptanceError("mapping record is invalid")
        occurrences = record.get("occurrences")
        if not isinstance(occurrences, list):
            raise AcceptanceError("mapping occurrences are invalid")
        normalized.append({
            "symbol_id": record.get("symbol_id"),
            "category": record.get("category"),
            "action": record.get("action"),
            "reason": record.get("reason"),
            "original_name": record.get("original_name"),
            "owner_module": record.get("owner_module"),
            "semantic_owner": record.get("semantic_owner"),
            "declaration": record.get("declaration"),
            "occurrences": sorted(
                [
                    {
                        "source_range": item.get("source_range"),
                        "provenance": item.get("provenance"),
                    }
                    for item in occurrences
                ],
                key=lambda item: (
                    item["source_range"].get("file"),
                    item["source_range"].get("start"),
                    item["source_range"].get("end"),
                    item["provenance"],
                ),
            ),
            "impact": record.get("impact"),
            "abi": record.get("abi"),
        })
    return sorted(normalized, key=lambda item: item["symbol_id"])


def normalized_mapping_range_digest(report: dict[str, Any]) -> str:
    return canonical(normalized_mapping_ranges(report))


def mapping_counts(report: dict[str, Any]) -> dict[str, Any]:
    records = normalized_mapping_ranges(report)
    return {
        "total": len(records),
        "rename": sum(item["action"] == "rename" for item in records),
        "preserve": sum(item["action"] == "preserve" for item in records),
        "unsupported": sum(item["action"] == "unsupported" for item in records),
        "modified_tokens": report["summary"]["modified_tokens"],
        "per_category": {
            category: {
                action: sum(
                    item["category"] == category and item["action"] == action
                    for item in records
                )
                for action in ("rename", "preserve", "unsupported")
            }
            for category in CATEGORIES
        },
    }


def _formal_signature(transformations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = {"file", "start", "end", "source_sha256", "replacement_sha256"}
    return [
        {key: item[key] for key in sorted(item) if key not in excluded}
        for item in transformations
    ]


def formal_signature_digest(manifest_report: dict[str, Any]) -> str:
    transformations = manifest_report.get("transformations")
    if not isinstance(transformations, list):
        raise AcceptanceError("formal transformations are missing")
    return canonical(_formal_signature(transformations))


def _run(command: list[str], *, expect: int | None = 0) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if expect is not None and process.returncode != expect:
        raise AcceptanceError(
            f"command failed ({process.returncode}): {' '.join(command)}\n"
            f"{process.stdout}\n{process.stderr}"
        )
    return process


def _cli_categories() -> list[str]:
    return [option for category in CATEGORIES for option in ("--category", category)]


def _cli_abi_categories() -> list[str]:
    return [option for category in ABI_CATEGORIES for option in ("--abi-category", category)]


def _assert_portable(value: object) -> None:
    if isinstance(value, dict):
        if any(key in {"source_root", "gate_dir", "restore_dir", "output_dir"} for key in value):
            raise AcceptanceError("portable report contains a private path key")
        for item in value.values():
            _assert_portable(item)
    elif isinstance(value, list):
        for item in value:
            _assert_portable(item)
    elif isinstance(value, str) and (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)):
        raise AcceptanceError("portable report contains an absolute path")


def _strict_compile(root: Path) -> tuple[int, int]:
    files = [str(root / relative) for relative in COMPILE_ORDER]
    script = "read_verilog -sv -formal -defer " + " ".join(files) + f"; hierarchy -check -top {TOP}"
    process = _run(["yosys", "-Q", "-p", script], expect=None)
    return (0, 0) if process.returncode == 0 else (1, 0)


def _formal_command(gold: Path, gate: Path) -> list[str]:
    return [
        sys.executable, "scripts/formal_equivalence.py",
        "--gold-filelist", str(gold / "design.f"), "--gold-root", str(gold),
        "--gate-filelist", str(gate / "design.f"), "--gate-root", str(gate),
        "--top", TOP, "--seq", SEQ,
    ]


def _yosys_warnings(root: Path, source: dict[str, Any], replacements: dict[str, str]) -> frozenset[str]:
    files = [str(root / relative) for relative in source["compile_order"]]
    script = "read_verilog -sv -formal -defer " + " ".join(files) + f"; hierarchy -check -top {TOP}"
    process = _run(["yosys", "-Q", "-p", script])
    result: set[str] = set()
    for output in (process.stdout, process.stderr):
        for raw_line in output.splitlines():
            if "Warning:" not in raw_line and not raw_line.startswith("Warnings:"):
                continue
            line = raw_line.replace(str(root), "<root>")
            for renamed, original in sorted(replacements.items(), key=lambda item: -len(item[0])):
                line = line.replace(renamed, original)
            line = re.sub(r"\$paramod\$[0-9a-f]+", "$paramod$<hash>", line)
            result.add(line)
    return frozenset(result)


def _run_release(work: Path) -> dict[str, Any]:
    gate = work / "gate"
    mapping_path = work / "orchestration.json"
    metrics_path = work / "metrics.json"
    restored = work / "restored"
    restored_report = work / "restore-report.json"
    encrypt_command = [
        sys.executable, "-m", "rtl_obfuscator.rewrite", "encrypt-vnext",
        "--project-root", str(RISC_ROOT), "--top", TOP,
        "--output-dir", str(gate), "--map", str(mapping_path),
        "--metrics", str(metrics_path), "--name-length", "20",
        *_cli_categories(), *_cli_abi_categories(),
    ]
    _run(encrypt_command)
    report = json.loads(mapping_path.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    _assert_portable(report)
    _assert_portable(metrics)
    if report.get("format") != "rtl-obfuscation.orchestration-vnext" or report.get("state") != "restored":
        raise AcceptanceError("orchestration report is not restored")
    source = normalized_source_set(report)
    if source["origin"] != "project-root" or source["top"] != TOP or tuple(source["compile_order"]) != COMPILE_ORDER:
        raise AcceptanceError("SourceSet closure or compile order mismatch")
    if len(source["compile_order"]) != 19 or len(source["top_closure_files"]) != 19:
        raise AcceptanceError("physical SourceSet count mismatch")
    if manifest(RISC_ROOT, COMPILE_ORDER) != INPUT_MANIFEST:
        raise AcceptanceError("input manifest oracle mismatch")
    if canonical(source) != SOURCE_SET_DIGEST:
        raise AcceptanceError("SourceSet digest oracle mismatch")
    execution = report["mapping_execution"]
    if execution["restored_manifest"] != execution["input_manifest"] or not report["summary"]["strict_compile_passed"]:
        raise AcceptanceError("gate or restore manifest audit failed")
    counts = mapping_counts(report)
    if counts["total"] != 1327 or counts["rename"] != 1301 or counts["preserve"] != 26 or counts["unsupported"] != 0:
        raise AcceptanceError("mapping count oracle mismatch")
    if len({item["owner_module"] for item in normalized_mapping_ranges(report) if item["category"] == "modules"}) != 17:
        raise AcceptanceError("module closure count mismatch")
    if report["summary"]["files"] != 19 or report["summary"]["modified_tokens"] != 7182:
        raise AcceptanceError("gate summary oracle mismatch")
    if normalized_mapping_range_digest(report) != MAPPING_RANGE_DIGEST or counts["per_category"] != PER_CATEGORY_COUNTS:
        raise AcceptanceError("mapping range or category oracle mismatch")
    if metrics["effective_lines"]["total"] != metrics["affected_lines"]["total"] or metrics["symbols"]["coverage"] != 1.0 or metrics["occurrences"]["coverage"] != 1.0 or metrics["plaintext_leakage_rate"] != 0.0:
        raise AcceptanceError("metrics audit failed")
    decrypt_command = [
        sys.executable, "-m", "rtl_obfuscator.rewrite", "decrypt-vnext",
        "--map", str(mapping_path), "--gate-dir", str(gate),
        "--source-root", str(RISC_ROOT), "--output-dir", str(restored),
        "--report", str(restored_report),
    ]
    _run(decrypt_command)
    if manifest(restored, COMPILE_ORDER) != INPUT_MANIFEST:
        raise AcceptanceError("restore manifest mismatch")
    if any((RISC_ROOT / relative).read_bytes() != (restored / relative).read_bytes() for relative in COMPILE_ORDER):
        raise AcceptanceError("restore is not byte-identical")

    gold_view = work / "formal-gold"
    gold_manifest = work / "formal-gold.json"
    gate_view = work / "formal-gate"
    gate_view_manifest = work / "formal-gate.json"
    aligned = work / "formal-aligned"
    aligned_manifest = work / "formal-aligned.json"
    source_set = from_project_root(project_root=RISC_ROOT, top=TOP)
    gate_source_set: SourceSet = replace(source_set, source_root=gate.resolve())
    gold_summary = build_formal_view_vnext(source_set, output_dir=gold_view, manifest_path=gold_manifest)
    gate_summary = build_formal_view_vnext(gate_source_set, output_dir=gate_view, manifest_path=gate_view_manifest)
    gold_view_report = json.loads(gold_manifest.read_text(encoding="utf-8"))
    gate_view_report = json.loads(gate_view_manifest.read_text(encoding="utf-8"))
    if gold_summary["transformations"] != FORMAL_TRANSFORMATIONS or gate_summary["transformations"] != FORMAL_TRANSFORMATIONS:
        raise AcceptanceError("formal transformation count oracle mismatch")
    if dict(Counter(item["kind"] for item in gold_view_report["transformations"])) != FORMAL_KIND_COUNTS:
        raise AcceptanceError("formal transformation kind oracle mismatch")
    if formal_signature_digest(gold_view_report) != FORMAL_SIGNATURE_DIGEST or formal_signature_digest(gate_view_report) != FORMAL_SIGNATURE_DIGEST:
        raise AcceptanceError("gold/gate formal transformation signatures differ")
    replacements = {
        record["renamed_name"]: record["original_name"]
        for record in report["mapping"]["records"]
        if record.get("action") == "rename"
    }
    gold_warnings = _yosys_warnings(gold_view, source, {})
    gate_warnings = _yosys_warnings(gate_view, source, replacements)
    if gold_warnings != gate_warnings:
        raise AcceptanceError("gold/gate Yosys warnings differ")
    alignment_summary = align_formal_view_vnext(
        gate_dir=gate, gate_view_dir=gate_view,
        gate_view_manifest_path=gate_view_manifest,
        orchestration_report_path=mapping_path,
        output_dir=aligned, manifest_path=aligned_manifest,
    )
    aligned_warnings = _yosys_warnings(aligned, source, {})
    if aligned_warnings != gold_warnings:
        raise AcceptanceError("gold/aligned Yosys warnings differ")
    if alignment_summary["identifier_replacements"] != 6914 or alignment_summary["aligned_view_manifest_sha256"] != ALIGNED_VIEW_MANIFEST:
        raise AcceptanceError("formal alignment oracle mismatch")
    positive_command = _formal_command(gold_view, aligned)
    positive = _run(positive_command)
    positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
    if positive_json.get("formal_equivalence") != "pass":
        raise AcceptanceError("positive Formal result is not pass")

    negative = work / "formal-negative"
    shutil.copytree(aligned, negative)
    negative_file = negative / "rtl/vector/vector_top.sv"
    original = negative_file.read_bytes()
    needle = b"assign vector_idle_o = "
    if original.count(needle) != 1:
        raise AcceptanceError("negative target assignment is not unique")
    position = original.index(needle) + len(needle)
    ampersand = original.find(b"&", position)
    if ampersand < 0:
        raise AcceptanceError("negative target has no ASCII ampersand")
    negative_file.write_bytes(original[:ampersand] + b"|" + original[ampersand + 1:])
    changed = negative_file.read_bytes()
    if len(changed) != len(original) or sum(left != right for left, right in zip(original, changed)) != 1:
        raise AcceptanceError("negative mutation is not one byte")
    negative_compile = _strict_compile(negative)
    if negative_compile != (0, 0):
        raise AcceptanceError(f"negative strict compile failed: {negative_compile}")
    negative_command = _formal_command(gold_view, negative)
    negative_process = _run(negative_command, expect=None)
    negative_text = (negative_process.stdout + negative_process.stderr).lower()
    if negative_process.returncode == 0 or "unproven" not in negative_text or "equiv_status -assert" not in negative_text:
        raise AcceptanceError("negative Formal did not fail with the required evidence")

    return {
        "format": "rtl-obfuscation.risc-v-vector-vnext-acceptance",
        "schema_version": 1,
        "status": "pass",
        "input": {
            "origin": source["origin"], "top": source["top"], "files": 19,
            "modules": 17, "input_manifest_sha256": INPUT_MANIFEST,
            "source_set_digest": canonical(source),
        },
        "mapping": {
            "range_digest": normalized_mapping_range_digest(report),
            **counts,
        },
        "metrics": {
            "effective_line_total": metrics["effective_lines"]["total"],
            "affected_line_count": metrics["affected_lines"]["changed"],
            "modified_tokens": report["summary"]["modified_tokens"],
            "symbols": metrics["symbols"], "occurrences": metrics["occurrences"],
            "plaintext_leakage_rate": metrics["plaintext_leakage_rate"],
        },
        "restore": {
            "files": 19, "restored_manifest_equal": True,
            "byte_identical": True,
        },
        "formal_view": {
            "gold_transformations": gold_summary["transformations"],
            "gate_transformations": gate_summary["transformations"],
            "gold_signature_digest": formal_signature_digest(gold_view_report),
            "gate_signature_digest": formal_signature_digest(gate_view_report),
            "normalized_yosys_warning_digest": canonical(sorted(gold_warnings)),
        },
        "formal_alignment": {
            "identifier_replacements": alignment_summary["identifier_replacements"],
            "aligned_view_manifest_sha256": alignment_summary["aligned_view_manifest_sha256"],
        },
        "formal_positive": {"top": TOP, "seq": SEQ, "formal_equivalence": "pass"},
        "formal_negative": {
            "file": "rtl/vector/vector_top.sv", "change": "one ASCII byte & -> |",
            "strict_compile": "pass", "exit_nonzero": True,
            "evidence": "unproven; equiv_status -assert",
        },
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    work = args.work_dir.expanduser()
    if not work.is_absolute() or (work.exists() and (not work.is_dir() or any(work.iterdir()))):
        raise SystemExit("work-dir must be an absent or empty absolute directory")
    work.mkdir(parents=True, exist_ok=True)
    try:
        result = _run_release(work.resolve())
    except (AcceptanceError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
