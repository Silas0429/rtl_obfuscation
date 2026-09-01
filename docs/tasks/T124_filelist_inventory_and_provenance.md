# T124：filelist 轻量组装与来源语义保留

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 起始 HEAD：`d1c43d7ac8d00687eb6974654f78f4cce6c10338`
- 起始工作树：仅有主 Agent 新增但未提交的 `DRAFT` 诊断记录
  `docs/tasks/T123_real_filelist_resource_and_library_diagnosis.md`
- 任务类型：SourceSet resource refactor / filelist provenance foundation
- 服务器目标：PySlang `11.0.0`

## 1. 背景与本任务位置

真实 filelist 有 2573 个 entry，其中 2563 个 source unit、749 个 `-v` entry。当前
`from_filelist()` 在“读取 filelist / 组装 SourceSet”阶段立即对完整 filelist 做一次 PySlang semantic
compilation；服务器实测该阶段耗时 1815.719 秒，登录会话下约 20 GiB RSS 后被 cgroup SIGKILL。

后续 `build_source_catalog()` 还会重新做 `top=None` 和 explicit-top compilation；最新大内存作业在
`top=None` 路径达到约 599.4 GiB。因此后续要实现以
`/project/STPU2/maoyiming/work/s5_code/ChipPlatform/aic_ss/src` 为改写种子的精确分析集合，第一步必须先：

1. 让 SourceSet 组装只负责 filelist 结构、物理路径、include closure 和 rewrite allowlist，不做 semantic
   compilation；
2. 保留目前会被抹掉的 `-v` / bare / context / include-dir / define 来源和展开顺序，供后续 library provider
   选择及 overlay `design.f` 使用。

本任务只建立该基础，不声称已经解决后续 `build_source_catalog()` 的 599 GiB 全库编译。T124 验收后才能
冻结 scoped semantic analysis 任务。

## 2. 单一目标

把 authoritative filelist 的 SourceSet 组装改成无 PySlang、可保持有效 entry provenance 的轻量结构阶段，
同时保持最终 public CLI 的 fail-closed、原子输出和 compact actual-gate 正确性。

## 3. 冻结数据合同

### 3.1 有效 entry provenance

新增一个 immutable、live-only 的 filelist entry record，名称可按现有模块风格确定，但必须至少保存：

- `kind`：精确区分 `source`、`library_source`、`context_file`、`include_dir`、`define`；
- `value`：完成环境变量、相对路径和 source-root 归一化后的 canonical 值；
- `filelist`：产生该有效 entry 的物理 filelist 绝对路径；
- `line`：该 entry 在对应 filelist 中的 1-based 行号。

要求：

1. 嵌套 `-f` 按当前展开顺序扁平化；`-f` 自身不作为有效 compile entry，但子项必须保留自己的物理
   filelist 与行号；
2. 裸 `.sv/.v` 为 `source`，`-v PATH` 为 `library_source`；二者继续进入同一
   `ordered_source_files` / `compile_order` 顺序，T124 不实现 lazy library search；
3. 裸 `.svh/.vh/.h/.vic` 为 `context_file`；一行多个 `+incdir+` / `+define+` 值按行内顺序分别形成记录；
4. 现有 duplicate、missing file、非法 suffix、未定义环境变量和不支持指令继续在 SourceSet 阶段以原稳定
   `SourceSetError` fail closed；
5. provenance 必须一对一描述 parser 接受的有效 entry，不允许通过重新读取原 filelist 或根据 suffix 猜回
   `-v`；
6. provenance 先作为 `SourceSet` 的 live-only internal field；`SourceSet.to_report()`、mapping schema 2、
   restore schema 和当前 canonical gate `design.f` 在 T124 中保持原形。持久化及 overlay 输出留给后续任务；
7. single-file / project-root 的 provenance 为空，不改变这两种输入模式。

### 3.2 轻量 SourceSet 组装

filelist 模式的 `from_filelist()` / `_discover_sourceset(... authoritative_filelist=True)` 必须满足：

1. 不得调用 `compile_pyslang_source_set()`、`SyntaxTree.fromFiles()`、`Compilation.getRoot()` 或任何等价
   parse / semantic / elaborate API；
2. 继续返回完整 `ordered_source_files`、context + source `compile_order`、bounded include closure、
   include dirs、defines、top 和 rewrite roots；
3. `top_closure_files` 在这个结构阶段固定为空；top 存在性、top 歧义、parse diagnostics、semantic
   diagnostics 和 vendor compatibility diagnostics 延迟到 SourceCatalog / orchestration；
4. filelist 显式列出的物理路径、include 路径和 rewrite root 的结构性错误仍在输出创建前报告；
5. include discovery 可以继续以有界方式读取源文本，但不得保留所有 source body，也不得借机建立完整
   PySlang syntax tree；
