# T105：struct/union 隐式 conversion 的源码边界

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 子 Agent：GPT-5.6 Luna Extra High（仅允许 `reasoning=xhigh`）
- 冻结基线：`fb2fa2954985e65e1c470c1c9bb4239e3cf06ab0`
- 任务类型：rewrite/mapping
- 设计输入：[`stcache_core_category_stability.md`](../development/architecture/stcache_core_category_stability.md) 第 3、5、6 节

## 1. 单一目标

修正 `struct_types` / `struct_fields` / `union_fields` 共用的 `TypeAliasType`
conversion 收集边界：只有源码中真实存在的显式 cast 类型 identifier 才建立 occurrence；PySlang
插入且没有类型 identifier 的隐式 conversion 只作为语义绑定事实，不建立 range、edit 或伪造
occurrence。由此使合法的 packed struct/union 隐式赋值、拼接、literal 与端口转换能够进入同一条
公开改写流水线，同时保持显式 cast 的 exact binding 和既有 fail-closed 强度。

## 2. 冻结实现计划

本任务只按以下四步执行，不增加中间任务：

1. 用 compact fixture 冻结显式 cast 与无源码隐式 conversion 的 PySlang 形状，并把 T070 的旧失败
   断言替换为“不产生虚假 occurrence”的正例；
2. 在唯一 `SymbolGraph` collector 中实现最小 source-backed 判定，不新增 collector、fallback 或兼容层；
3. 通过公开 filelist 流程验证 struct/union 的 graph、mapping、strict gate、直接恢复和 actual-gate
   Formal 正负例；
4. 记录证据并停在 `READY_FOR_REVIEW`，由主 Agent 独立验收。

验收通过后的下一步仍只能是既定的 interface 语义实例适配；本任务不得实现、创建或预埋该任务。

## 3. 冻结行为合同

### 3.1 唯一 source-occurrence 规则

对 semantic type 为 `TypeAliasType` 的 `ConversionExpression`：

1. `syntax is None` 时是编译器插入的隐式 conversion，直接跳过，不创建 occurrence；
2. syntax 不是 `CastExpressionSyntax` 时，没有 source-backed cast type token，同样不创建 type occurrence；
3. `CastExpressionSyntax` 中的 `signed` / `unsigned` 等 built-in cast 继续不是 typedef/struct occurrence；
4. 显式 `CastExpressionSyntax` 只接受 direct identifier token，且物理 bytes、semantic alias 与 owner 必须
   精确一致，provenance 保持 `semantic_cast_type`；
5. 显式 cast 有源码 type 位置但无法 exact 映射时继续稳定 fail-closed，禁止文本搜索、名称白名单、吞异常
   或把整个 owner 静默 preserve；
6. 跳过隐式 conversion 不能建立空 range、合成 range、额外 record 或 mapping schema 字段。

### 3.2 类别与既有边界

- 同一规则由 `typedefs`、`struct_types`、`struct_fields`、`union_fields` 的现有 aggregate 路径复用，
  不能为 struct/union 复制第二套 collector；
- compact 输入必须至少包含 packed struct 和 packed union 的类型/字段、direct explicit typedef/struct cast，
  以及由 concatenation、literal、assignment 和 port connection 触发的 syntax-less implicit conversion；
- direct named struct assignment-pattern key、macro argument/body provenance、top boundary、selected-category
  isolation、range 去重和原子发布保持原行为；
- `--category struct` 不隐式扩展为 `union_fields`；组合验证必须显式同时选择 `struct` 与
  `union_fields`；
- union/array/default/type/literal/macro/anonymous pattern key 的既有未授权形状不随本任务扩张。

### 3.3 输出与安全不变量

- 成功 compact 运行必须有真实 `struct_types`、`struct_fields`、`union_fields` rename，且
  `preserve=0`、`unsupported=0`；
- strict compile、mapping range/manifest audit、公开 decrypt 和 byte-identical restore 全部通过；
- actual renamed gate Formal 正例 exit 0 且 JSON `formal_equivalence=pass`；从 actual gate 制作的固定功能
  负例必须保持可严格编译并使 Formal 非零，输出包含 `unproven` 与 `equiv_status -assert`；
