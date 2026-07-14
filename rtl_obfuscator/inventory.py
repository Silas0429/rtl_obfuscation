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
    "instances",
    "generate_blocks",
    "typedefs",
    "struct_types",
    "struct_fields",
    "union_fields",
    "modules",
    "ports",
    "interfaces",
    "interface_instances",
    "interface_ports",
    "modports",
)

_ALL_CATEGORIES = tuple(
    c
    for c in _SUPPORTED_CATEGORIES
    if c
    not in (
        "modules",
        "ports",
        "interfaces",
        "interface_instances",
        "interface_ports",
        "modports",
    )
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


def _collect_hierarchy_names(
    compilation: pyslang.ast.Compilation, category: str
) -> tuple[list[Any], set[str]]:
    targets: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        kind = getattr(node, "kind", None)
        syntax = getattr(node, "syntax", None)
        syntax_kind = getattr(syntax, "kind", None)
        if (
            category == "instances"
            and kind == pyslang.ast.SymbolKind.Instance
            and syntax_kind == pyslang.syntax.SyntaxKind.HierarchicalInstance
            and node.isModule
            and not syntax.decl.dimensions
        ) or (
            category == "generate_blocks"
            and kind == pyslang.ast.SymbolKind.GenerateBlockArray
            and syntax_kind == pyslang.syntax.SyntaxKind.LoopGenerate
            and name
            and getattr(syntax.parent, "kind", None)
            == pyslang.syntax.SyntaxKind.ModuleDeclaration
        ):
            targets.append(node)

    compilation.getRoot().visit(visitor)

    unique_targets: dict[tuple[str, int, str], Any] = {}
    for target in targets:
        definition = target.declaringDefinition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(target, compilation.sourceManager)
        unique_targets.setdefault(key, target)

    ordered_targets = [unique_targets[key] for key in sorted(unique_targets)]
    return ordered_targets, existing_identifiers



def _collect_type_aliases(
    compilation: pyslang.ast.Compilation, category: str
) -> tuple[list[Any], set[str]]:
    type_aliases: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.TypeAlias:
            if category == "typedefs":
                if not (
                    node.isStruct
                    or node.isPackedUnion
                    or node.isUnpackedStruct
                    or node.isUnpackedUnion
                ):
                    type_aliases.append(node)
            elif category == "struct_types":
                if (
                    node.isStruct
                    or node.isPackedUnion
                    or node.isUnpackedStruct
                    or node.isUnpackedUnion
                ):
                    type_aliases.append(node)

    compilation.getRoot().visit(visitor)

    unique_targets: dict[tuple[str, int, str], Any] = {}
    for target in type_aliases:
        definition = target.declaringDefinition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(target, compilation.sourceManager)
        unique_targets.setdefault(key, target)

    ordered_targets = [unique_targets[key] for key in sorted(unique_targets)]
    return ordered_targets, existing_identifiers




def _collect_struct_union_fields(
    compilation: pyslang.ast.Compilation, category: str
) -> tuple[list[Any], set[str]]:
    fields: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.TypeAlias:
            definition = node.declaringDefinition
            if definition is None:
                return
            if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
                return
            resolved = node.targetType.type
            if category == "struct_fields" and not resolved.isStruct:
                return
            if (
                category == "union_fields"
                and not resolved.isPackedUnion
                and not resolved.isUnpackedUnion
            ):
                return
            for field in resolved:
                fields.append(field)

    compilation.getRoot().visit(visitor)

    unique_fields: dict[tuple[str, int, str], Any] = {}
    for field in fields:
        definition = field.declaringDefinition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        key = _symbol_sort_key(field, compilation.sourceManager)
        unique_fields.setdefault(key, field)

    ordered_fields = [unique_fields[key] for key in sorted(unique_fields)]
    return ordered_fields, existing_identifiers



def _collect_modules(
    compilation: pyslang.ast.Compilation, top: str
) -> tuple[list[Any], set[str]]:
    instances: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Instance:
            definition = node.definition
            if definition is None:
                return
            if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
                return
            if definition.name == top:
                return
            instances.append(node)

    compilation.getRoot().visit(visitor)

    # Group instances by their definition to deduplicate
    definition_to_instances: dict[Any, list[Any]] = {}
    for instance in instances:
        definition = instance.definition
        definition_to_instances.setdefault(definition, []).append(instance)

    ordered_targets: list[Any] = []
    for definition in sorted(
        definition_to_instances,
        key=lambda d: _symbol_sort_key(d, compilation.sourceManager),
    ):
        ordered_targets.append(definition)

    return ordered_targets, existing_identifiers


def _collect_ports(
    compilation: pyslang.ast.Compilation, top: str
) -> tuple[list[Any], set[str]]:
    ports: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Port:
            definition = node.declaringDefinition
            if definition is None:
                return
            if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
                return
            if definition.name == top:
                return
            ports.append(node)

    compilation.getRoot().visit(visitor)

    unique_ports: dict[tuple[str, int, str], Any] = {}
    for port in ports:
        key = _symbol_sort_key(port, compilation.sourceManager)
        unique_ports.setdefault(key, port)

    ordered_ports = [unique_ports[key] for key in sorted(unique_ports)]
    return ordered_ports, existing_identifiers



def _collect_interfaces(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    instances: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)

        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Instance:
            definition = node.definition
            if definition is None:
                return
            if definition.definitionKind != pyslang.ast.DefinitionKind.Interface:
                return
            instances.append(node)

    compilation.getRoot().visit(visitor)

    # Group instances by their definition to deduplicate
    definition_to_instances: dict[Any, list[Any]] = {}
    for instance in instances:
        definition = instance.definition
        definition_to_instances.setdefault(definition, []).append(instance)

    ordered_targets: list[Any] = []
    for definition in sorted(
        definition_to_instances,
        key=lambda d: _symbol_sort_key(d, compilation.sourceManager),
    ):
        ordered_targets.append(definition)

    return ordered_targets, existing_identifiers


def _collect_interface_instances(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    """Collect interface instance names (one target per instance)."""
    instances: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)
        if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Instance:
            return
        definition = getattr(node, "definition", None)
        if definition is None:
            return
        if definition.definitionKind != pyslang.ast.DefinitionKind.Interface:
            return
        instances.append(node)

    compilation.getRoot().visit(visitor)

    unique_instances: dict[tuple[str, int, str], Any] = {}
    for instance in instances:
        key = _symbol_sort_key(instance, compilation.sourceManager)
        unique_instances.setdefault(key, instance)
    ordered_instances = [
        unique_instances[key] for key in sorted(unique_instances)
    ]
    return ordered_instances, existing_identifiers


def _collect_interface_ports(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    """Collect interface member variables, deduplicated by declaration."""
    members: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)
        if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Instance:
            return
        definition = getattr(node, "definition", None)
        if definition is None:
            return
        if definition.definitionKind != pyslang.ast.DefinitionKind.Interface:
            return
        body = getattr(node, "body", None)
        if body is None:
            return
        for child in body:
            if getattr(child, "kind", None) != pyslang.ast.SymbolKind.Variable:
                continue
            declaring_definition = getattr(child, "declaringDefinition", None)
            if declaring_definition is None:
                continue
            if declaring_definition.name != definition.name:
                continue
            members.append(child)

    compilation.getRoot().visit(visitor)

    unique_members: dict[tuple[str, int, str], Any] = {}
    for member in members:
        key = _symbol_sort_key(member, compilation.sourceManager)
        unique_members.setdefault(key, member)
    ordered_members = [unique_members[key] for key in sorted(unique_members)]
    return ordered_members, existing_identifiers


def _collect_modports(
    compilation: pyslang.ast.Compilation,
) -> tuple[list[Any], set[str]]:
    """Collect modport declarations."""
    modports: list[Any] = []
    existing_identifiers: set[str] = set()

    def visitor(node: Any) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name and not name.startswith("$"):
            existing_identifiers.add(name)
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Modport:
            modports.append(node)

    compilation.getRoot().visit(visitor)

    unique_modports: dict[tuple[str, int, str], Any] = {}
    for modport in modports:
        key = _symbol_sort_key(modport, compilation.sourceManager)
        unique_modports.setdefault(key, modport)
    ordered_modports = [unique_modports[key] for key in sorted(unique_modports)]
    return ordered_modports, existing_identifiers

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
    if category in ("instances", "generate_blocks"):
        return _collect_hierarchy_names(compilation, category)
    if category in ("typedefs", "struct_types"):
        return _collect_type_aliases(compilation, category)
    if category in ("struct_fields", "union_fields"):
        return _collect_struct_union_fields(compilation, category)
    if category == "modules":
        raise ValueError("modules category requires top parameter; use _collect_modules directly")
    if category == "ports":
        raise ValueError("ports category requires top parameter; use _collect_ports directly")
    if category == "interfaces":
        return _collect_interfaces(compilation)
    if category == "interface_instances":
        return _collect_interface_instances(compilation)
    if category == "interface_ports":
        return _collect_interface_ports(compilation)
    if category == "modports":
        return _collect_modports(compilation)
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



def _type_alias_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))

    references: dict[Any, list[Any]] = {target: [] for target in targets}
    for target in targets:
        for node in semantic_nodes:
            kind = getattr(node, "kind", None)
            if kind not in (
                pyslang.ast.SymbolKind.Variable,
                pyslang.ast.SymbolKind.Net,
                pyslang.ast.SymbolKind.FormalArgument,
            ):
                continue
            declared_type = getattr(node, "declaredType", None)
            if declared_type is None:
                continue
            resolved_type = getattr(declared_type, "type", None)
            if resolved_type is not target:
                continue
            type_syntax = getattr(declared_type, "typeSyntax", None)
            if type_syntax is None:
                continue
            source_range = getattr(type_syntax, "sourceRange", None)
            if source_range is None:
                continue
            references[target].append(source_range)

    return references