6. public CLI 对缺失 top、parse error 和 semantic error 仍必须非零退出、不得创建输出。允许错误从
   SourceSet input stage 移到 mapping/catalog stage，但不得静默接受、吞掉 diagnostics 或发布半成品；
7. 没有 rewrite root 的既有 compact filelist CLI 仍能生成与 T124 前相同的 mapping、actual gate、restore
   和 Formal 结果。

## 4. 资源验收

新增直接 instrumentation，至少证明：

1. monkeypatch `compile_pyslang_source_set`、`SyntaxTree.fromFiles` 或等价入口为立即失败后，
   `from_filelist()` 对含 top、`-v`、context、include、define 和嵌套 `-f` 的 fixture 仍成功；
2. provenance 的 kind/value/filelist/line 和扁平顺序与原始 filelist 精确一致；
3. 一个由大量小 source entry 组成的临时 filelist，其 SourceSet 组装不会创建 PySlang compilation，且
   Python 额外内存随 entry metadata 而不是 semantic tree 增长；测试应直接约束调用边界，不以“小 fixture
   没 OOM”代替；
4. structural filelist 错误仍在 SourceSet 阶段，semantic/top 错误由后续 catalog/public CLI 原子拒绝。

## 5. 明确不包含

- 不实现 `analysis_compile_order`、外部 module stub、UnknownModule 放行或 dependency closure；
- 不缩小 `build_source_catalog()` 的 compile order，不删除其 `top=None` compilation；
- 不解决当前 `ADDF_D1_N_S6P25TL_C54L04` duplicate blocker；
- 不把 `-v` 自动设为只读或可改写，不实现 `-y`、`+libext` 或 simulator library priority；
- 不改变 rewrite eligibility、四个 category、NameFactory、mapping action/reason；
- 不改变当前输出目录布局，不生成 overlay filelist，不减少 gate/restore physical manifest；
- 不持久化 provenance，不升级 public schema；
- 不实现新的 vendor syntax compatibility；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 6. 允许修改的文件

- `docs/tasks/T124_filelist_inventory_and_provenance.md`
- `rtl_obfuscator/source_set.py`
- `rtl_obfuscator/project_discovery.py`
- `tests/test_t124_filelist_inventory_and_provenance.py`
- `tests/fixtures/t124_filelist_inventory_and_provenance/**`
- `tests/test_t098_authoritative_filelist.py`（只允许把 semantic/top 断言移动到 catalog/public CLI）
- `tests/test_t099_filelist_compile_context.py`（只允许把 semantic/top 断言移动到 catalog/public CLI）
- `tests/test_t117_filelist_v_library_source.py`（只允许增加 provenance 断言）
- `tests/test_source_set.py`
- `tests/test_source_catalog.py`
- `tests/test_project_root_inspect.py`
- `tests/test_t088_verilog_suffix.py`
- `tests/test_t090_filelist_context.py`
- `tests/test_t093_macro_fallback_and_cli_validation.py`
- `tests/test_t094_builtin_preprocessor_macros.py`
- `tests/test_t095_macro_formal_parameters.py`
- `tests/test_t097_local_typedef_discovery_scope.py`
- `tests/test_t118_vic_parameter_context.py`
- `tests/test_t121_vendor_model_readonly.py`
- `docs/development/project_structure.md`

上述新增旧测试只允许把 filelist `top_closure_files` 断言迁移为结构阶段为空，并把原有 top、parse、semantic、
vendor fail-closed 断言移动到 `build_source_catalog()` 或 public CLI；不得删除失败方向、放宽 diagnostic 分类或
把错误改成成功。不得修改 T123、rewrite/catalog/rename/mapping/orchestration 产品实现、README、公共 schema、
其它测试或 fixture。
若现有 API 使该 allowlist 不足，先在任务单记录阻塞，不得自行扩范围。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t124_filelist_inventory_and_provenance \
  tests.test_t098_authoritative_filelist \
  tests.test_t099_filelist_compile_context \
  tests.test_t117_filelist_v_library_source -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_set tests.test_source_catalog tests.test_project_root_inspect \
  tests.test_t088_verilog_suffix.VerilogSuffixTests.test_sourceset_accepts_mixed_v_and_vh_across_three_entries \
  tests.test_t090_filelist_context \
  tests.test_t091_h_macro_header tests.test_t093_macro_fallback_and_cli_validation \
  tests.test_t094_builtin_preprocessor_macros tests.test_t095_macro_formal_parameters \
  tests.test_t097_local_typedef_discovery_scope.T097LocalTypedefDiscoveryScopeTests.test_design_scope_typedefs_and_type_parameters_are_not_global_providers \
  tests.test_t097_local_typedef_discovery_scope.T097LocalTypedefDiscoveryScopeTests.test_compilation_unit_typedef_provider_is_reachable \
  tests.test_t097_local_typedef_discovery_scope.T097LocalTypedefDiscoveryScopeTests.test_compilation_unit_typedef_ambiguity_is_fail_closed_with_details \
  tests.test_t118_vic_parameter_context \
  tests.test_t119_filelist_multi_root_output tests.test_t120_explicit_vic_include_reference \
  tests.test_t121_vendor_model_readonly tests.test_t122_vendor_diagnostic_memory -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py \
  tests/test_t124_filelist_inventory_and_provenance.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T124_filelist_inventory_and_provenance.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t124_ready_for_review=pass")'
