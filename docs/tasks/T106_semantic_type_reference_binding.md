# T106：aggregate type reference 的 semantic target 精确绑定

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 子 Agent：GPT-5.6 Luna Extra High（仅允许 `reasoning=xhigh`）
- 冻结基线：`c602f023c3965028ae542cdb935af3f860c4c842`
- 任务类型：rewrite/mapping
- 设计输入：[`stcache_core_category_stability.md`](../development/architecture/stcache_core_category_stability.md)

## 1. 单一目标

删除 aggregate type reference 通过 identifier 文本和作用域猜测 typedef owner 的旧路径，统一改成：

```text
PySlang semantic type target
    -> 唯一 physical alias declaration record
    -> source identifier token 字节校验
    -> occurrence
```

同名 typedef/packed struct/packed union 可以存在于不同 module 或 compilation unit；名称只校验源码 token，
不能再参与 owner 选择。所有现有 aggregate type-reference 调用点必须复用这一条 resolver，包括显式 cast、
aggregate member type、function return type、module/interface port type、variable/net declared type。

真实服务器 StCache 已证明 PySlang catalog 完整编译且无 parse/semantic error，但在
`ReqPath/StChReqTagRw.sv:133` 的 `stsram_dat_t stsram_rdat;` 处出现两个真实物理 alias declaration：
`Memory/StChStatusBuf.sv:61` 与 `ReqPath/StChReqPath.sv:429`。本任务解决的正是这种“名称相同但 semantic
target 唯一”的通用绑定问题，不对 `stsram_dat_t`、StCache、文件名或行号做特判。

## 2. 冻结实现计划

本任务只按以下四步执行，不增加中间任务：

1. 建立 compact 同名 aggregate alias fixture/test，先冻结修改前的 owner mismatch；
2. 在唯一 SymbolGraph collector 中实现 semantic-target resolver，迁移所有既有 aggregate type-reference
   调用点并删除旧名称 resolver，不保留 fallback/兼容层；
3. 通过固定回归与公开 filelist gate/restore/actual-renamed-gate Formal 正负例；
4. 子 Agent 记录证据停在 `READY_FOR_REVIEW`，主 Agent 独立验收、接受并交付。

验收后的下一步只能是用户在服务器上重跑 StCache 的 `struct`、`union_fields` 和二者组合；不得在本任务
中创建或实现 interface 后续任务。

## 3. 冻结行为合同

### 3.1 唯一绑定规则

1. `add_type_reference` 或其等价唯一 helper 必须同时接收 source token、semantic type target 和 provenance；
2. semantic target 必须通过现有 target/declaration range registry 精确落到一个 physical alias record；
3. target 是非 aggregate alias 时，不创建 aggregate occurrence；target 是 aggregate alias、源码有 direct
   identifier token，但无法精确映射时稳定 fail-closed；
4. exact record 确定后，token 的文件、byte range 与原始 bytes 必须由既有 source-range 逻辑校验，token
   文本必须等于该 record 的原名；
5. 同名 alias 在不同 owner 中各自建立不同 symbol identity、declaration 和 occurrence，不允许交叉绑定；
6. 删除 `aliases_by_name` / `resolve_alias_token` 的 owner 选择职责；禁止 choose-first、filelist order、
   module/file/type 名特判、文本搜索、owner 级 preserve、吞异常、兼容 fallback 或第二 collector；
7. real semantic ambiguity、semantic target 缺失或 target 与 physical token 不一致时保持原子失败，不发布
   output/mapping/metrics 半成品。

### 3.2 必须覆盖的现有路径

compact 测试必须让两个或以上 physical aliases 使用相同源码 spelling，并逐项证明以下 reference 仍绑定到
各自 semantic declaration：

- direct explicit cast：`semantic_cast_type`；
- aggregate member 的 named type；
- function return type：`semantic_return_type`；
- selected 与 unselected port category 下的 module/interface port type：`semantic_port_type`；
- variable/net declared type：`semantic_type`。

collector 可以按 PySlang 的实际 API 从 declaration symbol、declared type、canonical type 或 field symbol取得
semantic target，但不得退回按名字选 owner。若某一调用点没有可用 semantic target，子 Agent必须记录
PySlang 形状并停止，不能缩小本节覆盖范围或新增猜测规则。

### 3.3 类别与输出不变量

