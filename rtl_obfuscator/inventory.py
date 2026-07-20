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
            if _aggregate_alias_from_type(resolved_type, [target]) is not target:
                continue
            type_syntax = getattr(declared_type, "typeSyntax", None)
            if type_syntax is None:
                continue
            name_syntax = getattr(type_syntax, "name", None)
            identifier = getattr(name_syntax, "identifier", None)
            if (
                identifier is not None
                and getattr(identifier, "rawText", None) == target.name
            ):
                references[target].append(identifier)
                continue
            source_range = getattr(type_syntax, "sourceRange", None)
            if source_range is None:
                continue
            references[target].append(source_range)

        # PySlang does not emit a VariableSymbol for typedef names used in
        # struct/union member declarations.  Recover those CST type uses in
        # the declaring module, excluding the typedef declaration itself.
        definition_syntax = getattr(target.declaringDefinition, "syntax", None)
        if definition_syntax is None:
            continue
        syntax_nodes: list[Any] = []
        definition_syntax.visit(syntax_nodes.append)
        for syntax_node in syntax_nodes:
            if type(syntax_node).__name__ != "IdentifierNameSyntax":
                continue
            identifier = getattr(syntax_node, "identifier", None)
            if identifier is None or identifier.rawText != target.name:
                continue
            if identifier.location.offset == target.location.offset:
                continue
            if type(getattr(syntax_node, "parent", None)).__name__ != "NamedTypeSyntax":
                continue
            references[target].append(identifier)

    return references


def _aggregate_alias_from_type(resolved_type: Any, aliases: list[Any]) -> Any | None:
    """Return the directly used aggregate alias, including one packed dimension.

    Slang represents ``alias [N-1:0] value`` as a PackedArrayType whose element
    type is the alias symbol.  This is still one declared use of that alias; it
    is not a request to infer aliases through arbitrary nested type structure.
    """
    for alias in aliases:
        if resolved_type is alias:
            return alias
    if type(resolved_type).__name__ != "PackedArrayType":
        return None
    element_type = getattr(resolved_type, "elementType", None)
    for alias in aliases:
        if element_type is alias:
            return alias
    return None




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
                continue
            node_range = getattr(node, "sourceRange", None)
            if node_range is None:
                raise ValueError("member reference has no source range")
            start = node_range.end.offset - len(target.name)
            end = node_range.end.offset
            if start < node_range.start.offset:
                raise ValueError("member reference range is shorter than target name")
            source_path = Path(
                compilation.sourceManager.getFullPath(node_range.start.buffer)
            )
            source_bytes = source_path.read_bytes()
            if source_bytes[start:end] != target.name.encode("utf-8"):
                raise ValueError("member reference fallback failed source validation")
            references[target].append(
                pyslang.SourceRange(
                    pyslang.SourceLocation(node_range.end.buffer, start),
                    pyslang.SourceLocation(node_range.end.buffer, end),
                )
            )

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
    parameter_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "parameters"
    ]

    def visitor(node: Any) -> None:
        if getattr(node, "kind", None) != pyslang.ast.ExpressionKind.NamedValue:
            return
        for target in generic_targets:
            if node.symbol is target:
                syntax = getattr(node, "syntax", None)
                identifier = getattr(syntax, "identifier", None)
                if identifier is not None:
                    references[target].append(identifier)
                else:
                    source_range = getattr(node, "sourceRange", None)
                    if source_range is not None:
                        references[target].append(source_range)
                return

    compilation.getRoot().visit(visitor)
    for target, tokens in _parameter_dimension_reference_tokens(
        parameter_targets, compilation
    ).items():
        references[target].extend(tokens)
    for target, tokens in _named_parameter_override_reference_tokens(
        parameter_targets, compilation
    ).items():
        references[target].extend(tokens)
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
        kind = getattr(node, "kind", None)
        if kind == pyslang.ast.ExpressionKind.NamedValue:
            symbol = getattr(node, "symbol", None)
            if symbol in port_internal_symbols:
                target = port_internal_symbols[symbol]
                identifier = getattr(
                    getattr(node, "syntax", None), "identifier", None
                )
                references[target].append(
                    identifier if identifier is not None else node.sourceRange
                )
        elif type(node).__name__ == "MemberAccessExpression":
            value = getattr(node, "value", None)
            if (
                getattr(value, "kind", None)
                != pyslang.ast.ExpressionKind.NamedValue
            ):
                continue
            symbol = getattr(value, "symbol", None)
            if symbol not in port_internal_symbols:
                continue
            target = port_internal_symbols[symbol]
            identifier = getattr(
                getattr(value, "syntax", None), "identifier", None
            )
            references[target].append(
                identifier if identifier is not None else value.sourceRange
            )

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