- 失败不得发布 output/mapping/metrics 半成品；不增加 CLI、schema、compatibility、fallback、第二 graph、
  fixture/module/type 名特判或 RISC 路径。

## 4. 固定输入与机器可验收输出

新增 `tests/fixtures/t105_struct_union_implicit_conversion/`：

- `design.f` 和最小 SystemVerilog source，只使用工程支持的 `.sv/.v/.svh/.vh` 语义；
- top 固定为 `t105_top`，外部 top 名和 ports 不改名；
- selected categories 固定为 `struct` 与 `union_fields`；
- fixture 必须能在修改前稳定复现 `semantic cast has no direct type identifier token`，修改后公开 filelist
  加密成功；
- 测试必须从 graph 精确证明显式 cast token 被记录，而隐式 conversion 所在源码没有 alias occurrence；
- 公开输出必须证明 `encryption_result=PASS_FULL`、真实三类 rename、strict compile、range/manifest audit、
  direct byte-identical restore、actual-gate Formal 正例和固定功能负例。

真实服务器 StCache 不在本地任务输入中。本任务接受后只能表述为“compact 与通用流水线已验收；StCache
struct/union 工程结论等待用户用新输出目录重跑”，不得用 compact 结果冒充外部工程证据。

## 5. 明确不包含

- 不实现 interface、interface instance array、interface port 或 modport 修复；
- 不处理 ports 的 18 个 `macro_origin_conflict`；
- 不改变 filelist、single-file、project-root 输入模式或 category registry；
- 不修改宏对象，不扩大 pattern-key 支持，不处理外部 testbench/SDC/DPI/VPI/UVM/blackbox；
- 不删除历史任务、fixture、脚本或运行 blanket unittest discovery / RISC-V-Vector Formal；
- 不创建 T106，不 commit、不 push、不设置 `ACCEPTED`。

## 6. 允许修改

```text
docs/tasks/T105_struct_union_implicit_conversion.md
docs/development/architecture/README.md
docs/development/architecture/stcache_core_category_stability.md
docs/development/future_work.md
docs/systemverilog_renaming_table.md
rtl_obfuscator/symbol_graph.py
tests/test_t070_keyword_cast.py
tests/test_t105_struct_union_implicit_conversion.py
tests/fixtures/t105_struct_union_implicit_conversion/**
```

其中四个既有文档改动是主 Agent 在本任务开始前建立的设计输入。子 Agent必须保留并安全合并，不得还原、
stash、覆盖或把它们误记为自己从零产生的改动。若实现需要修改列表外文件，记录后停止。

## 7. Baseline 与唯一验收矩阵

子 Agent 在第一次实现编辑前只运行 baseline：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_nonkeyword_typealias_wrapper_remains_stable_fail_closed tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_fixture_typed_identity_and_exact_graph_occurrences tests.test_t104_symbol_level_macro_provenance.T104SymbolLevelMacroProvenanceTests.test_compact_graph_maps_macro_arguments_and_keeps_siblings_eligible -v
```

baseline 预期三个既有测试通过，其中 T070 明确冻结当前旧失败行为；新增 T105 测试在此时尚不存在属于
baseline absence，不是产品验收失败。实现后只运行以下四条门禁：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_syntaxless_implicit_typealias_conversion_has_no_source_occurrence tests.test_t070_keyword_cast.T070BuiltinKeywordCastTests.test_typedef_cast_remains_exactly_bound_to_byte_t tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_fixture_typed_identity_and_exact_graph_occurrences tests.test_t084_struct_pattern_field.T084StructPatternFieldTests.test_union_array_scalar_positional_default_literal_and_type_are_no_go tests.test_t104_symbol_level_macro_provenance.T104SymbolLevelMacroProvenanceTests.test_compact_graph_maps_macro_arguments_and_keeps_siblings_eligible tests.test_t105_struct_union_implicit_conversion -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t070_keyword_cast.py tests/test_t105_struct_union_implicit_conversion.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'import subprocess; from pathlib import Path; exact={"docs/tasks/T105_struct_union_implicit_conversion.md","docs/development/architecture/README.md","docs/development/architecture/stcache_core_category_stability.md","docs/development/future_work.md","docs/systemverilog_renaming_table.md","rtl_obfuscator/symbol_graph.py","tests/test_t070_keyword_cast.py","tests/test_t105_struct_union_implicit_conversion.py"}; prefixes=("tests/fixtures/t105_struct_union_implicit_conversion/",); changed={line[3:] for line in subprocess.run(["git","status","--porcelain"],check=True,text=True,capture_output=True).stdout.splitlines() if line}; bad={path for path in changed if path not in exact and not path.startswith(prefixes)}; status=next(line for line in Path("docs/tasks/T105_struct_union_implicit_conversion.md").read_text().splitlines() if line.startswith("- 状态：")); assert not bad,bad; assert "docs/tasks/T105_struct_union_implicit_conversion.md" in changed,changed; assert status=="- 状态：`READY_FOR_REVIEW`",status; print("t105_ready_for_review=pass")'
```

