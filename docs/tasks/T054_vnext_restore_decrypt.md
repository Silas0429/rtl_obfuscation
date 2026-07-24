# T054：vNext report 持久化 restore/decrypt adapter

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-K
- 前置任务：T053 `ACCEPTED`，交付提交 `ef48c9b`
- 设计基线：`ef48c9b`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 1–7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：持久化 adapter；本任务只恢复已有 T053 actual gate，不生成新的 rewritten RTL
- Formal verification：`N/A`；本任务不生成新的 rewritten RTL，T053 actual gate 的 Formal 证据不被冒充为本任务 Formal

## 1. 单一目标

在现有 `python -m rtl_obfuscator.rewrite` CLI 中新增明确的 `decrypt-vnext` operation，消费
T053 产生的 orchestration report 和 actual gate，在新的 Python 进程中重建并校验持久化执行
envelope，恢复原始 physical files，并输出 byte-identical restore report。

本任务解决的是跨进程持久化恢复，不是重新加密或旧路径兼容：

- 不调用 T052 `run_vnext()`、T050 gate writer、rate selector 或随机命名器重新生成 gate；
- 不读取 legacy mapping v1/v2/v3/v4，不调用旧 `_decrypt()`/`_decrypt_project()`；
- 不修改 source、gate 或输入 report；任何 report、source 或 gate 不一致都必须 fail-closed；
- R4 project-root、旧 decrypt 替换和其他 CLI 兼容仍不属于本任务。

## 2. 固定 CLI 接口

新增子命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-vnext \
  --map <orchestration-report.json> \
  --gate-dir <actual-gate-dir> \
  --source-root <original-source-root> \
  --output-dir <restore-dir> \
  --report <restore-report.json>
