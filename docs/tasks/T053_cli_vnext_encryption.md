# T053：single-file/filelist `encrypt-vnext` CLI wiring

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-J
- 前置任务：T052 `ACCEPTED`，交付提交 `c681cea`
- 设计基线：`c681cea`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 1–7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：CLI adapter；本任务通过 T052 生成 actual rewritten RTL
- Formal verification：必须在目标 unittest 内真实执行 compact actual gate 正例和固定功能负例

## 1. 单一目标

在现有 `python -m rtl_obfuscator.rewrite` CLI 中新增一个明确的 `encrypt-vnext` operation，
只负责把 T052 `run_vnext()` 接入 single-file 和 explicit filelist 用户入口：

```text
encrypt-vnext arguments
  -> from_single_file() | from_filelist()
  -> T052 run_vnext()
  -> gate directory + orchestration report + metrics report + stdout summary
```

本任务是 vNext 加密入口，不是 legacy 路径替换：

- 旧 `encrypt`、`decrypt`、`encrypt-project`、`decrypt-project` 行为保持不变；
- `encrypt-project --project-root` 保持 legacy 路径，不得由本任务接管；
- vNext 跨进程 restore/decrypt 留给 T054，不得把不可持久化的 Python 对象伪装成 decrypt 输入。

## 2. 固定 CLI 接口

新增子命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-vnext \
  (--input <file.sv> | --filelist <design.f>) \
  --source-root <dir> \
  [--include-dir <dir> ...] \
  [--define <NAME[=VALUE]> ...] \
  [--top <module>] \
  [--category signals|parameters|genvars ...] \
  [--abi-category parameters ...] \
  [--encryption-rate <rate>] \
  [--name-length <int>] \
  --output-dir <gate-dir> \
  --map <orchestration-report.json> \
  --metrics <metrics.json>
