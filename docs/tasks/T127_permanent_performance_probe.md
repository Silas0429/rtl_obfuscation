# T127：PySlang 与 RenameIndex 永久性能探针

- 状态：`ACCEPTED`
- 设计负责人：主 Agent Codex
- 实现负责人：子 Agent（`gpt-5.6-luna`，`xhigh`）
- 起始 HEAD：`f4db0b254852b356c114247495cea0a0379bc1b7`
- 起始工作树：clean
- 前置任务：T126 已由主 Agent 验收并以 `f4db0b2` 推送
- 任务类型：展示层 / 性能可观测性；不改变 SourceSet、编译、改名或改写判定
- Formal verification：`N/A`；本任务只增加阶段边界输出，沿用 T116 的展示层边界，不改变任何 landed edit

## 1. 已冻结的问题

真实工程已经给出两组稳定证据：

```text
整个工程：
PySlang 编译与 elaborate       3789.375s
构建改名索引                  超过 10h56m，仍未结束

单模块：
PySlang 编译与 elaborate          4.404s
构建改名索引                    92.198s
生成映射 + 写出 + 回填             9.094s
```

现有 T116 进度只包围 `build_source_catalog()` 和 `build_rename_index()`，无法区分：

- PySlang parse/preprocess、`getRoot()` elaborate、diagnostics；
- SourceCatalog physical inventory、top closure、owner registry；
- RenameIndex semantic inventory、declaration、occurrence、CST inventory、dead-source、name completeness、finalize。

当前日志因此不足以决定下一步应优化 PySlang 输入、树遍历还是 token/reference 匹配。T127 只补永久、低开销的
阶段探针并在一个真实单模块公开 CLI 上取得细分时间；不实现任何性能优化。

## 2. 主 Agent 固定实现计划

本任务从开始到验收只允许以下三步，后续计划不得偏离或追加功能：

1. 冻结本合同、固定探针事件与单模块输入；
2. 子 Agent 只实现粗粒度阶段边界并完成固定自测；
3. 主 Agent 独立复跑同一验收，记录单模块细分时间并决定 `ACCEPTED` 与否。

T127 不创建或实现第二步 RenameIndex 优化任务。只有 T127 验收结束后，主 Agent 才根据本次数据重新判断是否
需要下一张独立性能合同。

## 3. 单一目标

复用 T116 的同一个 `time.monotonic()` 时钟和同一个 stderr writer，在现有两个外层阶段内部增加稳定、成对、
可机器解析的粗粒度 begin/end 事件。正常公开 CLI 必须实时显示每个子阶段累计时间和本阶段耗时；`--quiet`
必须继续抑制全部进度。探针不得改变阶段顺序、返回值、异常、stdout JSON、mapping、gate、restore 或随机命名。

## 4. 固定探针合同

### 4.1 唯一 observer

- 继续使用 T116 的 `StageObserver(stage, phase)`；不得建立第二个计时器、第二个 stderr writer 或性能报告 schema；
- 可新增一个最小内部模块，只保存 `StageObserver` 类型、稳定 stage ID 和无状态 `_observe()` helper；
- `orchestration_vnext.StageObserver` 必须继续可导入，保持当前内部调用兼容；
- 下层函数新增的 observer 参数必须可选且默认为 `None`；`None` 时不产生输出、不改变任何计算；
- 只允许在下列粗粒度函数边界调用 observer，禁止在 semantic node、CST node、token、record 或 reference 循环中逐项调用。

### 4.2 稳定子阶段 ID 与边界

公开 stderr 标签必须同时包含下列稳定 ID；中文说明可以按表中固定值输出：

