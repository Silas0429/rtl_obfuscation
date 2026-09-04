# T136：持久化运行记录与三视图 filelist

- 状态：`ACCEPTED`
- 负责人：子 Agent（实现与自测）/ 主 Agent（合同与验收）
- 起始分支：`delivery/fast-local-signals`
- 起始提交：`404e5864ca92a6e0196c481bce13cbbf22296536`

## 1. 单一目标

不改变 SourceSet、候选对象、rename/preserve/unsupported 决策、MappingVNext schema、随机命名、
RTL edits、strict compile、manifest 或 byte-identical restore，只扩充一次成功公开加密运行的交付信息：

1. `encryption_summary.txt` 保存展开 shell 环境变量后的有效启动命令、与 stderr **逐行完全相同**的
   全部阶段计时行，以及与 stderr 完全相同的最终“加密总结”；
2. CLI gate 在保持全部物理输入层级不变的同时输出 `design.f`、`export_design.f` 和
   `original_design.f` 三种有效编译上下文视图。

## 2. 固定输入与输出

主 Agent 冻结黑盒测试，子 Agent 不得修改：

```text
tests/test_t136_persisted_run_summary_and_filelists.py
```

测试动态建立一个带 `+incdir+`、`+define+`、literal include、`--top` 和 `--rewrite-root` 的小型
SystemVerilog filelist，并通过公开 `rtl_encrypt.py` 运行。

成功输出必须包含：

```text
<OUT>/design.f
<OUT>/export_design.f
<OUT>/original_design.f
<OUT>/encryption_summary.txt
<OUT>/mapping.json
<OUT>/metrics.json
<OUT>/mapping_table.csv
<OUT>/<原物理层级下的 source/header/context>
```

## 3. 冻结 summary 合同

1. `_CliVNextProgress.stage()` 生成每条计时文本一次；同一字符串立即写 stderr 并按顺序保留给
   `encryption_summary.txt`。禁止分别格式化、重新读取时钟或从 report 推算第二份计时行。
2. 非 quiet 成功运行中，从 stderr 提取的全部 `^[ ...s] 开始/完成 ...` 行必须与
   `encryption_summary.txt` 中提取的计时行列表逐项、逐字符相同，包含外层阶段、compile/rename
   子阶段和 restore 后的 audit/publish/cleanup。
3. 持久化文件末尾的“加密总结”与 stderr 最终“加密总结”使用同一个已生成字符串，逐字符相同；
   terminal summary 必须在 cleanup 计时结束后输出，使其成为 stderr 最后一段。
4. 启动指令记录当前 Python executable、脚本和完整 argv，使用 shell-safe quoting；shell 已展开的
   `$FILELIST/$TOP/$REWRITE/$OUT` 必须以实际值出现，不能恢复或输出这些占位变量。
5. 同时记录工作目录。`--quiet` 只压制 stderr，不能关闭计时采集或持久化 summary。
6. 总用时由同一个 `_CliVNextProgress` monotonic clock 读取一次，终端和持久化总结共用该值。
7. 只保证成功运行的持久化记录；OOM、SIGKILL 或原子失败不发布半成品 summary。本任务不增加
   `--run-log`。

## 4. 冻结三视图 filelist 合同

令 SourceSet 的 `compile_order` 条目为 `p`，规范 include directory 为 `d`，最终 CLI 输出目录为
`OUT`，原始 SourceSet 根为 `SRC`：

| 文件 | source/context entry | include directory |
| --- | --- | --- |
| `design.f` | `<absolute OUT>/<p>` | `+incdir+<absolute OUT>/<d>` |
| `export_design.f` | `$OUT/<p>` | `+incdir+$OUT/<d>` |
| `original_design.f` | `<absolute SRC>/<p>` | `+incdir+<absolute SRC>/<d>` |

1. 三份 filelist 依次写规范 include directories、规范 defines 和 `compile_order`；define 每行一个，
   固定为 `+define+NAME=VALUE`。
2. 三份 filelist 的目录、define 和 compile entry 顺序完全相同，只有路径根表示不同。
3. nested `-f` 已由 SourceSet 扁平化；`-v PATH` 继续是普通 source entry alias，不恢复 `-v` 标记。
4. `ordered_source_files + included_files` 的规范去重集合仍全部复制。仅由 literal include 进入的
   include-only 文件必须复制，但不得额外作为独立 compile entry 写进三份 filelist。
5. `design.f` 是当前输出的绝对本地入口；移动目录后允许失效。`export_design.f` 以用户将环境变量
   `OUT` 设为 gate 根为合同。`original_design.f` 指向运行时原始物理输入。
