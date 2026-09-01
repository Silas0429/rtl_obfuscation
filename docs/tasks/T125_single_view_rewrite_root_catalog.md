# T125：rewrite-root filelist 使用单一 explicit-top catalog

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 起始 HEAD：`742a7c62f85a3dc4130699bb69684b48b082d209`（T124 已 `ACCEPTED` 并推送 GitHub）
- 起始工作树：clean
- 任务类型：SourceCatalog resource reduction / readonly duplicate boundary
- 服务器目标：PySlang `11.0.0`

## 1. 已确认问题

T124 已移除 authoritative filelist 的第一轮完整 PySlang compilation。当前最大阻塞仍在
`build_source_catalog()`：它先以 `top=None` 对完整 filelist 建 catalog view，再以用户 top 建 overlay。
服务器对 2563 个 source unit 的真实 filelist 实测：此前 explicit-top compilation 约 20 GiB，而随后
`top=None` catalog 达到约 599.4 GiB，并在 CST duplicate 检查中发现：

```text
ADDF_D1_N_S6P25TL_C54L04
/project/STPU2/maoyiming/work/s5_code/ChipPlatform/common/src/StdLib/rtl/...
/library/SF4/install/pdk/MODEL/flk/...
```

用户已经冻结唯一改写目录：

```text
/project/STPU2/maoyiming/work/s5_code/ChipPlatform/aic_ss/src
```

其它 filelist 文件全部只读。T125 先移除最危险的 all-top elaborate：当 filelist 同时提供 explicit top 和
至少一个 rewrite root 时，每个原始或 gate catalog 只建立一份 explicit-top PySlang view，并对完全位于只读
边界、没有进入 top 闭包的 library duplicate 采用 fail-closed 的有限豁免。

本任务仍把完整 compile order 交给 PySlang 解析和 explicit-top elaborate，尚不是最终的
`analysis_compile_order`。它的目标是把已观测的约 599 GiB all-top 路径降回 explicit-top 量级，为下一任务的
依赖裁剪提供可运行基础。

## 2. 单一目标

filelist + explicit top + non-empty rewrite roots 模式下，`build_source_catalog()` 必须只调用一次 PySlang
compilation，且该调用必须带用户 top；基于同一 view 同时完成 physical module inventory、top closure、
readonly diagnostic 归类和 RenameIndex 所需语义对象，保持实际 gate、restore 与 Formal 正确。

## 3. 单一 view 合同

### 3.1 启用条件

只有同时满足下列条件才启用 T125 路径：

- `source_set.origin == "filelist"`；
- `source_set.top` 是非空 explicit top；
- `source_set.rewrite_roots` 非空。

single-file、project-root、无 top filelist、未提供 rewrite root 的 filelist 继续使用 T124 前既有 catalog +
optional top overlay 行为，不在本任务中改变。

### 3.2 编译次数与对象身份

启用 T125 时：

1. `build_source_catalog()` 对一个 SourceSet 只允许调用一次 `_compile_view()` /
   `compile_pyslang_source_set()`，且 `top` 参数必须精确等于 `source_set.top`；
2. 禁止隐式或显式创建 `top=None` view，禁止通过 parse-only 后再建立第二份 semantic Compilation；
3. `catalog_compilation` / `top_compilation`、`catalog_root` / `top_root`、对应 source manager 可以引用同一
   PySlang 对象；不得复制 semantic tree；
4. catalog 与 top report 仍各自存在并均为零 blocking error，公共 schema/version 不变；
5. original mapping 与 gate strict compile 各允许一份 view。一次公开加密在 T124 SourceSet 结构阶段为零次，
   original catalog 一次，gate catalog 一次；不得恢复额外 compilation；
6. 当前 MappingVNext 对原始 Compilation 的 live identity 保持不变。本任务不做子进程隔离或对象生命周期
   解耦。

### 3.3 physical module inventory

explicit-top semantic root 不会为所有未实例化 module 建立 native definition。T125 必须从同一 view 的 CST
建立全部 physical module declaration inventory，并保持既有：

