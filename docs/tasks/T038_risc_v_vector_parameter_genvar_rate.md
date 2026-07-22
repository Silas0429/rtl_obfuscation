# T038：RISC-V-Vector parameter/genvar 修复与加密率口径统一

- 状态：BLOCKED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T037 ACCEPTED
- Formal verification：必须执行本任务专用的 RISC-V-Vector 正例和功能负例
- RISC-V-Vector Formal：本任务明确要求执行；普通任务和普通全量回归仍然排除该 Formal 链路

## 1. 单一目标

修复两个相互影响但边界明确的问题，并保持 T037 已验收的五组 RISC 演示不变：

1. `project-root + top` 手动 profile 选择 `parameters` 时，正确区分真实 module
   `parameter/localparam` 与 PySlang elaboration 产生的 generate-loop iteration parameter，
   不再把 `genvar k` 误作为 parameter 改名导致 gate 语法损坏；
2. `--encryption-rate` 的选择器和 metrics 使用同一个 effective-line 分母，使
   `metrics.affected_lines.total` 与 `metrics.encryption_rate.total_lines` 一致。

T038 的 RISC Formal 固定 oracle 继续使用 T037 的五组 category，不因演示入口扩展而改变；
根目录 `encrypt.py` 的用户演示由第 7.1 节单独授权为全部 19 个 canonical category，并且
仍不把 Formal 植入一键演示。需要验证固定 Formal oracle 时，使用本任务的独立验收入口。

## 2. 固定输入和已知失败

固定 RISC 输入：

```text
project-root: rtl_samples/RISC-V-Vector
top: vector_top
manual categories: signals ports instances struct interface parameters
```

当前错误基线必须在任务记录中保留：

- gold 使用上述六组 category 可以通过分析；
- `vex.sv` 的 `genvar k` 被错误作为 5 个 `parameters` entry 收集，共 36 个伪 occurrence；
- gate 出现类似 `for (renamed = 0; k < renamed_lanes; k++)` 的部分改写；
- CLI 以 `MAPPING_V4_GATE_ANALYSIS_FAILED` 回滚且不发布半成品；
- 当前 RISC 加密率样例中 `encryption_rate.total_lines=5532`，而
  `affected_lines.total=4461`，因为前者统计物理行，后者统计非空且非 `//` 行。

## 3. 参数/genvar 修复契约

### 3.1 语义规则

- 真实 module value parameter、module `localparam` 和其已确认的表达式、dimension、
  generate header、named override 引用继续按既有 T031/T032/T035 规则处理；
- top value parameter 和 top ABI 继续 preserved；top localparam 是否 eligible 遵循现有
  classification，不得因为本修复扩大 top ABI；
- generate-loop iteration parameter 只能归入 `genvars`（当用户选择该 category），不能
  归入 `parameters`；当用户只选择 `parameters` 时必须被排除或以稳定 preserved/unsupported
  结果返回；
- 同名真实 parameter 和 genvar 必须依据语义 owner/source origin 分离，禁止按文本名称合并；
- 如果 PySlang 无法提供稳定的 genvar origin/owner 关系，必须 fail-closed，不得使用全局文本
  替换或猜测性 fallback。

### 3.2 RISC parameter-inclusive oracle

修复后的六组 RISC 手动 profile 必须满足：

- mapping version 4，19 个 closure files，17 个 reachable modules；
- 五组既有 T037 mapping 数量保持 1091 entries / 5741 occurrences；
- `parameters` category 只包含真实 module parameter/localparam，目标为 120 entries /
  1094 occurrences；其中不得出现 `scope=vex, original_name=k` 的 parameter entry；
- 六组组合目标为 1211 mapping entries / 6835 modified tokens；
- mapping ranges 不重叠，gate strict reanalysis 通过，metrics coverage=1.0，
  `plaintext_leakage_rate=0.0`；
- decrypt 后 mapping files 中全部 19 个文件与 gold byte-identical；
- 连续两次运行的 mapping、gate manifest、metrics 和 per-file map byte-identical。

上述数量是由当前失败 gate 中剔除 5 个 `vex/k` generate 伪 parameter 后冻结的目标；若实现
发现目标与 PySlang 稳定语义 API 冲突，必须先记录偏差并停止，不得自行改 oracle。

