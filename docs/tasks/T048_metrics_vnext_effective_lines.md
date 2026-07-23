# T048：metrics vNext effective-line、coverage 与 leakage 基线

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-E
- 前置任务：T047 `ACCEPTED`，交付提交 `a1e757a`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 1–7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：metrics；本任务不新增 rewritten RTL
- Formal verification：`N/A`，本任务只读取已验证的 MappingExecutionVNext、源 bytes 和 gate bytes 计算审计指标

## 1. 单一目标

在 T047 `MappingExecutionVNext` 之上建立新架构的第一版 metrics 计算和 JSON 报告：

1. 冻结唯一 effective-line 分母；
2. 计算实际 rename edits 覆盖的唯一 affected lines；
3. 计算 symbol/occurrence coverage 和 effective coverage；
4. 从 actual gate bytes 计算 plaintext leakage rate；
5. 原子写出可移植的 metrics JSON；
6. 只消费 T047 envelope 和源/gate bytes，不重建 SourceSet、SourceCatalog、SymbolGraph、
   RewritePolicy 或 MappingVNext，不调用 legacy metrics/rewrite/decrypt。

本任务不实现 `--encryption-rate` 选择器。rate selection 另由后续任务冻结，不能将目标率字段
或 greedy 候选选择提前混入本任务。

## 2. 固定输入

只读复用 T043–T047 已提交的 compact 输入和公开 API：

```text
tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/closure.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv
```

测试使用 T045 deterministic `name_factory`、T046 `write_gate_vnext()`/`restore_gate_vnext()` 和
T047 `build_mapping_execution_vnext()` 取得真实 envelope；metrics 读取 envelope 对应的 original
source bytes 和 actual gate physical bytes，所有输出与负例写入 `TemporaryDirectory`。

不新增或修改 RTL/formal fixture；18 个冻结 fixture hash 必须保持不变。

## 3. 固定公开 API

新增 `rtl_obfuscator/metrics_vnext.py`，提供以下公开对象：

```python
@dataclass(frozen=True)
class MetricsVNext:
    schema_version: int
    mapping_execution: MappingExecutionVNext = field(repr=False, compare=False)
    effective_line_total: int
    affected_line_count: int
    symbol_count: int
    occurrence_count: int
    plaintext_leakage_count: int

    def to_report(self) -> dict[str, object]: ...

def build_metrics_vnext(
    mapping_execution: MappingExecutionVNext,
    *,
    gate_dir: Path,
) -> MetricsVNext: ...

def write_metrics_vnext(
    metrics: MetricsVNext,
    *,
    output_file: Path,
) -> None: ...
```

`build_metrics_vnext()` 必须只接受 `MappingExecutionVNext`，并验证 envelope schema/state、manifest
顺序、gate manifest hash 和实际 gate bytes；不得接受 duck-typed dict 或重新生成 mapping。所有
源/gate 文件读取只能按 envelope 的 physical file 顺序进行。

## 4. effective-line 与 affected-line 定义

每个 physical source file 使用 UTF-8 bytes 按 `splitlines()` 分行；effective line 唯一定义为：

```python
line.strip() != b"" and not line.strip().startswith(b"//")
```

因此空行、纯空白行和纯 `//` 注释行不进入分母；未以换行符结尾的非空最后一行计入；`.svh`
physical file 也按同样规则计数。filelist、mapping、metrics 和 maps 文件不计入分母。

`affected_lines.changed` 是所有 `AppliedEdit.source_range` 覆盖的唯一 `(file, 1-based line)` 集合；
同一行多个 token 只计一次。`affected_lines.total` 与 `effective_lines.total` 使用同一分母，
`affected_lines.rate` 定义为：

```text
changed / effective_lines.total
```

当 effective-line 总数为 0 时，rate 固定为 `0.0`，不得产生 NaN 或异常。

## 5. metrics report schema

`MetricsVNext.to_report()` 顶层 key 和顺序固定为：

