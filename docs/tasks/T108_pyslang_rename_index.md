# T108：以 PySlang 为唯一语义权威的四核心组 RenameIndex

- 状态：`READY_FOR_REVIEW`
- 主 Agent：Codex
- 子 Agent：仅允许 GPT-5.6 Luna Extra High（`gpt-5.6-luna`，`reasoning=xhigh`）
- 起始 HEAD：`9a6ab0d183757345b8b1e1012bebabf59f998d5f`
- 任务类型：四核心组 adapter replacement + schema 2 + legacy collector cleanup + compact rewritten-gate Formal
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- 用户批准范围：本任务预先授权删除旧 SymbolGraph/RewritePolicy collector、切换 mapping schema 2，并同步其直接消费者；输入模型和 PySlang 编译配置不得迁移。

## 1. 单一目标

以 PySlang compile/elaboration 结果作为唯一 syntax、name、type、owner 和 target 权威，把现有复杂
`SymbolGraph -> RewritePolicy` 二次推断替换为薄型 `RenameIndex`。产品只公开
`signals / ports / interface / struct / all`；能证明完整物理绑定时改名，不能证明时安全保留对应核心组，
不得猜测、吞异常或发布错误 gate。

稳定不等于承诺所有 PySlang 合法语法都实际改名：稳定表示每个已发布 edit 都有唯一 semantic target 与
物理 identifier token 证据，不能证明的组保持原文并报告原因。

## 2. 冻结公共接口与 schema

1. `--category` 必须至少出现一次且可重复，只接受 `signals`、`ports`、`interface`、`struct`、`all`；
   `all` 展开为前四组并按固定顺序去重。
2. 缺失 category 报 `CLI_VNEXT_CATEGORY_REQUIRED`；任何旧细分类或旧类别报
   `CLI_VNEXT_CATEGORY_INVALID`，错误中列出五个允许值。
3. `interface` 覆盖 interface 类型、source-backed 实例、成员和 modport；`struct` 覆盖物理
   `typedef struct/union` 类型及字段。
4. 新 mapping 使用 `format=rtl-obfuscation.mapping`、`schema_version=2`。所有持久化
   orchestration/mapping-execution/rate/restore 报告同步到 schema 2；嵌套 SourceSet 自身 schema 不变。
5. 解密和审计拒绝 schema 1，稳定错误码为 `RESTORE_MAPPING_VERSION_UNSUPPORTED`；不得保留 schema 1
   hydration、兼容 dataclass、双写或版本分派。
6. 每个 mapping record 至少包含：`record_id`、四组之一的 `category`、`kind`、`original_name`、
   `renamed_name`、`owner`、`semantic_kind`、物理 `declaration`、`occurrences`、`action`、`reason`。
   PySlang object identity 只在单次构建中作为索引 key，持久化时只记录 semantic kind 和 source evidence，
   不伪造跨进程 object identity。
7. mapping 顶层包含四组顺序的 `category_outcomes`。每项状态只能为 `renamed / preserved / empty`，并记录
   candidate/rename/preserve/unsupported 数量和带 file/start/message 的 issues。

## 3. 冻结实现边界

目标流水线：

```text
SourceSet -> SourceCatalog / PySlang elaboration -> RenameIndex
          -> Mapping schema 2 -> Rewrite -> strict compile -> restore / Formal
```

### 3.1 四组识别

- `signals`：PySlang module-owned `VariableSymbol/NetSymbol`；排除 PortSymbol 对应对象、parameter、
  interface member 和 aggregate field。
- `ports`：source-backed module `PortSymbol`；top boundary、outside closure 继续是明确策略边界。
- `interface`：source-backed interface definition、标量 instance、`InstanceArraySymbol` 根、成员和 modport。
  匿名 array element、`SystemCallInfo` 和其他 elaboration-only node 只可注册为已有 record 的 semantic alias，
  不建立 declaration/edit。
- `struct`：只有声明 syntax 为物理 `typedef struct/union` 的 source-backed alias 建立 type record；字段使用
  PySlang FieldSymbol 的真实声明。`parameter type`、syntax-less implicit conversion 和 canonical aggregate
  shape 不建立 record；显式 type token 只有直接绑定物理 typedef 时才是 occurrence。

### 3.2 绑定与组事务

- occurrence 只来自 PySlang 直接 target binding，并必须映射到唯一物理 identifier token；禁止按名称、
  filelist 顺序、文本搜索、canonical shape 或自建 scope lookup 选择 owner。
- source-less semantic node 直接忽略；它不能触发 range 探测，也不能生成空名称记录。
- `selected_top_boundary`、`outside_top_closure`、已识别的 `macro_origin_conflict` 是逐对象合同边界，不触发
  整组回滚。
- 未识别的 source-backed semantic shape、物理 token 不唯一、owner 不确定或 range 冲突是组级 binding
  issue：该组所有原本 eligible 的记录改为 preserve，issue 对象可标 unsupported；其他选中组继续。
- overall `PASS_FULL` 要求至少一个真实 rename 且无组级 binding issue；存在组级保留、显式 boundary 或
  `rename == 0` 时为 `PASS_PARTIAL`。编译、schema、range overlap、rewrite、strict compile 或 restore
  完整性失败仍为 `REFUSED_ATOMIC` 并清理 staged output。

### 3.3 明确禁止

- 不修改 SourceSet/filelist/project-root/single-file 输入语义和 PySlang compile helper。
- 不实现 SystemVerilog tokenizer/parser、正则 identifier inventory、名称 lookup fallback 或第二套 owner graph。
- 不按 StCache 文件、module、identifier、固定数量或路径特判。
- 不新增 category、兼容层、缓存、插件、配置格式或 schema 1 读取。
- 不运行或修改 RISC-V-Vector 验收与 fixture。

## 4. 固定 compact 输入与 replacement coverage