def _struct_union_field_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))

    references: dict[Any, list[Any]] = {target: [] for target in targets}
    for target in targets:
        for node in semantic_nodes:
            if type(node).__name__ != "MemberAccessExpression":
                continue
            member = getattr(node, "member", None)
            if member is not target:
                continue
            syntax = getattr(node, "syntax", None)
            right = getattr(syntax, "right", None)
            source_range = getattr(right, "sourceRange", None)
            if source_range is not None:
                references[target].append(source_range)

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
        if category
        not in (
            "genvars",
            "functions",
            "tasks",
            "instances",
            "generate_blocks",
            "struct_fields",
            "union_fields",
            "modules",
            "ports",
            "interfaces",
            "interface_instances",
            "interface_ports",
            "modports",
        )
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
    type_alias_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category in ("typedefs", "struct_types")
    ]
    for target, tokens in _type_alias_reference_tokens(
        type_alias_targets, compilation
    ).items():
        references[target].extend(tokens)
    struct_union_field_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category in ("struct_fields", "union_fields")
    ]
    for target, tokens in _struct_union_field_reference_tokens(
        struct_union_field_targets, compilation
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
            if hasattr(token, "location"):
                raw_text = getattr(token, "rawText", None)
                if raw_text is None:
                    raw_text = getattr(token, "name", None)
                if not isinstance(raw_text, str):
                    raise ValueError("reference token has no source text")
                reference_records.append(
                    _range_record(
                        input_file,
                        compilation.sourceManager,
                        token.location,
                        len(raw_text.encode("utf-8")),
                    )
                )
            else:
                start_loc = token.start
                end_loc = token.end
                source_path = compilation.sourceManager.getFullPath(
                    start_loc.buffer
                ).resolve()
                if source_path != input_file.resolve():
                    raise ValueError("range is outside the input file")
                reference_records.append(
                    {
                        "file": str(input_file),
                        "start": start_loc.offset,
                        "end": end_loc.offset,
                    }
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
        _ALL_CATEGORIES if category == "all" else (category,)
    )
    targets: list[Any] = []
    categories_list: list[str] = []
    unavailable: set[str] = set()
    for requested_category in requested_categories:
        category_targets, existing_identifiers = _collect_targets(
            compilation, requested_category
        )
        targets.extend(category_targets)
        categories_list.extend([requested_category] * len(category_targets))
        unavailable.update(existing_identifiers)

    entries = []
    for target, target_category in zip(targets, categories_list, strict=True):
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
            categories_list,
            compilation,
            input_file,
        )

    return {"version": 1, "name_length": name_length, "entries": entries}