- `owner_id = module:<file>:<start>:<end>`；
- declaration byte range 验证、排序和唯一性；
- `modules` 包含 compile order 中所有 physical module，而不仅是 top-reachable module；
- `in_top_closure` / `is_selected_top` 只能由 explicit-top semantic definition 的物理 range 决定；
- RenameIndex 对 top-reachable、source-backed symbol 的 owner 绑定保持一对一；未 elaborate module 不得伪造
  semantic binding。

不得用正则扫描 module；必须使用该 PySlang view 的 CST token 与 physical-byte 校验。

## 4. 只读 duplicate 合同

### 4.1 默认继续阻塞

同名 physical module 有多个 declaration 时，以下任一条件成立必须继续
`CATALOG_DUPLICATE_MODULE` / `REFUSED_ATOMIC`：

1. 任一 declaration 位于任一 rewrite root；
2. 该 module 名称是 selected top；
3. explicit-top semantic view 实际绑定到该名称的某一 definition，即该名称进入 top closure；
4. 同一物理文件内重复声明同名 module；
5. provenance 缺失、路径无法一对一对应 filelist source entry，或存在两个及以上 bare `source` provider；
6. entry kind 不是 `source` / `library_source`，或任何范围、字节、路径验证失败。

### 4.2 唯一允许继续的形状

只有同时满足下列条件的 duplicate 才可作为 readonly library inventory 继续：

- 所有 declaration 都在 rewrite roots 外；
- 该名称不在 selected top / top closure；
- 每个 declaration path 都能唯一映射到 T124 `FilelistEntry`；
- provider mode 为“全部 `library_source`”或“恰好一个 bare `source` + 其余 `library_source`”；
- 所有 declaration 的 module name token 和 physical range 已精确校验。

允许继续不等于选择或编译 provider：这些 definition 在本任务中必须是 top-unreachable。记录一个 live-only、
确定排序的 readonly duplicate inventory，至少保存 module name 和全部 declaration ranges，供测试与下一任务
报告/overlay 使用；不得进入公共持久化 schema。

两个及以上 bare provider 继续阻塞。不得按目录名、文件 hash、出现顺序或“内容看起来相同”放行。

## 5. fail-closed 与行为保持

- explicit-top view 的 parse / semantic errors 继续阻塞；T121 精确 vendor compatibility 和 readonly file
  firewall 保持；
- MappingVNext 的 module `owner_id` 继续全局唯一；module name 只有在其全部 physical declaration 与
  `SourceCatalog.readonly_duplicate_inventory` 中一个 canonical entry 精确一致，且这些 owner 均为只读、
  top-unreachable 时才可重复。inventory 缺失、多余、伪造、range 不一致或普通 catalog 中的重名仍以
  `MAPPING_SOURCE_INVALID` fail-closed；
- 通过上述校验的 readonly duplicate 只允许产生 `preserve` record，不得产生 rename record / landed edit；实际
  public gate strict compile 必须继续使用原 SourceSet 的 live provenance，不得把 canonical `design.f` 中丢失的
  `-v` 误判为两个 bare provider；
- `MissingTimeScale` 继续 nonblocking，其它 diagnostics 不放宽；
- `--rewrite-root` 仍只授权改写，不因 `-v` 改变 edit eligibility；
- 所有 landed edit 仍必须在 rewrite roots 内，目录外 record 保持 `outside_rewrite_root` 或更保守原因；
- public output 仍原子发布，失败不得留下 output；
- mapping schema 2、SourceSet schema 1、rewrite/restore schema 与当前 canonical `design.f` 不变；
- actual gate strict compile、byte-identical restore 与 compact actual-gate Formal 必须通过。

## 6. 资源与机器验收

新增 compact fixture/test，至少证明：

1. instrumentation 统计 scoped original catalog 恰好一次 compile，参数为 explicit top，零次 `top=None`；
2. public/in-process actual gate 的 original + gate catalog 合计两次 explicit-top compile，零次 `top=None`；
3. CST inventory 仍包含一个 top-unreachable module，并正确标记 `in_top_closure=False`；
4. external duplicate matrix 覆盖：all-library 通过、one-bare-plus-library 通过、two-bare 拒绝、rewrite-root 内
   duplicate 拒绝、selected-top duplicate 拒绝、top-reachable external duplicate 拒绝、same-file duplicate
   拒绝、缺失 provenance 拒绝；
