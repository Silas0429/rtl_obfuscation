# T052：single-file/filelist vNext orchestration service

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-I
- 前置任务：T051 `ACCEPTED`，交付提交 `50a4e8e`
- 设计基线：`d6a6fa4`；T050/T051 计划文档已同步
- 设计依据：`docs/three_mode_refactor_plan.md` 第 1–7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：adapter/orchestration；本任务实际生成 rewritten RTL
- Formal verification：必须在目标 unittest 内真实执行 compact actual gate 正例和固定功能负例

## 1. 单一目标

建立一个只面向 `single-file` 和显式 `filelist` 的程序化 vNext orchestration service，把已经
验收的 T039–T051 API 串成一条可重复调用的流程：

```text
SourceSet
  -> SourceCatalog
  -> SymbolGraph
  -> RewritePolicy
  -> MappingVNext
  -> [optional RateSelectionVNext + RateRewriteExecutionVNext]
  -> gate / restore
  -> MappingExecutionVNext
  -> MetricsVNext
  -> optional RateMetricsVNext
```

本任务只建立 service API 和结果 envelope，不接入 argparse 或旧 `rewrite.py` CLI。后续 T053
才负责用户-facing single/filelist CLI wiring；R4 才接入 project-root。

## 2. 固定公开 API

新增 `rtl_obfuscator/orchestration_vnext.py`，公开对象固定为：

```python
@dataclass(frozen=True)
class OrchestrationVNext:
    schema_version: int
    source_set: SourceSet = field(repr=False, compare=False)
    mapping_vnext: MappingVNext = field(repr=False, compare=False)
    effective_mapping_vnext: MappingVNext = field(repr=False, compare=False)
    mapping_execution: MappingExecutionVNext = field(repr=False, compare=False)
    metrics: MetricsVNext = field(repr=False, compare=False)
    rate_metrics: RateMetricsVNext | None = field(repr=False, compare=False)

    def to_report(self) -> dict[str, object]: ...

def run_vnext(
    source_set: SourceSet,
    *,
    categories: Iterable[str],
    abi_categories: Iterable[str] = (),
    name_length: int = 20,
    name_factory: NameFactory = secure_name_factory,
    encryption_rate: str | None = None,
    gate_dir: Path,
    restore_dir: Path,
) -> OrchestrationVNext: ...
```

`run_vnext()` 必须只接受 `SourceSet.origin` 为 `single-file` 或 `filelist`；传入
`project-root` 必须 fail-closed。single-file/filelist 的输入对象由已有
`from_single_file()`/`from_filelist()` 建立，本任务不得复制 SourceSet discovery。

## 3. 固定执行语义

### 3.1 公共前半段

1. 验证 SourceSet schema、origin、路径和 `gate_dir`/`restore_dir` 入口；
2. 调用 `build_source_catalog(source_set)`；
3. 调用 `build_symbol_graph(source_catalog)`；
4. 调用 `build_rewrite_policy(graph, categories=..., abi_categories=...)`；
5. 调用 `build_mapping_vnext(policy, name_length=..., name_factory=...)`。

上述对象必须按 identity 传递；不得重建第二套 SourceCatalog、SymbolGraph、RewritePolicy 或
MappingVNext。`secure_name_factory` 是默认生产命名器，测试必须注入 T045 deterministic
`name_factory`。

### 3.2 无 rate 路径

当 `encryption_rate is None`：

1. `effective_mapping_vnext is mapping_vnext`；
2. 调用 T046 `write_gate_vnext()`；
3. 调用 T046 `restore_gate_vnext()`；
4. 调用 T047 `build_mapping_execution_vnext()`；
5. 调用 T048 `build_metrics_vnext()`；
6. `rate_metrics is None`。

### 3.3 rate 路径

当 `encryption_rate` 非空：

1. 调用 T049 `build_rate_selection_vnext(mapping_vnext, encryption_rate)`；
2. 调用 T050 `write_rate_selected_gate_vnext(mapping_vnext, rate_selection, gate_dir)`；
3. 调用 T051 `build_rate_metrics_vnext(rate_execution, gate_dir=gate_dir, restore_dir=restore_dir)`；
4. `effective_mapping_vnext` 必须等于 T050 execution 中的 selected mapping；
5. `mapping_execution` 和 `metrics` 必须直接引用 T051 `RateMetricsVNext` 中的同名对象；
6. `rate_metrics` 必须保留 T049 selection、T050 execution、T047 envelope 和 T048 metrics 的关联。

