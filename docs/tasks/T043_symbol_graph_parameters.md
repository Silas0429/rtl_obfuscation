# T043：SymbolGraph module parameter/localparam 与 ABI 分类

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R2-D
- 前置任务：T042 `ACCEPTED`，交付提交 `8edfa06`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 2、3、5、6、7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- 验收类型：SymbolGraph/range
- Formal verification：`N/A`，本任务只扩展 SymbolGraph，不产生 rewritten RTL

## 1. 当前项目位置

```text
T039 SourceSet
  -> T040 SourceCatalog / ModuleOwner / optional-top closure
  -> T041 signals
  -> T042 genvars + generate_syntax
  -> T043 module value parameter/localparam + ABI classification
  -> R3 RewritePolicy / mapping vNext / rewrite
```

T043 是 R2-D 的唯一实现任务。它补齐 R3 选择策略所需的 parameter source identity、全部受支持
occurrence 和 `internal/module_abi/top_boundary` 分类，但不选择 category、不生成新名称、不改写 RTL。

T038 的 RISC `6835/6882` 数量冲突继续只是历史证据。本任务只使用第 3 节 compact fixture，不运行
legacy parameter collector、RISC fixture、formal-align 或历史 acceptance driver。

## 2. 单一目标

扩展 `rtl_obfuscator/symbol_graph.py`，把 SourceCatalog 中 module-owned value parameter 和 source
localparam 归一化为唯一 `parameters` SourceSymbol，并完整记录：

1. 普通 semantic expression；
2. packed/unpacked declaration dimension；
3. if/loop generate control expression；
4. named parameter override 左侧；
5. optional top 下的 `internal/module_abi/top_boundary`、eligible/preserved 和稳定 reason。

必须继续满足：

- 只读取现有 SourceCatalog；不重新编译、不调用 legacy inventory/rewrite；
- source/range 收集只使用 catalog semantic view，ABI 分类只读取 T040 ModuleOwner flags；
- genvar elaborated iteration ParameterSymbol 永远不成为 parameter SourceSymbol；
- 同名 module parameter、nested localparam、genvar 和 named override 左右侧按 semantic identity 分离；
- 任一受支持对象的 owner、绑定或 range 无法证明时整图 fail-closed，不输出半张 graph。

## 3. 冻结输入（主 Agent 已建立并预检）

### 3.1 正例

```text
tests/fixtures/refactor_symbol_graph_parameters/
  design.f
  closure.f
  positional.f
  single.f
  single.sv
  rtl/child.sv
  rtl/shadow.sv
  rtl/top.sv
  rtl/unreachable.sv
  rtl/positional.sv
```

覆盖：

- value parameter、parameter-port-list localparam、module-body localparam；
- packed/unpacked dimension、if-generate condition、loop-generate condition；
- `.WIDTH(WIDTH)` 这种左右同名但 owner 不同的 named override；
- module value parameter 与 active generate 内同名 nested localparam；
- source genvar `lane` 对应的 elaborated iteration ParameterSymbol；
- selected top、closure child、closure 外 module、无 top、single-file；
- positional override：它没有 parameter-name token，重命名 parameter 后仍按位置绑定，因此不产生
  occurrence，也不应失败。

### 3.2 负例

```text
tests/fixtures/refactor_symbol_graph_parameters_invalid/
  type_parameter.f
  macro_declaration.f
  macro_reference.f
  defparam.f
  rtl/type_parameter.sv
  rtl/macro_declaration.sv
  rtl/macro_reference.sv
  rtl/defparam.sv
```

- module type parameter：不在 value-parameter scope；
- macro-generated localparam declaration；
- direct declaration + macro-generated dimension reference；
- `defparam`：会按名称跨层次修改 parameter，但本任务不支持其绑定和改写。