5. 允许的 duplicate 出现在 live-only readonly inventory，真实 RenameIndex / MappingVNext 可继续，且 mapping
   只有 preserve record、没有 rename record / landed edit；至少一个带允许 duplicate 的 public actual-gate正例必须完成 strict compile 与
   byte-identical restore。Formal 继续使用不含 duplicate 的 compact actual gate，因为服务器不使用 Yosys，且
   当前 Formal filelist/Yosys 流程不承担 `-v` 或 duplicate-library 解析；
6. parse/semantic/vendor diagnostics 仍按原方向阻塞或精确放行；
7. actual gate 与 gold 不同、restore byte-identical、Formal 正例 pass，固定功能负例 Formal 非零。

不得仅通过 mock 返回空 catalog 来证明次数；至少一个正例必须使用真实 PySlang view、真实 RenameIndex / mapping
和 actual gate。

## 7. 明确不包含

- 不建立只含 `aic_ss/src` 的 `analysis_compile_order`；
- 不生成 external module/interface/package stub，不放行 UnknownModule；
- 不减少传给 `SyntaxTree.fromFiles()` 的 source file 数量；
- 不持久化 `FilelistEntry` 或 readonly duplicate inventory；
- 不让输出 `design.f` 恢复 `-v`，不生成 overlay 输出；
- 不流式改写 physical files，不缩短 MappingVNext 对原始 Compilation 的生命周期；
- 不处理 `-y`、`+libext`、simulator-specific library priority；
- 不修复 T124 记录的既有 T088/T097 历史测试边界；
- 不新增 vendor syntax compatibility；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 8. 允许修改的文件

- `docs/tasks/T125_single_view_rewrite_root_catalog.md`
- `rtl_obfuscator/source_catalog.py`
- `rtl_obfuscator/mapping_vnext.py`（仅让 module-name 唯一性校验识别 T125 已认证的 live-only readonly
  duplicate inventory；不得改变 owner-id、semantic-owner、physical range 或普通 duplicate 的 fail-closed）
- `tests/test_t125_single_view_rewrite_root_catalog.py`
- `tests/fixtures/t125_single_view_rewrite_root_catalog/**`
- `tests/test_source_catalog.py`（仅补 single-view / CST inventory 回归）
- `tests/test_mapping_vnext.py`（仅补 readonly duplicate inventory 的精确接受/伪造拒绝矩阵）
- `tests/test_t121_vendor_model_readonly.py`（仅补 scoped compilation 次数/diagnostic 回归）
- `docs/development/project_structure.md`
- `docs/development/future_work.md`（仅记录仍未实现 analysis set / overlay / lifetime 边界）

不得修改 T123/T124、SourceSet、project discovery、rewrite、rename、mapping、orchestration、CLI、README、公共 schema
或其它测试。若 single-view 实现确实需要扩大产品 allowlist，先在任务单记录 BLOCKED，不得自行修改。

## 9. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t125_single_view_rewrite_root_catalog -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_catalog tests.test_t121_vendor_model_readonly \
  tests.test_t124_filelist_inventory_and_provenance \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_modport_ports_are_alias_occurrences_of_interface_members \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_struct_member_reference_uses_direct_field_symbol_location \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_typedef_and_conversion_shapes_are_semantically_scoped \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_unknown_struct_shape_is_a_boundary_and_preserves_only_its_own_record \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_unknown_cross_record_claim_preserves_the_entire_core_group \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_same_record_declaration_range_keeps_only_the_declaration \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_interface_arrays_are_root_aliases_without_anonymous_element_records \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_all_four_groups_have_real_candidates_and_compile_safe_mapping \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_ansi_nonansi_ports_interface_aliases_and_fields_have_real_renames \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes \
  tests.test_mapping_vnext tests.test_rewrite_vnext \
  tests.test_orchestration_vnext tests.test_restore_vnext -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_catalog.py tests/test_t125_single_view_rewrite_root_catalog.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T125_single_view_rewrite_root_catalog.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t125_ready_for_review=pass")'