```

固定参数语义：

- `--map` 必须是 T053 `rtl-obfuscation.orchestration-vnext` JSON，作为输入可存在；
- `--gate-dir` 必须是 T053 actual gate，包含 canonical `design.f` 和 report 中的 physical files；
- `--source-root` 必须是原始 source root，供 SourceSet、semantic catalog、SymbolGraph 和 input
  manifest 重新校验；不得从 report 中伪造或恢复本机绝对路径；
- `--output-dir` 和 `--report` 必须不存在，父目录必须存在，且不得与 source-root、gate-dir、map
  或彼此重叠；不得覆盖已有用户文件；
- 不接受 `--project-root`、`--input`、`--filelist`、legacy mapping version 或 debug 参数；
- `decrypt-vnext` 与旧 `decrypt`/`decrypt-project` 必须是独立分派。

## 3. 持久化输入校验与重建边界

新增 `rtl_obfuscator/restore_vnext.py` 作为 adapter，职责限定为加载、校验、重建和恢复：

1. 以 UTF-8 读取 `--map`，严格校验顶层 format=`rtl-obfuscation.orchestration-vnext`、
   schema=`1`、state=`restored`，以及 mapping、mapping_execution、metrics 和可选 rate_metrics
   的嵌套 format/state/schema；禁止绝对路径、private path key、NaN 和未知的执行状态；
2. 以 report 的 portable `source_set` 字段和用户提供的 `source-root` 构造 SourceSet，重新运行
   已验收的 SourceCatalog、SymbolGraph 和 RewritePolicy；`origin` 只能是 `single-file` 或
   `filelist`，文件顺序、include dirs、defines、top、top closure 和 compile order 必须与 report
   一致，否则返回稳定错误；
3. 使用 report 中 `mapping.records` 的 `symbol_id`、`renamed_name` 和所有 range 作为唯一持久化
   mapping 来源，重建 MappingVNext 并与重建的 graph/policy、input manifest 做逐字段校验；不得
   重新生成名称或使用随机/fixture-specific fallback；
4. 对 rate report，校验 top-level 原始 mapping、`mapping_execution.mapping` 的 effective mapping
   以及 `rate_metrics` 的 nested mapping/metrics 一致；`rate_unselected` 只能出现在有效执行
   mapping 中，不能被恢复逻辑静默改回 rename；
5. 从 `mapping_execution` report 重建 `RewriteExecution`、AppliedEdit、gate manifest 和
   CompileEvidence，调用既有 T046 `restore_gate_vnext()`；恢复结果必须通过 T047 envelope 校验，
   并使用 T048 metrics adapter 重算 metrics 后与持久化 report 完全一致；
6. 只在所有校验完成后发布 restore directory 和 restore report。失败时不得留下任何本次输出。

允许使用 dataclass `replace()` 和现有 vNext 校验函数，但不得把 JSON 直接当作可信执行对象，
不得通过 identity comparison、复制 gold、跳过 gate manifest 或跳过 range 校验来“恢复成功”。

## 4. 输出合同

### 4.1 Restore directory

`--output-dir` 只包含 report `mapping_execution.restored_manifest` 中列出的 physical files，文件
相对路径和内容必须与原始 source root 的 input manifest byte-identical；不额外发布 `design.f`、
map 或临时目录。

### 4.2 Restore report

`--report` 原子写出以下固定结构，UTF-8、稳定字段顺序、无绝对路径：

```json
{
  "format": "rtl-obfuscation.restore-vnext",
  "schema_version": 1,
  "state": "restored",
  "source_set": { "origin": "single-file|filelist", "top": null },
  "gate_manifest": [{ "file": "rtl/a.sv", "sha256": "..." }],
  "restored_manifest": [{ "file": "rtl/a.sv", "sha256": "..." }],
  "summary": {
    "files": 1,
    "restored_input_manifest_equal": true,
    "restored_byte_identical": true,
    "rate_enabled": false
  }
}
```

`source_set` 只保留 portable origin/top 等字段；不得写入 source-root、gate-dir、output-dir、
temporary directory 或本机路径。gate/restored manifest 顺序必须与持久化 execution envelope 一致。

### 4.3 stdout

成功时 stdout 只能输出稳定 portable summary：

```json
{
  "format": "rtl-obfuscation.restore-vnext-cli",
  "schema_version": 1,
  "state": "restored",
  "summary": { ...restore-report.summary... }
}
```

失败时 stderr 必须以 `error: <stable-code>` 开头，退出码非零，不暴露本机绝对路径；不得输出
成功 summary 或留下半成品。

## 5. 稳定错误码与失败边界

| condition | expected code |
| --- | --- |
| map/source-root 参数缺失、路径非法或 SourceSet 重建不一致 | `RESTORE_VNEXT_INPUT_INVALID` |
| report format/schema/state、mapping/range/manifest/metrics 不一致 | `RESTORE_VNEXT_REPORT_INVALID` |
| gate 缺失、gate manifest/hash/range/design.f 不一致 | `RESTORE_VNEXT_GATE_INVALID` |
| output/report 已存在、父目录不存在、路径重叠或发布失败 | `RESTORE_VNEXT_OUTPUT_INVALID` |
| JSON 读取、序列化、readback 或原子写失败 | `RESTORE_VNEXT_IO_ERROR` |

所有错误必须 fail-closed；source、gate、map 输入不得被删除或修改；失败后 output-dir 和 report
都不存在。不得捕获错误后降级为部分恢复、重新扫描全部 project root 或调用 legacy decrypt。

## 6. 允许修改的文件

- `rtl_obfuscator/restore_vnext.py`：持久化 report loader、mapping/execution hydration、restore audit 和稳定错误；
- `rtl_obfuscator/rewrite.py`：新增 `decrypt-vnext` parser/dispatch，旧分派保持不变；
- `tests/test_restore_vnext.py`：跨进程 no-rate/rate restore、report 校验、失败清理和 legacy 阻断；
- `README.md`：记录 `decrypt-vnext` 参数、输出和 source-root 必需边界；
- `docs/tasks/T054_vnext_restore_decrypt.md`：状态、执行记录和主 Agent验收记录。

不得修改 `rtl_obfuscator/orchestration_vnext.py`、T039–T053 core/fixture/Formal 脚本或任何其他
路径。需要修改允许列表外文件时，必须先在本任务记录偏差并停止。

## 7. 固定测试 oracle

测试只复用已验收的 compact fixture：

```text
tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv
```

目标测试必须覆盖：

1. 新 Python 进程先调用已验收 `encrypt-vnext` 生成 single-file no-rate gate/report，再调用
   `decrypt-vnext`，验证 physical files byte-identical、restore report 和 stdout；
2. 新 Python 进程先调用 `encrypt-vnext --filelist ... --top parameter_top --encryption-rate 0.35`，
   再调用 `decrypt-vnext`，验证 effective mapping 的 `rate_unselected`、gate manifest 和
   restored manifest 均按 report 保持，输出与 gold byte-identical；
3. normalized deterministic restore report、portable JSON、map tamper、effective mapping tamper、
   source byte mutation、gate byte/hash mutation 和 malformed JSON 均按稳定错误 fail-closed；
4. output/report 已存在、路径 overlap、缺少 gate/source/map 和发布/JSON 写失败均不产生部分输出；
5. `decrypt-vnext` 不调用 legacy `_decrypt`、`_decrypt_project`、旧 mapping loader、T052
   orchestration 或 T050 gate writer；旧 `decrypt`/`decrypt-project` parser/dispatch 仍可用；
6. 不执行 RISC-V-Vector Formal；不把 T053 encryption Formal 或 identity comparison 记作 T054 Formal。

本任务的 restore oracle 是 original source bytes、gate/restored manifests、range audit 和
T048 metrics 一致性；不是复制 gold 到 output，也不是只比较文件名或数量。

## 8. 目标验收命令

唯一验收命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/restore_vnext.py rtl_obfuscator/rewrite.py tests/test_restore_vnext.py
git diff --check HEAD
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T054_vnext_restore_decrypt.md
```

