# T050：rate-selected MappingVNext gate execution 与 restore

- 状态：READY
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-G
- 前置任务：T049 ACCEPTED，交付提交 1c8851f
- 设计依据：docs/three_mode_refactor_plan.md 第 1–7 节
- 执行规范：docs/refactor_subagent_protocol.md
- Formal 依据：docs/formal_verification.md
- 验收类型：rewrite/mapping；本任务产生 rewritten RTL
- Formal verification：必须执行 compact actual selected gate 正例和固定功能负例

## 1. 单一目标

把 T049 RateSelectionVNext 选择计划接入 T046 的一次性 rewrite/strict gate/restore 引擎：

1. 验证 MappingVNext 与 RateSelectionVNext identity、candidate ranges 和 selection equations；
2. 物化 selected mapping：selected rename records 保留 renamed_name，未选 rename records 转为
   preserve，reason 固定为 rate_unselected，renamed_name 固定为 null；
3. 保持所有 record、declaration、occurrence、owner 和 source ranges 完整，不允许部分 record；
4. 调用同一 write_gate_vnext/restore_gate_vnext 语义生成 gate、strict compile 和恢复结果；
5. 记录 rate selection 与 rewrite execution 的可审计关联；
6. actual selected gate 必须通过 compact Yosys Formal，固定一字节功能改变必须失败。

本任务不接入 CLI、project-root、metrics adapter 或历史 mapping 分派，不修改 T049 selector 算法。

## 2. 固定输入

只读复用 T043–T049 compact fixture 和公开 API：

tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/closure.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv

测试使用 T045 deterministic name_factory 构造真实 MappingVNext，调用 T049
build_rate_selection_vnext(mapping_vnext, rate="0.35")，再调用本任务 selected execution API。
所有 gate、restore、mapping 和负例写入 TemporaryDirectory；不新增或修改 RTL/formal fixture，
18 个冻结 fixture hash 必须保持不变。

## 3. 固定公开 API

允许在 rtl_obfuscator/rewrite_vnext.py 增加本任务 API，并新增
rtl_obfuscator/rate_execution_vnext.py：

RateRewriteExecutionVNext 固定包含：

- schema_version
- rate_selection
- rewrite_execution

公开 API：

- build_rate_selected_mapping_vnext(mapping_vnext, rate_selection) -> MappingVNext
- write_rate_selected_gate_vnext(mapping_vnext, rate_selection, output_dir) -> RateRewriteExecutionVNext
- restore_rate_selected_gate_vnext(rate_execution, gate_dir, output_dir) -> RestoreResult

build_rate_selected_mapping_vnext 必须使用 T049 selected symbol ids 和 mapping identity；不得重新
收集 symbol、reference、owner、category 或 range。输出 MappingVNext 的 policy decisions 与 records
必须一一对应：

- selected rename record：action=rename，保留原 renamed_name；
- unselected rename record：action=preserve，reason=rate_unselected，renamed_name=null；
- 原本 preserve/unsupported record：保持原 action、reason 和 renamed_name；
- record 顺序、symbol_id、category、owner、declaration、occurrences、impact、abi 不变。

write_rate_selected_gate_vnext 必须复用 T046 的 one-pass edit、atomic output、strict compile、
gate manifest 和 range audit；不得复制第二套 gate engine。restore API 必须复用 T046 restore 语义，
不得读取 gold。

## 4. selected mapping 与 report 不变量

selected mapping 必须满足：

- selected records 恰好等于 T049 selection 中 selected candidates；
- unselected rename records 不建立 edit；
- selected rename records 的 declaration 和全部 occurrences 建立 edit；
- T049 selection 的 candidate/line/report equations重新验证；
- input manifest、compile order、SourceSet、top 和 ABI policy 保持不变；
- selected mapping 的 preserve reason 只能为 rate_unselected 或原有 preserve reason；
- MappingVNext source ranges 和 existing T046 range audit 全部通过。

RateRewriteExecutionVNext report 顶层字段固定为：

format=rtl-obfuscation.rate-rewrite-execution-vnext
schema_version=1
state=gate-verified
rate_selection
rewrite_execution
summary

summary 固定包含 files、mapping_records、selected_renamed_records、rate_unselected_records、
modified_tokens、strict_compile_passed 和 restored_byte_identical。报告不得包含 source_root、gate_dir、
output_dir、TemporaryDirectory 或其他绝对路径。

## 5. strict gate 与 restore

selected gate 必须：

- 所有 physical files 按 input manifest 顺序输出；
- 使用 T046 同一 SourceSet compile context；
- catalog parse/semantic errors 为 0/0；
- 有 top 时 top-overlay parse/semantic errors 为 0/0；
- 未选 mapping 不产生 edit；
- output 或 strict compile 失败不发布部分目录；
- restore 后所有 physical files 与 gold byte-identical。

不得用 identity gate、复制 gold、删除 reference、放宽 diagnostic 或调用 legacy decrypt 作为证明。

## 6. Formal 正例与固定负例

目标 unittest 内必须真实生成 actual selected gate，并执行：

conda run -n rtl_obfuscation python scripts/formal_equivalence.py
  --gold-filelist tests/fixtures/refactor_symbol_graph_parameters/design.f
  --gold-root tests/fixtures/refactor_symbol_graph_parameters
  --gate-filelist <temporary-gate>/design.f
  --gate-root <temporary-gate>
  --top parameter_top
  --seq 5

正例要求：