### 3.3 冻结 hash

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `refactor_symbol_graph_parameters/closure.f` | 38 | `d219132843e4e46a3757571ad9b9beed19894c5b8e2f86388a6793cfeb3cd83f` |
| `refactor_symbol_graph_parameters/design.f` | 57 | `9473e0fb8143ef05686acac49c48d5fd896b9bd31ce89be4c406b4ce9b455ab4` |
| `refactor_symbol_graph_parameters/positional.f` | 18 | `137a3e6c929ed94de6d92b5eed6b654956c59508410ee99b56421d2a9482e7aa` |
| `refactor_symbol_graph_parameters/rtl/child.sv` | 655 | `5912234069b2b4cba33e365361c5974929886390ae9fda123d558102c6ce4777` |
| `refactor_symbol_graph_parameters/rtl/positional.sv` | 139 | `62ef23c4a0c52b066eb19387ea550099045f5858669c532319a86986f9e0e8a7` |
| `refactor_symbol_graph_parameters/rtl/shadow.sv` | 209 | `51d9644e72641311d705ffef098d7836de8a1eaa4dd01a2421bfccc346f82aa8` |
| `refactor_symbol_graph_parameters/rtl/top.sv` | 469 | `a59967267facc37cc1fa468daa2d4f2372080ad2f38cf9143e9bd93da225c65a` |
| `refactor_symbol_graph_parameters/rtl/unreachable.sv` | 175 | `2a120aa7a316a474980c31909d19f8c35d359b9761dc40fd771ea7ecbfb663aa` |
| `refactor_symbol_graph_parameters/single.f` | 10 | `c212b204450e94afc4afc2c3a4f42c47a2586c7d651203a8b562a45591602461` |
| `refactor_symbol_graph_parameters/single.sv` | 149 | `6bd1e12539fc462c990c7892055e1660316a87127f18a9ca6b86d51e890c0998` |
| `refactor_symbol_graph_parameters_invalid/defparam.f` | 16 | `cb7063f470ba048d0bc1d48d3127bdb3a0142fdf4aad0ae650fb2d8ca27896e3` |
| `refactor_symbol_graph_parameters_invalid/macro_declaration.f` | 25 | `8a487027e235f5e64676db6d94acf31fac3ba41d31c0809309916f6b542b897a` |
| `refactor_symbol_graph_parameters_invalid/macro_reference.f` | 23 | `b3738dfc81f16b979969cb837cfb97eb75c20ab7cdc555099838ac2c8eb34daa` |
| `refactor_symbol_graph_parameters_invalid/rtl/defparam.sv` | 160 | `103ab5668ce623405c57c4d607b1a12709c4b924c612b92b8f17d33f6852f534` |
| `refactor_symbol_graph_parameters_invalid/rtl/macro_declaration.sv` | 179 | `eb6fe663e8fe0d77459421f38a58a8b59d1ada6e0f84f77b6aea246111fcaf43` |
| `refactor_symbol_graph_parameters_invalid/rtl/macro_reference.sv` | 158 | `dc08df0b277c689311adacd1fcbade51d5a3d328503e8d680dda5cf81fc2dedb` |
| `refactor_symbol_graph_parameters_invalid/rtl/type_parameter.sv` | 92 | `2f4d9a0bd8283be0a5a9f275161e384a05ef5dcd2f72bcdb1e69b7f8037b0eb2` |
| `refactor_symbol_graph_parameters_invalid/type_parameter.f` | 22 | `4282295b7a9c54c0ac067cc573151952f88a19be3e5f9d7412f0920d7c81de34` |

这 18 个文件是主 Agent 冻结输入。子 Agent 不得修改；hash 不一致必须停止，不能更新 oracle。

### 3.4 主 Agent PySlang 预检

- full/no-top、full/top、closure/top、project-root/top、single-file、single-filelist、positional/top 和
  四个负例均成功建立 SourceCatalog，parse/semantic errors 均为 `0/0`；
- project-root `parameter_top` compile order 为 `child.sv, shadow.sv, top.sv`，与 closure filelist 一致；
- full catalog 有 13 个非-type ParameterSymbol physical identities，其中 12 个是 source parameter，
  `lane` 是 `LoopGenerateSyntax` elaborated iteration parameter，必须排除；
