# T135：FAST 改写范围统计与一次性执行审计

- 状态：`ACCEPTED`
- 负责人：子 Agent（实现与自测）/ 主 Agent（合同与验收）
- 起始分支：`delivery/fast-local-signals`
- 起始提交：`99d696e6390ab22174184d4f30ca54ea14db7a17`

## 1. 单一目标

保持 FAST/FULL 的候选、改名决策、MappingVNext schema、物理改写、完整 gate、strict compile、decrypt
和原子失败不变，建立两条路径共用的 rewrite-scope 统计和一次性 post-restore 执行事实：提供
`--rewrite-root` 时，文件覆盖率、总代码行数、实际加密行数和加密率只以 SourceSet 已登记且位于
rewrite-root 内的物理文件为范围；MappingExecution、Metrics 和最终 report 不得反复重建相同的
per-file projection、行号和覆盖率证据。

本任务只处理当前 AICluster 在 restore 后无日志等待的公共后端；不修改 FAST CST collector，也不声称
解决服务器上 `rename_index=1086.856s` 的前端瓶颈。

## 2. 固定输入

复用且不得修改：

```text
tests/fixtures/t130_fast_local_signals/**
```

主 Agent 冻结验收测试，子 Agent不得修改：

```text
tests/test_t135_scoped_execution_metrics.py
```

固定 FAST 输入：

```sh
python rtl_encrypt.py \
  --filelist tests/fixtures/t130_fast_local_signals/design.f \
  --rewrite-root tests/fixtures/t130_fast_local_signals/owned \
  --category signals \
  --output-dir <new-output>
```

固定 FULL 对照输入只额外提供：

```text
--top t130_top
```

## 3. 冻结统计语义

1. `physical_files` 仍是 `ordered_source_files + included_files` 的规范去重顺序，负责 manifest、完整 gate、
   strict compile 和 decrypt。
2. `metric_scope_files` 是已登记 `physical_files` 与规范 `rewrite_roots` 的有序交集；多个或嵌套 root
   取并集并去重。不得递归扫描目录或纳入 filelist 未登记文件。
3. 未提供 rewrite-root 时，metric scope 保持当前全部 physical files 语义。
4. 每个 landed edit 必须位于 metric scope；否则 fail closed，不允许把 root 外 edit 排除统计后继续成功。
5. `metrics.scope` 固定为：

```json
{
  "kind": "rewrite_roots",
  "files": ["owned/leaf_a.sv", "owned/leaf_b.sv", "owned/top.sv"],
  "physical_files": 4
}
```

   未提供 root 时 `kind="all_physical"`。
6. `metrics.effective_lines.by_file` 和 `metrics.affected_lines.by_file` 只列 metric scope，固定 fixture 的
   `effective_lines.total=50`。
7. orchestration `summary.files=3`，新增 `summary.physical_files=4`；`files` 从本任务起明确表示统计范围
   文件数。MappingExecution 自身的 manifest/per-file 文件数仍为完整 physical files。
8. FAST 固定 `affected_line_count=12`、改名决策 `rename=5/preserve=1/unsupported=0`；FULL 固定
   `affected_line_count=18`、改名决策 `rename=7/preserve=2/unsupported=0`。
9. 终端“总文件数”“文件覆盖率”“总代码行数”“加密率”使用 scoped 结果，并新增“交付物理文件数”显示
   manifest 文件数。FAST 为 `3/2/66.67%/50/12/24.00%`；FULL 为 `3/3/100.00%/50/18/36.00%`。
10. CLI、orchestration、mapping 和 metrics 的现有 format/schema version 保持不变；新增 scope/physical
    字段是可审计的语义修正，不新增 v2/v3 兼容分派。

## 4. 冻结性能结构

1. 允许增加一个公共内部 file-scope/execution-facts 模块；FAST 和 FULL 必须消费同一 scope 规则，禁止
   在 CLI 或 FAST 分支内复制统计逻辑。
2. per-file mapping 必须先建立 file bucket，再对每条 record/range 直接投影；禁止对每个 physical file
   重新遍历全部 mapping records。
