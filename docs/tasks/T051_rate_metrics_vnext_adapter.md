# T051：rate-selected execution 到 metrics vNext 的审计适配器

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-H
- 前置任务：T050 `ACCEPTED`，交付提交 `2ad27a1`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 1–7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：mapping/metrics adapter；本任务不产生新的 rewritten RTL
- Formal verification：`N/A`，本任务只消费 T050 已生成并验证过的 actual selected gate，新增的是
  T047/T048 审计连接，不新增 rewrite 行为

## 1. 单一目标

把 T050 的 `RateRewriteExecutionVNext` 接入 T047 `MappingExecutionVNext` 和 T048
`MetricsVNext`，形成一个可审计、可移植、带 rate selection 关联的 vNext 服务对象：

1. 只消费 T050 已建立的 rate-selected execution、gate manifest 和实际 gate bytes；
2. 通过 T050 restore API 产生真实 `RestoreResult`，再构造 T047 mapping execution envelope；
3. 通过 T048 `build_metrics_vnext()` 审计 actual selected gate 的 effective lines、affected lines、
   symbol/occurrence coverage 和 plaintext leakage；
4. 保持 rate selection、selected mapping、T047 envelope 和 T048 metrics 的对象 identity 关系；
5. 输出不含绝对路径的 canonical report，供后续 single-file/filelist CLI adapter 直接消费。

本任务不修改旧 CLI、不接入 project-root、不实现新的 gate/rewrite engine，也不改变 T047/T048/T050
既有 report schema。

## 2. 固定输入

只读复用 T043–T050 已提交 compact fixture 和公开 API：

```text
tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/closure.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv
```

测试先用 T045 deterministic `name_factory` 建立真实 `MappingVNext`，用 T049
`build_rate_selection_vnext(mapping, "0.35")` 和 T050
`write_rate_selected_gate_vnext()` 生成 actual selected gate，再调用本任务 adapter。所有 gate、
restore 和负例写入 `TemporaryDirectory`；不新增或修改 RTL/formal fixture，18 个冻结 fixture hash
必须保持不变。

## 3. 固定公开 API

新增 `rtl_obfuscator/rate_metrics_vnext.py`，公开对象固定为：

```python
@dataclass(frozen=True)
class RateMetricsVNext:
    schema_version: int
    rate_execution: RateRewriteExecutionVNext = field(repr=False, compare=False)
    mapping_execution: MappingExecutionVNext = field(repr=False, compare=False)
    metrics: MetricsVNext = field(repr=False, compare=False)

    def to_report(self) -> dict[str, object]: ...

def build_rate_metrics_vnext(
    rate_execution: RateRewriteExecutionVNext,
    *,
    gate_dir: Path,
    restore_dir: Path,
) -> RateMetricsVNext: ...
```

`build_rate_metrics_vnext()` 的固定顺序为：

1. 验证输入为 T050 `RateRewriteExecutionVNext` 且 schema/selection/mapping identity 合法；
2. 调用 `restore_rate_selected_gate_vnext(rate_execution, gate_dir, restore_dir)`，不得读取 gold；
3. 调用 `build_mapping_execution_vnext(rate_execution.rewrite_execution, restore_result)`；
4. 调用 `build_metrics_vnext(mapping_execution, gate_dir=gate_dir)`；
5. 验证 `mapping_execution.rewrite_execution is rate_execution.rewrite_execution`，
   `metrics.mapping_execution is mapping_execution`，然后返回 envelope。

不得重新调用 `build_source_catalog()`、`build_symbol_graph()`、`build_rewrite_policy()`、
`build_mapping_vnext()` 或 T049 selector；不得调用 `rtl_obfuscator.rewrite` 的 legacy encrypt、
decrypt、inventory 或 rate helper。

## 4. Report schema 与不变量

`RateMetricsVNext.to_report()` 顶层 key 和顺序固定为：

```text
format = rtl-obfuscation.rate-metrics-vnext
schema_version = 1
state = restored
rate_selection
mapping_execution
metrics
summary
```

`summary` 固定包含：

```text
files
mapping_records
selected_renamed_records
rate_unselected_records
modified_tokens
strict_compile_passed
restored_byte_identical
effective_line_total
affected_line_count
symbol_coverage
occurrence_coverage
plaintext_leakage_rate
effective_coverage
```

必须满足：

- `rate_selection` 直接来自 T050 `RateSelectionVNext.to_report()`；
- `mapping_execution` 直接来自 T047 `MappingExecutionVNext.to_report()`；
- `metrics` 直接来自 T048 `MetricsVNext.to_report()`；
- selected mapping 的 `rename`、`rate_unselected` preserve 和 occurrence edits 与 T050 一致；
- T047 `restored_input_manifest_equal`、`restored_byte_identical` 与 T048 `state=verified` 必须成立；
- `strict_compile_passed` 必须为 true，restore 后全部 physical files byte-identical；
- 所有路径只能是 SourceSet 相对 POSIX 路径；report 不得出现 `source_root`、`gate_dir`、
  `restore_dir`、`TemporaryDirectory` 或其他绝对路径；
