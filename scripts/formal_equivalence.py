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


def _yosys_script(gold: Path, gate: Path, top: str, seq: int) -> str:
    return f"""
read_verilog -sv -formal {gold}
prep -top {top} -flatten
rename {top} gold
design -stash gold_design
design -reset

read_verilog -sv -formal {gate}
prep -top {top} -flatten
rename {top} gate
design -stash gate_design
design -reset

design -copy-from gold_design -as gold gold
design -copy-from gate_design -as gate gate
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple -seq {seq}
equiv_induct -seq {seq}
equiv_status -assert
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove equivalence of two single-file SystemVerilog designs")
    parser.add_argument("--gold", required=True, type=_input_path, help="original SystemVerilog file")
    parser.add_argument("--gate", required=True, type=_input_path, help="renamed SystemVerilog file")
    parser.add_argument("--top", required=True, type=_top_name, help="unchanged top module name")
    parser.add_argument("--seq", type=int, default=5, help="sequential proof depth, default: 5")
    args = parser.parse_args()

    if args.seq < 1:
        parser.error("--seq must be at least 1")

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


if __name__ == "__main__":
    raise SystemExit(main())