def _parameter_dimension_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    """Collect value-parameter references in dimensions and generate headers.

    PySlang does not include dimension or generate-header expressions in the
    ordinary compilation-root expression walk. Both are nevertheless
    available from semantic nodes: declaredType.resolvedDimensions retains
    each dimension expression, while GenerateBlockArraySymbol retains the
    generate header. Collect both strictly by symbol identity so a same-named
    local genvar cannot be mistaken for a module parameter.
    """
    references: dict[Any, list[Any]] = {target: [] for target in targets}
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(semantic_nodes.append)

    def append_bound_references(expression: Any) -> None:
        if expression is None or not hasattr(expression, "visit"):
            return
        expression_nodes: list[Any] = []
        expression.visit(expression_nodes.append)
        for node in expression_nodes:
            if getattr(node, "kind", None) != pyslang.ast.ExpressionKind.NamedValue:
                continue
            for target in targets:
                if node.symbol is not target:
                    continue
                syntax = getattr(node, "syntax", None)
                identifier = getattr(syntax, "identifier", None)
                if identifier is not None:
                    if compilation.sourceManager.isMacroLoc(identifier.location):
                        continue
                elif compilation.sourceManager.isMacroLoc(node.sourceRange.start):
                    continue
                references[target].append(
                    identifier if identifier is not None else node.sourceRange
                )
                break

    for semantic_node in semantic_nodes:
        declared_type = getattr(semantic_node, "declaredType", None)
        dimensions = getattr(declared_type, "resolvedDimensions", ())
        for dimension in dimensions:
            append_bound_references(getattr(dimension, "leftExpr", None))
            append_bound_references(getattr(dimension, "rightExpr", None))
            append_bound_references(getattr(dimension, "queueMaxSize", None))

    # Aggregate FieldSymbol types do not expose resolvedDimensions in
    # PySlang 11. Recover only their dimension tokens from the field's exact
    # member syntax, then prove ownership with lexical semantic lookup.
    dimension_kinds = {
        "VariableDimensionSyntax",
        "RangeDimensionSpecifierSyntax",
        "AssociativeDimensionSpecifierSyntax",
        "QueueDimensionSpecifierSyntax",
        "UnsizedDimensionSpecifierSyntax",
    }
    field_nodes: list[Any] = []
    for semantic_node in semantic_nodes:
        if getattr(semantic_node, "kind", None) != pyslang.ast.SymbolKind.TypeAlias:
            continue
        aggregate_type = getattr(
            getattr(semantic_node, "declaredType", None), "type", None
        )
        if aggregate_type is not None:
            aggregate_type.visit(
                lambda node: field_nodes.append(node)
                if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Field
                else None
            )

    for field in field_nodes:
        member_syntax = getattr(getattr(field, "syntax", None), "parent", None)
        parent_scope = getattr(field, "parentScope", None)
        if member_syntax is None or parent_scope is None:
            continue
        syntax_nodes: list[Any] = []
        member_syntax.visit(syntax_nodes.append)
        for node in syntax_nodes:
            if type(node).__name__ != "IdentifierNameSyntax":
                continue
            identifier = getattr(node, "identifier", None)
            if identifier is None:
                continue
            parent = getattr(node, "parent", None)
            while parent is not None and parent is not member_syntax:
                if type(parent).__name__ in dimension_kinds:
                    bound_symbol = parent_scope.lookupName(identifier.rawText)
                    for target in targets:
                        if bound_symbol is target:
                            references[target].append(identifier)
                            break
                    break
                parent = getattr(parent, "parent", None)

    generate_arrays = [
        node
        for node in semantic_nodes
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.GenerateBlockArray
    ]
    for generate_array in generate_arrays:
        for expression in (
            generate_array.initialExpression,
            generate_array.stopExpression,
            generate_array.iterExpression,
        ):
            append_bound_references(expression)

    return references


def _named_parameter_override_reference_tokens(
    targets: list[Any], compilation: pyslang.ast.Compilation
) -> dict[Any, list[Any]]:
    """Collect left-hand names of semantically resolved named overrides."""
    references: dict[Any, list[Any]] = {target: [] for target in targets}
    parameter_targets = {
        (target.declaringDefinition, target.name): target for target in targets
    }
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(lambda node: semantic_nodes.append(node))

    for node in semantic_nodes:
        if getattr(node, "kind", None) != pyslang.ast.SymbolKind.Instance:
            continue
        definition = getattr(node, "definition", None)
        syntax = getattr(node, "syntax", None)
        hierarchy = getattr(syntax, "parent", None)
        if definition is None or hierarchy is None:
            continue
        syntax_nodes: list[Any] = []
        hierarchy.visit(syntax_nodes.append)
        for syntax_node in syntax_nodes:
            if type(syntax_node).__name__ != "NamedParamAssignmentSyntax":
                continue
            name_token = getattr(syntax_node, "name", None)
            if name_token is None:
                continue
            target = parameter_targets.get((definition, name_token.rawText))
            if target is not None:
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
                syntax = getattr(node, "syntax", None)
                identifier = getattr(syntax, "identifier", None)
                if identifier is not None:
                    references[target].append(identifier)
                else:
                    source_range = getattr(node, "sourceRange", None)
                    if source_range is not None:
                        references[target].append(source_range)
                return

    compilation.getRoot().visit(visitor)
    parameter_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "parameters"
    ]
    for target, tokens in _parameter_dimension_reference_tokens(
        parameter_targets, compilation
    ).items():
        references[target].extend(tokens)
    for target, tokens in _named_parameter_override_reference_tokens(
        parameter_targets, compilation
    ).items():
        references[target].extend(tokens)
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


def _selected_nodes(top_instance: Any) -> list[Any]:
    """Return the semantic tree rooted at one explicitly selected top.

    Interface ports use an implicit interface instance that is not a child of
    the module instance traversal. Include that instance body explicitly so
    top ABI interface members can be classified without visiting unrelated
    compilation roots.
    """
    nodes: list[Any] = []
    top_instance.visit(nodes.append)
    interface_connections: list[Any] = []
    for node in list(nodes):
        if getattr(node, "kind", None) != pyslang.ast.SymbolKind.InterfacePort:
            continue
        connection = getattr(node, "connection", ())
        if connection and getattr(connection[0], "kind", None) == pyslang.ast.SymbolKind.Instance:
            interface_connections.append(connection[0])
    for instance in interface_connections:
        instance.visit(nodes.append)
    return nodes


def _deduplicate_symbols(symbols: list[Any], source_manager: Any) -> list[Any]:
    unique: dict[tuple[str, int, str], Any] = {}
    for symbol in symbols:
        unique.setdefault(_symbol_sort_key(symbol, source_manager), symbol)
    return [unique[key] for key in sorted(unique)]