- `struct_types`、`struct_fields`、`union_fields` 继续共用当前 aggregate collector；不新增 category、CLI、
  mapping schema 或 discovery 路径；
- T105 对 syntax-less implicit conversion 的语义边界、显式 cast exact binding、selected-category isolation、
  signal 级宏来源映射、top boundary 和 range 去重保持不变；
- compact 公开运行必须是 `PASS_FULL`，有真实 `struct_types`、`struct_fields`、`union_fields` rename，且
  `preserve=0`、`unsupported=0`；
- strict compile、mapping range/manifest audit、公开 decrypt 和 byte-identical restore 必须通过；
- actual renamed gate Formal 正例 exit 0 且 JSON `formal_equivalence=pass`；从 actual gate 制作的固定功能
  负例保持可严格编译，并使 Formal 非零且输出含 `unproven` 与 `equiv_status -assert`。

## 4. 固定输入与机器可验收输出

新增 `tests/fixtures/t106_semantic_type_reference_binding/`：

- `design.f` 与最小 SystemVerilog source，top 固定为 `t106_top`；
- 至少两个不同 physical owners 声明同名 packed aggregate alias，并使同名 alias 都位于公开 gate 的实际
  逻辑与 Formal proof cone；
- fixture 同时覆盖 packed struct 与 packed union，并触发第 3.2 节所有 type-reference 路径；
- 新测试先在未修改产品代码上稳定复现 `type reference resolves to multiple semantic aliases`，产品修改后
  精确证明每个 reference 的 `symbol_id`、declaration range、occurrence range 与 source bytes；
- mapping 中至少两条同原名 type record 必须具有不同 `symbol_id`、不同 declaration 和各自一致的 occurrence；
- 公开输出证明 PASS_FULL、strict compile、range/manifest audit、direct byte-identical restore、actual-gate
  Formal 正例和固定功能负例。

真实 StCache 不在本地任务输入中。本任务接受后只能表述为“compact 与通用流水线已验收；StCache
struct/union 工程结论等待服务器新输出目录重跑”，不得以 compact 结果冒充外部工程证据。

## 5. 明确不包含

- 不处理 interface、interface instance array、interface port 或 modport 当前错误；
- 不处理 ports 的 18 个 `macro_origin_conflict`；
- 不修改外部 StCache/filelist，不处理宏对象，不扩大 pattern-key 支持；
- 不改变 single-file/filelist/project-root 输入模式、category registry 或 public mapping/report schema；
- 不添加旧名称 resolver 的 wrapper、deprecated API、兼容层或运行时开关；
- 不删除历史任务/fixture/script，不运行 blanket unittest discovery 或 RISC-V-Vector Formal；
- 子 Agent 不创建 T107，不 commit、不 push、不设置 `ACCEPTED`。

## 6. 允许修改

```text
docs/tasks/T106_semantic_type_reference_binding.md
docs/development/architecture/stcache_core_category_stability.md
docs/development/future_work.md
docs/systemverilog_renaming_table.md
rtl_obfuscator/symbol_graph.py
tests/test_t106_semantic_type_reference_binding.py
tests/fixtures/t106_semantic_type_reference_binding/**
```

若实现需要修改列表外文件，子 Agent必须记录原因并停止，不得自行扩大 allowlist。

## 7. Baseline 与唯一验收矩阵