- module type parameter 的 kind 是 `TypeParameter`，不是普通 `Parameter`；
- macro declaration location 与 macro dimension reference location 的 `isMacroLoc` 均为 true；
- if-generate 的 `GenerateBlockSymbol.conditionExpression` 绑定 child `WIDTH`；loop-generate 的
  `GenerateBlockArraySymbol.stopExpression` 分别绑定 genvar iteration `lane` 与 child `DEPTH`；
- 三个 named override 左侧 token 可由 instance definition 唯一映射到 child/shadow value parameter；
- defparam 输入暴露 `DefParamSymbol` 与 `DefParamAssignmentSyntax`；
- 现有 T041/T042 builder 在 full/closure/single 上的基线 audit 分别为 `8/8/6/14`、`7/7/6/13`、
  `1/1/0/1`，且没有 UninstantiatedDefSymbol。

预检只冻结 API 事实，不授权复制 legacy helper，也不作为子 Agent 验收结果。

## 4. API、schema 与 category 顺序

不新增公开类型或入口，继续使用：

```python
build_symbol_graph(source_catalog: SourceCatalog) -> SymbolGraph
```

`SourceSymbol` schema 和 `schema_version=1` 不变。parameter symbol 固定：

```text
category: parameters
symbol_id: symbol:parameters:<file>:<start>:<end>
semantic_owner: 与 owner_module 相同的 T040 ModuleOwner.owner_id
```

`categories` 按当前 canonical category 顺序输出实际出现项：

```text
signals, parameters, genvars
```

因此 full fixture 是 `['signals','parameters','genvars']`，single 是
`['signals','parameters']`，positional 是 `['parameters']`。不得按 fixture 或固定数量分支。

## 5. source identity 与 candidate 边界

### 5.1 支持 candidate

- semantic kind 为非-type `Parameter`；
- `declaringDefinition` 是 SourceCatalog 中 module definition；
- 名称非空、非 `$` 前缀；
- declaration 是 SourceSet 内直接物理 identifier token，非 macro；
- declaration 能通过 module declaration `(file,start,end)` 唯一映射 T040 ModuleOwner；
- value parameter、parameter-port-list localparam、module/body/generate-scope source localparam 均支持。

同一 physical declaration 因 elaboration/repeated instance 出现多份 semantic copy 时按
`(file,start,end)` 归一化；name/owner 不一致返回 `SYMBOL_GRAPH_RANGE_CONFLICT`。

### 5.2 必须排除或拒绝

- source GenvarSymbol 仍属于 `genvars`；
- `LoopGenerateSyntax` identifier 对应的 `isLocalParam/isBodyParam` elaborated ParameterSymbol 只作为
  genvar evidence，不能产生 parameter symbol或抢占 genvar occurrence；
- module-owned `TypeParameter` 使整图返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
- package/class/interface/$unit parameter 不进入 module parameter graph；
- macro declaration返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
- DefParamSymbol 返回 `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`。

本任务不支持 parameter array/string/real/struct、复杂层次引用或 lexical fallback。固定 fixture
之外若无法证明 source identity/owner，按第 10 节停止，不得静默漏收 candidate。

## 6. occurrences 与 provenance

declaration 不进入 occurrences。只允许以下四种 provenance：

| provenance | 范围与绑定证据 |
| --- | --- |
| `semantic_expression` | initializer、普通表达式和 named override 右侧，必须由 NamedValueExpression.symbol identity 绑定 |
| `declaration_dimension` | packed/unpacked declaration dimension，必须由 resolved dimension expression identity 或限定 declaration syntax + lexical scope identity 绑定 |
| `generate_syntax` | GenerateBlock/GenerateBlockArray control expression，必须由 semantic condition/initial/stop/iter expression identity 绑定 |
| `named_override` | NamedParamAssignmentSyntax 左侧，由 InstanceSymbol.definition + parameter name 映射到唯一 value parameter |

规则：

- `.WIDTH(WIDTH)` 左侧属于 child parameter，provenance=`named_override`；右侧属于 caller parameter，
  provenance=`semantic_expression`；