def _build_project_inventory(
    filelist_path: Path,
    source_root: Path,
    name_length: int,
    categories: list[str],
    top: str = "",
) -> dict[str, Any]:
    filelist_lines = filelist_path.read_text(encoding="utf-8").strip().splitlines()
    relative_files = [Path(line.strip()) for line in filelist_lines if line.strip()]

    compilation = pyslang.ast.Compilation()
    file_by_buffer: dict[Any, Path] = {}
    for relative_file in relative_files:
        absolute_file = source_root / relative_file
        syntax_tree = pyslang.syntax.SyntaxTree.fromFile(str(absolute_file))
        compilation.addSyntaxTree(syntax_tree)
        file_by_buffer[syntax_tree.root.sourceRange.start.buffer] = relative_file

    diagnostics = list(compilation.getAllDiagnostics())
    if any(diagnostic.isError() for diagnostic in diagnostics):
        raise ValueError("input contains SystemVerilog errors")

    requested_categories: list[str] = []
    for cat in categories:
        if cat == "all":
            requested_categories.extend(_ALL_CATEGORIES)
        else:
            requested_categories.append(cat)
    targets: list[Any] = []
    target_categories: list[str] = []
    unavailable: set[str] = set()
    for requested_category in requested_categories:
        if requested_category == "modules":
            category_targets, existing_identifiers = _collect_modules(
                compilation, top
            )
        elif requested_category == "ports":
            category_targets, existing_identifiers = _collect_ports(
                compilation, top
            )
        elif requested_category == "interfaces":
            category_targets, existing_identifiers = _collect_interfaces(
                compilation
            )
        else:
            category_targets, existing_identifiers = _collect_targets(
                compilation, requested_category
            )
        targets.extend(category_targets)
        target_categories.extend([requested_category] * len(category_targets))
        unavailable.update(existing_identifiers)

    entries = []
    for target, target_category in zip(targets, target_categories, strict=True):
        if target_category in ("modules", "interfaces"):
            scope = target.name
        else:
            scope = target.declaringDefinition.name
        entries.append(
            {
                "category": target_category,
                "scope": scope,
                "original_name": target.name,
                "renamed_name": _new_name(name_length, unavailable),
            }
        )

    _add_project_ranges(
        entries,
        targets,
        target_categories,
        compilation,
        source_root,
        file_by_buffer,
        top=top,
    )

    # Project mappings are stable by declaration location, then category.
    entries.sort(
        key=lambda entry: (
            entry["declaration"]["file"],
            entry["declaration"]["start"],
            entry["category"],
        )
    )

    return {
        "version": 2,
        "name_length": name_length,
        "files": [str(f) for f in relative_files],
        "top": top,
        "entries": entries,
    }