| ID | 中文标签 | 精确边界 |
| --- | --- | --- |
| `compile.parse` | PySlang 解析与预处理 | `SyntaxTree.fromFiles()` |
| `compile.elaborate` | PySlang 构建语义树 / elaborate | `Compilation` 建立、`addSyntaxTree()`、`getRoot()` |
| `compile.diagnostics` | PySlang 收集与分类诊断 | syntax/vendor/semantic diagnostic 收集与分类 |
| `compile.catalog_inventory` | SourceCatalog 建立物理模块清单 | 当前分支的 physical/CST module inventory 与第一轮 duplicate 校验 |
| `compile.top_closure` | SourceCatalog 计算 top 闭包 | explicit top reachability、selected-top physical mapping |
| `compile.owner_registry` | SourceCatalog 建立 owner 注册表 | module owner、readonly duplicate final inventory、semantic owner registry 与 `SourceCatalog` 组装 |
| `rename_index.semantic_inventory` | 改名索引收集语义清单 | root nodes、module maps、interface IDs、active interface/type 集合 |
| `rename_index.declarations` | 改名索引登记候选声明 | interface、struct、四核心组 declaration registration |
| `rename_index.occurrences` | 改名索引收集引用范围 | occurrence collection、binding/group issues、readonly firewall |
| `rename_index.syntax_inventory` | 改名索引收集 CST 清单 | `_syntax_nodes()` 的完整 CST walk |
| `rename_index.unelaborated` | 改名索引检查未展开源码 | `_apply_unelaborated_references()` |
| `rename_index.name_completeness` | 改名索引检查名字完整性 | `_apply_name_completeness()` |
| `rename_index.finalize` | 改名索引生成最终记录 | issue merge、`SourceSymbol` / `RenameDecision` / category outcome 与 `RenameIndex` 组装 |

每个成功子阶段精确产生一次 `begin` 和一次 `end`。同一个 `_CliVNextProgress` 计算累计与阶段耗时，格式保持：

```text
[  0.123s] 开始 PySlang 解析与预处理 [compile.parse]
[  0.456s] 完成 PySlang 解析与预处理 [compile.parse]（本阶段 0.333s）
```

失败时不得用 `finally` 伪造“完成”；已开始但抛错的子阶段可以只有 begin。非 explicit-top 路径若实际没有某个
工作阶段，可以不发该阶段；同一 `build_source_catalog()` 内发生两次真实 compilation 时，相同 PySlang ID 可以按
实际调用次数重复出现，不得为了日志隐藏真实工作。

### 4.3 不改变外层合同

- T116 的六个外层阶段、顺序、累计时钟和结束总结继续存在；
- stdout 继续只有原有单行 JSON，字段和值的语义不变；
- stderr 新增子阶段行，`--quiet` 时全部消失；
- 不向 mapping、SourceSet、orchestration、metrics、manifest 或 restore report 持久化时间；
- 不新增 `--profile`、`--timing-file`、环境变量或默认输出文件。

## 5. 固定单模块输入与机器可检查输出

新增 compact fixture：

```text
tests/fixtures/t127_performance_probe/design.f
tests/fixtures/t127_performance_probe/owned/top.sv
```

其中只有一个 `t127_probe_top` module，包含输入、输出和一个可改名内部 signal。目标测试必须用公开 CLI 执行：

```text
origin=filelist
top=t127_probe_top
rewrite_roots=(owned,)
categories=all
```

测试必须证明：

1. 13 个固定子阶段在该 single-view 路径各 begin/end 一次，顺序与嵌套关系和 §4.2 一致；
2. 每个累计秒数单调不减，每个阶段耗时为非负有限小数；
3. outer compile 包含六个 compile 子阶段，outer rename index 包含七个 rename 子阶段；
4. stdout 仍是一个合法的原 schema JSON，实际 `rename > 0`、strict compile 通过、restore byte-identical；
5. `--quiet` 的 stderr 不含任何外层或子阶段；
6. 目标测试在成功后向测试进程 stdout 打印一行机器可解析证据：

```text
T127_SINGLE_MODULE_TIMING_JSON={"compile.parse":<seconds>,...,"rename_index.finalize":<seconds>}
```

JSON 必须正好包含 13 个 ID，值为本次 CLI stderr 的“本阶段”秒数。实际浮点数不冻结为测试阈值；本任务只取得
基线，不以开发机绝对时间决定通过。