- positional override没有 parameter-name token，不产生 occurrence，也不失败；
- same-name nested localparam、module parameter和genvar必须按 semantic identity分离；
- dimension 中的 iteration `lane` 继续归 genvar，不得按同名/ParameterSymbol kind归入 parameters；
- 每个 token先拒绝 macro，再校验 file/range/source bytes；
- 重复 elaboration按 `(file,start,end,provenance)` 去重；同一 physical range出现多个 provenance时按
  语法上下文唯一归类，不允许保留重复项；
- symbols、occurrences和全局range沿用T041排序、唯一与非重叠审计。

禁止遍历全文件后按拼写匹配；syntax recovery只能在已绑定 semantic owner的 declaration、generate
或 instance context内进行。

## 7. ABI、impact、support 与 reason 冻结

### 7.1 localparam

所有 source localparam（包括 parameter-port-list、body和active generate scope）固定：

```text
impact: local
abi: internal
support: eligible
reason: null
```

### 7.2 module value parameter

```text
无 top：
  impact=cross_module, abi=module_abi, support=preserved,
  reason=module_abi_requires_top

有 top且 owner.is_selected_top：
  impact=cross_module, abi=top_boundary, support=preserved,
  reason=selected_top_boundary

有 top、位于 closure且不是 selected top：
  impact=cross_module, abi=module_abi, support=eligible, reason=null

有 top但位于 closure 外：
  impact=cross_module, abi=module_abi, support=preserved,
  reason=outside_top_closure
```

SymbolGraph 的 `eligible` 只表示对象和 ranges 可安全交给后续 policy；R3 仍必须显式选择 ABI
category 才能改写 `module_abi`。T043 不实现 RewritePolicy。

## 8. 冻结正例 oracle

| input | parameter symbols/refs/ranges | provenance refs (`semantic/dimension/generate/override`) | classification | whole graph audit |
| --- | --- | --- | --- | --- |
| `design.f` 无 top | `12/27/39` | `10/12/2/3` | internal eligible 5；module_abi preserved 7 | `20/20/33/53` |
| `design.f + parameter_top` | `12/27/39` | `10/12/2/3` | internal eligible 5；module_abi eligible 3；top_boundary preserved 3；outside preserved 1 | `20/20/33/53` |
| `closure.f + parameter_top` | `10/25/35` | `9/11/2/3` | internal eligible 4；module_abi eligible 3；top_boundary preserved 3 | `17/17/31/48` |
| project-root + `parameter_top` | `10/25/35` | `9/11/2/3` | normalized 后与 closure filelist 相同 | `17/17/31/48` |
| `single.sv`/`single.f` 无 top | `2/2/4` | `1/1/0/0` | internal eligible 1；module_abi preserved 1 | `3/3/2/5` |
| `positional.f + positional_top` | `1/0/1` | `0/0/0/0` | child module_abi eligible 1 | `1/1/0/1` |

表中 whole graph 格式为 `symbols/declarations/occurrences/total_ranges`。exact count只验证 compact
fixture，不得进入产品分支。

T042 fixture 在新增 parameter category 后，whole graph oracle 合法更新为：full `9/9/18/27`、
closure/project `7/7/15/22`、single `2/2/3/5`；full categories 为
`signals,parameters,genvars`。T042 的 genvar symbols/occurrences 不变；原“有/无 top 全 symbols
payload 相同”测试改为只比较 genvar payload，因为 parameter classification按 top有意变化。

## 9. 稳定失败矩阵

| input/action | expected code |
| --- | --- |
| macro localparam declaration | `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` |
| physical parameter + macro dimension reference | `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` |
| module type parameter | `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` |
| DefParamSymbol | `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE` |
| catalog 后改变 parameter declaration bytes | `SYMBOL_GRAPH_RANGE_INVALID` |
| 合法 parameter catalog 的 modules registry 替换为空 | `SYMBOL_GRAPH_OWNER_MISMATCH` |