```

## 8. Formal verification

T124 不改变预期 RTL 输出，但改变 public filelist pipeline 的 semantic validation 时点。第一条验收命令中的
`tests.test_t117_filelist_v_library_source` 必须继续生成 actual renamed gate，并完成既有 Formal 正例与固定
功能负例：

```text
formal_verification: PASS required
gold: tests/fixtures/t117_filelist_v_library_source/bare.f
gate: test-created actual public CLI gate from design.f
top: t117_top
positive: exit 0 and JSON formal_equivalence=pass
negative: fixed 1'b0 -> 1'b1 mutation, strict compile pass, Formal nonzero
```

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: d1c43d7ac8d00687eb6974654f78f4cce6c10338
starting_worktree: untracked T123 diagnostic record plus this authorized T124 contract
changed_files: docs/tasks/T124_filelist_inventory_and_provenance.md; rtl_obfuscator/source_set.py; rtl_obfuscator/project_discovery.py; tests/test_t124_filelist_inventory_and_provenance.py; tests/fixtures/t124_filelist_inventory_and_provenance/**; tests/test_t098_authoritative_filelist.py; tests/test_t099_filelist_compile_context.py; tests/test_t117_filelist_v_library_source.py; tests/test_source_set.py; tests/test_source_catalog.py; tests/test_project_root_inspect.py; tests/test_t088_verilog_suffix.py; tests/test_t090_filelist_context.py; tests/test_t093_macro_fallback_and_cli_validation.py; tests/test_t094_builtin_preprocessor_macros.py; tests/test_t095_macro_formal_parameters.py; tests/test_t097_local_typedef_discovery_scope.py; tests/test_t118_vic_parameter_context.py; tests/test_t121_vendor_model_readonly.py; docs/development/project_structure.md
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t124_filelist_inventory_and_provenance tests.test_t098_authoritative_filelist tests.test_t099_filelist_compile_context tests.test_t117_filelist_v_library_source -v`; `conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_project_root_inspect tests.test_t088_verilog_suffix.VerilogSuffixTests.test_sourceset_accepts_mixed_v_and_vh_across_three_entries tests.test_t090_filelist_context tests.test_t091_h_macro_header tests.test_t093_macro_fallback_and_cli_validation tests.test_t094_builtin_preprocessor_macros tests.test_t095_macro_formal_parameters tests.test_t097_local_typedef_discovery_scope.T097LocalTypedefDiscoveryScopeTests.test_design_scope_typedefs_and_type_parameters_are_not_global_providers tests.test_t097_local_typedef_discovery_scope.T097LocalTypedefDiscoveryScopeTests.test_compilation_unit_typedef_provider_is_reachable tests.test_t097_local_typedef_discovery_scope.T097LocalTypedefDiscoveryScopeTests.test_compilation_unit_typedef_ambiguity_is_fail_closed_with_details tests.test_t118_vic_parameter_context tests.test_t119_filelist_multi_root_output tests.test_t120_explicit_vic_include_reference tests.test_t121_vendor_model_readonly tests.test_t122_vendor_diagnostic_memory -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py tests/test_t124_filelist_inventory_and_provenance.py`; `git diff --check HEAD`; `conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T124_filelist_inventory_and_provenance.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t124_ready_for_review=pass")'`
results: first command exit 0, Ran 19 tests, OK; T117 actual-gate Formal positive exit 0 with JSON `formal_equivalence=pass`, fixed functional negative exit 1 with `unproven` and `equiv_status -assert`; revised secondary compatibility command exit 0, Ran 68 tests, OK, including T088/T097 affected SourceSet/catalog migrations and T118/T119/T120/T121 actual-gate Formal rows; py_compile exit 0; diff check exit 0; READY_FOR_REVIEW guard exit 0 with `t124_ready_for_review=pass`
schema_or_behavior: authoritative filelist SourceSet assembly no longer calls PySlang compilation, syntax-tree construction, or hierarchy discovery; added frozen live-only `FilelistEntry(kind, value, filelist, line)` records with depth-first nested-filelist provenance; preserved structural source/context/include closure, canonical compile order, rewrite roots, report schema, mapping schema 2, restore schema, and gate `design.f`; filelist top closure and top/parse/semantic diagnostics now defer to SourceCatalog; single-file/project-root provenance remains empty
boundaries: `-v` remains an ordered source entry and does not implement lazy library selection; no analysis narrowing, stubs, duplicate-provider policy, new suffix/directive support, schema persistence, or RISC-V-Vector Formal; T123 remains untouched; T094/T095 parse failures and all T121 whitelist failures now fail at catalog/orchestration with the same blocking direction; T097 valid typedef providers are visible in catalog semantic owner ids; the pre-existing public ambiguity behavior remains outside this T124 migration and is excluded from the fixed compatibility row; the pre-existing T088 public helper/category behavior and readonly include behavior are likewise outside this T124 migration and are excluded from the fixed compatibility row.
cleanup_candidates: none
formal_verification: PASS required and observed through T117 compact actual gate; gold `tests/fixtures/t117_filelist_v_library_source/bare.f`; gate test-created public CLI gate from `design.f`; top `t117_top`; positive JSON `formal_equivalence=pass`; fixed `1'b0 -> 1'b1` mutation strict compile exit 0 and Formal nonzero with `unproven`/`equiv_status -assert`
review_request: first review rejected because the required secondary command had 17 failures. Main Agent confirmed the
  failures are stale assertions for the contract's intentional SourceSet-to-catalog validation move, expanded the test-only
  allowlist, and returned the task to READY. The revised fixed compatibility row excludes the two pre-existing unrelated
  public cases; all T124-affected tests now pass and the task is READY_FOR_REVIEW. Main Agent must independently rerun the
  required black-box checks before setting ACCEPTED.