3. edit gate offset 必须使用每文件有序前缀增量或等价直接索引；禁止对每个 edit 重新扫描同文件全部
   edit 增量。
4. 每个 metric scope 文件的 line spans/line-start index 在一次 run 中最多建立一次；edit 到行号使用该
   索引，禁止每个 edit 对整文件 `splitlines()`。
5. MappingExecution 和 Metrics 的完整验证在 builder 中各执行一次并保存紧凑事实；成功返回后，重复
   `OrchestrationVNext.to_report()` 不得重新读 source/gate、重建 per-file projection 或重算 metrics。
6. CLI 只组装一次最终 report；JSON、CSV、终端总结消费同一 report，不得再次调用昂贵 builder。
7. 新增且各恰好一次 begin/end 的阶段日志，顺序固定在 restore 之后：

```text
audit.execution  构建执行索引
audit.metrics    计算加密指标
audit.report     组装结果报告
publish          原子发布输出
cleanup          清理临时文件
```

8. 安全校验不能删除：range 与原名/新名匹配、重复重叠、manifest、strict compile、restore byte identity、
   portable report 和失败清理仍必须保留，但同一事实不得靠多次全量重建证明。

## 5. 不包含

- 不修改 FAST candidate、`syntax_local_ambiguous`、FULL RewritePolicy 或随机命名；
- 不优化 FAST module CST inventory、全 filelist unavailable-name 扫描或 FULL SourceCatalog；
- 不改变完整 gate/design.f/manifest/decrypt 的物理文件集合；
- 不采用硬链接，不改变 `/tmp` 到最终输出的复制策略；
- 不改变 `--rate` 的候选选择和比例分母；公共 Metrics builder 的 scoped 输出可自然被 rate execution 复用；
- 不运行真实 AICluster/StCache，不运行 RISC-V-Vector Formal；
- 不删除历史测试、任务或 schema 兼容层。

## 6. 允许修改文件

```text
README.md
docs/systemverilog_renaming_table.md
docs/development/project_structure.md
docs/development/future_work.md
docs/tasks/T135_fast_scoped_execution_metrics.md
rtl_obfuscator/file_scope_vnext.py（可新增）
rtl_obfuscator/rewrite_vnext.py
rtl_obfuscator/metrics_vnext.py
rtl_obfuscator/orchestration_vnext.py
rtl_obfuscator/rewrite.py
```

固定测试和 fixture 不在子 Agent 允许修改列表。需要修改其他文件、schema version、rate selection 或改名
决策时，记录偏差并停止。

## 7. Baseline

产品修改前运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t135_scoped_execution_metrics.T135ScopedExecutionMetricsTests.test_fast_and_full_metrics_use_rewrite_scope -v
```

预期当前实现失败：`summary.files=4`、`effective_line_total=70`，且没有 `metrics.scope` 和
`summary.physical_files`。若失败形状不同，记录后停止。

## 8. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t135_scoped_execution_metrics \
  tests.test_t130_fast_local_signals.T130FastLocalSignalsTests.test_actual_gate_formal_positive_and_fixed_functional_negative -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_metrics_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext \
  tests.test_t130_fast_local_signals tests.test_t134_fast_include_closure -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/file_scope_vnext.py rtl_obfuscator/rewrite_vnext.py \
  rtl_obfuscator/metrics_vnext.py rtl_obfuscator/orchestration_vnext.py \
  rtl_obfuscator/rewrite.py tests/test_t135_scoped_execution_metrics.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T135_fast_scoped_execution_metrics.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t135_ready_for_review=pass")'
```