- 在 deterministic `name_factory` 下，连续两次 report 的 canonical JSON 必须 byte-identical。

## 5. 稳定错误码与失败边界

异常字符串固定以 `<code>: ` 开头：

| condition | expected code |
| --- | --- |
| 输入类型、schema、selection 或 mapping identity 非法 | `RATE_METRICS_EXECUTION_INVALID` |
| T050 gate、restore 或 restored bytes 非法 | `RATE_METRICS_RESTORE_INVALID` |
| T047 envelope identity、manifest 或 per-file projection 非法 | `RATE_METRICS_ENVELOPE_INVALID` |
| T048 metrics equations、manifest 或 gate leakage audit 非法 | `RATE_METRICS_INVALID` |

失败必须 fail-closed，不得吞掉异常后返回部分 report；`restore_dir` 失败时不得留下成功标记的
envelope。不得通过重新建立 identity mapping、复制 gold 或 restore 后再伪造 gate 证据来通过测试。

## 6. 明确不包含

- 不修改 T047 `MappingExecutionVNext` 或 T048 `MetricsVNext` 既有字段和 report schema；
- 不修改 T050 `RateRewriteExecutionVNext`、selected mapping、gate/restore API 或 T049 selector；
- 不修改 `rtl_obfuscator/rewrite.py`，不新增 argparse、CLI 或用户命令；
- 不接入 `project-root`、`from_project_root()` 或三入口 wiring；
- 不新增 gate/rewrite engine，不重建 SourceSet/SymbolGraph/MappingVNext；
- 不调用 legacy inventory/rewrite/decrypt/rate 路径；
- 不修改任何 RTL/formal fixture、README、renaming table、Formal 脚本或历史测试；
- 不运行 RISC-V-Vector Formal。

## 7. 允许修改的文件

- `rtl_obfuscator/rate_metrics_vnext.py`：rate execution 到 mapping/metrics 的单一审计适配器；
- `tests/test_rate_metrics_vnext.py`：真实 T050 gate、T047 envelope、T048 metrics 的 compact 黑盒测试；
- `docs/tasks/T051_rate_metrics_vnext_adapter.md`：状态、执行记录和主 Agent 验收记录。

需要修改允许列表外文件时，子 Agent 必须先在本任务记录偏差并停止，不得自行扩大范围。

## 8. 目标测试与验收命令

目标测试必须覆盖：

1. full/top rate=0.35 的 actual selected gate 到 T047/T048 的完整适配和 report schema；
2. selected mapping、rate selection、mapping execution、metrics 的 identity 和 summary equations；
3. restore 全部 physical files byte-identical，T047 manifest 与 T048 metrics verified；
4. single-file 与 filelist 的 normalized report 一致；
5. deterministic JSON byte identity、相对路径可移植性和 no-absolute-path；
6. 非法 execution/restore/envelope/metrics 输入 fail-closed；
7. 阻断 semantic graph/mapping rebuild、legacy path 和 identity proof。

唯一验收命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_rate_metrics_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rate_metrics_vnext.py tests/test_rate_metrics_vnext.py
git diff --check HEAD
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T051_rate_metrics_vnext_adapter.md
```

本任务不运行 Formal：它不新增 rewritten RTL，只消费 T050 已经通过 compact Formal 的 actual
selected gate；子 Agent 必须在执行记录写明 `formal_verification: N/A` 及该原因。

## 9. 子 Agent执行记录

```text
status: READY_FOR_REVIEW
starting_head: 7884b5e0212fbf8a9fda8c3ed53fd15bbd9e4bb7
start_time: 2026-07-23T16:45:28+08:00
starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 1]`; no other status entries
prerequisites: HEAD contains `2ad27a1`; T047/T048/T049/T050 are ACCEPTED; no other IN_PROGRESS or READY_FOR_REVIEW task was found
allowed_files: rtl_obfuscator/rate_metrics_vnext.py; tests/test_rate_metrics_vnext.py; docs/tasks/T051_rate_metrics_vnext_adapter.md
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_rate_metrics_vnext -v`
baseline_result: `ModuleNotFoundError: No module named 'tests.test_rate_metrics_vnext'`; Ran 1 test in 0.000s, FAILED, exit_code=1
changed_files: rtl_obfuscator/rate_metrics_vnext.py; tests/test_rate_metrics_vnext.py; docs/tasks/T051_rate_metrics_vnext_adapter.md
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_rate_metrics_vnext -v` — actual output: Ran 4 tests in 0.152s; OK; exit_code=0.
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rate_metrics_vnext.py tests/test_rate_metrics_vnext.py` — actual output: no stdout/stderr; exit_code=0.
  - `git diff --check HEAD` — actual output: no stdout/stderr; exit_code=0.
  - `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T051_rate_metrics_vnext_adapter.md` — actual output: `- 状态：READY_FOR_REVIEW`; exit_code=0.