沿用 `SymbolGraphError`；异常文本以 `'<code>: '` 开头并保存可用的首个稳定 file/start。失败不返回
部分 graph，不降级到 preserved，不调用 legacy fallback。

## 10. 目标测试（恰好 18 项新增行为）

新增 `tests/test_symbol_graph_parameters.py`，只通过公开 adapter、`build_source_catalog()` 和
`build_symbol_graph()` 覆盖：

1. full无top的12/27/39、分类和whole audit；
2. full有top的四类ABI结果；
3. 有/无top只改变value parameter classification，不改变symbol identity/ranges/provenance；
4. project-root与closure filelist normalized report除origin外相同；
5. single-file与single filelist normalized report除origin外相同；
6. 四种provenance计数、全部bytes、排序、去重、非重叠和三个主要audit正确；
7. named override左右同名token分别归child/caller owner；
8. module WIDTH与nested localparam WIDTH形成不同symbol且dimension不串owner；
9. T042 fixture的module parameter、source genvar和iteration parameter正确分离，并验证更新后的oracle；
10. positional override成功且不产生parameter-name occurrence；
11. categories canonical、schema不变、连续canonical JSON byte-identical；
12. monkeypatch T040 compile入口与所有legacy parameter/dimension/generate/override helper为立即失败，
    graph仍成功；
13. macro declaration失败；
14. macro reference失败；
15. type parameter失败；
16. defparam失败；
17. catalog后parameter declaration bytes变化返回range invalid；
18. parameter-only合法catalog缺失owner registry返回owner mismatch。

同时精确修订 `tests/test_symbol_graph_genvars.py` 中第 8 节列出的 whole-graph/category/top 比较 oracle；
不得削弱genvar-specific断言、删除测试或修改T041 tests。

目标测试不得调用产品私有 SymbolGraph helper制造结果，不得拼接其他 compilation的semantic node。
T041 15项 + T042 13项 + T043 18项在同一命令中共46 tests。

## 11. 允许修改的文件

- `rtl_obfuscator/symbol_graph.py`；
- `tests/test_symbol_graph_parameters.py`；
- `tests/test_symbol_graph_genvars.py`，仅第 8、10 节明确授权的 superseded whole-graph oracle；
- `docs/tasks/T043_symbol_graph_parameters.md`，仅状态和执行记录。

第3节fixture、T041 tests/task、T042 task、SourceSet、SourceCatalog、legacy inventory/rewrite、README、
renaming table、重构计划和其他文件均只读。需要修改允许列表外文件时记录原因并停止。

## 12. 明确不包含

- 不实现 type/package/class/interface/$unit parameter、parameter array/string/real/struct；
- 不实现 defparam、复杂层次parameter、macro fallback或任意全文件拼写搜索；
- 不增加 ports/modules/interfaces或其他category；
- 不改变SourceSet、SourceCatalog、ModuleOwner或SourceSymbol schema/version；
- 不实现 category selection、RewritePolicy、mapping vNext、命名、rewrite、gate、decrypt、metrics；
- 不复制或调用 legacy parameter collectors/range helpers；
- 不清理旧测试/脚本，不运行RISC、Formal或历史acceptance driver。

## 13. 子 Agent 强制行为

1. 完整阅读 `AGENTS.md`、本任务、`docs/refactor_subagent_protocol.md` 和重构计划第2/3/5/6/7节；
2. 确认 `8edfa06` 是HEAD祖先，合同与18个fixture已由主Agent提交，工作区干净，T043是唯一READY任务；
3. 校验全部hash和第3.4节0/0/API事实；任何不符立即记录并停止，不更新fixture/oracle；
4. 将状态改为`IN_PROGRESS`，记录starting HEAD、工作区、允许文件和baseline；
5. baseline只运行第14节unittest，预期T041/T042的28 tests通过，随后仅因
   `tests.test_symbol_graph_parameters`不存在而import失败；
6. 先创建第10节18项黑盒测试，再按candidate过滤、semantic expression、dimension、generate、
   named override、ABI classification、global audit顺序实现；