```

固定参数语义：

- `--input` 与 `--filelist` 必须二选一；不能同时提供或同时省略；
- `--source-root` 对两种入口都必填；
- `--top` 可选，由 T039/T052 SourceSet 语义处理；
- `--include-dir` 和 `--define` 直接传给现有 SourceSet adapter；
- `--category` 默认 `signals parameters genvars`，只接受这三个 canonical category；
- `--abi-category` 默认空，只接受 `parameters`，并由 RewritePolicy 校验 top/closed-world；
- `--encryption-rate` 可省略；省略走 T052 no-rate，提供后走 T052 rate path；
- `--name-length` 默认 20，必须满足 T045 NameFactory 合同；
- `--output-dir`、`--map`、`--metrics` 必须不存在，父目录必须存在，且不得位于 source root 内或
  彼此重叠；
- 不新增 `--debug`、`--file-map-dir`、`--project-root` 或 legacy mapping version 参数。

## 3. 输出合同

成功时：

1. `--output-dir` 是 T052 actual gate directory，包含 canonical `design.f` 和全部 physical files；
2. `--map` 是 `OrchestrationVNext.to_report()` 的完整 JSON，顶层 format 固定为
   `rtl-obfuscation.orchestration-vnext`；
3. `--metrics` 是 `report["metrics"]` 的 T048 verified JSON，顶层 format 固定为
   `rtl-obfuscation.metrics-vnext`；
4. stdout 是固定 portable summary：

```json
{
  "format": "rtl-obfuscation.cli-vnext",
  "schema_version": 1,
  "state": "restored",
  "summary": { ...OrchestrationVNext.summary... }
}
```

stdout、mapping report 和 metrics report 不得出现绝对路径、TemporaryDirectory、gate_dir 或
restore_dir；JSON 使用 UTF-8、稳定字段顺序和原子写出。

CLI 内部必须为 T052 提供一个临时 restore 目录并完成 restore/metrics audit；临时 restore 目录
不作为用户输出发布，成功后清理。失败时不得留下 gate、map 或 metrics 任一成功产物。

## 4. 固定实现边界

### 4.1 single-file

`--input` 通过 `from_single_file(source_file, source_root, include_dirs, defines, top)` 建立
SourceSet，再调用 T052 `run_vnext()`。不允许直接调用 legacy `inventory._build_inventory()`、
`_encrypt()` 或 `_rate_selection()`。

### 4.2 explicit filelist

`--filelist` 通过 `from_filelist(filelist, source_root, include_dirs, defines, top)` 建立 SourceSet，
保持 filelist 原始顺序，再调用同一 T052 `run_vnext()`。不允许调用旧 `_encrypt_filelist_project()`。

### 4.3 project-root 与 decrypt

`encrypt-vnext` 不接受 `--project-root`。旧 `encrypt-project --project-root`、旧 `decrypt` 和旧
`decrypt-project` 必须继续走原有分派；测试必须确认 vNext 入口不会调用这些 legacy helper。

vNext `--map` 是 orchestration report，不是 legacy mapping v1/v2/v3/v4；本任务不得让旧 decrypt
误读该文件。跨进程 vNext restore/decrypt 的 report loader 和 CLI 属于 T054。

## 5. 原子发布与失败边界

实现可以复用 `project._write_json_atomic()` 和既有发布工具，但必须满足：

- 先在临时 staging root 中运行 T052、写 gate、map 和 metrics；
- 所有对象审计、JSON 序列化和 readback 校验成功后再发布三个输出；
- 目标路径已存在、父目录不存在、路径重叠、T052 失败、JSON 写入失败或发布失败时，清理 staging
  和所有本次已发布产物；
- 不覆盖用户已有文件或目录；
- 不吞掉 `OrchestrationVNextError`、`RewriteVNextError`、`MetricsVNextError` 或 rate 错误后继续成功。

稳定 CLI 失败输出必须为 stderr 的 `error: <stable-code>`，退出码非零；非法输入不得产生部分 gate。

## 6. 稳定错误码

| condition | expected code |
| --- | --- |
| input/filelist/source-root/top/category 参数非法 | `CLI_VNEXT_INPUT_INVALID` |
| 输出路径已存在、重叠或无法发布 | `CLI_VNEXT_OUTPUT_INVALID` |
| T052 orchestration、gate、restore 或 audit 失败 | `CLI_VNEXT_ORCHESTRATION_INVALID` |
| rate 参数非法 | `CLI_VNEXT_RATE_INVALID` |
| JSON 序列化、readback 或原子发布失败 | `CLI_VNEXT_IO_ERROR` |

错误字符串必须以对应 code 开头；不得暴露本机绝对路径作为机器可依赖的错误字段。

## 7. 明确不包含

- 不修改旧 `encrypt`、`decrypt`、`encrypt-project`、`decrypt-project` 的业务实现；
- 不接入 project-root，不修改 `from_project_root()` 或 R4 行为；
- 不实现 vNext decrypt/restore loader；
- 不新增 mapping v1/v2/v3/v4 写入或兼容分派；
- 不修改 T052 `orchestration_vnext.py`、任何 T039–T051 core module、Formal 脚本或 fixture；
- 不删除 legacy 测试、脚本或 inventory/rewrite/decrypt；
- 不运行 RISC-V-Vector Formal；
- 不创建 T054，不执行 git add、commit 或 push。

## 8. 允许修改的文件

- `rtl_obfuscator/rewrite.py`：新增 `encrypt-vnext` parser/dispatch 和 CLI adapter；
- `tests/test_cli_vnext_encryption.py`：single/filelist CLI、输出、失败边界和 compact Formal 正负例；
- `README.md`：记录 `encrypt-vnext` 用法、输出格式和 vNext decrypt 尚未支持的边界；
- `docs/tasks/T053_cli_vnext_encryption.md`：状态、执行记录和主 Agent 验收记录。

需要修改允许列表外文件时，子 Agent 必须先记录偏差并停止，不得自行扩大范围。

## 9. 固定输入与测试 oracle

只读复用 T043/T052 compact fixture：

```text
tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv
```

目标测试必须覆盖：

1. single-file no-rate CLI actual gate、orchestration report、metrics report 和 stdout summary；
2. explicit filelist rate=`0.35` CLI actual selected gate、restore audit 和 report；
3. single/filelist normalized output、deterministic JSON、portable paths；
4. 非法输入、非法 rate、output overlap/existing、T052 failure、JSON/publish failure 的 fail-closed；
5. `encrypt-vnext` 不调用 legacy encrypt/project/decrypt/rate helper；
6. actual selected gate Formal 正例和只插入一个 ASCII `~` 的功能负例；
7. 旧 `encrypt-project --project-root` 和旧 decrypt 分派未被本任务改变。

Formal 正例必须使用 actual CLI gate、gold `design.f`、top=`parameter_top`、seq=`5`，JSON 必须包含
`formal_equivalence=pass`；负例 strict compile 仍为 0/0，Formal 非 0，并包含 `unproven` 和
`equiv_status -assert`。不得使用 identity comparison、复制 gold 或先 restore 后 Formal。

## 10. 目标验收命令

唯一验收命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_cli_vnext_encryption -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py tests/test_cli_vnext_encryption.py
git diff --check HEAD
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T053_cli_vnext_encryption.md
```

