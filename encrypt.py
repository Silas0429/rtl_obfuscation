#!/usr/bin/env python3
"""Demonstrate RISC-V-Vector project encryption and byte-identical decryption."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPOSITORY = Path(__file__).resolve().parent
RISC_ROOT = REPOSITORY / "rtl_samples" / "RISC-V-Vector"
DEFAULT_WORK_DIR = Path("/tmp/rtl_obfuscation_risc_demo")
TOP = "vector_top"
CATEGORIES = ("signals", "ports", "instances", "struct", "interface")


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
        raise RuntimeError(
            f"rewrite command failed with exit code {process.returncode}: {detail}"
        )
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


def _byte_identical(
    source_root: Path, restored_root: Path, relative_files: list[str]
) -> bool:
    return all(
        (source_root / relative_file).read_bytes()
        == (restored_root / relative_file).read_bytes()
        for relative_file in relative_files
    )


def run_demo(
    *, work_dir: Path, name_length: int, encryption_rate: str | None
) -> dict[str, Any]:
    if not RISC_ROOT.is_dir():
        raise ValueError(f"RISC-V-Vector sample is missing: {RISC_ROOT}")
    work = _prepare_work_dir(work_dir)
    gate = work / "gate"
    mapping_path = work / "mapping.json"
    metrics_path = work / "metrics.json"
    maps = work / "maps"
    restored = work / "restored"

    encrypt_arguments = [
        "encrypt-project",
        "--project-root",
        str(RISC_ROOT),
        "--top",
        TOP,
        "--output-dir",
        str(gate),
        "--map",
        str(mapping_path),
        "--metrics",
        str(metrics_path),
        "--file-map-dir",
        str(maps),
    ]
    for category in CATEGORIES:
        encrypt_arguments.extend(("--category", category))
    encrypt_arguments.extend(("--name-length", str(name_length)))
    if encryption_rate is not None:
        encrypt_arguments.extend(("--encryption-rate", encryption_rate))

    encrypt_summary = _run_rewrite(*encrypt_arguments)
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("encrypted mapping.json cannot be read") from error
    if not isinstance(mapping, dict):
        raise RuntimeError("encrypted mapping.json is not an object")
    relative_files = mapping.get("files")
    if not isinstance(relative_files, list) or not all(
        isinstance(relative_file, str) for relative_file in relative_files
    ):
        raise RuntimeError("encrypted mapping does not contain a valid files list")

    decrypt_summary = _run_rewrite(
        "decrypt-project",
        "--gate-dir",
        str(gate),
        "--map",
        str(mapping_path),
        "--output-dir",
        str(restored),
    )
    byte_identical = _byte_identical(RISC_ROOT, restored, relative_files)
    if not byte_identical:
        raise RuntimeError("decrypted RISC-V-Vector files are not byte-identical")

    return {
        "status": "pass",
        "top": TOP,
        "work_dir": str(work),
        "mapping_version": mapping.get("version"),
        "files": len(relative_files),
        "byte_identical": True,
        "encrypt": encrypt_summary,
        "decrypt": decrypt_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demonstrate RISC-V-Vector encryption and byte-identical decryption."
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help="output directory; it must be absent or empty (default: /tmp/rtl_obfuscation_risc_demo)",
    )
    parser.add_argument(
        "--name-length",
        type=int,
        default=8,
        help="encrypted identifier length passed to the project CLI (default: 8)",
    )
    parser.add_argument(
        "--encryption-rate",
        default=None,
        help="optional T036 encryption rate passed to the project CLI",
    )
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