不得在 rate 路径中再次调用 `write_gate_vnext()`、`restore_gate_vnext()`、selector、semantic
graph 或 mapping builder。

两条路径都必须最终得到 strict gate、restore manifest、mapping execution 和 verified metrics。
所有输出目录必须由既有 T046/T050 原子语义创建，不得发布半成品。

## 4. Report schema 与不变量

`OrchestrationVNext.to_report()` 顶层 key 和顺序固定为：

```text
format = rtl-obfuscation.orchestration-vnext
schema_version = 1
state = restored
source_set
mapping
mapping_execution
metrics
rate_metrics
summary
```

其中：

- `source_set` 只包含 portable 的 `origin`、ordered/included files、include dirs、defines、top、
  top closure 和 compile order，不得出现绝对 `source_root`；
- `mapping` 是原始完整 MappingVNext report；
- `mapping_execution` 是实际执行 mapping 的 T047 report；无 rate 时等于原始 mapping，有 rate 时
  是 selected mapping；
- `metrics` 是实际执行 mapping 对应的 T048 verified report；
- `rate_metrics` 无 rate 时为 `null`，有 rate 时直接为 T051 report；
- 所有 nested report 不得包含 `gate_dir`、`restore_dir`、TemporaryDirectory 或绝对路径。

`summary` 固定包含：

```text
origin
top
rate_enabled
files
mapping_records
effective_mapping_records
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

- `source_set` 与 `mapping_vnext.rewrite_policy.symbol_graph.source_catalog.source_set` identity 一致；
- `effective_mapping_vnext` 与 `mapping_execution.rewrite_execution.mapping_vnext` identity 一致；
- `metrics.mapping_execution is mapping_execution`；
- 无 rate 时 `mapping_vnext is effective_mapping_vnext` 且 `rate_metrics is None`；
- 有 rate 时 `rate_metrics.rate_execution.rate_selection.mapping_vnext is mapping_vnext`，
  `rate_metrics.mapping_execution is mapping_execution`，`rate_metrics.metrics is metrics`；
- strict compile 通过，T047 restored manifest 等于 input manifest，所有 physical files byte-identical；
- deterministic `name_factory` 下相同输入连续两次 canonical JSON byte-identical；
- single-file 与只含同一个 `.sv` 的等价 filelist report normalized 且 byte-identical；
- 输入 filelist 顺序和 SourceSet compile order 不得被排序或改写。

## 5. 稳定错误与失败边界

异常字符串固定以 `<code>: ` 开头：

| condition | expected code |
| --- | --- |
| 输入不是 SourceSet、schema 非 1 或 origin 为 project-root | `ORCHESTRATION_INPUT_INVALID` |
| SourceCatalog/SymbolGraph/RewritePolicy/MappingVNext 建立失败 | `ORCHESTRATION_MAPPING_INVALID` |
| gate、restore、manifest 或 strict compile 失败 | `ORCHESTRATION_EXECUTION_INVALID` |
| encryption rate 非法或 selection/execution 失败 | `ORCHESTRATION_RATE_INVALID` |
| T047/T048/T051 envelope 或 metrics 不一致 | `ORCHESTRATION_AUDIT_INVALID` |

失败必须 fail-closed，不得捕获异常后跳过对象、降级到 legacy、返回 identity mapping 或发布
部分 gate/restore/report。输出目录失败时不得留下成功产物。

## 6. 明确不包含

- 不修改 `rewrite.py`、`inventory.py`、`project.py`、`source_set.py` 或任何 T039–T051 core module；
- 不新增 argparse、CLI operation、CLI 参数或旧 mapping v1/v2/v3/v4 分派；
- 不接入 `from_project_root()`、project-root discovery 或 R4 行为；
- 不实现新的 gate、restore、metrics、rate selector 或 name factory；
- 不调用 legacy encrypt/decrypt/inventory/rate helper；
- 不修改任何 RTL/formal fixture、README、renaming table、Formal 脚本或历史测试；
- 不运行 RISC-V-Vector Formal；
- 不创建 T053，不执行 git add、commit 或 push。

## 7. 允许修改的文件

- `rtl_obfuscator/orchestration_vnext.py`：single/filelist vNext orchestration service 和结果 envelope；
- `tests/test_orchestration_vnext.py`：无 rate/有 rate、等价入口、失败边界和 compact Formal 正负例；
- `docs/tasks/T052_orchestration_vnext.md`：状态、执行记录和主 Agent 验收记录。

需要修改允许列表外文件时，子 Agent 必须先记录偏差并停止，不得自行扩大范围。

## 8. 固定输入与测试 oracle

只读复用 T043–T051 compact fixture：

```text
tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv
```

测试必须使用：

- full/top filelist：`design.f`，top=`parameter_top`，categories=`("signals", "parameters", "genvars")`，
  abi_categories=`("parameters",)`；
- equivalent single-file/filelist：`single.sv` 与 `single.f`，相同 categories 和 deterministic name factory；
- rate 正例：`encryption_rate="0.35"`；
- no-rate 正例：`encryption_rate=None`；
- 所有 gate/restore/negative 输出均置于 `TemporaryDirectory`。

目标测试至少覆盖：

1. no-rate full/top actual gate、restore、T047/T048 metrics 和 report；
2. rate full/top actual selected gate、T051 rate report 和 identity equations；
3. single-file/filelist normalized deterministic report；
4. project-root、非法 rate、非法 output、manifest/restore、duplicate/rebuild/legacy 负例；
5. actual selected gate Formal 正例和仅插入一个 ASCII `~` 的功能负例；
6. catalog/graph/policy/mapping builder 各只建立输入流水线所需对象，且不调用 legacy path。

Formal 正例必须使用 actual gate、gold `design.f`、top=`parameter_top`、seq=`5`，JSON 必须包含
`formal_equivalence=pass`；固定负例 strict compile 仍为 0/0，Formal 非 0，并包含 `unproven` 和
`equiv_status -assert`。不得使用 identity comparison、复制 gold 或先 restore 后 Formal。

## 9. 目标验收命令

唯一验收命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_orchestration_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/orchestration_vnext.py tests/test_orchestration_vnext.py
git diff --check HEAD
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T052_orchestration_vnext.md
```