def _project_range_record(
    source_root: Path,
    source_manager: Any,
    location: Any,
    byte_length: int,
    file_by_buffer: dict[Any, Path],
) -> dict[str, Any]:
    relative_file = file_by_buffer[location.buffer]
    return {
        "file": str(relative_file),
        "start": location.offset,
        "end": location.offset + byte_length,
    }




def _module_port_reference_tokens(
    targets: list[Any],
    categories: list[str],
    compilation: pyslang.ast.Compilation,
    top: str,
) -> dict[Any, list[Any]]:
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))

    references: dict[Any, list[Any]] = {target: [] for target in targets}

    # Collect all instances (excluding top)
    child_instances = []
    for node in semantic_nodes:
        if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Instance:
            continue
        definition = node.definition
        if definition is None:
            continue
        if definition.definitionKind != pyslang.ast.DefinitionKind.Module:
            continue
        if definition.name == top:
            continue
        child_instances.append(node)

    # Module targets: collect instance type references
    module_targets = [
        target for target, category in zip(targets, categories, strict=True)
        if category == "modules"
    ]
    for target in module_targets:
        for instance in child_instances:
            if instance.definition is target:
                syntax = instance.syntax
                parent = getattr(syntax, "parent", None)
                if parent is not None:
                    type_token = getattr(parent, "type", None)
                    if type_token is not None:
                        references[target].append(type_token)

    # Port targets: collect named connection references and body references
    port_targets = [
        target for target, category in zip(targets, categories, strict=True)
        if category == "ports"
    ]
    # Build mapping from internalSymbol to port target
    port_internal_symbols: dict[Any, Any] = {}
    for target in port_targets:
        internal = target.internalSymbol
        if internal is not None:
            port_internal_symbols[internal] = target
        port_name = target.name
        port_def = target.declaringDefinition
        # Collect named connection references
        for instance in child_instances:
            if instance.definition is not port_def:
                continue
            syntax = instance.syntax
            connections = getattr(syntax, "connections", None)
            if connections is None:
                continue
            for conn in connections:
                if type(conn).__name__ != "NamedPortConnectionSyntax":
                    continue
                name_token = getattr(conn, "name", None)
                if name_token is None:
                    continue
                if name_token.rawText == port_name:
                    references[target].append(name_token)

    # Collect body references via internalSymbol
    for node in semantic_nodes:
        if getattr(node, "kind", None) != pyslang.ast.ExpressionKind.NamedValue:
            continue
        symbol = getattr(node, "symbol", None)
        if symbol is None:
            continue
        if symbol in port_internal_symbols:
            target = port_internal_symbols[symbol]
            identifier = getattr(getattr(node, "syntax", None), "identifier", None)
            if identifier is not None:
                references[target].append(identifier)

    return references