子 Agent 在第一次实现编辑前只运行 baseline：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_syntaxless_implicit_typealias_conversion_has_no_source_occurrence tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_typedef_cast_remains_exactly_bound_to_byte_t tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_fixture_typed_identity_and_exact_graph_occurrences tests.test_t104_symbol_level_macro_provenance.T104SymbolLevelMacroProvenanceTests.test_compact_graph_maps_macro_arguments_and_keeps_siblings_eligible tests.test_t105_struct_union_implicit_conversion.T105StructUnionImplicitConversionTests.test_source_backed_cast_and_implicit_conversion_boundaries -v
```

baseline 预期 5 个既有测试通过；新增 T106 测试/fixture 此时尚不存在属于 baseline absence。子 Agent先写
T106 fixture/test，再运行其 graph 测试并记录修改产品前的精确 owner-mismatch 失败，然后才允许修改
`symbol_graph.py`。

实现后只运行以下四条门禁：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_syntaxless_implicit_typealias_conversion_has_no_source_occurrence tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_typedef_cast_remains_exactly_bound_to_byte_t tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_fixture_typed_identity_and_exact_graph_occurrences tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_union_array_scalar_positional_default_literal_and_type_are_no_go tests.test_t104_symbol_level_macro_provenance.T104SymbolLevelMacroProvenanceTests.test_compact_graph_maps_macro_arguments_and_keeps_siblings_eligible tests.test_t105_struct_union_implicit_conversion.T105StructUnionImplicitConversionTests.test_source_backed_cast_and_implicit_conversion_boundaries tests.test_t106_semantic_type_reference_binding -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t106_semantic_type_reference_binding.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'import subprocess; from pathlib import Path; exact={"docs/tasks/T106_semantic_type_reference_binding.md","docs/development/architecture/stcache_core_category_stability.md","docs/development/future_work.md","docs/systemverilog_renaming_table.md","rtl_obfuscator/symbol_graph.py","tests/test_t106_semantic_type_reference_binding.py"}; prefixes=("tests/fixtures/t106_semantic_type_reference_binding/",); changed={line[3:] for line in subprocess.run(["git","status","--porcelain"],check=True,text=True,capture_output=True).stdout.splitlines() if line}; bad={path for path in changed if path not in exact and not path.startswith(prefixes)}; status=next(line for line in Path("docs/tasks/T106_semantic_type_reference_binding.md").read_text().splitlines() if line.startswith("- 状态：")); assert not bad,bad; assert "docs/tasks/T106_semantic_type_reference_binding.md" in changed,changed; assert status=="- 状态：`READY_FOR_REVIEW`",status; print("t106_ready_for_review=pass")'
```

第一条目标 unittest 必须直接执行本任务唯一一组 compact actual-renamed-gate Formal 正例和固定功能负例；
不得以 strict compile、identity restore、gold/gold 或 copy-gold 比较替代 Formal。

## 8. 子 Agent 强制顺序与停止条件

1. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、子 Agent 协议、架构计划第 2–5 节、稳定化
   设计和 `docs/formal_verification.md`；
2. 确认唯一活动合同为本任务且状态 `READY`，检查 starting HEAD 与 allowlist；第一次实现编辑前把状态改为
   `IN_PROGRESS` 并记录实际模型、baseline 命令与输出；
3. 先写 compact fixture/test、确认旧产品失败，再做最小产品修改；
4. PySlang API 无法为第 3.2 节任一路径提供 exact semantic target、需要 allowlist 外产品修改或 Formal 只能
   降低强度才能通过时，记录偏差并停止，不得扩大 scope；
5. 四条门禁全部通过后，记录 changed files、命令/退出码、symbol identity/range、mapping/strict/restore/
   Formal 正负结果和未覆盖边界，把状态设为 `READY_FOR_REVIEW` 后停止。

## 9. 执行记录

status: READY_FOR_REVIEW
starting_head: c602f023c3965028ae542cdb935af3f860c4c842
starting_state: `git status --short --branch` = `## main...origin/main` plus only the pre-existing untracked T106 contract; no other active task contract or overlapping user change.
actual_model: GPT-5.6 Luna Extra High (reasoning=xhigh)
start_time: 2026-08-26 14:25:40 +0800
changed_files:
  - `rtl_obfuscator/symbol_graph.py`
  - `tests/test_t106_semantic_type_reference_binding.py`
  - `tests/fixtures/t106_semantic_type_reference_binding/design.f`
  - `tests/fixtures/t106_semantic_type_reference_binding/rtl/left.sv`
  - `tests/fixtures/t106_semantic_type_reference_binding/rtl/right.sv`
  - `tests/fixtures/t106_semantic_type_reference_binding/rtl/top.sv`
  - `tests/fixtures/t106_semantic_type_reference_binding/formal.sv`
  - `docs/development/architecture/stcache_core_category_stability.md`
  - `docs/development/future_work.md`
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_syntaxless_implicit_typealias_conversion_has_no_source_occurrence tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_typedef_cast_remains_exactly_bound_to_byte_t tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_fixture_typed_identity_and_exact_graph_occurrences tests.test_t104_symbol_level_macro_provenance.T104SymbolLevelMacroProvenanceTests.test_compact_graph_maps_macro_arguments_and_keeps_siblings_eligible tests.test_t105_struct_union_implicit_conversion.T105StructUnionImplicitConversionTests.test_source_backed_cast_and_implicit_conversion_boundaries -v`
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t106_semantic_type_reference_binding.T106SemanticTypeReferenceBindingTests.test_same_spelling_aggregate_references_bind_to_physical_aliases -v`
results:
  - baseline exit 0; 5 tests passed.
  - test-first pre-product graph exit 1; exact old failure was `SYMBOL_GRAPH_OWNER_MISMATCH: type reference resolves to multiple semantic aliases`, from `add_type_reference -> resolve_alias_token`.
  - after implementation targeted T106 exit 0; 4 tests passed. The ports-only test has aggregate resolver disabled and all emitted symbols are ports; the selected-port test verifies the aggregate port type occurrence.
  - final gate 1 exit 0; 10 tests passed. Output: `PASS_FULL`, `rename=28`, `preserve=0`, `unsupported=0`, `strict_compile_passed=true`, `restored_byte_identical=true`, `mapping_records=28`, `modified_tokens=74`.
  - final gate 2 exit 0; `py_compile` passed for product and T106 test.
  - final gate 3 exit 0; `git diff --check HEAD` passed.
  - final gate 4 exit 0; `t106_ready_for_review=pass`.