## 4. 加密率口径统一契约

### 4.1 唯一分母

本任务把 effective line 定义为源文件 `splitlines()` 后满足以下条件的行：

```text
line.strip() != "" and not line.strip().startswith("//")
```

对单文件、filelist 和 project-root 三种入口均使用 mapping 对应 RTL 文件集合计算：

- `encryption_rate.total_lines` 使用 effective line 总数；
- `encryption_rate.target_lines`、`candidate_lines`、`selected_lines`、`actual_rate` 和
  `maximum_rate` 使用同一分母；
- `affected_lines.total` 和 `affected_lines.rate` 使用同一分母；
- 对率模式，必须满足
  `affected_lines.total == encryption_rate.total_lines`，且
  `affected_lines.rate == encryption_rate.actual_rate`（允许 JSON 浮点表示误差）；
- 空行、空白行和纯 `//` 注释行不进入分母，但 identifier 影响行集合仍按原文件的 1-based
  行号记录；`.svh` 按普通 RTL 文件计入；
- 不提供 `--encryption-rate` 时，既有 mapping、gate、解密和非率 metrics 语义保持不变。

### 4.2 率选择行为

- 仍先建立完整候选 mapping，再按唯一 `(file, line)` 集合执行 greedy；
- target 不可达时仍选择全部候选、不报错，并报告 `target_unreachable=true`；
- 率选择不得因参数/genvar 修复产生重复或重叠 range；
- 率模式选择出的 mapping 必须通过现有 gate audit 和 decrypt。

## 5. 专项测试范围

新增紧凑 fixture `tests/fixtures/t038_risc_v_parameter_genvar/`，至少覆盖：

- 非顶层 module parameter/localparam；
- module parameter 与 generate-loop genvar 同名但不同 owner；
- 多个 generate loop 重复使用 `genvar k`；
- named parameter override 左侧和 RHS；
- top parameter preserved、unreachable parameter、unsupported parameter fail-closed；
- 空行、纯 `//` 行和多 mapping 命中同一物理行。

新增 `tests/test_t038_risc_v_parameter_genvar_rate.py`，验证 inventory、mapping、gate、
metrics、rate、decrypt、确定性和负向诊断。新增 `scripts/t038_acceptance.py`，只负责本任务
六组 RISC gate、formal-view、formal-align、Yosys 正负例和 byte-identical 解密，不修改
T037 的 `scripts/t029_acceptance.py` 固定五组 oracle。

## 6. RISC Formal 验收

- gold 与 parameter-inclusive gate 各生成 260 项 formal-view transformation，signature
  必须完全一致；
- gate view 只用 mapping v4 执行 formal-align，不能读取 gold；alignment 数量、manifest 和
  warning oracle 必须在新任务测试中冻结并重复运行一致；
- 正例：gold formal-view 与 aligned gate formal-view，top `vector_top`，`--seq 1`，退出码
  0 且 JSON `formal_equivalence=pass`；
- 负例：只将 `vector_idle_o` 的第一个二元 `&` 改成 `|`，退出码非零，达到
  `equiv_status -assert`，且只留下对应的一个未证明 cell；
- 正例和负例各自最多 600 秒；超时、parse error、hierarchy error 或 identity comparison
  均不算通过；
- RISC-V-Vector Formal 不加入普通全量回归。

## 7. 允许修改的文件

- `rtl_obfuscator/inventory.py`：仅修复 parameter/genvar 语义收集、分类和 source ranges；
- `tests/fixtures/t038_risc_v_parameter_genvar/**`：新增紧凑 SystemVerilog fixture；
- `tests/test_t038_risc_v_parameter_genvar_rate.py`：新增黑盒和 oracle 测试；
- `scripts/t038_acceptance.py`：新增本任务专用 RISC Formal 驱动；
- `tests/test_t036_encryption_rate.py`：更新率分母断言并补充 effective-line 一致性回归；
- `README.md`、`docs/systemverilog_renaming_table.md`、`docs/formal_verification.md`、
  `docs/future_work.md`、`docs/project_root_top_roadmap.md`：同步当前边界和新口径；
- `docs/category_profile_normalization_plan.md`、`docs/project_root_parameter_plan_draft.md`：
  将条件性 profile 晋级顺延到后续任务，并记录 T038 的边界修复；该旧占位不再使用 T039 编号；