def _interface_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))

    references: dict[Any, list[Any]] = {target: [] for target in targets}
    for target in targets:
        # Instance type references
        for node in semantic_nodes:
            if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Instance:
                continue
            if node.definition is not target:
                continue
            syntax = getattr(node, "syntax", None)
            if syntax is None:
                continue
            parent = getattr(syntax, "parent", None)
            if parent is None:
                continue
            type_token = getattr(parent, "type", None)
            if type_token is not None:
                references[target].append(type_token)

        # InterfacePort header references
        for node in semantic_nodes:
            if getattr(node, "kind", None) != pyslang.ast.SymbolKind.InterfacePort:
                continue
            syntax = getattr(node, "syntax", None)
            if syntax is None:
                continue
            parent = getattr(syntax, "parent", None)
            if parent is None:
                continue
            header = getattr(parent, "header", None)
            if header is None:
                continue
            source_range = getattr(header, "sourceRange", None)
            if source_range is not None:
                references[target].append(source_range)

    return references


def _source_range_matches_name(
    source_manager: Any, source_range: Any, name: str
) -> bool:
    """Check the source bytes covered by a range without relying on syntax APIs."""
    try:
        source_path = Path(
            source_manager.getFullPath(source_range.start.buffer)
        )
        source = source_path.read_bytes()
        return source[source_range.start.offset : source_range.end.offset] == name.encode(
            "utf-8"
        )
    except (OSError, AttributeError, TypeError):
        return False