第一个 unittest 命令内部必须真实执行 actual selected gate 的 Formal 正例和固定功能负例；不得
运行 RISC Formal、blanket discovery 或历史全量 acceptance。

## 10. 子 Agent执行记录

```text
status: READY_FOR_REVIEW
starting_head: 973df1d16a0885e77ea391e918285b4c4ad8c339
start_time: 2026-07-24T09:50:34+08:00
starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 3]`; no other status entries
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_orchestration_vnext -v`
baseline_result: `ModuleNotFoundError: No module named 'tests.test_orchestration_vnext'`; Ran 1 test in 0.000s, FAILED, exit_code=1
allowed_files: rtl_obfuscator/orchestration_vnext.py; tests/test_orchestration_vnext.py; docs/tasks/T052_orchestration_vnext.md
changed_files: rtl_obfuscator/orchestration_vnext.py; tests/test_orchestration_vnext.py; docs/tasks/T052_orchestration_vnext.md
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_orchestration_vnext -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/orchestration_vnext.py tests/test_orchestration_vnext.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T052_orchestration_vnext.md`
results: rerun unittest printed six named tests, `Ran 6 tests in 0.335s`, `OK`, exit_code=0; rerun py_compile produced no stdout/stderr, exit_code=0; rerun `git diff --check HEAD` produced no stdout/stderr, exit_code=0; final status guard matched `- 状态：READY_FOR_REVIEW`, exit_code=0
no_rate_summary: actual full/top no-rate gate and restore produced 4 physical files, 20 mapping records, 41 modified tokens, strict compile 0/0, restored byte identity true; T047 state was restored and T048 state was verified with symbols 16/16/1.0, occurrences 41/41/1.0, plaintext leakage 0.0, effective coverage 1.0, and affected-line total equal to the effective-line denominator
rate_summary: actual full/top `encryption_rate="0.35"` selected-gate path reused T049 selection, T050 one-pass execution, T051 restore/metrics adapter, and retained complete selected/unselected record semantics; strict compile 0/0, restored byte identity true, and the report was portable and deterministic
identity_result: PASS; SourceSet identity was retained through SourceCatalog, SymbolGraph, RewritePolicy, MappingVNext, and the final report; no-rate effective mapping was the original MappingVNext; rate effective mapping was the T050 selected mapping; T047 MappingExecutionVNext and T048 MetricsVNext identities were retained, with T051 RateMetricsVNext retaining the rate association
restore_summary: PASS; both paths used the established restore API, input/gate/restored manifests were audited by T047, all physical restored files were byte-identical, and failed restore/audit cases removed gate/restore artifacts
formal_positive: PASS; unittest ran Formal on the actual selected gate using gold `design.f`, top `parameter_top`, seq `5`; JSON contained `formal_equivalence=pass`
formal_negative: PASS; unittest copied only the actual selected gate, inserted one ASCII `~` after the unique `assign data_o = `, confirmed strict compile 0/0, and Formal exited non-zero with `unproven` and `equiv_status -assert`
formal_verification: PASS; actual rewritten RTL was produced by this task and the required positive/negative Formal flow passed inside the target unittest
deviations_or_blockers: previous review blocker corrected; verified contract/current task commit is `973df1d16a0885e77ea391e918285b4c4ad8c339`, and the starting worktree record is `## main...origin/main [ahead 3]` with no status entries. This correction pass changed no implementation files and did not expand scope.
boundaries: no CLI, project-root, legacy rewrite/inventory/decrypt/rate helper, second semantic graph/mapping/rate/gate engine, fixture, README, planning-document, or Formal-script changes; single-file/filelist equality is checked on normalized reports because the required report retains origin
review_request: READY_FOR_REVIEW; Main Agent may independently rerun the four commands in section 9
```

## 11. READY_FOR_REVIEW 条件

- 状态严格为 `READY_FOR_REVIEW`，精确状态守卫通过；
- unittest、py_compile、`git diff --check HEAD` 全部通过；
- no-rate 和 rate 两条路径均生成 actual gate、restore、T047 envelope 和 T048 verified metrics；
- single/filelist normalized report、identity、summary equations 和 portable paths 通过；
- actual selected gate Formal 正例通过，固定功能负例按预期失败；
- project-root、非法 rate、output、manifest、rebuild 和 legacy 负例 fail-closed；
- 只修改本合同第 7 节列出的三个文件；
- 子 Agent 不得设置 `ACCEPTED`、创建 T053、commit 或 push。

## 12. 主 Agent验收边界

主 Agent只独立复跑第 9 节四条命令，审查 no-rate/rate actual gate、restore、T047/T048/T051
identity、normalized report 和 Formal 正负例；全部通过后写本节验收记录并设置 `ACCEPTED`。
不增加 legacy、RISC、全量回归、CLI 或隐藏 probe。

## 13. 主 Agent合同冻结记录（2026-07-24）

```text
status: READY
baseline_commit: d6a6fa4
decision: T051 accepted; freeze the single/filelist orchestration service before CLI wiring
inputs: T039 SourceSet adapters + T040–T045 semantic/mapping core + T046–T051 execution/audit APIs
oracle: no-rate and rate actual gates; restore byte identity; T047/T048/T051 identity; normalized portable report; compact Formal +/-
formal_verification: required because this task produces actual rewritten RTL
forbidden: CLI argparse, project-root, legacy compatibility, new engines, fixture edits, T053 creation

