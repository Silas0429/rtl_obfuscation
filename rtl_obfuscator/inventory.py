"""Emit a random-name inventory for SystemVerilog rename targets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import string
import sys
from typing import Any

import pyslang


_FIRST_NAME_CHARS = string.ascii_letters
_REMAINING_NAME_CHARS = string.ascii_letters + string.digits + "_"
_SUPPORTED_CATEGORIES = (
    "signals",
    "parameters",
    "enum_values",
    "genvars",
    "functions",
    "tasks",
    "arguments",
)

# IEEE 1800 keywords cannot be used as ordinary identifiers. The set includes
# keywords from all language revisions accepted by the current parser.
_SYSTEMVERILOG_KEYWORDS = frozenset(
    """
    accept_on alias always always_comb always_ff always_latch and assert assign
    assume automatic before begin bind bins binsof bit break buf bufif0 bufif1
    byte case casex casez cell chandle checker class clocking cmos config const
    constraint context continue cover covergroup coverpoint cross deassign
    default defparam design disable dist do edge else end endcase endchecker endclass
    endclocking endconfig endfunction endgenerate endgroup endinterface
    endmodule endpackage endprimitive endprogram endproperty endspecify
    endsequence endtable endtask enum event eventually expect export extends
    extern final first_match for force foreach forever fork forkjoin function
    generate genvar global highz0 highz1 if iff ifnone ignore_bins
    illegal_bins implements implies import incdir include initial inout input
    inside instance int integer interconnect interface intersect join join_any
    join_none large let liblist library local localparam logic longint
    macromodule matches medium modport module nand negedge nettype new nexttime
    nmos nor noshowcancelled not notif0 notif1 null or output package packed
    parameter pmos posedge primitive priority program property protected pull0
    pull1 pulldown pullup pulsestyle_ondetect pulsestyle_onevent pure rand randc
    randcase randsequence rcmos real realtime ref reg reject_on release repeat
    restrict return rnmos rpmos rtran rtranif0 rtranif1 s_always s_eventually
    s_nexttime s_until s_until_with scalared sequence shortint shortreal
    showcancelled signed small soft solve specify specparam static string strong
    strong0 strong1 struct super supply0 supply1 sync_accept_on sync_reject_on
    table tagged task this throughout time timeprecision timeunit tran tranif0
    tranif1 tri tri0 tri1 triand trior trireg type typedef union unique unique0
    until until_with
    unsigned untyped use uwire var vectored virtual void wait wait_order wand
    weak weak0 weak1 while wildcard wire with within wor xnor xor
    """.split()
)


def _positive_name_length(value: str) -> int:
    name_length = int(value)
    if name_length < 4:
        raise argparse.ArgumentTypeError("name length must be at least 4")
    return name_length


def _symbol_sort_key(symbol: Any, source_manager: Any) -> tuple[str, int, str]:
    location = symbol.location
    return (
        str(source_manager.getFullPath(location.buffer)),
        location.offset,
        symbol.name,
    )


def _collect_signals(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    signals: list[Any] = []
    port_signals: set[Any] = set()
    function_return_variables: set[Any] = set()
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        kind = getattr(node, "kind", None)
        if kind == pyslang.ast.SymbolKind.Port:
            internal_symbol = node.internalSymbol
            if internal_symbol is not None:
                port_signals.add(internal_symbol)
        elif (
            kind == pyslang.ast.SymbolKind.Subroutine
            and node.subroutineKind == pyslang.ast.SubroutineKind.Function
            and node.returnValVar is not None
        ):
            function_return_variables.add(node.returnValVar)
        elif kind in (pyslang.ast.SymbolKind.Variable, pyslang.ast.SymbolKind.Net):
            signals.append(node)

    compilation.getRoot().visit(visitor)

    unique_signals: dict[tuple[str, int, str], Any] = {}
    for signal in signals:
        definition = signal.declaringDefinition
        if (
            signal in port_signals
            or signal in function_return_variables
            or definition is None
        ):
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(signal, compilation.sourceManager)
        unique_signals.setdefault(key, signal)

    ordered_signals = [unique_signals[key] for key in sorted(unique_signals)]
    return ordered_signals, existing_identifiers


def _collect_parameters(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    parameters: list[Any] = []
    genvars: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        kind = getattr(node, "kind", None)
        if kind == pyslang.ast.SymbolKind.Genvar:
            genvars.append(node)
        elif (
            kind == pyslang.ast.SymbolKind.Parameter
            and not node.isType
        ):
            parameters.append(node)

    compilation.getRoot().visit(visitor)

    parameters = [
        parameter
        for parameter in parameters
        if not any(
            parameter.name == genvar.name
            and parameter.location.buffer == genvar.location.buffer
            and parameter.location.offset == genvar.location.offset
            for genvar in genvars
        )
    ]

    unique_parameters: dict[tuple[str, int, str], Any] = {}
    for parameter in parameters:
        definition = parameter.declaringDefinition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(parameter, compilation.sourceManager)
        unique_parameters.setdefault(key, parameter)

    ordered_parameters = [
        unique_parameters[key] for key in sorted(unique_parameters)
    ]
    return ordered_parameters, existing_identifiers


def _collect_enum_values(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    enum_values: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.TransparentMember:
            wrapped = node.wrapped
            if wrapped.kind == pyslang.ast.SymbolKind.EnumValue:
                enum_values.append(wrapped)

    compilation.getRoot().visit(visitor)

    unique_enum_values: dict[tuple[str, int, str], Any] = {}
    for enum_value in enum_values:
        definition = enum_value.declaringDefinition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(enum_value, compilation.sourceManager)
        unique_enum_values.setdefault(key, enum_value)

    ordered_enum_values = [
        unique_enum_values[key] for key in sorted(unique_enum_values)
    ]
    return ordered_enum_values, existing_identifiers


def _collect_genvars(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    genvars: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Genvar:
            genvars.append(node)

    compilation.getRoot().visit(visitor)

    unique_genvars: dict[tuple[str, int, str], Any] = {}
    for genvar in genvars:
        definition = genvar.declaringDefinition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(genvar, compilation.sourceManager)
        unique_genvars.setdefault(key, genvar)

    ordered_genvars = [unique_genvars[key] for key in sorted(unique_genvars)]
    return ordered_genvars, existing_identifiers


def _collect_subroutines(
    compilation: pyslang.ast.Compilation, subroutine_kind: Any
) -> tuple[list[Any], set[str]]:
    subroutines: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if (
            getattr(node, "kind", None) == pyslang.ast.SymbolKind.Subroutine
            and node.subroutineKind == subroutine_kind
            and node.syntax is not None
            and node.body is not None
        ):
            subroutines.append(node)

    compilation.getRoot().visit(visitor)

    unique_subroutines: dict[tuple[str, int, str], Any] = {}
    for subroutine in subroutines:
        definition = subroutine.declaringDefinition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(subroutine, compilation.sourceManager)
        unique_subroutines.setdefault(key, subroutine)

    ordered_subroutines = [
        unique_subroutines[key] for key in sorted(unique_subroutines)
    ]
    return ordered_subroutines, existing_identifiers


def _collect_arguments(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    arguments: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.FormalArgument:
            arguments.append(node)

    compilation.getRoot().visit(visitor)

    unique_arguments: dict[tuple[str, int, str], Any] = {}
    for argument in arguments:
        definition = argument.declaringDefinition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(argument, compilation.sourceManager)
        unique_arguments.setdefault(key, argument)

    ordered_arguments = [
        unique_arguments[key] for key in sorted(unique_arguments)
    ]
    return ordered_arguments, existing_identifiers


def _collect_targets(
    compilation: pyslang.ast.Compilation, category: str
) -> tuple[list[Any], set[str]]:
    if category == "signals":
        return _collect_signals(compilation)
    if category == "parameters":
        return _collect_parameters(compilation)
    if category == "enum_values":
        return _collect_enum_values(compilation)
    if category == "genvars":
        return _collect_genvars(compilation)
    if category == "functions":
        return _collect_subroutines(
            compilation, pyslang.ast.SubroutineKind.Function
        )
    if category == "tasks":
        return _collect_subroutines(compilation, pyslang.ast.SubroutineKind.Task)
    if category == "arguments":
        return _collect_arguments(compilation)
    raise ValueError(f"unsupported category: {category}")


def _new_name(name_length: int, unavailable: set[str]) -> str:
    for _ in range(1000):
        candidate = secrets.choice(_FIRST_NAME_CHARS) + "".join(
            secrets.choice(_REMAINING_NAME_CHARS)
            for _ in range(name_length - 1)
        )
        if candidate in _SYSTEMVERILOG_KEYWORDS or candidate in unavailable:
            continue
        unavailable.add(candidate)
        return candidate
    raise RuntimeError("could not generate a unique non-keyword name in 1000 attempts")


def _range_record(
    input_file: Path,
    source_manager: Any,
    location: Any,
    byte_length: int,
) -> dict[str, Any]:
    source_path = source_manager.getFullPath(location.buffer).resolve()
    if source_path != input_file.resolve():
        raise ValueError("range is outside the input file")
    return {
        "file": str(input_file),
        "start": location.offset,
        "end": location.offset + byte_length,
    }


def _same_location(first: Any, second: Any) -> bool:
    return first.buffer == second.buffer and first.offset == second.offset


def _genvar_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))

    loop_syntaxes: list[Any] = []
    for syntax_tree in compilation.getSyntaxTrees():
        syntax_tree.root.visit(
            lambda node: loop_syntaxes.append(node)
            if getattr(node, "kind", None) == pyslang.syntax.SyntaxKind.LoopGenerate
            else None
        )

    references: dict[Any, list[Any]] = {target: [] for target in targets}
    for target in targets:
        iteration_parameters = [
            node
            for node in semantic_nodes
            if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Parameter
            and node.name == target.name
            and node.isLocalParam
            and node.isBodyParam
            and _same_location(node.location, target.location)
        ]
        if len(iteration_parameters) != 4:
            raise ValueError("expected four elaborated genvar iteration parameters")

        for node in semantic_nodes:
            if getattr(node, "kind", None) != pyslang.ast.ExpressionKind.NamedValue:
                continue
            if any(node.symbol is parameter for parameter in iteration_parameters):
                references[target].append(node.syntax.identifier)

        matching_loops = [
            loop
            for loop in loop_syntaxes
            if _same_location(loop.identifier.location, target.location)
            and loop.identifier.rawText == target.name
        ]
        if len(matching_loops) != 1:
            raise ValueError("expected one source loop for genvar")
        loop = matching_loops[0]
        header_tokens = [
            loop.stopExpr.left.identifier,
            loop.iterationExpr.operand.identifier,
        ]
        if any(token.rawText != target.name for token in header_tokens):
            raise ValueError("genvar header token does not match declaration")
        references[target].extend(header_tokens)

    return references


def _subroutine_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))

    references: dict[Any, list[Any]] = {target: [] for target in targets}
    for target in targets:
        for node in semantic_nodes:
            kind = getattr(node, "kind", None)
            if kind == pyslang.ast.ExpressionKind.Call:
                if node.subroutine is target:
                    references[target].append(node.syntax.left.identifier)
            elif (
                target.subroutineKind == pyslang.ast.SubroutineKind.Function
                and kind == pyslang.ast.ExpressionKind.NamedValue
                and node.symbol is target.returnValVar
            ):
                references[target].append(node.syntax.identifier)

    return references


def _add_ranges(
    entries: list[dict[str, Any]],
    targets: list[Any],
    categories: list[str],
    compilation: pyslang.ast.Compilation,
    input_file: Path,
) -> None:
    references: dict[Any, list[Any]] = {target: [] for target in targets}
    generic_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category not in ("genvars", "functions", "tasks")
    ]

    def visitor(node: Any) -> None:
        if getattr(node, "kind", None) != pyslang.ast.ExpressionKind.NamedValue:
            return
        for target in generic_targets:
            if node.symbol is target:
                references[target].append(node.syntax.identifier)
                return

    compilation.getRoot().visit(visitor)
    genvar_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "genvars"
    ]
    for target, tokens in _genvar_reference_tokens(
        genvar_targets, compilation
    ).items():
        references[target].extend(tokens)
    subroutine_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category in ("functions", "tasks")
    ]
    for target, tokens in _subroutine_reference_tokens(
        subroutine_targets, compilation
    ).items():
        references[target].extend(tokens)

    source_bytes = input_file.read_bytes()
    all_ranges: list[tuple[int, int]] = []

    for entry, target in zip(entries, targets, strict=True):
        declaration = _range_record(
            input_file,
            compilation.sourceManager,
            target.location,
            len(target.name),
        )
        reference_records = []
        for token in references[target]:
            reference_records.append(
                _range_record(
                    input_file,
                    compilation.sourceManager,
                    token.location,
                    len(token.rawText.encode("utf-8")),
                )
            )

        unique_references = {
            (record["start"], record["end"]): record
            for record in reference_records
        }
        ordered_references = [
            unique_references[key] for key in sorted(unique_references)
        ]
        entry["declaration"] = declaration
        entry["references"] = ordered_references

        expected_bytes = target.name.encode("utf-8")
        for record in [declaration, *ordered_references]:
            start = record["start"]
            end = record["end"]
            if source_bytes[start:end] != expected_bytes:
                raise ValueError("range does not contain the expected identifier")
            all_ranges.append((start, end))

    ordered_ranges = sorted(all_ranges)
    if len(ordered_ranges) != len(set(ordered_ranges)):
        raise ValueError("duplicate identifier ranges")
    if any(
        current_start < previous_end
        for (_, previous_end), (current_start, _) in zip(
            ordered_ranges, ordered_ranges[1:]
        )
    ):
        raise ValueError("overlapping identifier ranges")


def _build_inventory(
    input_file: Path,
    name_length: int,
    category: str,
    include_ranges: bool = False,
) -> dict[str, Any]:
    syntax_tree = pyslang.syntax.SyntaxTree.fromFile(str(input_file))
    compilation = pyslang.ast.Compilation()
    compilation.addSyntaxTree(syntax_tree)

    diagnostics = list(compilation.getAllDiagnostics())
    if any(diagnostic.isError() for diagnostic in diagnostics):
        raise ValueError("input contains SystemVerilog errors")

    requested_categories = (
        _SUPPORTED_CATEGORIES if category == "all" else (category,)
    )
    targets: list[Any] = []
    categories: list[str] = []
    unavailable: set[str] = set()
    for requested_category in requested_categories:
        category_targets, existing_identifiers = _collect_targets(
            compilation, requested_category
        )
        targets.extend(category_targets)
        categories.extend([requested_category] * len(category_targets))
        unavailable.update(existing_identifiers)

    entries = []
    for target, target_category in zip(targets, categories, strict=True):
        entries.append(
            {
                "category": target_category,
                "scope": target.declaringDefinition.name,
                "original_name": target.name,
                "renamed_name": _new_name(name_length, unavailable),
            }
        )

    if include_ranges:
        _add_ranges(
            entries,
            targets,
            categories,
            compilation,
            input_file,
        )

    return {"version": 1, "name_length": name_length, "entries": entries}


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List random-name mappings for SystemVerilog identifiers."
    )
    parser.add_argument("--input", required=True, type=Path, dest="input_file")
    parser.add_argument(
        "--category",
        required=True,
        choices=(
            "signals",
            "parameters",
            "enum_values",
            "genvars",
            "functions",
            "tasks",
            "arguments",
        ),
    )
    parser.add_argument(
        "--name-length", required=True, type=_positive_name_length, dest="name_length"
    )
    parser.add_argument("--include-ranges", action="store_true")
    return parser


def main() -> int:
    parser = _create_argument_parser()
    args = parser.parse_args()
    try:
        inventory = _build_inventory(
            args.input_file, args.name_length, args.category, args.include_ranges
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    json.dump(inventory, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