第一个 unittest 命令内部必须真实执行 actual CLI selected gate 的 Formal 正例和固定功能负例；不得
运行 RISC Formal、blanket discovery 或历史全量 acceptance。

## 11. 子 Agent执行记录

```text
status: READY_FOR_REVIEW
starting_head: 6b2d76549f9c566bbd8a535c18c5654f5a6c1d8f
start_time: 2026-07-24T10:33:40+08:00
starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 5]`; no other status entries
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_cli_vnext_encryption -v`
baseline_result: `ModuleNotFoundError: No module named 'tests.test_cli_vnext_encryption'`; Ran 1 test in 0.000s, FAILED, exit_code=1
allowed_files: rtl_obfuscator/rewrite.py; tests/test_cli_vnext_encryption.py; README.md; docs/tasks/T053_cli_vnext_encryption.md
changed_files: rtl_obfuscator/rewrite.py; tests/test_cli_vnext_encryption.py; README.md; docs/tasks/T053_cli_vnext_encryption.md
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_cli_vnext_encryption -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py tests/test_cli_vnext_encryption.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T053_cli_vnext_encryption.md`
results: unittest printed five named tests, `Ran 5 tests in 0.857s`, `OK`, exit_code=0; py_compile produced no stdout/stderr, exit_code=0; `git diff --check HEAD` produced no stdout/stderr, exit_code=0; final status guard matched `- 状态：READY_FOR_REVIEW`, exit_code=0
single_no_rate: actual CLI single-file `single.sv` no-rate path produced a gate directory, orchestration report format `rtl-obfuscation.orchestration-vnext`, verified metrics format `rtl-obfuscation.metrics-vnext`, and stdout format `rtl-obfuscation.cli-vnext`; stdout summary matched the orchestration summary, JSON readback was byte-stable, restore/metrics audit completed in the temporary restore directory, and no restore directory was published
filelist_rate: actual CLI `design.f`/`parameter_top` rate path with `encryption_rate=0.35` produced the selected gate and rate metrics; strict compile remained 0/0, T052 restore was byte-identical, metrics state was `verified`, plaintext leakage was 0.0, effective coverage was 1.0, and all reports were portable
output_and_error_boundaries: output directory, map, and metrics paths require absent targets, existing parents, no source-root overlap, and no mutual overlap; staged gate/report/metrics publication is atomic with rollback; invalid input and rate returned `CLI_VNEXT_INPUT_INVALID`/`CLI_VNEXT_RATE_INVALID`, existing output returned `CLI_VNEXT_OUTPUT_INVALID`, forced T052 failure returned `CLI_VNEXT_ORCHESTRATION_INVALID`, forced JSON failure returned `CLI_VNEXT_IO_ERROR`, and no gate/map/metrics artifacts remained after failure
legacy_blocking: PASS; vNext execution was tested with legacy encrypt, encrypt-project, decrypt, and decrypt-project helpers patched to fail; none was called. Existing legacy parser/dispatch branches were left unchanged, and no project-root or vNext decrypt loader was added
formal_positive: PASS; unittest invoked `python scripts/formal_equivalence.py --gold-filelist tests/fixtures/refactor_symbol_graph_parameters/design.f --gold-root tests/fixtures/refactor_symbol_graph_parameters --gate-filelist <actual_cli_gate>/design.f --gate-root <actual_cli_gate> --top parameter_top --seq 5`; exit_code=0 and final JSON contained `formal_equivalence=pass`, `top=parameter_top`, `seq=5`
formal_negative: PASS; unittest copied only the actual CLI selected gate, inserted one ASCII `~` after the unique `assign data_o = `, verified negative strict compile catalog/top-overlay 0/0, and invoked the same Formal command against the negative gate; exit_code was non-zero and output contained `unproven` and `equiv_status -assert`
formal_verification: PASS; this task produces actual rewritten RTL and the required compact actual-CLI-gate Formal positive and functional negative both passed their expected assertions
deviations_or_blockers: none
boundaries: project-root, vNext decrypt/restore loader, legacy cleanup, RISC Formal, fixture changes, and CLI options outside the frozen T053 interface remain intentionally uncovered
review_request: READY_FOR_REVIEW; Main Agent may independently rerun the four commands in section 10
```

## 12. READY_FOR_REVIEW 条件

- 状态严格为 `READY_FOR_REVIEW`，精确状态守卫通过；
- unittest、py_compile、`git diff --check HEAD` 全部通过；
- single/filelist `encrypt-vnext` 均生成 actual gate、portable map/metrics 和正确 stdout summary；
- no-rate/rate output、restore audit、deterministic JSON 和 failure cleanup 全部通过；
- actual selected gate Formal 正例通过，固定功能负例按预期失败；
- project-root、旧 decrypt、legacy helper 和 T052 core 均未被本任务接管或修改；
- 只修改本合同第 8 节列出的四个文件；
- 子 Agent 不得设置 `ACCEPTED`、创建 T054、commit 或 push。

## 13. 主 Agent验收边界

主 Agent只独立复跑第 10 节四条命令，审查 actual CLI gate、portable reports、原子发布/清理、旧
分派未改变和 Formal 正负例；全部通过后写本节验收记录并设置 `ACCEPTED`。不增加 legacy、RISC、
全量回归、project-root 或隐藏 probe。

## 13.1 主 Agent独立验收记录（2026-07-24）

```text
review_head: 6b2d76549f9c566bbd8a535c18c5654f5a6c1d8f
review_worktree: T053 four allowed files only; no unrelated paths
unittest: `conda run -n rtl_obfuscation python -m unittest tests.test_cli_vnext_encryption -v` -> 5 tests, OK, exit_code=0
py_compile: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py tests/test_cli_vnext_encryption.py` -> exit_code=0
diff_check: `git diff --check HEAD` -> clean, exit_code=0
status_guard: `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T053_cli_vnext_encryption.md` -> matched before ACCEPTED update, exit_code=0
formal: unittest independently exercised the actual CLI filelist rate gate; positive Formal passed with `formal_equivalence=pass`; one-byte `~` negative retained strict compile 0/0 and failed Formal with `unproven` and `equiv_status -assert`
scope_review: single/filelist outputs, portable orchestration/metrics reports, atomic cleanup, legacy helper blocking, and unchanged old dispatch reviewed; no project-root, vNext decrypt loader, fixture, or RISC Formal changes
decision: ACCEPTED
```

## 14. 主 Agent合同冻结记录（2026-07-24）

```text
status: READY
baseline_commit: c681cea
decision: T052 accepted; expose the first explicit single/filelist vNext encryption CLI before persistent vNext restore
inputs: T039 SourceSet adapters + T052 orchestration service
oracle: encrypt-vnext single/filelist actual gate; portable orchestration/metrics outputs; atomic failure cleanup; compact Formal +/-
formal_verification: required because the CLI produces actual rewritten RTL
forbidden: legacy command replacement, vNext decrypt loader, project-root, mapping compatibility, fixture edits, T054 creation
```