schema_or_behavior: compact fixture/test contains same-spelled struct/union aliases in two package owners, package-typed ports, variable declarations, member type, function return, explicit casts, and an actual-formal top. The pre-product test intentionally reproduces the old owner mismatch. The implementation now uses the semantic target's exact physical declaration range, validates the direct source token bytes, and refuses to choose an owner by name. Aggregate member fields are matched by FieldSymbol declaration range and semantic identity. The aggregate helper is a no-op when `collect_aggregates` is false and skips non-`TypeAliasType` targets before alias-registry lookup.
same_name_alias_evidence:
  - `formal.sv:151:159`, `symbol:struct_types:formal.sv:151:159`, occurrences `261:269 semantic_type`, `327:335 semantic_return_type`, `396:404 semantic_cast_type`.
  - `formal.sv:764:772`, `symbol:struct_types:formal.sv:764:772`, occurrences `874:882 semantic_type`, `940:948 semantic_return_type`, `1009:1017 semantic_cast_type`.
  - `rtl/left.sv:167:175`, `symbol:struct_types:rtl/left.sv:167:175`, occurrences `328:336 semantic_port_type`, `412:420 semantic_type`, `478:486 semantic_return_type`, `545:553 semantic_cast_type`, and `rtl/top.sv:103:111 semantic_type`.
  - `rtl/right.sv:168:176`, `symbol:struct_types:rtl/right.sv:168:176`, occurrences `331:339 semantic_port_type`, `416:424 semantic_type`, `482:490 semantic_return_type`, `549:557 semantic_cast_type`, and `rtl/top.sv:144:152 semantic_type`.
  - Deterministic mapping records preserve those four distinct symbol IDs/declarations and assign distinct names: `s4be11e91390b859`, `se5c18309fda4947`, `safda0b0ed129714`, `s9fa7284d4f8d231`.
  - Every listed declaration/occurrence range was checked against the expected `shared_t` source bytes; member type `member_t` and union field `raw` were checked similarly.
