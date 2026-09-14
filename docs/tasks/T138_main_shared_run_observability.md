# T138：main 通用统计、后处理进度与运行记录

- 状态：`ACCEPTED`
- 负责人：主 Agent（合同、冻结测试、独立验收与提交）/ Luna xhigh 子 Agent（实现与自测）
- 起始分支：`main`
- 起始提交：`1d9736fe511c3ceacf007009ee9409201d1e160d`
- 验收类型：adapter 迁移，复用一个 compact actual-gate Formal 正例与固定功能负例

## 1. 单一目标与来源

将 `404e586`（T135）的通用统计/报告优化和 `8173112`（T136）的成功运行记录部分迁入 main，
不引入 FAST 引擎。为同一条 FULL 语义流水线提供准确统计与可追溯运行证据。
只按 hunk 迁移；禁止 cherry-pick/merge 整个 FAST 分支或覆盖 main 文件历史。

必读：`AGENTS.md`、`docs/tasks/README.md`、`docs/development/process/refactor_subagent_protocol.md`、
`docs/formal_verification.md`。原 T135/T136 合同通过 `git show delivery/fast-local-signals:docs/tasks/...` 阅读。

## 2. 冻结行为与输出

1. `physical_files` 始终是 SourceSet 已登记 source + include 的有序去重完整集合。
   `metrics.scope={kind, files, physical_files}`：无 rewrite root 时 kind 为 `all_physical`；
   有 root 时为 `rewrite_roots`，files 仅为已登记物理集合与 root 并集的交集，不扫描目录。
2. `summary.files` 变为统计文件数；新增 `summary.physical_files` 为完整交付数。
   metrics 的行数分母/by_file 取统计集合；越界实际 edits 必须失败。
   manifest、mapping_execution.per_file_mapping、strict compile、gate、restore 仍使用完整物理集合。
   category、rename/preserve/unsupported、rate selection 及其既有分母不变。
3. 授权 T135 的按文件分桶、edit offset 前缀/index、每文件行索引、已验证 facts/report 的对象内缓存；
   `to_report()` 返回防御性副本，不重复读文件或重建 metrics/execution。
   外部新建/replace 的 envelope 仍须验证；不新增全局缓存或持久化缓存格式。
4. restore 后依次可见 `audit.execution`、`audit.metrics`、`audit.report`、publish、cleanup。
   同一阶段只出现一对 begin/end；失败不得伪报该阶段完成。
   rate 路径亦须满足：允许向现有 `build_rate_metrics_vnext` 增加可选 stage observer，
   在真实 restore / execution audit / metrics 边界透传事件，不改变 rate 选择、运算或数据合同。
5. 成功的 `encryption_summary.txt` 保存 shell-safe 的 executable/script/完整 argv、工作目录、
   与 stderr 逐字相同的全部计时行以及同一份最终总结；quiet 只关闭 stderr，不关闭采集。
   总结必须在 cleanup 后打印，stdout 仍为单行 schema 2 JSON。
6. 修正原 T136 发布时序：`publish end` 必须在本次所有 artifact 真正安装到最终路径之后发出。
   允许 `_cli_vnext_publish` 增加安装后、success 标记前的 finalize callback；callback 内清理 staging、
   生成一次总结、原子写最终 summary。任何普通异常必须回滚本次已发布 artifact，不覆盖已存在用户目标。
   summary 必须用原子单文件替换写入；不声称多个最终路径对 SIGKILL/OOM 具有跨文件事务保证。
   成功记录含已完成的发布与 staging 清理耗时，不包含总结自身最后的写入耗时。

## 3. 不包含

- T130–T133 FAST 引擎、T134 `99d696e`、任何 parse-only/FAST dispatch 或 `_compile_gate` 注入。
- T136/T137 filelist 三视图与 restore/Formal parser 改动（留给下一任务）。
- FULL/all 提速、no-top ABI 政策修复、vendor 判断、category 或安全边界改变。
- 修改 `project_discovery.py`、`source_set.py`、`source_catalog.py`、`rename_index.py`、`mapping_vnext.py`。
- 大型工程/RISC Formal、blanket discovery、删除任何历史测试/fixture、子 Agent 提交推送。

