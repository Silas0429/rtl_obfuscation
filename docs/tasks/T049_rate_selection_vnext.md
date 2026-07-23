# T049：MappingVNext greedy unique-line rate selector

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-F
- 前置任务：T048 ACCEPTED，交付提交 44f9f84
- 设计依据：docs/three_mode_refactor_plan.md 第 1–7 节
- 执行规范：docs/refactor_subagent_protocol.md
- Formal 依据：docs/formal_verification.md
- 验收类型：mapping/rate-selection；本任务不产生 rewritten RTL
- Formal verification：N/A，本任务只生成 MappingVNext 的候选/选择计划，不执行 gate 改写

## 1. 单一目标

建立不依赖 legacy rewrite.py 的 MappingVNext rate selector：

1. 按 T048 effective-line 定义计算唯一物理行分母；
2. 为每个 action=rename 的 MappingRecord 计算 declaration 加 occurrences 覆盖的唯一行集合；
3. 使用 greedy_unique_line_v1 算法选择不可拆分的完整 mapping record；
4. 产生可审计、路径可移植、确定性排序的选择计划；
5. 在目标不可达或候选为空时选择全部候选并明确报告，不返回错误；
6. 不修改 MappingVNext core，不生成 gate，不运行 CLI，不调用 legacy rate helper。

本任务只输出选择计划，不负责把 selected records 应用到 rewrite execution；selected mapping execution
由后续任务接入。

## 2. 固定输入

只读复用 T043–T048 已提交 compact fixture、MappingVNext 和 T048 effective-line 定义：

tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/closure.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv

测试使用 T045 deterministic name_factory 构造真实 MappingVNext；所有报告和负例写入 TemporaryDirectory。
不新增或修改 RTL/formal fixture；18 个冻结 fixture hash 必须保持不变。

## 3. 固定公开 API

新增 rtl_obfuscator/rate_vnext.py，提供 RateCandidateVNext、RateSelectionVNext、
RateSelectionVNext.to_report() 和 build_rate_selection_vnext(mapping_vnext, rate: str)。

RateCandidateVNext 固定字段：

- symbol_id
- category
- owner_module
- original_name
- declaration
- affected_lines: tuple[(file, one_based_line), ...]
- selected

RateSelectionVNext 固定字段：

- schema_version
- mapping_vnext
- algorithm
- target
- total_lines
- target_lines
- candidate_lines
- selected_lines
- actual_rate
- overshoot_lines
- maximum_rate
- target_unreachable
- selection_mode
- candidates

rate 必须解析为 finite Decimal，满足 0 < rate <= 1；target_lines 使用
ceil(Decimal(rate) * total_lines)。输入必须是真实 MappingVNext，不接受 dict、旧 mapping 或预先筛选的
record 列表。

## 4. 唯一行集合与候选规则

每个 physical source file 使用 T048 定义：

line.strip() != b"" and not line.strip().startswith(b"//")

total_lines 是 MappingVNext physical files 的 effective-line 总和；.svh 也计入，filelist、mapping、
metrics 和 maps 不计入。每个 candidate 的 affected_lines 是 declaration 与全部 occurrences 的唯一
(file, one_based_line) 集合，同一 record 同行多个 range 只能计一次。

候选只包含 action=rename 的 MappingRecord；preserve/unsupported 不进入 candidates。候选必须保留完整
record identity，不能只选 declaration 或部分 occurrences。

候选排序稳定 key 为：
(declaration.file, declaration.start, category, owner_module, original_name, symbol_id)

candidate_lines 是所有 candidate affected-lines 的唯一并集大小；maximum_rate 是
candidate_lines / total_lines，分母为 0 时固定为 0.0。

## 5. greedy_unique_line_v1 算法

1. 按稳定 key 建立 candidates 和已覆盖行集合；
2. 如果 total_lines 为 0、候选行集合为空或 target_lines 大于 candidate_lines，选择全部候选，
   target_unreachable=true、selection_mode=all_candidates；
3. 否则循环直到 covered 行数达到 target_lines：
   - 计算每个未选 candidate 的 marginal line count；
   - 若存在 marginal 大于等于 remaining target，选择 marginal 最小者；
   - 否则选择 marginal 最大者；
   - marginal 相同按稳定 key 升序；
4. 按稳定 key 逆序尝试删除已选 candidate；删除后仍满足 target_lines 即删除；
5. 从最终 selected candidates 重新计算 selected_lines、actual_rate 和 overshoot_lines；
6. actual_rate 是 selected_lines / total_lines，分母为 0 时固定为 0.0；
7. 不得依赖 occurrence 数量替代唯一物理行集合，不得返回部分 record。

## 6. report schema 与固定不变量

RateSelectionVNext.to_report() 顶层字段固定为：

