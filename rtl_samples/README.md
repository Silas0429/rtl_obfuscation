# RTL syntax samples

This directory contains eleven independent SystemVerilog RTL syntax samples
for parser and signal-renaming experiments. The examples progress from simple
continuous assignments to a finite-state machine. Each numbered file has one
documented top module and at least one internal signal. Sample 06 also contains
a child module to exercise instance and named-port handling.

| No. | File | Top module | Main syntax covered | Language |
| ---: | --- | --- | --- | --- |
| 01 | `01_continuous_assign.sv` | `sample01_continuous_assign` | `logic`, scalar ports, continuous assignment | SystemVerilog |
| 02 | `02_vector_operations.sv` | `sample02_vector_operations` | Packed vector, bit/part select, concatenation | SystemVerilog |
| 03 | `03_combinational_always.sv` | `sample03_combinational_always` | `always_comb`, `if/else`, procedural assignment | SystemVerilog |
| 04 | `04_sequential_counter.sv` | `sample04_sequential_counter` | `parameter int`, `always_ff`, nonblocking assignment | SystemVerilog |
| 05 | `05_case_statement.sv` | `sample05_case_statement` | Typed `localparam`, combinational `case` | SystemVerilog |
| 06 | `06_module_instance.sv` | `sample06_module_instance` | Child module, instance, named port connection | SystemVerilog |
| 07 | `07_generate_loop.sv` | `sample07_generate_loop` | Typed parameter, `genvar`, named generate block | SystemVerilog |
| 08 | `08_memory_array.sv` | `sample08_memory_array` | Unpacked memory, indexed read/write | SystemVerilog |
| 09 | `09_function_call.sv` | `sample09_function_call` | Automatic function, typed argument, local loop variable | SystemVerilog |
| 10 | `10_systemverilog_fsm.sv` | `sample10_systemverilog_fsm` | Enum, `always_comb`, `always_ff`, asynchronous reset | SystemVerilog |
| 11 | `11_supported_obfuscation.sv` | `sample11_supported_obfuscation` | All 13 single-file categories: signals, parameters, enum values, genvar, function, task, arguments, instance, generate block label, typedef, struct/union types and fields | SystemVerilog |

The combined sample exercises all thirteen categories included by
`--category all`: signals, parameters, enum values, genvars, functions, tasks,
arguments, instances, generate block labels, typedefs, struct types, struct
fields, and union fields. A one-pass `--category all` run on sample 11 produces
33 mapping entries and 90 modified tokens.

## File list

`filelist.f` uses paths relative to this directory. Tools invoked elsewhere
should either change into `rtl_samples` first or add that directory prefix.

All samples intentionally use SystemVerilog syntax. A Verilog-only parser may
reject some or all of them; that rejection should be recorded as an unsupported
syntax result rather than hidden.

## Syntax check

PySlang is the primary frontend. Run this check from the sample directory in a
Python environment where `pyslang` is installed:

```sh
python -c 'from pathlib import Path; import pyslang; files=[str(path) for path in sorted(Path(".").glob("*.sv"))]; tree=pyslang.syntax.SyntaxTree.fromFiles(files); print(f"PySlang parsed {len(files)} files; diagnostics={len(tree.diagnostics)}"); raise SystemExit(bool(tree.diagnostics))'
```

Verible and Icarus Verilog can be installed for additional syntax checks, but
they are not the semantic source used by the rewriter.

These files are syntax fixtures only. They do not include testbenches or any
obfuscation implementation.