新增 `tests/fixtures/t108_pyslang_rename_index/`。主 `design.f` 覆盖四组可安全改名路径；同目录独立
boundary filelist 覆盖必须整组 preserve 的未知 source-backed 形状，避免“主 `all` 必须四组真实 rename”
与“未知形状必须整组 preserve”互相冲突。fixture 整体覆盖：

- 四组真实 declaration/reference 和 `--category all`；
- 同名 typedef 的 semantic target、`parameter type`、implicit conversion、explicit cast；
- interface 标量/一维/多维 instance array、匿名 element、member、modport、system call metadata；
- macro argument/body 唯一来源和一个固定冲突；
- top boundary、outside closure、source-less node、组级未知 source-backed shape；
- 可由 Yosys 读取的四组真实 rename Formal cone，以及固定功能负例。

旧测试删除仅限下列路径，语义 replacement 必须进入 T108 两个测试模块：

- `tests/test_symbol_graph_signals.py`
- `tests/test_symbol_graph_parameters.py`
- `tests/test_symbol_graph_genvars.py`
- `tests/test_rewrite_policy.py`
- `tests/test_vnext_category_closure.py`
- `tests/test_t069_sized_cast_parameter.py`
- `tests/test_t070_keyword_cast.py`
- `tests/test_t071_type_parameter_defparam.py`
- `tests/test_t072_nested_generate.py`
- `tests/test_t073_macro_owner.py`
- `tests/test_t075_owner_occurrence_firewall.py`
- `tests/test_t076_module_end_label.py`
- `tests/test_t077_multiple_quarantine_reason_merge.py`
- `tests/test_t079_parameter_default_occurrence.py`
- `tests/test_t080_expression_sized_cast_parameter.py`
- `tests/test_t081_enum_lexical_completeness_firewall.py`
- `tests/test_t082_function_end_label.py`
- `tests/test_t083_named_function_argument.py`
- `tests/test_t084_struct_pattern_field.py`
- `tests/test_t085_typedef_lexical_completeness_firewall.py`
- `tests/test_t100_macro_readonly_module_preserve.py`
- `tests/test_t101_unelaborated_physical_module_boundary.py`
- `tests/test_t103_selected_category_stable_outcomes.py`
- `tests/test_t104_symbol_level_macro_provenance.py`
- `tests/test_t105_struct_union_implicit_conversion.py`
- `tests/test_t106_semantic_type_reference_binding.py`

对应 fixture 只有在删除后被 `rg` 证明无引用时才允许删除；否则保留。T108 replacement 必须继续验证：
exact range、owner/shadowing、macro provenance、selected isolation、atomic output、strict gate、direct restore、
actual-gate Formal 正例和功能负例。

## 5. 允许修改

产品文件：

- 新增 `rtl_obfuscator/rename_index.py`；删除 `rtl_obfuscator/symbol_graph.py`、
  `rtl_obfuscator/rewrite_policy.py`。
- `rtl_obfuscator/__init__.py`
- `rtl_obfuscator/category_registry_vnext.py`
- `rtl_obfuscator/source_catalog.py`
- `rtl_obfuscator/mapping_vnext.py`
- `rtl_obfuscator/rewrite.py`
- `rtl_obfuscator/rewrite_vnext.py`
- `rtl_obfuscator/orchestration_vnext.py`
- `rtl_obfuscator/metrics_vnext.py`
- `rtl_obfuscator/rate_vnext.py`
- `rtl_obfuscator/rate_execution_vnext.py`
- `rtl_obfuscator/rate_metrics_vnext.py`
- `rtl_obfuscator/restore_vnext.py`
- `rtl_obfuscator/formal_vnext.py`

测试文件：第 4 节明确列出的删除路径，以及以下新增/直接消费者：

- `tests/test_t108_pyslang_rename_index.py`
- `tests/test_t108_public_core_flow.py`
- `tests/test_public_cli.py`
- `tests/test_mapping_vnext.py`
- `tests/test_rewrite_vnext.py`
- `tests/test_orchestration_vnext.py`
- `tests/test_restore_vnext.py`
- `tests/test_metrics_vnext.py`
- `tests/test_rate_vnext.py`
- `tests/test_rate_execution_vnext.py`
- `tests/test_rate_metrics_vnext.py`
- `tests/test_mapping_execution_vnext.py`
- `tests/test_cli_vnext_encryption.py`
- `tests/test_project_root_vnext.py`
- `tests/fixtures/t108_pyslang_rename_index/**`

文档文件：

- 本任务单
- `README.md`
- `docs/systemverilog_renaming_table.md`
- `docs/development/project_structure.md`
- `docs/development/future_work.md`
- `docs/development/architecture/stcache_core_category_stability.md`

任何额外文件都必须先在本任务“偏差或阻塞”记录并停止，等待主 Agent决定；子 Agent不得自行扩表。

## 6. 机器可验收结果

compact `all` 运行必须满足：

- mapping `format=rtl-obfuscation.mapping`、`schema_version=2`；selected categories 恰为四组；
- 四组均有真实 candidate 和 rename；已知 macro conflict 逐对象报告，不使其他对象回滚；
- `strict_compile_passed=true`、`restored_byte_identical=true`；range/manifest audit 无重复、重叠或越界；
- schema 1 restore 稳定拒绝；缺失/旧 category 使用第 2 节错误码；
- positive Formal 比较公开生成的 actual gate，exit 0 且 JSON `formal_equivalence=pass`；
- fixed functional negative strict compile 通过但 Formal 非零，包含 `unproven` 或 `equiv_status -assert`。

## 7. 固定验收命令（最多五条）

Baseline（开始实现前单独记录，不计最终门禁）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext \
  tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v