第一条目标 unittest 必须直接执行本任务唯一一组 compact actual renamed-gate Formal 正例和固定功能负例，
不得把 strict compile、identity restore 或 gold/gold 比较代替 Formal。

## 8. 子 Agent 强制顺序与停止条件

1. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、子 Agent 协议、架构计划第 2–5 节、
   本合同链接的稳定化设计和 `docs/formal_verification.md`；
2. 确认唯一活动任务为本任务且状态 `READY`，检查 Git 状态和既有文档改动；第一次实现编辑前将状态改为
   `IN_PROGRESS`，记录 starting HEAD、实际模型、允许文件和 baseline；
3. 先建立 T105 compact test/fixture，再做最小产品修改；不得先改产品再倒推测试；
4. PySlang API 与合同不符、explicit cast 不能唯一落到物理 token、需要 allowlist 外产品修改或 Formal 只能
   降低强度才能通过时，记录偏差并停止，不得扩大 scope；
5. 四条门禁全部通过后，按规范记录 changed files、命令/退出码、graph/mapping/strict/restore/Formal
   正负结果和未覆盖边界，设置 `READY_FOR_REVIEW` 后停止。

## 9. 执行记录

开始记录（2026-08-24）：starting HEAD 为 `fb2fa2954985e65e1c470c1c9bb4239e3cf06ab0`；实际模型为
`GPT-5.6 Luna Extra High (reasoning=xhigh)`；确认唯一活动合同为本任务，既有主 Agent 文档改动为
`docs/development/architecture/README.md`、`docs/development/future_work.md`、
`docs/systemverilog_renaming_table.md` 和新增 `docs/development/architecture/stcache_core_category_stability.md`，
全部保留；允许文件检查通过；首条 baseline 使用第 7 节固定命令。第一次实现编辑将严格先写
`tests/fixtures/t105_struct_union_implicit_conversion/**` 与 `tests/test_t105_struct_union_implicit_conversion.py`，
再修改产品 collector。