- `docs/tasks/T038_risc_v_vector_parameter_genvar_rate.md`：任务记录和验收证据。

除第 7.1 节用户确认的演示扩展外，不允许修改 `scripts/formal_equivalence.py`、T037 固定
RISC 测试的五组 oracle 或 `rtl_samples/RISC-V-Vector` 原始 fixture；不在本任务中晋级更多
default category。

### 7.1 用户确认的演示样例扩展

用户另行要求整理当前演示样例，故本次允许同步修改以下 FIFO 内容：

- `rtl_samples/example_fifo/fifo_if.sv`、`fifo_ctrl.sv`、`fifo_top.sv`：让
  `fifo_ctrl` 使用 `fifo_if.consumer ctrl`，由 `fifo_top` 通过 `.ctrl(fifo_bus)` 连接；
- 对应 FIFO 黑盒测试、README、renaming table、Formal 边界说明和 T026 后续修订记录。
- `encrypt.py`、`tests/test_encrypt_demo.py`：支持 `fifo`/`riscv` 两个演示样例，默认名称长度
  20、默认输出目录按样例区分，并显式覆盖全部 19 个 canonical category。

该扩展不改变 T038 的 RISC Formal oracle、top-level FIFO ABI 或 `scripts/formal_equivalence.py`；
演示脚本的 category 选择不再受 T037 历史五组配置限制。由于
当前 Icarus/Yosys 不支持下层 interface-typed module port，演示验收不启动 FIFO Formal，
只要求 PySlang、Verible、mapping gate audit 和 decrypt 通过。

## 8. 验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t038_risc_v_parameter_genvar_rate -v
conda run -n rtl_obfuscation python -m unittest tests.test_t036_encryption_rate -v
conda run -n rtl_obfuscation python scripts/t038_acceptance.py \
  --work-dir /private/tmp/rtl-obfuscation-t038-risc-parameter
conda run -n rtl_obfuscation python -m unittest tests.test_risc_v_vector_project_root -v
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/inventory.py tests/test_t038_risc_v_parameter_genvar_rate.py \
  tests/test_t036_encryption_rate.py scripts/t038_acceptance.py
git diff --check
```

还必须执行 README 中的显式非 RISC 回归列表，并排除 `tests.test_risc_v_vector_project_root`
之外的 RISC Formal；本任务的专用脚本是唯一允许启动 RISC-V-Vector Formal 的新入口。

## 9. 执行记录

```text
status: IN_PROGRESS
start_record: 2026-07-21; T037 prerequisite confirmed ACCEPTED
changed_files: encrypt.py, tests/test_encrypt_demo.py, rtl_obfuscator/inventory.py, rtl_obfuscator/rewrite.py, tests/test_t036_encryption_rate.py, rtl_samples/example_fifo/fifo_if.sv, rtl_samples/example_fifo/fifo_ctrl.sv, rtl_samples/example_fifo/fifo_top.sv, tests/test_debug_mode.py, tests/test_example_fifo_project.py, tests/test_formal_equivalence.py, tests/test_project_root_rewrite.py, README.md, docs/formal_verification.md, docs/future_work.md, docs/project_root_top_roadmap.md, docs/systemverilog_renaming_table.md, docs/tasks/T026_fifo_interface_struct_usage.md, docs/tasks/T037_risc_v_vector_formal_demo.md, docs/tasks/T038_risc_v_vector_parameter_genvar_rate.md
scope_extension_record: user-directed demonstration cleanup added the lower-module fifo_if.consumer ctrl fixture and its inventory reference ownership; this is outside the original RISC/rate-only file list, remains IN_PROGRESS, and is not presented as T038 acceptance.
random_name_result: restored inventory._new_name to cryptographic random legal-identifier generation; a light FIFO signals run produced distinct names such as jenXcYoU, m2N_wNqJ and ivHdnO7T rather than the legacy lgaaaaaaaaaaaaaaaaaa sequence.
fifo_interface_result: fifo_ctrl now declares fifo_if.consumer ctrl and fifo_top connects .ctrl(fifo_bus); project-root interface profile passes with 12 entries / 53 occurrences, and the combined signals+ports+instances+struct+interface profile passes with 41 entries / 174 occurrences. Icarus/Yosys formal is unsupported for this fixture shape and was not run per user request.
encrypt_demo_result: `python encrypt.py --sample fifo --name-length 20` passes with 4 files / 67 entries / 268 occurrences; `python encrypt.py --sample riscv --name-length 20` passes with 19 files / 1238 entries / 7081 occurrences; both decrypt byte-identical and use all 19 canonical categories. Demo Formal was not run.
parameter_genvar_result: same-name module parameter/genvar regression passes; six-group project-root encryption succeeds with 1211 entries / 6882 occurrences, vex/k pseudo parameter entries absent, gate strict analysis and decrypt pass. The frozen 6835-occurrence oracle still differs by 47 references; the discrepancy is recorded without changing the oracle.
rate_denominator_result: pass; RISC sample reports total_lines=4461, target_lines=1339 at rate=0.3, affected_lines.total=4461, selected_lines=1339, actual_rate=0.3001569154898005
formal_verification: PENDING; the contract-required `tests/fixtures/t038_risc_v_parameter_genvar/`, `tests/test_t038_risc_v_parameter_genvar_rate.py`, and `scripts/t038_acceptance.py` are absent, so no RISC Formal result is claimed
exact_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_parameter_dimension_rewrite.ParameterDimensionRewriteTest.test_generate_local_genvar_shadows_module_parameter -v`; `conda run -n rtl_obfuscation python -m unittest tests.test_t036_encryption_rate -v`; explicit README non-RISC list via `conda run -n rtl_obfuscation python -m unittest ... -v` (35 modules, excluding `tests.test_risc_v_vector_project_root`); six-group encrypt/decrypt command recorded above
exit_codes: targeted genvar test 0; explicit non-RISC regression 0 (`Ran 115 tests`, `OK`, 3 skipped FIFO formal); six-group encrypt/decrypt 0; `py_compile` and `git diff --check` 0
uncovered_boundaries: T038 compact fixture, dedicated acceptance script, RISC Formal positive/negative, and the 6835-occurrence frozen oracle remain unresolved; RISC Formal was not run
review_request: not ready for review; task remains IN_PROGRESS
```