def _interface_instance_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    """Collect arbitrary-symbol and hierarchical instance references."""
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))
    references: dict[Any, list[Any]] = {target: [] for target in targets}

    for target in targets:
        for node in semantic_nodes:
            node_type = type(node).__name__
            if node_type == "ArbitrarySymbolExpression":
                symbol = getattr(node, "symbol", None)
                if symbol is not target and not (
                    getattr(symbol, "kind", None)
                    == pyslang.ast.SymbolKind.Instance
                    and getattr(symbol, "name", None) == target.name
                ):
                    continue
                source_range = getattr(node, "sourceRange", None)
                if source_range is not None:
                    references[target].append(source_range)
            elif node_type == "HierarchicalValueExpression":
                syntax = getattr(node, "syntax", None)
                if syntax is None or type(syntax).__name__ != "ScopedNameSyntax":
                    continue
                left = getattr(syntax, "left", None)
                source_range = getattr(left, "sourceRange", None)
                if source_range is None:
                    continue
                if _source_range_matches_name(
                    compilation.sourceManager, source_range, target.name
                ):
                    references[target].append(source_range)

    return references


def _interface_port_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    """Collect member accesses and modport port references for interface members."""
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))
    references: dict[Any, list[Any]] = {target: [] for target in targets}

    for target in targets:
        target_definition = getattr(target, "declaringDefinition", None)
        target_definition_name = getattr(target_definition, "name", None)
        for node in semantic_nodes:
            node_type = type(node).__name__
            if node_type == "HierarchicalValueExpression":
                symbol = getattr(node, "symbol", None)
                if symbol is not target and not (
                    getattr(symbol, "kind", None)
                    == pyslang.ast.SymbolKind.Variable
                    and getattr(symbol, "name", None) == target.name
                    and getattr(
                        getattr(symbol, "declaringDefinition", None),
                        "name",
                        None,
                    )
                    == target_definition_name
                ):
                    continue
                syntax = getattr(node, "syntax", None)
                right = getattr(syntax, "right", None)
                source_range = getattr(right, "sourceRange", None)
                if source_range is not None:
                    references[target].append(source_range)
            elif getattr(node, "kind", None) == pyslang.ast.SymbolKind.ModportPort:
                internal = getattr(node, "internalSymbol", None)
                if internal is not target and not (
                    getattr(internal, "name", None) == target.name
                    and getattr(
                        getattr(internal, "declaringDefinition", None),
                        "name",
                        None,
                    )
                    == target_definition_name
                ):
                    continue
                references[target].append(node)

        # Named interface port connections are represented by the left-hand
        # name token in each interface instance's HierarchicalInstanceSyntax.
        # Bind by the instance's resolved interface definition, so a same-name
        # port on an unrelated interface is never collected.
        for node in semantic_nodes:
            if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Instance:
                continue
            definition = getattr(node, "definition", None)
            if definition is None or definition.definitionKind != pyslang.ast.DefinitionKind.Interface:
                continue
            if getattr(definition, "name", None) != target_definition_name:
                continue
            syntax = getattr(node, "syntax", None)
            connections = getattr(syntax, "connections", None)
            if connections is None:
                continue
            for connection in connections:
                if type(connection).__name__ != "NamedPortConnectionSyntax":
                    continue
                name_token = getattr(connection, "name", None)
                if name_token is None:
                    continue
                if getattr(name_token, "rawText", None) == target.name:
                    references[target].append(name_token)

    return references