第一个 unittest 必须通过子进程真实执行 T053 `encrypt-vnext` 与 T054 `decrypt-vnext`，但不得运行
Formal；它必须记录跨进程边界、actual gate 输入、restore byte identity 和失败清理。

## 9. 子 Agent执行记录

```text
status: READY_FOR_REVIEW
starting_head: 82b5f94d3a89560d240dac73199edc0bb02f3f88
start_time: 2026-07-24T10:55:05+08:00
starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 7]`; no other status entries
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext -v`
baseline_result: exit 1; `ModuleNotFoundError: No module named 'tests.test_restore_vnext'`; Ran 1 test in 0.000s (expected before creating the T054 test file)
allowed_files: rtl_obfuscator/restore_vnext.py; rtl_obfuscator/rewrite.py; tests/test_restore_vnext.py; README.md; docs/tasks/T054_vnext_restore_decrypt.md
changed_files: rtl_obfuscator/restore_vnext.py; rtl_obfuscator/rewrite.py; tests/test_restore_vnext.py; README.md; docs/tasks/T054_vnext_restore_decrypt.md
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext -v` -> exit 0; Ran 5 tests in 1.485s; OK, including missing `--report` stable-error black-box coverage
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/restore_vnext.py rtl_obfuscator/rewrite.py tests/test_restore_vnext.py` -> exit 0; no output
  - `git diff --check HEAD` -> exit 0; no output
  - `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T054_vnext_restore_decrypt.md` -> exit 0; output `- 状态：READY_FOR_REVIEW`
results: all four final contract acceptance commands passed; no files outside allowed_files were modified
cross_process_single_no_rate: passed; independent encrypt-vnext then decrypt-vnext processes restored the single physical file byte-identically; restore report was deterministic byte-identical across two decrypt runs and stdout matched the portable summary
cross_process_filelist_rate: passed; independent encrypt-vnext --filelist design.f --top parameter_top --encryption-rate 0.35 then decrypt-vnext restored all physical files byte-identically; effective mapping preserved rate_unselected records and manifest order
report_hydration_and_manifest_audit: passed; report loader rebuilt SourceSet, SourceCatalog, SymbolGraph, RewritePolicy, MappingVNext and RewriteExecution, called T046 restore and T048 metrics audit, and verified mapping/execution reports, ranges, gate/restored manifests, metrics and byte identity
failure_cleanup: passed; report/gate/source tamper, malformed JSON, missing gate, missing `--report`, existing/overlapping output, JSON-write failure and publish-copy failure returned stable fail-closed errors with no output, report or publish temporary directories
legacy_blocking: passed; decrypt-vnext did not call legacy decrypt/decrypt-project, T052 run_vnext or T050 gate generation paths; old dispatch remains separate
formal_verification: N/A
reason: no new rewritten RTL is produced by this task; T053 actual gate Formal is inherited evidence only
deviations_or_blockers: none at start
boundaries: no vNext decrypt loader, project-root, mapping-version compatibility, legacy mapping, Formal rerun or new RTL generation was added; T053 actual gate Formal remains inherited evidence only
review_request: READY_FOR_REVIEW; missing-report stable error corrected and all required evidence is complete
correction_start: 2026-07-24; T054 returned to IN_PROGRESS by Main Agent because missing --report raised uncaught _CliVNextError instead of RESTORE_VNEXT_OUTPUT_INVALID
correction_scope: fix stable missing-report dispatch, add black-box coverage, rerun only the four contract commands; no implementation scope expansion
```