第一条中的 T130 Formal 必须使用公开 FAST actual gate，固定 gold/gate/top/seq 与 T130 已验收合同相同；
positive exit 0 且 JSON `formal_equivalence=pass`，fixed XOR→OR negative 必须非零并包含 `unproven` 与
`equiv_status -assert`。T135 测试必须同时确认 FAST/FULL strict compile、完整物理 manifest、root 外文件
只读和 decrypt byte-identical。

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 99d696e6390ab22174184d4f30ca54ea14db7a17
changed_files: README.md; docs/development/project_structure.md; docs/tasks/T135_fast_scoped_execution_metrics.md; rtl_obfuscator/file_scope_vnext.py; rtl_obfuscator/rewrite_vnext.py; rtl_obfuscator/metrics_vnext.py; rtl_obfuscator/orchestration_vnext.py; rtl_obfuscator/rewrite.py
commands: baseline; conda run -n rtl_obfuscation python -m unittest tests.test_t135_scoped_execution_metrics tests.test_t130_fast_local_signals.T130FastLocalSignalsTests.test_actual_gate_formal_positive_and_fixed_functional_negative -v; conda run -n rtl_obfuscation python -m unittest tests.test_metrics_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_t130_fast_local_signals tests.test_t134_fast_include_closure -v; conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/file_scope_vnext.py rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/metrics_vnext.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/rewrite.py tests/test_t135_scoped_execution_metrics.py; git diff --check HEAD; READY_FOR_REVIEW guard
results: baseline failed as expected at summary.files=4; after review rework, T135 plus T130 actual gate Formal command passed 4 tests (T135 3/3, Formal positive pass and fixed functional negative nonzero with required diagnostics); regression command passed 16 tests; scoped FAST report 3/4 files, 50 lines, 12 affected; scoped FULL report 3/4 files, 50 lines, 18 affected; py_compile pass; diff check pass; READY_FOR_REVIEW guard pass; frozen test hash ae1fb8d27c699ebf46c48e35b830ec658dda695fbcef92aafbdd9668f7df89bf
schema_or_behavior: mapping decisions, physical manifests, gate/decrypt, schema version 2, and rate selection unchanged; metrics now expose scope and orchestration summary separates scoped files from physical_files
review_rework: addressed code-review findings within T135 scope: range-file validation now uses one frozenset while preserving ordered tuples; physical-file and manifest duplicate checks use order-plus-seen; write_mapping_execution_vnext reuses builder-validated facts and still validates external envelopes once; README and project structure document shared scoped metrics and full physical delivery audits
boundaries: Sections 3-6
formal_verification: PASS via T130 actual-gate positive formal_equivalence=pass and fixed functional negative nonzero with unproven/equiv_status -assert
test_ownership: tests/test_t135_scoped_execution_metrics.py was not modified by the sub-agent; Main Agent made only the documented public decrypt-entrypoint and coverage-token assertion corrections, then froze hash ae1fb8d27c699ebf46c48e35b830ec658dda695fbcef92aafbdd9668f7df89bf
review_request: ready for Main Agent independent re-review; no commit or push performed
```

## 10. 偏差或阻塞

```text
none
```

## 11. 主 Agent 验收记录

```text
status: ACCEPTED
reviewed_head: 99d696e6390ab22174184d4f30ca54ea14db7a17 plus the reviewed T135 working-tree diff
acceptance: Main Agent independently reran the fixed commands; T135 plus Formal passed 4/4, shared regressions passed 16/16, py_compile and git diff --check HEAD passed
code_review: FAST/FULL share one registered rewrite-scope; full physical delivery remains intact; per-file projection is bucketed; range ownership uses one frozenset; gate deltas and affected lines use ordered indexes; completed reports reuse builder facts
blocking_findings: none after rework; the initial tuple-membership multiplication, redundant writer validation, and missing architecture documentation were corrected and revalidated
formal_verification: PASS; actual renamed FAST gate positive returned formal_equivalence=pass, and the fixed XOR-to-OR functional negative was nonzero with unproven and equiv_status -assert
resolution: accepted without changing rename decisions, schema versions, rate selection, strict compilation, manifest, restore, or decrypt behavior
next_step: rerun AICluster FAST on the accepted commit and use the new audit.execution/audit.metrics/audit.report/publish/cleanup timings to isolate the remaining FAST RenameIndex front-end cost; T135 does not claim to solve that separate 1086.856s stage
```