## 4. 固定输入和允许文件

主 Agent 冻结 `tests/test_t138_shared_run_observability.py`，子 Agent 不得修改。
它动态建立独立 main fixture：owned top、external helper、未登记文件；实际 gate XOR→OR 固定负例。
保留并运行 main 原 T133 include 测试，不复制 FAST 的 T130/T134 fixture。

子 Agent 只可修改：

```text
rtl_obfuscator/file_scope_vnext.py
rtl_obfuscator/metrics_vnext.py
rtl_obfuscator/rewrite_vnext.py
rtl_obfuscator/orchestration_vnext.py
rtl_obfuscator/rate_metrics_vnext.py
rtl_obfuscator/rewrite.py
README.md
docs/development/project_structure.md
docs/tasks/T138_main_shared_run_observability.md
tests/test_t116_cli_report.py
tests/test_t127_performance_probe.py
```

历史测试仅可同步新增 physical_files、后处理阶段和持久化总结合同，不放宽语义断言。

## 5. Baseline（唯一命令）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t138_shared_run_observability -v
```

预期新 scope/cache/progress/run-record 断言失败；existing gate/restore/Formal 应能运行。
先把本任务 READY → IN_PROGRESS 并记录 starting HEAD/已有主 Agent 测试与合同，再运行 baseline。

## 6. 固定验收（五条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t138_shared_run_observability -v

conda run -n rtl_obfuscation python -m unittest tests.test_metrics_vnext tests.test_mapping_execution_vnext tests.test_orchestration_vnext tests.test_rate_metrics_vnext tests.test_t133_include_physical_closure tests.test_t127_performance_probe tests.test_t116_cli_report.T116StdoutContractTests tests.test_t116_cli_report.T116DefinedFieldTests tests.test_t116_cli_report.T116DivisionByZeroTests -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/file_scope_vnext.py rtl_obfuscator/metrics_vnext.py rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/rate_metrics_vnext.py rtl_obfuscator/rewrite.py tests/test_t138_shared_run_observability.py tests/test_t116_cli_report.py tests/test_t127_performance_probe.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T138_main_shared_run_observability.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t138_ready_for_review=pass")'
```

命令 1 必须包含实际改名 gate 的 `scripts/formal_equivalence.py --gold <project>/owned/top.sv
--gate <gate>/owned/top.sv --top t138_top --seq 5`，exit 0 且 JSON pass；固定 XOR→OR 负例非零且含
`unproven` 和 `equiv_status -assert`。测试打印 `T138_FORMAL` 的路径与 JSON，主 Agent 独立重跑。
不得用历史 FAST 测试通过代替 main 验收。

## 7. 执行记录（子 Agent）