## 10. READY_FOR_REVIEW 条件

- 状态严格为 `READY_FOR_REVIEW`，精确状态守卫通过；
- unittest、py_compile、`git diff --check HEAD` 全部通过；
- single no-rate 和 filelist rate 均通过新的 Python 进程完成 restore，physical files byte-identical；
- report hydration、mapping/effective mapping、gate/restored manifest、range 和 metrics audit 全部通过；
- report/gate/source/output 任何篡改或非法路径均 fail-closed 且无部分输出；
- `decrypt-vnext` 未调用 legacy decrypt、旧 mapping loader、T052/T050 生成路径，旧分派未改变；
- 只修改本合同第 6 节列出的五个文件；
- Formal 明确记录为 `N/A` 及原因；
- 子 Agent 不得设置 `ACCEPTED`、创建 R4/T055、commit 或 push。

## 11. 主 Agent验收边界

主 Agent只独立复跑第 8 节四条命令，审查跨进程 actual gate 输入、restore report、portable 输出、
原子清理、旧分派和 T054 不生成新 RTL 的边界；不增加 Formal、RISC、project-root、legacy 全量
回归或隐藏 probe。全部通过后写本节验收记录并设置 `ACCEPTED`。

## 11.2 主 Agent独立验收记录（2026-07-24）

```text
review_head: 82b5f94d3a89560d240dac73199edc0bb02f3f88
review_worktree: only the five contract-allowed files changed; no fixture or unrelated path changes
unittest: `conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext -v` -> 5 tests, OK, exit_code=0
py_compile: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/restore_vnext.py rtl_obfuscator/rewrite.py tests/test_restore_vnext.py` -> exit_code=0
diff_check: `git diff --check HEAD` -> clean, exit_code=0
status_guard: `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T054_vnext_restore_decrypt.md` -> matched before ACCEPTED update, exit_code=0
missing_report: black-box decrypt-vnext returned exactly `error: RESTORE_VNEXT_OUTPUT_INVALID`, no traceback, and no partial output directory
scope_review: cross-process single no-rate and filelist rate restore, report hydration, tamper detection, path conflicts, atomic cleanup, and legacy/regeneration blocking independently reviewed; formal_verification=N/A because T054 produces no new rewritten RTL
record_note: stale execution-record status from the correction run was normalized to READY_FOR_REVIEW before this acceptance record
decision: ACCEPTED
```

## 11.1 主 Agent复核退回记录（2026-07-24）

```text
review_status: RETURNED_TO_IN_PROGRESS
finding: `decrypt-vnext` 缺少 `--report` 时，`_decrypt_vnext()` 通过 `_cli_vnext_fail()` 抛出 `_CliVNextError`，但 `main()` 的 decrypt-vnext 分支只捕获 `RestoreVNextError`；实际复现为未处理 traceback，而不是稳定 `error: RESTORE_VNEXT_OUTPUT_INVALID`。
required_fix: 将缺少 report 纳入 argparse required 或统一映射为 RestoreVNextError，并在目标 unittest 中增加缺少 report 的黑盒断言；不得放宽稳定错误合同。
acceptance: NOT_ACCEPTED
```

## 12. 主 Agent合同冻结记录（2026-07-24）

```text
status: READY
baseline_commit: ef48c9b
decision: T053 accepted; persist the first vNext report-to-restore cross-process adapter before R4 project-root
inputs: T053 orchestration report + actual gate + user-supplied source-root
oracle: hydrated mapping/execution envelope; gate/restored manifest equality; byte-identical physical restore; portable restore report
formal_verification: N/A; no new rewritten RTL is produced by T054
forbidden: legacy decrypt, mapping-version compatibility, T052/T050 regeneration, source/gate mutation, project-root, R4/T055 creation
```