```text
format = rtl-obfuscation.metrics-vnext
schema_version = 1
state = verified
mapping_execution_format = rtl-obfuscation.mapping-execution-vnext
filelist = design.f
effective_lines
affected_lines
symbols
occurrences
plaintext_leakage_rate
effective_coverage
```

字段要求：

```json
{
  "effective_lines": {"total": 0, "by_file": [{"file": "...", "lines": 0}]},
  "affected_lines": {"changed": 0, "total": 0, "rate": 0.0, "by_file": [{"file": "...", "lines": 0}]},
  "symbols": {"renamed": 0, "eligible": 0, "coverage": 1.0},
  "occurrences": {"renamed": 0, "eligible": 0, "coverage": 1.0},
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 1.0
}
```

`by_file` 顺序必须等于 T047 input manifest。`symbols.eligible` 是 action=`rename` 的 mapping record
数，`symbols.renamed` 是实际出现在 per-file mapping 的 rename record 数。`occurrences.eligible`
是 rename record 的 declaration 加 occurrences 总数，`occurrences.renamed` 是实际 AppliedEdit 数。
coverage 为 renamed/eligible；没有 eligible 项时 coverage 固定为 `1.0`。

`plaintext_leakage_count` 是 actual gate 中仍出现在对应 gate range 的 original identifier 次数；
`plaintext_leakage_rate` 为 leakage_count/occurrences.eligible，无 eligible 项时固定为 `0.0`。
`effective_coverage` 定义为 symbol/occurrence coverage 的几何平均；两者均为 `1.0` 时必须为 `1.0`。

compact top 固定 oracle：

```text
files=4
symbols.renamed=16, symbols.eligible=16, symbols.coverage=1.0
occurrences.renamed=41, occurrences.eligible=41, occurrences.coverage=1.0
plaintext_leakage_rate=0.0
effective_coverage=1.0
affected_lines.changed > 0
affected_lines.total == effective_lines.total
0.0 < affected_lines.rate <= 1.0
```

`effective_lines.total` 和 per-file 行数必须由实际 source bytes 计算，不得硬编码 compact 数量。
确定性 NameFactory 下，连续两次 metrics report JSON 必须 byte-identical。

## 6. 原子 metrics JSON 输出

`write_metrics_vnext()` 要求：

- `output_file` 不存在，父目录存在且为目录；
- output 不得位于 source_root、gate_dir 或 physical source/gate file 内；
- 先在同父目录创建临时文件，写入 canonical UTF-8 JSON，重新读取并校验 report 后一次 rename；
- 任一失败清理临时文件且不留下 output_file；
- 不覆盖、删除或移动用户已有路径；
- report 不包含 source_root、gate_dir、output_dir、TemporaryDirectory 或其他绝对路径。

## 7. 稳定错误码与负例矩阵

异常字符串固定以 `<code>: ` 开头，验证顺序固定为 output path、envelope/schema、manifest/bytes、
metrics equations、JSON staging 和 atomic publish。

| condition | expected code |
| --- | --- |
| metrics 输入类型、schema 或 envelope state 非法 | `METRICS_EXECUTION_INVALID` |
| manifest 顺序/hash 或 gate physical bytes 不匹配 | `METRICS_MANIFEST_INVALID` |
| effective/affected line、coverage 或 leakage 审计不一致 | `METRICS_AUDIT_INVALID` |
| output_file 已存在、父目录非法或路径重叠 | `METRICS_OUTPUT_INVALID` |
| 临时 JSON 写入、读取校验或 rename 失败 | `METRICS_IO_ERROR` |

所有负例必须保证目标 output 和临时文件均不存在；不得捕获后降级成功，不得调用 legacy metrics
或重新运行 rewrite 生成“修复后”输入。

## 8. 明确不包含

- 不实现 `--encryption-rate`、target/candidate/selected lines、greedy selection 或 rate metrics；
- 不修改 T047 envelope、T046 execution/restore、MappingVNext、RewritePolicy、SymbolGraph、
  SourceCatalog 或 SourceSet schema；
