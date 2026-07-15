"""Run the project's minimal Yosys RTL equivalence flow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _input_path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file does not exist: {value}")
    if any(character.isspace() or character in {'"', ';'} for character in str(path)):
        raise argparse.ArgumentTypeError("formal input paths cannot contain whitespace, quotes, or semicolons")
    return path


def _top_name(value: str) -> str:
    if not SIMPLE_IDENTIFIER.fullmatch(value):
        raise argparse.ArgumentTypeError("top must be a simple SystemVerilog identifier")
    return value


def _yosys_script_multifile(
    gold_files: list[Path], gate_files: list[Path], top: str, seq: int
) -> str:
    gold_paths = " ".join(str(f) for f in gold_files)
    gate_paths = " ".join(str(f) for f in gate_files)
    return f"""
read_verilog -sv -formal {gold_paths}
prep -top {top} -flatten
memory_map -formal
opt_clean
rename {top} gold
design -stash gold_design
design -reset

read_verilog -sv -formal {gate_paths}
prep -top {top} -flatten
memory_map -formal
opt_clean
rename {top} gate
design -stash gate_design
design -reset

design -copy-from gold_design -as gold gold
design -copy-from gate_design -as gate gate
equiv_make gold gate equiv
hierarchy -top equiv
equiv_struct -icells
equiv_simple -seq {seq}
equiv_induct -seq {seq}
equiv_status -assert
"""


def _yosys_script(gold: Path, gate: Path, top: str, seq: int) -> str:
    return f"""
read_verilog -sv -formal {gold}
prep -top {top} -flatten
memory_map -formal
opt_clean
rename {top} gold
design -stash gold_design
design -reset

read_verilog -sv -formal {gate}
prep -top {top} -flatten
memory_map -formal
opt_clean
rename {top} gate
design -stash gate_design
design -reset

design -copy-from gold_design -as gold gold
design -copy-from gate_design -as gate gate
equiv_make gold gate equiv
hierarchy -top equiv
equiv_struct -icells
equiv_simple -seq {seq}
equiv_induct -seq {seq}
equiv_status -assert
"""


def _resolve_filelist(filelist_path: Path, root: Path) -> list[Path]:
    # filelist_path: try cwd first, then root
    resolved_filelist = filelist_path.resolve()
    if not resolved_filelist.is_file():
        resolved_filelist = (root / filelist_path).resolve()
    if not resolved_filelist.is_file():
        raise argparse.ArgumentTypeError(f"filelist does not exist: {filelist_path}")
    lines = resolved_filelist.read_text(encoding="utf-8").strip().splitlines()
    files = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        resolved = (root / line).resolve()
        if not resolved.is_file():
            raise argparse.ArgumentTypeError(f"file does not exist: {resolved}")
        if any(c.isspace() or c in {'"', ';'} for c in str(resolved)):
            raise argparse.ArgumentTypeError("formal input paths cannot contain whitespace, quotes, or semicolons")
        files.append(resolved)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove equivalence of two SystemVerilog designs (single-file or multi-file)"
    )
    # Single-file mode
    parser.add_argument("--gold", type=_input_path, default=None, help="original SystemVerilog file")
    parser.add_argument("--gate", type=_input_path, default=None, help="renamed SystemVerilog file")
    # Multi-file mode
    parser.add_argument("--gold-filelist", type=Path, default=None, help="filelist for original design")
    parser.add_argument("--gold-root", type=Path, default=None, help="root directory for gold filelist")
    parser.add_argument("--gate-filelist", type=Path, default=None, help="filelist for renamed design")
    parser.add_argument("--gate-root", type=Path, default=None, help="root directory for gate filelist")
    # Common
    parser.add_argument("--top", required=True, type=_top_name, help="unchanged top module name")
    parser.add_argument("--seq", type=int, default=5, help="sequential proof depth, default: 5")
    args = parser.parse_args()

    if args.seq < 1:
        parser.error("--seq must be at least 1")

    single_mode = args.gold is not None and args.gate is not None
    multi_mode = (
        args.gold_filelist is not None
        and args.gold_root is not None
        and args.gate_filelist is not None
        and args.gate_root is not None
    )

    if single_mode and not multi_mode:
        process = subprocess.run(
            ["yosys", "-Q", "-p", _yosys_script(args.gold, args.gate, args.top, args.seq)],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            sys.stderr.write(process.stdout)
            sys.stderr.write(process.stderr)
            return process.returncode
        print(
            json.dumps(
                {
                    "formal_equivalence": "pass",
                    "gate": str(args.gate),
                    "gold": str(args.gold),
                    "seq": args.seq,
                    "top": args.top,
                },
                sort_keys=True,
            )
        )
        return 0
    elif multi_mode and not single_mode:
        gold_files = _resolve_filelist(args.gold_filelist, args.gold_root)
        gate_files = _resolve_filelist(args.gate_filelist, args.gate_root)
        process = subprocess.run(
            ["yosys", "-Q", "-p", _yosys_script_multifile(gold_files, gate_files, args.top, args.seq)],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            sys.stderr.write(process.stdout)
            sys.stderr.write(process.stderr)
            return process.returncode
        print(
            json.dumps(
                {
                    "formal_equivalence": "pass",
                    "gate": str(args.gate_root),
                    "gold": str(args.gold_root),
                    "seq": args.seq,
                    "top": args.top,
                },
                sort_keys=True,
            )
        )
        return 0
    else:
        parser.error("use either --gold/--gate (single-file) or --gold-filelist/--gold-root/--gate-filelist/--gate-root (multi-file)")


if __name__ == "__main__":
    raise SystemExit(main())