## 6. 包含与不包含

### 包含

- 13 个固定粗粒度子阶段；
- observer 从 orchestration 向 SourceCatalog、PySlang helper 和 RenameIndex 的只读透传；
- T116 进度测试对新增嵌套阶段的兼容调整；
- 一个单模块、单 source、explicit-top、rewrite-root compact fixture 和公开 CLI 实测；
- README 与项目结构中对永久细分进度的简短说明。

### 不包含

- 不优化、缓存、并行化或裁剪 PySlang / RenameIndex；
- 不增加计数器、RSS、CPU、I/O、采样堆栈或 profile 文件；
- 不实现 `analysis-root`、analysis filelist、依赖闭包或 provider overlay；
- 不改变 `--rewrite-root`、四 category、name completeness、dead-source 或 readonly 判定；
- 不改变 CLI 参数、stdout JSON、公共 report/schema、mapping、gate、restore、错误码；
- 不运行真实 AIClusterWrapper；该输入只存在服务器，本任务固定本地单模块基线；
- 不创建下一张性能任务，不顺手修复探针暴露的热点。

## 7. 允许修改文件

子 Agent 只能修改：

```text
docs/tasks/T127_permanent_performance_probe.md
rtl_obfuscator/performance_probe.py
rtl_obfuscator/project_discovery.py
rtl_obfuscator/source_catalog.py
rtl_obfuscator/rename_index.py
rtl_obfuscator/orchestration_vnext.py
rtl_obfuscator/rewrite.py
tests/test_t127_performance_probe.py
tests/fixtures/t127_performance_probe/**
tests/test_t116_cli_report.py
README.md
docs/development/project_structure.md
```

需要修改其它文件、公共 schema 或测试 oracle 时，先记录偏差并停止，不得扩大范围。

## 8. 实现约束

1. observer 必须是同步、无状态控制作用的边界通知；不得影响函数返回值、异常和分支选择。
2. 探针开销只允许固定数量的 callback 与 stderr 行，不得与 node/token/record 数量线性增长。
3. 所有 stage ID 为内部稳定诊断合同；不得使用 fixture/module 名控制事件。
4. `compile.diagnostics` 必须包含当前完整诊断分类工作，不能只包 `getAllDiagnostics()` 而隐藏 vendor 分类成本。
5. `rename_index.name_completeness` 必须完整包住 `_apply_name_completeness()`，这是当前最重要的待测热点。
6. 现有 `stage_observer=None` 调用全部保持有效；不得要求测试或内部调用者必须提供 observer。
7. 不捕获 observer 之外的新异常，不以探针为由放宽任何 fail-closed 行为。

## 9. 固定验收命令

子 Agent 与主 Agent 都只运行以下五条，不追加 blanket discovery、RISC Formal 或性能优化实验：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t127_performance_probe -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t116_cli_report.T116DefinedFieldTests \
  tests.test_t116_cli_report.T116DivisionByZeroTests \
  tests.test_t116_cli_report.T116StdoutContractTests \
  tests.test_source_catalog \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_typedef_and_conversion_shapes_are_semantically_scoped \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_modport_ports_are_alias_occurrences_of_interface_members \
  tests.test_orchestration_vnext \
  tests.test_t115_name_completeness -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/performance_probe.py \
  rtl_obfuscator/project_discovery.py \
  rtl_obfuscator/source_catalog.py \
  rtl_obfuscator/rename_index.py \
  rtl_obfuscator/orchestration_vnext.py \
  rtl_obfuscator/rewrite.py \
  tests/test_t127_performance_probe.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T127_permanent_performance_probe.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t127_ready_for_review=pass")'