def _add_project_ranges(
    entries: list[dict[str, Any]],
    targets: list[Any],
    categories: list[str],
    compilation: pyslang.ast.Compilation,
    source_root: Path,
    file_by_buffer: dict[Any, Path],
    top: str = "",
) -> None:
    references: dict[Any, list[Any]] = {target: [] for target in targets}
    generic_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category
        not in (
            "genvars",
            "functions",
            "tasks",
            "instances",
            "generate_blocks",
            "struct_fields",
            "union_fields",
            "modules",
            "ports",
            "interfaces",
            "interface_instances",
            "interface_ports",
            "modports",
        )
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
    type_alias_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category in ("typedefs", "struct_types")
    ]
    for target, tokens in _type_alias_reference_tokens(
        type_alias_targets, compilation
    ).items():
        references[target].extend(tokens)
    struct_union_field_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category in ("struct_fields", "union_fields")
    ]
    for target, tokens in _struct_union_field_reference_tokens(
        struct_union_field_targets, compilation
    ).items():
        references[target].extend(tokens)
    module_port_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category in ("modules", "ports")
    ]
    if module_port_targets:
        for target, tokens in _module_port_reference_tokens(
            module_port_targets,
            [c for c in categories if c in ("modules", "ports")],
            compilation,
            top,
        ).items():
            references[target].extend(tokens)
    interface_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "interfaces"
    ]
    for target, tokens in _interface_reference_tokens(
        interface_targets, compilation
    ).items():
        references[target].extend(tokens)
    interface_instance_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "interface_instances"
    ]
    for target, tokens in _interface_instance_reference_tokens(
        interface_instance_targets, compilation
    ).items():
        references[target].extend(tokens)
    interface_port_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "interface_ports"
    ]
    for target, tokens in _interface_port_reference_tokens(
        interface_port_targets, compilation
    ).items():
        references[target].extend(tokens)

    all_ranges: list[tuple[str, int, int]] = []

    for entry, target in zip(entries, targets, strict=True):
        declaration = _project_range_record(
            source_root,
            compilation.sourceManager,
            target.location,
            len(target.name),
            file_by_buffer,
        )
        reference_records = []
        for token in references[target]:
            if hasattr(token, "location"):
                raw_text = getattr(token, "rawText", None)
                if raw_text is None:
                    raw_text = getattr(token, "name", None)
                if not isinstance(raw_text, str):
                    raise ValueError("reference token has no source text")
                reference_records.append(
                    _project_range_record(
                        source_root,
                        compilation.sourceManager,
                        token.location,
                        len(raw_text.encode("utf-8")),
                        file_by_buffer,
                    )
                )
            else:
                start_loc = token.start
                end_loc = token.end
                relative_file = file_by_buffer[start_loc.buffer]
                reference_records.append(
                    {
                        "file": str(relative_file),
                        "start": start_loc.offset,
                        "end": end_loc.offset,
                    }
                )

        unique_references = {
            (record["file"], record["start"], record["end"]): record
            for record in reference_records
        }
        ordered_references = [
            unique_references[key]
            for key in sorted(unique_references)
        ]
        entry["declaration"] = declaration
        entry["references"] = ordered_references

        expected_bytes = target.name.encode("utf-8")
        for record in [declaration, *ordered_references]:
            rel_file = Path(record["file"])
            abs_file = source_root / rel_file
            source_bytes = abs_file.read_bytes()
            start = record["start"]
            end = record["end"]
            if source_bytes[start:end] != expected_bytes:
                raise ValueError("range does not contain the expected identifier")
            all_ranges.append((record["file"], start, end))

    # Check for duplicates and overlaps within the same file
    file_groups: dict[str, list[tuple[int, int]]] = {}
    for file_name, start, end in all_ranges:
        file_groups.setdefault(file_name, []).append((start, end))
    for file_name, ranges_in_file in file_groups.items():
        sorted_in_file = sorted(ranges_in_file)
        if len(sorted_in_file) != len(set(sorted_in_file)):
            raise ValueError("duplicate identifier ranges")
        if any(
            cs < pe
            for (_, pe), (cs, _) in zip(sorted_in_file, sorted_in_file[1:])
        ):
            raise ValueError("overlapping identifier ranges")


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
            "instances",
            "generate_blocks",
            "typedefs",
            "struct_types",
            "struct_fields",
            "union_fields",
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