7. 允许运行不写仓库的PySlang只读探针；普通测试失败是合同内实现工作，不是暂停理由；
8. 只有PySlang事实与第3.4节冲突、fixture hash变化、需要允许文件外修改、owner/range无法唯一证明时
   才停止；不得因实现尚未完成分批请求主Agent补充规范；
9. 完成后只运行第14节四条命令，一次性填写真实测试数/退出码/边界并设`READY_FOR_REVIEW`；
10. 不得设置`ACCEPTED`、git add/commit/push、创建T044或写主Agent验收记录。

## 14. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_genvars.py tests/test_symbol_graph_parameters.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T043_symbol_graph_parameters.md
```

不运行blanket discovery、legacy parameter tests、HDL compile、gate、decrypt、Yosys、RISC或历史
acceptance脚本。Formal为`N/A: no rewritten RTL is produced`。主Agent只审查本合同18项行为并独立
复跑以上命令，不增加隐藏probe或临时oracle。

## 15. 子 Agent执行记录

```text
status: READY_FOR_REVIEW
starting_head: 22fee3771118f6b8ca80e5ccd2ec62272c66a8a5
fixture_hash_check: 18/18 frozen fixture hashes matched section 3.3; no fixture files were modified
catalog_preflight: design, design + parameter_top, closure + parameter_top, project-root + parameter_top, single-file, single-filelist, positional + positional_top, and all four negative inputs reported catalog parse_errors=0 and semantic_errors=0; top overlays reported 0/0 where present
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters -v`
baseline_result: exit 1 as expected; T041/T042's 28 tests passed, then `tests.test_symbol_graph_parameters` import failed with `ModuleNotFoundError`; `Ran 29 tests in 0.253s` and `FAILED (errors=1)`
changed_files: none at start; workspace clean; only T043 allowed files may be changed
revision_after_main_agent_return: added the section 10.12 `source_catalog._compile_view` monkeypatch to the existing legacy-path regression test; no tests, fixtures, or behaviors were added
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_genvars.py tests/test_symbol_graph_parameters.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T043_symbol_graph_parameters.md`
results:
  - combined unittest: exit 0; `Ran 46 tests` and `OK`
  - py_compile: exit 0; no output
  - diff check: exit 0; no output
  - status guard: exit 0; output `- 状态：`READY_FOR_REVIEW``