```

验收类型：展示层 / 性能可观测性。Formal 为 `N/A`，理由与 T116 相同：本任务不改变任何改名、mapping、
landed edit 或 gate 内容；目标测试要求真实 compact gate strict compile、实际 rename 和 byte-identical restore，
但不把 identity comparison 冒充 Formal。

## 10. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: f4db0b254852b356c114247495cea0a0379bc1b7
start_time: 2026-09-02 Asia/Shanghai
first_command: git status --short --branch && git rev-parse HEAD
review_correction: 2026-09-02 review returned T127 from READY_FOR_REVIEW to IN_PROGRESS. Owner registry timing must include final readonly duplicate inventory; a real compile substage failure test and a corrected, passing compatibility row are required. The original execution record had consecutive cleanup_candidates: none and cleanup_candidates: lines; corrected record retains one cleanup_candidates: none line.
allowed_files: docs/tasks/T127_permanent_performance_probe.md; rtl_obfuscator/performance_probe.py; rtl_obfuscator/project_discovery.py; rtl_obfuscator/source_catalog.py; rtl_obfuscator/rename_index.py; rtl_obfuscator/orchestration_vnext.py; rtl_obfuscator/rewrite.py; tests/test_t127_performance_probe.py; tests/fixtures/t127_performance_probe/**; tests/test_t116_cli_report.py; README.md; docs/development/project_structure.md
changed_files: docs/tasks/T127_permanent_performance_probe.md; rtl_obfuscator/performance_probe.py; rtl_obfuscator/project_discovery.py; rtl_obfuscator/source_catalog.py; rtl_obfuscator/rename_index.py; rtl_obfuscator/orchestration_vnext.py; rtl_obfuscator/rewrite.py; tests/test_t127_performance_probe.py; tests/fixtures/t127_performance_probe/design.f; tests/fixtures/t127_performance_probe/owned/top.sv; tests/test_t116_cli_report.py; README.md; docs/development/project_structure.md
commands: |
  baseline: conda run -n rtl_obfuscation python -m unittest tests.test_t127_performance_probe -v (before implementation; exit 1, ModuleNotFoundError: target test module absent)
  conda run -n rtl_obfuscation python -m unittest tests.test_t127_performance_probe -v (exit 0, Ran 6 tests, OK; emitted T127_SINGLE_MODULE_TIMING_JSON below)
  previous compatibility row: conda run -n rtl_obfuscation python -m unittest tests.test_t116_cli_report tests.test_source_catalog tests.test_t108_pyslang_rename_index tests.test_orchestration_vnext tests.test_t115_name_completeness -v (exit 1, Ran 52 tests, 4 pre-existing failures; clean HEAD copy reproduced the same T116 diagnostic x3 and T108 macro-interface preserve x1 failures)
  corrected compatibility row: conda run -n rtl_obfuscation python -m unittest tests.test_t116_cli_report.T116DefinedFieldTests tests.test_t116_cli_report.T116DivisionByZeroTests tests.test_t116_cli_report.T116StdoutContractTests tests.test_source_catalog tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_typedef_and_conversion_shapes_are_semantically_scoped tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_modport_ports_are_alias_occurrences_of_interface_members tests.test_orchestration_vnext tests.test_t115_name_completeness -v (exit 0, Ran 38 tests, OK; T116 and T108 clean-HEAD failure methods excluded without modification)
  conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/performance_probe.py rtl_obfuscator/project_discovery.py rtl_obfuscator/source_catalog.py rtl_obfuscator/rename_index.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/rewrite.py tests/test_t127_performance_probe.py (exit 0)
  git diff --check HEAD (exit 0)
  conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T127_permanent_performance_probe.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t127_ready_for_review=pass")' (exit 0)
results: target test 6/6 passed; single-module public CLI produced valid schema 2 stdout, rename > 0, strict_compile_passed=true, restored_byte_identical=true, and quiet stderr empty. The corrected compatibility row passed 38 tests. py_compile and diff check passed; final status guard printed t127_ready_for_review=pass.
T127_SINGLE_MODULE_TIMING_JSON: {"compile.catalog_inventory":0.001,"compile.diagnostics":0.003,"compile.elaborate":0.002,"compile.owner_registry":0.0,"compile.parse":0.002,"compile.top_closure":0.001,"rename_index.declarations":0.001,"rename_index.finalize":0.0,"rename_index.name_completeness":0.0,"rename_index.occurrences":0.001,"rename_index.semantic_inventory":0.0,"rename_index.syntax_inventory":0.0,"rename_index.unelaborated":0.0}
schema_or_behavior: Added one shared StageObserver type/helper and 13 stable coarse stage IDs. Existing outer T116 stages, stage order, return values, exceptions, stdout JSON, mapping, gate, restore, and random naming remain unchanged; observer parameters default to None and never persist timing. Public stderr renders child IDs with begin/end and stage duration. Moved explicit-top owner registry begin before final readonly duplicate inventory and added a real parse-substage failure assertion; added one explicit-top filelist/rewrite-root compact fixture and six black-box assertions.
boundaries: No optimization, counters, profile files, analysis-root, CLI/schema/report changes, or RISC Formal. The original broad compatibility row's four failures (T116 diagnostic x3 and T108 macro-interface preserve x1) were independently reproduced on clean HEAD and excluded by the corrected exact row; no unrelated oracle or product behavior was changed.
cleanup_candidates: none
formal_verification: N/A
reason: observability-only task; no rename/rewrite decision changes are authorized
review_request: READY_FOR_REVIEW; main Agent must independently rerun the corrected five contract commands, review the allowlist and clean-HEAD compatibility boundary, and decide acceptance. This sub-agent does not set ACCEPTED and did not commit or push.
```