```

## 10. Formal verification

T125 改变 actual gate 的 strict compile 路径，必须在新 fixture 或既有 T121 fixture 上记录：

```text
formal_verification: PASS required
gold: compact fixture original design.f
gate: actual public/in-process renamed gate design.f
top: unchanged explicit top
positive: scripts/formal_equivalence.py exit 0 and JSON formal_equivalence=pass
negative: fixed functional mutation; strict compile exit 0; Formal nonzero with unproven/equiv_status -assert
```

## 11. 服务器复测门禁（Main Agent 本地验收后）

服务器命令必须使用精确 root：

```sh
python rtl_encrypt.py \
  --filelist "$FILELIST" \
  --top AIClusterWrapper \
  --rewrite-root /project/STPU2/maoyiming/work/s5_code/ChipPlatform/aic_ss/src \
  --category all \
  --output-dir "$OUT"
```

复测至少记录 SourceSet 时间、catalog 时间、Maximum resident set size、退出状态，以及 duplicate 是否属于
T125 允许形状。T125 目标是消除 `top=None` 约 599 GiB 路径；不在没有服务器证据时承诺低于 20 GiB。

## 12. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 742a7c62f85a3dc4130699bb69684b48b082d209
starting_worktree: clean plus this authorized T125 contract
changed_files: `rtl_obfuscator/source_catalog.py`; `rtl_obfuscator/mapping_vnext.py`; `tests/test_t125_single_view_rewrite_root_catalog.py`; `tests/test_mapping_vnext.py`; `tests/fixtures/t125_single_view_rewrite_root_catalog/{design.f,owned/child.sv,owned/top.sv,external/unreachable.sv}`; this task document
commands: baseline `conda run -n rtl_obfuscation python -m unittest tests.test_t125_single_view_rewrite_root_catalog -v` (exit 1: test module did not exist yet; `ModuleNotFoundError`); contract correction: fixed command 2 test module corrected from nonexistent `tests.test_rename_index` to existing `tests.test_t108_pyslang_rename_index`; fixed command 1 `conda run -n rtl_obfuscation python -m unittest tests.test_t125_single_view_rewrite_root_catalog -v` (exit 0, 5 tests, including compact Formal positive/negative and public readonly-duplicate gate); corrected fixed command 2 with `tests.test_t108_pyslang_rename_index` (exit 1 only at pre-existing `T108RenameIndexTests.test_macro_backed_interface_declaration_and_invalid_typed_token_are_fail_closed`, preserve expected 2 vs actual 4; all other listed tests passed); clean HEAD copy command `conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_backed_interface_declaration_and_invalid_typed_token_are_fail_closed -v` reproduced the same expected 2 vs actual 4 failure; fixed command 3 `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_catalog.py tests/test_t125_single_view_rewrite_root_catalog.py` (exit 0); additional allowlisted mapping compile `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/mapping_vnext.py tests/test_mapping_vnext.py` (exit 0); fixed command 4 `git diff --check HEAD` (exit 0); fixed command 5 after setting this record to `READY_FOR_REVIEW`: `t125_ready_for_review=pass`
results: single explicit-top branch calls `_compile_view` once with `top=source_set.top`, reuses compilation/root/source manager for catalog and top, and inventories all compile-order CST module declarations including `t125_unreachable` with `in_top_closure=False`; duplicate matrix passes all-library and one-bare-plus-library into live-only readonly inventory and rejects two-bare, rewrite-root, selected-top, top-reachable, same-file, and missing-provenance cases with `CATALOG_DUPLICATE_MODULE`; MappingVNext now accepts only an exact live readonly inventory, keeps global owner IDs unique, retains the full RenameIndex and category outcomes, and requires duplicate-related symbols to be non-eligible/preserve; allowed duplicate records contain no rename or landed edit; public gate combines a renamed owned signal with two preserved external duplicate providers, passes strict compile, and restores all bytes identically; in-process original+gate compile count passes
schema_or_behavior: public report/schema remains unchanged; readonly duplicate inventory is live-only and excluded from `SourceCatalog.to_report()`; the only additional product change is the allowlisted `mapping_vnext.py` owner validation for exact T125 certified duplicates; existing non-T125 catalog path remains selected when filelist/top/rewrite-root enablement is absent
boundaries: Contract correction recorded: fixed command 2 now uses existing `tests.test_t108_pyslang_rename_index`; its exact failing test `T108RenameIndexTests.test_macro_backed_interface_declaration_and_invalid_typed_token_are_fail_closed` remains unchanged because clean HEAD independently reports preserve expected 2 vs actual 4. No test was weakened and no files outside the expanded T125 allowlist were changed. Public filelist mode intentionally omits unsupported `--source-root`; its output and restore directories are outside the source root. Resource audit: `_physical_module_declarations`, `_walk_reachable_modules`, and `_semantic_owner_ids` use callback visitors without retaining full node lists; every physical/semantic range uses `stat + seek + read(token_length)`, with the 256 KiB padding regression confirming token-sized reads and no full filelist byte cache. Reachable duplicate check remains a second fail-closed call after closure discovery. Mapping duplicate validation rejects missing, extra, forged, range-mismatched, reachable/selected, and ordinary duplicate inventory; no RenameIndex filtering or replacement is performed.
formal_verification: PASS on compact actual gate in T125 test: `scripts/formal_equivalence.py` exit 0 with JSON `formal_equivalence=pass`; fixed functional mutation (first child assignment RHS prefixed with `~`) exits nonzero with `unproven` and `equiv_status -assert`; readonly-duplicate public gate separately passes strict compile and byte-identical restore without expanding Formal's `-v`/duplicate flow
review_request: T125-specific tests, allowlisted mapping duplicate matrix, compile, diff, actual-gate Formal, and exact `READY_FOR_REVIEW` guard pass. This sub-agent does not set `ACCEPTED`.
start_record: T125 sub-agent read AGENTS.md, docs/tasks/README.md, the T125 contract, refactor protocol, project structure, and directly related SourceCatalog/SourceSet/vendor tests; `git status --short --branch` showed clean HEAD plus this authorized untracked T125 contract.
```

