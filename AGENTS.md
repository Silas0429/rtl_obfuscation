# Project instructions

## Tool environment

- The project toolchain is provided by the Conda environment named `rtl_obfuscation`.
- Run all Python, parser, HDL, lint, compile, and test commands through this environment.
- For non-interactive commands, prefer `conda run -n rtl_obfuscation <command>` so the selected environment is explicit and reproducible.
- Do not use packages or EDA binaries from the Conda `base` environment or the system installation when a project command is available in `rtl_obfuscation`.
- The environment currently provides Pyverilog, Verible, Icarus Verilog, PySlang, and Yosys.

Examples:

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_variable_rewrite -v
conda run -n rtl_obfuscation iverilog -g2012 -t null design.sv
conda run -n rtl_obfuscation verible-verilog-syntax design.sv
conda run -n rtl_obfuscation yosys -V
```

- The current environment does not provide `pytest`; the repository test suite uses Python's built-in `unittest` runner shown above.

## RTL language scope

- SystemVerilog is the only target RTL language for this project.
- New RTL samples and fixtures must use the `.sv` extension and SystemVerilog syntax.
- Verilog-only behavior may be studied for compatibility, but it must not drive the product design or acceptance criteria.

## Development approach

- Implement the project incrementally, beginning with the smallest verifiable step.
- Do not introduce a larger framework, abstraction, or dependency until the current step demonstrates that it is needed.
- Validate each step before starting the next one.

## Renaming implementation sources of truth

- `docs/systemverilog_renaming_table.md` defines the only renaming categories in scope.
- `README.md` defines the current user workflow, implementation overview, and delivered capability boundaries.
- `docs/formal_verification.md` defines the mandatory Yosys equivalence flow for rewritten RTL.
- `docs/future_work.md` records unsupported behavior and possible future expansion; it does not authorize implementation.
- `docs/tasks/README.md` defines the mandatory task status workflow.
- `docs/three_mode_refactor_plan.md` defines the approved R0–R5 replacement architecture.
- `docs/refactor_subagent_protocol.md` defines the mandatory sub-agent and simplified acceptance
  rules for R0–R5.
- Implementation work must have exactly one active `docs/tasks/TNNN_*.md` task contract.
- Do not implement a renaming category or behavior that is not authorized by the active task contract.

## Main Agent role

- The Main Agent owns requirements, architecture, task boundaries, expected input/output, and acceptance commands.
- The Main Agent prepares one small task at a time and sets it to `READY` only after the output is objectively checkable.
- The Main Agent validates delivered behavior with the task's black-box commands before setting it to `ACCEPTED`.
- For every task that produces rewritten RTL, the Main Agent must independently rerun the task's required `scripts/formal_equivalence.py` flow and require a passing JSON result. RISC-V-Vector Formal is excluded from routine acceptance and full-regression runs; routine test commands must omit `tests.test_risc_v_vector_project_root` and must not use a blanket discovery command that invokes it. Run its `formal-view`/`formal-align`/Yosys flow only when the active task contract is a dedicated RISC-V-Vector acceptance task that explicitly requires it.
- The Main Agent creates the next task only after the current task is accepted.

## Sub-agent role and documentation duty

- The sub-agent implements and self-tests only the active task.
- During R0–R5, the sub-agent must follow `docs/refactor_subagent_protocol.md` and run only the
  acceptance row selected by the active task; blanket discovery and historical acceptance drivers
  are not default requirements.
- Before editing code, the sub-agent must change the task status from `READY` to `IN_PROGRESS` and update its execution record.
- If an assumption, API difference, or boundary issue appears, the sub-agent must document it in the task before continuing and must not expand scope on its own.
- Before requesting review, the sub-agent must record changed files, exact commands, actual outputs, and uncovered boundaries, then set the task to `READY_FOR_REVIEW`.
- For tasks that produce rewritten RTL, the sub-agent must run the task contract's Yosys flow in `docs/formal_verification.md` and record the exact gold, gate, top, command, exit code, and JSON result. The sub-agent must not run RISC-V-Vector Formal during routine work unless the active task contract explicitly defines a dedicated RISC-V-Vector acceptance flow.
- For mapping-only or source-range-only tasks, the sub-agent must record formal verification as `N/A` with the reason; it must not run an identity comparison and call that evidence of transformed RTL correctness.
- A task with rewritten RTL and a failed, skipped, or unsupported formal check cannot be set to `READY_FOR_REVIEW`.
- The sub-agent must not set a task to `ACCEPTED`; that status belongs to the Main Agent.
- The sub-agent must not modify RTL fixtures or planning documents unless the active task explicitly allows it.
- Obsolete tests or scripts may be deleted only by an active cleanup task that lists their paths and
  replacement coverage; an unrelated implementation task must not remove them.

## Git workflow

- This project must be managed with Git.
- The sub-agent does not commit or push. It stops at `READY_FOR_REVIEW` after documenting its changes and evidence.
- After the Main Agent independently validates a task and marks it `ACCEPTED`, the Main Agent reviews `git status` and the staged diff, then runs:

```sh
git add .
git commit -m "[TYPE] concise description"
git push
```

- Do not commit failing or unaccepted task work.
- Do not amend, rebase, force-push, or rewrite history unless the user explicitly requests it.
- A push failure must be reported; it must not be described as a successful delivery.

Allowed commit prefixes:

| Prefix | Use |
| --- | --- |
| `[FEAT]` | New feature, capability, command, API, or module |
| `[FIX]` | Bug fix or behavior correction |
| `[REFACTOR]` | Structural change without behavior change |
| `[PERF]` | Performance improvement |
| `[DOCS]` | Documentation-only change |
| `[TEST]` | Test addition or test modification |
| `[CHORE]` | Build, tooling, or other non-business maintenance |
| `[STYLE]` | Formatting, whitespace, or naming-only change |

- Use one prefix per commit. For multiple closely related items, use a concise numbered description such as `[FEAT] 1. Add source ranges; 2. Preserve inventory output`.