format=rtl-obfuscation.rate-selection-vnext
schema_version=1
state=planned
mapping_format=rtl-obfuscation.mapping-vnext
algorithm
target
total_lines
target_lines
candidate_lines
selected_lines
actual_rate
overshoot_lines
maximum_rate
target_unreachable
selection_mode
candidate_entries
selected_entries
candidates

每个 candidate 固定包含 symbol_id、category、owner_module、original_name、declaration、affected_lines、
affected_line_count、selected。报告只能包含相对 POSIX 路径，不得包含 source_root、TemporaryDirectory
或其他绝对路径。

必须满足：

- selected_lines 等于 selected candidates 的 affected-lines 唯一并集；
- actual_rate 等于 selected_lines / total_lines，允许 JSON 浮点表示误差；
- candidate_entries 等于 candidates 长度；
- selected_entries 等于 selected candidates 数量；
- target_unreachable=false 时 actual_rate >= target；
- target_unreachable=true 时所有候选 selected、selection_mode=all_candidates、
  selected_lines=candidate_lines、actual_rate=maximum_rate；
- deterministic NameFactory 与相同 rate 下连续 report JSON byte-identical。

compact top 至少冻结 16 个 rename candidates；candidate/selected entries 与唯一行集合必须由实际
fixture bytes 重算，所有 selected candidate 的 occurrences 必须完整保留，不得硬编码 RISC 或历史全量数量。

## 7. 稳定错误码与负例矩阵

异常字符串固定以 <code>: 开头：

| condition | expected code |
| --- | --- |
| rate 非数字、非 finite、<=0 或 >1 | RATE_SELECTION_INVALID |
| input 不是 MappingVNext、schema/format 不正确 | RATE_MAPPING_INVALID |
| input manifest、source bytes、range 或 record identity 非法 | RATE_MAPPING_INVALID |
| candidate range 无法映射到 physical line 或发生 owner/range 重叠 | RATE_CANDIDATE_INVALID |
| greedy selection 无法达到可达 target | RATE_SELECTION_FAILED |

目标不可达不是错误；只有可达目标在候选耗尽前无法选择时才返回 RATE_SELECTION_FAILED。所有负例
不产生 gate、mapping 文件或其他输出，不调用 legacy helper。

## 8. 明确不包含

- 不修改 MappingVNext、RewritePolicy、SymbolGraph、SourceCatalog、SourceSet 或 T048 metrics schema；
- 不把 selected candidates 应用到 gate 或 restore；
- 不新增 CLI、encryption-rate 参数、project-root adapter 或 metrics adapter；
- 不实现 RISC-V-Vector Formal；
- 不删除 legacy rate selection、旧 metrics 或旧 mapping 分派；
- 不修改任何 RTL/formal fixture、README、renaming table 或 Formal 脚本。

## 9. 允许修改的文件

- rtl_obfuscator/rate_vnext.py：本任务 selector、candidate line audit 和 report；
- tests/test_rate_vnext.py：compact 黑盒测试；
- docs/tasks/T049_rate_selection_vnext.md：状态、执行记录和主 Agent验收记录。

需要修改允许列表外文件时，子 Agent 必须记录偏差并停止，不得自行扩大范围。

## 10. 目标测试与验收命令

目标测试必须覆盖 full/top、single/filelist normalized report、rate 参数和 ceil 规则、唯一 affected
lines、完整 occurrences、稳定 greedy tie-break、target unreachable、空 candidate、zero effective-line、
report equations、路径可移植性、deterministic JSON、MappingVNext/range 负例，以及 legacy rate helper
阻断。

唯一验收命令：

conda run -n rtl_obfuscation python -m unittest tests.test_rate_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rate_vnext.py tests/test_rate_vnext.py
git diff --check HEAD
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T049_rate_selection_vnext.md

本任务 Formal verification 为 N/A；不产生 rewritten RTL。

## 11. 子 Agent执行记录

status: READY_FOR_REVIEW
starting_head: 9ec9f5cc1980ee480522e9ce071e3d70a7606316
start_time: 2026-07-23T15:51:04+08:00
starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 2]`; no other status entries
allowed_files: rtl_obfuscator/rate_vnext.py; tests/test_rate_vnext.py; docs/tasks/T049_rate_selection_vnext.md; all were absent/unmodified in the starting tree
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_rate_vnext -v`
baseline_result: target unittest unavailable before implementation; `ModuleNotFoundError: No module named 'tests.test_rate_vnext'`, Ran 1 test in 0.000s, FAILED, exit_code=1
changed_files: rtl_obfuscator/rate_vnext.py; tests/test_rate_vnext.py; docs/tasks/T049_rate_selection_vnext.md
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_rate_vnext -v` — actual output: Ran 8 tests in 0.110s; OK; exit_code=0
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rate_vnext.py tests/test_rate_vnext.py` — actual output: no stdout/stderr; exit_code=0
  - `git diff --check HEAD` — actual output: no stdout/stderr; exit_code=0
  - `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T049_rate_selection_vnext.md` — actual output: `- 状态：READY_FOR_REVIEW`; exit_code=0