```

最终门禁：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow \
  tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext \
  tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rename_index.py rtl_obfuscator/category_registry_vnext.py \
  rtl_obfuscator/mapping_vnext.py rtl_obfuscator/rewrite_vnext.py \
  rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/restore_vnext.py \
  tests/test_t108_pyslang_rename_index.py tests/test_t108_public_core_flow.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'import subprocess; from pathlib import Path; status=next(line for line in Path("docs/tasks/T108_pyslang_rename_index.md").read_text().splitlines() if line.startswith("- 状态：")); changed={line[3:] for line in subprocess.run(["git","status","--porcelain"],check=True,text=True,capture_output=True).stdout.splitlines() if line}; committed=subprocess.run(["git","diff","--name-status","9a6ab0d","HEAD"],check=True,text=True,capture_output=True).stdout.splitlines(); assert status=="- 状态：`READY_FOR_REVIEW`",status; assert "docs/tasks/T108_pyslang_rename_index.md" in changed,changed; assert "rtl_obfuscator/rename_index.py" in changed,changed; assert any(line=="D\\trtl_obfuscator/symbol_graph.py" for line in committed),committed; assert any(line=="D\\trtl_obfuscator/rewrite_policy.py" for line in committed),committed; print("t108_ready_for_review=pass")'
```

`tests.test_t108_public_core_flow` 必须实际调用 `scripts/formal_equivalence.py` 完成 positive 和 fixed negative，
并在 unittest 输出或任务记录中给出 gold、actual gate、top、命令、退出码和 JSON/首个失败断言。

## 8. 同一任务的服务器 StCache 门禁

子 Agent本地门禁通过后可设 `READY_FOR_REVIEW`；主 Agent不得在服务器门禁前设置 `ACCEPTED`。
固定服务器命令为：

```sh
export PROJ=/home/lufengchi/workspace/ChipPlatform
FILELIST="$PROJ/aic_ss/src/stcache/StCache.f"
OUT=/home/lufengchi/workspace/test/stcache_all_t108_001

python rtl_encrypt.py \
  --filelist "$FILELIST" \
  --top StChCore \
  --category all \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --output-dir "$OUT"
```

必须满足：无 `REFUSED_ATOMIC`；strict compile 和 byte-identical restore 为 true；四组均识别到对象；
signals/interface/struct 及除既有 boundary 外的 ports 有真实 rename；只允许既有
`selected_top_boundary/outside_top_closure/macro_origin_conflict`；mapping schema 2 且 range audit 通过。

服务器失败时任务回到 `IN_PROGRESS`，仍在本合同和同一模型内修正，不创建 T109。

## 9. 子 Agent 强制顺序与记录

1. 完整阅读 `AGENTS.md`、`CLAUDE.md`、本合同、执行规范及本合同链接的结构/类别文档。
2. 确认起始 HEAD、干净工作区和唯一活动任务；第一次产品编辑前设 `IN_PROGRESS` 并填写开始记录。
3. 运行 baseline；按 RenameIndex 数据合同、四组识别、mapping/rewrite/restore、CLI/docs 顺序小步实现。
4. 只运行第 7 节门禁；不得 blanket discovery、RISC Formal、commit、push、ACCEPTED 或创建下一任务。
5. 通过后填写 changed files、命令、结果、schema/behavior、boundary、cleanup replacement 和 Formal 证据，
   再设 `READY_FOR_REVIEW`。

执行记录：

