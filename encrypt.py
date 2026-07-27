#!/usr/bin/env python3
"""Run the non-RISC FIFO vNext encryption/restore demonstration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from rtl_obfuscator.category_registry_vnext import MODULE_ABI_CATEGORIES


REPOSITORY = Path(__file__).resolve().parent
FIFO_ROOT = REPOSITORY / "rtl_samples" / "example_fifo"
ALL_CATEGORIES = (
    "signals", "parameters", "enum_values", "genvars", "functions", "tasks",
    "arguments", "instances", "generate_blocks", "typedefs", "struct_types",
    "struct_fields", "union_fields", "modules", "ports", "interfaces",
    "interface_instances", "interface_ports", "modports",
)


def _run_rewrite(*arguments: str) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(f"rewrite command failed with exit code {process.returncode}: {detail}")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("rewrite command did not emit one JSON summary") from error
    if not isinstance(payload, dict):
        raise RuntimeError("rewrite command emitted a non-object JSON summary")
    return payload


def _prepare_work_dir(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise ValueError("--work-dir must be absent or an empty directory")
    else:
        resolved.mkdir(parents=True)
    return resolved


def run_demo(
    *, work_dir: Path | None = None, name_length: int = 20,
    encryption_rate: str | None = None,
) -> dict[str, Any]:
    if not FIFO_ROOT.is_dir():
        raise ValueError(f"FIFO sample is missing: {FIFO_ROOT}")
    work = _prepare_work_dir(work_dir or Path("/tmp/rtl_samples/fifo"))
    gate = work / "gate"
    mapping_path = work / "orchestration.json"
    metrics_path = work / "metrics.json"
    restored = work / "restored"
    restore_report = work / "restore.json"

    encrypt_arguments = [
        "encrypt-vnext", "--project-root", str(FIFO_ROOT), "--top", "fifo_top",
        "--category", "all", "--category", "interface", "--category", "modules",
        "--category", "ports", "--name-length", str(name_length),
        "--output-dir", str(gate), "--map", str(mapping_path),
        "--metrics", str(metrics_path),
    ]
    for category in MODULE_ABI_CATEGORIES:
        encrypt_arguments.extend(("--abi-category", category))
    if encryption_rate is not None:
        encrypt_arguments.extend(("--encryption-rate", encryption_rate))
    encrypt_summary = _run_rewrite(*encrypt_arguments)

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    source_set = mapping.get("source_set")
    if not isinstance(source_set, dict):
        raise RuntimeError("orchestration report does not contain SourceSet")
    relative_files = tuple(dict.fromkeys((*source_set["ordered_source_files"], *source_set["included_files"])))
    decrypt_summary = _run_rewrite(
        "decrypt-vnext", "--gate-dir", str(gate), "--map", str(mapping_path),
        "--source-root", str(FIFO_ROOT), "--output-dir", str(restored),
        "--report", str(restore_report),
    )
    byte_identical = all(
        (FIFO_ROOT / relative_file).read_bytes() == (restored / relative_file).read_bytes()
        for relative_file in relative_files
    )
    if not byte_identical:
        raise RuntimeError("FIFO files are not byte-identical after restore")
    return {
        "status": "pass",
        "sample": "fifo",
        "top": "fifo_top",
        "name_length": name_length,
        "categories": list(ALL_CATEGORIES),
        "files": len(relative_files),
        "byte_identical": True,
        "encrypt": encrypt_summary["summary"],
        "decrypt": decrypt_summary["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Demonstrate FIFO vNext encryption and restore.")
    parser.add_argument("--sample", choices=("fifo",), default="fifo")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--name-length", type=int, default=20)
    parser.add_argument("--encryption-rate", default=None)
    args = parser.parse_args()
    try:
        summary = run_demo(
            work_dir=args.work_dir,
            name_length=args.name_length,
            encryption_rate=args.encryption_rate,
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