results: T049 acceptance row passed; the final status guard passed.
selection_summary: full/top real MappingVNext produced 16 rename candidates; candidates are stably ordered by (declaration.file, declaration.start, category, owner_module, original_name, symbol_id). Selection is complete-record only, with declaration plus all occurrences projected to unique physical (file, 1-based line) pairs. Single-file and filelist reports are normalized and deterministic.
rate_equations: finite Decimal input is restricted to 0 < rate <= 1; target_lines = ceil(Decimal(rate) * total_lines); candidate_lines and selected_lines are unique affected-line union sizes; actual_rate = selected_lines / total_lines, maximum_rate = candidate_lines / total_lines, denominator-zero rates are 0.0, and overshoot_lines = max(0, selected_lines - target_lines). Reachable targets use greedy_unique_line_v1; zero-line, empty-candidate, and unreachable targets select all candidates with selection_mode=all_candidates.
negative_cases: invalid rates returned RATE_SELECTION_INVALID; manifest and range/record identity corruption returned RATE_MAPPING_INVALID; forged candidate sequence/target returned fail-closed errors; no-candidate and zero-effective-line cases selected all candidates without output; deterministic JSON was byte-identical; legacy _parse_encryption_rate and _rate_selection were patched to fail and were not called.
formal_verification: N/A; no rewritten RTL is produced by this task
deviations_or_blockers: none at start
boundaries: selector consumes only the established MappingVNext and verified source manifest bytes; it does not apply selected records to gate output and does not implement CLI, encryption-rate integration, project-root handling, metrics integration, or legacy cleanup.
review_request: READY_FOR_REVIEW; Main Agent may independently rerun the four commands in section 10.

## 12. READY_FOR_REVIEW 条件

- 状态严格为 READY_FOR_REVIEW，精确状态守卫通过；
- 目标测试、py_compile 和 git diff --check HEAD 全部通过；
- effective-line、candidate-line、ceil、greedy、unreachable 和 report equations 全部通过；
- selected candidates 保留完整 declaration/occurrences，未产生部分 mapping；
- normalized single/filelist report 和 deterministic JSON 通过；
- 所有负例 fail-closed 且无输出残留；
- 不重建语义图、MappingVNext 或调用 legacy rate helper；
- fixture hash 和 T048 既有 metrics schema 未改变；
- 子 Agent 不得设置 ACCEPTED、创建 T050、commit 或 push。

## 13. 主 Agent验收边界

主 Agent只独立复跑第 10 节四条命令，审查真实 MappingVNext、source bytes、唯一行集合和 greedy
selection report；全部通过后写本节验收记录并设置 ACCEPTED。不增加 legacy、RISC、全量回归、CLI、
gate 或隐藏 probe。

## 14. 主 Agent合同冻结记录（2026-07-23）

status: READY
baseline_commit: 44f9f84
decision: T048 accepted; freeze MappingVNext-only rate selection before selected mapping execution and CLI integration
inputs: committed T043 parameter fixture + MappingVNext + T048 effective-line definition
oracle: greedy_unique_line_v1; complete rename records only; unique physical lines; unreachable selects all candidates
formal_verification: N/A - no rewritten RTL is produced by this task
forbidden: gate rewrite, restore, CLI, project-root, RISC Formal, legacy compatibility, fixture edits, T050 creation

## 15. 主 Agent最终验收记录（2026-07-23）

status: ACCEPTED
reviewed_head: 9ec9f5cc1980ee480522e9ce071e3d70a7606316; required T049 baseline commit is present
prerequisites: PASS; T047 and T048 are ACCEPTED and T049 was the only active READY task
scope: PASS; changed paths are exactly rate_vnext.py, tests/test_rate_vnext.py, and this task contract
acceptance_commands:
  - conda run -n rtl_obfuscation python -m unittest tests.test_rate_vnext -v
  - conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rate_vnext.py tests/test_rate_vnext.py
  - git diff --check HEAD
  - rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T049_rate_selection_vnext.md
independent_results: unittest exit 0, Ran 8 tests in 0.113s, OK; py_compile exit 0; diff check exit 0; READY_FOR_REVIEW guard exit 0 before this acceptance update
selection_oracle: PASS; full/top has 16 rename candidates, complete declaration/occurrence records, unique affected lines, finite Decimal/ceil equations, deterministic greedy selection, and correct unreachable/empty/zero-line behavior
portable_output: PASS; normalized single/filelist reports and deterministic JSON are byte-identical and contain no absolute paths
negative_oracle: PASS; invalid rates, manifest/range/identity corruption and failed selection use frozen errors; legacy rate helpers are blocked
formal_verification: N/A; no rewritten RTL is produced by this task
decision: all frozen T049 requirements passed; ACCEPTED
delivery: ready for Main Agent commit and push; no T050 implementation included