```text
status: READY_FOR_REVIEW
starting_head: 1d9736fe511c3ceacf007009ee9409201d1e160d
started_at: 2026-09-14 Asia/Shanghai
preexisting_authorized_files: docs/tasks/T138_main_shared_run_observability.md; tests/test_t138_shared_run_observability.py
changed_files: rtl_obfuscator/file_scope_vnext.py; rtl_obfuscator/metrics_vnext.py; rtl_obfuscator/rewrite_vnext.py; rtl_obfuscator/orchestration_vnext.py; rtl_obfuscator/rate_metrics_vnext.py; rtl_obfuscator/rewrite.py; README.md; docs/development/project_structure.md; docs/tasks/T138_main_shared_run_observability.md; tests/test_t116_cli_report.py; tests/test_t127_performance_probe.py
commands: baseline; conda run -n rtl_obfuscation python -m unittest tests.test_t138_shared_run_observability -v; conda run -n rtl_obfuscation python -m unittest tests.test_metrics_vnext tests.test_mapping_execution_vnext tests.test_orchestration_vnext tests.test_rate_metrics_vnext tests.test_t133_include_physical_closure tests.test_t127_performance_probe tests.test_t116_cli_report.T116StdoutContractTests tests.test_t116_cli_report.T116DefinedFieldTests tests.test_t116_cli_report.T116DivisionByZeroTests -v; conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/file_scope_vnext.py rtl_obfuscator/metrics_vnext.py rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/rate_metrics_vnext.py rtl_obfuscator/rewrite.py tests/test_t138_shared_run_observability.py tests/test_t116_cli_report.py tests/test_t127_performance_probe.py; git diff --check HEAD; READY_FOR_REVIEW guard
results: baseline ran before implementation with 9 tests: 3 failures and 4 errors in the expected scope/cache/run-record/publish assertions; its actual Formal positive passed and fixed negative returned nonzero. Final T138 command passed 11/11, including scoped and all-physical metrics, rate path events, defensive cache copies, late-collision rollback, summary-write rollback, actual gate Formal positive and fixed XOR->OR negative. Shared regression passed 25/25, including T133 include closure/Formal; py_compile passed exit 0; diff check passed.
schema_or_behavior: added registered physical-vs-metric scope, summary.files/physical_files separation, per-file execution facts and line/index reuse, defensive report copies, no-rate and rate post-restore audit stages, stderr-sourced successful run summary with expanded command/cwd, and install-before-publish-end rollback semantics; no schema version, category, rate algorithm, gate/restore, include closure, FAST, T134, or three-view filelist behavior changed
boundaries: successful summary is guaranteed only after ordinary atomic publish; SIGKILL/OOM cross-file transaction is not claimed; cleanup failure does not emit a cleanup end event; no large-project/RISC Formal run
formal_verification: PASS
gold: dynamic T138 project/owned/top.sv
gate: dynamic T138 gate/owned/top.sv
top: t138_top
command: conda run -n rtl_obfuscation python -m unittest tests.test_t138_shared_run_observability -v (embedded scripts/formal_equivalence.py --gold <project>/owned/top.sv --gate <gate>/owned/top.sv --top t138_top --seq 5)
exit_code: 0 for positive; fixed XOR->OR negative exit_code: 1
result: positive JSON formal_equivalence=pass; negative diagnostics contain unproven and equiv_status -assert; T138_FORMAL emitted
review_request: ready for Main Agent independent acceptance; no commit or push performed
```
完成后只设为 READY_FOR_REVIEW，不创建下一任务、不提交推送。

## 8. 偏差或阻塞

2026-09-14 主 Agent 静态核查补充：原 T135 仅在 no-rate 路径加入 execution/metrics audit，
rate 的 build_rate_metrics_vnext 把 restore 与 audit 包在一个调用中。为履行本合同通用进度要求，
允许 rate_metrics_vnext.py 只增加可选 observer 与真实阶段事件；不改变 rate semantics。
冻结测试新增 rate 阶段顺序检查，以及 dataclasses.replace 后不得继承缓存的检查。

## 9. 主 Agent 验收

```text
status: ACCEPTED
accepted_at: 2026-09-14 Asia/Shanghai
independent_acceptance: section 6 commands 1-5 independently rerun; all exit 0
tests: T138 11/11 (1.026s); shared regressions 25/25 (1.357s)
syntax_and_diff: PASS
ready_guard: t138_ready_for_review=pass before acceptance
formal_verification: PASS
gold: /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t138-main-3t29cxfu/project/owned/top.sv
gate: /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t138-main-3t29cxfu/formal-gate/owned/top.sv
top: t138_top
command: conda run -n rtl_obfuscation python -m unittest tests.test_t138_shared_run_observability -v
result: actual gate formal_equivalence=pass, seq=5, exit 0; fixed XOR->OR negative exit 1 with unproven and equiv_status -assert
include_regression: main T133 actual gate positive and functional negative independently passed; macro include guard retained
scope_review: only authorized files; no FAST import/dispatch, SourceSet/discovery/category/rename/rate-selection or filelist-delivery change
git_delivery: Main Agent to commit and push accepted changes; actual result reported in delivery message
```