results: T051 adapter tests, py_compile, and diff check passed; the test module exercised actual T050 restore, T047 envelope, and T048 metrics without Formal.
rate_metrics_summary: actual selected gate from design.f with top=parameter_top and rate=0.35 was adapted to format `rtl-obfuscation.rate-metrics-vnext`, schema_version=1, state=restored, with all four physical files audited. Metrics report state was `verified`, symbol/occurrence coverage was complete, plaintext leakage was 0.0, and effective coverage was 1.0.
identity_result: PASS; the returned RateMetricsVNext retained the exact RateRewriteExecutionVNext object, T047 MappingExecutionVNext retained the exact T050 RewriteExecution object, and T048 MetricsVNext retained the exact T047 envelope object. Selection and selected-mapping semantic graph identity was also checked without rebuilding it.
restore_summary: PASS; T050 restore API produced the actual RestoreResult, restored manifest equaled the input manifest, and every physical file in restore_dir was byte-identical to the source bytes.
report_result: PASS; fixed top-level key order and summary equations passed; rate selection, mapping execution, and metrics reports were projected with portable relative paths, without source_root/gate_dir/restore_dir/TemporaryDirectory or absolute paths. Single-file and filelist canonical JSON matched byte-for-byte, and repeated JSON was deterministic.
formal_verification: N/A; this task only audits the T050 already verified actual selected gate and produces no new rewritten RTL.
deviations_or_blockers: none
boundaries: no CLI, project-root, legacy rewrite/decrypt/inventory/rate helper, semantic rebuild, fixture, README, planning-document, or Formal-script changes. T050 does not carry its original MappingVNext as a separate field, so this adapter verifies selection-to-selected-mapping relation through the existing shared SymbolGraph object identity without reconstructing inputs.
review_request: READY_FOR_REVIEW; Main Agent may independently rerun the four commands in section 8.
```

## 10. READY_FOR_REVIEW 条件

- 状态严格为 `READY_FOR_REVIEW`，精确状态守卫通过；
- 目标 unittest、py_compile 和 `git diff --check HEAD` 全部通过；
- actual selected gate 经过 T050 restore，T047 envelope 和 T048 metrics 均为 verified；
- report 顶层 schema、summary equations、identity、portable paths 和 deterministic JSON 全部通过；
- invalid execution/restore/envelope/metrics 负例 fail-closed；
- 只修改本合同第 7 节列出的三个文件；
- `formal_verification: N/A` 已记录，并明确本任务不产生新的 rewritten RTL；
- 子 Agent 不得设置 `ACCEPTED`、创建 T052、commit 或 push。

## 11. 主 Agent验收边界

主 Agent只独立复跑第 8 节四条命令，审查真实 T050 actual selected gate、T047/T048 identity、
restore byte identity 和 portable report；全部通过后写本节验收记录并设置 `ACCEPTED`。不增加
legacy、RISC、全量回归、CLI 或隐藏 probe。

## 12. 主 Agent合同冻结记录（2026-07-23）

```text
status: READY
baseline_commit: 2ad27a1
decision: T050 accepted; freeze the smallest rate-selected T047/T048 audit bridge before CLI wiring
inputs: T050 RateRewriteExecutionVNext + T047 MappingExecutionVNext + T048 MetricsVNext
oracle: actual selected gate restored byte-identically; mapping/metrics identity preserved; portable deterministic rate-metrics report
formal_verification: N/A - no new rewritten RTL is produced by this adapter
forbidden: CLI, project-root, legacy paths, selector changes, gate engine changes, fixture edits, T052 creation

## 13. 主 Agent验收记录（2026-07-23）

```text
status: ACCEPTED
reviewed_head: 7884b5e0212fbf8a9d8c3ed53fd15bbd9e4bb7
prerequisites: PASS; T047/T048/T049/T050 已 ACCEPTED，T051 是唯一 READY_FOR_REVIEW 任务
scope: PASS; 实际修改仅限 rate_metrics_vnext.py、test_rate_metrics_vnext.py 和本任务合同
acceptance_commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_rate_metrics_vnext -v` — 4 tests，OK，exit_code=0
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rate_metrics_vnext.py tests/test_rate_metrics_vnext.py` — exit_code=0
  - `git diff --check HEAD` — exit_code=0
  - `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T051_rate_metrics_vnext_adapter.md` — 状态更新前匹配成功，exit_code=0
rate_metrics: PASS; actual T050 selected gate 经 restore 后建立 T047 envelope 和 T048 verified metrics，report schema、summary equations、portable paths 和 deterministic JSON 均通过
identity: PASS; RateRewriteExecutionVNext、MappingExecutionVNext、MetricsVNext 三层对象 identity 保持，未重建 semantic graph、mapping 或 selector
restore: PASS; restored manifest 等于 input manifest，所有 physical files byte-identical
negative_cases: PASS; 非法 execution、restore、envelope 和 metrics 输入 fail-closed，且 legacy/rebuild/identity proof 均被测试阻断
formal_verification: N/A; 本任务只审计 T050 已验证的 actual selected gate，未产生新的 rewritten RTL
decision: ACCEPTED
next_step: T051 可提交交付；下一任务应另行冻结 T052 single-file/filelist CLI adapter，不在本任务中实现
```
```