## 10. 主 Agent 验收记录

```text
acceptance_time: 2026-07-22
independent_commands: explicit 35-module non-RISC regression; `conda run -n rtl_obfuscation python -m py_compile encrypt.py rtl_obfuscator/inventory.py rtl_obfuscator/rewrite.py tests/test_debug_mode.py tests/test_encrypt_demo.py tests/test_example_fifo_project.py tests/test_formal_equivalence.py tests/test_project_root_rewrite.py tests/test_t036_encryption_rate.py`; `git diff --check`; six-group RISC encrypt/decrypt
independent_results: non-RISC `Ran 115 tests`, `OK`, 3 expected skips; targeted same-name genvar test passes; six-group RISC gate/decrypt passes with 19 files, 1211 entries, 6882 occurrences, coverage 1.0 and plaintext leakage 0.0
formal_recheck: pending; required T038 acceptance driver and formal-view/formal-align/Yosys positive/negative flow are not present or executed
git_status: 20 modified tracked paths remain unstaged; no files staged or committed because T038 is not ACCEPTED
staged_diff_review: not applicable; task is not ready for review
acceptance_conclusion: NOT_ACCEPTED; keep T038 IN_PROGRESS until the missing dedicated artifacts, frozen occurrence oracle decision, and RISC Formal evidence are resolved
```

## 11. 继续执行记录（2026-07-22）