## 11. 主 Agent 验收

```text
main_result: PASS after one bounded review correction within the frozen three-step plan and allowlist
reviewed_head: f4db0b254852b356c114247495cea0a0379bc1b7 + T127 working tree
scope_review: PASS; every changed path is listed in §7; no CLI flag, public JSON/report schema, mapping, gate, restore, category, readonly policy, analysis-root, cache, counter or optimization was added
code_review: PASS; one shared stateless StageObserver forwards exactly 13 stable coarse events; PySlang parse/elaborate/diagnostics, SourceCatalog inventory/closure/owner, and RenameIndex seven subphases are bounded without per-node callbacks; explicit-top owner timing includes final readonly duplicate inventory; failed substage emits begin without a forged end; observer=None and --quiet preserve existing behavior
single_module_timing: T127_SINGLE_MODULE_TIMING_JSON={"compile.catalog_inventory":0.001,"compile.diagnostics":0.003,"compile.elaborate":0.002,"compile.owner_registry":0.0,"compile.parse":0.002,"compile.top_closure":0.001,"rename_index.declarations":0.001,"rename_index.finalize":0.0,"rename_index.name_completeness":0.0,"rename_index.occurrences":0.001,"rename_index.semantic_inventory":0.0,"rename_index.syntax_inventory":0.0,"rename_index.unelaborated":0.0}
target_result: PASS; tests.test_t127_performance_probe, 6 tests, exit 0; real compact public CLI had rename > 0, strict compile pass, byte-identical restore, ordered/nested events and empty quiet stderr
compatibility_result: PASS; corrected exact row, 38 tests, exit 0; T115 actual-gate Formal positive exit 0 with formal_equivalence=pass and fixed functional negative exited nonzero with unproven/equiv_status -assert. The original broad row's T116 x3 and T108 x1 failures were independently identical on an archived clean HEAD copy and were not modified
py_compile: PASS; exact §9 command, exit 0
git_diff_check: PASS; git diff --check HEAD, exit 0
ready_for_review_guard: PASS before acceptance; t127_ready_for_review=pass
formal_verification: N/A
reason: observability-only behavior; T127 changes no rename/rewrite decision or landed edit. The compatibility row's existing T115 Formal evidence is supplementary and passed
accepted_by: Main Agent Codex
```

## 12. 验收后的唯一下一步

主 Agent 只根据 `T127_SINGLE_MODULE_TIMING_JSON` 和服务器后续以相同 stage ID 产生的日志，判断第二步是否应
优先优化 RenameIndex 的哪一个内部阶段。T127 不预先授权任何优化，也不自动创建新任务。