commands:
  - final gate 1: `conda run -n rtl_obfuscation python -m unittest tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_syntaxless_implicit_typealias_conversion_has_no_source_occurrence tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_typedef_cast_remains_exactly_bound_to_byte_t tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_fixture_typed_identity_and_exact_graph_occurrences tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_union_array_scalar_positional_default_literal_and_type_are_no_go tests.test_t104_symbol_level_macro_provenance.T104SymbolLevelMacroProvenanceTests.test_compact_graph_maps_macro_arguments_and_keeps_siblings_eligible tests.test_t105_struct_union_implicit_conversion.T105StructUnionImplicitConversionTests.test_source_backed_cast_and_implicit_conversion_boundaries tests.test_t106_semantic_type_reference_binding -v`
  - final gate 2: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t106_semantic_type_reference_binding.py`
  - final gate 3: `git diff --check HEAD`
  - final gate 4: the exact status/allowlist guard in section 7.
  - T106 public gate command: `python rtl_encrypt.py --filelist tests/fixtures/t106_semantic_type_reference_binding/design.f --top t106_top --category struct --category union_fields --output-dir <fresh gate>`; summary and range audit were asserted from `mapping.json`.
  - T106 positive Formal command: `python scripts/formal_equivalence.py --gold tests/fixtures/t106_semantic_type_reference_binding/formal.sv --gate <gate>/formal.sv --top t106_top --seq 5`; JSON was `{"formal_equivalence":"pass"}`.
  - T106 negative Formal used the actual gate with one functional inversion in `assign data_o`; exit code was 1 and output contained `unproven` and `equiv_status -assert`.
formal_verification: PASS. Actual renamed gate positive passed with JSON `formal_equivalence=pass`; the fixed functional negative failed as required. The public gate also passed PySlang strict compile and direct byte-identical decrypt/restore.
metrics: `PASS_FULL`; `rename=28`, `preserve=0`, `unsupported=0`; `mapping.range_audit={declarations:28, occurrences:46, total_ranges:74}`; `strict_compile_passed=true`; `restored_byte_identical=true`; `symbol_coverage=1.0`; `occurrence_coverage=1.0`.
boundaries: no allowlist expansion; no interface implementation, port macro-conflict change, StCache/filelist change, macro-object encryption, category/schema/input-mode change, commit, push, ACCEPTED, or next task.
cleanup_candidates: none.
review_request: READY_FOR_REVIEW; Main Agent must independently rerun the contract gates and decide acceptance.

## 10. 主 Agent 验收

2026-08-26 主 Agent 验收：`ACCEPTED`。完整检查 allowlist、产品 diff、compact fixture 与文档后，独立
复跑第 7 节四条门禁：目标 unittest exit 0，`Ran 10 tests`、`OK`；`py_compile` exit 0；
`git diff --check HEAD` exit 0；状态/allowlist guard exit 0 并输出 `t106_ready_for_review=pass`。

主 Agent运行中的公开 filelist 输出为 `PASS_FULL`，`rename=28`、`preserve=0`、`unsupported=0`，strict
compile 与 byte-identical restore 均通过；range audit 为 `declarations=28`、`occurrences=46`、
`total_ranges=74`。actual renamed gate 的 Formal 正例 exit 0、JSON `formal_equivalence=pass`；固定功能
负例由 actual gate 的 top expression 加反产生，Formal exit 1，并包含 `unproven` 与
`equiv_status -assert`。

代码审查确认：旧 `aliases_by_name` / `resolve_alias_token` 已删除；type reference 只由 semantic
`TypeAliasType` 的 exact declaration range 命中 alias registry，再校验 direct token bytes；aggregate
member 通过 `FieldSymbol` declaration range 一一对应；cast、member type、function return、selected/
unselected port type 与 variable/net type 共用该规则。ports-only 明确不进入 aggregate resolver。没有
名称/filelist-order 特判、fallback、兼容层、第二 collector、schema/CLI 变化或 allowlist 外修改。

T106 本地 compact 与通用流水线验收完成。真实 StCache `struct`、`union_fields` 及组合结果仍是外部证据
边界，下一步只能由用户在服务器上使用新输出目录重跑，不能用本地 compact 结果替代。

## 11. Post-acceptance 外部观察（不改变 T106 验收结论）

2026-08-26 用户在服务器提交 `950be8e` 上使用新输出目录重跑 StCache `--category struct`。SourceSet
成功建立 147 个 source、154 项 compile order，PySlang catalog 成功建立 329758 个 semantic node；随后
SymbolGraph/mapping 报告：

```text
REFUSED_ATOMIC: semantic aggregate type target does not map to one physical alias record
reference: StChReqTagRw.sv:119:5  req_icmd_if_t req_icmd;
semantic target: StChReqTagRw.sv:46:16  SyntaxKind.TypeAssignment
physical typedef candidate: StChReqPath.sv:264:2  typedef struct ... req_icmd_if_t
```

该证据说明 T106 compact 的 physical `TypeAliasType` 精确绑定仍成立，但合同未覆盖解析结果为 aggregate
shape 的 module type parameter。`TypeAliasType.isStruct=True` 不能证明目标声明本身是 physical
`typedef struct`。T106 保持 `ACCEPTED`；StCache struct 工程支持仍未通过，未来任务必须按 source
declaration kind 分离 typedef 与 `TypeAssignment`，不能使用同名/canonical-type fallback。