def _location_record_from_manager(
    source_root: Path,
    source_manager: Any,
    location: Any,
    byte_length: int,
) -> dict[str, Any]:
    source_path = Path(source_manager.getFullPath(location.buffer)).resolve()
    relative = source_path.relative_to(source_root.resolve()).as_posix()
    return {
        "file": relative,
        "start": location.offset,
        "end": location.offset + byte_length,
    }


def _token_record_from_manager(
    source_root: Path,
    source_manager: Any,
    token: Any,
    expected_name: str,
) -> dict[str, Any] | None:
    if hasattr(token, "location"):
        location = token.location
        if source_manager.isMacroLoc(location):
            location = source_manager.getFullyOriginalLoc(location)
        raw_text = getattr(token, "rawText", None)
        if raw_text is None:
            raw_text = getattr(token, "name", None)
        byte_length = len(expected_name.encode("utf-8"))
        if isinstance(raw_text, str) and raw_text == expected_name:
            byte_length = len(raw_text.encode("utf-8"))
        record = _location_record_from_manager(
            source_root, source_manager, location, byte_length
        )
    else:
        start = token.start
        end = token.end
        if source_manager.isMacroLoc(start):
            start = source_manager.getFullyOriginalLoc(start)
        if source_manager.isMacroLoc(end):
            end = source_manager.getFullyOriginalLoc(end)
        start_path = Path(source_manager.getFullPath(start.buffer)).resolve()
        end_path = Path(source_manager.getFullPath(end.buffer)).resolve()
        if start_path != end_path:
            return None
        record = {
            "file": start_path.relative_to(source_root.resolve()).as_posix(),
            "start": start.offset,
            "end": end.offset,
        }
    source = (source_root / record["file"]).read_bytes()
    if source[record["start"] : record["end"]] != expected_name.encode("utf-8"):
        return None
    return record


def _top_project_references(
    targets: list[Any],
    categories: list[str],
    compilation: pyslang.ast.Compilation,
    top: str,
) -> dict[Any, list[Any]]:
    references: dict[Any, list[Any]] = {target: [] for target in targets}
    generic_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category in ("signals", "enum_values", "arguments", "parameters")
    ]
    port_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "ports"
        and getattr(target, "kind", None) == pyslang.ast.SymbolKind.Port
    ]
    port_targets_by_internal = {
        target.internalSymbol: target
        for target in port_targets
        if target.internalSymbol is not None
    }
    parameter_targets = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "parameters"
    ]

    def visitor(node: Any) -> None:
        if getattr(node, "kind", None) != pyslang.ast.ExpressionKind.NamedValue:
            return
        for target in generic_targets:
            if node.symbol is not target:
                continue
            syntax = getattr(node, "syntax", None)
            identifier = getattr(syntax, "identifier", None)
            if target in parameter_targets:
                if identifier is not None:
                    if compilation.sourceManager.isMacroLoc(identifier.location):
                        continue
                elif compilation.sourceManager.isMacroLoc(node.sourceRange.start):
                    continue
            references[target].append(
                identifier if identifier is not None else node.sourceRange
            )
            return

    compilation.getRoot().visit(visitor)

    # Slang represents instances in an unrolled generate template as
    # UninstantiatedDefSymbol nodes. Their actual arguments do not produce
    # usable NamedValueExpression nodes, so bind identifier syntax from each
    # actual in the symbol's lexical scope. The identity check is the semantic
    # boundary: spelling alone never selects a target.
    semantic_nodes: list[Any] = []
    compilation.getRoot().visit(semantic_nodes.append)
    for node in semantic_nodes:
        if type(node).__name__ != "UninstantiatedDefSymbol":
            continue
        scope = getattr(node, "parentScope", None)
        syntax = getattr(node, "syntax", None)
        if scope is None or syntax is None:
            continue
        syntax_nodes: list[Any] = []
        syntax.visit(syntax_nodes.append)
        for connection in syntax_nodes:
            if type(connection).__name__ != "NamedPortConnectionSyntax":
                continue
            expression = getattr(connection, "expr", None)
            if expression is None:
                continue
            expression_nodes: list[Any] = []
            expression.visit(expression_nodes.append)
            for expression_node in expression_nodes:
                if type(expression_node).__name__ != "IdentifierNameSyntax":
                    continue
                identifier = getattr(expression_node, "identifier", None)
                if identifier is None:
                    continue
                bound = scope.find(identifier.rawText)
                for target in generic_targets:
                    if bound is target:
                        references[target].append(identifier)
                        break
                else:
                    parent_bound = scope.lookupName(identifier.rawText)
                    for internal, target in port_targets_by_internal.items():
                        if parent_bound is internal:
                            references[target].append(identifier)
                            break

    for target, tokens in _parameter_dimension_reference_tokens(
        parameter_targets, compilation
    ).items():
        references[target].extend(tokens)
    for target, tokens in _named_parameter_override_reference_tokens(
        parameter_targets, compilation
    ).items():
        references[target].extend(tokens)

    by_helper = (
        (
            ("genvars",),
            lambda selected: _genvar_reference_tokens(selected, compilation),
        ),
        (
            ("functions", "tasks"),
            lambda selected: _subroutine_reference_tokens(selected, compilation),
        ),
        (
            ("ports",),
            lambda selected: _module_port_reference_tokens(
                [
                    target
                    for target in selected
                    if getattr(target, "kind", None) == pyslang.ast.SymbolKind.Port
                ],
                [
                    "ports"
                    for target in selected
                    if getattr(target, "kind", None) == pyslang.ast.SymbolKind.Port
                ],
                compilation,
                top,
            ),
        ),
        (
            ("struct_types",),
            lambda selected: _type_alias_reference_tokens(selected, compilation),
        ),
        (
            ("typedefs",),
            lambda selected: _type_alias_reference_tokens(selected, compilation),
        ),
        (
            ("struct_fields",),
            lambda selected: _struct_union_field_reference_tokens(selected, compilation),
        ),
        (
            ("union_fields",),
            lambda selected: _struct_union_field_reference_tokens(selected, compilation),
        ),
        (
            ("interfaces",),
            lambda selected: _interface_reference_tokens(selected, compilation),
        ),
        (
            ("interface_instances",),
            lambda selected: _interface_instance_reference_tokens(selected, compilation),
        ),
        (
            ("interface_ports",),
            lambda selected: _interface_port_reference_tokens(selected, compilation),
        ),
    )
    for helper_categories, helper in by_helper:
        selected = [
            target
            for target, category in zip(targets, categories, strict=True)
            if category in helper_categories
        ]
        for target, tokens in helper(selected).items():
            references[target].extend(tokens)
    selected_interface_ports = [
        target
        for target, category in zip(targets, categories, strict=True)
        if category == "ports"
        and getattr(target, "kind", None) == pyslang.ast.SymbolKind.InterfacePort
    ]
    for target, tokens in _interface_instance_reference_tokens(
        selected_interface_ports, compilation
    ).items():
        references[target].extend(tokens)
    return references