6. CLI 内部 staging gate 可以继续使用既有相对 canonical filelist 完成 strict compile 与 restore；
   对外三视图只能在已知最终 `--output-dir` 后生成，禁止把临时 staging 路径泄露到 `design.f`。
7. public decrypt 必须接受并验证新的 gate file set，继续恢复全部物理文件且 byte-identical。
8. `scripts/formal_equivalence.py` 必须支持三视图中的 `+incdir+`、`+define+` 和绝对 source entry，
   将上下文传给 gold/gate 各自的 Yosys `read_verilog`，不能把 directive 当文件路径。

## 5. 不包含

- 不改变 FAST/FULL、SourceCatalog、RenameIndex、category 或安全判据；
- 不增加新的 mapping/report schema 字段或 schema version；
- 不把 include-only header 当作 standalone compilation unit；
- 不保存失败/SIGKILL 运行日志；
- 不支持当前 SourceSet 本身不接受的 filelist shell 语法；
- 不运行真实 AICluster/StCache，不运行 RISC-V-Vector Formal；
- 不提交或推送，交付由主 Agent 验收后处理。

## 6. 允许修改文件

```text
README.md
docs/development/project_structure.md
docs/formal_verification.md
docs/tasks/T136_persisted_run_summary_and_filelists.md
rtl_obfuscator/rewrite.py
rtl_obfuscator/restore_vnext.py
scripts/formal_equivalence.py
tests/test_t116_cli_report.py
tests/test_t127_performance_probe.py
tests/test_formal_equivalence.py
tests/test_t119_filelist_multi_root_output.py
tests/test_t134_fast_include_closure.py
```

固定黑盒测试不在子 Agent 允许修改列表。需要修改 SourceSet、mapping schema、rename 实现、fixture 或
其他生产文件时，必须记录偏差并停止。

## 7. Baseline

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t136_persisted_run_summary_and_filelists -v
```

预期失败：当前 `encryption_summary.txt` 没有命令和阶段行；`design.f` 仍是相对 compile order；不存在
`export_design.f` 和 `original_design.f`。

## 8. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t136_persisted_run_summary_and_filelists \
  tests.test_t116_cli_report.T116StdoutContractTests \
  tests.test_t116_cli_report.T116DefinedFieldTests \
  tests.test_t116_cli_report.T116DivisionByZeroTests \
  tests.test_t116_cli_report.T116FailurePositionTests.test_missing_file_reports_its_absolute_path_and_filelist_line \
  tests.test_t116_cli_report.T116FailurePositionTests.test_missing_file_named_by_a_nested_filelist_reports_that_filelist \
  tests.test_t116_cli_report.T116FailurePositionTests.test_quiet_does_not_silence_a_failure \
  tests.test_t127_performance_probe \
  tests.test_t135_scoped_execution_metrics -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_rewrite_vnext tests.test_restore_vnext tests.test_formal_equivalence \
  tests.test_public_cli tests.test_t119_filelist_multi_root_output \
  tests.test_t130_fast_local_signals tests.test_t134_fast_include_closure -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py \
  scripts/formal_equivalence.py tests/test_t136_persisted_run_summary_and_filelists.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T136_persisted_run_summary_and_filelists.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t136_ready_for_review=pass")'
```

第一条必须包含 T136 actual renamed gate Formal 正例 exit 0 / `formal_equivalence=pass`，以及固定 XOR→OR
功能负例非零并含 `unproven` 与 `equiv_status -assert`。主 Agent 验收时独立重跑同一命令。

## 9. 执行记录