```text
status: READY_FOR_REVIEW
starting_head: 9a6ab0d183757345b8b1e1012bebabf59f998d5f
started_at: 2026-08-26T17:10:00+08:00
rework_start: 2026-08-26T18:23:41+08:00; returned by Main Agent under §10 review; four frozen corrections: direct FieldSymbol binding, complete semantic/range/transaction coverage, T073/T075 cleanup migration, and schema-2 consumer invariants
second_rework_start: 2026-08-26T19:02:00+08:00; returned by Main Agent under §10.1 review; frozen corrections: group-wide preserve for unknown binding issues and independent boundary filelist for macro-generated struct field
third_rework_start: 2026-08-26T19:34:00+08:00; returned by Main Agent under §10.2 review; frozen correction: add an eligible ordinary struct/field to boundary.f and prove group-wide struct preserve with rename=0
fourth_rework_start: 2026-08-26T19:13:11+08:00; returned by Main Agent under §10.3 review; frozen correction: deduplicate a same-record occurrence whose physical range equals the declaration while preserving cross-record conflict handling
server_rework_start: 2026-08-26T19:41:51+08:00; returned by Main Agent under §12 review after StCache server gate; frozen correction: make every selected declaration/typed-token location fail closed with semantic diagnostics or group preserve, including macro-backed interface declarations and source-less array elements
server_rework_review_start: 2026-08-26T20:12:00+08:00; returned by Main Agent under §12.1 review; frozen correction: centralize typed declaration-token resolution, recover macro locations only through SourceManager original locations and byte validation, alias elaboration wrappers, and allow macro_interface real interface rename while preserving independent invalid-token group rollback
rework_scope: only §12 server-gate correction within the existing T108 product, fixture, test, and contract allowlist; no public interface, schema, category, validator, compatibility layer, parser, or gate expansion
first_command: conda run -n rtl_obfuscation python -m unittest tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v
allowed_files_checked: section 5 allowlist; no overlap with pre-existing user changes
current_stage: §12.1 server-gate review rework complete; centralized typed declaration resolution maps uniquely proven macro interface declarations to original bytes, aliases elaboration wrappers, ignores anonymous elements, and preserves invalid typed-token groups; final gates 1-4 passed; ready for Main Agent review
first_risk: interface array elements and macro-expanded occurrences may be source-less or non-unique; handled as semantic aliases or preserve issues, never fabricated ranges
changed_files: README.md; docs/development/architecture/stcache_core_category_stability.md; docs/development/future_work.md; docs/development/project_structure.md; docs/systemverilog_renaming_table.md; docs/tasks/T108_pyslang_rename_index.md; rtl_obfuscator/category_registry_vnext.py; rtl_obfuscator/mapping_vnext.py; rtl_obfuscator/metrics_vnext.py; rtl_obfuscator/orchestration_vnext.py; rtl_obfuscator/rate_execution_vnext.py; rtl_obfuscator/rate_metrics_vnext.py; rtl_obfuscator/rate_vnext.py; rtl_obfuscator/rename_index.py; rtl_obfuscator/restore_vnext.py; rtl_obfuscator/rewrite.py; rtl_obfuscator/rewrite_vnext.py; rtl_obfuscator/source_catalog.py; deleted rtl_obfuscator/symbol_graph.py and rtl_obfuscator/rewrite_policy.py; tests/test_t108_pyslang_rename_index.py; tests/test_t108_public_core_flow.py; tests/fixtures/t108_pyslang_rename_index/**; direct-consumer tests/test_public_cli.py, tests/test_mapping_vnext.py, tests/test_rewrite_vnext.py, tests/test_orchestration_vnext.py, tests/test_restore_vnext.py, tests/test_metrics_vnext.py, tests/test_rate_vnext.py, tests/test_rate_execution_vnext.py, tests/test_rate_metrics_vnext.py, tests/test_mapping_execution_vnext.py, tests/test_cli_vnext_encryption.py, tests/test_project_root_vnext.py; deleted section-4 legacy tests
commands: baseline `conda run -n rtl_obfuscation python -m unittest tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v`
results: baseline exit 1; 64 tests, 59 passed, 5 failed on the pre-T108 SymbolGraph/RewritePolicy expectations; not used as acceptance evidence
commands: replacement/direct-consumer suite `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_mapping_execution_vnext tests.test_cli_vnext_encryption tests.test_project_root_vnext -v`
results: exit 0; 31 tests passed; compact all has four real groups, strict compile, schema 2 and byte-identical restore
schema_or_behavior: PySlang-only RenameIndex; ModportPortSymbol aliases existing interface-member records; struct member references bind direct FieldSymbol records; public encrypt/decrypt envelopes and persisted mapping/execution/rate/metrics/restore reports use schema 2; schema 1 mapping is rejected with RESTORE_MAPPING_VERSION_UNSUPPORTED; public category and input-mode checks are strict
boundaries: no StCache special case; no name/regex semantic fallback; no second parser, owner graph, or schema 1 hydration; source-less elaboration nodes are ignored or aliased; selected top/outside closure and recognized macro conflicts remain explicit per-object preserves; server StCache gate is not claimed locally
cleanup_candidates: first delivery deleted 25 obsolete SymbolGraph/RewritePolicy/category tests, but Main Agent review found tests/test_t073_macro_owner.py and tests/test_t075_owner_occurrence_firewall.py still import removed category/SymbolGraph surfaces; both paths are now explicitly authorized for replacement cleanup, and coverage must move into T108 tests
commands: pre-rework gate 1 `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v`; exit 0, 23 tests passed, including actual Formal positive/negative
commands: pre-rework gate 2 `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py rtl_obfuscator/category_registry_vnext.py rtl_obfuscator/mapping_vnext.py rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/restore_vnext.py tests/test_t108_pyslang_rename_index.py tests/test_t108_public_core_flow.py`; exit 0
commands: pre-rework gate 3 `git diff --check HEAD`; exit 0
commands: pre-rework gate 4 was recorded as passed before Main Agent returned T108 to IN_PROGRESS; it is not current acceptance evidence
results: pre-rework gates 1-4 passed; the task was nevertheless returned for §10 corrections, so those results were superseded by the current rework
formal_verification: positive PASS via actual `scripts/formal_equivalence.py`: command `python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t108_pyslang_rename_index/formal.f --gold-root tests/fixtures/t108_pyslang_rename_index --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-herm0cie/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-herm0cie/gate --top formal_top --seq 5`; gold `tests/fixtures/t108_pyslang_rename_index`, gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-herm0cie/gate`, top `formal_top`, exit 0, JSON `{"formal_equivalence":"pass","seq":5,"top":"formal_top"}`; fixed functional negative uses the actual renamed gate with `formal.sv` changed from `<= in_a;` to `<= ~in_a;`, command uses the same gold and top with gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-herm0cie/negative`, strict PySlang compile 0/0, exit 1, evidence `unproven` and `equiv_status -assert`
review_request: returned by Main Agent to IN_PROGRESS under §12; current local evidence is superseded until the unchanged §7 gates are rerun
rework_completed_at: 2026-08-26T18:47:00+08:00
rework_changes: replaced per-record occurrence assignment with range-keyed semantic claims; repeated claims by one record are deduplicated during collection; macro-provenance conflicts remove the shared occurrence from every claimant, mark eligible claimants unsupported, and add physical range issues; unknown cross-record claims remove the shared occurrence, preserve every eligible record in the affected category, and add a group issue; added T108 assertions for issue ranges, conflict removal, same-record deduplication, and unknown group preserve
rework_commands: `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t073_macro_owner tests.test_t075_owner_occurrence_firewall tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_mapping_execution_vnext tests.test_cli_vnext_encryption tests.test_project_root_vnext`; `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_mapping_vnext tests.test_rate_vnext -v`; `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v`
rework_results: direct consumer suite exit 0, 14 tests passed; focused range/index suite exit 0, 12 tests passed; T108 gate 1 exit 0, 34 tests passed; compact all strict compile and direct restore passed; actual Formal positive exit 0 with JSON `{"formal_equivalence":"pass","seq":5,"top":"formal_top"}`; fixed functional negative strict PySlang compile passed and Formal exit 1 with `unproven; equiv_status -assert`
rework_formal: gate 1 test command invoked `scripts/formal_equivalence.py` with gold filelist/root `tests/fixtures/t108_pyslang_rename_index/formal.f` / `tests/fixtures/t108_pyslang_rename_index`, actual positive gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-wlv2230c/gate`, top `formal_top`, `--seq 5`, exit 0, JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-wlv2230c/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t108_pyslang_rename_index","seq":5,"top":"formal_top"}`; fixed functional negative copied that actual gate, changed `formal.sv` from `<= in_a;` to `<= ~in_a;`, strict PySlang compile remained 0/0, same gold/top and negative gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-wlv2230c/negative`, exit 1 with `unproven; equiv_status -assert`
range_policy: mapping and rewrite validators remain strict; they reject duplicate/overlap ranges. RenameIndex is the only layer permitted to deduplicate one semantic record or resolve a diagnosed cross-record claim, and it never deduplicates two distinct records silently.
rework_boundaries: no category, parser, compatibility layer, schema 1 hydration, StCache special case, or server-gate claim was added
second_rework_completed_at: 2026-08-26T19:18:00+08:00
second_rework_changes: unknown binding reasons now trigger preserve for every eligible record in the affected core group while retaining physical file/start/message issues; macro_origin_conflict remains per-object; macro-generated struct field moved from main design.f to boundary.f/boundary.sv and boundary coverage asserts every struct record is preserved with zero struct renames; main design.f retains real rename candidates in all four groups
second_rework_commands: `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index -v`; `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t073_macro_owner tests.test_t075_owner_occurrence_firewall tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_mapping_execution_vnext tests.test_cli_vnext_encryption tests.test_project_root_vnext`; `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v`
second_rework_results: focused T108 suite exit 0, 8 tests passed; direct consumer suite exit 0, 14 tests passed; exact §7 gate 1 exit 0, 35 tests passed; main compact all has real rename in signals/ports/interface/struct, strict compile and direct restore passed; boundary compact all reports struct candidate 1, rename 0, preserve 1, issue `boundary.sv` with `source_binding_incomplete`; actual Formal positive exit 0 with JSON `{"formal_equivalence":"pass","seq":5,"top":"formal_top"}`; fixed functional negative strict PySlang compile passed and Formal exit 1 with `unproven; equiv_status -assert`
second_rework_formal: gate 1 invoked actual `scripts/formal_equivalence.py` with gold `tests/fixtures/t108_pyslang_rename_index/formal.f`, gold root `tests/fixtures/t108_pyslang_rename_index`, actual gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-nxzi84y4/gate`, negative gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-nxzi84y4/negative`, top `formal_top`, `--seq 5`, positive exit 0 JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-nxzi84y4/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t108_pyslang_rename_index","seq":5,"top":"formal_top"}`; negative changed `formal.sv` from `<= in_a;` to `<= ~in_a;`, strict compile 0/0, exit 1, evidence `unproven; equiv_status -assert`
third_rework_completed: completed in the current controlled run after the recorded third_rework_start and before the final gate rerun
third_rework_changes: boundary.f/boundary.sv now compile an ordinary source-backed `ordinary_struct_t` with `ordinary_field` alongside macro-generated `boundary_macro_struct_t`; the replacement test proves both ordinary records and the unknown macro struct are present, proves `boundary_field` has no source-backed struct record, asserts every struct record is preserved with `rename=0`, and asserts the `source_binding_incomplete` issue is anchored to the unknown macro struct declaration
third_rework_commands: `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py rtl_obfuscator/category_registry_vnext.py rtl_obfuscator/mapping_vnext.py rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/restore_vnext.py tests/test_t108_pyslang_rename_index.py tests/test_t108_public_core_flow.py`; `git diff --check HEAD`; exact §7 status guard
third_rework_results: exact §7 gate 1 exit 0, 35 tests passed; boundary test passed with ordinary struct type/field plus macro struct, all 3 struct records preserved, `rename=0`, and `source_binding_incomplete` at the macro struct declaration; actual Formal positive exit 0 with JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-slpo5158/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t108_pyslang_rename_index","seq":5,"top":"formal_top"}`; fixed functional negative strict PySlang compile 0/0 and Formal exit 1 with `unproven; equiv_status -assert`; gate 2 exit 0; gate 3 exit 0; gate 4 exit 0 with `t108_ready_for_review=pass`
third_rework_formal: exact §7 gate 1 invoked `scripts/formal_equivalence.py`; gold filelist/root `tests/fixtures/t108_pyslang_rename_index/formal.f` / `tests/fixtures/t108_pyslang_rename_index`, actual positive gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-slpo5158/gate`, negative gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-slpo5158/negative`, top `formal_top`, `--seq 5`, positive exit 0 JSON `formal_equivalence=pass`; negative copied the actual gate, changed `formal.sv` from `<= in_a;` to `<= ~in_a;`, strict PySlang compile remained 0/0, exit 1 with `unproven; equiv_status -assert`
third_rework_boundaries: no product algorithm or public interface changed; no compatibility layer, fallback, parser, category, schema, gate, server claim, commit, push, ACCEPTED, or T109
fourth_rework_completed: completed in the current controlled run after the recorded fourth_rework_start and before the final gate rerun
fourth_rework_changes: `_claim_occurrence` now omits an occurrence when its physical range equals the same record declaration, retaining the declaration as the sole edit while preserving the range claim for cross-record conflict detection; added a direct same-record regression and kept the different-record conflict regression asserting group-level preserve
fourth_rework_commands: `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_same_record_declaration_range_keeps_only_the_declaration tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_unknown_cross_record_claim_preserves_the_entire_core_group tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes -v`; exact §7 gate 1; exact §7 gate 2; exact §7 gate 3; exact §7 gate 4
fourth_rework_results: focused direct regressions passed; exact §7 gate 1 exit 0, 36 tests passed; actual Formal positive exit 0 with JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-_lweb65k/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t108_pyslang_rename_index","seq":5,"top":"formal_top"}`; fixed functional negative strict PySlang compile 0/0 and Formal exit 1 with `unproven; equiv_status -assert`; gate 2 exit 0; gate 3 exit 0; gate 4 exit 0 with `t108_ready_for_review=pass`
fourth_rework_boundaries: mapping/rewrite validators remain strict; no cross-record silent deduplication; no fixture target, public interface, schema, other algorithm, compatibility layer, fallback, parser, server claim, commit, push, ACCEPTED, or T109
server_rework_completed: completed in the current controlled run after the recorded server_rework_start and before the final gate rerun
server_rework_changes: all selected declaration and typed-token location paths now fail closed; invalid source-backed locations produce `source_binding_incomplete` issues carrying semantic kind/name and directly available file/start evidence, while source-less or anonymous interface array elements remain aliases/ignored and do not create records; added compact macro-backed ModportSymbol/InstanceSymbol/InstanceArraySymbol coverage, source-less array assertions, and invalid typed-token regression; schema 2, strict range validators, Formal flow, and server command are unchanged
server_rework_commands: `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py rtl_obfuscator/category_registry_vnext.py rtl_obfuscator/mapping_vnext.py rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/restore_vnext.py tests/test_t108_pyslang_rename_index.py tests/test_t108_public_core_flow.py`; `git diff --check HEAD`; exact §7 status guard
server_rework_results: exact §7 gate 1 exit 0, 38 tests passed; macro-backed interface CLI schema 2 flow completed with strict compile and direct restore; actual Formal positive exit 0 with JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-qe1nnigz/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t108_pyslang_rename_index","seq":5,"top":"formal_top"}`; fixed functional negative strict PySlang compile 0/0 and Formal exit 1 with `unproven; equiv_status -assert`; gate 2 exit 0; gate 3 exit 0; gate 4 exit 0 with `t108_ready_for_review=pass`
server_rework_boundaries: no name/text fallback, second parser, new category, schema change, validator relaxation, fixture target change, compatibility layer, server-gate claim, commit, push, ACCEPTED, or T109
server_rework_review_completed: completed in the current controlled run after the recorded server_rework_review_start and before the final gate rerun
server_rework_review_changes: centralized declaration resolution with typed token priority and SourceManager original-location plus byte validation; ModportSymbol uses syntax.name, interface scalar/array roots use syntax.decl.name, and interface definitions use syntax.header.name; source-backed elaboration wrappers alias existing records; anonymous array elements are ignored; macro-generated aggregate fields remain an unknown-shape boundary and trigger struct-group preserve; compact macro interface now has real interface renames while the independent invalid typed-token regression preserves the full interface group
server_rework_review_commands: `conda run --no-capture-output -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow -v`; exact §7 gate 1; exact §7 gate 2; exact §7 gate 3; exact §7 gate 4
server_rework_review_results: focused suite exit 0, 12 tests passed; macro_interface interface outcome has rename=3 and preserve=2 with macro_if/value/macro_mp renamed and top-boundary if0/if_array preserved, strict compile and byte-identical restore passed; invalid typed-token regression preserves all eligible interface records; exact §7 gate 1 exit 0, 38 tests passed; actual Formal positive exit 0 with JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-pad881sg/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t108_pyslang_rename_index","seq":5,"top":"formal_top"}`; fixed functional negative strict PySlang compile 0/0 and Formal exit 1 with `unproven; equiv_status -assert`; gate 2 exit 0; gate 3 exit 0; gate 4 exit 0 with `t108_ready_for_review=pass`
server_rework_review_boundaries: no public category/schema/validator/Formal/server command change; no name/text/filelist fallback, compatibility layer, second parser, StCache special case, commit, push, ACCEPTED, or T109
final_gate_1: current exact §7 command exit 0; 38 tests passed, including selected-location fail-closed coverage, macro-backed interface declaration/instances, source-less array elements, invalid typed tokens, same-record declaration/occurrence deduplication, different-record conflict/group preserve, boundary ordinary-plus-unknown struct group preservation, duplicate/overlap, atomic/tamper, schema 2 restore, compact all strict compile/restore, and actual Formal positive/negative; Formal positive actual gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-pad881sg/gate`, top `formal_top`, exit 0, JSON `formal_equivalence=pass`; fixed functional negative actual gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t108-formal-pad881sg/negative`, top `formal_top`, exit 1, evidence `unproven; equiv_status -assert`
final_gate_2: current exact §7 py_compile command exit 0
final_gate_3: current exact `git diff --check HEAD` exit 0
final_gate_4: current §7 status guard exit 0; current HEAD `d1c45b6` already contains the T108 cleanup, so the guard verifies `symbol_graph.py` and `rewrite_policy.py` deletions in `git diff 9a6ab0d..HEAD` and the current task/index changes; printed `t108_ready_for_review=pass`
```

## 10. 主 Agent第一次审查退回（合同不变）

主 Agent独立复跑第 7 节 gate 1：exit 0，23 tests passed，actual-gate Formal positive/negative 均符合
预期；但代码与 replacement coverage 审查不通过，因此不得保留 `READY_FOR_REVIEW`：

1. `rename_index.py` 的 struct field 注册仍调用 `canonical.find(field_name)`，这是按名字寻找
   FieldSymbol，与本合同“direct FieldSymbol、不按名字猜”冲突。必须从 PySlang semantic aggregate/field
   对象直接取得每个 FieldSymbol 及其 source-backed declaration，再建立 record。
2. T108 fixture/测试没有覆盖第 4 节冻结的 macro argument/body 唯一来源与冲突、同名 typedef、
   `parameter type`、implicit conversion、unknown source-backed shape 的整组 preserve、range duplicate/overlap
   和 atomic/tamper 门禁。不得用三个 RenameIndex 测试替代这些仍有效的不变量。
3. `tests/test_t073_macro_owner.py`、`tests/test_t075_owner_occurrence_firewall.py` 仍引用已删除 API；主 Agent
   独立命令 exit 1，均在 import 阶段失败。两条路径现加入第 4 节 cleanup allowlist，相关 macro/owner
   不变量必须迁入 T108 replacement tests；RISC-V-Vector 测试仍不修改、不运行。
4. direct-consumer 测试可删除旧 category/count oracle，但必须保留 schema 2 下仍有效的 name factory
   collision/invalid、range duplicate/overlap、manifest/tamper、strict failure atomic cleanup、direct restore
   byte identity、path conflict 和 pipeline identity 检查。

同一 GPT-5.6 Luna Extra High 子 Agent必须先记录 rework start，然后在原产品/fixture/测试/文档 allowlist 内
修正；不创建 T109、不恢复兼容层、不增加门禁步骤。修正后重新执行原第 7 节四条门禁并更新同一执行记录。

### 10.1 主 Agent第二次审查退回（合同不变）

第一次返工已移除名称 fallback，并补齐 macro provenance、range transaction 和 direct-consumer 不变量；
但主 Agent静态审查发现，未知 source-backed struct field 当前只保留对应 typedef，而同一输入中的其他
`struct` record 仍会 rename。这违反第 3.2 节“证明缺失触发该核心组整体保留”的事务边界。

同一子 Agent必须完成以下修正：

1. 任一核心组出现 `source_binding_incomplete`、未知 source-backed shape、owner 不确定或其他非已知策略
   binding issue 时，该输入中该核心组所有原本 eligible 的记录必须 preserve，并保留具体 file/start/message；
   `macro_origin_conflict` 仍是已知逐对象边界，不得错误升级为整组回滚。
2. 将 macro-generated struct field 的未知形状移到独立 boundary filelist；主 `design.f --category all` 不含
   未知形状，继续满足四组均有真实 rename。boundary 测试必须断言其 `struct` 组全部 preserve，不能只断言
   单个 typedef。
3. 不改变公开 category、schema 2、allowlist、验收命令、Formal 或服务器门禁；不增加名称 fallback、解析器、
   StCache 特判、兼容层或新任务。

修正后必须重新执行原第 7 节四条门禁并更新同一执行记录；此前 `READY_FOR_REVIEW` 与门禁结果均被本次
退回取代。

### 10.2 主 Agent第三次审查退回（合同不变）

§10.1 产品实现已经加入组级 preserve，但 boundary fixture 当前只有一个 struct record；现有断言只能证明
“未知 typedef 自身被 preserve”，不能证明“同组另一个原本 eligible 的 typedef/field 也被事务性回滚”。

同一子 Agent只需完成一个冻结修正：在 `boundary.f` 输入中增加至少一个完全 source-backed、原本 eligible
的普通 struct/field，并让测试先证明该输入至少包含未知记录和普通记录，再断言因未知 binding issue 导致
该输入全部 struct records preserve、`rename=0`，且 issue 仍定位到未知 macro-generated field。不得修改
产品算法、公开接口、schema、门禁或其他 fixture 目标。

修正后重新执行原第 7 节四条门禁并更新同一执行记录；此前 `READY_FOR_REVIEW` 与门禁结果再次被本次
退回取代。

### 10.3 主 Agent独立门禁退回（合同不变）

主 Agent在 §10.2 后独立执行原第 7 节 gate 1，35 tests 中 34 通过，actual-gate Formal 正例通过且固定
功能负例正确失败；唯一失败为公开 `design.f --category all` CLI 在 mapping 阶段拒绝：
`MAPPING_RANGE_OVERLAP: ranges contain an exact duplicate`。同一公开测试隔离运行通过，40 个独立
`PYTHONHASHSEED` 进程也未复现，因此不得把一次 rerun 通过当作根因修复。

静态检查确认 `_claim_occurrence` 只去重 occurrence 与 occurrence，没有显式排除“同一 semantic record 的
occurrence range 等于其 declaration range”。二者本来就是同一个物理 edit；若 PySlang 某次遍历把声明
token 同时暴露为直接绑定引用，mapping 会稳定地拒绝重复 range。

同一子 Agent必须：

1. 在 RenameIndex claim 层将“同 record、同 declaration range”的 occurrence 作为同一物理 edit 去重；
   不放宽 mapping/rewrite duplicate/overlap validator，不跨 record 静默去重。
2. 增加直接回归：同 record 的 declaration/occurrence 相同只保留 declaration；不同 record 争用该 range
   仍走既有 conflict/组级 preserve，不能被新规则吞掉。
3. 运行原第 7 节四条门禁并更新同一记录；不改其他算法、公开接口、schema、fixture 目标或任务步骤。

此前 `READY_FOR_REVIEW` 与门禁结果被本次退回取代。

## 11. 主 Agent验收与交付

主 Agent在 `READY_FOR_REVIEW` 后独立审查 allowlist、replacement coverage、range/edit 字节和 schema 2，
复跑第 7 节四条命令及其中实际的 Formal 正负例。随后等待第 8 节服务器证据；全部通过才可设
`ACCEPTED`、提交 `[REFACTOR] Replace SymbolGraph with PySlang rename index` 并推送。验收后不自动创建
T109。

### 11.1 主 Agent本地验收记录

```text
reviewed_at: 2026-08-26T20:10:00+08:00
starting_head_verified: 9a6ab0d183757345b8b1e1012bebabf59f998d5f
allowlist_review: pass; changes are limited to §4/§5 product, replacement tests, T108 fixture and documentation paths
architecture_review: pass; product consumers no longer import SymbolGraph/RewritePolicy; no name lookup fallback, regex semantic parser, schema-1 hydration or StCache special case found
main_gate_1: exit 0; 36 tests passed
main_formal_positive: actual renamed gate; exit 0; JSON formal_equivalence=pass; top=formal_top; seq=5
main_formal_negative: strict PySlang compile 0/0; exit 1; evidence unproven and equiv_status -assert
main_gate_2: exact §7 py_compile exit 0
main_gate_3: exact git diff --check HEAD exit 0
main_gate_4: exact READY_FOR_REVIEW guard exit 0; t108_ready_for_review=pass
main_range_audit: schema_version=2; records=42; ranges=112; every declaration/occurrence byte equals original_name; no duplicate/overlap
main_core_counts: signals rename=13 unsupported=2; ports rename=12 preserve=2; interface rename=4 preserve=3; struct rename=6
main_local_result: PASS
server_gate: PENDING; §8 StCache evidence is required before ACCEPTED
delivery_override: 2026-08-26 user explicitly requested commit/push before the server gate so the server can synchronize T108; this delivery does not change task status or claim ACCEPTED
```

## 12. 服务器 StCache 第一次门禁退回（合同不变）

服务器在已推送提交 `d1c45b6` 上运行第 8 节固定命令，PySlang compile/elaboration 后进入 RenameIndex，
但 mapping 前原子拒绝：

```text
detail: ORCHESTRATION_MAPPING_INVALID
message: REFUSED_ATOMIC: semantic location is invalid
```

该结果违反第 3.1/3.2 节：source-less elaboration node 应忽略或只作 alias；source-backed node 的物理绑定
无法证明时应形成带位置的核心组 preserve issue，不得由未捕获的 `_range_for_location` 异常终止全部四组。

同一 GPT-5.6 Luna Extra High 子 Agent必须在原 T108 内完成：

1. 审计 RenameIndex 所有 selected declaration/typed-token location 入口，消除 `ModportSymbol`、interface
   scalar/array root、macro-backed declaration 等路径上的未捕获 semantic location 异常。
2. source-less/anonymous elaborated element 不建 record、不生成 edit；有 syntax/source 证据但无法映射唯一物理
   token 时，记录 semantic kind/name 与可得位置，并触发对应核心组 preserve。禁止按名字、文本或 filelist
   顺序 fallback。
3. 增加 compact replacement coverage，至少覆盖 macro-backed interface declaration、source-less array element
   与 typed-token 位置无效；CLI 必须完成 schema 2 mapping/strict compile/restore，或按合同输出组级 preserve，
   不得再出现 `semantic location is invalid` orchestration exception。
4. 保持四个公共核心组、schema 2、严格 range validator、Formal 和服务器命令不变；重新执行第 7 节四条
   门禁，停在 `READY_FOR_REVIEW`，不得设置 `ACCEPTED` 或创建 T109。

本次服务器失败使此前本地 `READY_FOR_REVIEW` 返回 `IN_PROGRESS`；修复提交后仍需重跑同一 StCache 门禁。

### 12.1 主 Agent服务器修复审查退回（合同不变）

§12 第一版避免了未捕获异常，但 compact `macro_interface.f` 的结果为 interface `rename=0`：具有唯一
PySlang typed syntax 和唯一宏实参物理来源的 `macro_if/value/macro_mp/if0/if_array` 均被错误升级为
`source_binding_incomplete`。其中 elaboration 复制节点的虚拟 semantic location 不能推翻已经存在的
source-backed declaration；宏实参 token 也应通过 SourceManager original location 绑定，而不是整组保留。

同一子 Agent必须完成以下冻结修正：

1. 使用一个集中、薄型的 declaration resolver：只接受 PySlang 明确 typed declaration token 或 semantic
   location；若 location 为 macro loc，只通过 `SourceManager.getFullyOriginalLoc` 还原物理位置并核验原始
   bytes。禁止文本扫描、名称搜索或 filelist 顺序 fallback。
2. `ModportSymbol` 使用 typed `syntax.name`；interface scalar/array root 使用 typed `syntax.decl.name`；
   Variable/Net/Port/Field/typedef/interface definition 使用各自明确 typed declaration token。semantic location
   只作为同一直接证据的补充，不应优先于可用 typed token。
3. 若 elaboration wrapper 的 typed declaration range 已对应现有 record，则只注册 semantic alias，不新增
   record/issue；source-less anonymous element 继续忽略。只有确有 source/syntax 证据且 typed token、original
   macro loc 和 semantic loc 都不能证明唯一物理 token 时，才触发组级 preserve。
4. `macro_interface.f` 必须产生真实 interface rename，并通过 CLI schema 2、strict compile、byte-identical
   restore；测试必须断言 macro unique-source declaration 被 rename、数组 element 不建 record/issue。独立
   invalid typed-token fixture/单元测试仍需证明未知绑定会整组 preserve。
5. 收敛 §12 第一版重复的逐分支异常样板，保持 RenameIndex 是薄型绑定索引；mapping/rewrite strict validator、
   公共接口、schema、Formal 和服务器门禁不变。

主 Agent未运行最终门禁，因为静态语义结果已违反合同；此前 §12 `READY_FOR_REVIEW` 与门禁记录被本次退回
取代。修正后重新执行原第 7 节四条门禁，仅可设 `READY_FOR_REVIEW`。

### 12.2 主 Agent第二版服务器修复本地验收

```text
reviewed_after_12_1: 2026-08-26T21:05:00+08:00
architecture_review: pass; typed declaration resolver is centralized, macro locations use only PySlang SourceManager original locations plus byte validation, and no name/text/filelist fallback was found
macro_interface_result: interface rename=3 preserve=2; macro_if/value/macro_mp rename; selected-top if0/if_array preserve; no source_binding_incomplete issue
main_gate_1: exit 0; 38 tests passed
main_formal_positive: actual renamed gate; exit 0; JSON formal_equivalence=pass
main_formal_negative: strict PySlang compile 0/0; exit 1; evidence unproven and equiv_status -assert
main_gate_2: exact §7 py_compile exit 0
main_gate_3: exact git diff --check HEAD exit 0
main_gate_4: exact READY_FOR_REVIEW guard exit 0; t108_ready_for_review=pass
local_result: PASS
server_gate: PENDING_RETRY; StCache must pull the follow-up fix and rerun the unchanged §8 command
```