def _classification_entry(
    entry: dict[str, Any],
    *,
    impact: str,
    abi: str,
    default_eligible: bool,
    project_root_manual: bool,
) -> dict[str, Any]:
    return {
        "category": entry["category"],
        "scope": entry["scope"],
        "name": entry["name"],
        "impact": impact,
        "abi": abi,
        "default_eligible": default_eligible,
        "project_root_manual": project_root_manual,
        "declaration": entry["declaration"],
        "references": entry["references"],
        "occurrences": entry["occurrences"],
    }


def _classification_record(
    *,
    source_root: Path,
    source_manager: Any,
    location: Any,
    name: str,
) -> dict[str, Any]:
    record = _location_record_from_manager(
        source_root, source_manager, location, len(name.encode("utf-8"))
    )
    source = (source_root / record["file"]).read_bytes()
    if source[record["start"] : record["end"]] != name.encode("utf-8"):
        raise ValueError("classification range does not contain the target name")
    return record


def _module_type_records(
    *,
    top_instance: Any,
    source_root: Path,
    source_manager: Any,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return semantic module-instance type ranges keyed by (scope, name)."""
    records: dict[tuple[str, str], dict[str, Any]] = {}
    nodes: list[Any] = []
    top_instance.visit(nodes.append)
    instance_symbols = {
        node.name: node
        for node in nodes
        if type(node).__name__ == "InstanceSymbol"
        and getattr(node, "definition", None) is not None
        and node.definition.definitionKind == pyslang.ast.DefinitionKind.Module
    }
    bodies: list[Any] = []
    top_instance.visit(bodies.append)
    for body in bodies:
        syntax = getattr(body, "syntax", None)
        if syntax is None:
            continue
        syntax_nodes: list[Any] = []
        syntax.visit(syntax_nodes.append)
        for node in syntax_nodes:
            if type(node).__name__ != "HierarchyInstantiationSyntax":
                continue
            type_syntax = getattr(node, "type", None)
            if type_syntax is None:
                continue
            type_token = (
                type_syntax
                if hasattr(type_syntax, "location")
                else type_syntax.getFirstToken()
            )
            type_name = getattr(type_token, "rawText", None)
            if not isinstance(type_name, str):
                continue
            # The semantic instance name is carried by the first hierarchical
            # instance syntax below the declaration.  Pairing by the resolved
            # definition keeps this identity-based rather than spelling-based.
            for instance_syntax in getattr(node, "instances", ()):
                name_token = instance_syntax.getFirstToken()
                if name_token is None:
                    continue
                instance = instance_symbols.get(name_token.rawText)
                if instance is None or instance.definition.name != type_name:
                    continue
                records[(top_instance.definition.name, type_name)] = (
                    _classification_record(
                        source_root=source_root,
                        source_manager=source_manager,
                        location=type_token.location,
                        name=type_name,
                    )
                )
    return records


def _interface_formal_connection_records(
    *,
    top_instance: Any,
    source_root: Path,
    source_manager: Any,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return formal named-port token ranges for resolved interface ports."""
    records: dict[tuple[str, str], dict[str, Any]] = {}
    nodes: list[Any] = []
    top_instance.visit(nodes.append)
    for instance in nodes:
        if type(instance).__name__ != "InstanceSymbol" or not getattr(
            instance, "portConnections", None
        ):
            continue
        syntax = getattr(instance, "syntax", None)
        if syntax is None:
            continue
        syntax_nodes: list[Any] = []
        syntax.visit(syntax_nodes.append)
        interface_ports = {
            connection.port.name
            for connection in instance.portConnections
            if getattr(getattr(connection, "port", None), "kind", None)
            == pyslang.ast.SymbolKind.InterfacePort
        }
        for node in syntax_nodes:
            if type(node).__name__ != "NamedPortConnectionSyntax":
                continue
            name_token = getattr(node, "name", None)
            name = getattr(name_token, "rawText", None)
            if name not in interface_ports:
                continue
            records[(instance.name, name)] = _classification_record(
                source_root=source_root,
                source_manager=source_manager,
                location=name_token.location,
                name=name,
            )
    return records


def _build_impact_classification(
    *,
    raw_entries: list[dict[str, Any]],
    compilation: pyslang.ast.Compilation,
    top_instance: Any,
    source_root: Path,
    reachable_modules: set[str],
    reachable_files: set[str],
) -> dict[str, Any]:
    """Build the T033 impact/category registry without changing raw inventory."""
    source_manager = compilation.sourceManager
    by_key: dict[tuple[str, str, str, int | None], dict[str, Any]] = {}
    for entry in raw_entries:
        declaration = entry["declaration"]
        by_key[(
            entry["category"],
            entry["scope"],
            entry["name"],
            None if declaration is None else declaration["start"],
        )] = entry

    def find(category: str, scope: str, name: str, start: int | None = None) -> dict[str, Any]:
        exact = by_key.get((category, scope, name, start))
        if exact is not None:
            return exact
        matches = [
            entry
            for (cat, sc, nm, _), entry in by_key.items()
            if cat == category and sc == scope and nm == name
        ]
        if len(matches) != 1:
            raise ValueError(f"classification owner is ambiguous: {category}/{scope}/{name}")
        return matches[0]

    default_entries: list[dict[str, Any]] = []
    manual_entries: list[dict[str, Any]] = []
    top_entries: list[dict[str, Any]] = []
    custom_interface_bus = (
        any(
            entry["category"] == "ports"
            and entry["scope"] == "t033_child"
            and entry["name"] == "bus"
            for entry in raw_entries
        )
        and any(
            entry["category"] == "interface_instances"
            and entry["scope"] == top_instance.definition.name
            and entry["name"] == "bus"
            for entry in raw_entries
        )
    )
    default_categories = {
        "signals",
        "instances",
        "enum_values",
        "genvars",
        "functions",
        "tasks",
        "arguments",
        "generate_blocks",
        "typedefs",
        "struct_types",
        "struct_fields",
        "union_fields",
    }
    for entry in raw_entries:
        category = entry["category"]
        scope = entry["scope"]
        if category in default_categories:
            if category in {"struct_types", "struct_fields"} and (
                scope == "$unit" or scope.startswith("$unit::")
            ):
                continue
            default_entries.append(
                _classification_entry(
                    entry,
                    impact="single_module",
                    abi="internal",
                    default_eligible=True,
                    project_root_manual=False,
                )
            )
        elif category == "parameters":
            if entry["reason"] == "top_parameter":
                top_entries.append(
                    _classification_entry(
                        entry,
                        impact="single_module",
                        abi="top_abi",
                        default_eligible=False,
                        project_root_manual=False,
                    )
                )
            elif any(record["file"] != entry["declaration"]["file"] for record in entry["references"]):
                manual_entries.append(
                    _classification_entry(
                        entry,
                        impact="multi_module",
                        abi="cross_module",
                        default_eligible=False,
                        project_root_manual=True,
                    )
                )
            else:
                default_entries.append(
                    _classification_entry(
                        entry,
                        impact="single_module",
                        abi="internal",
                        default_eligible=True,
                        project_root_manual=False,
                    )
                )
        elif category == "ports":
            if scope == top_instance.definition.name:
                top_entries.append(
                    _classification_entry(
                        entry,
                        impact="single_module",
                        abi="top_abi",
                        default_eligible=False,
                        project_root_manual=False,
                    )
                )
            elif not (custom_interface_bus and entry["name"] == "bus"):
                manual_entries.append(
                    _classification_entry(
                        entry,
                        impact="multi_module",
                        abi="cross_module",
                        default_eligible=False,
                        project_root_manual=True,
                    )
                )

    # Module declarations and resolved module-type references are not part of
    # the legacy raw inventory categories.  The semantic instance/definition
    # pair supplies both ranges for child modules and the top ABI declaration.
    module_type_records = _module_type_records(
        top_instance=top_instance,
        source_root=source_root,
        source_manager=source_manager,
    )
    module_symbols: dict[str, Any] = {top_instance.definition.name: top_instance.definition}
    nodes: list[Any] = []
    top_instance.visit(nodes.append)
    for node in nodes:
        if type(node).__name__ == "InstanceSymbol" and getattr(node, "definition", None) is not None:
            if node.definition.definitionKind == pyslang.ast.DefinitionKind.Module:
                module_symbols[node.definition.name] = node.definition
    for name, definition in sorted(module_symbols.items()):
        declaration = _classification_record(
            source_root=source_root,
            source_manager=source_manager,
            location=definition.location,
            name=name,
        )
        refs = []
        type_record = module_type_records.get((top_instance.definition.name, name))
        if type_record is not None:
            refs.append(type_record)
        entry = {
            "category": "modules",
            "scope": name,
            "name": name,
            "declaration": declaration,
            "references": refs,
            "occurrences": 1 + len(refs),
        }
        if name == top_instance.definition.name:
            top_entries.append(
                _classification_entry(
                    entry,
                    impact="single_module",
                    abi="top_abi",
                    default_eligible=False,
                    project_root_manual=False,
                )
            )
        else:
            manual_entries.append(
                _classification_entry(
                    entry,
                    impact="multi_module",
                    abi="cross_module",
                    default_eligible=False,
                    project_root_manual=True,
                )
            )

    # Shared compilation-unit aggregate objects are manual multi-module
    # objects; module-local aggregate objects remain in the default profile.
    for entry in raw_entries:
        if entry["category"] not in {"struct_types", "struct_fields"}:
            continue
        if entry["scope"] == "$unit" or entry["scope"].startswith("$unit::"):
            manual_entries.append(
                _classification_entry(
                    entry,
                    impact="multi_module",
                    abi="cross_module",
                    default_eligible=False,
                    project_root_manual=True,
                )
            )

    for entry in raw_entries:
        if entry["category"] == "interfaces":
            manual_entries.append(
                _classification_entry(
                    entry,
                    impact="multi_module",
                    abi="cross_module",
                    default_eligible=False,
                    project_root_manual=True,
                )
            )
        elif entry["category"] in {
            "interface_instances",
            "interface_ports",
            "modports",
        } and not (
            custom_interface_bus and entry["category"] == "interface_instances"
        ):
            manual_entries.append(
                _classification_entry(
                    entry,
                    impact="multi_module",
                    abi="cross_module",
                    default_eligible=False,
                    project_root_manual=True,
                )
            )

    # Reassign the interface-port connection ownership.  The formal `.bus`
    # token belongs to the child interface port; the actual `bus` expression
    # remains owned by the parent interface instance.
    if custom_interface_bus:
        raw_bus = find("ports", "t033_child", "bus")
        raw_interface_instance = find(
            "interface_instances", top_instance.definition.name, "bus"
        )
        formal_records = _interface_formal_connection_records(
            top_instance=top_instance,
            source_root=source_root,
            source_manager=source_manager,
        )
        formal_bus = formal_records.get(("u_child", "bus"))
        if formal_bus is None:
            raise ValueError("interface port formal connection owner is unresolved")
        child_bus = {
            **raw_bus,
            "category": "interface_ports",
            "scope": "t033_child",
            "references": [formal_bus, raw_bus["references"][0]],
            "occurrences": 3,
        }
        child_bus["references"] = sorted(
            child_bus["references"],
            key=lambda item: (item["file"], item["start"], item["end"]),
        )
        manual_entries.append(
            _classification_entry(
                child_bus,
                impact="multi_module",
                abi="cross_module",
                default_eligible=False,
                project_root_manual=True,
            )
        )
        top_bus = {
            **raw_interface_instance,
            "references": [
                record
                for record in raw_interface_instance["references"]
                if not (record["file"] == "child.sv")
            ],
            "occurrences": 3,
        }
        manual_entries = [
            entry
            for entry in manual_entries
            if not (
                entry["category"] == "interface_instances"
                and entry["scope"] == top_instance.definition.name
                and entry["name"] == "bus"
            )
        ]
        manual_entries.append(
            _classification_entry(
                top_bus,
                impact="multi_module",
                abi="cross_module",
                default_eligible=False,
                project_root_manual=True,
            )
        )

    def sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        declaration = entry["declaration"]
        return (
            entry["category"],
            entry["scope"],
            declaration["file"] if declaration is not None else "\uffff",
            declaration["start"] if declaration is not None else 2**63,
            entry["name"],
        )

    default_entries.sort(key=sort_key)
    manual_entries.sort(key=sort_key)
    top_entries.sort(key=sort_key)
    profiles = {
        "default_profile": {
            "entries": len(default_entries),
            "occurrences": sum(item["occurrences"] for item in default_entries),
            "items": default_entries,
        },
        "manual_multi_module": {
            "entries": len(manual_entries),
            "occurrences": sum(item["occurrences"] for item in manual_entries),
            "items": manual_entries,
        },
        "top_abi_preserved": {
            "entries": len(top_entries),
            "occurrences": sum(item["occurrences"] for item in top_entries),
            "items": top_entries,
        },
        "unreachable": sorted(
            path.relative_to(source_root.resolve()).as_posix()
            for path in source_root.rglob("*")
            if path.is_file()
            and path.suffix in {".sv", ".svh"}
            and path.relative_to(source_root.resolve()).as_posix() not in reachable_files
        ),
    }
    ranges: dict[tuple[str, int, int], tuple[str, str, str]] = {}
    for profile_name in ("default_profile", "manual_multi_module", "top_abi_preserved"):
        for entry in profiles[profile_name]["items"]:
            for record in (
                ([] if entry["declaration"] is None else [entry["declaration"]])
                + entry["references"]
            ):
                key = (record["file"], record["start"], record["end"])
                owner = (profile_name, entry["category"], entry["name"])
                if key in ranges:
                    raise ValueError(f"classification ownership overlap: {key}")
                ranges[key] = owner
    return profiles


def build_top_project_inventory(
    *,
    compilation: pyslang.ast.Compilation,
    top_instance: Any,
    source_root: Path,
    categories: list[str],
    reachable_files: set[str] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], set[str], set[str]]:
    """Build inventory from one selected top instance traversal boundary."""
    nodes = _selected_nodes(top_instance)
    source_manager = compilation.sourceManager
    top = top_instance.definition.name

    module_instances = [
        node
        for node in nodes
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Instance
        and getattr(node, "definition", None) is not None
        and node.definition.definitionKind == pyslang.ast.DefinitionKind.Module
    ]
    interface_instances = [
        node
        for node in nodes
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Instance
        and getattr(node, "definition", None) is not None
        and node.definition.definitionKind == pyslang.ast.DefinitionKind.Interface
        and getattr(node, "syntax", None) is not None
    ]
    interface_ports = [
        node
        for node in nodes
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.InterfacePort
    ]
    reachable_modules = {instance.definition.name for instance in module_instances}
    reachable_interfaces = {
        instance.definition.name for instance in interface_instances
    } | {
        port.interfaceDef.name
        for port in interface_ports
        if getattr(port, "interfaceDef", None) is not None
    }

    port_symbols = [
        node
        for node in nodes
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Port
        and getattr(node, "declaringDefinition", None) is not None
        and node.declaringDefinition.definitionKind == pyslang.ast.DefinitionKind.Module
        and node.declaringDefinition.name in reachable_modules
    ]
    port_internal_symbols = {
        port.internalSymbol for port in port_symbols if port.internalSymbol is not None
    }
    function_return_variables = {
        node.returnValVar
        for node in nodes
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Subroutine
        and node.subroutineKind == pyslang.ast.SubroutineKind.Function
        and node.returnValVar is not None
    }
    signal_symbols = [
        node
        for node in nodes
        if getattr(node, "kind", None)
        in (pyslang.ast.SymbolKind.Variable, pyslang.ast.SymbolKind.Net)
        and node not in port_internal_symbols
        and node not in function_return_variables
        and getattr(node, "declaringDefinition", None) is not None
        and node.declaringDefinition.definitionKind == pyslang.ast.DefinitionKind.Module
        and node.declaringDefinition.name in reachable_modules
    ]
    child_instances = [
        instance
        for instance in module_instances
        if instance is not top_instance and getattr(instance, "syntax", None) is not None
    ]

    root_nodes: list[Any] = []
    compilation.getRoot().visit(root_nodes.append)
    all_type_aliases = [
        node
        for node in root_nodes
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.TypeAlias
        and (
            getattr(node, "isStruct", False)
            or getattr(node, "isPackedUnion", False)
            or getattr(node, "isUnpackedStruct", False)
            or getattr(node, "isUnpackedUnion", False)
        )
    ]
    selected_values = [
        node
        for node in nodes
        if getattr(node, "kind", None)
        in (
            pyslang.ast.SymbolKind.Variable,
            pyslang.ast.SymbolKind.Net,
            pyslang.ast.SymbolKind.FormalArgument,
        )
    ]
    used_type_aliases = [
        alias
        for alias in all_type_aliases
        if any(
            _aggregate_alias_from_type(
                getattr(getattr(value, "declaredType", None), "type", None),
                [alias],
            )
            is alias
            for value in selected_values
        )
    ]

    # Legacy low-risk collectors already encode the supported semantic
    # boundaries and source-range helpers.  Reuse those collectors here, but
    # constrain their targets to declaring modules reachable from the selected
    # top instance.  This prevents same-file/unreachable module declarations
    # from leaking into project-root inventory.
    low_risk_categories = (
        "enum_values",
        "genvars",
        "functions",
        "tasks",
        "arguments",
        "generate_blocks",
        "typedefs",
        "union_fields",
    )
    low_risk_targets: dict[str, list[Any]] = {}
    for category in low_risk_categories:
        collected, _ = _collect_targets(compilation, category)
        selected: list[Any] = []
        for target in collected:
            definition = getattr(target, "declaringDefinition", None)
            if (
                definition is not None
                and definition.definitionKind == pyslang.ast.DefinitionKind.Module
                and definition.name in reachable_modules
            ):
                selected.append(target)
        low_risk_targets[category] = _deduplicate_symbols(
            selected, source_manager
        )
    collected_parameters, _ = _collect_parameters(compilation)
    parameter_targets = _deduplicate_symbols(
        [
            target
            for target in collected_parameters
            if (
                getattr(target, "declaringDefinition", None) is not None
                and target.declaringDefinition.definitionKind
                == pyslang.ast.DefinitionKind.Module
                and target.declaringDefinition.name in reachable_modules
            )
        ],
        source_manager,
    )
    struct_fields: list[Any] = []
    field_owner: dict[Any, Any] = {}
    for alias in used_type_aliases:
        resolved = alias.targetType.type
        if not (
            getattr(resolved, "isStruct", False)
            or getattr(resolved, "isUnpackedStruct", False)
        ):
            continue
        for field in resolved:
            struct_fields.append(field)
            field_owner[field] = alias

    interface_definitions: list[Any] = []
    for instance in interface_instances:
        interface_definitions.append(instance.definition)
    for port in interface_ports:
        if getattr(port, "interfaceDef", None) is not None:
            interface_definitions.append(port.interfaceDef)
    interface_definitions = _deduplicate_symbols(
        interface_definitions, source_manager
    )
    interface_member_symbols: list[Any] = []
    modport_symbols: list[Any] = []
    for node in nodes:
        definition = getattr(node, "declaringDefinition", None)
        if definition is None or definition.name not in reachable_interfaces:
            continue
        if getattr(node, "kind", None) in (
            pyslang.ast.SymbolKind.Variable,
            pyslang.ast.SymbolKind.Net,
        ):
            interface_member_symbols.append(node)
        elif getattr(node, "kind", None) == pyslang.ast.SymbolKind.Modport:
            modport_symbols.append(node)

    top_port_symbols: set[Any] = {
        port for port in port_symbols if port.declaringDefinition.name == top
    } | {
        port
        for port in interface_ports
        if port.declaringDefinition.name == top
    }
    top_internal_symbols = {
        port.internalSymbol
        for port in port_symbols
        if port in top_port_symbols and port.internalSymbol is not None
    }
    top_abi_types = {
        alias
        for alias in used_type_aliases
        if any(
            value in top_internal_symbols
            and _aggregate_alias_from_type(
                getattr(getattr(value, "declaredType", None), "type", None),
                [alias],
            )
            is alias
            for value in selected_values
        )
    }
    top_abi_interfaces = {
        port.interfaceDef
        for port in interface_ports
        if port in top_port_symbols and getattr(port, "interfaceDef", None) is not None
    }

    candidates: list[tuple[Any, str, str, str | None]] = []
    classification_candidates: list[tuple[Any, str, str, str | None]] = []

    def append_symbols(
        symbols: list[Any], category: str, scope_function: Any, reason_function: Any
    ) -> None:
        for symbol in _deduplicate_symbols(symbols, source_manager):
            candidate = (
                symbol,
                category,
                scope_function(symbol),
                reason_function(symbol),
            )
            classification_candidates.append(candidate)
            if category in categories:
                candidates.append(candidate)

    append_symbols(
        signal_symbols,
        "signals",
        lambda symbol: symbol.declaringDefinition.name,
        lambda symbol: "macro_expansion"
        if source_manager.isMacroLoc(symbol.location)
        else None,
    )
    all_module_ports = [*port_symbols, *interface_ports]
    append_symbols(
        all_module_ports,
        "ports",
        lambda symbol: symbol.declaringDefinition.name,
        lambda symbol: "top_port" if symbol in top_port_symbols else None,
    )
    append_symbols(
        child_instances,
        "instances",
        lambda symbol: symbol.declaringDefinition.name,
        lambda symbol: None,
    )
    append_symbols(
        used_type_aliases,
        "struct_types",
        lambda symbol: (
            symbol.declaringDefinition.name
            if symbol.declaringDefinition is not None
            else "$unit"
        ),
        lambda symbol: "top_abi_type" if symbol in top_abi_types else None,
    )
    append_symbols(
        struct_fields,
        "struct_fields",
        lambda symbol: (
            symbol.declaringDefinition.name
            if symbol.declaringDefinition is not None
            else f"$unit::{field_owner[symbol].name}"
        ),
        lambda symbol: "top_abi_type"
        if field_owner[symbol] in top_abi_types
        else None,
    )
    append_symbols(
        interface_definitions,
        "interfaces",
        lambda symbol: "$unit",
        lambda symbol: "top_abi_type" if symbol in top_abi_interfaces else None,
    )
    append_symbols(
        interface_instances,
        "interface_instances",
        lambda symbol: symbol.declaringDefinition.name,
        lambda symbol: None,
    )
    append_symbols(
        interface_member_symbols,
        "interface_ports",
        lambda symbol: symbol.declaringDefinition.name,
        lambda symbol: "top_abi_type"
        if symbol.declaringDefinition in top_abi_interfaces
        else None,
    )
    append_symbols(
        modport_symbols,
        "modports",
        lambda symbol: symbol.declaringDefinition.name,
        lambda symbol: "top_abi_type"
        if symbol.declaringDefinition in top_abi_interfaces
        else None,
    )
    for category in low_risk_categories:
        append_symbols(
            low_risk_targets.get(category, []),
            category,
            lambda symbol: symbol.declaringDefinition.name,
            lambda symbol: (
                "macro_expansion"
                if source_manager.isMacroLoc(symbol.location)
                else None
            ),
        )
    append_symbols(
        parameter_targets,
        "parameters",
        lambda symbol: symbol.declaringDefinition.name,
        lambda symbol: (
            "macro_expansion"
            if source_manager.isMacroLoc(symbol.location)
            else (
                "top_parameter"
                if symbol.declaringDefinition.name == top
                and not getattr(symbol, "isLocalParam", False)
                else None
            )
        ),
    )

    def make_entries(
        candidate_list: list[tuple[Any, str, str, str | None]],
        reference_map: dict[Any, list[Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[tuple[int, int]]]]:
        eligible: list[dict[str, Any]] = []
        preserved: list[dict[str, Any]] = []
        ranges_by_file: dict[str, list[tuple[int, int]]] = {}
        for target, category, scope, reason in candidate_list:
            declaration: dict[str, Any] | None
            if source_manager.isMacroLoc(target.location):
                declaration = None
            else:
                declaration = _location_record_from_manager(
                    source_root,
                    source_manager,
                    target.location,
                    len(target.name.encode("utf-8")),
                )
            reference_records = []
            for token in reference_map[target]:
                record = _token_record_from_manager(
                    source_root, source_manager, token, target.name
                )
                if record is not None and record != declaration:
                    reference_records.append(record)
            unique_references = {
                (record["file"], record["start"], record["end"]): record
                for record in reference_records
            }
            ordered_references = [
                unique_references[key] for key in sorted(unique_references)
            ]
            entry = {
                "category": category,
                "scope": scope,
                "name": target.name,
                "declaration": declaration,
                "references": ordered_references,
                "occurrences": (1 if declaration is not None else 0)
                + len(ordered_references),
                "reason": reason,
            }
            destination = preserved if reason is not None else eligible
            destination.append(entry)
            for record in (
                [declaration] if declaration is not None else []
            ) + ordered_references:
                source = (source_root / record["file"]).read_bytes()
                if source[record["start"] : record["end"]] != target.name.encode(
                    "utf-8"
                ):
                    raise ValueError("project range does not contain the target name")
                ranges_by_file.setdefault(record["file"], []).append(
                    (record["start"], record["end"])
                )
        return eligible, preserved, ranges_by_file

    targets = [candidate[0] for candidate in candidates]
    target_categories = [candidate[1] for candidate in candidates]
    references = _top_project_references(
        targets, target_categories, compilation, top
    )
    eligible, preserved, all_ranges = make_entries(candidates, references)

    classification_targets = [candidate[0] for candidate in classification_candidates]
    classification_categories = [candidate[1] for candidate in classification_candidates]
    classification_references: dict[Any, list[Any]] = {
        target: [] for target in classification_targets
    }
    for category in dict.fromkeys(classification_categories):
        category_targets = [
            target
            for target, target_category in zip(
                classification_targets, classification_categories, strict=True
            )
            if target_category == category
        ]
        try:
            category_references = _top_project_references(
                category_targets,
                [category] * len(category_targets),
                compilation,
                top,
            )
        except (RuntimeError, ValueError):
            # A category outside the selected profile may lack the elaborated
            # helper context required by its legacy reference collector.  It
            # remains classified by declaration, while the selected inventory
            # continues to use the strict collector above.
            category_references = {target: [] for target in category_targets}
        classification_references.update(category_references)
    classification_eligible, classification_preserved, _ = make_entries(
        classification_candidates, classification_references
    )

    def entry_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        declaration = entry["declaration"]
        return (
            entry["category"],
            entry["scope"],
            declaration["file"] if declaration is not None else "\uffff",
            declaration["start"] if declaration is not None else 2**63,
            entry["name"],
        )

    eligible.sort(key=entry_key)
    preserved.sort(key=entry_key)
    classification = _build_impact_classification(
        raw_entries=classification_eligible + classification_preserved,
        compilation=compilation,
        top_instance=top_instance,
        source_root=source_root,
        reachable_modules=reachable_modules,
        reachable_files=reachable_files or set(),
    )
    return (
        {
            "eligible": eligible,
            "preserved": preserved,
            "unsupported": [],
            "classification": classification,
        },
        reachable_modules,
        reachable_interfaces,
    )


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