schema_or_behavior: added only `parameters`; section 10.12 now blocks `_compile_view` and all five legacy parameter helpers; full no-top is 12/27/39 with graph audit 20/20/33/53; closure/project top is 10/25/35 with audit 17/17/31/48; single is 2/2/4 with audit 3/3/2/5; positional is 1/0/1 with audit 1/1/0/1; provenance counts are semantic 10, dimension 12, generate 2, named override 3; T042 whole-graph oracles were updated only as authorized
deviations_or_blockers: none
boundaries: no type/package/class/interface/$unit parameters, parameter arrays/strings/reals/structs, defparam support, macro fallback, lexical scan, second compilation, legacy collector/helper, category policy, mapping, rewrite, gate, decrypt, or Formal
cleanup_candidates: none in T043
formal_verification: N/A - no rewritten RTL is produced
review_request: READY_FOR_REVIEW; one complete review request after all 18 T043 behaviors; no main-agent acceptance record
```

## 16. READY_FOR_REVIEW 条件

- 第10节18项行为全部覆盖，三模块共46 tests通过；
- 第14节四条命令全部退出0；
- diff只包含第11节允许文件，18个fixture hash不变；
- 12/27/39、10/25/35、2/2/4和positional oracle准确；
- 四种provenance、三种ABI、support/reason和同名owner完整；
- genvar iteration parameter未进入parameters，T041/T042有效不变量未回退；
- 六项负例按第9节whole-graph fail-closed；
- 没有第二次compile、legacy helper、全文件文本搜索、fixture特判或模式专用graph；
- Formal准确记录为N/A；状态严格为`READY_FOR_REVIEW`。

## 17. 主 Agent验收边界

主 Agent只执行：

1. 审查starting HEAD、允许文件和fixture hash；
2. 审查18项测试由公开API和真实SourceCatalog触发；
3. 审查iteration parameter排除、四种provenance和named override owner证据；
4. 审查ABI classification只读取共享ModuleOwner，不遍历第二套top inventory；
5. 在状态仍为`READY_FOR_REVIEW`时独立运行第14节四条命令；
6. 全部通过后写验收记录并设置`ACCEPTED`。

退回必须引用本合同具体条款或测试项。验收时新想到但未冻结的parameter形状记录为后续边界，不能
新增为T043阻塞条件。

## 18. 主 Agent合同冻结记录（2026-07-23）

```text
status: READY
baseline_commit: 8edfa06
decision: complete R2-D parameter graph and ABI classification before starting RewritePolicy
frozen_inputs: 18 files; hashes and byte sizes recorded in section 3.3
preflight: all inputs catalog 0/0; Parameter/TypeParameter/genvar-iteration/dimension/generate/override/defparam API shapes independently inspected
positive_oracles: full 12/27/39; closure 10/25/35; single 2/2/4; positional 1/0/1; exact provenance and whole-graph audits in section 8
negative_matrix: macro declaration, macro reference, type parameter, defparam, range corruption, owner mismatch
superseded_tests: only T042 whole-graph/category/top-all-symbol comparison; genvar-specific behavior remains frozen
acceptance: exactly four commands; 46 tests; no Formal or hidden probes
formal_verification: N/A - no rewritten RTL is produced
```

## 19. 主 Agent首次验收记录（2026-07-23）

```text
status: IN_PROGRESS / NOT_ACCEPTED
reviewed_head: 22fee3771118f6b8ca80e5ccd2ec62272c66a8a5
independent_commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_genvars.py tests/test_symbol_graph_parameters.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：\`READY_FOR_REVIEW\`' docs/tasks/T043_symbol_graph_parameters.md`
independent_results: all four exited 0 before return; unittest ran 46 tests in 0.532s and reported OK
contract_finding:
  - section 10 item 12 requires the existing no-recompile test to monkeypatch both the T040 `_compile_view` entry and every listed legacy parameter helper to fail immediately; `test_graph_reuses_catalog_and_does_not_call_legacy_parameter_paths` patches the five legacy helpers but never imports or patches `rtl_obfuscator.source_catalog._compile_view`
required_revision:
  - extend that existing test to patch `source_catalog._compile_view` with an immediate `AssertionError`, then rerun the unchanged four commands and restore `READY_FOR_REVIEW`
scope: test-only correction in `tests/test_symbol_graph_parameters.py` plus task status/execution record; no new test method, fixture, behavior, error code, implementation change or acceptance command
formal_verification: N/A - no rewritten RTL is produced
review_request: withdrawn until the single frozen section 10.12 guard is present
```

## 20. 主 Agent最终验收记录（2026-07-23）

```text
status: ACCEPTED
reviewed_head: 22fee3771118f6b8ca80e5ccd2ec62272c66a8a5
revision_review:
  - the existing section 10.12 regression now patches `source_catalog._compile_view` and all five frozen legacy parameter helpers to raise immediately
  - test count remains exactly 18 for T043; no fixture, behavior, implementation scope or acceptance command was added by the revision
independent_commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_genvars.py tests/test_symbol_graph_parameters.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：\`READY_FOR_REVIEW\`' docs/tasks/T043_symbol_graph_parameters.md`
independent_results:
  - unittest: exit 0; `Ran 46 tests in 0.520s`; `OK`
  - py_compile: exit 0; no output
  - diff check: exit 0; no output
  - READY_FOR_REVIEW guard: exit 0 before acceptance; exact status line matched
scope_review: only section 11 allowed files changed; all 18 frozen fixture files remain unchanged; no second compilation, legacy helper call, rewrite, mapping, gate, Formal or hidden acceptance input
formal_verification: N/A - no rewritten RTL is produced
decision: ACCEPTED
```
