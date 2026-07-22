#!/usr/bin/env python3
"""Demonstrate FIFO or RISC-V-Vector project encryption and decryption."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from rtl_obfuscator import category_profile


REPOSITORY = Path(__file__).resolve().parent
FIFO_ROOT = REPOSITORY / "rtl_samples" / "example_fifo"
RISC_ROOT = REPOSITORY / "rtl_samples" / "RISC-V-Vector"


@dataclass(frozen=True)
class Sample:
    name: str
    root: Path
    top: str
    default_work_dir: Path


SAMPLES = {
    "fifo": Sample(
        name="fifo",
        root=FIFO_ROOT,
        top="fifo_top",
        default_work_dir=Path("/tmp/rtl_samples/fifo"),
    ),
    "riscv": Sample(
        name="riscv",
        root=RISC_ROOT,
        top="vector_top",
        default_work_dir=Path("/tmp/rtl_samples/riscv"),
    ),
}
DEFAULT_SAMPLE = "riscv"
ALL_CATEGORIES = tuple(category_profile.CANONICAL_CATEGORIES)


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
    *, sample: str = DEFAULT_SAMPLE, work_dir: Path | None = None,
    name_length: int = 20, encryption_rate: str | None = None
) -> dict[str, Any]:
    selected = SAMPLES.get(sample)
    if selected is None:
        raise ValueError(f"unsupported sample: {sample}")
    if not selected.root.is_dir():
        raise ValueError(f"{selected.name} sample is missing: {selected.root}")
    work = _prepare_work_dir(work_dir or selected.default_work_dir)
    gate = work / "gate"
    mapping_path = work / "mapping.json"
    metrics_path = work / "metrics.json"
    maps = work / "maps"
    restored = work / "restored"

    encrypt_arguments = [
        "encrypt-project",
        "--project-root",
        str(selected.root),
        "--top",
        selected.top,
        "--output-dir",
        str(gate),
        "--map",
        str(mapping_path),
        "--metrics",
        str(metrics_path),
        "--file-map-dir",
        str(maps),
    ]
    for category in ALL_CATEGORIES:
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
    byte_identical = _byte_identical(selected.root, restored, relative_files)
    if not byte_identical:
        raise RuntimeError(f"decrypted {selected.name} files are not byte-identical")

    return {
        "status": "pass",
        "sample": selected.name,
        "top": selected.top,
        "work_dir": str(work),
        "categories": list(ALL_CATEGORIES),
        "name_length": name_length,
        "mapping_version": mapping.get("version"),
        "files": len(relative_files),
        "byte_identical": True,
        "encrypt": encrypt_summary,
        "decrypt": decrypt_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demonstrate FIFO or RISC-V-Vector encryption and byte-identical decryption."
    )
    parser.add_argument(
        "--sample",
        choices=tuple(SAMPLES),
        default=DEFAULT_SAMPLE,
        help="sample to encrypt (default: riscv)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="output directory; it must be absent or empty (default depends on --sample)",
    )
    parser.add_argument(
        "--name-length",
        type=int,
        default=20,
        help="encrypted identifier length passed to the project CLI (default: 20)",
    )
    parser.add_argument(
        "--encryption-rate",
        default=None,
        help="optional T036 encryption rate passed to the project CLI",
    )
    args = parser.parse_args()
    try:
        summary = run_demo(
            sample=args.sample,
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