- 不新增 CLI、encrypt/decrypt adapter 或 project-root 分支；
- 不运行 RISC-V-Vector Formal；
- 不删除 legacy inventory/rewrite/decrypt、旧 metrics 或旧 mapping 分派；
- 不修改任何 RTL/formal fixture、README、renaming table 或 Formal 脚本。

## 9. 允许修改的文件

- `rtl_obfuscator/metrics_vnext.py`：本任务 metrics API、line/coverage/leakage audit 和 atomic JSON output；
- `tests/test_metrics_vnext.py`：compact 黑盒测试；
- `docs/tasks/T048_metrics_vnext_effective_lines.md`：状态、执行记录和主 Agent验收记录。

需要修改允许列表外文件时，子 Agent必须记录偏差并停止，不得自行扩大范围。

## 10. 目标测试与验收命令

目标测试必须使用真实 T047 envelope、source bytes 和 actual gate bytes，覆盖：

1. full/top metrics schema、effective-line 分母、affected-line 唯一集合和 coverage/leakage oracle；
2. single filelist 与 single-file normalized metrics report 一致；
3. deterministic JSON byte identity 和无绝对路径；
4. source/gate manifest、gate bytes、equation、output path 和 I/O 负例 fail-closed；
5. 阻断 SourceSet/SymbolGraph/mapping/legacy metrics/rewrite/decrypt 重建；
6. atomic output 失败不留下 JSON 或临时文件。

唯一验收命令（不超过五条）：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_metrics_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/metrics_vnext.py tests/test_metrics_vnext.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T048_metrics_vnext_effective_lines.md
```

本任务 Formal verification 为 `N/A`；不产生新的 rewritten RTL。

## 11. 子 Agent执行记录

~~~text
status: NOT_STARTED
starting_head:
start_time:
baseline_command:
baseline_result:
changed_files:
commands:
results:
metrics_summary:
line_denominator_result:
coverage_leakage_result:
negative_cases:
formal_verification: N/A; no new rewritten RTL is produced by this task
deviations_or_blockers:
boundaries:
review_request:
~~~

## 12. READY_FOR_REVIEW 条件

- 任务状态严格为 `READY_FOR_REVIEW`，精确状态守卫通过；
- 目标测试、py_compile 和 `git diff --check HEAD` 全部通过；
- effective-line 分母完全按 source bytes 计算，affected-line 使用唯一 physical line 集合；
- symbols/occurrences/effective coverage、plaintext leakage 和 JSON schema 满足固定 oracle；
- single/filelist normalized report 一致；
- 所有负例 fail-closed 且无输出/临时文件残留；
- 不重建语义图、mapping 或调用 legacy 路径；
- fixture hash、T047 envelope 和既有 schema 未改变；
- 子 Agent不得设置 `ACCEPTED`、创建 T049、commit 或 push。

## 13. 主 Agent验收边界

主 Agent只独立复跑第 10 节四条命令，审查实际 source/gate bytes、行集合、coverage/leakage 计算和
原子 JSON 行为；全部通过后写本节验收记录并设置 `ACCEPTED`。不增加 legacy、RISC、全量回归、CLI
或隐藏 probe。

## 14. 主 Agent合同冻结记录（2026-07-23）

~~~text
status: READY
baseline_commit: a1e757a
decision: T047 accepted; freeze effective-line/affected-line/coverage/leakage metrics before rate selection
inputs: committed T043 parameter fixture + T047 MappingExecutionVNext + actual source/gate bytes
oracle: symbol 16/16/1.0; occurrence 41/41/1.0; plaintext leakage 0.0; effective coverage 1.0; effective denominator computed from bytes
formal_verification: N/A - no new rewritten RTL is produced by this task
forbidden: rate selection, CLI, project-root, RISC Formal, legacy compatibility, fixture edits, T049 creation
~~~