## 14. 主 Agent验收记录（2026-07-24）

```text
status: ACCEPTED
reviewed_head: 973df1d16a0885e77ea391e918285b4c4ad8c339
prerequisites: PASS; T047/T048/T049/T050/T051 已 ACCEPTED，T052 是唯一 READY_FOR_REVIEW 任务
scope: PASS; 最终修改仅限 orchestration_vnext.py、test_orchestration_vnext.py 和本任务合同；修正基线记录阶段未修改实现文件
acceptance_commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_orchestration_vnext -v` — 6 tests，OK，exit_code=0；实际执行 Formal 正负例
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/orchestration_vnext.py tests/test_orchestration_vnext.py` — exit_code=0
  - `git diff --check HEAD` — exit_code=0
  - `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T052_orchestration_vnext.md` — 状态更新前匹配成功，exit_code=0
no_rate: PASS; 4 physical files、20 mapping records、41 edits，strict compile 0/0，T047 restored，T048 verified，restore byte-identical
rate: PASS; rate=0.35 复用 T049/T050/T051，selected mapping、rate metrics、restore 和 portable deterministic report 全部通过
identity: PASS; SourceSet、MappingVNext、effective mapping、MappingExecutionVNext、MetricsVNext 和 RateMetricsVNext identity 保持
normalized_report: PASS; single-file/filelist canonical report byte-identical，未包含绝对路径或受保护路径字段
formal_positive: PASS; actual selected gate Formal JSON 为 `formal_equivalence=pass`，top=`parameter_top`，seq=5
formal_negative: PASS; 单字节 `~` 负例 strict compile 0/0，Formal 非 0，输出包含 `unproven` 和 `equiv_status -assert`
negative_cases: PASS; project-root、非法 rate/output/restore、manifest、rebuild 和 legacy 路径均 fail-closed
formal_verification: PASS
decision: ACCEPTED
next_step: T052 可提交交付；下一任务为另行冻结的 T053 single/filelist CLI wiring，不在本任务中实现
```
```