```text
status: BLOCKED
changed_files: rtl_obfuscator/inventory.py, tests/fixtures/t038_risc_v_parameter_genvar/**, tests/fixtures/t038_risc_v_parameter_genvar_negative/type_parameter.sv, tests/test_t038_risc_v_parameter_genvar_rate.py, docs/tasks/T038_risc_v_vector_parameter_genvar_rate.md
inventory_result: parameter-inclusive RISC inspect is exactly 1211 eligible entries / 6835 occurrences after excluding the five vex/k pseudo-parameter symbols; the compact fixture passes owner-separated parameter/genvar inventory, named override range ownership, repeated genvar collection, unreachable exclusion, and unsupported type-parameter fail-closed diagnostics.
gate_boundary: removing the 47 syntax-owned parameter references needed to reach 6835 causes strict gate reanalysis to report UndeclaredIdentifier diagnostics in rtl/shared/eb_buff_generic.sv and fails with MAPPING_V4_GATE_ANALYSIS_FAILED; retaining those owner-bound references produces a strict gate/decrypt-passing mapping of 1211 entries / 6882 occurrences.
extra_reference_breakdown: 45 generate-body/header references plus 2 syntax-dimension references; these are real parameter uses, not vex/k pseudo-parameter declarations. The 45-reference set includes eb_buff_generic/BUFF_TYPE, eb_one_slot/FULL_THROUGHPUT, v_int_alu/VECTOR_LANES and VECTOR_LANE_NUM, vex/FWD_POINT_A/FWD_POINT_B/VECTOR_LANES, vex_pipe/FWD_POINT_A/FWD_POINT_B/VECTOR_FP_ALU/VECTOR_FXP_ALU/VECTOR_LANE_NUM, and vis/VECTOR_LANES.
rate_result: tests.test_t036_encryption_rate passes 6 tests; affected_lines.total equals encryption_rate.total_lines and affected_lines.rate equals encryption_rate.actual_rate.
fixture_test_result: tests.test_t038_risc_v_parameter_genvar_rate passes 3 tests; project_root_parameters plus parameter_dimension_rewrite passes 11 tests; py_compile and git diff --check pass.
formal_view_result: six-group gate with 1211/6882 passes gate audit/decrypt; gold and gate formal-view each produce 260 transformations; gold view manifest remains 56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872.
formal_verification: BLOCKED
formal_blocker: existing formal-align rejects the strict gate/decrypt-passing parameter-inclusive mapping with `formal-align mapping oracle mismatch` because it is hard-coded to T037 1091 entries / 5741 occurrences; the contract forbids changing that oracle and requires stopping when the frozen 1211/6835 target conflicts with stable semantic gate behavior. No Yosys positive or negative result is claimed.
acceptance_conclusion: NOT_ACCEPTED; task remains BLOCKED pending Main Agent/user decision on whether the frozen 1211/6835 oracle or the semantically required 1211/6882 gate oracle is authoritative. The dedicated scripts/t038_acceptance.py was not added because it cannot truthfully implement the contradictory contract.
```

## 12. 架构复核与后续决策（2026-07-22）

```text
decision_status: RECORDED; no implementation resumed
user_direction: replace the accumulated single-file/filelist/project-root compatibility paths with one SourceSet/SymbolGraph/rewrite architecture; single-file is a one-file filelist subset, and project-root discovers a top-rooted SourceSet before delegating to the same filelist engine
mode_policy: every filelist module may receive non-ABI rewrites; with top enabled, only the selected-top closure may opt into child-module ABI rewrites; selected top external boundary remains preserved by default
compatibility_direction: stop adding v2/v3/v4 writer branches and legacy-count-driven tests; future implementation will define one mapping vNext and retire mode-specific encrypt/inventory/audit paths
planning_document: docs/three_mode_refactor_plan.md
next_implementation_plan: docs/refactor_next_sourceset_task.md
subagent_protocol: docs/refactor_subagent_protocol.md
t038_conclusion: remains BLOCKED / NOT_ACCEPTED; the 6835-vs-6882 conflict and missing T038 Formal are retained as historical evidence, not resolved or accepted by this planning update
next_task_rule: superseded on 2026-07-22 by explicit user authorization after the blocked worktree was preserved; T039 may proceed under the replacement architecture without accepting or resuming T038
formal_verification: N/A; this update records architecture and task planning only and produces no rewritten RTL
```

## 13. 主 Agent 保存与关闭处置（2026-07-22）

```text
snapshot_commit: e4f3f94
snapshot_subject: [CHORE] Preserve blocked T038 snapshot before refactor
snapshot_scope: all previously staged T038 implementation, compact fixtures, tests, evidence, and refactor planning documents
status: BLOCKED / NOT_ACCEPTED
acceptance_claim: none; the snapshot preserves evidence and recoverability only
user_direction: preserve the previous result, stop extending T038 compatibility/oracles, and create the next replacement-architecture task
successor_task: docs/tasks/T039_sourceset_input_contract.md
resume_policy: do not resume T038 implementation; reuse its semantic evidence only when a later SymbolGraph task explicitly authorizes it
```