rework_start: T124 sub-agent resumed after the expanded test-only allowlist was provided; no product files or T123 changes were added.
main_baseline_boundary_check: Main Agent exported clean HEAD d1c43d7 to /tmp and independently proved the two
  unrelated failures already exist before T124: T088 public three-mode test fails because the historical helper omits the
  now-required --category; T097 public typedef-ambiguity test expects nonzero but current HEAD exits 0. The fixed secondary
  command therefore targets only the SourceSet assertions affected by T124. T088 helper behavior and T097 public ambiguity
  require separate cleanup/semantic tasks and must not be changed here.
start_record: T124 sub-agent started after reading AGENTS.md, docs/tasks/README.md, this contract, the refactor protocol, project structure, and the directly referenced implementation/tests; starting `git status --short --branch` showed only untracked T123 and T124 task records at HEAD d1c43d7ac8d00687eb6974654f78f4cce6c10338.
```

## 10. 主 Agent 验收

```text
main_result: PASS
reviewed_head: d1c43d7ac8d00687eb6974654f78f4cce6c10338 + T124 working tree
scope_review: PASS; product changes are limited to source_set.py and project_discovery.py; all other T124
  changes are authorized task/docs/fixture/test migrations; pre-existing T123 remained untouched
code_review: PASS; authoritative filelist branch no longer constructs any PySlang view; FilelistEntry records are
  created during the original depth-first parse with physical filelist and 1-based line provenance; report/schema,
  compile_order, structural errors, duplicate handling and non-filelist adapters retain their frozen boundaries
target_command: conda run -n rtl_obfuscation python -m unittest
  tests.test_t124_filelist_inventory_and_provenance tests.test_t098_authoritative_filelist
  tests.test_t099_filelist_compile_context tests.test_t117_filelist_v_library_source -v
target_result: PASS; Ran 19 tests, OK
compatibility_command: the revised exact section 7 secondary command
compatibility_result: PASS; Ran 68 tests, OK
py_compile: PASS
git_diff_check: PASS
ready_for_review_guard: PASS; t124_ready_for_review=pass
formal_verification: PASS; T117 actual renamed gate positive exit 0 with JSON formal_equivalence=pass;
  fixed 1'b0 -> 1'b1 negative strict compile exit 0 and Formal exit 1 with unproven/equiv_status -assert
baseline_boundary_probe: PASS; clean HEAD d1c43d7 exported to /tmp independently reproduced the unrelated T088
  missing-category failure and T097 public typedef-ambiguity expectation failure, so neither was hidden or fixed in T124
remaining_boundary: build_source_catalog still compiles the complete filelist with top=None and therefore the real
  duplicate-provider / approximately 599.4 GiB path is not solved by T124; scoped semantic analysis is the next task
accepted_by: Main Agent Codex
```
