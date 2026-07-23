# T047：mapping vNext 最终执行封装、per-file mapping 与 manifest

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-D
- 前置任务：T046 `ACCEPTED`，交付提交 `48b2b68`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 1–7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：mapping/execution-envelope；本任务不新增 rewritten RTL
- Formal verification：`N/A`，本任务只把已由 T046 strict gate/restore 验证的 execution 投影为最终封装，不新增 RTL 改写行为

## 1. 单一目标

在 T046 的 `RewriteExecution` 与 `RestoreResult` 之上建立一个可持久化、可审计、路径可移植的
最终 mapping execution envelope：

1. 验证 execution、restore、MappingVNext identity 和三份 manifest 的关系仍然一致；
2. 生成按 physical file 分组的 canonical per-file mapping；
3. 统一输出 input、gate、restored manifest，并证明 restored manifest 等于 input manifest；
4. 提供原子 JSON 写出，不覆盖已有文件，不留下部分输出；
5. 只消费 T046 已产生的对象和 gate bytes，不重新建立 SourceSet、SourceCatalog、SymbolGraph、
   RewritePolicy 或 mapping，不读取 gold source_root。

本任务不修改 T046 的 `RewriteExecution.to_report()` 和 `RestoreResult.to_report()` 既有 schema；
最终封装是新的上层报告，不向旧 v1/v2/v3/v4 mapping 增加兼容分派。

## 2. 固定输入

只读复用 T043/T046 已提交的 compact 输入和公开 API：

```text
tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/closure.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv
```

测试使用 T045 deterministic `name_factory` 构造 `MappingVNext`，再调用 T046 的
`write_gate_vnext()` 与 `restore_gate_vnext()` 取得真实 execution/restore；所有 gate、mapping JSON
和负例均写入 `TemporaryDirectory`。不新增或修改 RTL/formal fixture；18 个冻结 fixture hash 必须保持不变。

## 3. 固定公开 API

在 `rtl_obfuscator/rewrite_vnext.py` 增加以下公开对象；不得修改 T039–T046 已冻结的数据类字段：

```python
@dataclass(frozen=True)
class MappingExecutionVNext:
    schema_version: int
    rewrite_execution: RewriteExecution = field(repr=False, compare=False)
    restore_result: RestoreResult = field(repr=False, compare=False)

    def to_report(self) -> dict[str, object]: ...

def build_mapping_execution_vnext(
    rewrite_execution: RewriteExecution,
    restore_result: RestoreResult,
) -> MappingExecutionVNext: ...

def write_mapping_execution_vnext(
    mapping_execution: MappingExecutionVNext,
    *,
    output_file: Path,
) -> None: ...
```

`build_mapping_execution_vnext()` 必须 fail-closed 验证：execution/restore schema 为 1，execution
引用的 MappingVNext 与 restore 引用一致，gate manifest 与 execution 一致，restored manifest 与
MappingVNext.input_manifest 一致，且 per-file projection 可由 execution.edits 完整重建。不得接受
duck-typed dict 代替公开 dataclass。

## 4. 最终 envelope report schema

`MappingExecutionVNext.to_report()` 的顶层 key 和顺序固定为：

```text
format = rtl-obfuscation.mapping-execution-vnext
schema_version = 1
state = restored
mapping = MappingVNext.to_report()
filelist = design.f
input_manifest
gate_manifest
restored_manifest
per_file_mapping
summary
```

所有路径只能是 SourceSet 的相对 POSIX 路径；报告不得出现 `source_root`、`gate_dir`、
`output_dir`、TemporaryDirectory 或其他绝对路径。

manifest 三者均按 physical file 的 canonical 顺序排列：

- `input_manifest` 直接等于 MappingVNext.input_manifest；
- `gate_manifest` 直接等于 RewriteExecution.gate_manifest；
- `restored_manifest` 直接等于 RestoreResult.restored_manifest，并且必须逐项等于 input_manifest。

`per_file_mapping` 必须覆盖 input manifest 中的每个 physical file，顺序一致；每个 file entry 固定
包含 `file`、`input_sha256`、`gate_sha256`、`records`。每个 record projection 固定包含
`symbol_id`、`category`、`action`、`reason`、`original_name`、`renamed_name`、`owner_module`、
`semantic_owner`、`impact`、`abi`、`ranges`。`ranges` 按 MappingVNext record 顺序、每个 record
声明优先再 occurrence 的顺序排列，每项包含 `provenance`、`source_range`、`gate_range`；preserve
record 的 gate range 必须与 source range 相同，rename record 的 gate range 必须来自 T046 AppliedEdit。

固定 compact top oracle：

```text
files=4
mapping_records=20
renamed_records=16
modified_tokens=41
per_file_mapping files=4
projected ranges=41 rename ranges + 12 preserve ranges
restored_byte_identical=true
```

`summary` 固定包含 `files`、`mapping_records`、`renamed_records`、`modified_tokens`、
`per_file_records`、`input_gate_manifest_equal`、`restored_input_manifest_equal` 和
`restored_byte_identical`。确定性 NameFactory 下，连续两次 report JSON 必须 byte-identical；
随机 NameFactory 不要求 renamed names 或派生 hash byte-identical。

