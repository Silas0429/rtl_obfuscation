"""Run the project's minimal Yosys RTL equivalence flow."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
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


@dataclass(frozen=True)
class _FilelistContext:
    files: tuple[Path, ...]
    include_dirs: tuple[Path, ...]
    defines: tuple[tuple[str, str], ...]


def _read_verilog(context: _FilelistContext) -> str:
    arguments = (
        *(f"-I{path}" for path in context.include_dirs),
        *(f"-D{name}={value}" for name, value in context.defines),
        *(str(path) for path in context.files),
    )
    return "read_verilog -sv -formal -defer " + " ".join(arguments)


def _yosys_script_multifile(
    gold: _FilelistContext, gate: _FilelistContext, top: str, seq: int
) -> str:
    gold_read = _read_verilog(gold)
    gate_read = _read_verilog(gate)
    return f"""
{gold_read}
prep -top {top} -flatten
async2sync
memory_map -formal
opt_clean
rename {top} gold
design -stash gold_design
design -reset

{gate_read}
prep -top {top} -flatten
async2sync
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


def _safe_yosys_argument(
    value: str, *, label: str, allow_empty: bool = False
) -> str:
    if (not value and not allow_empty) or any(
        character.isspace() or character in {'"', ";", "`"}
        for character in value
    ):
        raise argparse.ArgumentTypeError(f"formal {label} is not shell-safe")
    return value


def _resolve_filelist(filelist_path: Path, root: Path) -> _FilelistContext:
    # filelist_path: try cwd first, then root
    resolved_filelist = filelist_path.resolve()
    if not resolved_filelist.is_file():
        resolved_filelist = (root / filelist_path).resolve()
    if not resolved_filelist.is_file():
        raise argparse.ArgumentTypeError(f"filelist does not exist: {filelist_path}")
    files: list[Path] = []
    include_dirs: list[Path] = []
    defines: list[tuple[str, str]] = []

    def resolved_path(raw: str, *, base: Path, label: str) -> Path:
        safe = _safe_yosys_argument(os.path.expandvars(raw), label=label)
        path = Path(safe)
        return path.resolve() if path.is_absolute() else (base / path).resolve()

    def visit(current: Path, active: tuple[Path, ...], entry_base: Path) -> None:
        canonical = current.resolve()
        if canonical in active:
            raise argparse.ArgumentTypeError(
                f"filelist includes itself through a recursive -f chain: {canonical}"
            )
        if not canonical.is_file():
            raise argparse.ArgumentTypeError(f"filelist does not exist: {canonical}")
        next_active = (*active, canonical)
        for raw_line in canonical.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            tokens = line.split()
            if tokens[0] == "-f":
                if len(tokens) != 2:
                    raise argparse.ArgumentTypeError(
                        "-f requires exactly one filelist path"
                    )
                nested = resolved_path(
                    tokens[1], base=entry_base, label="nested filelist"
                )
                visit(nested, next_active, nested.parent)
                continue
            if tokens[0] == "-v":
                if len(tokens) != 2:
                    raise argparse.ArgumentTypeError(
                        "-v requires exactly one source path"
                    )
                source = resolved_path(
                    tokens[1], base=entry_base, label="input path"
                )
                if not source.is_file():
                    raise argparse.ArgumentTypeError(
                        f"file does not exist: {source}"
                    )
                files.append(source)
                continue
            if line.startswith("+incdir+"):
                paths = line[len("+incdir+") :].split("+")
                if not paths or any(not path for path in paths):
                    raise argparse.ArgumentTypeError(
                        "+incdir+ requires one or more directory paths"
                    )
                for raw in paths:
                    resolved_dir = resolved_path(
                        raw, base=entry_base, label="include directory"
                    )
                    if not resolved_dir.is_dir():
                        raise argparse.ArgumentTypeError(
                            f"include directory does not exist: {resolved_dir}"
                        )
                    include_dirs.append(resolved_dir)
                continue
            if line.startswith("+define+"):
                payloads = line[len("+define+") :].split("+")
                if not payloads or any(not payload for payload in payloads):
                    raise argparse.ArgumentTypeError(
                        "+define+ requires one or more NAME[=VALUE] definitions"
                    )
                for payload in payloads:
                    expanded = os.path.expandvars(payload)
                    name, separator, value = expanded.partition("=")
                    if SIMPLE_IDENTIFIER.fullmatch(name) is None:
                        raise argparse.ArgumentTypeError(
                            f"invalid formal define: {payload}"
                        )
                    definition = value if separator else "1"
                    _safe_yosys_argument(
                        definition, label="define value", allow_empty=True
                    )
                    defines.append((name, definition))
                continue
            if len(tokens) != 1 or line.startswith(("+", "-")):
                raise argparse.ArgumentTypeError(
                    f"unsupported formal filelist entry: {line}"
                )
            source = resolved_path(
                tokens[0], base=entry_base, label="input path"
            )
            if not source.is_file():
                raise argparse.ArgumentTypeError(f"file does not exist: {source}")
            files.append(source)

    visit(resolved_filelist, (), root.resolve())
    if not files:
        raise argparse.ArgumentTypeError("filelist has no source entries")
    return _FilelistContext(tuple(files), tuple(include_dirs), tuple(defines))


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
        gold_context = _resolve_filelist(args.gold_filelist, args.gold_root)
        gate_context = _resolve_filelist(args.gate_filelist, args.gate_root)
        process = subprocess.run(
            ["yosys", "-Q", "-p", _yosys_script_multifile(gold_context, gate_context, args.top, args.seq)],
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
