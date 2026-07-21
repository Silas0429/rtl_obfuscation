"""Run the complete T029 RISC-V-Vector delivery acceptance flow."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[1]
RISC = REPO / "rtl_samples" / "RISC-V-Vector"
FIFO = REPO / "rtl_samples" / "example_fifo"
INPUT_MANIFEST = "a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d"
ELIGIBLE_SHA256 = "6d4e0ef7d46d569d2fecda8563ccdd4012eb6043cb86b9c908d06391b291e6d0"
PRESERVED_SHA256 = "b5b31416d834ff03eda28e28c4e625108b13e36ecdf28750dc5d78f22e244d9f"
INVENTORY_SHA256 = "0b661f775f936cb15ca5c39dbafbb54c450a5062a935d7daac2d16113d6b3e93"
GOLD_VIEW_MANIFEST = "56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872"
ALIGNED_VIEW_MANIFEST = "d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7"
NEGATIVE_VIEW_MANIFEST = "65e5933dd66b272e924e84ec000313f51d69f9109becd49dd062e1a94fcfb7d6"
GROUPS = ("signals", "ports", "instances", "struct", "interface")


def _canonical(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest(root: Path, files: list[str]) -> str:
    payload = b"".join(
        hashlib.sha256((root / relative).read_bytes()).hexdigest().encode("ascii")
        + b"  "
        + relative.encode("utf-8")
        + b"\n"
        for relative in sorted(files)
    )
    return hashlib.sha256(payload).hexdigest()


def _run(
    command: list[str], *, timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"command timed out: {' '.join(command)}") from error


def _successful_json(
    command: list[str], *, timeout: int | None = None
) -> dict[str, Any]:
    payload, _ = _successful_json_process(command, timeout=timeout)
    return payload


def _successful_json_process(
    command: list[str], *, timeout: int | None = None
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    process = _run(command, timeout=timeout)
    if process.returncode != 0:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(command)}\n"
            + process.stderr[-4000:]
        )
    try:
        return json.loads(process.stdout), process
    except ValueError as error:
        raise RuntimeError("successful command did not emit one JSON object") from error


def _normalized_yosys_warnings(
    stderr: str, mapping: dict[str, Any]
) -> frozenset[str]:
    replacements = {
        entry["renamed_name"]: entry["original_name"]
        for entry in mapping["entries"]
    }
    normalized: set[str] = set()
    for raw_line in stderr.splitlines():
        if "Warning:" not in raw_line:
            continue
        line = raw_line
        source_marker = line.find("/rtl/")
        if source_marker >= 0:
            line = line[source_marker + 1 :]
        for renamed_name, original_name in replacements.items():
            line = line.replace(renamed_name, original_name)
        line = re.sub(r"\$paramod\$[0-9a-f]+", "$paramod$<hash>", line)
        normalized.add(line)
    return frozenset(normalized)


def _rewrite_command(operation: str, *arguments: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "rtl_obfuscator.rewrite",
        operation,
        *arguments,
    ]


def _formal_command(
    *, gold: Path, gate: Path, top: str, seq: int
) -> list[str]:
    return [
        sys.executable,
        "scripts/formal_equivalence.py",
        "--gold-filelist",
        str(gold / "design.f"),
        "--gold-root",
        str(gold),
        "--gate-filelist",
        str(gate / "design.f"),
        "--gate-root",
        str(gate),
        "--top",
        top,
        "--seq",
        str(seq),
    ]


def _signature(item: dict[str, Any]) -> tuple[Any, ...]:
    common = (
        item["kind"],
        item["file"],
        item["syntax_kind"],
        item["structural_ordinal"],
    )
    if item["kind"] == "lower_packed_aggregate_type":
        return (*common, item["bit_width"])
    if item["kind"] == "lower_packed_struct_member":
        return (
            *common,
            item["struct_width"],
            item["field_offset"],
            item["field_width"],
            item["base_shape"],
        )
    return common


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _prepare_work_dir(path: Path) -> Path:
    path = path.resolve()
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise ValueError("--work-dir must be absent or an empty directory")
    else:
        path.mkdir(parents=True)
    return path


def _run_fifo_regression(work: Path) -> dict[str, Any]:
    fifo_work = work / "fifo"
    gate = fifo_work / "gate"
    mapping_path = fifo_work / "mapping.json"
    summary = _successful_json(
        _rewrite_command(
            "encrypt-project",
            "--project-root",
            str(FIFO),
            "--top",
            "fifo_top",
            "--output-dir",
            str(gate),
            "--map",
            str(mapping_path),
            "--metrics",
            str(fifo_work / "metrics.json"),
            *[option for group in GROUPS for option in ("--category", group)],
            "--name-length",
            "8",
        )
    )
    _require(summary == {"files": 4, "mapping_entries": 49, "modified_tokens": 180}, "FIFO encryption oracle mismatch")
    positive = _successful_json(
        _formal_command(gold=FIFO, gate=gate, top="fifo_top", seq=5),
        timeout=600,
    )

    negative = fifo_work / "negative"
    shutil.copytree(gate, negative)
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    count_entry = next(
        item
        for item in mapping["entries"]
        if item["category"] == "signals" and item["original_name"] == "count"
    )
    renamed = count_entry["renamed_name"].encode("ascii")
    path = negative / "fifo_ctrl.sv"
    source = path.read_bytes()
    old = renamed + b" <= " + renamed + b" + 1'b1;"
    new = renamed + b" <= " + renamed + b" + 2;"
    _require(source.count(old) == 1, "FIFO negative mutation target mismatch")
    path.write_bytes(source.replace(old, new, 1))
    negative_process = _run(
        _formal_command(gold=FIFO, gate=negative, top="fifo_top", seq=5),
        timeout=600,
    )
    _require(negative_process.returncode != 0, "FIFO functional negative passed")
    return {"positive": positive["formal_equivalence"], "negative": "expected-fail"}


def run_acceptance(work: Path) -> dict[str, Any]:
    report_path = work / "gold-report.json"
    inspect = _successful_json(
        _rewrite_command(
            "inspect-project",
            "--project-root",
            str(RISC),
            "--top",
            "vector_top",
            "--report",
            str(report_path),
            *[option for group in GROUPS for option in ("--category", group)],
        )
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    files = report["reachable"]["files"]
    _require(_manifest(RISC, files) == INPUT_MANIFEST, "fixed input manifest mismatch")
    _require(inspect["reachable_modules"] == 17 and inspect["closure_files"] == 19, "closure oracle mismatch")
    eligible = report["inventory"]["eligible"]
    preserved = report["inventory"]["preserved"]
    _require(len(eligible) == 1091 and sum(item["occurrences"] for item in eligible) == 5741, "eligible inventory oracle mismatch")
    _require(len(preserved) == 35 and sum(item["occurrences"] for item in preserved) == 113, "preserved inventory oracle mismatch")
    _require(_canonical(eligible) == ELIGIBLE_SHA256, "eligible canonical digest mismatch")
    _require(_canonical(preserved) == PRESERVED_SHA256, "preserved canonical digest mismatch")
    _require(_canonical(report["inventory"]) == INVENTORY_SHA256, "inventory canonical digest mismatch")

    gate = work / "gate"
    mapping_path = work / "mapping.json"
    metrics_path = work / "metrics.json"
    mapping_summary = _successful_json(
        _rewrite_command(
            "encrypt-project",
            "--project-root",
            str(RISC),
            "--top",
            "vector_top",
            "--output-dir",
            str(gate),
            "--map",
            str(mapping_path),
            "--metrics",
            str(metrics_path),
            "--file-map-dir",
            str(work / "maps"),
            *[option for group in GROUPS for option in ("--category", group)],
            "--name-length",
            "8",
        )
    )
    _require(mapping_summary == {"files": 19, "mapping_entries": 1091, "modified_tokens": 5741}, "combined mapping oracle mismatch")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    _require(not any(item["category"] == "parameters" for item in mapping["entries"]), "parameter was renamed")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    _require(metrics["symbols"]["coverage"] == 1.0 and metrics["occurrences"]["coverage"] == 1.0 and metrics["plaintext_leakage_rate"] == 0.0, "metrics oracle mismatch")

    gate_report_path = work / "gate-report.json"
    gate_inspect = _successful_json(
        _rewrite_command(
            "inspect-project",
            "--project-root",
            str(gate),
            "--top",
            "vector_top",
            "--report",
            str(gate_report_path),
            *[option for group in GROUPS for option in ("--category", group)],
        )
    )
    _require(gate_inspect["reachable_modules"] == 17 and gate_inspect["closure_files"] == 19 and gate_inspect["eligible_symbols"] == 1091 and gate_inspect["eligible_occurrences"] == 5741, "gate strict inspect mismatch")

    restored = work / "restored"
    decrypt = _successful_json(
        _rewrite_command(
            "decrypt-project",
            "--gate-dir",
            str(gate),
            "--map",
            str(mapping_path),
            "--output-dir",
            str(restored),
        )
    )
    _require(all((RISC / name).read_bytes() == (restored / name).read_bytes() for name in files), "decrypt bytes mismatch")
    _require(_manifest(restored, files) == INPUT_MANIFEST, "restored manifest mismatch")

    gold_view = work / "formal-gold"
    gate_view = work / "formal-gate"
    gold_view_manifest_path = work / "formal-gold.json"
    gate_view_manifest_path = work / "formal-gate.json"
    gold_view_summary, gold_view_process = _successful_json_process(
        _rewrite_command(
            "formal-view",
            "--project-root",
            str(RISC),
            "--top",
            "vector_top",
            "--output-dir",
            str(gold_view),
            "--manifest",
            str(gold_view_manifest_path),
        )
    )
    gate_view_summary, gate_view_process = _successful_json_process(
        _rewrite_command(
            "formal-view",
            "--project-root",
            str(gate),
            "--top",
            "vector_top",
            "--output-dir",
            str(gate_view),
            "--manifest",
            str(gate_view_manifest_path),
        )
    )
    _require(gold_view_summary["transformations"] == gate_view_summary["transformations"] == 260, "formal-view transform count mismatch")
    _require(gold_view_summary["view_manifest_sha256"] == GOLD_VIEW_MANIFEST, "gold formal-view manifest mismatch")
    gold_view_manifest = json.loads(gold_view_manifest_path.read_text(encoding="utf-8"))
    gate_view_manifest = json.loads(gate_view_manifest_path.read_text(encoding="utf-8"))
    _require([_signature(item) for item in gold_view_manifest["transformations"]] == [_signature(item) for item in gate_view_manifest["transformations"]], "formal-view signatures are asymmetric")

    aligned = work / "formal-gate-aligned"
    aligned_manifest_path = work / "formal-gate-aligned.json"
    alignment, alignment_process = _successful_json_process(
        _rewrite_command(
            "formal-align",
            "--gate-dir",
            str(gate),
            "--gate-view-dir",
            str(gate_view),
            "--gate-view-manifest",
            str(gate_view_manifest_path),
            "--map",
            str(mapping_path),
            "--output-dir",
            str(aligned),
            "--manifest",
            str(aligned_manifest_path),
        )
    )
    _require(alignment["identifier_replacements"] == 5527 and alignment["view_manifest_sha256"] == ALIGNED_VIEW_MANIFEST, "formal alignment oracle mismatch")
    gold_warnings = _normalized_yosys_warnings(gold_view_process.stderr, mapping)
    gate_warnings = _normalized_yosys_warnings(gate_view_process.stderr, mapping)
    aligned_warnings = _normalized_yosys_warnings(alignment_process.stderr, mapping)
    _require(len(gold_warnings) == 18, "gold formal-view warning oracle mismatch")
    _require(gate_warnings == gold_warnings, "gate formal-view warnings are asymmetric")
    _require(aligned_warnings == gold_warnings, "aligned formal-view warnings are asymmetric")
    aligned_repeat = work / "formal-gate-aligned-repeat"
    aligned_repeat_manifest = work / "formal-gate-aligned-repeat.json"
    alignment_repeat = _successful_json(
        _rewrite_command(
            "formal-align",
            "--gate-dir",
            str(gate),
            "--gate-view-dir",
            str(gate_view),
            "--gate-view-manifest",
            str(gate_view_manifest_path),
            "--map",
            str(mapping_path),
            "--output-dir",
            str(aligned_repeat),
            "--manifest",
            str(aligned_repeat_manifest),
        )
    )
    _require(alignment_repeat == alignment and aligned_repeat_manifest.read_bytes() == aligned_manifest_path.read_bytes(), "formal alignment is not deterministic")
    _require(all((aligned / name).read_bytes() == (aligned_repeat / name).read_bytes() for name in files), "aligned RTL is not deterministic")

    positive = _successful_json(
        _formal_command(gold=gold_view, gate=aligned, top="vector_top", seq=1),
        timeout=600,
    )
    negative = work / "formal-gate-negative"
    shutil.copytree(aligned, negative)
    negative_file = negative / "rtl/vector/vector_top.sv"
    source = negative_file.read_bytes()
    marker = source.index(b"assign vector_idle_o =")
    semicolon = source.index(b";", marker)
    operator = source.index(b"&", marker, semicolon)
    mutated = source[:operator] + b"|" + source[operator + 1 :]
    _require(len(mutated) == len(source) and sum(a != b for a, b in zip(source, mutated, strict=True)) == 1, "RISC negative is not one byte")
    negative_file.write_bytes(mutated)
    _require(_manifest(negative, files) == NEGATIVE_VIEW_MANIFEST, "RISC negative manifest mismatch")
    negative_process = _run(
        _formal_command(gold=gold_view, gate=negative, top="vector_top", seq=1),
        timeout=600,
    )
    negative_log = negative_process.stdout + negative_process.stderr
    _require(negative_process.returncode != 0, "RISC functional negative passed")
    _require("Found 1 unproven $equiv cells" in negative_log and re.search(r"Trying to prove \$equiv for \\vector_idle_o: failed", negative_log) is not None, "RISC negative did not isolate vector_idle_o")

    fifo = _run_fifo_regression(work)
    return {
        "status": "pass",
        "input_manifest": INPUT_MANIFEST,
        "closure": 19,
        "modules": 17,
        "inventory": {"eligible": [1091, 5741], "preserved": [35, 113]},
        "mapping": mapping_summary,
        "metrics": {"symbols": 1.0, "occurrences": 1.0, "leakage": 0.0},
        "decrypt": decrypt,
        "formal_view": {"transformations": 260, "gold_manifest": GOLD_VIEW_MANIFEST, "warnings": 18},
        "formal_alignment": alignment,
        "formal_positive": positive,
        "formal_negative": {"status": "expected-fail", "unproven": 1, "cell": "vector_idle_o"},
        "fifo_regression": fifo,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run_acceptance(_prepare_work_dir(args.work_dir))
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