## 5. 原子 JSON 输出

`write_mapping_execution_vnext()` 要求：

- `output_file` 不存在，父目录存在且为目录；
- 输出文件不得位于 source_root、gate_dir 或任何 physical source file 内；
- 先在同父目录创建临时文件，写入 canonical JSON（UTF-8、无额外绝对路径）并重新读取校验，
  成功后一次 rename 到 output_file；
- 任一失败清理临时文件且不留下 output_file；
- 不覆盖或删除用户已有路径。

## 6. 稳定错误码与负例矩阵

异常字符串固定以 `<code>: ` 开头。验证顺序固定为：output path、execution/restore schema 与 identity、
manifest、per-file projection、JSON staging 与 atomic publish。

| condition | expected code |
| --- | --- |
| execution/restore 类型、schema 或引用 identity 被篡改 | `MAPPING_EXECUTION_INVALID` |
| input/gate/restored manifest 顺序、文件、hash 或相等关系被篡改 | `MAPPING_MANIFEST_INVALID` |
| AppliedEdit 缺失、重复、per-file range 不匹配或 preserve gate range 被篡改 | `MAPPING_PER_FILE_INVALID` |
| output_file 已存在、父路径非法或与输入/gate路径重叠 | `MAPPING_OUTPUT_INVALID` |
| 临时 JSON 写入、读取校验或 rename 失败 | `MAPPING_IO_ERROR` |

所有负例都必须保证 output_file 不存在且不留下临时文件；不得用重新生成 mapping、读取 gold 或
调用 legacy decrypt 作为 fallback。

## 7. 明确不包含

- 不修改 T046 `RewriteExecution`、`RestoreResult`、`write_gate_vnext()` 或 `restore_gate_vnext()` 的既有 report schema；
- 不修改 MappingVNext、RewritePolicy、SymbolGraph、SourceCatalog、SourceSet 数据模型；
- 不新增 CLI、`encrypt-project`/`decrypt-project` adapter 或 project-root 分支；
- 不实现 effective-line、coverage、plaintext leakage、rate selection 或 metrics；
- 不实现 RISC-V-Vector Formal；
- 不删除 legacy inventory/rewrite/decrypt、旧测试或旧 mapping 分派；
- 不修改任何 fixture、README、renaming table、Formal 脚本或用户演示。

## 8. 允许修改的文件

- `rtl_obfuscator/rewrite_vnext.py`：只增加本任务公开 API、envelope projection、manifest validation 和 atomic JSON output；
- `tests/test_mapping_execution_vnext.py`：本任务 compact 黑盒测试；
- `docs/tasks/T047_mapping_execution_envelope.md`：状态、执行记录和主 Agent验收记录。

需要修改允许列表外文件时，子 Agent 必须先在任务单记录偏差并停止，不得自行扩大范围。

## 9. 目标测试与验收命令

目标测试必须验证真实 T046 execution/restore，不得构造 identity gate 或直接复制 gold：

1. full/top envelope、manifest 顺序/hash、4-file per-file projection 和 41/12 range 覆盖；
2. single filelist 与 single-file 的 normalized envelope 一致；
3. deterministic JSON byte identity 和相对路径可移植性；
4. execution、restore、manifest、per-file range、output path 和 I/O 负例 fail-closed；
5. atomic output 失败不留下 JSON 或临时文件；
6. 阻断 SourceSet/SymbolGraph/mapping 重建和 legacy rewrite/decrypt 调用。