## 13. 主 Agent 验收

```text
main_result: PASS
reviewed_head: 742a7c62f85a3dc4130699bb69684b48b082d209 + T125 working tree
scope_review: PASS; product changes only in source_catalog.py and the explicitly expanded mapping_vnext.py
  allowlist; remaining changes are the T125 task, fixture and tests; T123/T124 are unchanged
code_review: PASS; filelist + explicit top + rewrite root creates one explicit-top view and reuses its
  compilation/root/source manager; CST, reachable-module and semantic-owner walks do not retain full-node Python
  lists; physical token checks use bounded stat/seek/read; certified readonly duplicates remain physical owners and
  preserve records but cannot become rename records or landed edits; forged/incomplete/reordered inventories fail closed
target_command: conda run -n rtl_obfuscation python -m unittest
  tests.test_t125_single_view_rewrite_root_catalog -v
target_result: PASS; Ran 5 tests, OK
compatibility_command: revised exact section 9 secondary command, excluding only the independently reproduced
  clean-HEAD T108 historical assertion
compatibility_result: PASS; Ran 45 tests, OK
py_compile: PASS; source_catalog.py, mapping_vnext.py and their T125/mapping tests
git_diff_check: PASS
ready_for_review_guard: PASS before acceptance; t125_ready_for_review=pass
formal_verification: PASS; compact actual renamed gate positive exit 0 with JSON formal_equivalence=pass;
  fixed functional negative exit 1 with unproven/equiv_status -assert
readonly_duplicate_public_gate: PASS; owned top signal renamed with modified_tokens > 0 while one bare plus one -v
  duplicate provider remained preserve and byte-identical; strict gate compile and full restore passed
single_view_evidence: PASS; original and gate catalogs each call _compile_view exactly once with explicit top and
  never with top=None; catalog/top objects are identical within each catalog
baseline_boundary_probe: PASS; clean HEAD 742a7c6 exported independently under /tmp reproduces
  T108RenameIndexTests.test_macro_backed_interface_declaration_and_invalid_typed_token_are_fail_closed with
  preserve expected 2 versus actual 4; the assertion and implementation were not changed by T125
remaining_boundary: the complete filelist is still passed to the one explicit-top PySlang view, so T125 removes the
  observed approximately 599.4 GiB top=None path but does not yet implement analysis_compile_order, provider overlay,
  subprocess lifetime isolation or streaming rewrite; server RSS/time remain to be measured and no sub-20-GiB promise
  is made before that evidence
accepted_by: Main Agent Codex
```