```text
status: implementation, boundary follow-up, and self-test complete; ready for Main Agent review
starting_head: 404e5864ca92a6e0196c481bce13cbbf22296536
started_at: 2026-09-04 Asia/Shanghai
changed_files:
  README.md
  docs/development/project_structure.md
  docs/formal_verification.md
  docs/tasks/T136_persisted_run_summary_and_filelists.md
  rtl_obfuscator/rewrite.py
  rtl_obfuscator/restore_vnext.py
  scripts/formal_equivalence.py
  tests/test_formal_equivalence.py
  tests/test_t116_cli_report.py
  tests/test_t119_filelist_multi_root_output.py
  tests/test_t127_performance_probe.py
  tests/test_t134_fast_include_closure.py
  tests/test_t136_persisted_run_summary_and_filelists.py (Main Agent frozen black-box test; unchanged by sub-agent)
commands:
  1. conda run -n rtl_obfuscation python -m unittest tests.test_t136_persisted_run_summary_and_filelists tests.test_t116_cli_report.T116StdoutContractTests tests.test_t116_cli_report.T116DefinedFieldTests tests.test_t116_cli_report.T116DivisionByZeroTests tests.test_t116_cli_report.T116FailurePositionTests.test_missing_file_reports_its_absolute_path_and_filelist_line tests.test_t116_cli_report.T116FailurePositionTests.test_missing_file_named_by_a_nested_filelist_reports_that_filelist tests.test_t116_cli_report.T116FailurePositionTests.test_quiet_does_not_silence_a_failure tests.test_t127_performance_probe tests.test_t135_scoped_execution_metrics -v
  2. conda run -n rtl_obfuscation python -m unittest tests.test_rewrite_vnext tests.test_restore_vnext tests.test_formal_equivalence tests.test_public_cli tests.test_t119_filelist_multi_root_output tests.test_t130_fast_local_signals tests.test_t134_fast_include_closure -v
  3. conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py scripts/formal_equivalence.py tests/test_t136_persisted_run_summary_and_filelists.py
  4. git diff --check HEAD
results:
  command 1: PASS, 29 tests
  command 2: PASS, 23 tests (includes source-root `+incdir+.` three-view/decrypt/Formal regression)
  command 3: PASS, exit 0
  command 4: PASS, exit 0
formal_verification: PASS
gold: T136 dynamic original project/rtl/top.sv via <gate>/original_design.f
gate: T136 actual renamed gate/rtl/top.sv via <gate>/design.f
top: t136_top
command: command 1 above, test_actual_gate_formal_positive_and_fixed_functional_negative
exit_code: 0
result: positive Yosys JSON formal_equivalence=pass; fixed actual-gate XOR -> OR negative returned nonzero and contained both unproven and equiv_status -assert
additional_formal: source-root `+incdir+.` actual renamed gate passed Yosys via original_design.f/design.f, exit 0, JSON formal_equivalence=pass
uncovered_boundaries: successful runs only; no SIGKILL/OOM log; design.f intentionally binds the current absolute gate while export_design.f requires OUT to name the relocated gate; no AICluster/StCache or RISC-V-Vector run
```

## 10. 偏差或阻塞

```text
2026-09-04 contract clarification: the frozen T136 behavior intentionally replaces the
old relative-design.f contract, while T119 and T134 acceptance tests still asserted the
old bytes and were required by section 8. Main Agent added only those two historical
tests to the allowlist so their assertions can follow the new three-view filelist
contract; product scope and acceptance commands are unchanged.

2026-09-04 baseline audit: T127's fixed stage list predates the already-accepted T135
audit.execution/audit.metrics/audit.report events, so Main Agent added T127 to the
allowlist solely to synchronize that permanent probe. Three T116 diagnostic-detail
tests already fail on starting HEAD 404e586 because orchestration no longer forwards
PySlang diagnostic positions; that unrelated product behavior is excluded from T136's
acceptance command rather than repaired or weakened here. All other T116 classes plus
the three still-passing input-failure tests remain mandatory.

2026-09-04 Main Agent review follow-up: a legal include directory equal to the
SourceSet root is represented as `.`. The first delivery rejected that empty relative
suffix while validating original_design.f. T136 returned to IN_PROGRESS to fix only
this canonical root-include boundary and add CLI/decrypt/Formal regression coverage.

2026-09-04 historical Formal test audit: tests/test_formal_equivalence.py on the
starting HEAD still invoked removed `parameters` / `genvars` categories and the removed
`--abi-category` option, so it failed before reaching Formal. The regression now uses
the current canonical `signals` category on the same design and retains its actual-gate
positive proof plus functional negative. This does not claim or silently preserve
parameter/genvar renaming coverage; those categories are outside the current public
contract. The new root-include regression separately covers the T136 three-view,
decrypt, and Formal behavior.
```

## 11. 主 Agent 验收记录

```text
status: ACCEPTED
accepted_at: 2026-09-04 Asia/Shanghai
starting_head: 404e5864ca92a6e0196c481bce13cbbf22296536
independent_acceptance:
  command 1: PASS, 29 tests
  command 2: PASS, 23 tests
  py_compile: PASS
  git diff --check HEAD: PASS
formal_positive: PASS, actual renamed gate, JSON formal_equivalence=pass
formal_negative: PASS, fixed XOR -> OR mutation returned nonzero with unproven and equiv_status -assert
additional_delivery_check: PASS, copied gate compiled and proved through export_design.f after OUT was changed to the relocated root
summary_identity: PASS, persisted timing lines and terminal summary are exact stderr-origin strings
scope_review: PASS, no SourceSet, MappingVNext schema, rename decision, RTL edit, strict compile, manifest, or restore-byte policy change
```