唯一验收命令（不超过五条）：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_mapping_execution_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite_vnext.py tests/test_mapping_execution_vnext.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T047_mapping_execution_envelope.md
```

本任务不运行 Formal；T046 已对相同 actual renamed gate 完成 strict compile、Formal 正例和功能负例，
T047 只生成报告和 JSON，不产生新的 rewritten RTL。

## 10. 子 Agent执行记录

~~~text
status: READY_FOR_REVIEW
starting_head: aafe23a6cff2bb3d37569fd28f882fb8d63a243a
start_time: 2026-07-23T14:46:19+08:00
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_mapping_execution_vnext -v`
baseline_result: target unittest unavailable before implementation; `ModuleNotFoundError: No module named 'tests.test_mapping_execution_vnext'`, Ran 1 test in 0.000s, FAILED, exit_code=1
changed_files: rtl_obfuscator/rewrite_vnext.py; tests/test_mapping_execution_vnext.py; docs/tasks/T047_mapping_execution_envelope.md
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_mapping_execution_vnext -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite_vnext.py tests/test_mapping_execution_vnext.py`; `git diff --check HEAD`; `rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T047_mapping_execution_envelope.md`
results: target unittest PASS, Ran 7 tests in 0.179s, OK, exit_code=0; py_compile PASS, exit_code=0; `git diff --check HEAD` PASS with no output, exit_code=0; exact status guard PASS, matched `- 状态：`READY_FOR_REVIEW``, exit_code=0
envelope_summary: format `rtl-obfuscation.mapping-execution-vnext`, schema_version 1, state `restored`, filelist `design.f`; full/top files=4, mapping_records=20, renamed_records=16, modified_tokens=41; canonical deterministic JSON is byte-identical across repeated reports and writes
manifest_result: input manifest canonical order is `rtl/child.sv`, `rtl/shadow.sv`, `rtl/top.sv`, `rtl/unreachable.sv` with T045 hashes; gate manifest is projected directly from T046 RewriteExecution; restored manifest is projected directly from T046 RestoreResult and equals input manifest; restored byte identity is true
per_file_result: per_file_mapping covers all 4 physical files in manifest order; all 53 source ranges project exactly once as 41 rename ranges plus 12 preserve ranges; rename gate ranges come from AppliedEdit and preserve/unsupported gate ranges equal source ranges
negative_cases: execution/restore schema and identity, manifest order/equality, missing/duplicate/tampered AppliedEdit range, existing/missing/overlapping output paths, and atomic rename failure all fail closed with required stable codes; failed atomic output leaves neither output nor `.mapping-execution-vnext-*.tmp`
formal_verification: N/A; no new rewritten RTL is produced by this task
deviations_or_blockers: none
boundaries: gate hash correctness is trusted from the T046 RewriteExecution manifest because this API has no gate directory/bytes parameter; no source/gold bytes are read or reconstructed by T047; gate_dir overlap cannot be independently resolved from the frozen public T046 object fields
review_request: READY_FOR_REVIEW; all implementation evidence recorded; Main Agent should independently rerun only the four section 9 commands
~~~

## 11. READY_FOR_REVIEW 条件

- 任务状态严格为 `READY_FOR_REVIEW`，且精确状态守卫通过；
- 目标测试、py_compile 和 `git diff --check HEAD` 全部通过；
- full/top 固定 4/20/16/41 oracle 和 41 rename + 12 preserve range 投影通过；
- input/gate/restored manifest 顺序、hash 和相等关系通过；
- single-file/filelist normalized report 通过；
- 所有负例 fail-closed，失败不留下 output 或临时文件；
- 测试未重建 SymbolGraph、mapping 或调用 legacy 路径；
- 允许文件边界、fixture hash 和 T046 既有 report schema 未改变；
- 子 Agent只申请 `READY_FOR_REVIEW`，不得设置 `ACCEPTED`、创建 T048、commit 或 push。

## 12. 主 Agent验收边界

主 Agent只独立复跑第 9 节四条命令，审查真实 T046 execution/restore、manifest/range 投影和原子
JSON 行为；全部通过后再写本节验收记录并设置 `ACCEPTED`。不增加 legacy、RISC、全量回归、CLI
或隐藏 probe。

## 13. 主 Agent合同冻结记录（2026-07-23）

~~~text
status: READY
baseline_commit: 48b2b68
decision: T046 accepted; freeze final execution envelope and per-file/manifest projection as the next smallest R3 step
inputs: committed T043 parameter graph fixture + T046 public execution/restore API
oracle: 4 physical files / 20 mapping records / 16 rename records / 41 edits / 41 rename ranges / 12 preserve ranges / restored byte-identical
formal_verification: N/A - no new rewritten RTL is produced by this task
forbidden: CLI, project-root, metrics, RISC Formal, legacy compatibility, fixture edits, T048 creation
~~~

## 14. 主 Agent最终验收记录（2026-07-23）

~~~text
status: ACCEPTED
reviewed_head: aafe23a6cff2bb3d37569fd28f882fb8d63a243a; required T047 baseline commit is present
prerequisites: PASS; T046 is ACCEPTED and T047 was the only active READY task
scope: PASS; changed paths are exactly rewrite_vnext.py, tests/test_mapping_execution_vnext.py, and this task contract
acceptance_commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_mapping_execution_vnext -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite_vnext.py tests/test_mapping_execution_vnext.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T047_mapping_execution_envelope.md`
independent_results: unittest exit 0, Ran 7 tests in 0.175s, OK; py_compile exit 0; diff check exit 0; READY_FOR_REVIEW guard exit 0 before this acceptance update
envelope_oracle: PASS; format `rtl-obfuscation.mapping-execution-vnext`, schema_version=1, state=restored, files=4, mapping_records=20, renamed_records=16, modified_tokens=41
manifest_oracle: PASS; input/gate/restored manifests use canonical physical order; restored manifest equals input manifest; restored_byte_identical=true
per_file_oracle: PASS; all four physical files covered exactly once with 41 rename ranges and 12 preserve ranges; deterministic reports and JSON writes are byte-identical
negative_oracle: PASS; execution/restore identity, manifest, AppliedEdit, output path and atomic I/O failures use the frozen stable codes without artifacts
formal_verification: N/A; no new rewritten RTL is produced by this task
decision: all frozen T047 requirements passed; ACCEPTED
delivery: ready for Main Agent commit and push; no T048 implementation included
~~~