main_review_rework: 2026-08-24 Main Agent returned the same task to IN_PROGRESS without changing the frozen plan or allowlist. The submitted Formal compiled `stress.sv` through a `FORMAL` stub that removed every selected struct/union rename from the proof cone, so it was not acceptable actual-renamed-gate evidence. The compact graph test also proved the assignment and port-connection shapes mainly by source text instead of binding each claimed shape to the corresponding syntax-less `TypeAliasType` conversion. Rework kept the full stress shape in the public filelist, moved the Formal proof to a Yosys-compatible module-local aggregate in the single-file `formal.sv` comparison, bound the literal/concatenation/union/typed-port cases to PySlang semantic nodes and exact source ranges, and shared the unselected-port type-token extraction.
status: READY_FOR_REVIEW
starting_head: fb2fa2954985e65e1c470c1c9bb4239e3cf06ab0
actual_model: GPT-5.6 Luna Extra High (reasoning=xhigh)
allowed_files_check: PASS; all changes are within section 6 allowlist; the four pre-existing Main Agent document changes were retained.
baseline: PASS; the three section 7 baseline tests passed before implementation edits; the old T070 failure behavior was the frozen baseline.
changed_files: `rtl_obfuscator/symbol_graph.py`; `tests/test_t070_keyword_cast.py`; `tests/test_t105_struct_union_implicit_conversion.py`; `tests/fixtures/t105_struct_union_implicit_conversion/design.f`; `tests/fixtures/t105_struct_union_implicit_conversion/formal.sv`; `tests/fixtures/t105_struct_union_implicit_conversion/stress.sv`; this task contract; the four pre-existing Main Agent document changes remained intact.
commands: section 7 baseline; section 7 final unittest row; section 7 `py_compile`; section 7 `git diff --check HEAD`; section 7 exact READY_FOR_REVIEW guard.
results: final unittest row passed 7 tests; compact public result was `PASS_FULL` with strict compile and byte-identical restore; rename covered `struct_types`, `struct_fields`, and `union_fields` with no preserve/unsupported; the graph test bound the syntax-less literal conversion operand to `2'b01`, the struct concatenation assignment to `t105_pair_t`, the union assignment to `t105_payload_t`, and the typed `child_i` port to the semantic `t105_pair_t` PortSymbol and exact connection syntax; py_compile exit 0; diff check exit 0; the exact status guard passed with `t105_ready_for_review=pass`.
schema_or_behavior: syntax-less/non-CastExpressionSyntax TypeAliasType conversions are semantic-only and create no occurrence; exact direct identifiers in CastExpressionSyntax remain `semantic_cast_type` and fail closed when unmappable; aggregate type references in an unselected port category reuse the existing alias collector so a selected aggregate type cannot leave a stale port token.
boundaries: no interface work, no ports macro-conflict work, no CLI/category/schema change, no second collector/fallback/name special case, no RISC Formal; the full PySlang filelist strict gate includes the real stress shapes, while actual Formal directly compares the public gate's `formal.sv` with the original single file and proves the renamed `t105_formal_pair_t`, `hi`, and `lo` records; StCache remains an external rerun boundary.
cleanup_candidates: none identified; the old T070 assertion was replaced because it froze the removed behavior.
formal_verification: PASS; actual records in the public gate were `t105_formal_pair_t -> EpdzsSBgE8mck68oWowk`, `hi -> Dw8FsTy9RBQIYjlcC95Y`, and `lo -> ES5GB1lATAdiLi4mf1c7`; the positive command used single-file gold=`tests/fixtures/t105_struct_union_implicit_conversion/formal.sv` and gate=`/private/tmp/t105-formal-687vye6r/gate/formal.sv`, top=`t105_top`, seq=`5`, and exited 0 with JSON `formal_equivalence=pass`; the fixed functional negative changed the actual gate expression, remained strictly compilable, exited 1, and reported `unproven` plus `equiv_status -assert`.
final_gate_status_guard: PASS; exit 0; output `t105_ready_for_review=pass`.
review_request: Main Agent independently rerun all four section 7 gates and inspect the allowlist/diff; sub-agent stops here without commit, push, or ACCEPTED.

## 10. 主 Agent 验收

2026-08-24 主 Agent 验收：`ACCEPTED`。完整审查 allowlist diff 后独立复跑第 7 节四条门禁：目标
unittest exit 0，`Ran 7 tests`、`OK`；`py_compile` exit 0；`git diff --check HEAD` exit 0；状态守卫
exit 0 并输出 `t105_ready_for_review=pass`。

主 Agent 运行中，公开 filelist 输出为 `PASS_FULL`，strict compile 与 byte-identical restore 均通过，
`preserve=0`、`unsupported=0`；actual gate 的 `formal.sv` 中确认真实改名记录
`t105_formal_pair_t -> mb1A_cJx6vbm7ffS0H6h`、`hi -> q8qGeNfOs77ejLxoS_zv`、
`lo -> wK0tqsJqn1VHDV5OR2Or`。该 actual renamed gate 的 Formal 正例 exit 0，JSON
`formal_equivalence=pass`；固定功能负例保持严格可编译，Formal exit 1，并包含 `unproven` 与
`equiv_status -assert`。

代码审查确认：只有 non-source-backed/non-`CastExpressionSyntax` conversion 被跳过；显式 cast 仍走
direct exact token 与既有 fail-closed；unselected port 只复用已有 alias type-reference 路径，没有新增
collector、fallback、兼容层、schema/CLI 变更、名称特判或 allowlist 外修改。T105 的本地 compact 与通用
流水线验收完成；真实 StCache struct/union filelist 重跑仍是外部证据边界，下一实现步骤保持为 interface。