- actual selected gate 至少有一个 physical file 与 gold 不同；
- selected gate strict compile 0/0；
- restore byte-identical；
- Formal exit 0；
- JSON 包含 formal_equivalence=pass、seq=5、top=parameter_top。

固定负例从 actual selected gate 复制，仅在 rtl/child.sv 的唯一
assign data_o = 后插入一个 ASCII ~：

- strict compile 仍为 0/0；
- 与正例相同 gold/filelist/top/seq；
- Formal exit 非 0；
- 输出包含 unproven 和 equiv_status -assert；
- 不接受 identity comparison 或先 restore 后 Formal。

## 7. 稳定错误码与负例矩阵

异常字符串固定以 <code>: 开头：

| condition | expected code |
| --- | --- |
| rate selection 类型、schema、mapping identity 或 selection identity 非法 | RATE_EXECUTION_INVALID |
| selected record、preserve reason、policy decision 或 record 顺序非法 | RATE_MAPPING_INVALID |
| gate range、manifest 或 strict compile 失败 | RATE_GATE_INVALID |
| restore execution、gate 或 bytes 非法 | RATE_RESTORE_INVALID |
| 输出路径已存在、重叠或 atomic I/O 失败 | RATE_OUTPUT_INVALID / RATE_IO_ERROR |

所有失败不得留下 gate、restore 或临时目录，不得捕获后降级成功。

## 8. 明确不包含

- 不修改 T049 greedy_unique_line_v1 算法或其 report schema；
- 不新增 CLI、encryption-rate 参数接线、project-root adapter 或三入口接线；
- 不实现 metrics adapter 或 RISC-V-Vector Formal；
- 不删除 legacy rewrite/inventory/decrypt 或旧 rate 分派；
- 不修改任何 RTL/formal fixture、README、renaming table 或 Formal 脚本。

## 9. 允许修改的文件

- rtl_obfuscator/rate_execution_vnext.py：selected mapping materialization 和 rate execution envelope；
- rtl_obfuscator/rewrite_vnext.py：只增加复用 T046 gate/restore 的必要公开桥接 API；
- tests/test_rate_execution_vnext.py：compact black-box、strict gate、restore、Formal 正负例；
- docs/tasks/T050_rate_selected_execution.md：状态、执行记录和主 Agent验收记录。

需要修改允许文件之外的内容时，子 Agent必须记录偏差并停止，不得自行扩大范围。

## 10. 目标测试与验收命令

目标测试必须覆盖：

1. full/top rate=0.35 selected mapping 的完整 record、preserve reason 和 report equations；
2. one-pass selected gate、strict compile、manifest、range audit 和 restore byte identity；
3. single/filelist normalized selected execution；
4. invalid selection/mapping/manifest/range/output 负例；
5. 阻断 SymbolGraph/mapping rebuild、legacy rewrite/decrypt 和 identity proof；
6. actual selected gate Formal 正例与一字节功能负例。

唯一验收命令：

conda run -n rtl_obfuscation python -m unittest tests.test_rate_execution_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rate_execution_vnext.py rtl_obfuscator/rewrite_vnext.py tests/test_rate_execution_vnext.py
git diff --check HEAD
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T050_rate_selected_execution.md

第一个 unittest 命令内部必须真实运行 Formal 正例和负例；不得运行 RISC、blanket discovery 或历史
全量 acceptance。

## 11. 子 Agent执行记录

status: NOT_STARTED
starting_head:
start_time:
baseline_command:
baseline_result:
changed_files:
commands:
results:
selected_mapping_summary:
strict_compile:
restore_summary:
formal_positive:
formal_negative:
formal_verification: PASS | FAIL | BLOCKED
deviations_or_blockers:
boundaries:
review_request:

## 12. READY_FOR_REVIEW 条件

- 状态严格为 READY_FOR_REVIEW，精确状态守卫通过；
- 目标测试、py_compile 和 git diff --check HEAD 全部通过；
- selected mapping 完整 record、unselected preserve 和 T049 identity 方程通过；
- selected gate strict compile 0/0、manifest/range audit 通过；
- restore 全部 physical files byte-identical；
- actual selected gate Formal 正例 pass；
- 固定一字节功能负例 strict compile 0/0 且 Formal 非 0；
- 不重建语义图、不复制 gold、不调用 legacy 路径；
- fixture hash、T046/T047/T048/T049 schema 未改变；
- 子 Agent不得设置 ACCEPTED、创建 T051、commit 或 push。

## 13. 主 Agent验收边界

主 Agent只独立复跑第 10 节四条命令，审查 selected mapping materialization、actual selected gate、
strict compile、restore 和 Formal 正负例；全部通过后写本节验收记录并设置 ACCEPTED。不增加 legacy、
RISC、全量回归、CLI 或隐藏 probe。

## 14. 主 Agent合同冻结记录（2026-07-23）

status: READY
baseline_commit: 1c8851f
decision: T049 accepted; freeze selected mapping materialization and rate-selected gate/restore before CLI integration
inputs: committed T043 parameter fixture + T049 RateSelectionVNext + T046 gate/restore engine
oracle: selected records preserve full occurrences; unselected rename records become rate_unselected preserve; strict 0/0; restore byte-identical; compact Formal +/- required
formal_verification: required actual selected gate positive and one-byte functional negative
forbidden: T049 algorithm changes, CLI, project-root, metrics adapter, RISC Formal, legacy compatibility, fixture edits, T051 creation
